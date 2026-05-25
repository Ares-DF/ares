// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2026 Ares

//! Ares desktop shell (Tauri) — Track D / D3.
//!
//! Replaces the Electron wrapper (`../electron/main.js`). The Ares backend already
//! serves the UI + API + WebSockets **same-origin**, so this shell takes the
//! "Option A" path: spawn the backend, wait for `/api/v1/health`, then point the
//! webview straight at `http://127.0.0.1:<port>`. There is **no static file
//! server, no `/api` proxy, and no WebSocket forwarding** — the hardest part of
//! the Electron main process simply does not exist here.
//!
//! Implemented: backend lifecycle (spawn / health / restart), the Remote Access
//! commands the in-app panel calls (`window.aresDesktop.getRemote/setRemote`), and
//! an init script that shims `window.aresDesktop` / `window.electronAPI` and seeds
//! the admin token (`localStorage['ares.token']`) so the desktop skips the login
//! screen when remote auth is on.
//!
//! TODO(D3.3): first-run venv/pip + `npm run build` with a live splash log.
//! TODO(D3.5): app menu (export/purge), forced dark, geolocation (GeoClue) parity.
//!
//! NOTE: scaffolded without a Rust toolchain in the build env — `cargo check` /
//! `cargo tauri dev` on a dev machine is the immediate next step (D3.1). See
//! `README.md` for the v2 API spots most likely to need a tweak.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

const BACKEND_PORT: u16 = 8000;

#[derive(Clone, Default, Serialize, Deserialize)]
struct RemoteCfg {
    enabled: bool,
    #[serde(default)]
    password: String,
}

#[derive(Serialize)]
struct RemoteStatus {
    enabled: bool,
    has_password: bool,
    port: u16,
    urls: Vec<String>,
}

struct AppState {
    backend: Mutex<Option<Child>>,
    remote: Mutex<RemoteCfg>,
    config_dir: PathBuf,
}

impl AppState {
    fn remote_cfg_path(&self) -> PathBuf {
        self.config_dir.join("remote.json")
    }
    fn load_remote(&self) -> RemoteCfg {
        std::fs::read_to_string(self.remote_cfg_path())
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default()
    }
    fn save_remote(&self, cfg: &RemoteCfg) {
        let _ = std::fs::create_dir_all(&self.config_dir);
        if let Ok(s) = serde_json::to_string(cfg) {
            let _ = std::fs::write(self.remote_cfg_path(), s);
        }
    }
}

/// Best-effort primary LAN IP: connect a UDP socket toward a public address and
/// read the local side (no packets are actually sent). `None` when offline.
fn primary_lan_ip() -> Option<String> {
    use std::net::UdpSocket;
    let sock = UdpSocket::bind("0.0.0.0:0").ok()?;
    sock.connect("8.8.8.8:80").ok()?;
    sock.local_addr().ok().map(|a| a.ip().to_string())
}

/// `src-tauri/` lives at `<repo>/src-tauri`; the backend is `<repo>/backend`.
fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn backend_python(root: &Path) -> String {
    let venv = if cfg!(windows) {
        root.join("backend/.venv/Scripts/python.exe")
    } else {
        root.join("backend/.venv/bin/python")
    };
    if venv.exists() {
        venv.to_string_lossy().into_owned()
    } else if cfg!(windows) {
        "python".into()
    } else {
        "python3".into()
    }
}

fn spawn_backend(state: &AppState) {
    let root = repo_root();
    let cfg = state.remote.lock().unwrap().clone();
    let host = if cfg.enabled { "0.0.0.0" } else { "127.0.0.1" };

    let mut cmd = Command::new(backend_python(&root));
    cmd.current_dir(root.join("backend"))
        .args([
            "-m", "uvicorn", "app.main:app",
            "--host", host,
            "--port", &BACKEND_PORT.to_string(),
        ])
        .env("PYTHONUNBUFFERED", "1")
        .env("PORT", BACKEND_PORT.to_string())
        .env("HOST", host);
    if cfg.enabled {
        cmd.env("ARES_AUTH", "true");
        if !cfg.password.is_empty() {
            cmd.env("ARES_ADMIN_PASSWORD", &cfg.password);
        }
    } else {
        cmd.env("ARES_AUTH", "false");
    }

    match cmd.spawn() {
        Ok(child) => *state.backend.lock().unwrap() = Some(child),
        Err(e) => eprintln!("[ares] backend spawn failed: {e}"),
    }
}

fn stop_backend(state: &AppState) {
    if let Some(mut child) = state.backend.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

fn wait_for_health(timeout: Duration) -> bool {
    let url = format!("http://127.0.0.1:{BACKEND_PORT}/api/v1/health");
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if ureq::get(&url).timeout(Duration::from_millis(900)).call().is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

/// Log in as `admin` and return a bearer token so the loopback desktop window can
/// skip the login screen when remote auth is on. `None` when auth is off.
fn mint_admin_token(cfg: &RemoteCfg) -> Option<String> {
    if !cfg.enabled || cfg.password.is_empty() {
        return None;
    }
    let url = format!("http://127.0.0.1:{BACKEND_PORT}/api/v1/auth/login");
    let body = serde_json::json!({ "username": "admin", "password": cfg.password }).to_string();
    let resp = ureq::post(&url)
        .set("Content-Type", "application/json")
        .timeout(Duration::from_secs(4))
        .send_string(&body)
        .ok()?;
    let v: serde_json::Value = serde_json::from_str(&resp.into_string().ok()?).ok()?;
    v.get("token").and_then(|t| t.as_str()).map(str::to_string)
}

// ── commands the in-app Remote Access panel calls ─────────────────────────────
#[tauri::command]
fn remote_get(state: tauri::State<AppState>) -> RemoteStatus {
    let cfg = state.remote.lock().unwrap().clone();
    let urls = primary_lan_ip()
        .map(|ip| vec![format!("http://{ip}:{BACKEND_PORT}")])
        .unwrap_or_default();
    RemoteStatus {
        enabled: cfg.enabled,
        has_password: !cfg.password.is_empty(),
        port: BACKEND_PORT,
        urls,
    }
}

#[tauri::command]
fn remote_set(state: tauri::State<AppState>, cfg: RemoteCfg) -> Result<RemoteStatus, String> {
    let mut new_cfg = cfg;
    // keep the existing password unless a new one was supplied
    if new_cfg.password.is_empty() {
        new_cfg.password = state.remote.lock().unwrap().password.clone();
    }
    if new_cfg.enabled && new_cfg.password.is_empty() {
        return Err("Set a password before enabling remote access.".into());
    }
    *state.remote.lock().unwrap() = new_cfg.clone();
    state.save_remote(&new_cfg);

    stop_backend(&state);
    std::thread::sleep(Duration::from_millis(400)); // let the port free
    spawn_backend(&state);
    wait_for_health(Duration::from_secs(30));
    Ok(remote_get(state))
}

fn init_script(token: Option<&str>) -> String {
    let seed = token
        .map(|t| {
            format!(
                "try{{localStorage.setItem('ares.token',{});}}catch(e){{}}",
                serde_json::to_string(t).unwrap_or_else(|_| "\"\"".into())
            )
        })
        .unwrap_or_default();
    format!(
        r#"{seed}
window.aresDesktop = {{
  isDesktop: true,
  getRemote: () => window.__TAURI__.core.invoke('remote_get'),
  setRemote: (cfg) => window.__TAURI__.core.invoke('remote_set', {{ cfg }}),
}};
// Electron-compat shims so the frontend's desktop detection + menu hooks keep working.
window.electronAPI = window.electronAPI || {{
  onExportGeoJSON: () => {{}}, onExportPDF: () => {{}}, onPurgeCache: () => {{}},
}};
"#
    )
}

fn open_main_window(handle: &tauri::AppHandle) {
    let ok = wait_for_health(Duration::from_secs(60));
    let token = if ok {
        let cfg = handle.state::<AppState>().remote.lock().unwrap().clone();
        mint_admin_token(&cfg)
    } else {
        None
    };
    let url = format!("http://127.0.0.1:{BACKEND_PORT}");
    let built = WebviewWindowBuilder::new(handle, "main", WebviewUrl::External(url.parse().unwrap()))
        .title("Ares")
        .inner_size(1440.0, 900.0)
        .min_inner_size(900.0, 600.0)
        .maximized(true)
        .initialization_script(init_script(token.as_deref()))
        .build();

    match built {
        Ok(_) => {
            if let Some(splash) = handle.get_webview_window("splash") {
                let _ = splash.close();
            }
        }
        Err(e) => {
            eprintln!("[ares] main window failed: {e}");
            if let Some(splash) = handle.get_webview_window("splash") {
                let _ = splash.emit("ares://status", "Failed to open the main window — see log");
            }
        }
    }
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let config_dir = app
                .path()
                .app_config_dir()
                .unwrap_or_else(|_| PathBuf::from("."));
            let state = AppState {
                backend: Mutex::new(None),
                remote: Mutex::new(RemoteCfg::default()),
                config_dir,
            };
            *state.remote.lock().unwrap() = state.load_remote(); // restore saved choice
            spawn_backend(&state);
            app.manage(state);

            // Boot off-thread so setup() returns promptly; open the real window
            // once the backend is healthy.
            let handle = app.handle().clone();
            std::thread::spawn(move || open_main_window(&handle));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![remote_get, remote_set])
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) && window.label() == "main" {
                if let Some(state) = window.app_handle().try_state::<AppState>() {
                    stop_backend(&state);
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running the Ares desktop shell");
}
