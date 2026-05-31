#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史报告 → recommendations.csv 批量回填（离线、可复现）
=====================================================
为评分回测优化器扩充近端训练样本。

1. 解析 results/opportunity_top10_*.md（复用 rebuild_and_optimize.parse_all_reports）
   提取每只票的完整因子（score / chase_risk / quant_score / sector_score /
   tech_score / rsi / buy_signals / sell_signals / 涨幅 等）。
2. 同 (code, report_date) 的多份日内报告去重，保留因子最完整的一条
   （并列时取文件名最新的一份）。
3. 与现有 recommendations.csv 取并集：**已存在的 (code, date) 行原样保留**
   （它们来自实盘打分器，含 momentum_pattern 与已结算收益），仅补入历史新行。
4. 对缺收益的新行，**直接从 sqlite OHLCV 离线计算** 1/3/5/10 日前瞻收益
   （复用 auto_backtest.compute_forward_returns + ohlcv_repo.load_dataframe，
   口径与生产 update_returns 完全一致：次日开盘买入、第 N 日收盘卖出，零网络）。
5. 写回 CSV（写前自动时间戳备份），并打印扩样前后对比 + score↔5d 相关性诊断。

**不**触碰评分权重/配置（scoring_runtime_config.json / DIMENSION_WEIGHTS /
chase/quant 逻辑）——那是在另一台机器上并行重调、稍后合并的部分。
本脚本只扩数据、不调参。

用法:
    .venv/bin/python scripts/backfill_history_from_reports.py            # 执行
    .venv/bin/python scripts/backfill_history_from_reports.py --dry-run  # 仅预演
"""

import os
import sys
import shutil
import argparse
import importlib.util
from datetime import datetime

import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CSV = os.path.join(ROOT, 'results', 'backtest', 'recommendations.csv')

# 规范列序（与 auto_backtest.save_recommendations 一致）
COLS = ['report_date', 'rank', 'code', 'name', 'score', 'chase_risk',
        'buy_signals', 'sell_signals', 'rsi', 'day_change', 'change_3d',
        'change_5d', 'sector_score', 'quant_score', 'tech_score',
        'momentum_pattern', 'buy_price', 'return_1d', 'return_3d',
        'return_5d', 'return_10d']
RET_COLS = ['return_1d', 'return_3d', 'return_5d', 'return_10d']


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def norm_code(c):
    """任意形态股票代码 -> 6 位零填充数字串（去 .SH/.SZ 后缀）。"""
    s = str(c).strip().split('.')[0]
    s = ''.join(ch for ch in s if ch.isdigit())
    return s.zfill(6) if s else ''


def corr_report(df, label):
    """只读：打印 score↔5d 相关性与 score>=80 队列表现（不写任何配置）。"""
    d = df.copy()
    d['score'] = pd.to_numeric(d['score'], errors='coerce')
    d['return_5d'] = pd.to_numeric(d['return_5d'], errors='coerce')
    d = d.dropna(subset=['score', 'return_5d'])
    if len(d) < 5:
        print(f"  [{label}] settled(5d)={len(d)} (样本太少)")
        return
    c = d['score'].corr(d['return_5d'])
    hi = d[d['score'] >= 80]
    hi_txt = (f"score>=80 队列 n={len(hi)} 5d均值={hi['return_5d'].mean():+.2f}%"
              if len(hi) else "score>=80 队列 n=0")
    print(f"  [{label}] settled(5d)={len(d)}  score↔5d corr={c:+.3f}  {hi_txt}")


def main():
    ap = argparse.ArgumentParser(description='历史报告批量回填 recommendations.csv（离线）')
    ap.add_argument('--dry-run', action='store_true', help='只预演与诊断，不落盘')
    args = ap.parse_args()

    rao = _load_module(os.path.join(ROOT, 'scripts', 'rebuild_and_optimize.py'), 'rao')
    ab = _load_module(os.path.join(ROOT, 'scripts', 'auto_backtest.py'), 'ab')
    from data_store import ohlcv_repo

    # 1) 现有 CSV
    if os.path.exists(CSV):
        existing = pd.read_csv(CSV, encoding='utf-8-sig')
    else:
        existing = pd.DataFrame(columns=COLS)
    for col in COLS:
        if col not in existing.columns:
            existing[col] = np.nan
    existing = existing[COLS]
    existing_keys = {(norm_code(c), str(d))
                     for c, d in zip(existing['code'], existing['report_date'])}
    print(f"现有: {len(existing)} 行, {existing['report_date'].nunique()} 个日期, "
          f"{len(existing_keys)} 个 (code,date) 键")

    # 2) 解析全部报告 + 同 (code,date) 去重（保留最完整、并列取最新文件）
    parsed = rao.parse_all_reports()
    parsed['code'] = parsed['code'].map(norm_code)
    parsed['_nn'] = parsed.notna().sum(axis=1)
    parsed = (parsed.sort_values(['_nn', 'filename'])
                    .drop_duplicates(['code', 'report_date'], keep='last'))
    print(f"解析去重后 distinct (code,date): {len(parsed)}")

    # 3) 仅取现有 CSV 中尚不存在的历史新键
    is_new = [(norm_code(c), str(d)) not in existing_keys
              for c, d in zip(parsed['code'], parsed['report_date'])]
    new = parsed[is_new].copy()
    print(f"待新增历史行: {len(new)}")

    for col in COLS:
        if col not in new.columns:
            new[col] = np.nan
    new['momentum_pattern'] = '[]'      # 旧报告正文未结构化保存信号原因，留空
    new['buy_price'] = np.nan
    for c in RET_COLS:
        new[c] = np.nan
    new = new[COLS]

    # 4) 离线从 sqlite 计算前瞻收益（口径同生产 update_returns）
    cache = {}
    filled = 0
    for idx, row in new.iterrows():
        code = norm_code(row['code'])
        if code not in cache:
            try:
                cache[code] = ohlcv_repo.load_dataframe(code, '1d')
            except Exception:
                cache[code] = None
        daily = cache[code]
        if daily is None or len(daily) == 0:
            continue
        res = ab.compute_forward_returns(daily, str(row['report_date']))
        if not res:
            continue
        new.at[idx, 'buy_price'] = round(res['buy_price'], 4)
        wrote = False
        for n in (1, 3, 5, 10):
            key = f'return_{n}d'
            if key in res:
                new.at[idx, key] = round(res[key], 4)
                wrote = True
        if wrote:
            filled += 1
    print(f"收益已回填(>=1 档): {filled}/{len(new)} "
          f"(无 sqlite 数据或前瞻不足的行收益留 NaN)")

    # 5) 合并 + 诊断 + 落盘
    merged = pd.concat([existing, new], ignore_index=True)
    merged['code'] = merged['code'].map(norm_code)   # 顺手修复历史前导零丢失
    merged = merged.sort_values(['report_date', 'rank']).reset_index(drop=True)

    print("\n=== score↔return 诊断（只读，未写任何评分配置）===")
    corr_report(existing, 'BEFORE 现有')
    corr_report(merged, 'AFTER  合并')

    settled_after = merged['return_5d'].notna().sum()
    print(f"\n合并结果: {len(existing)} -> {len(merged)} 行 (+{len(merged) - len(existing)}), "
          f"{merged['report_date'].nunique()} 个日期, 含 5d 收益的行 {settled_after}")

    if args.dry_run:
        print("\n[dry-run] 未写文件")
        return

    bak = CSV.replace('.csv', f".backup_{datetime.now():%Y%m%d_%H%M%S}.csv")
    shutil.copy2(CSV, bak)
    print(f"已备份 -> {bak}")
    merged.to_csv(CSV, index=False, encoding='utf-8-sig')
    print(f"已写入 -> {CSV}")


if __name__ == '__main__':
    main()
