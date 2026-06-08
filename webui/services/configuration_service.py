"""User-editable runtime configuration for the desktop WebUI."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _strip_json_comments(text: str) -> str:
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue

        if char == "/" and next_char == "/":
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue

        result.append(char)
        index += 1

    return "".join(result)


def _deep_merge(defaults: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _mask_secret(value: Any, keep_start: int = 4, keep_end: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= keep_start + keep_end + 3:
        return "*" * len(text)
    return f"{text[:keep_start]}{'*' * 8}{text[-keep_end:]}"


class RuntimeConfigurationService:
    def __init__(self, project_root: Path, user_root: Path, token_verifier=None):
        self.project_root = Path(project_root)
        self.user_root = Path(user_root)
        # token_verifier(token:str) -> {"ok": bool, "error": str|None}; 默认懒加载
        # tushare_client.verify_token(联网 trade_cal 探针)。注入以便离线测试。
        self._token_verifier = token_verifier
        configured_config_dir = os.environ.get("KRONOS_CONFIG_DIR")
        self.user_config_dir = Path(configured_config_dir).expanduser() if configured_config_dir else self.user_root / "config"
        self.project_config_dir = self.project_root / "config"
        self.source_config_dir = self._discover_source_config_dir()
        self.user_config_dir.mkdir(parents=True, exist_ok=True)
        self._bootstrap_desktop_user_configs()
        self.apply_environment()

    @staticmethod
    def default_llm_config() -> dict[str, Any]:
        return {"enabled_models": [], "api_keys": {}}

    @staticmethod
    def default_tushare_config() -> dict[str, Any]:
        return {
            "tushare": {"token": "", "timeout": 30, "retry_count": 3},
            "data_settings": {
                "output_dir": "./data/",
                "file_format": "csv",
                "date_format": "%Y-%m-%d %H:%M:%S",
            },
            "default_params": {
                "freq": "5min",
                "adj": "qfq",
                "start_date": "",
                "end_date": "",
                "data_dir": "./data/tushare_data",
            },
        }

    def apply_environment(self) -> None:
        os.environ["KRONOS_CONFIG_DIR"] = str(self.user_config_dir)
        os.environ.setdefault("KRONOS_DATA_DIR", str(self.user_root / "data"))
        os.environ.setdefault("KRONOS_RESULTS_DIR", str(self.user_root / "results"))
        os.environ.setdefault("KRONOS_LOGS_DIR", str(self.user_root / "logs"))
        os.environ.setdefault("KRONOS_MODELS_DIR", str(self.user_root / "models"))
        token = self.load_tushare_config().get("tushare", {}).get("token", "")
        if token:
            os.environ["TUSHARE_TOKEN"] = str(token)

    def _discover_source_config_dir(self) -> Path | None:
        configured = os.environ.get("KRONOS_SOURCE_CONFIG_DIR") or os.environ.get("KRONOS_LEGACY_CONFIG_DIR")
        if configured:
            config_dir = Path(configured).expanduser()
            if config_dir.name == "config" and config_dir.exists():
                return config_dir
            if (config_dir / "config").exists():
                return config_dir / "config"

        for parent in [self.project_root, *self.project_root.parents]:
            config_dir = parent / "config"
            if parent == self.project_root:
                continue
            if (parent / "kronos_app.py").exists() and config_dir.exists():
                return config_dir
        return None

    def _bootstrap_desktop_user_configs(self) -> None:
        if os.environ.get("KRONOS_DESKTOP") != "tauri":
            return
        if not self.source_config_dir:
            return
        for filename in ("llm_config.json", "tushare_config.json"):
            user_path = self.user_config_dir / filename
            source_path = self.source_config_dir / filename
            if user_path.exists() or not source_path.exists():
                continue
            try:
                payload = self._load_json(source_path)
            except Exception:
                continue
            if payload:
                self._save_user_config(filename, payload)

    def _candidate_paths(self, filename: str) -> list[Path]:
        paths = [self.user_config_dir / filename]
        if self.source_config_dir and self.source_config_dir != self.user_config_dir:
            paths.append(self.source_config_dir / filename)
        if self.project_config_dir not in {self.user_config_dir, self.source_config_dir}:
            paths.append(self.project_config_dir / filename)
        return paths

    def _load_json(self, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            loaded = json.loads(_strip_json_comments(text))
        return loaded if isinstance(loaded, dict) else {}

    def _load_first(self, filename: str, defaults: dict[str, Any]) -> dict[str, Any]:
        for path in self._candidate_paths(filename):
            if not path.exists():
                continue
            try:
                return _deep_merge(defaults, self._load_json(path))
            except Exception:
                continue
        return dict(defaults)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            Path(tmp_name).replace(path)
        finally:
            Path(tmp_name).unlink(missing_ok=True)

    def _save_user_config(self, filename: str, payload: dict[str, Any]) -> Path:
        user_path = self.user_config_dir / filename
        self._write_json(user_path, payload)
        return user_path

    def load_llm_config(self) -> dict[str, Any]:
        cfg = self._load_first("llm_config.json", self.default_llm_config())
        cfg["enabled_models"] = [str(item) for item in cfg.get("enabled_models", []) if item]
        api_keys = cfg.get("api_keys") if isinstance(cfg.get("api_keys"), dict) else {}
        cfg["api_keys"] = {str(key): str(value or "") for key, value in api_keys.items()}
        return cfg

    def load_provider_config(self) -> dict[str, Any]:
        return self._load_first("llm_provider_config.json", {"providers": {}})

    def load_tushare_config(self) -> dict[str, Any]:
        cfg = self._load_first("tushare_config.json", self.default_tushare_config())
        tushare = cfg.get("tushare") if isinstance(cfg.get("tushare"), dict) else {}
        cfg["tushare"] = {
            "token": str(tushare.get("token") or cfg.get("token") or ""),
            "timeout": int(tushare.get("timeout") or cfg.get("timeout") or 30),
            "retry_count": int(tushare.get("retry_count") or cfg.get("retry_count") or 3),
        }
        return _deep_merge(self.default_tushare_config(), cfg)

    def settings_payload(self) -> dict[str, Any]:
        llm = self.load_llm_config()
        provider_config = self.load_provider_config()
        tushare = self.load_tushare_config()
        enabled_models = set(llm.get("enabled_models", []))
        api_keys = llm.get("api_keys", {})
        available_model_keys = set()

        providers = []
        for provider_name, provider_cfg in provider_config.get("providers", {}).items():
            models = []
            for model_key, model_cfg in provider_cfg.get("models", {}).items():
                full_key = f"{provider_name}/{model_key}"
                available_model_keys.add(full_key)
                models.append({
                    "key": model_key,
                    "full_key": full_key,
                    "selected": full_key in enabled_models,
                    "model_id": model_cfg.get("model_id", ""),
                    "description": model_cfg.get("description", ""),
                    "max_tokens": model_cfg.get("max_tokens"),
                })
            provider_key = api_keys.get(provider_name, "")
            providers.append({
                "name": provider_name,
                "enabled": bool(provider_cfg.get("enabled", False)),
                "base_url": provider_cfg.get("base_url", ""),
                "api_style": provider_cfg.get("api_style", "openai"),
                "has_api_key": bool(provider_key),
                "api_key_masked": _mask_secret(provider_key),
                "models": models,
            })

        token = tushare.get("tushare", {}).get("token", "")
        return {
            "llm": {
                "enabled_models": llm.get("enabled_models", []),
                "providers": providers,
                "configured": any(
                    model in available_model_keys and bool(api_keys.get(model.split("/", 1)[0], ""))
                    for model in enabled_models
                ),
                "config_path": str(self.user_config_dir / "llm_config.json"),
            },
            "tushare": {
                "configured": bool(token),
                "token_masked": _mask_secret(token),
                "timeout": tushare.get("tushare", {}).get("timeout", 30),
                "retry_count": tushare.get("tushare", {}).get("retry_count", 3),
                "data_settings": tushare.get("data_settings", {}),
                "default_params": tushare.get("default_params", {}),
                "config_path": str(self.user_config_dir / "tushare_config.json"),
            },
        }

    def save_llm_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load_llm_config()
        enabled = payload.get("enabled_models", current.get("enabled_models", []))
        if isinstance(enabled, str):
            enabled = [enabled]
        api_keys = dict(current.get("api_keys", {}))
        for provider, key in (payload.get("api_keys") or {}).items():
            key_text = str(key or "").strip()
            if key_text:
                api_keys[str(provider)] = key_text
            elif payload.get("clear_empty_api_keys"):
                api_keys.pop(str(provider), None)

        saved = {
            "enabled_models": [str(item) for item in enabled if item],
            "api_keys": api_keys,
        }
        path = self._save_user_config("llm_config.json", saved)
        return {"success": True, "path": str(path), "settings": self.settings_payload()}

    def save_tushare_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load_tushare_config()
        tushare = dict(current.get("tushare", {}))
        token_value = payload.get("token")
        if isinstance(token_value, str) and token_value.strip():
            tushare["token"] = token_value.strip()
        elif payload.get("clear_token"):
            tushare["token"] = ""

        for key, default in (("timeout", 30), ("retry_count", 3)):
            try:
                tushare[key] = max(1, int(payload.get(key, tushare.get(key, default))))
            except (TypeError, ValueError):
                tushare[key] = default

        saved = _deep_merge(current, {"tushare": tushare})
        path = self._save_user_config("tushare_config.json", saved)
        if tushare.get("token"):
            os.environ["TUSHARE_TOKEN"] = str(tushare["token"])
        elif payload.get("clear_token"):
            os.environ.pop("TUSHARE_TOKEN", None)
        # Token 变更后清掉 tushare 客户端缓存,让新 Token 立即生效(否则要重启 App
        # 才能甩掉首次构建的失败客户端 / 失败 latch)。
        try:
            from data_store import tushare_client
            tushare_client.reset()
        except Exception:  # noqa: BLE001 — 重置失败不应阻断保存
            pass
        result = {"success": True, "path": str(path), "settings": self.settings_payload()}
        if payload.get("verify") and tushare.get("token"):
            result["token_check"] = self._verify_token(str(tushare["token"]))
        return result

    def _verify_token(self, token: str) -> dict:
        verifier = self._token_verifier
        if verifier is None:
            from data_store import tushare_client
            verifier = tushare_client.verify_token
        try:
            return verifier(token)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
