#!/usr/bin/env python3
"""直接使用已有CSV数据运行4轮参数优化（跳过报告解析和网络获取）"""
import os, sys, pandas as pd, numpy as np

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from scripts.rebuild_and_optimize import (
    DEFAULT_PARAMS, score_row, evaluate, objective,
    round1_single_scan, round2_refinement, round3_combo_search,
    round4_threshold_search, print_final_results
)

print("=" * 70)
print("  直接使用已有CSV数据 - 4轮参数优化")
print("=" * 70)

# 加载已有数据
csv_path = os.path.join(project_root, 'results', 'backtest_rebuilt_20260305_update.csv')
df = pd.read_csv(csv_path)
print(f"  加载数据: {len(df)} 条, {df['report_date'].nunique()} 个日期")

# 去重
df = df.sort_values('filename', ascending=False).drop_duplicates(
    subset=['code', 'report_date'], keep='first'
).sort_values(['report_date', 'rank']).reset_index(drop=True)
print(f"  去重后: {len(df)} 条")

# 只保留有收益的数据
df_valid = df[df['return_5d'].notna()].copy()
print(f"  有效数据: {len(df_valid)} 条, {df_valid['report_date'].nunique()} 个日期")
print(f"  日期范围: {df_valid['report_date'].min()} ~ {df_valid['report_date'].max()}")

# 基线
params = dict(DEFAULT_PARAMS)
base_result = evaluate(df_valid, params)
print(f"\n  v15基线: wr={base_result['wr']:.1f}%, avg={base_result['avg']:+.2f}%, "
      f"n={base_result['n']}, top_wr={base_result['top_wr']:.1f}%")

# Round 1: 单参数扫描
params, improvements = round1_single_scan(df_valid, params)
r1 = evaluate(df_valid, params)
print(f"\n  第1轮后: wr={r1['wr']:.1f}%, avg={r1['avg']:+.2f}%, n={r1['n']}")

# Round 2: 精细化
params = round2_refinement(df_valid, params)
r2 = evaluate(df_valid, params)
print(f"\n  第2轮后: wr={r2['wr']:.1f}%, avg={r2['avg']:+.2f}%, n={r2['n']}")

# Round 3: 组合搜索
params = round3_combo_search(df_valid, params)
r3 = evaluate(df_valid, params)
print(f"\n  第3轮后: wr={r3['wr']:.1f}%, avg={r3['avg']:+.2f}%, n={r3['n']}")

# Round 4: 阈值搜索
best_threshold = round4_threshold_search(df_valid, params)

# 最终结果
print_final_results(df_valid, params, best_threshold)

# 输出参数变化摘要
print("\n" + "=" * 70)
print("  v16参数变化总结 (相对v15)")
print("=" * 70)
changes = []
for k, v in params.items():
    if v != DEFAULT_PARAMS.get(k):
        changes.append((k, DEFAULT_PARAMS.get(k), v))
if changes:
    for name, old, new in sorted(changes):
        print(f"  {name}: {old} -> {new}")
    print(f"\n  共 {len(changes)} 个参数变化")
else:
    print("  (v15已是最优，无需变化)")
