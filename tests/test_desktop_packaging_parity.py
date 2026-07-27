import importlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEVICE_ID = "ABCDEF0123456789"


def test_windows_native_build_uses_same_tauri_pipeline_as_macos():
    batch = (ROOT / "packaging/scripts/build_universal.bat").read_text(encoding="utf-8-sig")
    shell = (ROOT / "packaging/scripts/build_universal.sh").read_text(encoding="utf-8")

    assert "build_backend.py" in batch
    assert "npm run desktop:build -- --bundles nsis" in batch
    assert "--bundles msi" not in batch
    assert "sys.version_info[:2] >= (3, 11)" in batch
    assert "^>=" not in batch
    assert r"%USERPROFILE%\.cargo\bin\cargo.exe" in batch
    assert "Rustlang.Rustup" in batch
    assert r"%ProgramFiles%\nodejs\npm.cmd" in batch
    assert "OpenJS.NodeJS.LTS" in batch
    assert r"node_modules\.bin\tauri.cmd" in batch
    assert "npm install --include=optional" in batch
    assert "vswhere.exe" in batch
    assert "VsDevCmd.bat" in batch
    assert r"Microsoft Visual Studio\2022\BuildTools" in batch
    assert "vcvarsall.bat" in batch
    assert "Microsoft.VisualStudio.Workload.VCTools" in batch
    assert batch.index("where link") < batch.index("build_backend.py")
    assert "kronos_windows.spec" not in batch
    assert "Kronos_Ultra" not in batch
    assert "windows-docker" not in shell
    assert "windows-wine" not in shell
    assert "Kronos_Ultra_Windows_Portable" not in shell


def test_desktop_binary_and_artifact_names_use_lumo_trade():
    tauri = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    cargo = tomllib.loads((ROOT / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    version = json.loads((ROOT / "packaging/version.json").read_text(encoding="utf-8"))

    assert tauri["productName"] == "Lumo Trade"
    assert tauri["mainBinaryName"] == "lumo_trade"
    assert cargo["package"]["name"] == "lumo_trade"
    assert package["name"] == "lumo-trade-desktop"
    assert version["artifact_template"].startswith("lumo_trade_v")


def test_rust_desktop_process_helpers_are_platform_gated():
    source = (ROOT / "src-tauri/src/main.rs").read_text(encoding="utf-8")
    spec = (ROOT / "packaging/scripts/kronos_webui_backend.spec").read_text(encoding="utf-8")

    assert "#[cfg(unix)]\nuse std::thread;" in source
    assert "#[cfg(windows)]\nuse std::os::windows::process::CommandExt;" in source
    assert "const CREATE_NO_WINDOW: u32 = 0x08000000;" in source
    windows_helper = source[source.index("#[cfg(windows)]\nfn configure_backend_command") :]
    windows_helper = windows_helper[: windows_helper.index("\n}\n") + 3]
    assert "command.creation_flags(CREATE_NO_WINDOW);" in windows_helper
    assert "console=True" in spec


def test_bundled_backend_excludes_conflicting_postgres_ssl_libraries():
    spec = (ROOT / "packaging/scripts/kronos_webui_backend.spec").read_text(encoding="utf-8")

    excludes = spec[spec.index("    excludes=[") : spec.index("    noarchive=False")]
    assert '"psycopg2"' in excludes


def test_bundled_backend_import_check_covers_the_active_robyn_stack():
    source = (ROOT / "packaging/scripts/kronos_webui_backend.py").read_text(encoding="utf-8")

    assert '("finetune.license_system.license_codec"' in source
    assert '("webui.app"' not in source


def test_desktop_builds_run_the_bundled_backend_import_check_before_tauri():
    batch = (ROOT / "packaging/scripts/build_universal.bat").read_text(encoding="utf-8-sig")
    shell = (ROOT / "packaging/scripts/build_universal.sh").read_text(encoding="utf-8")

    for script in (batch, shell):
        assert "--import-check" in script
        assert script.index("--import-check") < script.index("desktop:build")


def test_loading_page_surfaces_backend_exit_diagnostics_instead_of_retrying_forever():
    rust = (ROOT / "src-tauri/src/main.rs").read_text(encoding="utf-8")
    loading_page = (ROOT / "desktop/index.html").read_text(encoding="utf-8")

    assert "backend_diagnostics" in rust
    assert ".try_wait()" in rust
    assert "backend.stderr.log" in rust
    assert 'invoke("backend_diagnostics")' in loading_page
    assert "工作台启动失败" in loading_page


def test_legacy_admin_generator_matches_desktop_lumo_protocol(monkeypatch):
    admin_dir = str(ROOT / "license_admin")
    monkeypatch.syspath_prepend(admin_dir)
    sys.modules.pop("license_generator", None)
    generator_module = importlib.import_module("license_generator")
    from webui.services.license_service import generate_license_code

    class Storage:
        def __init__(self):
            self.record = None

        def add_license(self, record):
            self.record = record

    generator = generator_module.LicenseGenerator.__new__(generator_module.LicenseGenerator)
    generator.storage = Storage()
    generator._sign_license_data = lambda _code: "signature"

    code = generator._generate_device_bound_license(DEVICE_ID)

    assert code == generate_license_code(DEVICE_ID)
    assert code.startswith("LUMO-")
    assert generator.storage.record["license_code"] == code


def test_legacy_validator_uses_shared_lumo_device_protocol(monkeypatch):
    license_dir = str(ROOT / "finetune/license_system")
    monkeypatch.syspath_prepend(license_dir)
    sys.modules.pop("license_validator", None)
    validator_module = importlib.import_module("license_validator")
    from finetune.license_system.license_codec import generate_device_license

    validator = validator_module.LicenseValidator.__new__(validator_module.LicenseValidator)
    code = generate_device_license(DEVICE_ID)

    assert validator._validate_license_format(code)
    assert validator._validate_device_bound_license(code, DEVICE_ID)
    assert not validator._validate_license_format("KRONOS-" + code.split("-", 1)[1])


def test_license_configs_use_lumo_trade_protocol():
    config_paths = (
        ROOT / "license_admin/config.json",
        ROOT / "finetune/license_system/config.json",
    )

    for path in config_paths:
        config = json.loads(path.read_text(encoding="utf-8"))
        assert config["product_name"] == "Lumo Trade"
        assert config["license_format"].startswith("LUMO-")


def test_legacy_gui_activation_surface_uses_lumo_protocol():
    source = (ROOT / "tools/launchers/kronos_modern_gui.py").read_text(encoding="utf-8")

    assert "KRONOS-" not in source
    assert "generate_device_license" in source
    assert "verify_device_license" in source


def test_windows_platform_identifiers_use_powershell_when_wmic_is_missing(monkeypatch):
    from finetune.license_system.device_fingerprint import DeviceFingerprint

    fingerprint = DeviceFingerprint()
    fingerprint.system = "Windows"

    def fake_run(command, **_kwargs):
        if command[0].lower().startswith("wmic"):
            raise FileNotFoundError("wmic is not installed")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="UUID=11111111-2222-3333-4444-555555555555\nSerialNumber=BOARD-123\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert fingerprint._get_platform_identifiers() == (
        "11111111-2222-3333-4444-555555555555",
        "BOARD-123",
    )


def test_windows_cpu_id_uses_powershell_when_wmic_is_missing(monkeypatch):
    from finetune.license_system.device_fingerprint import DeviceFingerprint

    fingerprint = DeviceFingerprint()
    fingerprint.system = "Windows"

    def fake_run(command, **_kwargs):
        if command[0].lower().startswith("wmic"):
            raise FileNotFoundError("wmic is not installed")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="ProcessorId=CPU-ABC-123\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert fingerprint._get_cpu_id() == "CPU-ABC-123"


def test_windows_platform_identifiers_use_powershell_when_wmic_returns_empty(monkeypatch):
    from finetune.license_system.device_fingerprint import DeviceFingerprint

    fingerprint = DeviceFingerprint()
    fingerprint.system = "Windows"

    def fake_run(command, **_kwargs):
        if command[0].lower().startswith("wmic"):
            return subprocess.CompletedProcess(command, 0, stdout="\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="UUID=AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE\nSerialNumber=BOARD-456\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert fingerprint._get_platform_identifiers() == (
        "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
        "BOARD-456",
    )


def test_windows_cpu_id_uses_powershell_when_wmic_returns_empty(monkeypatch):
    from finetune.license_system.device_fingerprint import DeviceFingerprint

    fingerprint = DeviceFingerprint()
    fingerprint.system = "Windows"

    def fake_run(command, **_kwargs):
        if command[0].lower().startswith("wmic"):
            return subprocess.CompletedProcess(command, 0, stdout="\n", stderr="")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="ProcessorId=CPU-EMPTY-FALLBACK\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert fingerprint._get_cpu_id() == "CPU-EMPTY-FALLBACK"
