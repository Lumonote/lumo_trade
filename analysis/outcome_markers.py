# -*- coding: utf-8 -*-
"""入选后表现标记 (outcome markers) —— 2026-07-29 回溯产物。

背景
====
对「机会挖掘入选 → 之后 10 个交易日实际表现」做了一次全量回溯:
合并 ``results/backtest_rebuilt_*.csv`` 与 SQLite ``backtest_recommendation``
两侧记录, 去重后得 2363 条; 剔除 degraded(因子全 0 的降级 run)后
**1896 条有效样本 / 1100 只个股 / 121 个入选日 / 2025-11-19 ~ 2026-07-28**。
基线: 均值 -2.20% / 胜率 35.6% / 暴涨率(≥+20%) 4.7% / 暴跌率(≤-15%) 11.6%。

核心发现(本模块存在的理由)
==========================
**总分对尾部没有区分度。** 表现最好的 50 只中位分 67.9, 最差的 50 只中位分 67.1;
score≥85 组的暴涨率反而是全场最低(2.4%)。评分体系 v25 优化的是胜率与稳健,
不是尾部爆发力 —— 所以「会不会暴涨 / 会不会暴跌」必须用一组**与总分正交**的
特征单独标出来, 而不是寄希望于把它们塞进总分。

筛掉了什么(同样重要)
--------------------
- **行业/主题共性不可固化**: TOP50 里通信设备占 6 席看似最强(全样本 n=68,
  均值 +4.56%, 暴涨率 19.1%), 但分半检验 H1 +9.17% → H2 -5.08% **反向**;
  发电设备 +5.74% → -9.17% 同样反向。这些是 2025-11~2026-02 军工+光通信
  那一段行情的特征, 不是可复用规律, 故**不做行业标记**。
- **量化分 40-50 奖励区**: H1 超额 +6.72% → H2 -0.87% 反向, 剔除。

保留的标记都通过了 H1/H2 分半同向检验(H1=2025-11~2026-02上, H2=2026-02下~07)。

设计约定
========
- **只提示不改分**: 本模块不参与 ``analysis.scoring_rules`` 的加减分,
  不改变 v25 回测口径, 也不淘汰任何标的(用户偏好: 只打分不淘汰)。
- **因子缺失不伪造**: None/NaN/非数值 → 对应标记不触发。
- **复合警报不重复计分**: ``top_trap``/``sentiment_peak`` 由已计分的分量组成,
  ``weight=0``, 只做醒目提示, 不影响体质净分层。
- **回测数字不进对用户的描述**: 上面这些统计是标定规则的依据、留在注册表里自证,
  但用户看到的是"这只票现在是什么状态、该怎么办", 不是回测报告。
- **措辞合规**: 描述一律只做形态与状态的客观陈述, 不用涨跌预判类字眼、不承诺
  收益, 统一以 ``DISCLAIMER`` 收尾。

使用方式
========
    from analysis.outcome_markers import marker_payload, extract_context, batch_crowding
    payload = marker_payload({'tech_score': 65, 'sector_score': 48, 'rsi': 62},
                             context={'position_pct': 0.82, 'change_20d': 31.5})
    payload['constitution']['grade']   # '偏强体质'
    payload['description']             # 逐条标记的状态判断
    payload['narrative']               # 结合这只票走势的深度描述
    batch_crowding(items)              # 当日入选批次的拥挤度(日级风险)
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, NamedTuple, Optional

MARKERS_VERSION = 'm1'

# 回溯样本基线(全部实证数字的分母, 写死以便描述可自证)
BASELINE: Dict[str, Any] = {
    'sample_n': 1896,
    'stocks': 1100,
    'days': 121,
    'window': '2025-11-19~2026-07-28',
    'avg_return_10d': -2.20,
    'win_rate': 35.6,
    'surge_rate': 4.7,    # 10日 ≥ +20%
    'crash_rate': 11.6,   # 10日 ≤ -15%
}

# 尾部口径(10 个交易日): 用于标定, 不出现在对用户的描述里。
SURGE_THRESHOLD = 20.0
CRASH_THRESHOLD = -15.0

# 合规免责: 描述一律只做形态与状态的客观陈述, 结尾统一附此句。
DISCLAIMER = '以上为公开数据的形态特征描述，仅供参考，不构成投资建议。'

# ============================================================ 标记注册表
# 每个标记回答两件事: 这只票的特征落在**正向侧还是风险侧**(tail), 以及**现在是
# 什么状态、该怎么办**(summary/action)。回测数字(sample_n/avg_return_10d/...)
# 只作标定依据留档与自证, **不进对用户的描述** —— 用户要的是对这只票的判断,
# 不是回测报告。
# weight=1 计入体质净分层(已验证单调); weight=0 为复合警报, 仅提示。
MARKER_SPECS: Dict[str, Dict[str, Any]] = {
    # ---------------------------------------------------------- 正向
    'breakout_gene': {
        'label': '爆发基因',
        'strong_label': '强爆发基因',
        'emoji': '🚀',
        'kind': 'positive',
        'tail': 'upside',
        'weight': 1,
        'rule': '技术分≥60 且 板块分<55(冷门)',
        'summary': '技术面已经先走强，所属板块却还没被市场炒热',
        'action': '属于向上弹性相对较好的一类，仓位仍宜控制，待板块跟上后再评估',
        'sample_n': 359,
        'avg_return_10d': -0.37,
        'win_rate': 38.4,
        'surge_rate': 8.4,
        'crash_rate': 8.1,
        'half_excess': (2.10, 0.69),
        'evidence': '暴涨率 8.4%(基线 4.7% 的 1.8 倍), 暴跌率 8.1% 低于基线 11.6%',
        'note': '技术面已走强、但板块还没被炒热 —— 暴涨样本最集中的位置。'
                '叠加 RSI 55-70 时升级为「强爆发基因」(n=262, 暴涨率 8.8%, 胜率 40.1%)。',
    },
    'clean_sell': {
        'label': '零卖压',
        'emoji': '✅',
        'kind': 'positive',
        'tail': 'upside',
        'weight': 1,
        'rule': '量化模型卖出信号 = 0',
        'summary': '30 个量化模型没有一个发出卖出信号，各条技术路径都找不到离场理由',
        'action': '持有环境相对干净，可按既定计划执行',
        'sample_n': 117,
        'avg_return_10d': 0.26,
        'win_rate': 43.6,
        'surge_rate': 6.0,
        'crash_rate': 6.0,
        'half_excess': (3.53, 1.91),
        'evidence': '全样本唯一 10 日均值为正的分组, 暴跌率 6.0% 仅为基线的一半',
        'note': '两个时段超额均稳定为正(+3.53% / +1.91%), 是最可靠的单一正向特征。',
    },

    # ---------------------------------------------------------- 负向
    'sector_overheat': {
        'label': '板块过热',
        'emoji': '🔥',
        'kind': 'negative',
        'tail': 'downside',
        'weight': 1,
        'rule': '板块分 ≥ 95(板块情绪打满)',
        'summary': '所属板块情绪已经打满，题材进入人尽皆知的阶段',
        'action': '处于情绪高位区，追入的性价比偏低；持仓者留意兑现节奏',
        'sample_n': 143,
        'avg_return_10d': -6.75,
        'win_rate': 25.9,
        'surge_rate': 2.1,
        'crash_rate': 25.2,
        'half_excess': (-7.52, -0.09),
        'evidence': '暴跌率 25.2%(基线 11.6% 的 2.2 倍), 胜率仅 25.9%',
        'note': '典型案例 2026-02-10: 当日 58 只入选中 43% 板块分打满, 传媒影视股扎堆, '
                '10 日后 -18%~-41% 全军覆没。板块分满格是接盘位, 不是买点。',
    },
    'chase_exhaust': {
        'label': '追高透支',
        'emoji': '⚠️',
        'kind': 'negative',
        'tail': 'downside',
        'weight': 1,
        'rule': '追高风险 ≥ 80',
        'summary': '位置、涨幅、连涨天数三项一起压在高位，上涨空间被提前透支',
        'action': '此位置介入只会放大波动、不改善方向，宜等回调企稳后再评估',
        'sample_n': 286,
        'avg_return_10d': -4.30,
        'win_rate': 33.6,
        'surge_rate': 6.6,
        'crash_rate': 24.5,
        'half_excess': (-2.85, -1.07),
        'evidence': '暴跌率 24.5%(基线 11.6% 的 2.1 倍), 胜率 33.6%',
        'note': '追高是波动放大器而非方向信号: 暴涨率 6.6% 也高于基线, '
                '但暴跌率翻倍 —— 赔率不对称, 期望为负。',
    },
    'overbought': {
        'label': '超买风险',
        'emoji': '📈',
        'kind': 'negative',
        'tail': 'downside',
        'weight': 1,
        'rule': 'RSI ≥ 75',
        'summary': 'RSI 进入超买区，短线买盘已经透支',
        'action': '短线不宜追入，持仓者可收紧止盈，等指标回落至中性区间',
        'sample_n': 239,
        'avg_return_10d': -4.84,
        'win_rate': 29.3,
        'surge_rate': 5.4,
        'crash_rate': 22.2,
        'half_excess': (-3.65, -0.42),
        'evidence': '暴跌率 22.2%, 胜率 29.3%; RSI≥80 段胜率进一步跌至 25.6%',
        'note': 'RSI 60-70 是暴涨样本的密集区, 越过 75 后风险收益比迅速反转。',
    },
    'tech_weak': {
        'label': '技术乏力',
        'emoji': '📉',
        'kind': 'negative',
        'tail': 'downside',
        'weight': 1,
        'rule': '技术分 < 45',
        'summary': '均线、量价、指标共振都没跟上，这波更像消息或资金推的脉冲',
        'action': '技术面缺乏承接，冲高回落的概率偏大，参与需严格设置止损',
        'sample_n': 614,
        'avg_return_10d': -3.80,
        'win_rate': 34.2,
        'surge_rate': 2.8,
        'crash_rate': 15.8,
        'half_excess': (-2.83, -0.06),
        'evidence': '暴涨率仅 2.8%(基线 4.7%), 暴跌率 15.8%',
        'note': '技术分是全样本唯一与 10 日收益单调同向的维度'
                '(<30 段 -4.35% → ≥75 段 -0.51%)。技术面没跟上的入选多为消息/资金驱动的脉冲。',
    },
    'sell_pressure': {
        'label': '卖压聚集',
        'emoji': '🔻',
        'kind': 'negative',
        'tail': 'downside',
        'weight': 1,
        'rule': '量化模型卖出信号 ≥ 4',
        'summary': '多个量化模型同时给出卖出信号，离场理由在不同维度上重复出现',
        'action': '属减仓类信号，不宜逆势加仓',
        'sample_n': 390,
        'avg_return_10d': -4.27,
        'win_rate': 31.8,
        'surge_rate': 5.1,
        'crash_rate': 19.7,
        'half_excess': (-3.14, -0.37),
        'evidence': '暴跌率 19.7%(基线 11.6%), 胜率 31.8%',
        'note': '与「零卖压」构成同一维度的两端, 跨度达 4.5 个百分点。',
    },

    # ---------------------------------------------------------- 复合警报(不计净分)
    'top_trap': {
        'label': '顶部陷阱',
        'emoji': '☠️',
        'kind': 'negative',
        'tail': 'downside',
        'weight': 0,
        'rule': '技术分<45 且 追高≥80 且 5日涨幅≥15%',
        'summary': '技术面没走强却已经大涨、追高又打满，纯情绪推动的末端形态',
        'action': '风险特征最集中的组合，宜规避；持仓者优先控制风险',
        'sample_n': 92,
        'avg_return_10d': -7.11,
        'win_rate': 25.0,
        'surge_rate': 7.6,
        'crash_rate': 30.4,
        'half_excess': (-5.87, None),
        'evidence': '暴跌率 30.4%(基线 11.6% 的 2.6 倍), 胜率 25.0%',
        'note': '技术面没走强却已大涨且追高打满 —— 纯情绪推动的末端形态, 最差的组合。',
    },
    'sentiment_peak': {
        'label': '情绪顶',
        'emoji': '☠️',
        'kind': 'negative',
        'tail': 'downside',
        'weight': 0,
        'rule': '板块分≥95 且 RSI≥70',
        'summary': '板块情绪打满叠加个股超买，整个题材同时站在顶部',
        'action': '题材集体退潮的典型位置，宜规避',
        'sample_n': 35,
        'avg_return_10d': -14.89,
        'win_rate': 5.7,
        'surge_rate': 2.9,
        'crash_rate': 57.1,
        'half_excess': (-13.80, None),
        'evidence': '胜率仅 5.7%, 暴跌率 57.1% —— 全样本最差形态',
        'note': '全样本最差的形态, 无一例外来自板块情绪顶部的集体入选。样本 35 例偏少, '
                '但方向与量级都极端一致。',
    },
}

# ============================================================ 体质分层(净标记数 → 实证表现)
# 净分层 = 命中正向(weight=1)数 - 命中负向(weight=1)数; 回测中均值与暴跌率完全单调。
# summary 说这只票整体是什么状态, advice 说该怎么办 —— 都不引用回测数字。
CONSTITUTION_TIERS: List[Dict[str, Any]] = [
    {'min_net': 2,  'grade': '爆发体质', 'sample_n': 27,  'avg_return_10d': 2.63,
     'win_rate': 48.1, 'surge_rate': 22.2, 'crash_rate': 11.1,
     'summary': '多项正向特征同时成立，属于波动弹性较大的一类，上下振幅都会被放大',
     'advice': '适合小仓位博弹性，不适合重仓，且要提前想好止损位'},
    {'min_net': 1,  'grade': '偏强体质', 'sample_n': 376, 'avg_return_10d': -0.82,
     'win_rate': 37.2, 'surge_rate': 6.1, 'crash_rate': 7.5,
     'summary': '正向特征占优，风险特征很少',
     'advice': '可按常规或略积极的仓位对待'},
    {'min_net': 0,  'grade': '中性体质', 'sample_n': 631, 'avg_return_10d': -1.59,
     'win_rate': 35.8, 'surge_rate': 4.3, 'crash_rate': 8.7,
     'summary': '正向特征与风险特征基本抵消，形态无明显偏向',
     'advice': '按常规仓位对待，跟着综合评分走即可'},
    {'min_net': -1, 'grade': '偏弱体质', 'sample_n': 466, 'avg_return_10d': -2.27,
     'win_rate': 36.9, 'surge_rate': 3.4, 'crash_rate': 10.9,
     'summary': '风险特征略多于正向特征',
     'advice': '降低收益预期、减小仓位'},
    {'min_net': -2, 'grade': '风险体质', 'sample_n': 174, 'avg_return_10d': -3.11,
     'win_rate': 36.2, 'surge_rate': 2.9, 'crash_rate': 12.1,
     'summary': '多项风险特征叠加',
     'advice': '严格止损，不宜重仓'},
    {'min_net': -99, 'grade': '高危体质', 'sample_n': 222, 'avg_return_10d': -6.03,
     'win_rate': 27.5, 'surge_rate': 5.4, 'crash_rate': 27.5,
     'summary': '风险特征密集，几乎没有正向特征支撑',
     'advice': '建议规避，不要在这个位置介入'},
]

# ============================================================ 批次拥挤度阈值
# 日级证据: 板块满分占比 <5% 的交易日后续 10 日均值 -1.53%, ≥40% 的 -3.77%;
#          追高占比 <10% 的 -1.29%, 30-50% 的 -3.77%。
CROWDING = {
    'min_items': 8,             # 样本不足不下结论
    'hot_sector_score': 95.0,
    'hot_sector_share': 0.40,
    'high_chase_score': 80.0,
    'high_chase_share': 0.30,
}


class MarkerHit(NamedTuple):
    """单个标记命中。strong 仅 breakout_gene 使用(RSI 黄金带加强)。"""
    key: str
    label: str
    emoji: str
    kind: str          # positive | negative
    tail: str          # surge | crash —— 指向暴涨侧还是暴跌侧
    weight: int        # 1 计入体质净分层, 0 为复合警报
    strong: bool
    detail: str        # 带实际因子值的触发说明
    summary: str       # 这只票现在是什么状态
    action: str        # 该怎么办
    evidence: str      # 标定依据(留档自证, 不进对用户的描述)


def _num(value: Any) -> Optional[float]:
    """安全转 float; None/NaN/bool/非数值 → None (标记不触发)。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _hit(key: str, detail: str, strong: bool = False) -> MarkerHit:
    spec = MARKER_SPECS[key]
    label = spec.get('strong_label', spec['label']) if strong else spec['label']
    return MarkerHit(
        key=key,
        label=label,
        emoji=spec['emoji'],
        kind=spec['kind'],
        tail=spec['tail'],
        weight=int(spec['weight']),
        strong=strong,
        detail=detail,
        summary=spec['summary'],
        action=spec['action'],
        evidence=spec['evidence'],
    )


# ============================================================ 纯函数: 个股标记
def evaluate_markers(factors: Dict[str, Any]) -> List[MarkerHit]:
    """成品因子 → 命中的标记列表(负向在前, 风险优先)。

    Args:
        factors: 与 ``analysis.scoring_rules.evaluate_shared_rules`` 同口径的因子字典,
            使用键: tech_score, sector_score, rsi, chase_risk, sell_signals, change_5d。
            缺失/None/NaN 的因子对应标记不触发。

    Returns:
        List[MarkerHit]; 用 ``constitution()`` 汇总分层, ``describe_markers()`` 出文案。
    """
    factors = factors or {}
    tech = _num(factors.get('tech_score'))
    sector = _num(factors.get('sector_score'))
    rsi = _num(factors.get('rsi'))
    chase = _num(factors.get('chase_risk'))
    sell = _num(factors.get('sell_signals'))
    chg_5d = _num(factors.get('change_5d'))

    positive: List[MarkerHit] = []
    negative: List[MarkerHit] = []

    # ---- 正向 ----
    if tech is not None and sector is not None and tech >= 60 and sector < 55:
        strong = rsi is not None and 55 <= rsi <= 70
        detail = f"技术{tech:.0f}分 + 板块{sector:.0f}分(冷门)"
        if strong:
            detail += f" + RSI{rsi:.0f}(黄金带)"
        positive.append(_hit('breakout_gene', detail, strong=strong))

    if sell is not None and sell == 0:
        positive.append(_hit('clean_sell', "量化模型零卖出信号"))

    # ---- 负向 ----
    if sector is not None and sector >= 95:
        negative.append(_hit('sector_overheat', f"板块分{sector:.0f}(情绪打满)"))
    if chase is not None and chase >= 80:
        negative.append(_hit('chase_exhaust', f"追高风险{chase:.0f}分"))
    if rsi is not None and rsi >= 75:
        negative.append(_hit('overbought', f"RSI {rsi:.0f}"))
    if tech is not None and tech < 45:
        negative.append(_hit('tech_weak', f"技术{tech:.0f}分"))
    if sell is not None and sell >= 4:
        negative.append(_hit('sell_pressure', f"{sell:.0f}个模型发出卖出信号"))

    # ---- 复合警报(不计净分) ----
    if (tech is not None and chase is not None and chg_5d is not None
            and tech < 45 and chase >= 80 and chg_5d >= 15):
        negative.append(_hit(
            'top_trap', f"技术{tech:.0f}分 + 追高{chase:.0f} + 5日涨{chg_5d:.1f}%"))
    if sector is not None and rsi is not None and sector >= 95 and rsi >= 70:
        negative.append(_hit('sentiment_peak', f"板块{sector:.0f}分 + RSI{rsi:.0f}"))

    return negative + positive


# ============================================================ 纯函数: 体质分层
def constitution(hits: Iterable[MarkerHit],
                 net_override: Optional[int] = None) -> Dict[str, Any]:
    """标记命中 → 体质分层(净标记数 → 回溯实证表现)。

    Args:
        hits: ``evaluate_markers`` 的输出。
        net_override: 直接指定净分层(供测试/复盘用), 给出时忽略 hits。
    """
    if net_override is None:
        net = 0
        for hit in hits or ():
            if hit.weight != 1:
                continue
            net += 1 if hit.kind == 'positive' else -1
    else:
        net = int(net_override)

    tier = next(t for t in CONSTITUTION_TIERS if net >= t['min_net'])
    return {
        'net': net,
        'grade': tier['grade'],
        'summary': tier['summary'],
        'advice': tier['advice'],
        'sample_n': tier['sample_n'],
        'avg_return_10d': tier['avg_return_10d'],
        'win_rate': tier['win_rate'],
        'surge_rate': tier['surge_rate'],
        'crash_rate': tier['crash_rate'],
    }


# ============================================================ 纯函数: 文本描述
def describe_markers(hits: Iterable[MarkerHit], max_items: int = 4) -> str:
    """标记命中 → 一段对这只票的判断(负向优先)。

    只讲「现在是什么状态 + 该怎么办」, **不复述回测数字** —— 回测是标定这些
    规则的依据, 不是给用户看的结论。
    """
    hits = list(hits or ())
    if not hits:
        return '正向特征与风险特征均未触发，按常规评分对待'

    parts: List[str] = []
    for hit in hits[:max_items]:
        parts.append(f"{hit.emoji}{hit.label}（{hit.detail}）：{hit.summary}，{hit.action}")
    text = '；'.join(parts)
    if len(hits) > max_items:
        text += f"；另有 {len(hits) - max_items} 项标记未展开"
    return text


def _trend_sentence(context: Dict[str, Any]) -> str:
    """走势定位: 用这只票自己的位置/涨幅/节奏说话。"""
    context = context or {}
    bits: List[str] = []

    position = _num(context.get('position_pct'))
    distance = _num(context.get('distance_from_high'))
    if position is not None:
        # position_pct 在评分链路里是 0~1 的年内分位
        pct = position * 100 if position <= 1.5 else position
        where = '年内高位' if pct >= 80 else '年内中高位' if pct >= 55 \
            else '年内中位' if pct >= 35 else '年内低位'
        piece = f"股价处于{where}（年内分位 {pct:.0f}%"
        if distance is not None:
            piece += f"，距年内高点 {distance:.1f}%"
        bits.append(piece + '）')
    elif distance is not None:
        bits.append(f"距年内高点 {distance:.1f}%")

    moves = []
    for label, key in (('5日', 'change_5d'), ('20日', 'change_20d'), ('60日', 'change_60d')):
        value = _num(context.get(key))
        if value is not None:
            moves.append(f"{label} {value:+.1f}%")
    if moves:
        bits.append('近期涨跌 ' + '、'.join(moves))

    streak = _num(context.get('consecutive_up_days'))
    if streak is not None and streak >= 3:
        bits.append(f"已连涨 {streak:.0f} 天")

    drawdown = _num(context.get('drawdown_from_recent'))
    if drawdown is not None and drawdown >= 5:
        bits.append(f"自近期高点回撤 {drawdown:.1f}%")

    volume_ratio = _num(context.get('volume_ratio'))
    if volume_ratio is not None:
        if volume_ratio >= 1.5:
            bits.append(f"成交显著放量（量比 {volume_ratio:.1f}）")
        elif volume_ratio <= 0.7:
            bits.append(f"成交缩量（量比 {volume_ratio:.1f}）")

    # 评分链路给的是裸值(如 '多头排列'/'金叉'/'一般'/'等待回调'), 单独摆进句子里
    # 读不出说的是哪个维度, 这里补上维度名; '中性'/'一般' 这类无信息量的直接跳过。
    for key, label, skip in (
        ('ma_status', '均线', ('中性',)),
        ('macd_status', 'MACD ', ('中性',)),
        ('vol_price_status', '量价', ('一般',)),
        ('entry_timing', '入场时机：', ()),
    ):
        value = context.get(key)
        if not isinstance(value, str):
            continue
        value = value.strip()
        if not value or value == '—' or value in skip:
            continue
        bits.append(value if value.startswith(label.strip()) else f"{label}{value}")

    sector = context.get('sector_name')
    if isinstance(sector, str) and sector.strip() and sector.strip() != '—':
        bits.append(f"所属板块「{sector.strip()}」")

    return '；'.join(bits)


def narrate(factors: Dict[str, Any],
            context: Optional[Dict[str, Any]] = None,
            hits: Optional[Iterable[MarkerHit]] = None) -> str:
    """这只票的深度描述: 走势定位 → 正向特征 → 风险特征 → 结论。

    与 ``describe_markers`` 的区别: 后者只罗列命中的标记, 本函数把标记放回
    **这只票自己的走势和相关资料**里讲 —— 用户要的是"这只票现在怎么样",
    不是"历史上同类有多少例"。

    措辞按合规要求处理: 只做**形态与状态的客观描述**, 不用涨跌预判类字眼,
    不承诺收益, 结尾统一带免责。

    Args:
        factors: 与 ``evaluate_markers`` 同口径的因子字典。
        context: 走势/相关资料(position_pct、change_20d、consecutive_up_days、
            volume_ratio、ma_status、sector_name 等), 缺失则跳过对应表述。
        hits: 已算好的命中(省一次计算); 不给则内部算。
    """
    hits = list(hits) if hits is not None else evaluate_markers(factors)
    context = context or {}
    paragraphs: List[str] = []

    trend = _trend_sentence(context)
    if trend:
        paragraphs.append(f"【走势定位】{trend}。")

    upside = [h for h in hits if h.tail == 'upside']
    downside = [h for h in hits if h.tail == 'downside']

    if upside:
        paragraphs.append('【正向特征】' + '；'.join(
            f"{h.label}（{h.detail}）—— {h.summary}" for h in upside) + '。')
    if downside:
        paragraphs.append('【风险特征】' + '；'.join(
            f"{h.label}（{h.detail}）—— {h.summary}" for h in downside) + '。')
    if not upside and not downside:
        paragraphs.append('【特征判定】正向特征与风险特征均未触发，'
                          '当前形态没有明显偏向。')

    tier = constitution(hits)
    actions = []
    for hit in hits:
        if hit.action not in actions:
            actions.append(hit.action)
    conclusion = f"【结论】{tier['grade']}：{tier['summary']}，{tier['advice']}"
    if actions:
        conclusion += '。具体到操作：' + '；'.join(actions[:3])
    paragraphs.append(conclusion + '。')
    paragraphs.append(DISCLAIMER)

    return ' '.join(paragraphs)


# ============================================================ 纯函数: 批次拥挤度
def batch_crowding(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """当日入选批次 → 拥挤度(日级风险)。

    实证: 板块分满格占比 <5% 的交易日, 后续 10 日均值 -1.53%; ≥40% 的 -3.77%。
    追高占比 <10% 的 -1.29%; 30~50% 的 -3.77%。
    """
    rows = [r for r in (items or ()) if isinstance(r, dict)]
    total = len(rows)
    if total < CROWDING['min_items']:
        return {
            'crowded': False,
            'insufficient': True,
            'total': total,
            'hot_sector_share': None,
            'high_chase_share': None,
            'summary': f"当日入选仅 {total} 只，样本不足以判断批次拥挤度",
        }

    hot = sum(1 for r in rows
              if (_num(r.get('sector_score')) or -1) >= CROWDING['hot_sector_score'])
    chased = sum(1 for r in rows
                 if (_num(r.get('chase_risk')) or -1) >= CROWDING['high_chase_score'])
    hot_share = hot / total
    chase_share = chased / total

    reasons: List[str] = []
    if hot_share >= CROWDING['hot_sector_share']:
        reasons.append(
            f"{hot_share * 100:.0f}% 的入选标的板块情绪已打满(≥95)，"
            f"当日入选高度集中在情绪高位的题材上"
        )
    if chase_share >= CROWDING['high_chase_share']:
        reasons.append(
            f"{chase_share * 100:.0f}% 的入选标的追高风险≥80，"
            f"当日入选普遍处在已经大涨过的位置"
        )

    crowded = bool(reasons)
    summary = ('批次拥挤提示：' + '；'.join(reasons)) if crowded else (
        f"批次结构均衡：板块满格 {hot_share * 100:.0f}%、追高 {chase_share * 100:.0f}%，均在常态区间"
    )
    return {
        'crowded': crowded,
        'insufficient': False,
        'total': total,
        'hot_sector_share': hot_share,
        'high_chase_share': chase_share,
        'reasons': reasons,
        'summary': summary,
    }


# ============================================================ 纯函数: 因子提取
def extract_factors(stock: Dict[str, Any]) -> Dict[str, Any]:
    """OpportunityDiscovery 的 stock 结果 → 本模块所需的 6 个因子。

    口径与 ``data_store.opportunity_repo.build_items`` 一致:
    chase 优先取 advanced_analysis 的风险指标, 为 0/缺失时回退动量明细。

    **降级 run 的取数失败必须按缺失处理**: ``_score_technical_analysis`` 拿不到
    历史数据时返回 ``(0.0, {'error': ...})``, 直接采信会把"没数据"读成"技术 0 分"
    而错误触发「技术乏力」(标定样本里 degraded 行本就被剔除, 这类值不在适用域内)。
    """
    stock = stock or {}
    scoring = stock.get('scoring_result') or {}
    scores = scoring.get('scores') or {}
    details = scoring.get('details') or {}
    tech = details.get('technical') or {}
    quant = details.get('quantitative') or {}
    price_changes = details.get('price_changes') or {}
    momentum = details.get('momentum') or {}

    tech_failed = bool(tech.get('error'))
    momentum_failed = bool(momentum.get('error'))

    chase = (((scoring.get('advanced_analysis') or {}).get('overall_score') or {})
             .get('risk_metrics') or {}).get('chase_risk_score')
    if not chase:  # 0/None → 回退动量明细(与评分逻辑一致)
        chase = None if momentum_failed else momentum.get('chase_risk_score')

    return {
        'tech_score': None if tech_failed else scores.get('technical'),
        'sector_score': scores.get('sector'),
        'rsi': None if tech_failed else tech.get('RSI'),
        'chase_risk': chase,
        'sell_signals': quant.get('sell_count'),
        'change_5d': price_changes.get('change_5d'),
    }


CONTEXT_KEYS = (
    'position_pct', 'distance_from_high', 'change_5d', 'change_20d', 'change_60d',
    'drawdown_from_recent', 'consecutive_up_days', 'entry_timing',
    'volume_ratio', 'ma_status', 'macd_status', 'vol_price_status', 'sector_name',
)


def extract_context(stock: Dict[str, Any]) -> Dict[str, Any]:
    """OpportunityDiscovery 的 stock 结果 → ``narrate`` 用的走势/相关资料。

    与 ``extract_factors`` 一样, 取数失败的明细整块跳过, 不用降级值编故事。
    """
    stock = stock or {}
    scoring = stock.get('scoring_result') or {}
    details = scoring.get('details') or {}
    tech = details.get('technical') or {}
    momentum = details.get('momentum') or {}

    context: Dict[str, Any] = {}
    if not momentum.get('error'):
        for key in ('position_pct', 'distance_from_high', 'change_5d', 'change_20d',
                    'change_60d', 'drawdown_from_recent', 'consecutive_up_days',
                    'entry_timing'):
            if momentum.get(key) is not None:
                context[key] = momentum[key]
    if not tech.get('error'):
        for src, dst in (('volume_ratio', 'volume_ratio'), ('MA_status', 'ma_status'),
                         ('MACD_status', 'macd_status'), ('vol_price_status', 'vol_price_status')):
            if tech.get(src) is not None:
                context[dst] = tech[src]

    sector = stock.get('sector') or stock.get('industry')
    if sector:
        context['sector_name'] = sector
    return context


# ============================================================ 一站式出参
def marker_payload(factors: Dict[str, Any],
                   context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """成品因子(+可选走势上下文) → 可直接入库/渲染的 JSON 安全结构。

    ``description`` 是标记逐条的状态判断; ``narrative`` 是把标记放回这只票自己的
    走势里讲的深度描述(给了 context 才有实质内容)。两者都不复述回测数字。
    """
    hits = evaluate_markers(factors)
    return {
        'version': MARKERS_VERSION,
        'markers': [
            {
                'key': h.key,
                'label': h.label,
                'emoji': h.emoji,
                'kind': h.kind,
                'tail': h.tail,
                'strong': h.strong,
                'detail': h.detail,
                'summary': h.summary,
                'action': h.action,
            }
            for h in hits
        ],
        'constitution': constitution(hits),
        'description': describe_markers(hits),
        'narrative': narrate(factors, context, hits),
    }
