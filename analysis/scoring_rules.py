#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
共享打分规则核心 (sim/live 统一) — v24
=====================================
背景: `scripts/simulate_v5_backtest.py`(回测) 与 `analysis/opportunity_scorer.py`(生产)
此前是两套独立规则, 漂移到 14+ 处分歧, 最严重的是 chase_risk 方向相反
(sim ≥80 罚 15 vs live ≥75 奖 4)。本模块是唯一的"事后奖惩"规则来源,
两侧都消费同一套 RULESET + 纯函数, 参数改动只改这里。

v24 改动 (依据 docs/superpowers/specs/2026-06-10-pc-and-scoring-optimization-analysis.md §4,
数据 results/backtest_rebuilt_20260407_204957.csv 1489行/77交易日):
1. 恢复 chg3d 重罚: ≥12 罚12, ≥18 罚15 (chg3d[10,18): 213/31.9%wr; ≥18: 136/30.1%/-5.06%)
2. chase 分段罚: 40-60 罚5 / 60-80 罚12 / ≥80 罚15; 移除 live 的 chase≥75 +4 / ≥50 +2 奖励
   (chase[60,80): 106/28.3%/-2.44%, 比 ≥80 还差, 中段是惩罚空档)
3. 移除 zt_high_chase_bonus (v17 涨停+chase≥50 加8; 该子群 210/35.2%/-2.86%,
   劣于涨停&chase<50 的 167/37.1%/-0.63%)
4. quant<50 奖励加 sector<55 门控 (无门控跨期退化 63.3%→40.8%; 加门控 63/58.7%/+4.14%);
   sector 缺失视为不满足门控
5. 新增 RSI≥80 × chase≥60 组合罚 -10 (全场最差大子群 105/26.7%/-6.99%)

v25 改动 (2026-07-09, 新接入主力资金 moneyflow_dc + 期指多空 CFFEX 前20席位,
因子取数统一走 analysis/factor_history.py, 历史回填 scripts/backfill_factor_history.py;
同数据集 1487 行剔 degraded, 稳定性=前/后半窗方向一致):
1. 新增 main_outflow 罚: 当日主力净流入率 <= -5% 罚 10
   (187/29.4%wr/-3.09%; 前半 38.0% vs 基线 42.3%, 后半 19.5% vs 38.4%)
2. 新增 main_inflow 奖: 2% <= 净流入率 < 5% 奖 4 (温和吸筹带, 122/46.7%/+1.51%;
   前半 44.4%/+2.17, 后半 48.5%/+0.99 双半窗同向; 注意 >5% 极端流入≈基线, 不奖)
3. 新增 fut_bear 罚(市场门控): 四品种(IF/IH/IC/IM)前20席位净持仓 3 日滚动净变动
   <= -8000 张(≈窗口 P20)时全场罚 10 (267样本 前半 34.8% vs 42.3%, 后半 25.9% vs 38.4%;
   网格 6/8/10 单调改善取 10 = 常规规则尺度上限; 15 仍走强但属旋钮边界且 live
   有 25 分惩罚上限会截断, 防过拟合不取)
4. 关闭 net_buy/buy_count 梯度奖(sim 的 sim_net_buy_gradient=0 + live v21 块删除):
   当前全量数据全面反向 — buy>=10: 37.1%wr, >=12: 29.9%, >=14: 19.4%(却拿+10),
   双半窗一致低于基线; 关闭后 A>B 倒挂修复(45.1%<50.0% → 63%>52%),
   [82,85) 断层 32%→50%+ 同步修复 (v21 "buy>=10=55%wr" 系旧小样本结论)
5. rsi_pullback_pen 4→0: n=379(打了25%的行) 触发组 40.9% ≈ 未触发 40.1%,
   双半窗 Δ+0.8/+0.4, 惩罚无区分度 → 停用
6. sim_tech_high_pen 3→0: 触发组 45.5% 反而高于未触发 39.6%, 方向反转 → 停用
   落选: main_in_days3 连续流入天数(39-40% 全平坦无信号)、期指净多回补奖励(前半不成立)、
   净空×追高交叉罚(前半 n=13 样本不足, 两条独立罚已自然叠加)、
   rsi_overbought/qs_high 软化(对分层零影响, 维持原值观察)

v25 终版回测 (同数据集 1487 行剔 degraded):
  B+: 235/55.7%wr/+2.30% (v24: 338/49.7%/+1.44)
  三段走窗 B+ wr: 53.8 / 63.4 / 54.5 全>50%; A>B ✓; 评分桶单调违例 0;
  新因子独立增量(关梯度奖后对照): B+ wr 52.2→55.7, 近半窗 avg +1.47→+2.23

使用方式:
    from analysis.scoring_rules import evaluate_shared_rules, RULESET, RULESET_VERSION
    hits = evaluate_shared_rules({'rsi': 82, 'chase_risk': 65, ...})
    penalty = shared_penalty(hits); bonus = shared_bonus(hits)

设计约定:
- 因子缺失 (None/NaN) 的规则一律不触发 (不伪造数据);
  唯一例外按 v24#4: quant<50 奖励在 sector 缺失时同样不触发 (门控不满足)。
- 只打分不淘汰 (用户偏好): 本模块只输出加减分明细, 不输出剔除指令。
- "sim-only" 参数 (sim_ 前缀) 仅由回测器消费, 在此登记以便单点审计:
  * sim_score_high_threshold / 渐进惩罚 max(15,(score-76)*1.2):
    原始评分过高反指标 (score>=90 仅 25%wr), live 侧已有 单调性约束 + quant封顶 等
    机制承担同类职责, 故不进 live。
  * sim_tech_high_pen: tech>=80 在回测 B 级是负向 (wr=34.6%), live v21 已移除, 维持 sim-only。
  * sim_adj_cap=95: ≥95 上限保护 (≥95 wr 42.86% < ≥85 的 61.76%)。
  * 净买入梯度奖励 (net_buy>=4..12 → +3..+16): live 侧由
    _compute_total_score_quant_buy_bonus + buy_count 梯度 (走 headroom) 承担, 不重复。
- "live 在别处实现" 的规则 (live 牛股 Pattern 块已覆盖, live 调用时 skip):
  * zt_low_chase / strong_low_chase / momentum_start
- live 移除的旧分歧规则 (统一到本模块的 sim 验证语义):
  * RSI 60-80 区 +3 奖励 (live v22 私有, 回测无证据, 删)
  * chase≥75/+4, chase≥50/+2 奖励 (v24#2 方向冲突源头, 删)
  * 涨停+chase≥50 +8 (v24#3, 两侧都删)
"""

import math
from typing import Dict, FrozenSet, Iterable, List, NamedTuple, Optional

RULESET_VERSION = 'v25'

RULESET: Dict[str, float] = {
    # ===== RSI 分区 =====
    'rsi_extreme_pen': 25,        # rsi >= 85
    'rsi_overbought_pen': 15,     # 80 <= rsi < 85
    'rsi_pullback_pen': 0,        # 50 < rsi < 60 [v25停用: n=379 触发组≈未触发, 无区分度]
    'rsi_golden_bonus': 4,        # 40 <= rsi <= 50 (黄金区, 52.5%wr/+2.79%)
    'rsi_oversold_bonus': 5,      # rsi < 35

    # ===== 当日涨幅 =====
    'day_chg_20_pen': 25,         # day_change >= 20 暴涨
    'zt_lianban_pen': 5,          # 涨停(>=9.5) 且 3日>=15 连板; 首板不罚 (53.8%wr/+1.73%)
    'day_chg_7_pen': 3,           # 7 <= day_change < 9.5
    'day_chg_5_pen': 5,           # 5 <= day_change < 7

    # ===== 短期涨幅 (v24#1 恢复重罚) =====
    'chg5d_25_pen': 25,           # change_5d > 25
    'chg5d_20_pen': 10,           # 20 < change_5d <= 25
    'chg3d_18_pen': 15,           # change_3d >= 18  [v24#1]
    'chg3d_12_pen': 12,           # 12 <= change_3d < 18  [v24#1]

    # ===== 追高风险 (v24#2 分段罚, 无任何 chase 奖励) =====
    'chase_80_pen': 15,           # chase >= 80
    'chase_60_pen': 12,           # 60 <= chase < 80 (中段惩罚空档修复)
    'chase_40_pen': 5,            # 40 <= chase < 60

    # ===== 组合风险 =====
    'rsi80_chase60_pen': 10,      # [v24#5] rsi>=80 且 chase>=60 (105/26.7%/-6.99%)
    'rsi80_3d10_pen': 10,         # rsi>80 且 chg3d>10
    'chg5d15_rsi72_pen': 10,      # chg5d>15 且 rsi>72

    # ===== 量化分极端值 =====
    'qs_95_pen': 18,              # quant_score >= 95 极端共识反指标
    'qs_90_pen': 12,              # 90 <= quant_score < 95 (33%wr/-3.53%)
    'qs_low_bonus': 5,            # quant_score < 50 少数模型看好 [v24#4 加 sector 门控]
    'qs_low_sector_gate': 55,     # 仅 sector_score < 55 时给 qs_low_bonus; sector 缺失不给

    # ===== 买卖信号 =====
    'sell3_pen': 5,               # sell_signals >= 3 (sell<2: 48.3%wr vs >=2: 36.9%wr)
    'sell0_bonus': 4,             # sell_signals == 0 (53.8%wr/+5.02%)
    'sell0_zt_bonus': 8,          # sell=0 且 涨停 (66.7%wr/+10.97%)
    'signal_crowd_pen': 8,        # buy_signals >= 15 信号拥挤

    # ===== 板块 =====
    'sector_hot_pen': 12,         # sector_score >= 95 过热
    'sector_dead_peak_pen': 10,   # 60-75 死区 U 型连续惩罚峰值 (中心 67.5)

    # ===== 主力资金 (v25, 因子: main_net_rate 当日主力净流入率%) =====
    'main_outflow_pen': 10,       # main_net_rate <= -5 主力大幅流出 (29.4%wr/-3.09%)
    'main_outflow_rate': -5,      # 流出罚触发阈值(%)
    'main_inflow_bonus': 4,       # 2 <= main_net_rate < 5 温和吸筹带 (46.7%wr/+1.51%)

    # ===== 期指多空市场门控 (v25, 因子: fut_net_chg_3d 四品种前20净持仓3日净变动,张) =====
    'fut_bear_pen': 10,           # fut_net_chg_3d <= -8000 净空加深, 全场降温 [v25网格取10]
    'fut_bear_threshold': -8000,  # ≈回测窗口 P20; live 由 factor_history 提供同口径因子

    # ===== 涨停/低chase 奖励 (live 由牛股 Pattern 块实现, 调用时 skip) =====
    'zt_low_chase_bonus': 10,     # 涨停首板 + chase<50 + 非信号拥挤(buy<=8)
    'strong_low_chase_bonus': 12, # day>=7 + chase<40
    'momentum_start_bonus': 5,    # 3<=day<10 + chase<50
    'low_risk_momentum_bonus': 8, # chase<25 + rsi<50

    # ===== sim-only (仅 simulate_v5_backtest 消费, 见模块 docstring) =====
    'sim_score_high_threshold': 76,
    'sim_tech_high_pen': 0,       # [v25停用: 触发组 45.5% 高于未触发 39.6%, 方向反转]
    'sim_adj_cap': 95,
    'sim_net_buy_gradient': 0,    # [v25停用: buy>=10 组 37.1%/>=14 组 19.4%, 奖励负向群体]
}

# live 调用方应 skip 的规则 (其牛股动量 Pattern 块已实现同类逻辑, 避免重复计分)
LIVE_PATTERN_COVERED_RULES: FrozenSet[str] = frozenset({
    'zt_low_chase', 'strong_low_chase', 'momentum_start',
})


class RuleHit(NamedTuple):
    """单条规则命中: delta<0 为惩罚, delta>0 为奖励"""
    rule: str
    delta: float
    detail: str


def _num(value) -> Optional[float]:
    """安全转 float; None/NaN/非数值 → None (规则不触发)"""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def evaluate_shared_rules(factors: Dict, ruleset: Optional[Dict[str, float]] = None,
                          skip: Iterable[str] = ()) -> List[RuleHit]:
    """对成品因子应用 v24 共享奖惩规则, 返回命中明细列表。

    Args:
        factors: 成品因子字典, 支持键:
            rsi, chase_risk, change_3d, change_5d, day_change,
            quant_score, tech_score, sector_score, buy_signals, sell_signals,
            main_net_rate (v25 主力净流入率%), fut_net_chg_3d (v25 期指3日净变动,张)
            缺失/None/NaN 的因子对应规则不触发。
        ruleset: 参数表, 默认 RULESET (v24)。
        skip: 要跳过的规则 id 集合 (如 live 侧的 LIVE_PATTERN_COVERED_RULES)。

    Returns:
        List[RuleHit]; 用 shared_penalty()/shared_bonus() 汇总。
    """
    p = ruleset or RULESET
    skip = frozenset(skip)
    hits: List[RuleHit] = []

    rsi = _num(factors.get('rsi'))
    chase = _num(factors.get('chase_risk'))
    chg_3d = _num(factors.get('change_3d'))
    chg_5d = _num(factors.get('change_5d'))
    day_chg = _num(factors.get('day_change'))
    qs = _num(factors.get('quant_score'))
    sector = _num(factors.get('sector_score'))
    buy_sig = _num(factors.get('buy_signals'))
    sell_sig = _num(factors.get('sell_signals'))

    def add(rule: str, delta: float, detail: str):
        if rule in skip or delta == 0:
            return
        hits.append(RuleHit(rule, float(delta), detail))

    # ===== RSI 分区 =====
    if rsi is not None:
        if rsi >= 85:
            add('rsi_extreme', -p['rsi_extreme_pen'], f"RSI极端超买{rsi:.0f}:-{p['rsi_extreme_pen']:.0f}")
        elif rsi >= 80:
            add('rsi_overbought', -p['rsi_overbought_pen'], f"RSI超买{rsi:.0f}:-{p['rsi_overbought_pen']:.0f}")
        elif 50 < rsi < 60:
            add('rsi_pullback', -p['rsi_pullback_pen'], f"RSI回落区{rsi:.0f}:-{p['rsi_pullback_pen']:.0f}")
        elif 40 <= rsi <= 50:
            add('rsi_golden', p['rsi_golden_bonus'], f"RSI黄金区{rsi:.0f}:+{p['rsi_golden_bonus']:.0f}")
        if rsi < 35:
            add('rsi_oversold', p['rsi_oversold_bonus'], f"RSI超卖{rsi:.0f}:+{p['rsi_oversold_bonus']:.0f}")

    # ===== 当日涨幅 =====
    if day_chg is not None:
        if day_chg >= 20:
            add('day_surge', -p['day_chg_20_pen'], f"暴涨{day_chg:.1f}%:-{p['day_chg_20_pen']:.0f}")
        elif day_chg >= 9.5:
            if chg_3d is not None and chg_3d >= 15:
                add('zt_lianban', -p['zt_lianban_pen'],
                    f"连板涨停{day_chg:.1f}%+3日{chg_3d:.1f}%:-{p['zt_lianban_pen']:.0f}")
            # 涨停首板不惩罚
        elif day_chg >= 7:
            add('day_mid', -p['day_chg_7_pen'], f"中涨{day_chg:.1f}%:-{p['day_chg_7_pen']:.0f}")
        elif day_chg >= 5:
            add('day_small', -p['day_chg_5_pen'], f"小涨{day_chg:.1f}%:-{p['day_chg_5_pen']:.0f}")

    # ===== 短期涨幅 =====
    if chg_5d is not None:
        if chg_5d > 25:
            add('chg5d_surge', -p['chg5d_25_pen'], f"5日暴涨{chg_5d:.1f}%:-{p['chg5d_25_pen']:.0f}")
        elif chg_5d > 20:
            add('chg5d_high', -p['chg5d_20_pen'], f"5日涨{chg_5d:.1f}%:-{p['chg5d_20_pen']:.0f}")

    if chg_3d is not None:
        if chg_3d >= 18:
            add('chg3d_18', -p['chg3d_18_pen'], f"3日急涨{chg_3d:.1f}%:-{p['chg3d_18_pen']:.0f}")
        elif chg_3d >= 12:
            add('chg3d_12', -p['chg3d_12_pen'], f"3日涨{chg_3d:.1f}%:-{p['chg3d_12_pen']:.0f}")

    # ===== 追高风险 (v24#2: 纯惩罚, 无奖励) =====
    if chase is not None:
        if chase >= 80:
            add('chase_80', -p['chase_80_pen'], f"追高极端{chase:.0f}:-{p['chase_80_pen']:.0f}")
        elif chase >= 60:
            add('chase_60', -p['chase_60_pen'], f"追高偏高{chase:.0f}:-{p['chase_60_pen']:.0f}")
        elif chase >= 40:
            add('chase_40', -p['chase_40_pen'], f"追高中等{chase:.0f}:-{p['chase_40_pen']:.0f}")

    # ===== 组合风险 =====
    if rsi is not None and chase is not None and rsi >= 80 and chase >= 60:
        add('rsi80_chase60', -p['rsi80_chase60_pen'],
            f"RSI超买{rsi:.0f}+追高{chase:.0f}:-{p['rsi80_chase60_pen']:.0f}")
    if rsi is not None and chg_3d is not None and rsi > 80 and chg_3d > 10:
        add('rsi80_chg3d10', -p['rsi80_3d10_pen'], f"RSI超买+3日涨:-{p['rsi80_3d10_pen']:.0f}")
    if chg_5d is not None and rsi is not None and chg_5d > 15 and rsi > 72:
        add('chg5d15_rsi72', -p['chg5d15_rsi72_pen'], f"5日涨+RSI偏高:-{p['chg5d15_rsi72_pen']:.0f}")

    # ===== 量化分极端值 =====
    if qs is not None:
        if qs >= 95:
            add('qs_extreme', -p['qs_95_pen'], f"量化分极端{qs:.0f}:-{p['qs_95_pen']:.0f}(过度共识反指标)")
        elif qs >= 90:
            add('qs_high', -p['qs_90_pen'], f"量化分极高{qs:.0f}:-{p['qs_90_pen']:.0f}")
        elif qs < 50:
            # v24#4: 加 sector<55 门控; sector 缺失视为不满足
            if sector is not None and sector < p['qs_low_sector_gate']:
                add('qs_low_gated', p['qs_low_bonus'],
                    f"量化分低{qs:.0f}+板块冷{sector:.0f}:+{p['qs_low_bonus']:.0f}")

    # ===== 买卖信号 =====
    if sell_sig is not None and sell_sig >= 3:
        add('sell3', -p['sell3_pen'], f"卖出信号多{sell_sig:.0f}:-{p['sell3_pen']:.0f}")
    if sell_sig is not None and sell_sig == 0:
        if day_chg is not None and day_chg >= 9.5:
            add('sell0', p['sell0_zt_bonus'], f"涨停+零卖出:+{p['sell0_zt_bonus']:.0f}")
        else:
            add('sell0', p['sell0_bonus'], f"零卖出信号:+{p['sell0_bonus']:.0f}")
    if buy_sig is not None and buy_sig >= 15:
        add('signal_crowd', -p['signal_crowd_pen'], f"信号拥挤{buy_sig:.0f}:-{p['signal_crowd_pen']:.0f}")

    # ===== 板块 =====
    if sector is not None:
        if sector >= 95:
            add('sector_hot', -p['sector_hot_pen'], f"板块过热{sector:.0f}:-{p['sector_hot_pen']:.0f}")
        elif 60 <= sector <= 75:
            # U 型连续函数, peak 在死区中心 67.5, 边界 60/75 自然为 0
            distance = abs(sector - 67.5) / 7.5
            dead_pen = round(p['sector_dead_peak_pen'] * (1 - distance))
            if dead_pen > 0:
                add('sector_dead', -dead_pen, f"板块死区{sector:.0f}:-{dead_pen}")

    # ===== 涨停/低chase 奖励 (v24#3: 移除高chase涨停奖励, 仅保留低chase路径) =====
    if day_chg is not None and chase is not None:
        if day_chg >= 9.5 and chase < 50:
            if not (buy_sig is not None and buy_sig > 8):  # 非信号拥挤
                add('zt_low_chase', p['zt_low_chase_bonus'],
                    f"首板低chase{chase:.0f}:+{p['zt_low_chase_bonus']:.0f}")
        elif day_chg >= 7 and chase < 40:
            add('strong_low_chase', p['strong_low_chase_bonus'],
                f"强势低chase{chase:.0f}:+{p['strong_low_chase_bonus']:.0f}")
        if 3 <= day_chg < 10 and chase < 50:
            add('momentum_start', p['momentum_start_bonus'], f"动量启动:+{p['momentum_start_bonus']:.0f}")
    if chase is not None and rsi is not None and chase < 25 and rsi < 50:
        add('low_risk_momentum', p['low_risk_momentum_bonus'],
            f"低风险动量:+{p['low_risk_momentum_bonus']:.0f}")

    # ===== 主力资金 (v25) =====
    main_rate = _num(factors.get('main_net_rate'))
    if main_rate is not None:
        if main_rate <= p['main_outflow_rate']:
            add('main_outflow', -p['main_outflow_pen'],
                f"主力大幅流出{main_rate:.1f}%:-{p['main_outflow_pen']:.0f}")
        elif 2 <= main_rate < 5:
            add('main_inflow', p['main_inflow_bonus'],
                f"主力温和吸筹{main_rate:.1f}%:+{p['main_inflow_bonus']:.0f}")

    # ===== 期指多空市场门控 (v25) =====
    fut_3d = _num(factors.get('fut_net_chg_3d'))
    if fut_3d is not None and fut_3d <= p['fut_bear_threshold']:
        add('fut_bear', -p['fut_bear_pen'],
            f"期指净空加深{fut_3d:.0f}张:-{p['fut_bear_pen']:.0f}(市场降温)")

    return hits


def shared_penalty(hits: List[RuleHit]) -> float:
    """命中明细中的惩罚总额 (正数)"""
    return sum(-h.delta for h in hits if h.delta < 0)


def shared_bonus(hits: List[RuleHit]) -> float:
    """命中明细中的奖励总额 (正数)"""
    return sum(h.delta for h in hits if h.delta > 0)


def is_degraded_quant(quant_details: Optional[Dict]) -> bool:
    """判断量化评分是否为"数据缺失降级" (而非真实弱信号)。

    仅当 quant_details 明示 degraded 或 error='无历史数据' 时为 True;
    quant 正常算出来的低分不算降级。
    """
    if not isinstance(quant_details, dict):
        return False
    if quant_details.get('degraded'):
        return True
    return quant_details.get('error') == '无历史数据'
