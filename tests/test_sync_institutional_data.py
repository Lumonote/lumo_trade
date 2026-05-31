"""scripts/sync_institutional_data.py —— 市场级机构回填编排（E2）。

纯逻辑（代码归一/列解析/job 去重/退出码）+ run() 的 sync_log 落库与退出码，
全程注入假 provider/adapter，不触网。
"""
from __future__ import annotations

import argparse
import sqlite3

import pandas as pd
import pytest

from analysis.institutional.base import ProviderResult
from data_store.schema import migrate
import scripts.sync_institutional_data as sync


# --------------------------------------------------------------------------- 纯逻辑
def test_to_ts_code_suffix():
    assert sync._to_ts_code("600519") == "600519.SH"
    assert sync._to_ts_code("000001") == "000001.SZ"
    assert sync._to_ts_code("300750") == "300750.SZ"
    assert sync._to_ts_code("830799") == "830799.BJ"


def test_norm_code_accepts_both_forms():
    assert sync._norm_code("600519") == "600519.SH"
    assert sync._norm_code("600519.SH") == "600519.SH"
    assert sync._norm_code(" sz000001 ") == "000001.SZ"  # Sina 前缀也能抽出 6 位归一


def test_provider_jobs_dedupes_holders():
    # top10 与 gdhs 同由 holders 一次抓取 → 去重为单个 job，jgdy 不在其中
    assert sync._provider_jobs(["top10", "gdhs", "lhb"]) == ["holders", "lhb"]
    assert sync._provider_jobs(["jgdy"]) == []


def test_parse_tables_all_and_validation():
    assert set(sync._parse_tables("all")) == set(sync._ALL_TABLES)
    assert sync._parse_tables("lhb,fund") == ["lhb", "fund"]
    with pytest.raises(SystemExit):
        sync._parse_tables("lhb,bogus")


def test_exit_code():
    assert sync._exit_code([]) == 0
    assert sync._exit_code(["ok", "ok"]) == 0
    assert sync._exit_code(["ok", "failed"]) == 1
    assert sync._exit_code(["failed", "failed"]) == 2


def test_normalize_jgdy_defensive():
    df = pd.DataFrame({
        "代码": ["600519", "000001", "bad"],
        "名称": ["贵州茅台", "平安银行", "x"],
        "接待日期": ["2026-05-20", "2026-05-21", "2026-05-22"],
        "调研机构": ["高瓴", "", "睿远"],
        "接待方式": ["特定对象调研", "电话会议", "现场"],
        "接待地点": ["公司", "线上", "公司"],
    })
    rows = sync._normalize_jgdy(df, "2026-05-19")
    assert len(rows) == 2                                  # "bad" 非 6 位被剔除
    assert rows[0]["ts_code"] == "600519.SH"
    assert rows[0]["survey_date"] == "2026-05-20"
    assert rows[0]["inst_name"] == "高瓴"
    # 机构名为空时用「接待方式#序号」占位，保证主键唯一
    assert rows[1]["inst_name"].startswith("电话会议#")


# --------------------------------------------------------------------------- run() 落库
@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = sqlite3.connect(str(tmp_path / "t.sqlite"), isolation_level=None)
    migrate(c)
    getter = lambda: c  # noqa: E731
    from data_store import connection, sync_log_repo, survey_repo, calendar_repo
    monkeypatch.setattr(connection, "get_conn", getter)
    monkeypatch.setattr(sync_log_repo, "get_conn", getter)
    monkeypatch.setattr(survey_repo, "get_conn", getter)
    monkeypatch.setattr(calendar_repo, "get_conn", getter)
    yield c
    c.close()


class _Prov:
    """假 provider：get 返回固定 status；可选 _fetch_and_save 记录调用。"""
    def __init__(self, status, data=None, reason=None, with_fetch=True):
        self._res = ProviderResult(data=data, data_status=status, reason=reason)
        self.fetched = []
        if with_fetch:
            self._fetch_and_save = self.fetched.append  # 记录被回填的 code

    def get(self, code):
        return self._res


def _args(**kw):
    base = dict(codes=None, watchlist=False, all=False, since=None,
                tables="all", limit=None, jgdy_max_days=20)
    base.update(kw)
    return argparse.Namespace(**base)


def _synclog_count(conn, status=None):
    if status:
        return conn.execute("SELECT COUNT(*) FROM sync_log WHERE status=?", (status,)).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0]


def test_run_partial_writes_synclog_and_exit_1(conn):
    providers = {
        "lhb": _Prov("stale", data={"history_90d": [1, 2]}),
        "fund": _Prov("unavailable", reason="重仓基金：数据源熔断中"),
    }
    rc = sync.run(_args(codes="000001,600519", tables="lhb,fund"), providers=providers)
    assert rc == 1                                   # 2 ok + 2 failed
    assert _synclog_count(conn) == 4
    assert _synclog_count(conn, "ok") == 2
    assert _synclog_count(conn, "failed") == 2
    assert providers["lhb"].fetched == ["000001.SZ", "600519.SH"]  # 强制回填两只


def test_run_all_ok_exit_0(conn):
    providers = {"lhb": _Prov("stale", data={"history_90d": []})}
    rc = sync.run(_args(codes="000001", tables="lhb"), providers=providers)
    assert rc == 0
    assert _synclog_count(conn, "ok") == 1


def test_run_all_failed_exit_2(conn):
    providers = {"hsgt": _Prov("unavailable", reason="北向持股：暂无数据")}
    rc = sync.run(_args(codes="000001,600519", tables="hsgt"), providers=providers)
    assert rc == 2
    assert _synclog_count(conn, "failed") == 2


def test_run_jgdy_market_wide(conn):
    from data_store import calendar_repo, survey_repo
    calendar_repo.upsert(["20260520", "20260521"])    # 两个交易日

    class _Adapter:
        def __init__(self):
            self.dates = []
        def fetch(self, key, *a, **kw):
            assert key == "jgdy"
            self.dates.append(kw.get("date"))
            return pd.DataFrame({
                "代码": ["600519"], "接待日期": ["2026-05-20"],
                "调研机构": ["高瓴"], "接待方式": ["特定对象"], "接待地点": ["公司"],
            })

    adapter = _Adapter()
    providers = {"survey": _Prov("unavailable", with_fetch=False)}
    providers["survey"]._adapter = adapter

    rc = sync.run(_args(codes="600519", tables="jgdy", since="2026-05-01"), providers=providers)
    assert rc == 0
    assert set(adapter.dates) == {"20260520", "20260521"}
    # jgdy 行已落 survey 表
    df = survey_repo.get_by_code("600519.SH", since="2026-01-01")
    assert not df.empty
    assert (df["inst_name"] == "高瓴").any()
