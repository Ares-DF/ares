# Ares desktop shell (Tauri) — Track D / D3

Rust/Tauri v2 replacement for the Electron wrapper (`../electron/`). See
[`../docs/TRACK_D_PLAN.md`](../docs/TRACK_D_PLAN.md) (D3) for the full design.

## Why this is small

The Ares backend already serves the UI + API + WebSockets **same-origin**
(`docs/REMOTE.md`). So this shell uses **Option A**: it spawns the backend, waits
for `/api/v1/health`, then opens a webview pointed straight at
`http://127.0.0.1:8000`. That removes the three hardest parts of `electron/main.js`
— the static file server, the `/api` proxy, and the WebSocket upgrade-forwarding.
What remains:

- **Backend lifecycle** — spawn `uvicorn app.main:app` with the same env Electron
  used (`HOST`/`PORT`/`ARES_AUTH`/`ARES_ADMIN_PASSWORD`), health-poll, restart.
- **Remote Access commands** — `remote_get` / `remote_set` back the existing
  `window.aresDesktop` API the React `RemoteAccessPanel` calls; an init script
  shims `window.aresDesktop` + `window.electronAPI` so **the frontend needs zero
  changes**, and seeds `localStorage['ares.token']` when remote auth is on so the
  desktop skips the login screen.

## Status: scaffold — not yet compiled

There was no Rust toolchain in the env where this was written, so the code is
**unverified**. First steps on a dev machine:

```bash
# 1. toolchain + Tauri CLI
curl https://sh.rustup.rs -sSf | sh
cargo install tauri-cli --version '^2'

# 2. generate the app icons (referenced by tauri.conf.json -> bundle.icon)
cd src-tauri && cargo tauri icon ../frontend/public/icon.png

# 3. type-check, then run
cargo check
cd .. && ./start-desktop-tauri.sh     # = cargo tauri dev
```

### v2 API spots most likely to need a tweak during `cargo check`
- `WebviewUrl::External(url.parse().unwrap())` — confirm the expected `Url` type.
- `Emitter` / `Manager` trait imports for `.emit()` / `.get_webview_window()`.
- `app.path().app_config_dir()` return shape.
- Loading an **external** URL requires the capability `remote.urls` entry (already
  set in `capabilities/default.json`) for `invoke` to work from that origin.

## Still TODO (tracked in the plan)
- **D3.3** — first-run venv/pip + `npm run build` with a live splash log (the
  splash already listens for `ares://status` / `ares://log` events).
- **D3.5** — app menu (export/purge), forced dark mode, geolocation (GeoClue)
  parity, single-instance.
- **D3.6/3.7** — bundler CI for AppImage/deb/nsis/dmg; ship alongside Electron,
  then default to Tauri.

## Layout
```
src-tauri/
├── Cargo.toml              deps (tauri 2, serde, ureq)
├── build.rs                tauri_build::build()
├── tauri.conf.json         v2 config; frontendDist = dist-shell (splash only)
├── capabilities/default.json   window + IPC perms, incl. remote.urls for loopback
├── dist-shell/index.html   boot splash (real UI loads from the backend)
└── src/main.rs             backend lifecycle + remote commands + init-script shim
```
