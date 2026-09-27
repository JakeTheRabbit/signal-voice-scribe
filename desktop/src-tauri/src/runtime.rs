//! Finding the Signal Scribe install folder ("root") this window controls.
//!
//! In order: `--root <absolute path>`, `SIGNAL_SCRIBE_ROOT`, a
//! `signal-scribe-root.txt` next to the executable or in a parent folder, a parent
//! folder that is itself a Signal Scribe install, and finally the per-user pointer
//! the installer writes (`<config dir>/signal-scribe/root.txt`). An invalid
//! explicit choice is an error; the current directory is never used.
use crate::control::{DesktopError, err};
use std::ffi::OsString;
use std::path::{Path, PathBuf};

pub fn project_root() -> Result<PathBuf, DesktopError> {
    resolve_root(
        &std::env::args_os().skip(1).collect::<Vec<_>>(),
        std::env::var_os("SIGNAL_SCRIBE_ROOT"),
        &std::env::current_exe().map_err(|_| err("root_unavailable"))?,
        user_pointer().as_deref(),
    )
}

/// `--hidden` starts in the tray without opening the window (used at login).
pub fn start_hidden() -> bool {
    std::env::args_os().skip(1).any(|arg| arg == "--hidden")
}

pub fn user_pointer() -> Option<PathBuf> {
    let base = if cfg!(windows) {
        std::env::var_os("APPDATA").map(PathBuf::from)
    } else if cfg!(target_os = "macos") {
        std::env::var_os("HOME").map(|home| PathBuf::from(home).join("Library/Application Support"))
    } else {
        std::env::var_os("XDG_CONFIG_HOME")
            .filter(|value| !value.is_empty())
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")))
    };
    base.map(|base| base.join("signal-scribe").join("root.txt"))
}

pub fn resolve_root(
    args: &[OsString],
    environment: Option<OsString>,
    executable: &Path,
    user_pointer: Option<&Path>,
) -> Result<PathBuf, DesktopError> {
    let mut explicit = None;
    let mut index = 0;
    while index < args.len() {
        let arg = args[index]
            .to_str()
            .ok_or_else(|| err("invalid_root_argument"))?;
        if arg == "--hidden" || arg.starts_with("-psn_") {
            // -psn_* is added by older macOS versions when launched from Finder.
            index += 1;
            continue;
        }
        let value = if arg == "--root" {
            index += 1;
            args.get(index)
                .cloned()
                .ok_or_else(|| err("invalid_root_argument"))?
        } else if let Some(value) = arg.strip_prefix("--root=") {
            value.into()
        } else {
            return Err(err("invalid_root_argument"));
        };
        if value.is_empty() || explicit.replace(PathBuf::from(value)).is_some() {
            return Err(err("invalid_root_argument"));
        }
        index += 1;
    }
    // Invalid explicit choices are errors, never permission to use another install.
    if let Some(path) = explicit {
        return validate_root(&path);
    }
    if let Some(path) = environment.filter(|value| !value.is_empty()) {
        return validate_root(Path::new(&path));
    }
    for ancestor in executable
        .parent()
        .ok_or_else(|| err("root_unavailable"))?
        .ancestors()
    {
        let pointer = ancestor.join("signal-scribe-root.txt");
        if pointer.exists() {
            return read_pointer(&pointer);
        }
        if ancestor.join("control_server.py").is_file() {
            return validate_root(ancestor);
        }
    }
    match user_pointer {
        Some(pointer) if pointer.is_file() => read_pointer(pointer),
        _ => Err(err("root_unavailable")),
    }
}

fn read_pointer(pointer: &Path) -> Result<PathBuf, DesktopError> {
    let raw = std::fs::read_to_string(pointer).map_err(|_| err("root_unavailable"))?;
    validate_root(Path::new(raw.trim()))
}

fn validate_root(path: &Path) -> Result<PathBuf, DesktopError> {
    if !path.is_absolute()
        || !["control_server.py", "transcriber.py", "link.py"]
            .iter()
            .all(|file| path.join(file).is_file())
        || !path.join("scribe").is_dir()
    {
        return Err(err("root_unavailable"));
    }
    #[cfg(windows)]
    return dunce::canonicalize(path).map_err(|_| err("root_unavailable"));

    #[cfg(not(windows))]
    path.canonicalize().map_err(|_| err("root_unavailable"))
}

pub fn python_executable(root: &Path) -> PathBuf {
    let candidates = if cfg!(windows) {
        [".venv/Scripts/python.exe", "runtime/python.exe"]
    } else {
        [".venv/bin/python3", "runtime/python3"]
    };
    for candidate in candidates {
        let path = root.join(candidate);
        if path.is_file() {
            return path;
        }
    }
    // Development checkouts may use a prepared Python on PATH, never another install's venv.
    // pythonw is deliberately excluded: it does not provide reliable JSON-lines stdio.
    PathBuf::from(if cfg!(windows) {
        "python.exe"
    } else {
        "python3"
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn canonical_test_path(path: &Path) -> PathBuf {
        #[cfg(windows)]
        return dunce::canonicalize(path).unwrap();

        #[cfg(not(windows))]
        path.canonicalize().unwrap()
    }

    fn root() -> tempfile::TempDir {
        let dir = tempfile::tempdir().unwrap();
        for file in ["control_server.py", "transcriber.py", "link.py"] {
            std::fs::write(dir.path().join(file), "").unwrap();
        }
        std::fs::create_dir(dir.path().join("scribe")).unwrap();
        dir
    }
    #[test]
    fn explicit_root_beats_environment_and_executable_ancestor() {
        let chosen = root();
        let other = root();
        let result = resolve_root(
            &["--root".into(), chosen.path().into(), "--hidden".into()],
            Some(other.path().into()),
            &other.path().join("desktop/app.exe"),
            None,
        )
        .unwrap();
        assert_eq!(result, canonical_test_path(chosen.path()));
    }
    #[test]
    fn invalid_explicit_root_never_falls_back() {
        let other = root();
        assert!(
            resolve_root(
                &["--root".into(), other.path().join("missing").into()],
                Some(other.path().into()),
                &other.path().join("app.exe"),
                None,
            )
            .is_err()
        );
    }
    #[test]
    fn ancestor_and_absolute_installed_pointer_work_without_cwd() {
        let source = root();
        let installed = tempfile::tempdir().unwrap();
        assert_eq!(
            resolve_root(
                &[],
                None,
                &source.path().join("runtime/desktop/signal-scribe.exe"),
                None,
            )
            .unwrap(),
            canonical_test_path(source.path())
        );
        std::fs::write(
            installed.path().join("signal-scribe-root.txt"),
            source.path().to_str().unwrap(),
        )
        .unwrap();
        assert_eq!(
            resolve_root(&[], None, &installed.path().join("app.exe"), None).unwrap(),
            canonical_test_path(source.path())
        );
        std::fs::write(
            installed.path().join("signal-scribe-root.txt"),
            "relative-checkout",
        )
        .unwrap();
        assert!(resolve_root(&[], None, &installed.path().join("app.exe"), None).is_err());
    }
    #[test]
    fn user_pointer_is_the_last_resort() {
        let source = root();
        let elsewhere = tempfile::tempdir().unwrap();
        let pointer = elsewhere.path().join("root.txt");
        std::fs::write(&pointer, format!("{}\n", source.path().display())).unwrap();
        assert_eq!(
            resolve_root(
                &["-psn_0_12345".into()],
                None,
                &elsewhere
                    .path()
                    .join("Signal Scribe.app/Contents/MacOS/signal-scribe"),
                Some(&pointer),
            )
            .unwrap(),
            canonical_test_path(source.path())
        );
        assert!(resolve_root(&[], None, &elsewhere.path().join("app"), None).is_err());
    }
    #[test]
    fn missing_duplicate_relative_and_unknown_arguments_are_rejected() {
        for args in [
            vec!["--root"],
            vec!["--root="],
            vec!["--root", "relative"],
            vec!["--root=a", "--root=b"],
            vec!["--unknown"],
        ] {
            assert!(
                resolve_root(
                    &args.into_iter().map(Into::into).collect::<Vec<_>>(),
                    None,
                    Path::new("app.exe"),
                    None,
                )
                .is_err()
            );
        }
    }
    #[test]
    fn console_interpreter_from_selected_runtime_is_used_for_all_children() {
        let source = root();
        let relative = if cfg!(windows) {
            ".venv/Scripts/python.exe"
        } else {
            ".venv/bin/python3"
        };
        let python = source.path().join(relative);
        std::fs::create_dir_all(python.parent().unwrap()).unwrap();
        std::fs::write(&python, "").unwrap();
        assert_eq!(python_executable(source.path()), python);
    }

    #[cfg(windows)]
    #[test]
    fn resolved_root_is_safe_for_python_and_java_child_processes() {
        let source = root();
        let resolved = resolve_root(
            &["--root".into(), source.path().into()],
            None,
            &source.path().join("desktop/app.exe"),
            None,
        )
        .unwrap();

        assert!(
            !resolved.as_os_str().to_string_lossy().starts_with(r"\\?\"),
            "child process root must not use the Windows verbatim path prefix: {resolved:?}"
        );
    }
}
