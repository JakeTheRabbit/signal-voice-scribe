use crate::process::{Pipes, ProcessSpec, ProcessTree};
use serde::Serialize;
use serde_json::{Value, json};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::sync::{Mutex, TryLockError, mpsc};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_REQUEST: usize = 1024 * 1024;
const MAX_RESPONSE: u64 = 64 * 1024 * 1024;

#[derive(Clone, Debug, Serialize, thiserror::Error)]
#[error("{message}")]
pub struct DesktopError {
    pub code: String,
    pub message: String,
}

// Never forward arbitrary Python text, paths, tracebacks, QR codes or tokens.
pub fn err(code: &str) -> DesktopError {
    let message = match code {
        "control_timeout" => {
            "The operation timed out; its outcome may be unknown. Refresh before trying again."
        }
        "root_unavailable" | "invalid_root_argument" => {
            "Signal Scribe can't find its install folder. Run the installer again, or start it with --root <install folder>."
        }
        "runtime_closed" => "Signal Scribe is shutting down.",
        "invalid_response" | "mismatched_response" => {
            "The background service returned an invalid response."
        }
        "control_unavailable" | "control_failed" => {
            "The background service is not responding. Run the installer again if this continues."
        }
        "invalid_params" => "The request was invalid.",
        "engine_start_failed" | "engine_owned" => {
            "The transcription engine could not start. Another copy of Signal Scribe may be running."
        }
        "engine_stop_failed" | "process_stop_failed" => "The engine could not be stopped safely.",
        "link_failed" => {
            "Linking could not start. Run the installer again to repair Java and signal-cli."
        }
        "link_active" => "Finish or cancel linking before starting the engine.",
        "link_engine_running" => "Stop the engine before linking Signal.",
        "media_unavailable" => "The audio was not kept or has expired.",
        "media_too_large" => "The audio is larger than 16 MB and can't be played here.",
        "path_denied" => "That file is outside Signal Scribe's history folder.",
        "config_unavailable" => {
            "Settings could not be read. Fix or delete config.json to restore defaults."
        }
        "invalid_config" => "One of the settings is invalid.",
        "config_write_failed" => {
            "Settings could not be saved. Check permissions and free disk space."
        }
        "receiver_busy" => {
            "Signal Scribe is already running for this install (maybe in a terminal). Stop it first."
        }
        "receiver_unavailable" => "The data folder can't be written. Check its permissions.",
        "runtime_missing" => "Python for Signal Scribe is missing. Run the installer again.",
        "autostart_unavailable" => "Start at login is only available in the desktop app.",
        "autostart_failed" => "Start at login could not be changed.",
        "open_failed" => "The folder could not be opened.",
        "method_not_allowed" => "This version of the background service doesn't support that.",
        _ => "The operation could not be completed.",
    };
    DesktopError {
        code: code.into(),
        message: message.into(),
    }
}

/// Validation messages name a setting and its allowed values; pass those through.
fn safe_detail(message: &str) -> bool {
    !message.is_empty()
        && message.len() <= 200
        && message
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || " .,:;-_()'".contains(c))
}

fn service_error(value: &Value) -> DesktopError {
    let code = value
        .get("code")
        .and_then(Value::as_str)
        .filter(|code| {
            matches!(
                *code,
                "invalid_params"
                    | "invalid_config"
                    | "config_unavailable"
                    | "config_write_failed"
                    | "media_unavailable"
                    | "media_too_large"
                    | "path_denied"
                    | "method_not_allowed"
                    | "autostart_unavailable"
                    | "autostart_failed"
            )
        })
        .unwrap_or("control_failed");
    let mut error = err(code);
    if code == "invalid_config"
        && let Some(detail) = value.get("message").and_then(Value::as_str)
        && safe_detail(detail)
    {
        error.message = format!("Invalid setting: {detail}.");
    }
    error
}

struct Work {
    request: Vec<u8>,
    reply: mpsc::SyncSender<Result<Vec<u8>, DesktopError>>,
}
struct Session {
    process: ProcessTree,
    input: Option<mpsc::SyncSender<Work>>,
    worker: Option<JoinHandle<()>>,
}

/// What "start at login" should run: the unpacked AppImage's launcher on Linux,
/// otherwise this executable.
fn desktop_executable() -> Option<std::ffi::OsString> {
    if let Some(appdir) = std::env::var_os("APPDIR") {
        let launcher = PathBuf::from(appdir).join("AppRun");
        if launcher.is_file() {
            return Some(launcher.into_os_string());
        }
    }
    std::env::current_exe().ok().map(PathBuf::into_os_string)
}

impl Session {
    fn spawn(spec: &ProcessSpec) -> Result<Self, DesktopError> {
        let mut process = spec
            .spawn(Pipes::Protocol)
            .map_err(|_| err("control_unavailable"))?;
        let mut stdin = process
            .child
            .stdin
            .take()
            .ok_or_else(|| err("control_unavailable"))?;
        let mut stdout = BufReader::new(
            process
                .child
                .stdout
                .take()
                .ok_or_else(|| err("control_unavailable"))?,
        );
        let (input, requests) = mpsc::sync_channel::<Work>(1);
        let worker = thread::Builder::new()
            .name("scribe-control-io".into())
            .spawn(move || {
                while let Ok(work) = requests.recv() {
                    let result = (|| {
                        stdin
                            .write_all(&work.request)
                            .and_then(|_| stdin.flush())
                            .map_err(|_| err("control_unavailable"))?;
                        let mut line = Vec::new();
                        stdout
                            .by_ref()
                            .take(MAX_RESPONSE + 1)
                            .read_until(b'\n', &mut line)
                            .map_err(|_| err("control_unavailable"))?;
                        if line.len() as u64 > MAX_RESPONSE || line.last() != Some(&b'\n') {
                            return Err(err("invalid_response"));
                        }
                        Ok(line)
                    })();
                    let failed = result.is_err();
                    if work.reply.send(result).is_err() || failed {
                        break;
                    }
                }
            })
            .map_err(|_| err("control_unavailable"))?;
        Ok(Self {
            process,
            input: Some(input),
            worker: Some(worker),
        })
    }
}
impl Drop for Session {
    fn drop(&mut self) {
        self.input.take();
        // Kill the entire tree to release inherited pipe handles, both reads and writes.
        if self.process.terminate().is_ok()
            && let Some(worker) = self.worker.take()
        {
            let _ = worker.join();
        }
    }
}

#[derive(Default)]
struct ClientInner {
    session: Option<Session>,
    next_id: u64,
    closed: bool,
}

pub struct ControlClient {
    spec: ProcessSpec,
    timeout: Duration,
    inner: Mutex<ClientInner>,
}
impl ControlClient {
    fn request_timeout(&self, method: &str) -> Duration {
        if method == "diagnostics.get" {
            // The first check loads the speech libraries, which is slow on some computers.
            self.timeout.max(Duration::from_secs(60))
        } else {
            self.timeout
        }
    }
    pub fn new(root: PathBuf) -> Self {
        let mut spec = ProcessSpec::python(&root, "control_server.py")
            .with_env("SIGNAL_SCRIBE_DESKTOP_ROOT", root.as_os_str());
        if let Some(exe) = desktop_executable() {
            spec = spec.with_env("SIGNAL_SCRIBE_DESKTOP_EXE", exe);
        }
        Self {
            spec,
            timeout: REQUEST_TIMEOUT,
            inner: Mutex::new(ClientInner::default()),
        }
    }

    /// A failed exchange destroys its session and is NEVER replayed: a mutation may
    /// already have committed. Only a subsequent caller may start a fresh process.
    pub fn call(&self, method: &str, params: Value) -> Result<Value, DesktopError> {
        let deadline = Instant::now() + self.request_timeout(method);
        let mut inner = loop {
            match self.inner.try_lock() {
                Ok(inner) => break inner,
                Err(TryLockError::Poisoned(_)) => return Err(err("control_unavailable")),
                Err(TryLockError::WouldBlock) => {
                    if Instant::now() >= deadline {
                        return Err(err("control_timeout"));
                    }
                    thread::sleep(Duration::from_millis(5));
                }
            }
        };
        if inner.closed {
            return Err(err("runtime_closed"));
        }
        inner.next_id = inner
            .next_id
            .checked_add(1)
            .ok_or_else(|| err("control_unavailable"))?;
        let id = inner.next_id;
        let mut request = serde_json::to_vec(&json!({"id":id,"method":method,"params":params}))
            .map_err(|_| err("invalid_params"))?;
        if request.len() > MAX_REQUEST {
            return Err(err("invalid_params"));
        }
        request.push(b'\n');
        if inner
            .session
            .as_mut()
            .is_some_and(|s| !matches!(s.process.try_wait(), Ok(None)))
        {
            inner.session.take();
        }
        if inner.session.is_none() {
            inner.session = Some(Session::spawn(&self.spec)?);
        }
        let session = inner.session.as_ref().unwrap();
        let (reply, response) = mpsc::sync_channel(1);
        let result = (|| {
            session
                .input
                .as_ref()
                .unwrap()
                .try_send(Work { request, reply })
                .map_err(|_| err("control_unavailable"))?;
            let line = response
                .recv_timeout(deadline.saturating_duration_since(Instant::now()))
                .map_err(|error| match error {
                    mpsc::RecvTimeoutError::Timeout => err("control_timeout"),
                    mpsc::RecvTimeoutError::Disconnected => err("control_unavailable"),
                })??;
            decode_response(&line, id)
        })();
        match result {
            Ok(outcome) => outcome,
            Err(error) => {
                inner.session.take();
                Err(error)
            }
        }
    }
    pub fn shutdown(&self) {
        let mut inner = self
            .inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        inner.closed = true;
        inner.session.take();
    }
}

// Outer Result is protocol integrity; inner Result is an ordinary application error.
fn decode_response(line: &[u8], id: u64) -> Result<Result<Value, DesktopError>, DesktopError> {
    let response: Value = serde_json::from_slice(line).map_err(|_| err("invalid_response"))?;
    if response.get("id").and_then(Value::as_u64) != Some(id) {
        return Err(err("mismatched_response"));
    }
    match response.get("ok").and_then(Value::as_bool) {
        Some(true) if response.get("error").is_none() => response
            .get("result")
            .cloned()
            .map(Ok)
            .ok_or_else(|| err("invalid_response")),
        Some(false) if response.get("result").is_none() => {
            let error = response
                .get("error")
                .filter(|error| {
                    error.get("code").is_some_and(Value::is_string)
                        && error.get("message").is_some_and(Value::is_string)
                })
                .ok_or_else(|| err("invalid_response"))?;
            Ok(Err(service_error(error)))
        }
        _ => Err(err("invalid_response")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn diagnostics_get_more_time_than_ordinary_requests() {
        let (_root, client) = fixture(ECHO);
        assert!(client.request_timeout("diagnostics.get") >= Duration::from_secs(60));
        assert_eq!(client.request_timeout("state.get"), Duration::from_secs(30));
    }
    #[test]
    fn known_errors_keep_codes_but_not_untrusted_content() {
        for code in [
            "media_unavailable",
            "media_too_large",
            "path_denied",
            "config_write_failed",
            "autostart_unavailable",
        ] {
            let error = service_error(&json!({"code":code,"message":"private transcript"}));
            assert_eq!(error.code, code);
            assert!(!error.message.contains("private transcript"));
        }
        let unknown = service_error(&json!({"code":"secret-token","message":"x"}));
        assert_eq!(unknown.code, "control_failed");
    }
    #[test]
    fn setting_validation_details_are_shown_only_when_plain() {
        let plain = service_error(
            &json!({"code":"invalid_config","message":"delivery.mode must be one of: note_to_self, chat"}),
        );
        assert!(plain.message.contains("delivery.mode"));
        let odd = service_error(&json!({"code":"invalid_config","message":"<img src=x>"}));
        assert!(!odd.message.contains("<img"));
    }
    fn fixture(script: &str) -> (tempfile::TempDir, ControlClient) {
        let root = tempfile::tempdir().unwrap();
        std::fs::write(root.path().join("control_server.py"), script).unwrap();
        let client = ControlClient::new(root.path().to_owned());
        (root, client)
    }
    const ECHO: &str = "import sys,json,os\nn=0\nfor line in sys.stdin:\n n+=1\n r=json.loads(line)\n print(json.dumps({'id':r['id'],'ok':True,'result':{'n':n,'pid':os.getpid(),'params':r['params']}}),flush=True)\n";
    #[test]
    fn requests_reuse_one_private_process() {
        let (_root, client) = fixture(ECHO);
        let first = client.call("state.get", json!({})).unwrap();
        let second = client.call("state.get", json!({})).unwrap();
        assert_eq!(second["n"], 2);
        assert_eq!(first["pid"], second["pid"]);
    }
    #[test]
    fn concurrent_calls_are_serialized_and_correlated() {
        let (_root, client) = fixture(ECHO);
        let client = std::sync::Arc::new(client);
        let joins: Vec<_> = (0..12)
            .map(|n| {
                let client = client.clone();
                thread::spawn(move || {
                    let result = client.call("echo", json!({"n":n})).unwrap();
                    assert_eq!(result["params"]["n"], n);
                    result["pid"].clone()
                })
            })
            .collect();
        let pids: Vec<_> = joins.into_iter().map(|join| join.join().unwrap()).collect();
        assert!(pids.iter().all(|pid| pid == &pids[0]));
    }
    #[test]
    fn untrusted_service_errors_never_reach_renderer_or_force_a_restart() {
        let (_root, client) = fixture(
            "import sys,json\nn=0\nfor line in sys.stdin:\n n+=1\n r=json.loads(line)\n print(json.dumps({'id':r['id'],'ok':False,'error':{'code':'secret-token','message':'private-transcript'}} if n==1 else {'id':r['id'],'ok':True,'result':n}),flush=True)\n",
        );
        let error =
            serde_json::to_string(&client.call("state.get", json!({})).unwrap_err()).unwrap();
        assert!(!error.contains("private-transcript"));
        assert!(!error.contains("secret-token"));
        assert_eq!(client.call("state.get", json!({})).unwrap(), 2);
    }
    #[test]
    fn malformed_mismatched_eof_and_partial_lines_invalidate_the_session() {
        for output in [
            "print('bad-json',flush=True)",
            "print(json.dumps({'id':999,'ok':True,'result':1}),flush=True)",
            "sys.exit(0)",
            "sys.stdout.write('{');sys.stdout.flush();sys.exit(0)",
        ] {
            let script = format!(
                "import sys,json\nfor line in sys.stdin:\n r=json.loads(line)\n if r['method']=='bad':\n  {output}\n else:\n  print(json.dumps({{'id':r['id'],'ok':True,'result':42}}),flush=True)\n"
            );
            let (_root, client) = fixture(&script);
            assert!(client.call("bad", json!({})).is_err());
            assert!(client.inner.lock().unwrap().session.is_none());
            assert_eq!(client.call("good", json!({})).unwrap(), 42);
        }
    }
    #[test]
    fn timeout_never_replays_mutation_and_recovers_next_request() {
        let (root, mut client) = fixture(
            "import sys,json,time\nfor line in sys.stdin:\n r=json.loads(line)\n if r['method']=='mutate':\n  with open('mutations','a') as f: f.write('x')\n  time.sleep(60)\n else:\n  print(json.dumps({'id':r['id'],'ok':True,'result':42}),flush=True)\n",
        );
        // Establish readiness before shortening the deadline: slow interpreter startup
        // under parallel test load must not masquerade as a committed mutation.
        client.call("ready", json!({})).unwrap();
        client.timeout = Duration::from_millis(700);
        let start = Instant::now();
        assert_eq!(
            client.call("mutate", json!({})).unwrap_err().code,
            "control_timeout"
        );
        assert!(start.elapsed() < Duration::from_secs(5));
        assert!(client.inner.lock().unwrap().session.is_none());
        assert_eq!(
            std::fs::read_to_string(root.path().join("mutations")).unwrap(),
            "x"
        );
        client.timeout = REQUEST_TIMEOUT;
        assert_eq!(client.call("read", json!({})).unwrap(), 42);
        assert_eq!(
            std::fs::read_to_string(root.path().join("mutations")).unwrap(),
            "x"
        );
    }
    #[test]
    fn blocked_pipe_write_obeys_the_same_timeout() {
        let (_root, mut client) = fixture("import time\ntime.sleep(60)\n");
        client.timeout = Duration::from_millis(300);
        let start = Instant::now();
        assert_eq!(
            client
                .call("write", json!({"payload":"x".repeat(512*1024)}))
                .unwrap_err()
                .code,
            "control_timeout"
        );
        assert!(start.elapsed() < Duration::from_secs(5));
        assert!(client.inner.lock().unwrap().session.is_none());
    }
    #[test]
    fn shutdown_reaps_control_and_refuses_future_calls() {
        let (_root, client) = fixture(ECHO);
        client.call("state.get", json!({})).unwrap();
        client.shutdown();
        assert!(client.inner.lock().unwrap().session.is_none());
        assert_eq!(
            client.call("state.get", json!({})).unwrap_err().code,
            "runtime_closed"
        );
    }
    #[test]
    fn invalid_envelopes_are_not_success_and_null_result_is_valid() {
        for line in [
            r#"{"id":1,"ok":true}"#,
            r#"{"id":1,"ok":false}"#,
            r#"{"id":1,"ok":"true","result":1}"#,
            r#"{"id":1,"ok":true,"result":1,"error":{}}"#,
        ] {
            assert!(decode_response(line.as_bytes(), 1).is_err());
        }
        assert_eq!(
            decode_response(br#"{"id":1,"ok":true,"result":null}"#, 1)
                .unwrap()
                .unwrap(),
            Value::Null
        );
    }
}
