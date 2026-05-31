fn main() {
    println!("cargo:rerun-if-env-changed=KRONOS_BACKEND_BUNDLE_MODE");
    println!("cargo:rerun-if-env-changed=KRONOS_WEB_SERVER");
    let bundle_mode =
        std::env::var("KRONOS_BACKEND_BUNDLE_MODE").unwrap_or_else(|_| "lite".to_string());
    let web_server = std::env::var("KRONOS_WEB_SERVER").unwrap_or_else(|_| "robyn".to_string());
    println!("cargo:rustc-env=KRONOS_BACKEND_BUNDLE_MODE={bundle_mode}");
    println!("cargo:rustc-env=KRONOS_WEB_SERVER={web_server}");
    tauri_build::build()
}
