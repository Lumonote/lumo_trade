#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    env,
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::Duration,
};

use tauri::{Manager, WindowEvent};

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 7070;

struct BackendProcess(Mutex<Option<Child>>);

impl BackendProcess {
    fn new(child: Option<Child>) -> Self {
        Self(Mutex::new(child))
    }

    fn stop(&self) {
        if let Ok(mut child_slot) = self.0.lock() {
            if let Some(child) = child_slot.as_mut() {
                let _ = child.kill();
                let _ = child.wait();
            }
            *child_slot = None;
        }
    }
}

impl Drop for BackendProcess {
    fn drop(&mut self) {
        if let Ok(mut child_slot) = self.0.lock() {
            if let Some(child) = child_slot.as_mut() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

fn backend_addr() -> SocketAddr {
    SocketAddr::from(([127, 0, 0, 1], BACKEND_PORT))
}

fn is_backend_running() -> bool {
    TcpStream::connect_timeout(&backend_addr(), Duration::from_millis(250)).is_ok()
}

fn bundled_project_root(app: &tauri::App) -> PathBuf {
    if let Ok(root) = env::var("KRONOS_PROJECT_ROOT") {
        return PathBuf::from(root);
    }

    if cfg!(debug_assertions) {
        return PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("src-tauri should have a project parent")
            .to_path_buf();
    }

    app.path()
        .resource_dir()
        .unwrap_or_else(|_| env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
}

fn python_candidates() -> Vec<(&'static str, Vec<&'static str>)> {
    if cfg!(windows) {
        vec![
            ("python3.11.exe", vec![]),
            ("python3.exe", vec![]),
            ("python.exe", vec![]),
            ("py.exe", vec!["-3"]),
        ]
    } else {
        vec![("python3.11", vec![]), ("python3", vec![]), ("python", vec![])]
    }
}

fn command_exists(program: &str, base_args: &[&str]) -> bool {
    let mut command = Command::new(program);
    command.args(base_args).arg("--version");
    command.stdout(Stdio::null()).stderr(Stdio::null());
    command.status().map(|status| status.success()).unwrap_or(false)
}

fn start_backend(app: &tauri::App) -> Option<Child> {
    if is_backend_running() {
        return None;
    }

    let project_root = bundled_project_root(app);
    let app_py = project_root.join("webui").join("app.py");
    if !app_py.exists() {
        eprintln!("Kronos backend entry not found: {}", app_py.display());
        return None;
    }

    let python = env::var("KRONOS_PYTHON")
        .ok()
        .map(|program| (program, Vec::<String>::new()))
        .or_else(|| {
            python_candidates()
                .into_iter()
                .find(|(program, args)| command_exists(program, args))
                .map(|(program, args)| {
                    (
                        program.to_string(),
                        args.into_iter().map(str::to_string).collect(),
                    )
                })
        });

    let Some((program, mut args)) = python else {
        eprintln!("No Python interpreter found for Kronos backend");
        return None;
    };

    args.push(app_py.to_string_lossy().to_string());

    let mut command = Command::new(program);
    command
        .args(args)
        .current_dir(project_root)
        .env("KRONOS_DESKTOP", "tauri")
        .env("KRONOS_HOST", BACKEND_HOST)
        .env("KRONOS_PORT", BACKEND_PORT.to_string())
        .env("FLASK_DEBUG", "0")
        .env("PYTHONUNBUFFERED", "1");

    if cfg!(debug_assertions) {
        command.stdout(Stdio::inherit()).stderr(Stdio::inherit());
    } else {
        command.stdout(Stdio::null()).stderr(Stdio::null());
    }

    command.spawn().map(Some).unwrap_or_else(|error| {
        eprintln!("Failed to start Kronos backend: {error}");
        None
    })
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let backend = BackendProcess::new(start_backend(app));
            app.manage(backend);
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                window.state::<BackendProcess>().stop();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Kronos Tauri application");
}
