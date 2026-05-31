#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    env,
    fs::{self, OpenOptions},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};

use tauri::{Manager, RunEvent, WindowEvent};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 7070;
const BACKEND_BUNDLE_MODE: &str = env!("KRONOS_BACKEND_BUNDLE_MODE");
const WEB_SERVER: &str = env!("KRONOS_WEB_SERVER");
const BACKEND_PID_FILE: &str = "backend.pid";

struct BackendProcess {
    child: Mutex<Option<Child>>,
    pid_file: PathBuf,
}

impl BackendProcess {
    fn new(child: Option<Child>, pid_file: PathBuf) -> Self {
        Self {
            child: Mutex::new(child),
            pid_file,
        }
    }

    fn stop(&self) {
        if let Ok(mut child_slot) = self.child.lock() {
            if let Some(child) = child_slot.as_mut() {
                terminate_child(child);
            }
            *child_slot = None;
        }
        cleanup_backend_processes(&self.pid_file);
    }
}

impl Drop for BackendProcess {
    fn drop(&mut self) {
        if let Ok(mut child_slot) = self.child.lock() {
            if let Some(child) = child_slot.as_mut() {
                terminate_child(child);
            }
        }
        cleanup_backend_processes(&self.pid_file);
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

    let resource_dir = app
        .path()
        .resource_dir()
        .unwrap_or_else(|_| env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    let tauri_resource_root = resource_dir.join("_up_");
    if tauri_resource_root.exists() {
        tauri_resource_root
    } else {
        resource_dir
    }
}

fn bundled_backend_path(app: &tauri::App) -> Option<PathBuf> {
    if cfg!(debug_assertions) {
        return None;
    }

    let resource_dir = app.path().resource_dir().ok()?;
    let executable_name = if cfg!(windows) {
        "kronos_webui_backend.exe"
    } else {
        "kronos_webui_backend"
    };
    [
        resource_dir
            .join("_up_")
            .join("packaging")
            .join("backend")
            .join("kronos_webui_backend")
            .join(executable_name),
        resource_dir
            .join("packaging")
            .join("backend")
            .join("kronos_webui_backend")
            .join(executable_name),
        resource_dir
            .join("kronos_webui_backend")
            .join(executable_name),
    ]
    .into_iter()
    .find(|path| path.exists())
}

fn user_data_dir(app: &tauri::App) -> PathBuf {
    app.path()
        .app_data_dir()
        .unwrap_or_else(|_| env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
}

fn backend_pid_path(user_dir: &Path) -> PathBuf {
    user_dir.join(BACKEND_PID_FILE)
}

fn record_backend_pid(user_dir: &Path, child: &Child) {
    let pid_file = backend_pid_path(user_dir);
    if let Some(parent) = pid_file.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(pid_file, child.id().to_string());
}

fn clear_backend_pid_file(pid_file: &Path) {
    let _ = fs::remove_file(pid_file);
}

fn read_backend_pid_file(pid_file: &Path) -> Option<u32> {
    fs::read_to_string(pid_file)
        .ok()
        .and_then(|value| value.trim().parse::<u32>().ok())
}

#[cfg(unix)]
fn process_is_running(pid: u32) -> bool {
    Command::new("kill")
        .arg("-0")
        .arg(pid.to_string())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

#[cfg(windows)]
fn process_is_running(pid: u32) -> bool {
    Command::new("tasklist")
        .args(["/FI", &format!("PID eq {pid}")])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .map(|output| String::from_utf8_lossy(&output.stdout).contains(&pid.to_string()))
        .unwrap_or(false)
}

#[cfg(unix)]
fn terminate_pid(pid: u32) {
    let pid_arg = pid.to_string();
    let process_group_arg = format!("-{pid}");
    let _ = Command::new("kill")
        .arg("-TERM")
        .arg(&process_group_arg)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    let _ = Command::new("kill")
        .arg("-TERM")
        .arg(&pid_arg)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();

    for _ in 0..20 {
        if !process_is_running(pid) {
            return;
        }
        thread::sleep(Duration::from_millis(100));
    }

    let _ = Command::new("kill")
        .arg("-KILL")
        .arg(process_group_arg)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    let _ = Command::new("kill")
        .arg("-KILL")
        .arg(pid_arg)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

#[cfg(windows)]
fn terminate_pid(pid: u32) {
    let _ = Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

fn terminate_child(child: &mut Child) {
    terminate_pid(child.id());
    let _ = child.wait();
}

fn cleanup_backend_processes(pid_file: &Path) {
    if let Some(pid) = read_backend_pid_file(pid_file) {
        if process_is_running(pid) {
            terminate_pid(pid);
        }
    }

    for pid in backend_port_pids() {
        if is_kronos_backend_process(pid) {
            terminate_pid(pid);
        }
    }

    clear_backend_pid_file(pid_file);
}

fn cleanup_stale_backend(user_dir: &Path) {
    cleanup_backend_processes(&backend_pid_path(user_dir));
}

#[cfg(unix)]
fn backend_port_pids() -> Vec<u32> {
    Command::new("lsof")
        .args(["-ti", &format!("tcp:{BACKEND_PORT}"), "-sTCP:LISTEN"])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .map(|output| {
            String::from_utf8_lossy(&output.stdout)
                .lines()
                .filter_map(|line| line.trim().parse::<u32>().ok())
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(windows)]
fn backend_port_pids() -> Vec<u32> {
    Vec::new()
}

#[cfg(unix)]
fn is_kronos_backend_process(pid: u32) -> bool {
    let pid_arg = pid.to_string();
    Command::new("ps")
        .args(["-p", &pid_arg, "-o", "command="])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .output()
        .map(|output| {
            let command = String::from_utf8_lossy(&output.stdout).to_lowercase();
            command.contains("kronos_webui_backend")
                || command.contains("webui/run_robyn.py")
                || command.contains("webui/run.py")
                || command.contains("webui.robyn_app")
                || command.contains("webui.run")
        })
        .unwrap_or(false)
}

#[cfg(windows)]
fn is_kronos_backend_process(_pid: u32) -> bool {
    false
}

fn log_stdio(user_dir: &PathBuf, filename: &str) -> Stdio {
    let log_dir = user_dir.join("logs");
    if fs::create_dir_all(&log_dir).is_err() {
        return Stdio::null();
    }

    OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join(filename))
        .map(Stdio::from)
        .unwrap_or_else(|_| Stdio::null())
}

fn configure_backend_command(command: &mut Command) {
    #[cfg(unix)]
    {
        command.process_group(0);
    }
}

fn python_candidates() -> Vec<(&'static str, Vec<&'static str>)> {
    if cfg!(windows) {
        vec![
            ("python3.13.exe", vec![]),
            ("python3.12.exe", vec![]),
            ("python3.11.exe", vec![]),
            ("python3.exe", vec![]),
            ("python.exe", vec![]),
            ("py.exe", vec!["-3"]),
        ]
    } else {
        vec![
            ("python3.13", vec![]),
            ("python3.12", vec![]),
            ("python3.11", vec![]),
            ("python3", vec![]),
            ("python", vec![]),
        ]
    }
}

fn command_exists(program: &str, base_args: &[&str]) -> bool {
    let mut command = Command::new(program);
    command.args(base_args).args([
        "-c",
        "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)",
    ]);
    command.stdout(Stdio::null()).stderr(Stdio::null());
    command
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn start_backend(app: &tauri::App) -> Option<Child> {
    let user_dir = user_data_dir(app);
    cleanup_stale_backend(&user_dir);

    if is_backend_running() {
        return None;
    }

    let project_root = bundled_project_root(app);

    if let Some(backend_exe) = bundled_backend_path(app) {
        let mut command = Command::new(backend_exe);
        configure_backend_command(&mut command);
        command
            .current_dir(&project_root)
            .env("KRONOS_PROJECT_ROOT", &project_root)
            .env("KRONOS_USER_DIR", &user_dir)
            .env("KRONOS_DESKTOP", "tauri")
            .env(
                "KRONOS_SOURCE_CONFIG_DIR",
                env!("CARGO_MANIFEST_DIR").replace("/src-tauri", "/config"),
            )
            .env("KRONOS_HOST", BACKEND_HOST)
            .env("KRONOS_PORT", BACKEND_PORT.to_string())
            .env("FLASK_DEBUG", "0")
            .env("KRONOS_BACKEND_BUNDLE_MODE", BACKEND_BUNDLE_MODE)
            .env("KRONOS_WEB_SERVER", WEB_SERVER)
            .env(
                "KRONOS_DISABLE_TORCH",
                if BACKEND_BUNDLE_MODE == "full" {
                    "0"
                } else {
                    "1"
                },
            )
            .env("PYTHONUNBUFFERED", "1")
            .stdout(log_stdio(&user_dir, "backend.stdout.log"))
            .stderr(log_stdio(&user_dir, "backend.stderr.log"));

        return match command.spawn() {
            Ok(child) => {
                record_backend_pid(&user_dir, &child);
                Some(child)
            }
            Err(error) => {
                eprintln!("Failed to start bundled Kronos backend: {error}");
                None
            }
        };
    }

    let backend_entry = if WEB_SERVER == "robyn" {
        project_root.join("webui").join("run_robyn.py")
    } else {
        project_root.join("webui").join("app.py")
    };
    if !backend_entry.exists() {
        eprintln!(
            "Kronos backend entry not found: {}",
            backend_entry.display()
        );
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

    args.push(backend_entry.to_string_lossy().to_string());

    let mut command = Command::new(program);
    configure_backend_command(&mut command);
    command
        .args(args)
        .current_dir(project_root)
        .env("KRONOS_DESKTOP", "tauri")
        .env("KRONOS_USER_DIR", &user_dir)
        .env(
            "KRONOS_SOURCE_CONFIG_DIR",
            env!("CARGO_MANIFEST_DIR").replace("/src-tauri", "/config"),
        )
        .env("KRONOS_HOST", BACKEND_HOST)
        .env("KRONOS_PORT", BACKEND_PORT.to_string())
        .env("FLASK_DEBUG", "0")
        .env("KRONOS_WEB_SERVER", WEB_SERVER)
        .env("PYTHONUNBUFFERED", "1");

    if cfg!(debug_assertions) {
        command.stdout(Stdio::inherit()).stderr(Stdio::inherit());
    } else {
        command
            .stdout(log_stdio(&user_dir, "backend.stdout.log"))
            .stderr(log_stdio(&user_dir, "backend.stderr.log"));
    }

    match command.spawn() {
        Ok(child) => {
            record_backend_pid(&user_dir, &child);
            Some(child)
        }
        Err(error) => {
            eprintln!("Failed to start Kronos backend: {error}");
            None
        }
    }
}

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let user_dir = user_data_dir(app);
            let backend = BackendProcess::new(start_backend(app), backend_pid_path(&user_dir));
            app.manage(backend);
            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                window.state::<BackendProcess>().stop();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Kronos Tauri application");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            app_handle.state::<BackendProcess>().stop();
        }
    });
}
