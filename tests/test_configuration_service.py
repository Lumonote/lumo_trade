import json
import os

from webui.services.configuration_service import RuntimeConfigurationService


def test_configuration_service_reads_commented_llm_json_and_masks_secret(tmp_path, monkeypatch):
    project = tmp_path / "project"
    user = tmp_path / "user"
    project_config = project / "config"
    project_config.mkdir(parents=True)
    (project_config / "llm_config.json").write_text(
        """
        {
          "enabled_models": ["DeepSeek官方/DeepSeek-V4"],
          "api_keys": {
            // legacy comments should not break desktop settings
            "DeepSeek官方": "sk-1234567890abcdef"
          }
        }
        """,
        encoding="utf-8",
    )
    (project_config / "llm_provider_config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "DeepSeek官方": {
                        "enabled": True,
                        "api_style": "openai",
                        "base_url": "https://api.example.test",
                        "models": {
                            "DeepSeek-V4": {
                                "model_id": "deepseek-v4",
                                "description": "DeepSeek",
                            }
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("KRONOS_CONFIG_DIR", raising=False)

    service = RuntimeConfigurationService(project, user)
    payload = service.settings_payload()

    assert payload["llm"]["configured"] is True
    provider = payload["llm"]["providers"][0]
    assert provider["has_api_key"] is True
    assert provider["api_key_masked"].startswith("sk-1")
    assert provider["models"][0]["selected"] is True
    assert os.environ["KRONOS_CONFIG_DIR"] == str(user / "config")


def test_configuration_service_saves_user_configs_and_environment(tmp_path, monkeypatch):
    project = tmp_path / "project"
    user = tmp_path / "user"
    (project / "config").mkdir(parents=True)
    monkeypatch.delenv("KRONOS_CONFIG_DIR", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    service = RuntimeConfigurationService(project, user)
    llm_result = service.save_llm_settings(
        {
            "enabled_models": ["Provider/Model"],
            "api_keys": {"Provider": "sk-test"},
        }
    )
    tushare_result = service.save_tushare_settings(
        {
            "token": "12345678901234567890",
            "timeout": "45",
            "retry_count": "2",
        }
    )

    llm_path = user / "config" / "llm_config.json"
    tushare_path = user / "config" / "tushare_config.json"
    assert llm_result["success"] is True
    assert tushare_result["success"] is True
    assert json.loads(llm_path.read_text(encoding="utf-8"))["api_keys"]["Provider"] == "sk-test"
    assert json.loads(tushare_path.read_text(encoding="utf-8"))["tushare"]["timeout"] == 45
    assert os.environ["TUSHARE_TOKEN"] == "12345678901234567890"


def test_save_tushare_validates_token_when_requested(tmp_path, monkeypatch):
    """带 verify 标记保存时,用注入的校验器验证 Token,并把结果回传给前端。"""
    project = tmp_path / "project"
    user = tmp_path / "user"
    (project / "config").mkdir(parents=True)
    monkeypatch.delenv("KRONOS_CONFIG_DIR", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    service = RuntimeConfigurationService(
        project, user,
        token_verifier=lambda t: {"ok": False, "error": "您的token不对，请确认。"},
    )
    result = service.save_tushare_settings({"token": "bad-token-20charslong", "verify": True})

    assert result["success"] is True            # 仍然落盘(离线时不因校验失败而拒存)
    assert result["token_check"] == {"ok": False, "error": "您的token不对，请确认。"}


def test_save_tushare_skips_validation_by_default(tmp_path, monkeypatch):
    """默认不校验(不联网),token_check 缺省。"""
    project = tmp_path / "project"
    user = tmp_path / "user"
    (project / "config").mkdir(parents=True)
    monkeypatch.delenv("KRONOS_CONFIG_DIR", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    calls: list[str] = []
    service = RuntimeConfigurationService(
        project, user,
        token_verifier=lambda t: calls.append(t) or {"ok": True, "error": None},
    )
    result = service.save_tushare_settings({"token": "abc1234567"})

    assert calls == []                           # 未触发联网校验
    assert result.get("token_check") is None


def test_configuration_service_shows_provider_templates_without_user_config(tmp_path, monkeypatch):
    project = tmp_path / "project"
    user = tmp_path / "user"
    project_config = project / "config"
    project_config.mkdir(parents=True)
    (project_config / "llm_provider_config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "DeepSeek官方": {
                        "enabled": True,
                        "api_style": "openai",
                        "base_url": "https://api.deepseek.com",
                        "models": {
                            "DeepSeek-V4": {
                                "model_id": "deepseek-v4-pro",
                                "description": "DeepSeek V4",
                            }
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("KRONOS_CONFIG_DIR", raising=False)

    service = RuntimeConfigurationService(project, user)
    payload = service.settings_payload()

    assert payload["llm"]["configured"] is False
    assert payload["llm"]["providers"][0]["name"] == "DeepSeek官方"
    assert payload["llm"]["providers"][0]["models"][0]["full_key"] == "DeepSeek官方/DeepSeek-V4"


def test_desktop_configuration_bootstraps_user_secrets_from_source_config(tmp_path, monkeypatch):
    packaged_root = tmp_path / "Kronos.app" / "Contents" / "Resources"
    source_root = tmp_path / "project"
    user = tmp_path / "user"
    packaged_config = packaged_root / "config"
    source_config = source_root / "config"
    packaged_config.mkdir(parents=True)
    source_config.mkdir(parents=True)
    (source_root / "kronos_app.py").write_text("", encoding="utf-8")
    (packaged_config / "llm_provider_config.json").write_text(
        json.dumps(
            {
                "providers": {
                    "DeepSeek官方": {
                        "enabled": True,
                        "api_style": "openai",
                        "models": {"DeepSeek-V4": {"model_id": "deepseek-v4-pro"}},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (source_config / "llm_config.json").write_text(
        json.dumps(
            {
                "enabled_models": ["DeepSeek官方/DeepSeek-V4"],
                "api_keys": {"DeepSeek官方": "sk-source"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (source_config / "tushare_config.json").write_text(
        json.dumps({"tushare": {"token": "source-token", "timeout": 31, "retry_count": 2}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("KRONOS_DESKTOP", "tauri")
    monkeypatch.setenv("KRONOS_SOURCE_CONFIG_DIR", str(source_config))
    monkeypatch.delenv("KRONOS_CONFIG_DIR", raising=False)

    service = RuntimeConfigurationService(packaged_root, user)
    payload = service.settings_payload()

    assert (user / "config" / "llm_config.json").exists()
    assert (user / "config" / "tushare_config.json").exists()
    assert payload["llm"]["configured"] is True
    assert payload["tushare"]["configured"] is True
    assert payload["tushare"]["token_masked"] == "sour********oken"
