# tests/test_scoring_config_path.py
"""scoring_config_path 统一读写路径：env 覆盖 > user 目录(首次从仓库播种) 。"""
from __future__ import annotations

import json

import pytest

from webui.services import paths


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    user = tmp_path / "user"
    monkeypatch.setenv("KRONOS_PROJECT_ROOT", str(repo))
    monkeypatch.setenv("KRONOS_USER_DIR", str(user))
    monkeypatch.delenv("KRONOS_SCORING_CONFIG", raising=False)
    return repo, user


def test_env_override_wins(isolated_dirs, tmp_path, monkeypatch):
    override = tmp_path / "custom.json"
    monkeypatch.setenv("KRONOS_SCORING_CONFIG", str(override))
    assert paths.scoring_config_path() == override


def test_seeds_user_copy_from_repo_config(isolated_dirs):
    repo, user = isolated_dirs
    seed = {"rating_thresholds": {"S": 85}}
    (repo / "config" / "scoring_runtime_config.json").write_text(
        json.dumps(seed), encoding="utf-8")

    resolved = paths.scoring_config_path()
    assert resolved == user / "config" / "scoring_runtime_config.json"
    assert json.loads(resolved.read_text(encoding="utf-8")) == seed


def test_existing_user_copy_not_overwritten(isolated_dirs):
    repo, user = isolated_dirs
    (repo / "config" / "scoring_runtime_config.json").write_text("{\"a\": 1}", encoding="utf-8")
    user_cfg = user / "config" / "scoring_runtime_config.json"
    user_cfg.parent.mkdir(parents=True)
    user_cfg.write_text("{\"b\": 2}", encoding="utf-8")

    resolved = paths.scoring_config_path()
    assert resolved == user_cfg
    assert json.loads(resolved.read_text(encoding="utf-8")) == {"b": 2}


def test_no_repo_config_returns_user_path(isolated_dirs):
    repo, user = isolated_dirs
    resolved = paths.scoring_config_path()
    assert resolved == user / "config" / "scoring_runtime_config.json"
    assert not resolved.exists()  # 无种子可播,返回可写目标路径


def test_scorer_reads_unified_path(isolated_dirs, monkeypatch):
    """opportunity_scorer 启动时按统一路径读取运行时配置。"""
    repo, user = isolated_dirs
    cfg = {"rating_thresholds": {"S": 90}}
    user_cfg = user / "config" / "scoring_runtime_config.json"
    user_cfg.parent.mkdir(parents=True)
    user_cfg.write_text(json.dumps(cfg), encoding="utf-8")

    from analysis.opportunity_scorer import OpportunityScorer
    scorer = OpportunityScorer.__new__(OpportunityScorer)
    scorer.RATING_THRESHOLDS = dict(OpportunityScorer.RATING_THRESHOLDS)
    scorer.DIMENSION_WEIGHTS = dict(OpportunityScorer.DIMENSION_WEIGHTS)
    scorer.EXCLUSION_RULES = dict(OpportunityScorer.EXCLUSION_RULES)
    scorer._load_runtime_config()
    assert scorer.RATING_THRESHOLDS["S"] == 90
