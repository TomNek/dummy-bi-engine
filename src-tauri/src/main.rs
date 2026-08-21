//! Semantic Migration Workbench — Tauri v2 desktop shell
//!
//! Lifecycle:
//! 1. Generate a random auth token
//! 2. Spawn the Python sidecar: `dax_backend --port 0 --auth-token <TOKEN>`
//! 3. Read stdout until `PORT=<n>` is emitted
//! 4. Navigate the webview to `http://127.0.0.1:<n>/runtime/ui-react`
//! 5. On window close, kill the sidecar

use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::Manager;

/// State shared with Tauri commands
struct SidecarState {
    child: Option<Child>,
}

/// Stop the whole sidecar process tree. PyInstaller one-file executables spawn
/// an extracted child process on Windows, so killing only the bootloader leaves
/// the backend listening after the desktop window closes.
fn terminate_sidecar(child: &mut Child) {
    #[cfg(target_os = "windows")]
    {
        let pid = child.id().to_string();
        let _ = Command::new("taskkill")
            .args(["/PID", &pid, "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }

    #[cfg(not(target_os = "windows"))]
    let _ = child.kill();

    let _ = child.wait();
}

/// Generate a random hex token for desktop auth
fn generate_token() -> String {
    use rand::RngExt;
    let mut rng = rand::rng();
    let bytes: Vec<u8> = (0..32).map(|_| rng.random()).collect();
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

fn percent_encode_query(value: &str) -> String {
    let mut encoded = String::new();
    for byte in value.as_bytes() {
        match *byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                encoded.push(*byte as char);
            }
            other => encoded.push_str(&format!("%{:02X}", other)),
        }
    }
    encoded
}

/// Find the sidecar binary path.
/// In production: Tauri bundles it via externalBin with target-triple suffix.
/// In dev: falls back to dist/dax_backend.exe or the PyInstaller onedir output.
fn find_sidecar() -> std::path::PathBuf {
    let resource_path = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .unwrap_or_default();

    let candidates = [
        // Production: Tauri externalBin with target triple
        resource_path.join("dax_backend-x86_64-pc-windows-msvc.exe"),
        resource_path.join("dax_backend.exe"),
        resource_path
            .join("binaries")
            .join("dax_backend-x86_64-pc-windows-msvc.exe"),
        resource_path.join("binaries").join("dax_backend.exe"),
        // Dev fallback: PyInstaller onefile output
        std::path::PathBuf::from("dist/dax_backend.exe"),
        // Dev fallback: PyInstaller onedir output
        std::path::PathBuf::from("dist/dax_backend/dax_backend.exe"),
    ];

    for c in &candidates {
        if c.exists() {
            return c.clone();
        }
    }

    // Last resort: assume it's on PATH (dev convenience)
    std::path::PathBuf::from("dax_backend")
}

fn spawn_sidecar(token: &str, workspace: Option<&str>) -> Result<(Child, u16), String> {
    let sidecar_path = find_sidecar();

    let mut args = vec![
        "--port".to_string(),
        "0".to_string(),
        "--auth-token".to_string(),
        token.to_string(),
        "--mode".to_string(),
        "author".to_string(),
    ];
    if let Some(ws) = workspace {
        args.push("--workspace".to_string());
        args.push(ws.to_string());
    }

    let mut command = Command::new(&sidecar_path);
    command.args(&args);
    if let Some(profile) = option_env!("DAX_EMBEDDED_PRODUCT_PROFILE") {
        if !profile.trim().is_empty() {
            command.env("DAX_PRODUCT_PROFILE", profile);
        }
    }

    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("Failed to spawn sidecar at {:?}: {}", sidecar_path, e))?;

    // Read stdout until we see PORT=<n>
    let stdout = child
        .stdout
        .take()
        .ok_or("Failed to capture sidecar stdout")?;
    let reader = BufReader::new(stdout);

    let mut port: Option<u16> = None;
    for line in reader.lines() {
        let line = line.map_err(|e| format!("Failed to read sidecar stdout: {}", e))?;
        if let Some(rest) = line.strip_prefix("PORT=") {
            port = rest.trim().parse().ok();
            if port.is_some() {
                break;
            }
        }
    }

    let port = port.ok_or("Sidecar did not report PORT=<n>")?;
    Ok((child, port))
}

fn main() {
    let token = generate_token();

    // Check for --workspace <path> in CLI args
    let args: Vec<String> = std::env::args().collect();
    let workspace = args
        .iter()
        .position(|a| a == "--workspace")
        .and_then(|i| args.get(i + 1))
        .cloned();

    // Spawn the Python backend sidecar
    let (child, port) =
        spawn_sidecar(&token, workspace.as_deref()).expect("Failed to start backend sidecar");

    println!("[tauri] Backend sidecar running on port {}", port);

    let sidecar_state = SidecarState { child: Some(child) };

    tauri::Builder::default()
        .manage(Mutex::new(sidecar_state))
        .setup(move |app| {
            // Navigate the main window to the backend-served React UI
            let route = match workspace.as_deref() {
                Some(ws) if !ws.trim().is_empty() => {
                    format!("/runtime/ui-react?project={}", percent_encode_query(ws))
                }
                _ => "/runtime/ui-react".to_string(),
            };
            let url = format!("http://127.0.0.1:{}{}", port, route);
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.navigate(url.parse().unwrap());
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Kill sidecar on window close
                if let Ok(mut state) = window.app_handle().state::<Mutex<SidecarState>>().lock() {
                    if let Some(ref mut child) = state.child {
                        terminate_sidecar(child);
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
