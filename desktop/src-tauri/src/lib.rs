mod control;
mod engine;
mod process;
mod runtime;
mod state;

use control::{DesktopError, err};
use engine::EngineSnapshot;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use state::DesktopState;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, State, WindowEvent};
use tauri_plugin_dialog::DialogExt;

type Managed<'a> = State<'a, Arc<DesktopState>>;

// Blocking pipes, process waits, file locks, and dialogs never execute on the UI thread.
async fn blocking<T: Send + 'static>(
    state: Managed<'_>,
    operation: impl FnOnce(Arc<DesktopState>) -> Result<T, DesktopError> + Send + 'static,
) -> Result<T, DesktopError> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        if state.shutting_down.load(Ordering::Acquire) {
            return Err(err("runtime_closed"));
        }
        operation(state)
    })
    .await
    .map_err(|_| err("control_unavailable"))?
}
async fn call(
    state: Managed<'_>,
    method: &'static str,
    params: Value,
) -> Result<Value, DesktopError> {
    blocking(state, move |state| state.control.call(method, params)).await
}

#[derive(Deserialize)]
struct PythonState {
    linked: bool,
    #[serde(default)]
    unlinked: bool,
    account: String,
    schema_version: u64,
    #[serde(default)]
    engine: Option<Value>,
}
#[derive(Serialize)]
struct AppState {
    linked: bool,
    unlinked: bool,
    account: String,
    schema_version: u64,
    /// The engine process as supervised by this app.
    engine: EngineSnapshot,
    /// The engine's own heartbeat: connection, model, queue.
    heartbeat: Option<Value>,
    startup_error: Option<DesktopError>,
    version: &'static str,
}

#[tauri::command]
async fn app_state(state: Managed<'_>) -> Result<AppState, DesktopError> {
    blocking(state, |state| {
        let python: PythonState =
            serde_json::from_value(state.control.call("state.get", json!({}))?)
                .map_err(|_| err("invalid_response"))?;
        Ok(AppState {
            linked: python.linked,
            unlinked: python.unlinked,
            account: python.account,
            schema_version: python.schema_version,
            engine: state.engine.snapshot()?,
            heartbeat: python.engine,
            startup_error: state
                .startup_error
                .lock()
                .map_err(|_| err("engine_state_failed"))?
                .clone(),
            version: env!("CARGO_PKG_VERSION"),
        })
    })
    .await
}
#[tauri::command]
async fn config_get(state: Managed<'_>) -> Result<Value, DesktopError> {
    call(state, "config.get", json!({})).await
}
#[tauri::command]
async fn config_save(
    state: Managed<'_>,
    config: Map<String, Value>,
) -> Result<Value, DesktopError> {
    validate_config_patch(&config)?;
    // The Python result is the complete merged config, not the patch.
    call(state, "config.save", json!({"config":config})).await
}
fn validate_config_patch(config: &Map<String, Value>) -> Result<(), DesktopError> {
    if config.contains_key("theme") {
        return Err(err("invalid_config"));
    }
    if let Some(desktop) = config.get("desktop") {
        let desktop = desktop.as_object().ok_or_else(|| err("invalid_config"))?;
        if desktop
            .get("start_engine_on_launch")
            .is_some_and(|value| !value.is_boolean())
        {
            return Err(err("invalid_config"));
        }
        if desktop
            .get("theme")
            .is_some_and(|theme| !matches!(theme.as_str(), Some("system" | "light" | "dark")))
        {
            return Err(err("invalid_config"));
        }
    }
    Ok(())
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct HistoryFilters {
    #[serde(skip_serializing_if = "Option::is_none")]
    query: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    direction: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    kind: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    conversation: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    limit: Option<u32>,
}
#[tauri::command]
async fn history_list(state: Managed<'_>, filters: HistoryFilters) -> Result<Value, DesktopError> {
    call(
        state,
        "history.list",
        serde_json::to_value(filters).map_err(|_| err("invalid_params"))?,
    )
    .await
}
#[tauri::command]
async fn history_delete(state: Managed<'_>, ids: Vec<String>) -> Result<Value, DesktopError> {
    call(state, "history.delete", json!({"ids":ids})).await
}
#[tauri::command]
async fn history_clear(state: Managed<'_>) -> Result<Value, DesktopError> {
    call(state, "history.clear", json!({})).await
}
#[tauri::command]
async fn history_conversations(state: Managed<'_>) -> Result<Value, DesktopError> {
    call(state, "history.conversations", json!({})).await
}
#[tauri::command]
async fn history_audio(state: Managed<'_>, id: String) -> Result<Value, DesktopError> {
    call(state, "history.audio", json!({"id":id})).await
}
#[tauri::command]
async fn diagnostics_get(state: Managed<'_>) -> Result<Value, DesktopError> {
    call(state, "diagnostics.get", json!({})).await
}
#[tauri::command]
async fn autostart_get(state: Managed<'_>) -> Result<Value, DesktopError> {
    call(state, "autostart.get", json!({})).await
}
#[tauri::command]
async fn autostart_set(state: Managed<'_>, enabled: bool) -> Result<Value, DesktopError> {
    call(state, "autostart.set", json!({"enabled":enabled})).await
}
#[tauri::command]
async fn engine_start(state: Managed<'_>) -> Result<EngineSnapshot, DesktopError> {
    blocking(state, |state| state.engine_action("start")).await
}
#[tauri::command]
async fn engine_stop(state: Managed<'_>) -> Result<EngineSnapshot, DesktopError> {
    blocking(state, |state| state.engine_action("stop")).await
}
#[tauri::command]
async fn engine_restart(state: Managed<'_>) -> Result<EngineSnapshot, DesktopError> {
    blocking(state, |state| state.engine_action("restart")).await
}
#[tauri::command]
async fn link_signal(state: Managed<'_>) -> Result<(), DesktopError> {
    blocking(state, |state| state.link_signal()).await
}
#[tauri::command]
async fn link_status(state: Managed<'_>) -> Result<Value, DesktopError> {
    blocking(state, |state| state.link_status()).await
}
#[tauri::command]
async fn link_cancel(state: Managed<'_>) -> Result<(), DesktopError> {
    blocking(state, |state| state.link_cancel()).await
}
#[tauri::command]
async fn open_logs(state: Managed<'_>) -> Result<(), DesktopError> {
    blocking(state, |state| {
        let logs = state.root.join("logs");
        std::fs::create_dir_all(&logs).map_err(|_| err("open_failed"))?;
        let opener = if cfg!(windows) {
            "explorer"
        } else if cfg!(target_os = "macos") {
            "open"
        } else {
            "xdg-open"
        };
        std::process::Command::new(opener)
            .arg(&logs)
            .spawn()
            .map(|_| ())
            .map_err(|_| err("open_failed"))
    })
    .await
}

fn show_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}
fn request_quit(app: &tauri::AppHandle) {
    let state = app.state::<Arc<DesktopState>>().inner().clone();
    if state.shutting_down.swap(true, Ordering::AcqRel) {
        return;
    }
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        state.shutdown();
        app.exit(0);
    });
}
fn tray_engine_action(app: &tauri::AppHandle, action: &'static str) {
    let state = app.state::<Arc<DesktopState>>().inner().clone();
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        if let Err(error) = state.engine_action(action) {
            app.dialog()
                .message(error.message)
                .title("Signal Scribe")
                .show(|_| {});
        }
    });
}
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _| {
            if let Some(state) = app.try_state::<Arc<DesktopState>>() {
                let requested = runtime::resolve_root(
                    &args.into_iter().skip(1).map(Into::into).collect::<Vec<_>>(),
                    std::env::var_os("SIGNAL_SCRIBE_ROOT"),
                    &std::env::current_exe().unwrap_or_default(),
                    runtime::user_pointer().as_deref(),
                );
                if !matches!(requested, Ok(ref root) if root == &state.root) {
                    app.dialog()
                        .message("Signal Scribe is already open for a different install folder. Quit it first.")
                        .title("Signal Scribe")
                        .show(|_| {});
                    return;
                }
            }
            show_window(app);
        }))
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let root = match runtime::project_root() {
                Ok(root) => root,
                Err(error) => {
                    let handle = app.handle().clone();
                    app.dialog()
                        .message(error.message)
                        .title("Signal Scribe")
                        .show(move |_| handle.exit(1));
                    return Ok(());
                }
            };
            let state = Arc::new(DesktopState::new(root)?);
            app.manage(state.clone());
            if !runtime::start_hidden() {
                show_window(app.handle());
            }
            let handle = app.handle().clone();
            tauri::async_runtime::spawn_blocking(move || {
                if let Some(error) = state.start_on_launch() {
                    handle
                        .dialog()
                        .message(error.message)
                        .title("Signal Scribe")
                        .show(|_| {});
                }
            });
            let show = MenuItem::with_id(app, "show", "Open Signal Scribe", true, None::<&str>)?;
            let start = MenuItem::with_id(app, "start", "Start transcribing", true, None::<&str>)?;
            let stop = MenuItem::with_id(app, "stop", "Pause transcribing", true, None::<&str>)?;
            let separator = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Signal Scribe", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &start, &stop, &separator, &quit])?;
            let mut tray = TrayIconBuilder::new()
                .tooltip("Signal Scribe")
                .menu(&menu)
                .show_menu_on_left_click(false);
            if cfg!(target_os = "macos") {
                // A monochrome template icon adapts to the light or dark menu bar.
                tray = tray
                    .icon(tauri::image::Image::from_bytes(include_bytes!(
                        "../icons/tray-template.png"
                    ))?)
                    .icon_as_template(true);
            } else if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.on_menu_event(|app, event| match event.id.as_ref() {
                "show" => show_window(app),
                "start" => tray_engine_action(app, "start"),
                "stop" => tray_engine_action(app, "stop"),
                "quit" => request_quit(app),
                _ => {}
            })
            .on_tray_icon_event(|tray, event| {
                if let TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } = event
                {
                    show_window(tray.app_handle());
                }
            })
            .build(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            app_state,
            config_get,
            config_save,
            history_list,
            history_delete,
            history_clear,
            history_conversations,
            history_audio,
            diagnostics_get,
            autostart_get,
            autostart_set,
            engine_start,
            engine_stop,
            engine_restart,
            link_signal,
            link_status,
            link_cancel,
            open_logs
        ])
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // Closing the window keeps transcribing in the tray; Quit stops everything.
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("Signal Scribe desktop initialization failed");
    app.run(|app, event| match event {
        tauri::RunEvent::ExitRequested { api, .. } => {
            if let Some(state) = app.try_state::<Arc<DesktopState>>()
                && !state.shutting_down.load(Ordering::Acquire)
            {
                api.prevent_exit();
                request_quit(app);
            }
        }
        tauri::RunEvent::Exit => {
            if let Some(state) = app.try_state::<Arc<DesktopState>>() {
                state.shutdown();
            }
        }
        #[cfg(target_os = "macos")]
        tauri::RunEvent::Reopen { .. } => show_window(app),
        _ => {}
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn history_filters_reject_arbitrary_fields_and_omit_missing_values() {
        assert!(serde_json::from_value::<HistoryFilters>(json!({"path":"private"})).is_err());
        let filters: HistoryFilters =
            serde_json::from_value(json!({"query":"hello","limit":20})).unwrap();
        assert_eq!(
            serde_json::to_value(filters).unwrap(),
            json!({"query":"hello","limit":20})
        );
    }
    #[test]
    fn theme_is_only_accepted_in_desktop_config() {
        for patch in [
            json!({"theme":"dark"}),
            json!({"desktop":{"theme":"invalid"}}),
            json!({"desktop":false}),
        ] {
            assert!(validate_config_patch(patch.as_object().unwrap()).is_err());
        }
        assert!(
            validate_config_patch(
                json!({"desktop":{"theme":"dark"},"other":{"preserved":true}})
                    .as_object()
                    .unwrap()
            )
            .is_ok()
        );
    }
}
