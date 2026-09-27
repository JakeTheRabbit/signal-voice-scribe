//! Owned child trees. Dropping a child terminates its descendants, including signal-cli.
use crate::control::{DesktopError, err};
use crate::runtime::python_executable;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::time::{Duration, Instant};

/// Environment changes that undo an AppImage's AppRun for a child process: every entry it
/// added under `appdir` (PYTHONHOME, PYTHONPATH, LD_LIBRARY_PATH, PATH, the GTK variables…)
/// goes, and so does its PYTHONDONTWRITEBYTECODE. `None` removes the variable.
fn leave_appimage(
    appdir: &Path,
    vars: impl IntoIterator<Item = (OsString, OsString)>,
) -> Vec<(OsString, Option<OsString>)> {
    let mut changes = vec![(OsString::from("PYTHONDONTWRITEBYTECODE"), None)];
    for (key, value) in vars {
        let entries: Vec<PathBuf> = std::env::split_paths(&value).collect();
        if !entries.iter().any(|entry| entry.starts_with(appdir)) {
            continue;
        }
        let kept = entries
            .into_iter()
            .filter(|entry| !entry.as_os_str().is_empty() && !entry.starts_with(appdir));
        let joined = std::env::join_paths(kept)
            .ok()
            .filter(|joined| !joined.is_empty());
        changes.push((key, joined));
    }
    changes
}

/// Give `command` the environment it would have outside the AppImage (no-op elsewhere).
/// Otherwise Python finds the bundle's PYTHONHOME instead of its own standard library.
pub fn outside_appimage(command: &mut Command) -> &mut Command {
    if let Some(appdir) = std::env::var_os("APPDIR") {
        for (key, value) in leave_appimage(Path::new(&appdir), std::env::vars_os()) {
            match value {
                Some(value) => command.env(key, value),
                None => command.env_remove(key),
            };
        }
    }
    command
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Pipes {
    /// No pipes (the link helper).
    None,
    /// stdin only: closing it asks the child to stop cleanly (the engine).
    StopSignal,
    /// stdin and stdout for the JSON-lines control protocol.
    Protocol,
}

#[derive(Clone)]
pub struct ProcessSpec {
    pub program: PathBuf,
    pub args: Vec<OsString>,
    pub cwd: PathBuf,
    pub env: Vec<(String, OsString)>,
}
impl ProcessSpec {
    pub fn python(root: &Path, script: &str) -> Self {
        Self {
            program: python_executable(root),
            args: vec!["-u".into(), root.join(script).into()],
            cwd: root.to_owned(),
            env: Vec::new(),
        }
    }
    pub fn with_env(mut self, key: &str, value: impl Into<OsString>) -> Self {
        self.env.push((key.into(), value.into()));
        self
    }
    pub fn spawn(&self, pipes: Pipes) -> Result<ProcessTree, DesktopError> {
        let mut command = Command::new(&self.program);
        outside_appimage(&mut command)
            .args(&self.args)
            .current_dir(&self.cwd)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8")
            // The desktop always uses its own runtime folder for data.
            .env_remove("SIGNAL_SCRIBE_HOME")
            .stdin(if pipes == Pipes::None {
                Stdio::null()
            } else {
                Stdio::piped()
            })
            .stdout(if pipes == Pipes::Protocol {
                Stdio::piped()
            } else {
                Stdio::null()
            })
            .stderr(Stdio::null());
        for (key, value) in &self.env {
            command.env(key, value);
        }
        ProcessTree::spawn(command)
    }
}

pub struct ProcessTree {
    pub child: Child,
    terminated: bool,
    #[cfg(windows)]
    job: windows_job::Job,
}
impl ProcessTree {
    fn spawn(mut command: Command) -> Result<Self, DesktopError> {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            // Suspend before Python executes so signal-cli cannot escape during startup.
            command.creation_flags(0x08000000 | 0x00000004); // CREATE_NO_WINDOW | CREATE_SUSPENDED
            let job = windows_job::Job::new()?;
            let mut child = command.spawn().map_err(|_| err("process_start_failed"))?;
            if let Err(error) = job.attach_and_resume(&child) {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
            Ok(Self {
                child,
                job,
                terminated: false,
            })
        }
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
            Ok(Self {
                child: command.spawn().map_err(|_| err("process_start_failed"))?,
                terminated: false,
            })
        }
    }
    pub fn id(&self) -> u32 {
        self.child.id()
    }
    pub fn try_wait(&mut self) -> Result<Option<ExitStatus>, DesktopError> {
        self.child
            .try_wait()
            .map_err(|_| err("process_state_failed"))
    }
    /// Close stdin (the child's cue to finish cleanly), wait up to `grace`, then terminate.
    pub fn stop(&mut self, grace: Duration) -> Result<(), DesktopError> {
        if self.terminated {
            return Ok(());
        }
        if self.child.stdin.take().is_some() {
            let deadline = Instant::now() + grace;
            while Instant::now() < deadline {
                if matches!(self.child.try_wait(), Ok(Some(_))) {
                    break;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
        }
        // Always end the whole tree: a clean Python exit must not leave signal-cli behind.
        self.terminate()
    }
    pub fn terminate(&mut self) -> Result<(), DesktopError> {
        if self.terminated {
            return Ok(());
        }
        #[cfg(windows)]
        self.job.terminate()?;
        #[cfg(unix)]
        {
            // Each child owns a fresh group; this never targets an unrelated process.
            let result = unsafe { libc::kill(-(self.child.id() as i32), libc::SIGKILL) };
            if result != 0 && std::io::Error::last_os_error().raw_os_error() != Some(libc::ESRCH) {
                return Err(err("process_stop_failed"));
            }
        }
        let _ = self.child.kill();
        self.child.wait().map_err(|_| err("process_stop_failed"))?;
        self.terminated = true;
        Ok(())
    }
}
impl Drop for ProcessTree {
    fn drop(&mut self) {
        let _ = self.terminate();
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[test]
    fn children_leave_the_appimage_environment() {
        let vars = [
            ("PYTHONHOME", "/apps/scribe/app/usr/"),
            ("PYTHONPATH", "/apps/scribe/app/usr/share/pyshared/:"),
            ("PATH", "/apps/scribe/app/usr/bin/:/usr/local/bin:/usr/bin"),
            (
                "LD_LIBRARY_PATH",
                "/apps/scribe/app/usr/lib/:/apps/scribe/app//usr/lib64",
            ),
            ("GTK_THEME", "Adwaita:light"),
            ("HOME", "/home/user"),
            ("NEIGHBOUR", "/apps/scribe/app-2/usr"),
        ]
        .map(|(key, value)| (OsString::from(key), OsString::from(value)));
        let changes = leave_appimage(Path::new("/apps/scribe/app"), vars);
        let change = |key: &str| {
            changes
                .iter()
                .find(|(k, _)| k == key)
                .map(|(_, value)| value.clone())
        };
        for removed in [
            "PYTHONHOME",
            "PYTHONPATH",
            "LD_LIBRARY_PATH",
            "PYTHONDONTWRITEBYTECODE",
        ] {
            assert_eq!(change(removed), Some(None), "{removed}");
        }
        assert_eq!(change("PATH"), Some(Some("/usr/local/bin:/usr/bin".into())));
        for untouched in ["GTK_THEME", "HOME", "NEIGHBOUR"] {
            assert_eq!(change(untouched), None, "{untouched}");
        }
    }
}

#[cfg(windows)]
mod windows_job {
    use super::*;
    use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
    use windows_sys::Win32::Foundation::{HANDLE, INVALID_HANDLE_VALUE};
    use windows_sys::Win32::System::Diagnostics::ToolHelp::*;
    use windows_sys::Win32::System::JobObjects::*;
    use windows_sys::Win32::System::Threading::{OpenThread, ResumeThread, THREAD_SUSPEND_RESUME};
    pub struct Job(OwnedHandle);
    impl Job {
        pub fn new() -> Result<Self, DesktopError> {
            unsafe {
                let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if handle.is_null() {
                    return Err(err("process_start_failed"));
                }
                let job = Self(OwnedHandle::from_raw_handle(handle));
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                if SetInformationJobObject(
                    job.handle(),
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const _,
                    std::mem::size_of_val(&info) as u32,
                ) == 0
                {
                    return Err(err("process_start_failed"));
                }
                Ok(job)
            }
        }
        fn handle(&self) -> HANDLE {
            self.0.as_raw_handle()
        }
        pub fn attach_and_resume(&self, child: &Child) -> Result<(), DesktopError> {
            unsafe {
                if AssignProcessToJobObject(self.handle(), child.as_raw_handle()) == 0 {
                    return Err(err("process_start_failed"));
                }
                let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
                if snapshot == INVALID_HANDLE_VALUE {
                    return Err(err("process_start_failed"));
                }
                let snapshot = OwnedHandle::from_raw_handle(snapshot);
                let mut entry: THREADENTRY32 = std::mem::zeroed();
                entry.dwSize = std::mem::size_of::<THREADENTRY32>() as u32;
                let mut found = Thread32First(snapshot.as_raw_handle(), &mut entry);
                while found != 0 {
                    if entry.th32OwnerProcessID == child.id() {
                        let thread = OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID);
                        if thread.is_null() {
                            return Err(err("process_start_failed"));
                        }
                        let thread = OwnedHandle::from_raw_handle(thread);
                        if ResumeThread(thread.as_raw_handle()) == u32::MAX {
                            return Err(err("process_start_failed"));
                        }
                        return Ok(());
                    }
                    found = Thread32Next(snapshot.as_raw_handle(), &mut entry);
                }
                Err(err("process_start_failed"))
            }
        }
        pub fn terminate(&self) -> Result<(), DesktopError> {
            if unsafe { TerminateJobObject(self.handle(), 1) } == 0 {
                return Err(err("process_stop_failed"));
            }
            Ok(())
        }
    }
}
