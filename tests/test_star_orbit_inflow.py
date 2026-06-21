"""星轨图谱成分股「主力买入」兜底回归测试。

背景: 东财 ``ulist.np`` 不返回 f62(主力净流入)、``clist`` 又常被限流,导致成分股
表「主力买入」整列「—」。修复是用 Tushare ``moneyflow_dc`` 兜底,但其 ``net_amount``
单位是**万元**(而板块 ``moneyflow_ind_dc`` 与东财 f62 都是元),必须 ×1e4 归一到元,
否则 2.12 亿会被显示成「+2万」。这里把单位换算与兜底合并逻辑钉死,防止回归。
"""
import pandas as pd

from webui.services import star_orbit_service as s


class _FakePro:
    """伪 Tushare pro,moneyflow_dc 回固定一日全市场(net_amount 单位万元)。"""

    def __init__(self, df: pd.DataFrame):
        self._df = df

    def moneyflow_dc(self, trade_date=None):  # noqa: D401 - 测试桩
        return self._df


def _reset_inflow_cache():
    s._inflow_cache.update(ts=0.0, by_code={})


def test_tushare_inflow_table_converts_wan_to_yuan(monkeypatch):
    """moneyflow_dc.net_amount(万元)→ 元: 寒武纪 21161.96 万 → 2.116196e8 元 → 「+2.12亿」。"""
    _reset_inflow_cache()
    df = pd.DataFrame([
        {"ts_code": "688256.SH", "net_amount": 21161.96},   # 万元
        {"ts_code": "002579.SZ", "net_amount": 33146.15},
    ])
    from data_store import tushare_client
    monkeypatch.setattr(tushare_client, "get_pro", lambda: _FakePro(df))
    monkeypatch.setattr(tushare_client, "recent_trade_dates", lambda n=20, exchange="SSE": ["2026-06-18"])

    table = s._tushare_inflow_table()
    assert table["688256"] == round(21161.96 * 1e4, 2) == 211619600.0
    # 末端口径: 与东财 f62 / _money_text 一致
    assert s._money_text(table["688256"]) == "+2.12亿"
    assert s._money_text(table["002579"]) == "+3.31亿"


def test_tushare_inflow_filters_and_normalizes_codes(monkeypatch):
    """按 6 位代码过滤,不在表里的代码不返回。"""
    _reset_inflow_cache()
    monkeypatch.setattr(s, "_tushare_inflow_table",
                        lambda: {"688256": 211619600.0, "002579": 331461500.0})
    got = s._tushare_inflow(["688256.SH", "002579", "999999"])
    assert got == {"688256": 211619600.0, "002579": 331461500.0}


def test_quote_overlay_backfills_inflow_when_realtime_missing(monkeypatch):
    """实时报价拿不到 f62(东财/腾讯都缺)时,_quote_overlay 用 Tushare 补主力净流入。"""

    class _Boom:  # 让东财 ulist.np 与腾讯两条网络路径都立即失败 → out 为空
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            raise RuntimeError("network down in test")

    monkeypatch.setattr(s.httpx, "Client", _Boom)
    monkeypatch.setattr(s, "_tushare_inflow",
                        lambda codes: {"688256": 211619600.0})

    out = s._quote_overlay(["688256", "002579"])
    # 688256 被 Tushare 兜底补上主力净流入(价/涨幅仍为 None)
    assert out["688256"]["main_net_inflow"] == 211619600.0
    assert out["688256"]["price"] is None
    # 002579 既无实时报价也不在兜底表里 → 不应凭空出现
    assert "002579" not in out


def test_money_text_unit_contract():
    """护栏: 元口径下的亿/万阈值(防止有人误把单位改回万元)。"""
    assert s._money_text(211619600.0) == "+2.12亿"
    assert s._money_text(-4444672.0) == "-444万"   # 板块 BK1101 实测口径
    assert s._money_text(None) == ""
