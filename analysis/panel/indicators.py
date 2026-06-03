"""16 项量化指标聚合（4 组）。从 features 派生多空信号，复用 Task 2 特征（DRY）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

GROUPS = ("capital", "technical", "chip", "model")


def _amount_text(v: float) -> str:
    a = abs(v)
    sign = "净流入" if v >= 0 else "净流出"
    if a >= 1e8:
        return f"{sign} {v / 1e8:.2f} 亿"
    if a >= 1e4:
        return f"{sign} {v / 1e4:.2f} 万"
    return f"{sign} {v:.0f}"


def _ind(group: str, key: str, label: str, *, value_text: str, signal: str,
         strength: float, data_status: str = "fresh") -> Dict[str, Any]:
    return {"group": group, "key": key, "label": label, "value_text": value_text,
            "signal": signal, "strength": max(0.0, min(1.0, strength)),
            "data_status": data_status}


def _unavailable(group: str, key: str, label: str, note: str = "数据不足") -> Dict[str, Any]:
    return _ind(group, key, label, value_text=note, signal="neutral",
                strength=0.0, data_status="unavailable")


def _signed(group: str, key: str, label: str, value: Optional[float], *,
            value_text: str, scale: float) -> Dict[str, Any]:
    """正 → up(红/多)，负 → down(绿/空)。strength 按 |value|/scale 归一。"""
    if value is None:
        return _unavailable(group, key, label)
    signal = "up" if value > 0 else ("down" if value < 0 else "neutral")
    return _ind(group, key, label, value_text=value_text, signal=signal,
                strength=min(1.0, abs(value) / scale) if scale else 0.0)


def build_indicators(f: Dict[str, Any]) -> List[Dict[str, Any]]:
    inds: List[Dict[str, Any]] = []

    # ---- 资金面 (4) ----
    main = f.get("main_net_inflow")
    inds.append(_unavailable("capital", "main_capital", "主力资金") if main is None
                else _signed("capital", "main_capital", "主力资金", main,
                             value_text=_amount_text(main), scale=2e8))
    north = f.get("north_delta_30d")
    inds.append(_unavailable("capital", "north_capital", "北向资金") if north is None
                else _signed("capital", "north_capital", "北向资金", north,
                             value_text=f"30 日持股比 {'+' if north >= 0 else ''}{north:.2f}%",
                             scale=1.0))
    elg = f.get("super_large_net")
    inds.append(_unavailable("capital", "super_large", "超大单") if elg is None
                else _signed("capital", "super_large", "超大单", elg,
                             value_text=_amount_text(elg), scale=1.5e8))
    seats = f.get("quant_seat_appearances")
    lhb_net = f.get("lhb_net_inst_buy")
    if seats is None and lhb_net is None:
        inds.append(_unavailable("capital", "lhb_seat", "龙虎榜席位"))
    else:
        s = seats or 0
        net = lhb_net or 0
        if s >= 1 and net > 0:
            sig, strg = "up", min(1.0, 0.4 + s * 0.2)
        elif net < 0:
            sig, strg = "down", min(1.0, abs(net) / 1e8)
        else:
            sig, strg = "neutral", 0.2
        inds.append(_ind("capital", "lhb_seat", "龙虎榜席位",
                         value_text=f"量化席位 {int(s)} 次 / {_amount_text(net)}",
                         signal=sig, strength=strg))

    # ---- 技术面 (6) ----
    rsi = f.get("rsi")
    if rsi is None:
        inds.append(_unavailable("technical", "rsi", "RSI"))
    else:
        sig = "up" if rsi <= 30 else ("down" if rsi >= 70 else "neutral")
        inds.append(_ind("technical", "rsi", "RSI", value_text=f"{rsi:.0f}",
                         signal=sig, strength=abs(rsi - 50) / 50))
    mh = f.get("macd_hist")
    inds.append(_unavailable("technical", "macd", "MACD") if mh is None
                else _signed("technical", "macd", "MACD", mh,
                             value_text=f"柱 {mh:+.3f}", scale=0.5))
    kdj = f.get("kdj_j")
    if kdj is None:
        inds.append(_unavailable("technical", "kdj", "KDJ"))
    else:
        sig = "up" if kdj <= 0 else ("down" if kdj >= 100 else
                                     ("up" if kdj >= 50 else "down"))
        inds.append(_ind("technical", "kdj", "KDJ", value_text=f"J {kdj:.0f}",
                         signal=sig, strength=min(1.0, abs(kdj - 50) / 50)))
    ma = f.get("ma_alignment")
    if ma is None:
        inds.append(_unavailable("technical", "ma_align", "均线排列"))
    else:
        sig = {"bull": "up", "bear": "down", "mixed": "neutral"}[ma]
        text = {"bull": "多头排列", "bear": "空头排列", "mixed": "交织"}[ma]
        inds.append(_ind("technical", "ma_align", "均线排列", value_text=text,
                         signal=sig, strength=0.7 if ma != "mixed" else 0.2))
    boll = f.get("boll_position")
    if boll is None:
        inds.append(_unavailable("technical", "boll", "布林带"))
    else:
        sig = "up" if boll >= 0.8 else ("down" if boll <= 0.2 else "neutral")
        inds.append(_ind("technical", "boll", "布林带",
                         value_text=f"带内位置 {boll * 100:.0f}%",
                         signal=sig, strength=abs(boll - 0.5) * 2))
    vol = f.get("volume_ratio")
    if vol is None:
        inds.append(_unavailable("technical", "volume", "量能"))
    else:
        sig = "up" if vol >= 1.5 else ("down" if vol <= 0.7 else "neutral")
        inds.append(_ind("technical", "volume", "量能", value_text=f"量比 {vol:.2f}",
                         signal=sig, strength=min(1.0, abs(vol - 1.0))))

    # ---- 筹码·机构 (3) ----
    ctrl = f.get("control_degree")
    if ctrl is None:
        inds.append(_unavailable("chip", "control", "控盘度"))
    else:
        sig = "up" if ctrl >= 60 else ("down" if ctrl <= 30 else "neutral")
        inds.append(_ind("chip", "control", "控盘度", value_text=f"{ctrl:.0f}",
                         signal=sig, strength=ctrl / 100))
    hn = f.get("holder_number_trend")
    if hn is None:
        inds.append(_unavailable("chip", "holder_number", "股东户数"))
    else:
        sig = {"down": "up", "up": "down", "flat": "neutral"}[hn]  # 户数减少=筹码集中=多
        text = {"down": "户数减少（筹码集中）", "up": "户数增加（筹码分散）", "flat": "持平"}[hn]
        inds.append(_ind("chip", "holder_number", "股东户数", value_text=text,
                         signal=sig, strength=0.6 if hn != "flat" else 0.1))
    # 重仓基金：单期数据无增减持趋势 → 改用「重仓家数 + 持仓市值」反映机构关注度。
    # 趋势(fund_hold_trend)派生待后续补上一期，命中则优先展示增减持。
    fh_trend = f.get("fund_hold_trend")
    fh_count = f.get("fund_hold_count")
    if fh_trend in ("up", "down", "flat"):
        sig = {"up": "up", "down": "down", "flat": "neutral"}[fh_trend]
        text = {"up": "基金增持", "down": "基金减持", "flat": "持平"}[fh_trend]
        inds.append(_ind("chip", "fund_hold", "重仓基金", value_text=text,
                         signal=sig, strength=0.6 if fh_trend != "flat" else 0.1))
    elif fh_count:
        n = int(fh_count)
        mv = f.get("fund_hold_mv")
        mv_txt = f" · 持仓 {mv / 1e8:.1f} 亿" if mv else ""
        # 重仓家数越多=机构认可度越高(偏多)；零星持有=信息中性。
        sig = "up" if n >= 10 else "neutral"
        inds.append(_ind("chip", "fund_hold", "重仓基金",
                         value_text=f"{n} 只基金重仓{mv_txt}",
                         signal=sig, strength=min(1.0, n / 20)))
    else:
        inds.append(_unavailable("chip", "fund_hold", "重仓基金"))

    # ---- 模型·预测 (3) ----
    ratio = f.get("model_bull_ratio")
    if ratio is None:
        inds.append(_unavailable("model", "model_resonance", "30模型共振"))
    else:
        sig = "up" if ratio >= 0.55 else ("down" if ratio <= 0.4 else "neutral")
        bull = int(f.get("model_bull") or 0)
        bear = int(f.get("model_bear") or 0)
        inds.append(_ind("model", "model_resonance", "30模型共振",
                         value_text=f"多 {bull} / 空 {bear}",
                         signal=sig, strength=abs(ratio - 0.5) * 2))
    # ★ Kronos 预测：模型运行时 Phase 2（暂留降级）
    inds.append(_unavailable("model", "kronos_pred", "★Kronos预测", "Phase 2 接入"))
    # ★ 回测胜率（Phase 3）：当前均线形态的历史 N 日前向胜率（纯 OHLCV）
    bw = f.get("backtest_winrate")
    if not bw or bw.get("winrate") is None:
        inds.append(_unavailable("model", "backtest_winrate", "★回测胜率", "样本不足"))
    else:
        wr = float(bw["winrate"])
        sig = "up" if wr >= 0.55 else ("down" if wr <= 0.45 else "neutral")
        state_txt = {"bull": "多头排列", "bear": "空头排列", "mixed": "均线交织"}.get(bw.get("state"), "全样本")
        conf = "" if bw.get("confident") else " · 基准"
        inds.append(_ind("model", "backtest_winrate", "★回测胜率",
                         value_text=f"{state_txt} {int(bw.get('horizon', 5))}日胜率 {wr * 100:.0f}%（n={int(bw.get('sample', 0))}{conf}）",
                         signal=sig, strength=min(1.0, abs(wr - 0.5) * 2)))

    return inds
