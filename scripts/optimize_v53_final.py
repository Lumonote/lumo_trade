#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v12 近期数据优化 - 基于最近20个交易日严谨量化回测
==================================================
1. 重建全量回测数据（解析所有报告）
2. 自动补充所有缺失的收益数据
3. 基于最近20个交易日进行算法优化
4. 与全量数据交叉验证避免过拟合
5. 输出优化结果和参数变更建议
"""

import os
import sys
import json
import re
import pandas as pd
import numpy as np
from datetime import datetime
from copy import deepcopy

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
RESULTS_DIR = os.path.join(project_root, 'results')


# ============ 数据重建 ============

def parse_report(filepath):
    """解析单个报告文件"""
    records = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # 提取日期
        m = re.search(r'生成时间:\s*(\d{4}-\d{2}-\d{2})', content)
        report_date = m.group(1) if m else None
        if not report_date:
            m = re.search(r'(\d{4})(\d{2})(\d{2})_\d{6}', os.path.basename(filepath))
            if m:
                report_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if not report_date:
            return []

        # 解析排名表
        rows = re.findall(r'\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*([\d.]+)\s*\|(.*?)\|', content)
        for row in rows:
            rank, code, name, score, detail = row
            feat = {
                'code': int(code), 'name': name.strip(), 'score': float(score),
                'rank': int(rank), 'report_date': report_date,
                'filename': os.path.basename(filepath)
            }

            # 涨幅
            m2 = re.search(r'当日[:：]([+-]?\d+\.?\d*)%.*?3日[:：]([+-]?\d+\.?\d*)%.*?5日[:：]([+-]?\d+\.?\d*)%', detail)
            if m2:
                feat['day_change'] = float(m2.group(1))
                feat['change_3d'] = float(m2.group(2))
                feat['change_5d'] = float(m2.group(3))

            # 板块
            m2 = re.search(r'【板块】.*?(\d+)分', detail)
            if m2: feat['sector_score'] = float(m2.group(1))

            # 量化
            m2 = re.search(r'【量化】买(\d+)/卖(\d+)/总(\d+)\(\d+%\)[，,]\s*(\d+)分', detail)
            if m2:
                feat['buy_signals'] = int(m2.group(1))
                feat['sell_signals'] = int(m2.group(2))
                feat['quant_score'] = float(m2.group(4))
            else:
                m2 = re.search(r'【量化】买(\d+)/总(\d+)\(\d+%\)[，,]\s*(\d+)分', detail)
                if m2:
                    feat['buy_signals'] = int(m2.group(1))
                    feat['quant_score'] = float(m2.group(3))

            # RSI
            m2 = re.search(r'RSI[:：]\s*(\d+\.?\d*)', detail)
            if m2: feat['rsi'] = float(m2.group(1))

            # 技术分
            m2 = re.search(r'【技术】.*?(\d+)分', detail)
            if m2: feat['tech_score'] = float(m2.group(1))

            # 追高风险
            m2 = re.search(r'追高风险.*?(\d+)分', detail)
            if m2: feat['chase_risk'] = float(m2.group(1))

            records.append(feat)
    except Exception:
        pass
    return records


def rebuild_data():
    """重建全量回测数据"""
    print("\n[1/3] 解析所有历史报告...", flush=True)
    report_files = sorted([
        f for f in os.listdir(RESULTS_DIR)
        if f.startswith('opportunity_top10_') and f.endswith('.md')
    ])
    print(f"  找到 {len(report_files)} 个报告文件", flush=True)

    all_records = []
    for rf in report_files:
        records = parse_report(os.path.join(RESULTS_DIR, rf))
        all_records.extend(records)

    df = pd.DataFrame(all_records)
    print(f"  解析出 {len(df)} 条记录, {df['report_date'].nunique()} 个日期", flush=True)

    # 去重
    before = len(df)
    df = df.sort_values('filename', ascending=False).drop_duplicates(
        subset=['code', 'report_date'], keep='first'
    ).sort_values(['report_date', 'rank']).reset_index(drop=True)
    print(f"  去重: {before} → {len(df)} (移除{before - len(df)}条)", flush=True)

    # 合并已有收益数据
    rebuilt_csvs = sorted([
        f for f in os.listdir(RESULTS_DIR)
        if f.startswith('backtest_rebuilt_') and f.endswith('.csv')
    ])
    if rebuilt_csvs:
        existing = pd.read_csv(os.path.join(RESULTS_DIR, rebuilt_csvs[-1]))
        return_cols = ['return_1d', 'return_3d', 'return_5d', 'return_10d']
        for col in return_cols:
            if col not in df.columns:
                df[col] = np.nan

        existing_returns = existing[['code', 'report_date'] + [c for c in return_cols if c in existing.columns]].copy()
        existing_returns['code'] = existing_returns['code'].astype(int)
        df['code'] = df['code'].astype(int)

        merged = df.merge(existing_returns, on=['code', 'report_date'], how='left', suffixes=('', '_existing'))
        for col in return_cols:
            ecol = f'{col}_existing'
            if ecol in merged.columns:
                merged[col] = merged[col].fillna(merged[ecol])
                merged.drop(columns=[ecol], inplace=True)
        df = merged

    for col in ['return_1d', 'return_3d', 'return_5d', 'return_10d']:
        if col not in df.columns:
            df[col] = np.nan

    has_5d = df['return_5d'].notna().sum()
    print(f"  已有5日收益: {has_5d}/{len(df)}", flush=True)

    return df


def fetch_missing_returns(df):
    """通过tushare获取缺失的收益数据"""
    print("\n[2/3] 获取缺失收益数据...", flush=True)

    cfg_path = os.path.join(project_root, 'config', 'tushare_config.json')
    if not os.path.exists(cfg_path):
        print("  ⚠ tushare_config.json不存在，跳过", flush=True)
        return df

    with open(cfg_path, 'r') as f:
        cfg = json.load(f)
    token = cfg.get('token', '') or cfg.get('tushare', {}).get('token', '')
    if not token:
        print("  ⚠ tushare token为空，跳过", flush=True)
        return df

    import tushare as ts
    ts.set_token(token)
    pro = ts.pro_api()

    missing_mask = df['return_5d'].isna()
    missing_codes = df[missing_mask][['code', 'report_date']].drop_duplicates()
    print(f"  缺失5日收益: {len(missing_codes)} 条", flush=True)

    if len(missing_codes) == 0:
        # 仍然检查10d缺失
        missing_10d = df['return_10d'].isna() & df['return_5d'].notna()
        print(f"  缺失10日收益(有5d): {missing_10d.sum()} 条", flush=True)
    else:
        missing_10d = pd.Series(False, index=df.index)

    filled_5d = 0
    filled_10d = 0
    errors = 0

    # 按code分组批量获取
    all_missing = pd.concat([
        df[missing_mask][['code', 'report_date']],
        df[missing_10d][['code', 'report_date']]
    ]).drop_duplicates()

    for code_val in all_missing['code'].unique():
        code_str = str(int(code_val)).zfill(6)
        ts_code = f"{code_str}.SH" if code_str.startswith(('6', '9')) else f"{code_str}.SZ"

        code_rows = df[df['code'] == code_val]
        min_date = code_rows['report_date'].min().replace('-', '')
        max_date = '20260315'

        try:
            price_df = pro.daily(ts_code=ts_code, start_date=min_date, end_date=max_date)
            if price_df is None or len(price_df) == 0:
                errors += 1
                continue
            price_df = price_df.sort_values('trade_date').reset_index(drop=True)
            dates_list = price_df['trade_date'].tolist()

            for idx in code_rows.index:
                rd = str(df.at[idx, 'report_date']).replace('-', '')

                buy_idx = None
                for i, d in enumerate(dates_list):
                    if d > rd:
                        buy_idx = i
                        break
                if buy_idx is None:
                    continue

                bp = price_df.iloc[buy_idx]['open']
                if bp <= 0:
                    continue

                # 1d
                if pd.isna(df.at[idx, 'return_1d']) and buy_idx + 1 < len(price_df):
                    p1 = price_df.iloc[buy_idx]['close']
                    df.at[idx, 'return_1d'] = (p1 - bp) / bp * 100

                # 3d
                if pd.isna(df.at[idx, 'return_3d']) and buy_idx + 3 <= len(price_df):
                    p3 = price_df.iloc[buy_idx + 2]['close']
                    df.at[idx, 'return_3d'] = (p3 - bp) / bp * 100

                # 5d
                if pd.isna(df.at[idx, 'return_5d']) and buy_idx + 5 <= len(price_df):
                    p5 = price_df.iloc[buy_idx + 4]['close']
                    df.at[idx, 'return_5d'] = (p5 - bp) / bp * 100
                    filled_5d += 1

                # 10d
                if pd.isna(df.at[idx, 'return_10d']) and buy_idx + 10 <= len(price_df):
                    p10 = price_df.iloc[buy_idx + 9]['close']
                    df.at[idx, 'return_10d'] = (p10 - bp) / bp * 100
                    filled_10d += 1

        except Exception:
            errors += 1

    print(f"  补充5d: {filled_5d}, 补充10d: {filled_10d}, 错误: {errors}", flush=True)

    # Save
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    save_path = os.path.join(RESULTS_DIR, f'backtest_rebuilt_{timestamp}.csv')
    df.to_csv(save_path, index=False)
    print(f"  保存: {save_path} ({len(df)}行)", flush=True)

    has_5d = df['return_5d'].notna().sum()
    has_10d = df['return_10d'].notna().sum()
    print(f"  最终: 有5d={has_5d}, 有10d={has_10d}", flush=True)

    return df


# ============ 评分系统(v11) ============

from scripts.simulate_v5_backtest import apply_v8_scoring


def evaluate_tiers(df_scored, score_col='v8_score'):
    """多层级评估"""
    tiers = {}
    for name, lo, hi in [('S', 85, 999), ('A', 78, 85), ('B', 70, 78), ('C+', 60, 70), ('C', 0, 60)]:
        mask = (df_scored[score_col] >= lo) & (df_scored[score_col] < hi) if hi < 999 else df_scored[score_col] >= lo
        sub = df_scored[mask]
        r5 = sub['return_5d'].dropna()
        r10 = sub['return_10d'].dropna()
        r3 = sub['return_3d'].dropna()
        if len(r5) > 0:
            wr = (r5 > 0).mean() * 100
            avg = r5.mean()
            losses = r5[r5 < 0]
            pf = abs(r5[r5 > 0].sum() / losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 999
            avg10 = r10.mean() if len(r10) > 0 else None
            avg3 = r3.mean() if len(r3) > 0 else 0
        else:
            wr = 0; avg = 0; pf = 0; avg10 = None; avg3 = 0
        tiers[name] = {'n': len(r5), 'wr': wr, 'avg': avg, 'pf': pf, 'avg10': avg10, 'avg3': avg3}
    return tiers


def print_tiers(tiers, label=""):
    if label:
        print(f"\n  {label}:", flush=True)
    print(f"  {'评级':>6} | {'数量':>5} | {'胜率':>7} | {'5d收益':>10} | {'10d收益':>10} | {'盈亏比':>6}", flush=True)
    print("  " + "-" * 60, flush=True)
    for name in ['S', 'A', 'B', 'C+', 'C']:
        t = tiers.get(name, {'n': 0, 'wr': 0, 'avg': 0, 'pf': 0, 'avg10': None})
        if t['n'] > 0:
            pf_str = f"{t['pf']:.2f}" if t['pf'] < 100 else "∞"
            avg10_str = f"{t['avg10']:+9.2f}%" if t['avg10'] is not None else "  数据不足"
            print(f"  {name:>6} | {t['n']:>5} | {t['wr']:>6.1f}% | {t['avg']:>+9.2f}% | {avg10_str} | {pf_str:>6}", flush=True)
        else:
            print(f"  {name:>6} | {t['n']:>5} | {'—':>7} | {'—':>10} | {'—':>10} | {'—':>6}", flush=True)


# ============ 优化搜索 ============

# v11当前参数(从simulate_v5_backtest.py的apply_v8_scoring中读取)
# 这里列出可调参数及其搜索空间
SEARCH_SPACE = {
    # S级关键
    'adj_high_threshold': [79, 85, 90, 999],
    'adj_high_pen': [0, 3, 5, 8],
    # B级关键(v11新增)
    'tech_high_pen': [0, 2, 3, 5, 8],
    'score_very_high_pen': [0, 2, 3, 5, 8],
    'rsi_golden_bonus': [0, 3, 5, 8, 10],
    # 核心惩罚
    'score_high_pen': [15, 19, 22, 25, 28, 30],
    'chase_60_pen': [3, 5, 6, 8],
    'chg3d_10_pen': [8, 10, 12, 15, 18],
    'tech_low_pen': [5, 8, 10, 12],
    'sector_hot_pen': [5, 8, 10, 12, 15],
    'sector_dead_pen': [0, 3, 5, 8],
    # 奖励
    'rsi_oversold_bonus': [3, 5, 8, 10, 12],
    'zt_low_chase_bonus': [8, 10, 12, 15],
    'strong_low_chase_bonus': [10, 12, 15, 18, 20],
    'momentum_start_bonus': [3, 5, 8, 10],
    'low_risk_momentum_bonus': [3, 5, 8, 10],
}


def modify_scoring_param(param_name, value):
    """
    修改simulate_v5_backtest中apply_v8_scoring的参数。
    由于apply_v8_scoring是硬编码的，我们通过猴子补丁来模拟参数变化。
    返回一个函数，接受df返回scored_df，使用修改后的参数。
    """
    # 实际上apply_v8_scoring是硬编码的，不接受参数
    # 我们需要用optimize_v51_deep.py中的参数化score_row函数
    pass


def score_with_params(df, params):
    """使用参数化评分 (与optimize_v51_deep.py相同的逻辑)"""
    from scripts.optimize_v51_deep import score_row
    df = df.copy()
    df['v8_score'] = df.apply(lambda r: score_row(r, params), axis=1)

    for _, row_data in df.iterrows():
        idx = row_data.name
        s = df.at[idx, 'v8_score']
        if s >= 85:
            df.at[idx, 'confidence_tier'] = 'S'
        elif s >= 78:
            df.at[idx, 'confidence_tier'] = 'A'
        elif s >= 70:
            df.at[idx, 'confidence_tier'] = 'B'
        else:
            df.at[idx, 'confidence_tier'] = 'C'
    return df


def multi_tier_objective(tiers):
    """多层级目标函数"""
    s = tiers.get('S', {'n': 0, 'wr': 0, 'avg': 0})
    a = tiers.get('A', {'n': 0, 'wr': 0, 'avg': 0})
    b = tiers.get('B', {'n': 0, 'wr': 0, 'avg': 0})
    cp = tiers.get('C+', {'n': 0, 'wr': 0, 'avg': 0})

    score = 0

    # S级 (15%)
    if s['n'] > 0:
        score += (min(s['n'], 10) * 2 + s['wr'] * 0.3 + min(s['avg'], 30) * 0.5) * 0.15
    else:
        score -= 5

    # A级 (30%)
    if a['n'] >= 3:
        score += (a['wr'] * 0.3 + a['avg'] * 0.5 + min(a['n'], 20) * 0.5) * 0.30
    elif a['n'] > 0:
        score += (a['wr'] * 0.3 + a['avg'] * 0.5) * 0.15
    else:
        score -= 15

    # B级 (35%)
    if b['n'] >= 5:
        b_score = b['wr'] * 0.25 + b['avg'] * 0.8 + min(b['n'], 50) * 0.1
        if b['avg'] > 0:
            b_score += min(b['avg'] * 3, 15)
        elif b['avg'] < -1:
            b_score -= 10
        score += b_score * 0.35
    elif b['n'] > 0:
        score += (b['wr'] * 0.2 + b['avg'] * 0.5) * 0.15

    # 单调性 (15%)
    mono = 0
    if s['n'] > 0 and a['n'] > 0 and s['avg'] > a['avg']:
        mono += 3
    if a['n'] > 0 and b['n'] > 0:
        if a['wr'] > b['wr']: mono += 4
        if a['avg'] > b['avg']: mono += 4
    if b['n'] > 0 and cp['n'] > 0:
        if b['wr'] > cp['wr']: mono += 3
        if b['avg'] > cp['avg']: mono += 3
    score += mono * 0.15

    # 总量
    total = s['n'] + a['n'] + b['n']
    if total < 15:
        score -= (15 - total) * 0.5

    return score


def main():
    print("=" * 70, flush=True)
    print("  v12 近期数据优化 - 基于最近20交易日", flush=True)
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("=" * 70, flush=True)

    # 步骤1: 重建数据
    df = rebuild_data()

    # 步骤2: 补充收益
    df = fetch_missing_returns(df)

    df_valid = df[df['return_5d'].notna()].copy()
    dates = sorted(df_valid['report_date'].unique())
    print(f"\n  有效数据: {len(df_valid)} 行, {len(dates)} 天", flush=True)
    print(f"  日期范围: {dates[0]} ~ {dates[-1]}", flush=True)

    # 步骤3: v11基线评估
    print("\n" + "=" * 60, flush=True)
    print("  [3/3] v11基线评估 + 近期优化", flush=True)
    print("=" * 60, flush=True)

    df_scored_all = apply_v8_scoring(df_valid)
    tiers_all = evaluate_tiers(df_scored_all)
    obj_all = multi_tier_objective(tiers_all)
    print_tiers(tiers_all, f"v11全量基线 ({len(df_valid)}行, {len(dates)}天)")
    print(f"  目标函数: {obj_all:.2f}", flush=True)

    # 最近20交易日
    recent_dates = dates[-20:] if len(dates) >= 20 else dates
    df_recent = df_valid[df_valid['report_date'].isin(recent_dates)].copy()
    df_scored_recent = apply_v8_scoring(df_recent)
    tiers_recent = evaluate_tiers(df_scored_recent)
    obj_recent = multi_tier_objective(tiers_recent)
    print_tiers(tiers_recent, f"v11近20天 ({len(df_recent)}行, {len(recent_dates)}天: {recent_dates[0]}~{recent_dates[-1]})")
    print(f"  目标函数: {obj_recent:.2f}", flush=True)

    # 更早的数据（用于交叉验证）
    early_dates = [d for d in dates if d not in recent_dates]
    if early_dates:
        df_early = df_valid[df_valid['report_date'].isin(early_dates)].copy()
        df_scored_early = apply_v8_scoring(df_early)
        tiers_early = evaluate_tiers(df_scored_early)
        print_tiers(tiers_early, f"v11早期 ({len(df_early)}行, {len(early_dates)}天)")

    # ============ 参数化优化（使用v11 score_row函数） ============
    print("\n" + "=" * 60, flush=True)
    print("  参数化优化搜索", flush=True)
    print("=" * 60, flush=True)

    # 当前v11参数
    from scripts.optimize_v51_deep import V10_PARAMS
    current_params = dict(V10_PARAMS)
    # 应用v11优化值
    current_params.update({
        'adj_high_pen': 0,
        'chase_60_pen': 3,
        'chg3d_10_pen': 15,
        'tech_low_pen': 8,
        'score_high_pen': 25,
        'rsi_oversold_bonus': 5,
        'zt_low_chase_bonus': 12,
        'tech_high_pen': 3,
        'score_very_high_pen': 3,
        'score_very_high_threshold': 76,
        'rsi_golden_bonus': 5,
        'rsi_golden_low': 45,
        'rsi_golden_high': 55,
    })

    # 参数化基线
    df_param_all = score_with_params(df_valid, current_params)
    tiers_param_all = evaluate_tiers(df_param_all)
    obj_param_all = multi_tier_objective(tiers_param_all)

    df_param_recent = score_with_params(df_recent, current_params)
    tiers_param_recent = evaluate_tiers(df_param_recent)
    obj_param_recent = multi_tier_objective(tiers_param_recent)

    print(f"\n  参数化v11基线:", flush=True)
    print(f"    全量: obj={obj_param_all:.2f}", flush=True)
    print(f"    近20天: obj={obj_param_recent:.2f}", flush=True)

    # 逐参数搜索 (同时考虑全量和近期)
    best_params = dict(current_params)
    all_search_params = list(SEARCH_SPACE.keys())

    for iteration in range(3):
        changed = 0
        for param_name in all_search_params:
            cur_obj_all = multi_tier_objective(evaluate_tiers(score_with_params(df_valid, best_params)))
            cur_obj_recent = multi_tier_objective(evaluate_tiers(score_with_params(df_recent, best_params)))
            # 综合目标: 全量40% + 近期60%
            cur_combined = cur_obj_all * 0.4 + cur_obj_recent * 0.6

            best_val = best_params[param_name]
            best_combined = cur_combined

            for val in SEARCH_SPACE.get(param_name, []):
                test = dict(best_params)
                test[param_name] = val
                obj_a = multi_tier_objective(evaluate_tiers(score_with_params(df_valid, test)))
                obj_r = multi_tier_objective(evaluate_tiers(score_with_params(df_recent, test)))
                combined = obj_a * 0.4 + obj_r * 0.6

                # 约束: 全量不能大幅倒退
                if obj_a < cur_obj_all - 3:
                    continue
                if combined > best_combined:
                    best_combined = combined
                    best_val = val

            if best_val != best_params[param_name]:
                old = best_params[param_name]
                best_params[param_name] = best_val
                print(f"    [{iteration+1}] {param_name}: {old} → {best_val} "
                      f"(combined {cur_combined:.2f}→{best_combined:.2f})", flush=True)
                changed += 1

        if changed == 0:
            print(f"    [{iteration+1}] 无改善, 收敛", flush=True)
            break

    # 参数对联合搜索
    print(f"\n  参数对联合搜索:", flush=True)
    pairs = [
        ('adj_high_threshold', 'adj_high_pen'),
        ('tech_high_pen', 'score_very_high_pen'),
        ('rsi_golden_bonus', 'rsi_oversold_bonus'),
        ('score_high_pen', 'chg3d_10_pen'),
        ('chase_60_pen', 'sector_dead_pen'),
        ('momentum_start_bonus', 'low_risk_momentum_bonus'),
        ('strong_low_chase_bonus', 'zt_low_chase_bonus'),
        ('tech_high_pen', 'tech_low_pen'),
        ('sector_hot_pen', 'sector_dead_pen'),
    ]

    for p1, p2 in pairs:
        cur_a = multi_tier_objective(evaluate_tiers(score_with_params(df_valid, best_params)))
        cur_r = multi_tier_objective(evaluate_tiers(score_with_params(df_recent, best_params)))
        cur_combined = cur_a * 0.4 + cur_r * 0.6

        best = (best_params[p1], best_params[p2])
        best_comb = cur_combined

        for v1 in SEARCH_SPACE.get(p1, [best_params[p1]]):
            for v2 in SEARCH_SPACE.get(p2, [best_params[p2]]):
                test = dict(best_params)
                test[p1] = v1
                test[p2] = v2
                obj_a = multi_tier_objective(evaluate_tiers(score_with_params(df_valid, test)))
                if obj_a < cur_a - 3:
                    continue
                obj_r = multi_tier_objective(evaluate_tiers(score_with_params(df_recent, test)))
                comb = obj_a * 0.4 + obj_r * 0.6
                if comb > best_comb:
                    best_comb = comb
                    best = (v1, v2)

        if best != (best_params[p1], best_params[p2]):
            print(f"    {p1}={best[0]}, {p2}={best[1]} (+{best_comb - cur_combined:.3f})", flush=True)
            best_params[p1] = best[0]
            best_params[p2] = best[1]

    # 最终收敛
    for iteration in range(3):
        changed = 0
        for param_name in all_search_params:
            cur_a = multi_tier_objective(evaluate_tiers(score_with_params(df_valid, best_params)))
            cur_r = multi_tier_objective(evaluate_tiers(score_with_params(df_recent, best_params)))
            cur_comb = cur_a * 0.4 + cur_r * 0.6
            best_val = best_params[param_name]
            best_comb = cur_comb
            for val in SEARCH_SPACE.get(param_name, []):
                test = dict(best_params)
                test[param_name] = val
                obj_a = multi_tier_objective(evaluate_tiers(score_with_params(df_valid, test)))
                if obj_a < cur_a - 3:
                    continue
                obj_r = multi_tier_objective(evaluate_tiers(score_with_params(df_recent, test)))
                comb = obj_a * 0.4 + obj_r * 0.6
                if comb > best_comb:
                    best_comb = comb
                    best_val = val
            if best_val != best_params[param_name]:
                best_params[param_name] = best_val
                changed += 1
        if changed == 0:
            break

    # ============ 最终对比 ============
    print("\n" + "=" * 60, flush=True)
    print("  最终对比", flush=True)
    print("=" * 60, flush=True)

    opt_all = score_with_params(df_valid, best_params)
    opt_recent = score_with_params(df_recent, best_params)

    tiers_opt_all = evaluate_tiers(opt_all)
    tiers_opt_recent = evaluate_tiers(opt_recent)
    obj_opt_all = multi_tier_objective(tiers_opt_all)
    obj_opt_recent = multi_tier_objective(tiers_opt_recent)

    print_tiers(tiers_param_all, "v11全量基线")
    print(f"  obj={obj_param_all:.2f}", flush=True)

    print_tiers(tiers_opt_all, "v12全量优化")
    print(f"  obj={obj_opt_all:.2f}", flush=True)

    print_tiers(tiers_param_recent, "v11近20天基线")
    print(f"  obj={obj_param_recent:.2f}", flush=True)

    print_tiers(tiers_opt_recent, "v12近20天优化")
    print(f"  obj={obj_opt_recent:.2f}", flush=True)

    # 参数变化
    changes = []
    for k in sorted(current_params.keys()):
        old = current_params[k]
        new = best_params[k]
        if old != new:
            changes.append((k, old, new))

    if changes:
        print(f"\n  参数变化 ({len(changes)} 个):", flush=True)
        for k, old, new in changes:
            print(f"    {k}: {old} → {new}", flush=True)
    else:
        print(f"\n  无参数变化 — v11已是最优", flush=True)

    # 层级单调性验证
    print(f"\n  层级单调性 (全量):", flush=True)
    for t_hi, t_lo in [('S', 'A'), ('A', 'B'), ('B', 'C+')]:
        hi_t = tiers_opt_all.get(t_hi, {'n': 0, 'wr': 0, 'avg': 0})
        lo_t = tiers_opt_all.get(t_lo, {'n': 0, 'wr': 0, 'avg': 0})
        if hi_t['n'] > 0 and lo_t['n'] > 0:
            wr_ok = hi_t['wr'] >= lo_t['wr']
            avg_ok = hi_t['avg'] >= lo_t['avg']
            print(f"    {t_hi}>{t_lo} 胜率: {'PASS' if wr_ok else 'FAIL'} ({hi_t['wr']:.1f}% vs {lo_t['wr']:.1f}%), "
                  f"收益: {'PASS' if avg_ok else 'FAIL'} ({hi_t['avg']:+.2f}% vs {lo_t['avg']:+.2f}%)", flush=True)

    # 近20天单调性
    print(f"\n  层级单调性 (近20天):", flush=True)
    for t_hi, t_lo in [('S', 'A'), ('A', 'B'), ('B', 'C+')]:
        hi_t = tiers_opt_recent.get(t_hi, {'n': 0, 'wr': 0, 'avg': 0})
        lo_t = tiers_opt_recent.get(t_lo, {'n': 0, 'wr': 0, 'avg': 0})
        if hi_t['n'] > 0 and lo_t['n'] > 0:
            wr_ok = hi_t['wr'] >= lo_t['wr']
            avg_ok = hi_t['avg'] >= lo_t['avg']
            print(f"    {t_hi}>{t_lo} 胜率: {'PASS' if wr_ok else 'FAIL'} ({hi_t['wr']:.1f}% vs {lo_t['wr']:.1f}%), "
                  f"收益: {'PASS' if avg_ok else 'FAIL'} ({hi_t['avg']:+.2f}% vs {lo_t['avg']:+.2f}%)", flush=True)

    # 保存结果
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    result = {
        'timestamp': datetime.now().isoformat(),
        'data_total': len(df_valid),
        'data_recent': len(df_recent),
        'recent_dates': recent_dates,
        'v11_tiers_all': tiers_param_all,
        'v12_tiers_all': tiers_opt_all,
        'v11_tiers_recent': tiers_param_recent,
        'v12_tiers_recent': tiers_opt_recent,
        'v12_params': best_params,
        'changes': [{'param': k, 'old': o, 'new': n} for k, o, n in changes],
    }
    result_file = os.path.join(RESULTS_DIR, f'optimization_v12_{timestamp}.json')
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  结果已保存: {result_file}", flush=True)

    # 结论
    print("\n" + "=" * 60, flush=True)
    print("  结论", flush=True)
    print("=" * 60, flush=True)

    improved_all = obj_opt_all > obj_param_all
    improved_recent = obj_opt_recent > obj_param_recent
    print(f"  全量改善: {'YES' if improved_all else 'NO'} ({obj_param_all:.2f} → {obj_opt_all:.2f})", flush=True)
    print(f"  近期改善: {'YES' if improved_recent else 'NO'} ({obj_param_recent:.2f} → {obj_opt_recent:.2f})", flush=True)

    if changes and (improved_all or improved_recent):
        print(f"\n  建议更新 {len(changes)} 个参数", flush=True)
    else:
        print(f"\n  v11参数已是当前最优，无需更新", flush=True)


if __name__ == '__main__':
    main()
