#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    env,
    fs::{self, OpenOptions},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::{Duration, Instant},
};

use tauri::{Emitter, Manager, RunEvent, WindowEvent};

#[cfg(unix)]
use std::thread;

#[cfg(unix)]
use std::os::unix::process::CommandExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const BACKEND_HOST: &str = "127.0.0.1";
const BACKEND_PORT: u16 = 7070;
const BACKEND_BUNDLE_MODE: &str = env!("KRONOS_BACKEND_BUNDLE_MODE");
const WEB_SERVER: &str = env!("KRONOS_WEB_SERVER");
const BACKEND_PID_FILE: &str = "backend.pid";
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

struct BackendProcess {
    child: Mutex<Option<Child>>,
    pid_file: PathBuf,
    startup_detail: String,
    stderr_log: PathBuf,
}

impl BackendProcess {
    fn new(
        child: Option<Child>,
        pid_file: PathBuf,
        startup_detail: String,
        stderr_log: PathBuf,
    ) -> Self {
        Self {
            child: Mutex::new(child),
            pid_file,
            startup_detail,
            stderr_log,
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

fn bundled_backend_candidates(app: &tauri::App) -> Vec<PathBuf> {
    if cfg!(debug_assertions) {
        return Vec::new();
    }

    let Ok(resource_dir) = app.path().resource_dir() else {
        return Vec::new();
    };
    let executable_name = if cfg!(windows) {
        "kronos_webui_backend.exe"
    } else {
        "kronos_webui_backend"
    };
    vec![
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
}

fn bundled_config_dir(project_root: &Path) -> PathBuf {
    project_root.join("config")
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

fn backend_log_path(user_dir: &Path, filename: &str) -> PathBuf {
    user_dir.join("logs").join(filename)
}

fn log_stdio(user_dir: &Path, filename: &str) -> Stdio {
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

fn tail_log(path: &Path, max_bytes: usize) -> String {
    let Ok(content) = fs::read(path) else {
        return String::new();
    };
    let start = content.len().saturating_sub(max_bytes);
    String::from_utf8_lossy(&content[start..])
        .trim()
        .to_string()
}

#[cfg(unix)]
fn configure_backend_command(command: &mut Command) {
    command.process_group(0);
}

#[cfg(windows)]
fn configure_backend_command(command: &mut Command) {
    command.creation_flags(CREATE_NO_WINDOW);
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

fn start_backend(app: &tauri::App) -> (Option<Child>, String) {
    let user_dir = user_data_dir(app);
    cleanup_stale_backend(&user_dir);

    if is_backend_running() {
        return (
            None,
            format!("{BACKEND_HOST}:{BACKEND_PORT} 已有后端进程监听"),
        );
    }

    let project_root = bundled_project_root(app);
    let source_config_dir = bundled_config_dir(&project_root);
    let backend_candidates = bundled_backend_candidates(app);

    if let Some(backend_exe) = backend_candidates
        .iter()
        .find(|path| path.exists())
        .cloned()
    {
        let mut command = Command::new(&backend_exe);
        configure_backend_command(&mut command);
        command
            .current_dir(&project_root)
            .env("KRONOS_PROJECT_ROOT", &project_root)
            .env("KRONOS_USER_DIR", &user_dir)
            .env("KRONOS_DESKTOP", "tauri")
            .env("KRONOS_SOURCE_CONFIG_DIR", &source_config_dir)
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
                (
                    Some(child),
                    format!("已启动内置后端：{}", backend_exe.display()),
                )
            }
            Err(error) => {
                eprintln!("Failed to start bundled Kronos backend: {error}");
                (
                    None,
                    format!("无法启动内置后端 {}：{error}", backend_exe.display()),
                )
            }
        };
    }

    let backend_entry = if WEB_SERVER == "robyn" {
        project_root.join("webui").join("run_robyn.py")
    } else {
        project_root.join("webui").join("app.py")
    };
    if !backend_entry.exists() {
        let checked_paths = backend_candidates
            .iter()
            .map(|path| path.display().to_string())
            .collect::<Vec<_>>()
            .join("\n");
        let checked_paths = if checked_paths.is_empty() {
            "（无法解析资源目录）"
        } else {
            &checked_paths
        };
        let detail = format!(
            "未找到内置后端。源码入口：{}\n检查过的打包路径：\n{checked_paths}",
            backend_entry.display()
        );
        eprintln!("{detail}");
        return (None, detail);
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
        return (
            None,
            "未找到 Python 3.11 或更高版本，无法启动开发后端".to_string(),
        );
    };

    args.push(backend_entry.to_string_lossy().to_string());

    let mut command = Command::new(&program);
    configure_backend_command(&mut command);
    command
        .args(args)
        .current_dir(project_root)
        .env("KRONOS_DESKTOP", "tauri")
        .env("KRONOS_USER_DIR", &user_dir)
        .env("KRONOS_SOURCE_CONFIG_DIR", &source_config_dir)
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
            (
                Some(child),
                format!("已使用 {program} 启动开发后端：{}", backend_entry.display()),
            )
        }
        Err(error) => {
            eprintln!("Failed to start Kronos backend: {error}");
            (None, format!("无法启动开发后端 {program}：{error}"))
        }
    }
}

#[tauri::command]
fn backend_diagnostics(backend: tauri::State<'_, BackendProcess>) -> String {
    let process_detail = match backend.child.lock() {
        Ok(mut child_slot) => match child_slot.as_mut() {
            Some(child) => match child.try_wait() {
                Ok(Some(status)) => format!("内置后端已提前退出（{status}）"),
                Ok(None) => "内置后端进程仍在运行，但 HTTP 服务尚未就绪".to_string(),
                Err(error) => format!("无法读取内置后端进程状态：{error}"),
            },
            None if is_backend_running() => {
                format!("{BACKEND_HOST}:{BACKEND_PORT} 有进程监听，但工作台接口未就绪")
            }
            None => "内置后端进程没有启动".to_string(),
        },
        Err(_) => "无法读取内置后端进程状态".to_string(),
    };

    let stderr_tail = tail_log(&backend.stderr_log, 4000);
    let mut detail = format!(
        "{process_detail}\n{}\n错误日志：{}",
        backend.startup_detail,
        backend.stderr_log.display()
    );
    if !stderr_tail.is_empty() {
        detail.push_str("\n\n最近错误：\n");
        detail.push_str(&stderr_tail);
    }
    detail
}

/// 弹窗去抖状态：记录上次因失焦隐藏的时刻，用于区分「点击托盘想关闭」与「失焦自动收起」。
struct PopupState {
    last_hidden: Mutex<Option<Instant>>,
}

/// 显示并聚焦主窗（菜单「打开控制台」/ 关窗后再唤起都走这里）。
fn show_main(app: &tauri::AppHandle) {
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.unminimize();
        let _ = main.show();
        let _ = main.set_focus();
    }
}

/// 锚定到托盘位置并显示弹窗。
fn show_popup(popup: &tauri::WebviewWindow) {
    use tauri_plugin_positioner::{Position, WindowExt};
    let _ = popup.move_window(Position::TrayCenter);
    let _ = popup.show();
    let _ = popup.set_focus();
}

/// 左键托盘：可见→隐藏；隐藏→显示。带 250ms 去抖，避免与失焦隐藏竞争导致闪烁/双触。
fn toggle_popup(app: &tauri::AppHandle) {
    let Some(popup) = app.get_webview_window("tray-popup") else {
        return;
    };
    if popup.is_visible().unwrap_or(false) {
        let _ = popup.hide();
        return;
    }
    if let Some(state) = app.try_state::<PopupState>() {
        if let Ok(guard) = state.last_hidden.lock() {
            if let Some(hidden_at) = *guard {
                if hidden_at.elapsed() < Duration::from_millis(250) {
                    // 本次点击正是刚触发失焦隐藏的那次 —— 视为「关闭」，不再弹出。
                    return;
                }
            }
        }
    }
    show_popup(&popup);
}

/// 弹窗 JS 调用：显示+聚焦主窗并导航到后端路由（个股分析/形态/报告等），随后收起弹窗。
#[tauri::command]
fn open_main(app: tauri::AppHandle, route: String) {
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.unminimize();
        let _ = main.show();
        let _ = main.set_focus();
        let route = if route.starts_with('/') {
            route
        } else {
            format!("/{route}")
        };
        let url = format!("http://{BACKEND_HOST}:{BACKEND_PORT}{route}");
        // route 仅来自内置 tray.html（页面名 + 6 位代码），对单引号做转义以防注入。
        let safe = url.replace('\'', "%27");
        let _ = main.eval(&format!("window.location.assign('{safe}')"));
    }
    if let Some(popup) = app.get_webview_window("tray-popup") {
        let _ = popup.hide();
    }
}

/// 弹窗 JS 调用：收起面板（点击跳转后顺手隐藏）。
#[tauri::command]
fn hide_popup(app: tauri::AppHandle) {
    if let Some(popup) = app.get_webview_window("tray-popup") {
        let _ = popup.hide();
    }
}

/// 前端调用：在系统默认浏览器中打开 URL（解决 WKWebView 下 target=_blank 被拦截的问题）。
#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    let url = if url.starts_with("http://") || url.starts_with("https://") {
        url
    } else {
        return Err(format!("不支持的协议: {url}"));
    };
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("无法打开浏览器: {e}"))?;
    }
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(["/c", "start", "", &url])
            .spawn()
            .map_err(|e| format!("无法打开浏览器: {e}"))?;
    }
    #[cfg(target_os = "linux")]
    {
        std::process::Command::new("xdg-open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("无法打开浏览器: {e}"))?;
    }
    Ok(())
}

/// 构建托盘图标 + 右键菜单（打开控制台 / 刷新行情 / 退出）。
#[cfg(desktop)]
fn build_tray(app: &tauri::App) -> tauri::Result<()> {
    use tauri::menu::{MenuBuilder, MenuItemBuilder};
    use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};

    let open_console = MenuItemBuilder::with_id("open_console", "打开控制台").build(app)?;
    let refresh = MenuItemBuilder::with_id("refresh", "刷新行情").build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "退出 Lumo Trade").build(app)?;
    let menu = MenuBuilder::new(app)
        .item(&open_console)
        .item(&refresh)
        .separator()
        .item(&quit)
        .build()?;

    let mut builder = TrayIconBuilder::with_id("kronos-tray")
        .tooltip("Lumo Trade 行情台")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open_console" => show_main(app),
            "refresh" => {
                let _ = app.emit_to("tray-popup", "tray://refresh", ());
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // 缓存托盘坐标，供 positioner 锚定弹窗。
            tauri_plugin_positioner::on_tray_event(tray.app_handle(), &event);
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                toggle_popup(tray.app_handle());
            }
        });

    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_positioner::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            open_main,
            hide_popup,
            open_url,
            backend_diagnostics
        ])
        .setup(|app| {
            let user_dir = user_data_dir(app);
            let (backend_child, startup_detail) = start_backend(app);
            let backend = BackendProcess::new(
                backend_child,
                backend_pid_path(&user_dir),
                startup_detail,
                backend_log_path(&user_dir, "backend.stderr.log"),
            );
            app.manage(backend);
            app.manage(PopupState {
                last_hidden: Mutex::new(None),
            });

            #[cfg(desktop)]
            build_tray(app)?;
            Ok(())
        })
        .on_window_event(|window, event| match event {
            // D1：关主窗 ×→ 隐藏常驻（后端继续跑），不再杀后端。
            WindowEvent::CloseRequested { api, .. } if window.label() == "main" => {
                api.prevent_close();
                let _ = window.hide();
            }
            // 弹窗失焦自动收起（菜单栏应用标准行为），并记录时刻供左键去抖。
            WindowEvent::Focused(false) if window.label() == "tray-popup" => {
                let _ = window.hide();
                if let Some(state) = window.app_handle().try_state::<PopupState>() {
                    if let Ok(mut guard) = state.last_hidden.lock() {
                        *guard = Some(Instant::now());
                    }
                }
            }
            _ => {}
        })
        .build(tauri::generate_context!())
        .expect("error while building Kronos Tauri application");

    app.run(|app_handle, event| {
        match event {
            // macOS：主窗已被 D1 改成关=隐藏，全窗隐藏后点 Dock 图标只会触发
            // Reopen 事件——不处理它 Dock 就「点不开」，只剩托盘「控制台」能唤回。
            // 这里与托盘 open_main 同款：唤醒 + 前置主窗。
            #[cfg(target_os = "macos")]
            RunEvent::Reopen { .. } => {
                if let Some(main) = app_handle.get_webview_window("main") {
                    let _ = main.unminimize();
                    let _ = main.show();
                    let _ = main.set_focus();
                }
            }
            // 仅「真正退出」（菜单退出 / Cmd+Q）才杀后端；关窗已改为隐藏常驻（见 D1）。
            RunEvent::ExitRequested { .. } | RunEvent::Exit => {
                app_handle.state::<BackendProcess>().stop();
            }
            _ => {}
        }
    });
}
