use crate::control::{ControlClient, DesktopError, err};
use crate::engine::{EngineSnapshot, EngineSupervisor};
use crate::process::{Pipes, ProcessSpec, ProcessTree};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

/// Signal gives a link code a few minutes; link.py gives up after five.
const LINK_LIMIT: Duration = Duration::from_secs(310);

/// link.py deletes its QR image when it finishes; a killed helper can't, so do it here.
fn forget_link_code(root: &Path) {
    let _ = std::fs::remove_file(root.join("data").join("link").join("qr.png"));
}

fn should_start_on_launch(linked: bool, config: &Value) -> Result<bool, DesktopError> {
    let enabled = match config
        .get("desktop")
        .and_then(|desktop| desktop.get("start_engine_on_launch"))
    {
        None => true,
        Some(value) => value.as_bool().ok_or_else(|| err("invalid_config"))?,
    };
    Ok(linked && enabled)
}

pub struct DesktopState {
    pub root: PathBuf,
    pub control: ControlClient,
    pub engine: EngineSupervisor,
    link: Mutex<Option<ProcessTree>>,
    pub shutting_down: AtomicBool,
    launch_cancelled: AtomicBool,
    pub startup_error: Mutex<Option<DesktopError>>,
}
impl DesktopState {
    pub fn new(root: PathBuf) -> Result<Self, DesktopError> {
        Ok(Self {
            control: ControlClient::new(root.clone()),
            engine: EngineSupervisor::new(&root)?,
            root,
            link: Mutex::new(None),
            shutting_down: AtomicBool::new(false),
            launch_cancelled: AtomicBool::new(false),
            startup_error: Mutex::new(None),
        })
    }
    pub fn engine_action(&self, action: &str) -> Result<EngineSnapshot, DesktopError> {
        self.launch_cancelled.store(true, Ordering::Release);
        let result = self.engine_action_inner(action, false);
        if result.is_ok() {
            self.startup_error
                .lock()
                .unwrap_or_else(|p| p.into_inner())
                .take();
        }
        result
    }
    fn engine_action_inner(
        &self,
        action: &str,
        from_launch: bool,
    ) -> Result<EngineSnapshot, DesktopError> {
        if self.shutting_down.load(Ordering::Acquire) {
            return Err(err("runtime_closed"));
        }
        let mut link = self.link.lock().map_err(|_| err("link_failed"))?;
        if from_launch && self.launch_cancelled.load(Ordering::Acquire) {
            return self.engine.snapshot();
        }
        if link
            .as_mut()
            .is_some_and(|child| !matches!(child.try_wait(), Ok(None)))
        {
            link.take();
        }
        if action != "stop" && link.is_some() {
            return Err(err("link_active"));
        }
        let result = match action {
            "start" => self.engine.start(),
            "restart" => self.engine.restart(),
            "stop" => self.engine.stop(),
            _ => Err(err("invalid_params")),
        };
        if from_launch && result.is_err() {
            let _ = self.engine.stop();
        }
        result
    }

    pub fn link_signal(self: &Arc<Self>) -> Result<(), DesktopError> {
        self.launch_cancelled.store(true, Ordering::Release);
        if self.shutting_down.load(Ordering::Acquire) {
            return Err(err("runtime_closed"));
        }
        let mut link = self.link.lock().map_err(|_| err("link_failed"))?;
        if link
            .as_mut()
            .is_some_and(|child| matches!(child.try_wait(), Ok(None)))
        {
            return Ok(()); // already showing a code
        }
        link.take();
        if self.engine.snapshot()?.status != "stopped" {
            return Err(err("link_engine_running"));
        }
        crate::engine::receiver_available(&self.root)?;
        std::fs::create_dir_all(self.root.join("logs")).map_err(|_| err("link_failed"))?;
        let mut child = ProcessSpec::python(&self.root, "link.py")
            .spawn(Pipes::None)
            .map_err(|_| err("link_failed"))?;
        // Catch a missing runtime straight away (link.py's output is never read: it holds the link code).
        let start = Instant::now();
        while start.elapsed() < Duration::from_millis(300) {
            if let Some(status) = child.try_wait().map_err(|_| err("link_failed"))? {
                return if status.success() {
                    Ok(())
                } else {
                    Err(err("link_failed"))
                };
            }
            thread::sleep(Duration::from_millis(20));
        }
        let pid = child.id();
        *link = Some(child);
        let owner = self.clone();
        thread::Builder::new()
            .name("scribe-link-supervisor".into())
            .spawn(move || {
                loop {
                    thread::sleep(Duration::from_millis(250));
                    let mut link = owner.link.lock().unwrap_or_else(|p| p.into_inner());
                    let Some(child) = link.as_mut() else { break };
                    if child.id() != pid {
                        break;
                    }
                    if owner.shutting_down.load(Ordering::Acquire)
                        || start.elapsed() > LINK_LIMIT
                        || !matches!(child.try_wait(), Ok(None))
                    {
                        link.take();
                        forget_link_code(&owner.root);
                        break;
                    }
                }
            })
            .map_err(|_| {
                link.take();
                err("link_failed")
            })?;
        Ok(())
    }

    /// The link helper's progress, corrected when the helper is no longer running.
    pub fn link_status(&self) -> Result<Value, DesktopError> {
        let mut status = self.control.call("link.status", json!({}))?;
        let alive = self
            .link
            .lock()
            .map_err(|_| err("link_failed"))?
            .as_mut()
            .is_some_and(|child| matches!(child.try_wait(), Ok(None)));
        let state = status
            .get("state")
            .and_then(Value::as_str)
            .unwrap_or("idle");
        if !alive && matches!(state, "starting" | "waiting") {
            forget_link_code(&self.root);
            status = json!({"state":"failed","reason":"cancelled"});
        }
        Ok(status)
    }

    pub fn link_cancel(&self) -> Result<(), DesktopError> {
        self.link.lock().map_err(|_| err("link_failed"))?.take();
        forget_link_code(&self.root);
        Ok(())
    }

    pub fn shutdown(&self) {
        self.shutting_down.store(true, Ordering::Release);
        // Match engine_action/link_signal lock ordering, and never hold these across control I/O.
        if self
            .link
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .take()
            .is_some()
        {
            forget_link_code(&self.root);
        }
        self.engine.shutdown();
        self.control.shutdown();
    }
    /// Called once by app setup, never by constructors or test fixture creation.
    /// No config is written. Manual actions supersede this pending launch decision.
    pub fn start_on_launch(&self) -> Option<DesktopError> {
        let result: Result<(), DesktopError> = (|| {
            if self.launch_cancelled.load(Ordering::Acquire)
                || self.shutting_down.load(Ordering::Acquire)
            {
                return Ok(());
            }
            let python = self.control.call("state.get", json!({}))?;
            let linked = python
                .get("linked")
                .and_then(Value::as_bool)
                .ok_or_else(|| err("invalid_response"))?;
            let unlinked = python
                .get("unlinked")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            if !linked || unlinked {
                return Ok(());
            }
            let config = self.control.call("config.get", json!({}))?;
            if !should_start_on_launch(linked, &config)? {
                return Ok(());
            }
            let interpreter = crate::runtime::python_executable(&self.root);
            if !interpreter.is_absolute() || !interpreter.is_file() {
                return Err(err("runtime_missing"));
            }
            self.engine_action_inner("start", true)?;
            Ok(())
        })();
        if let Err(error) = result
            && !self.launch_cancelled.load(Ordering::Acquire)
            && !self.shutting_down.load(Ordering::Acquire)
        {
            *self.startup_error.lock().unwrap_or_else(|p| p.into_inner()) = Some(error.clone());
            return Some(error);
        }
        None
    }
}
impl Drop for DesktopState {
    fn drop(&mut self) {
        self.shutdown();
    }
}

#[cfg(test)]
mod launch_tests {
    use super::*;
    #[test]
    fn launch_defaults_to_linked_only_and_honours_explicit_opt_out() {
        assert!(should_start_on_launch(true, &json!({})).unwrap());
        assert!(!should_start_on_launch(false, &json!({})).unwrap());
        assert!(
            !should_start_on_launch(true, &json!({"desktop":{"start_engine_on_launch":false}}))
                .unwrap()
        );
        assert!(
            should_start_on_launch(true, &json!({"desktop":{"start_engine_on_launch":"yes"}}))
                .is_err()
        );
    }

    fn startup_fixture(
        linked: bool,
        enabled: bool,
        delay: f32,
    ) -> (tempfile::TempDir, Arc<DesktopState>) {
        let root = tempfile::tempdir().unwrap();
        let script = format!(
            "import sys,json,time,pathlib\nfor line in sys.stdin:\n r=json.loads(line)\n pathlib.Path('requested').write_text('yes')\n time.sleep({delay})\n result={{'linked':{linked},'unlinked':False}} if r['method']=='state.get' else {{'desktop':{{'start_engine_on_launch':{enabled}}}}}\n print(json.dumps({{'id':r['id'],'ok':True,'result':result}}),flush=True)\n",
            linked = if linked { "True" } else { "False" },
            enabled = if enabled { "True" } else { "False" }
        );
        std::fs::write(root.path().join("control_server.py"), script).unwrap();
        std::fs::write(
            root.path().join("transcriber.py"),
            "from pathlib import Path\nPath('unexpected-engine').write_text('bad')",
        )
        .unwrap();
        let state = Arc::new(DesktopState::new(root.path().into()).unwrap());
        (root, state)
    }
    #[test]
    fn startup_skips_unlinked_opted_out_or_missing_local_runtime_without_running_engine() {
        for (linked, enabled, missing_runtime) in [
            (false, true, false),
            (true, false, false),
            (true, true, true),
        ] {
            let (root, state) = startup_fixture(linked, enabled, 0.0);
            let error = state.start_on_launch();
            assert_eq!(
                error.map(|e| e.code),
                if missing_runtime {
                    Some("runtime_missing".into())
                } else {
                    None
                }
            );
            assert_eq!(state.engine.snapshot().unwrap().status, "stopped");
            assert!(!root.path().join("unexpected-engine").exists());
        }
    }
    #[test]
    fn manual_stop_cancels_in_flight_launch_decision() {
        let (root, state) = startup_fixture(true, true, 0.2);
        let background = state.clone();
        let worker = thread::spawn(move || background.start_on_launch());
        let deadline = Instant::now() + Duration::from_secs(5);
        while !root.path().join("requested").exists() {
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(10));
        }
        state.engine_action("stop").unwrap();
        assert!(worker.join().unwrap().is_none());
        assert_eq!(state.engine.snapshot().unwrap().status, "stopped");
        assert!(!root.path().join("unexpected-engine").exists());
    }
    #[test]
    fn a_dead_link_helper_is_reported_as_cancelled() {
        let root = tempfile::tempdir().unwrap();
        std::fs::write(
            root.path().join("control_server.py"),
            "import sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n print(json.dumps({'id':r['id'],'ok':True,'result':{'state':'waiting','qr':'data:image/png;base64,AA=='}}),flush=True)\n",
        )
        .unwrap();
        let qr = root.path().join("data/link/qr.png");
        std::fs::create_dir_all(qr.parent().unwrap()).unwrap();
        std::fs::write(&qr, b"stale code").unwrap();
        let state = DesktopState::new(root.path().into()).unwrap();
        let status = state.link_status().unwrap();
        assert!(!qr.exists(), "a stale link code must not stay on disk");
        assert_eq!(status["state"], "failed");
        assert_eq!(status["reason"], "cancelled");
        assert!(status.get("qr").is_none());
    }
}
