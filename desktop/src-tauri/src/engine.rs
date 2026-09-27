use crate::control::{DesktopError, err};
use crate::process::{Pipes, ProcessSpec, ProcessTree};
use serde::Serialize;
use std::fs::{File, OpenOptions};
use std::path::Path;
use std::sync::{Arc, Condvar, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct EngineSnapshot {
    pub running: bool,
    pub pid: Option<u32>,
    pub status: &'static str,
    /// Exit code of the last engine that stopped by itself (2 = needs the user).
    pub exit_code: Option<i32>,
}

/// The engine exits with these when restarting would not help (see scribe/engine.py).
const EXIT_NEEDS_USER: i32 = 2;
const EXIT_BUSY: i32 = 3;
/// How long the engine gets to finish cleanly after its stdin is closed.
const STOP_GRACE: Duration = Duration::from_secs(10);

#[derive(Clone, Copy)]
struct Policy {
    first_delay: Duration,
    max_delay: Duration,
    stable_after: Duration,
    poll: Duration,
}
impl Default for Policy {
    fn default() -> Self {
        Self {
            first_delay: Duration::from_secs(1),
            max_delay: Duration::from_secs(30),
            stable_after: Duration::from_secs(60),
            poll: Duration::from_millis(200),
        }
    }
}
struct Inner {
    child: Option<ProcessTree>,
    desired: bool,
    closed: bool,
    status: &'static str,
    failures: u32,
    retry_at: Option<Instant>,
    started_at: Option<Instant>,
    lease: Option<File>,
    exit_code: Option<i32>,
}
impl Default for Inner {
    fn default() -> Self {
        Self {
            child: None,
            desired: false,
            closed: false,
            status: "stopped",
            failures: 0,
            retry_at: None,
            started_at: None,
            lease: None,
            exit_code: None,
        }
    }
}

pub struct EngineSupervisor {
    shared: Arc<(Mutex<Inner>, Condvar)>,
    spec: ProcessSpec,
    policy: Policy,
    worker: Mutex<Option<JoinHandle<()>>>,
}
impl EngineSupervisor {
    pub fn new(root: &Path) -> Result<Self, DesktopError> {
        Self::with_spec(
            ProcessSpec::python(root, "transcriber.py").with_env("SIGNAL_SCRIBE_PARENT_PIPE", "1"),
            Policy::default(),
        )
    }
    fn with_spec(spec: ProcessSpec, policy: Policy) -> Result<Self, DesktopError> {
        let shared = Arc::new((Mutex::new(Inner::default()), Condvar::new()));
        let background = shared.clone();
        let process_spec = spec.clone();
        let worker = thread::Builder::new()
            .name("scribe-engine-supervisor".into())
            .spawn(move || {
                let (lock, wake) = &*background;
                let mut inner = lock.lock().unwrap_or_else(|p| p.into_inner());
                while !inner.closed {
                    refresh(&mut inner, policy);
                    if inner.desired
                        && inner.child.is_none()
                        && inner.retry_at.is_some_and(|at| Instant::now() >= at)
                    {
                        let _ = launch(&mut inner, &process_spec, policy);
                    }
                    inner = wake
                        .wait_timeout(inner, policy.poll)
                        .unwrap_or_else(|p| p.into_inner())
                        .0;
                }
            })
            .map_err(|_| err("engine_start_failed"))?;
        Ok(Self {
            shared,
            spec,
            policy,
            worker: Mutex::new(Some(worker)),
        })
    }
    pub fn snapshot(&self) -> Result<EngineSnapshot, DesktopError> {
        let mut inner = self
            .shared
            .0
            .lock()
            .map_err(|_| err("engine_state_failed"))?;
        refresh(&mut inner, self.policy);
        Ok(snapshot(&inner))
    }
    pub fn start(&self) -> Result<EngineSnapshot, DesktopError> {
        let mut inner = self
            .shared
            .0
            .lock()
            .map_err(|_| err("engine_state_failed"))?;
        self.start_locked(&mut inner)
    }
    fn start_locked(&self, inner: &mut Inner) -> Result<EngineSnapshot, DesktopError> {
        if inner.closed {
            return Err(err("runtime_closed"));
        }
        refresh(inner, self.policy);
        if inner.desired {
            return Ok(snapshot(inner));
        }
        // The OS releases this lock on crashes. Never unlink the file while it is locked.
        std::fs::create_dir_all(self.spec.cwd.join("data")).map_err(|_| err("engine_owned"))?;
        let lease = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(self.spec.cwd.join("data/.desktop-engine.lock"))
            .map_err(|_| err("engine_owned"))?;
        lease.try_lock().map_err(|_| err("engine_owned"))?;
        inner.lease = Some(lease);
        inner.desired = true;
        inner.failures = 0;
        inner.exit_code = None;
        let result = launch(inner, &self.spec, self.policy);
        self.shared.1.notify_all();
        result?;
        Ok(snapshot(inner))
    }
    pub fn stop(&self) -> Result<EngineSnapshot, DesktopError> {
        let mut inner = self
            .shared
            .0
            .lock()
            .map_err(|_| err("engine_state_failed"))?;
        stop_locked(&mut inner)?;
        self.shared.1.notify_all();
        Ok(snapshot(&inner))
    }
    pub fn restart(&self) -> Result<EngineSnapshot, DesktopError> {
        let mut inner = self
            .shared
            .0
            .lock()
            .map_err(|_| err("engine_state_failed"))?;
        stop_locked(&mut inner)?;
        self.start_locked(&mut inner)
    }
    pub fn shutdown(&self) {
        {
            let mut inner = self.shared.0.lock().unwrap_or_else(|p| p.into_inner());
            inner.closed = true;
            let _ = stop_locked(&mut inner);
            self.shared.1.notify_all();
        }
        if let Some(worker) = self.worker.lock().unwrap_or_else(|p| p.into_inner()).take() {
            let _ = worker.join();
        }
    }
}
impl Drop for EngineSupervisor {
    fn drop(&mut self) {
        self.shutdown();
    }
}

fn snapshot(inner: &Inner) -> EngineSnapshot {
    let running = inner.child.is_some() && inner.status != "unknown";
    EngineSnapshot {
        running,
        pid: inner.child.as_ref().map(ProcessTree::id),
        status: inner.status,
        exit_code: inner.exit_code,
    }
}
fn schedule_retry(inner: &mut Inner, policy: Policy) {
    let multiplier = 1_u32 << inner.failures.min(10);
    let delay = policy
        .first_delay
        .saturating_mul(multiplier)
        .min(policy.max_delay);
    inner.failures = inner.failures.saturating_add(1);
    inner.retry_at = Some(Instant::now() + delay);
    inner.status = "backoff";
}
fn refresh(inner: &mut Inner, policy: Policy) {
    let Some(child) = inner.child.as_mut() else {
        return;
    };
    match child.try_wait() {
        Ok(None) => {
            if inner.status != "stop_failed" {
                inner.status = "running";
            }
            if inner
                .started_at
                .is_some_and(|at| at.elapsed() >= policy.stable_after)
            {
                inner.failures = 0;
            }
        }
        Ok(Some(exit)) => {
            // Even if Python exited itself, terminate any signal-cli descendants before restarting.
            inner.child.take();
            inner.started_at = None;
            inner.exit_code = exit.code();
            let hopeless = matches!(exit.code(), Some(EXIT_NEEDS_USER | EXIT_BUSY));
            if inner.desired && !hopeless {
                schedule_retry(inner, policy);
            } else {
                // Not linked, unlinked, a broken install or another engine: restarting won't help.
                inner.desired = false;
                inner.retry_at = None;
                inner.status = "stopped";
                inner.lease.take();
            }
        }
        Err(_) => {
            inner.status = "unknown";
        } // Never start a second child if liveness is uncertain.
    }
}
fn launch(inner: &mut Inner, spec: &ProcessSpec, policy: Policy) -> Result<(), DesktopError> {
    if inner.child.is_some() {
        return Ok(());
    }
    if let Err(error) = receiver_available(&spec.cwd) {
        inner.desired = false;
        inner.retry_at = None;
        inner.lease.take();
        inner.status = "stopped";
        return Err(error);
    }
    match spec.spawn(Pipes::StopSignal) {
        Ok(child) => {
            inner.child = Some(child);
            inner.started_at = Some(Instant::now());
            inner.retry_at = None;
            inner.status = "running";
            Ok(())
        }
        Err(_) => {
            schedule_retry(inner, policy);
            Err(err("engine_start_failed"))
        }
    }
}
fn stop_locked(inner: &mut Inner) -> Result<(), DesktopError> {
    inner.desired = false;
    inner.retry_at = None;
    inner.failures = 0;
    if let Some(child) = inner.child.as_mut()
        && child.stop(STOP_GRACE).is_err()
    {
        inner.status = "stop_failed";
        return Err(err("engine_stop_failed"));
    }
    inner.child.take();
    inner.started_at = None;
    inner.lease.take();
    inner.status = "stopped";
    Ok(())
}

/// Probe and CLOSE before spawn. Python owns this lease for the actual receiver
/// lifetime and closes the TOCTOU gap. An empty lockfile is valid; never unlink it.
pub fn receiver_available(root: &Path) -> Result<(), DesktopError> {
    std::fs::create_dir_all(root.join("data")).map_err(|_| err("receiver_unavailable"))?;
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(root.join("data/.receiver.lock"))
        .map_err(|_| err("receiver_unavailable"))?;
    #[cfg(windows)]
    file.try_lock().map_err(|_| err("receiver_busy"))?; // Overlaps Python's byte-zero msvcrt lock.
    #[cfg(unix)]
    {
        use std::os::fd::AsRawFd;
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
            return Err(err("receiver_busy"));
        }
    }
    drop(file);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn direct_python_receiver_byte_zero_lease_blocks_native_start() {
        let (root, engine) = fixture("import time\ntime.sleep(60)\n");
        std::fs::create_dir(root.path().join("data")).unwrap();
        std::fs::write(root.path().join("receiver.py"), "import os,time,pathlib\nf=os.fdopen(os.open('data/.receiver.lock',os.O_RDWR|os.O_CREAT,0o600),'r+b');f.seek(0)\nif os.name=='nt':\n import msvcrt\n msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)\nelse:\n import fcntl\n fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)\npathlib.Path('receiver-ready').write_text('yes')\ntime.sleep(60)\n").unwrap();
        let mut receiver = ProcessSpec::python(root.path(), "receiver.py")
            .spawn(Pipes::None)
            .unwrap();
        wait_until(|| root.path().join("receiver-ready").exists());
        assert_eq!(engine.start().unwrap_err().code, "receiver_busy");
        assert!(!engine.snapshot().unwrap().running);
        receiver.terminate().unwrap();
        assert!(engine.start().unwrap().running);
        engine.stop().unwrap();
    }
    fn fixture(script: &str) -> (tempfile::TempDir, EngineSupervisor) {
        let root = tempfile::tempdir().unwrap();
        std::fs::write(root.path().join("transcriber.py"), script).unwrap();
        let engine = EngineSupervisor::with_spec(
            ProcessSpec::python(root.path(), "transcriber.py"),
            Policy {
                first_delay: Duration::from_millis(250),
                max_delay: Duration::from_millis(700),
                stable_after: Duration::from_secs(2),
                poll: Duration::from_millis(10),
            },
        )
        .unwrap();
        (root, engine)
    }
    fn wait_until(mut condition: impl FnMut() -> bool) {
        let deadline = Instant::now() + Duration::from_secs(5);
        while !condition() {
            assert!(Instant::now() < deadline, "fixture condition timed out");
            thread::sleep(Duration::from_millis(10));
        }
    }
    #[test]
    fn idle_start_is_explicit_and_duplicate_starts_keep_same_pid() {
        let (root, engine) = fixture(
            "import time,pathlib\npathlib.Path('started').write_text('yes')\ntime.sleep(60)\n",
        );
        assert_eq!(
            engine.snapshot().unwrap(),
            EngineSnapshot {
                running: false,
                pid: None,
                status: "stopped",
                exit_code: None
            }
        );
        thread::sleep(Duration::from_millis(100));
        assert!(!root.path().join("started").exists());
        let first = engine.start().unwrap();
        let second = engine.start().unwrap();
        assert_eq!(first.pid, second.pid);
        assert!(first.running);
        assert_eq!(
            engine.stop().unwrap(),
            EngineSnapshot {
                running: false,
                pid: None,
                status: "stopped",
                exit_code: None
            }
        );
    }
    #[test]
    fn process_death_is_truthful_then_supervised_with_backoff() {
        let (root, engine) =
            fixture("from pathlib import Path\nwith Path('starts').open('a') as f: f.write('x')\n");
        engine.start().unwrap();
        wait_until(|| engine.snapshot().unwrap().status == "backoff");
        let dead = engine.snapshot().unwrap();
        assert!(!dead.running);
        assert_eq!(dead.pid, None);
        assert_eq!(
            std::fs::read_to_string(root.path().join("starts")).unwrap(),
            "x"
        );
        wait_until(|| {
            std::fs::read_to_string(root.path().join("starts"))
                .unwrap_or_default()
                .len()
                >= 2
        });
        engine.stop().unwrap();
        let count = std::fs::read_to_string(root.path().join("starts")).unwrap();
        thread::sleep(Duration::from_millis(800));
        assert_eq!(
            std::fs::read_to_string(root.path().join("starts")).unwrap(),
            count
        );
        assert_eq!(engine.snapshot().unwrap().status, "stopped");
    }
    #[test]
    fn stop_during_backoff_cancels_restart_and_shutdown_is_terminal() {
        let (root, engine) =
            fixture("from pathlib import Path\nwith Path('starts').open('a') as f: f.write('x')\n");
        engine.start().unwrap();
        wait_until(|| engine.snapshot().unwrap().status == "backoff");
        engine.stop().unwrap();
        thread::sleep(Duration::from_millis(800));
        assert_eq!(
            std::fs::read_to_string(root.path().join("starts")).unwrap(),
            "x"
        );
        engine.shutdown();
        assert_eq!(engine.start().unwrap_err().code, "runtime_closed");
    }
    #[test]
    fn two_supervisors_cannot_own_the_same_runtime() {
        let (root, first) = fixture("import time\ntime.sleep(60)\n");
        let second = EngineSupervisor::new(root.path()).unwrap();
        first.start().unwrap();
        assert_eq!(second.start().unwrap_err().code, "engine_owned");
        first.stop().unwrap();
        assert!(second.start().unwrap().running);
        second.stop().unwrap();
    }
    #[test]
    fn restart_replaces_one_child_and_spawn_failure_can_be_stopped() {
        let (_root, engine) = fixture("import time\ntime.sleep(60)\n");
        let first = engine.start().unwrap();
        let second = engine.restart().unwrap();
        assert_ne!(first.pid, second.pid);
        engine.shutdown();
        assert!(!engine.snapshot().unwrap().running);
        let root = tempfile::tempdir().unwrap();
        let spec = ProcessSpec {
            program: root.path().join("missing-python"),
            args: vec![],
            cwd: root.path().into(),
            env: vec![],
        };
        let failed = EngineSupervisor::with_spec(spec, Policy::default()).unwrap();
        assert_eq!(failed.start().unwrap_err().code, "engine_start_failed");
        assert_eq!(failed.snapshot().unwrap().status, "backoff");
        assert_eq!(failed.stop().unwrap().status, "stopped");
    }
    #[test]
    fn stop_kills_descendant_and_its_inherited_handles() {
        let (root, engine) = fixture(
            "import subprocess,sys,time,pathlib\np=subprocess.Popen([sys.executable,'-c',\"import time,pathlib; pathlib.Path('grandchild-ready').write_text('yes'); time.sleep(60); pathlib.Path('escaped').write_text('bad')\"])\npathlib.Path('grandchild-pid').write_text(str(p.pid))\ntime.sleep(60)\n",
        );
        engine.start().unwrap();
        wait_until(|| root.path().join("grandchild-ready").exists());
        let pid: u32 = std::fs::read_to_string(root.path().join("grandchild-pid"))
            .unwrap()
            .parse()
            .unwrap();
        #[cfg(windows)]
        let handle = unsafe {
            use std::os::windows::io::{FromRawHandle, OwnedHandle};
            let handle = windows_sys::Win32::System::Threading::OpenProcess(0x00100000, 0, pid);
            assert!(!handle.is_null());
            OwnedHandle::from_raw_handle(handle)
        };
        engine.stop().unwrap();
        #[cfg(windows)]
        {
            use std::os::windows::io::AsRawHandle;
            assert_eq!(
                unsafe {
                    windows_sys::Win32::System::Threading::WaitForSingleObject(
                        handle.as_raw_handle(),
                        3000,
                    )
                },
                0
            );
        }
        #[cfg(unix)]
        wait_until(|| unsafe { libc::kill(pid as i32, 0) } != 0);
        assert!(!root.path().join("escaped").exists());
    }
    #[test]
    fn needs_user_exit_is_not_restarted() {
        let (root, engine) = fixture(
            "from pathlib import Path
with Path('starts').open('a') as f: f.write('x')
raise SystemExit(2)
",
        );
        engine.start().unwrap();
        wait_until(|| engine.snapshot().unwrap().exit_code == Some(2));
        thread::sleep(Duration::from_millis(800));
        let snapshot = engine.snapshot().unwrap();
        assert_eq!(snapshot.status, "stopped");
        assert!(!snapshot.running);
        assert_eq!(
            std::fs::read_to_string(root.path().join("starts")).unwrap(),
            "x"
        );
        // The ownership lease was released, so a later start works.
        assert!(engine.start().is_ok());
        engine.stop().unwrap();
    }
    #[test]
    fn stop_lets_the_engine_finish_cleanly_first() {
        let (root, engine) = fixture(
            "import sys,pathlib
pathlib.Path('ready').write_text('yes')
sys.stdin.read()
pathlib.Path('clean-exit').write_text('yes')
",
        );
        engine.start().unwrap();
        wait_until(|| root.path().join("ready").exists());
        engine.stop().unwrap();
        assert!(root.path().join("clean-exit").exists());
    }
}
