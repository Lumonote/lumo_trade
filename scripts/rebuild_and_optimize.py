#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全量历史回测重建 + 多轮参数优化
================================
1. 解析所有 opportunity_top10 报告，提取完整特征
2. 获取真实收益数据
3. 去重合并
4. 多轮自动优化
5. 输出最优参数
"""

import os
import re
import sys
import glob
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from itertools import product

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

RESULTS_DIR = os.path.join(project_root, 'results')


# ========== 第一部分: 报告解析 ==========

def parse_new_format(text, code):
    """解析新格式 (带 【tag】 标签的 <br> 分隔)"""
    feat = {}

    # 涨幅
    m = re.search(r'当日[:：]([+-]?\d+\.?\d*)%.*?3日[:：]([+-]?\d+\.?\d*)%.*?5日[:：]([+-]?\d+\.?\d*)%', text)
    if m:
        feat['day_change'] = float(m.group(1))
        feat['change_3d'] = float(m.group(2))
        feat['change_5d'] = float(m.group(3))

    # 板块
    m = re.search(r'【板块】.*?(\d+)分', text)
    if m:
        feat['sector_score'] = float(m.group(1))

    # 量化 - 新格式: 买14/卖2/总30(47%)，100分
    m = re.search(r'【量化】买(\d+)/卖(\d+)/总(\d+)\(\d+%\)[，,]\s*(\d+)分', text)
    if m:
        feat['buy_signals'] = int(m.group(1))
        feat['sell_signals'] = int(m.group(2))
        feat['total_signals'] = int(m.group(3))
        feat['quant_score'] = float(m.group(4))
    else:
        # 旧新格式: 买12/总30(40%)，75分
        m = re.search(r'【量化】买(\d+)/总(\d+)\(\d+%\)[，,]\s*(\d+)分', text)
        if m:
            feat['buy_signals'] = int(m.group(1))
            feat['total_signals'] = int(m.group(2))
            feat['quant_score'] = float(m.group(3))

    # 技术
    m = re.search(r'RSI[:：]\s*(\d+\.?\d*)', text)
    if m:
        feat['rsi'] = float(m.group(1))

    m = re.search(r'【技术】.*?(\d+)分', text)
    if m:
        feat['tech_score'] = float(m.group(1))

    # 追高风险
    m = re.search(r'追高风险.*?(\d+)分', text)
    if m:
        feat['chase_risk'] = float(m.group(1))

    return feat


def parse_old_format(text, code):
    """解析旧格式 (纯文本, 无 【tag】)"""
    feat = {}

    m = re.search(r'RSI=(\d+\.?\d*)', text)
    if m:
        feat['rsi'] = float(m.group(1))

    m = re.search(r'买入信号(\d+)个', text)
    if m:
        feat['buy_signals'] = int(m.group(1))

    m = re.search(r'卖出信号(\d+)个', text)
    if m:
        feat['sell_signals'] = int(m.group(1))

    return feat


def parse_report(filepath):
    """解析单个报告文件, 返回 [{code, name, score, rank, features...}]"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return []

    fname = os.path.basename(filepath)

    # 提取报告日期
    m = re.search(r'生成时间[:：]\s*(\d{4}-\d{2}-\d{2})', content)
    if m:
        report_date = m.group(1)
    else:
        # 从文件名提取
        m2 = re.search(r'(\d{8})_\d{6}', fname)
        if m2:
            d = m2.group(1)
            report_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        else:
            return []

    results = []
    is_new_format = '【概览】' in content or '【涨幅】' in content

    # 解析表格行
    # 新格式: | 1 | 002136 | 安 纳 达 | 73.64 | 【概览】... |
    # 旧格式: | 1    | 002213   | 大为股份   | 70.90    | 代码：... |
    rows = re.findall(
        r'\|\s*(\d+)\s*\|\s*(\d{6})\s*\|\s*(.+?)\s*\|\s*(\d+\.?\d*)\s*\|\s*(.+?)\s*\|',
        content
    )

    for rank_str, code, name, score_str, detail_text in rows:
        rank = int(rank_str)
        if rank > 20:
            continue

        code = code.strip()
        name = name.strip().replace(' ', '')
        score = float(score_str)

        if is_new_format:
            feat = parse_new_format(detail_text, code)
        else:
            feat = parse_old_format(detail_text, code)

        row = {
            'report_date': report_date,
            'filename': fname,
            'rank': rank,
            'code': code,
            'name': name,
            'score': score,
            **feat
        }
        results.append(row)

    return results


def parse_all_reports():
    """解析所有报告, 返回完整DataFrame"""
    files = sorted(glob.glob(os.path.join(RESULTS_DIR, 'opportunity_top10_*.md')))
    print(f"找到 {len(files)} 个报告文件")

    all_rows = []
    for f in files:
        rows = parse_report(f)
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    print(f"解析出 {len(df)} 条推荐记录")
    print(f"日期范围: {df['report_date'].min()} ~ {df['report_date'].max()}")
    print(f"唯一日期: {df['report_date'].nunique()}")
    return df


# ========== 第二部分: 收益数据获取 ==========

def get_returns_from_existing_csv(df_new):
    """从现有CSV获取收益数据"""
    csv_files = sorted(glob.glob(os.path.join(RESULTS_DIR, 'backtest_analysis_*.csv')))
    if not csv_files:
        return df_new

    df_old = pd.read_csv(csv_files[-1])
    print(f"从 {os.path.basename(csv_files[-1])} 读取已有收益数据: {len(df_old)} 条")

    # 创建收益查找表 (code+date -> returns)
    return_cols = ['return_1d', 'return_3d', 'return_5d', 'return_10d', 'max_drawdown_5d', 'buy_date', 'buy_price']
    existing_returns = {}
    for _, row in df_old.iterrows():
        key = (str(row.get('code', '')).zfill(6), str(row.get('report_date', '')))
        returns = {}
        for col in return_cols:
            if col in df_old.columns and pd.notna(row.get(col)):
                returns[col] = row[col]
        if returns:
            existing_returns[key] = returns

    # 合并到新数据
    matched = 0
    for idx, row in df_new.iterrows():
        key = (str(row['code']).zfill(6), str(row['report_date']))
        if key in existing_returns:
            for col, val in existing_returns[key].items():
                df_new.at[idx, col] = val
            matched += 1

    print(f"  匹配到收益数据: {matched}/{len(df_new)}")
    return df_new


def fetch_missing_returns(df):
    """通过tushare获取缺失的收益数据"""
    missing = df[df['return_5d'].isna()].copy()
    if len(missing) == 0:
        print("所有记录都已有收益数据")
        return df

    print(f"\n需要补充收益数据: {missing['report_date'].nunique()} 个日期, {len(missing)} 条记录")

    # 尝试导入tushare
    try:
        from scripts.fetch_data import get_tushare_api
        ts_api = get_tushare_api()
        if ts_api is None:
            raise ImportError("No tushare API")
    except Exception:
        try:
            import tushare as ts
            config_path = os.path.join(project_root, 'config', 'tushare_config.json')
            if os.path.exists(config_path):
                with open(config_path) as f:
                    cfg = json.load(f)
                token = cfg.get('token', '')
                if token:
                    ts.set_token(token)
                    ts_api = ts.pro_api()
                else:
                    print("  ⚠️ Tushare token 未配置, 跳过收益获取")
                    return df
            else:
                print("  ⚠️ Tushare 配置文件不存在, 跳过收益获取")
                return df
        except ImportError:
            print("  ⚠️ Tushare 未安装, 跳过收益获取")
            return df

    # 获取每个日期的下一个交易日
    unique_dates = sorted(missing['report_date'].unique())
    # 过滤太近的日期（5个交易日不够）
    cutoff = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
    fetchable_dates = [d for d in unique_dates if d < cutoff]

    if not fetchable_dates:
        print(f"  所有缺失日期({len(unique_dates)}个)都太近, 无法获取5日收益")
        return df

    print(f"  可获取日期: {len(fetchable_dates)}/{len(unique_dates)}")

    # 获取交易日历
    try:
        start_d = fetchable_dates[0].replace('-', '')
        end_d = (datetime.now() + timedelta(days=5)).strftime('%Y%m%d')
        cal = ts_api.trade_cal(exchange='SSE', start_date=start_d, end_date=end_d)
        trade_days = sorted(cal[cal['is_open'] == 1]['cal_date'].tolist())
    except Exception as e:
        print(f"  ⚠️ 获取交易日历失败: {e}")
        return df

    def next_trade_day(date_str, n=1):
        d = date_str.replace('-', '')
        future = [t for t in trade_days if t > d]
        if len(future) >= n:
            return future[n - 1]
        return None

    # 批量获取行情
    fetched = 0
    for report_date in fetchable_dates:
        buy_day = next_trade_day(report_date, 1)
        day_1 = next_trade_day(report_date, 2)
        day_3 = next_trade_day(report_date, 4)
        day_5 = next_trade_day(report_date, 6)
        day_10 = next_trade_day(report_date, 11)

        if not buy_day or not day_5:
            continue

        date_rows = missing[missing['report_date'] == report_date]

        for _, row in date_rows.iterrows():
            code = str(row['code']).zfill(6)
            # 确定市场后缀
            if code.startswith('6'):
                ts_code = f"{code}.SH"
            else:
                ts_code = f"{code}.SZ"

            try:
                # 获取买入日到N日后的行情
                all_dates = [d for d in [buy_day, day_1, day_3, day_5, day_10] if d]
                start = min(all_dates)
                end = max(all_dates)
                daily = ts_api.daily(ts_code=ts_code, start_date=start, end_date=end)
                if daily is None or len(daily) == 0:
                    continue

                daily = daily.sort_values('trade_date')
                prices = dict(zip(daily['trade_date'], daily['close']))

                buy_price = prices.get(buy_day)
                if buy_price is None or buy_price == 0:
                    continue

                idx = df[(df['code'] == row['code']) & (df['report_date'] == report_date)].index
                if len(idx) == 0:
                    continue

                df.loc[idx, 'buy_date'] = buy_day
                df.loc[idx, 'buy_price'] = buy_price

                for label, target_day in [('return_1d', day_1), ('return_3d', day_3),
                                           ('return_5d', day_5), ('return_10d', day_10)]:
                    if target_day and target_day in prices:
                        ret = (prices[target_day] - buy_price) / buy_price * 100
                        df.loc[idx, label] = ret

                fetched += 1

            except Exception:
                continue

        # 控制API频率
        import time
        time.sleep(0.3)

    print(f"  成功获取 {fetched} 条新收益数据")
    return df


# ========== 第三部分: 评分函数 (参数化) ==========

DEFAULT_PARAMS = {
    # RSI惩罚
    'rsi_85_pen': 25,
    'rsi_80_pen': 15,
    'rsi_75_pen': 3,             # v9: 0→3

    # 日涨幅惩罚
    'day_chg_20_pen': 25,
    'zt_chase_pen': 12,          # v9: 20→12
    'zt_signal_pen': 14,         # v9: 15→14
    'zt_base_pen': 3,
    'chg7_pen': 3,               # v9: 恢复
    'chg5_pen': 5,               # v9: 3→5

    # 短期涨幅
    'chg5d_18_pen': 25,          # v9: 20→25
    'chg3d_20_pen': 20,
    'chg3d_15_pen': 16,          # v9: 10→16
    'chg3d_10_pen': 12,          # v13: 15→12

    # 追高风险
    'chase_80_pen': 20,          # v9: 15→20
    'chase_60_pen': 3,           # v11: 6→3

    # 技术面
    'tech_low_pen': 8,           # v11: 10→8

    # 板块
    'sector_hot_pen': 12,        # v12: 10→12
    'sector_dead_pen': 5,        # v12: 3→5

    # 评分过高
    'score_high_threshold': 78,  # v14: 74→78
    'score_high_pen': 20,        # v14: 25→20

    # 组合风险
    'rsi80_3d10_pen': 10,
    'chg5d15_rsi72_pen': 10,

    # 信号拥挤
    'signal_crowd_pen': 1,       # 保持v9

    # 卖出信号 (v9移除)
    'sell_dom_pen': 0,
    'sell_abs_pen': 0,

    # 追高超买组合
    'chase_rsi_combo_pen': 0,    # v10: 3→0 (移除)

    # === 奖励 ===
    'rsi_oversold_bonus': 5,     # v13: 10→5
    'buy_dominance_bonus': 0,    # v10: 5→0 (移除)
    'zt_low_chase_bonus': 10,    # v13: 12→10
    'strong_low_chase_bonus': 12, # v13: 15→12
    'momentum_start_bonus': 5,   # v9: 8→5
    'quant_moderate_bonus': 0,   # v9: 2→0 (移除)
    'low_risk_momentum_bonus': 8, # v12: 5→8

    # v11新增参数
    'tech_high_pen': 3,          # v11: 技术面>=80虚高惩罚
    'score_very_high_pen': 3,    # v11: 原始评分>=76额外惩罚
    'score_very_high_threshold': 76,
    'rsi_golden_bonus': 4,       # v15: 3→4
    'rsi_golden_low': 40,        # v15: 42→40
    'rsi_golden_high': 50,       # v15: 53→50

    # v15新增
    'sell0_bonus': 4,            # v15: 零卖出信号奖励
    'sell0_zt_bonus': 8,         # v15: 涨停+零卖出奖励

    # 甜蜜区
    'sweet_low': 63,
    'sweet_high': 69,            # v9: 73→69
    'sweet_bonus': 0,            # v10: 5→0 (移除)

    # 过高评分惩罚
    'adj_high_threshold': 79,    # v9: 85→79
    'adj_high_pen': 0,           # v11: 8→0 (移除,释放S级空间)
}


def score_row(row, params):
    """用参数化方式计算v8评分"""
    score = float(row.get('score', 0) or 0)
    chase = row.get('chase_risk')
    rsi = row.get('rsi')
    day_chg = row.get('day_change')
    chg_5d = row.get('change_5d')
    chg_3d = row.get('change_3d')
    qs = row.get('quant_score')
    buy_sig = row.get('buy_signals')
    sell_sig = row.get('sell_signals')
    tech = row.get('tech_score')
    sector = row.get('sector_score')

    penalty = 0
    bonus = 0

    # RSI惩罚
    if pd.notna(rsi):
        if rsi >= 85:
            penalty += params['rsi_85_pen']
        elif rsi > 80:
            penalty += params['rsi_80_pen']
        elif rsi > 75:
            penalty += params['rsi_75_pen']

    # 日涨幅
    if pd.notna(day_chg):
        if day_chg >= 20:
            penalty += params['day_chg_20_pen']
        elif day_chg >= 9.5:
            # v14: 涨停首板(3日<15%)不惩罚
            if pd.notna(chg_3d) and chg_3d >= 15:
                penalty += params['zt_base_pen']  # 连板涨停才惩罚
            # 首板不惩罚
        elif day_chg >= 7:
            penalty += params['chg7_pen']
        elif day_chg >= 5:
            penalty += params['chg5_pen']

    # 短期涨幅
    if pd.notna(chg_5d) and chg_5d > 18:
        penalty += params['chg5d_18_pen']
    if pd.notna(chg_3d):
        if chg_3d > 20:
            penalty += params['chg3d_20_pen']
        elif chg_3d > 15:
            penalty += params['chg3d_15_pen']
        elif chg_3d > 10:
            penalty += params['chg3d_10_pen']

    # 追高
    if pd.notna(chase):
        if chase >= 80:
            penalty += params['chase_80_pen']
        elif chase >= 60:
            penalty += params['chase_60_pen']

    # 技术面低
    if pd.notna(tech) and tech < 60:
        has_exempt = False
        if pd.notna(day_chg) and 9.5 <= day_chg < 20:
            if pd.notna(chase) and chase < 50 and pd.notna(buy_sig) and buy_sig <= 8:
                has_exempt = True
        if pd.notna(day_chg) and 3 <= day_chg < 10:
            if pd.notna(chase) and chase < 50 and pd.notna(qs) and 55 <= qs <= 80:
                has_exempt = True
        if not has_exempt:
            penalty += params['tech_low_pen']

    # v11: 技术面虚高
    if pd.notna(tech) and tech >= 80:
        penalty += params['tech_high_pen']

    # 板块
    if pd.notna(sector):
        if sector >= 95:
            penalty += params['sector_hot_pen']
        elif 60 <= sector < 75:
            penalty += params['sector_dead_pen']

    # 原始评分过高
    if score >= params['score_high_threshold']:
        penalty += params['score_high_pen']

    # v11: 评分极高额外惩罚
    if score >= params.get('score_very_high_threshold', 76):
        penalty += params.get('score_very_high_pen', 0)

    # 组合风险
    if pd.notna(rsi) and pd.notna(chg_3d) and rsi > 80 and chg_3d > 10:
        penalty += params['rsi80_3d10_pen']
    if pd.notna(chg_5d) and pd.notna(rsi) and chg_5d > 15 and rsi > 72:
        penalty += params['chg5d15_rsi72_pen']

    # 信号拥挤
    if pd.notna(buy_sig) and buy_sig >= 15:
        penalty += params['signal_crowd_pen']

    # 卖出信号
    if pd.notna(sell_sig) and pd.notna(buy_sig) and sell_sig > buy_sig:
        penalty += params['sell_dom_pen']
    if pd.notna(sell_sig) and sell_sig >= 5:
        penalty += params['sell_abs_pen']

    # 追高超买组合
    if pd.notna(chase) and pd.notna(rsi) and chase > 30 and rsi > 60:
        penalty += params['chase_rsi_combo_pen']

    # === 奖励 ===
    # RSI超卖
    if pd.notna(rsi) and rsi < 35:
        bonus += params['rsi_oversold_bonus']

    # v11: RSI黄金区间
    if pd.notna(rsi) and params.get('rsi_golden_low', 40) <= rsi <= params.get('rsi_golden_high', 50):
        bonus += params.get('rsi_golden_bonus', 0)

    # v15: 零卖出信号奖励
    if pd.notna(sell_sig) and sell_sig == 0:
        if pd.notna(day_chg) and day_chg >= 9.5:
            bonus += params.get('sell0_zt_bonus', 8)
        else:
            bonus += params.get('sell0_bonus', 4)

    # 买入占优
    if pd.notna(buy_sig) and pd.notna(sell_sig) and buy_sig >= 5 and sell_sig > 0 and buy_sig >= sell_sig * 2:
        bonus += params['buy_dominance_bonus']

    # 涨停低追高
    if pd.notna(day_chg) and day_chg >= 9.5 and pd.notna(chase) and chase < 50:
        if not (pd.notna(buy_sig) and buy_sig > 8):
            bonus += params['zt_low_chase_bonus']
    elif pd.notna(day_chg) and day_chg >= 7 and pd.notna(chase) and chase < 40:
        bonus += params['strong_low_chase_bonus']

    # 动量启动
    if pd.notna(day_chg) and 3 <= day_chg < 10 and pd.notna(chase) and chase < 50:
        bonus += params['momentum_start_bonus']

    # 量化适中
    if pd.notna(qs) and 55 <= qs <= 80:
        bonus += params['quant_moderate_bonus']

    # 低风险动量
    if pd.notna(chase) and pd.notna(rsi) and chase < 25 and rsi < 50:
        bonus += params['low_risk_momentum_bonus']

    # 计算
    adj = max(0, score - penalty + bonus)

    # 甜蜜区
    if params['sweet_low'] <= adj <= params['sweet_high']:
        adj += params['sweet_bonus']

    # 过高惩罚
    if adj >= params['adj_high_threshold']:
        adj -= params['adj_high_pen']

    return adj


def evaluate(df, params, threshold=78, top_n=10):
    """评估参数组合, 返回 {wr, avg, n, pf, top_wr, top_avg}"""
    df = df.copy()
    df['adj_score'] = df.apply(lambda r: score_row(r, params), axis=1)

    # 按分数阈值
    high = df[df['adj_score'] >= threshold]
    r5_high = high['return_5d'].dropna()

    # 按每日Top-N
    top_selections = []
    for date, group in df.groupby('report_date'):
        top = group.nlargest(top_n, 'adj_score')
        top_selections.append(top)
    if top_selections:
        df_top = pd.concat(top_selections)
    else:
        df_top = pd.DataFrame()
    r5_top = df_top['return_5d'].dropna()

    result = {}

    # 阈值指标
    if len(r5_high) > 0:
        result['wr'] = (r5_high > 0).mean() * 100
        result['avg'] = r5_high.mean()
        result['n'] = len(r5_high)
        losses = r5_high[r5_high < 0].sum()
        result['pf'] = abs(r5_high[r5_high > 0].sum() / losses) if losses != 0 else 999
    else:
        result['wr'] = 0
        result['avg'] = 0
        result['n'] = 0
        result['pf'] = 0

    # Top-N 指标
    if len(r5_top) > 0:
        result['top_wr'] = (r5_top > 0).mean() * 100
        result['top_avg'] = r5_top.mean()
        result['top_n'] = len(r5_top)
    else:
        result['top_wr'] = 0
        result['top_avg'] = 0
        result['top_n'] = 0

    return result


def objective(result, min_n=5):
    """目标函数: 兼顾胜率、收益和样本量"""
    if result['n'] < min_n:
        return -999
    # 主目标: 高胜率 + 正收益
    # 加入样本量的对数权重避免过拟合到极小样本
    n_weight = min(1.0, np.log(result['n'] + 1) / np.log(50))
    return result['wr'] * 0.5 + result['avg'] * 0.3 + result['top_wr'] * 0.1 + result['top_avg'] * 0.1 * n_weight


# ========== 第四部分: 多轮优化 ==========

def round1_single_scan(df, base_params):
    """第1轮: 单参数扫描"""
    print("\n" + "=" * 60)
    print("  第1轮: 单参数敏感度扫描")
    print("=" * 60)

    # 每个参数的搜索范围
    search_space = {
        'rsi_85_pen': [15, 20, 25, 30],
        'rsi_80_pen': [5, 10, 15, 20],
        'rsi_75_pen': [0, 3, 5],
        'day_chg_20_pen': [15, 20, 25, 30],
        'zt_chase_pen': [10, 15, 20, 25],
        'zt_signal_pen': [5, 10, 15, 20],
        'zt_base_pen': [0, 3, 5, 8],
        'chg7_pen': [0, 3, 5],
        'chg5_pen': [0, 3, 5],
        'chg5d_18_pen': [10, 15, 20, 25],
        'chg3d_20_pen': [10, 15, 20, 25],
        'chg3d_15_pen': [5, 8, 10, 15],
        'chg3d_10_pen': [0, 3, 5, 8],
        'chase_80_pen': [5, 10, 15, 20],
        'chase_60_pen': [5, 8, 10, 15],
        'tech_low_pen': [5, 10, 15, 20],
        'sector_hot_pen': [5, 10, 15, 20],
        'sector_dead_pen': [0, 3, 5, 8, 10],
        'score_high_threshold': [65, 68, 70, 72, 75, 78],
        'score_high_pen': [5, 10, 15, 20],
        'rsi80_3d10_pen': [0, 5, 10, 15],
        'chg5d15_rsi72_pen': [0, 5, 10, 15],
        'signal_crowd_pen': [0, 5, 10, 15],
        'sell_dom_pen': [0, 3, 5, 8],
        'sell_abs_pen': [0, 3, 5, 8],
        'chase_rsi_combo_pen': [0, 3, 5, 8],
        'rsi_oversold_bonus': [0, 3, 5, 8, 10],
        'buy_dominance_bonus': [0, 3, 5, 8],
        'zt_low_chase_bonus': [0, 5, 8, 10, 15],
        'strong_low_chase_bonus': [0, 5, 8, 10, 15],
        'momentum_start_bonus': [0, 3, 5, 8, 10],
        'quant_moderate_bonus': [0, 2, 3, 5],
        'low_risk_momentum_bonus': [0, 3, 5, 8],
        'sweet_low': [58, 60, 63, 65],
        'sweet_high': [70, 73, 75, 78],
        'sweet_bonus': [0, 3, 5, 8],
        'adj_high_threshold': [80, 82, 85, 88],
        'adj_high_pen': [5, 8, 10, 15],
    }

    base_result = evaluate(df, base_params)
    base_obj = objective(base_result)
    print(f"  基线: wr={base_result['wr']:.1f}%, avg={base_result['avg']:+.2f}%, n={base_result['n']}, "
          f"top_wr={base_result['top_wr']:.1f}%, obj={base_obj:.2f}")

    improvements = {}
    best_params = dict(base_params)

    for param_name, values in search_space.items():
        best_val = base_params[param_name]
        best_obj = base_obj

        for val in values:
            if val == base_params[param_name]:
                continue
            test_params = dict(base_params)
            test_params[param_name] = val
            result = evaluate(df, test_params)
            obj = objective(result)
            if obj > best_obj:
                best_obj = obj
                best_val = val

        if best_val != base_params[param_name]:
            improvements[param_name] = {
                'old': base_params[param_name],
                'new': best_val,
                'improvement': best_obj - base_obj
            }
            best_params[param_name] = best_val

    # 排序显示
    sorted_impr = sorted(improvements.items(), key=lambda x: -x[1]['improvement'])
    print(f"\n  发现 {len(sorted_impr)} 个改善参数:")
    for name, info in sorted_impr[:15]:
        print(f"    {name}: {info['old']} → {info['new']} (+{info['improvement']:.2f})")

    return best_params, improvements


def round2_refinement(df, base_params):
    """第2轮: 精细化搜索"""
    print("\n" + "=" * 60)
    print("  第2轮: 精细化搜索")
    print("=" * 60)

    base_result = evaluate(df, base_params)
    base_obj = objective(base_result)

    best_params = dict(base_params)
    improved = True
    iteration = 0

    while improved and iteration < 5:
        improved = False
        iteration += 1
        print(f"\n  迭代 {iteration}:")

        for param_name in sorted(base_params.keys()):
            current_val = best_params[param_name]
            best_val = current_val
            best_obj_local = base_obj

            # 在当前值附近搜索
            if isinstance(current_val, int):
                candidates = [current_val - 2, current_val - 1, current_val + 1, current_val + 2]
            else:
                candidates = [current_val - 2, current_val - 1, current_val + 1, current_val + 2]

            candidates = [max(0, c) for c in candidates]

            for val in candidates:
                if val == current_val:
                    continue
                test_params = dict(best_params)
                test_params[param_name] = val
                result = evaluate(df, test_params)
                obj = objective(result)
                if obj > best_obj_local:
                    best_obj_local = obj
                    best_val = val

            if best_val != current_val:
                best_params[param_name] = best_val
                base_obj = best_obj_local
                improved = True

        result = evaluate(df, best_params)
        print(f"    当前最优: wr={result['wr']:.1f}%, avg={result['avg']:+.2f}%, n={result['n']}, "
              f"obj={objective(result):.2f}")

    return best_params


def round3_combo_search(df, base_params):
    """第3轮: 关键参数组合搜索"""
    print("\n" + "=" * 60)
    print("  第3轮: 关键参数组合搜索")
    print("=" * 60)

    # 选择最敏感的参数做组合搜索
    key_params = {
        'score_high_threshold': [65, 68, 70, 72, 75],
        'score_high_pen': [10, 12, 15, 18, 20],
        'adj_high_pen': [5, 8, 10, 12, 15],
        'adj_high_threshold': [80, 82, 85, 88],
        'sweet_bonus': [0, 3, 5, 8],
        'zt_base_pen': [0, 2, 3, 5],
    }

    base_result = evaluate(df, base_params)
    base_obj = objective(base_result)
    best_params = dict(base_params)
    best_obj = base_obj

    # 按对组合搜索
    param_names = list(key_params.keys())
    total_combos = 1
    for v in key_params.values():
        total_combos *= len(v)
    print(f"  搜索空间: {total_combos} 组合")

    count = 0
    for combo in product(*key_params.values()):
        test_params = dict(base_params)
        for i, name in enumerate(param_names):
            test_params[name] = combo[i]

        result = evaluate(df, test_params)
        obj = objective(result)
        count += 1

        if obj > best_obj:
            best_obj = obj
            best_params = dict(test_params)
            print(f"    [{count}/{total_combos}] 新最优: wr={result['wr']:.1f}%, "
                  f"avg={result['avg']:+.2f}%, n={result['n']}, obj={obj:.2f}")
            for i, name in enumerate(param_names):
                if combo[i] != base_params[name]:
                    print(f"      {name}: {base_params[name]} → {combo[i]}")

    result = evaluate(df, best_params)
    print(f"\n  第3轮最优: wr={result['wr']:.1f}%, avg={result['avg']:+.2f}%, n={result['n']}, obj={best_obj:.2f}")
    return best_params


def round4_threshold_search(df, best_params):
    """第4轮: 最优阈值搜索"""
    print("\n" + "=" * 60)
    print("  第4轮: 最优阈值搜索")
    print("=" * 60)

    df_scored = df.copy()
    df_scored['adj_score'] = df_scored.apply(lambda r: score_row(r, best_params), axis=1)

    print("\n  不同阈值下的表现:")
    print(f"  {'阈值':>6} | {'数量':>4} | {'5d胜率':>7} | {'5d均收益':>9} | {'盈亏比':>7} | 目标函数")
    print(f"  {'-'*6}-+-{'-'*4}-+-{'-'*7}-+-{'-'*9}-+-{'-'*7}-+-{'-'*8}")

    best_threshold = 78
    best_obj = -999

    for threshold in range(55, 95):
        high = df_scored[df_scored['adj_score'] >= threshold]
        r5 = high['return_5d'].dropna()
        if len(r5) < 3:
            continue
        wr = (r5 > 0).mean() * 100
        avg = r5.mean()
        losses = r5[r5 < 0].sum()
        pf = abs(r5[r5 > 0].sum() / losses) if losses != 0 else 999

        n_weight = min(1.0, np.log(len(r5) + 1) / np.log(50))
        obj = wr * 0.6 + avg * 0.3 + n_weight * 10

        if threshold in [60, 65, 70, 72, 75, 78, 80, 82, 85, 88, 90] or obj > best_obj:
            pf_str = f"{pf:.2f}" if pf < 999 else "INF"
            marker = " ◀" if obj > best_obj else ""
            print(f"  {threshold:>6} | {len(r5):>4} | {wr:>6.1f}% | {avg:>+8.2f}% | {pf_str:>7} | {obj:.2f}{marker}")

        if obj > best_obj:
            best_obj = obj
            best_threshold = threshold

    print(f"\n  推荐阈值: {best_threshold} (obj={best_obj:.2f})")
    return best_threshold


def print_final_results(df, params, threshold):
    """打印最终结果"""
    print("\n" + "=" * 70)
    print("  最终优化结果")
    print("=" * 70)

    df_scored = df.copy()
    df_scored['adj_score'] = df_scored.apply(lambda r: score_row(r, params), axis=1)

    # 置信度分级
    for idx, row in df_scored.iterrows():
        s = row['adj_score']
        if s >= 85:
            df_scored.at[idx, 'tier'] = 'S'
        elif s >= threshold:
            df_scored.at[idx, 'tier'] = 'A'
        elif s >= 70:
            df_scored.at[idx, 'tier'] = 'B'
        else:
            df_scored.at[idx, 'tier'] = 'C'

    # 分级表现
    print("\n  置信度分级表现:")
    print(f"  {'级别':>4} | {'数量':>5} | {'5d胜率':>7} | {'5d均收益':>9} | {'10d均收益':>9} | {'盈亏比':>7}")
    print(f"  {'-'*4}-+-{'-'*5}-+-{'-'*7}-+-{'-'*9}-+-{'-'*9}-+-{'-'*7}")

    for tier in ['S', 'A', 'B', 'C']:
        sub = df_scored[df_scored['tier'] == tier]
        r5 = sub['return_5d'].dropna()
        r10 = sub['return_10d'].dropna()
        if len(r5) > 0:
            wr = (r5 > 0).mean() * 100
            avg = r5.mean()
            avg10 = r10.mean() if len(r10) > 0 else 0
            losses = r5[r5 < 0].sum()
            pf = abs(r5[r5 > 0].sum() / losses) if losses != 0 else 999
            pf_str = f"{pf:.2f}" if pf < 999 else "INF"
            print(f"  {tier:>4} | {len(r5):>5} | {wr:>6.1f}% | {avg:>+8.2f}% | {avg10:>+8.2f}% | {pf_str:>7}")
        else:
            print(f"  {tier:>4} | {0:>5} | {'---':>7} | {'---':>9} | {'---':>9} | {'---':>7}")

    # Top-N表现
    print("\n  每日Top-N表现:")
    for n in [3, 5, 10]:
        tops = []
        for date, group in df_scored.groupby('report_date'):
            tops.append(group.nlargest(n, 'adj_score'))
        if tops:
            df_top = pd.concat(tops)
            r5 = df_top['return_5d'].dropna()
            if len(r5) > 0:
                wr = (r5 > 0).mean() * 100
                avg = r5.mean()
                print(f"    Top{n}: n={len(r5)}, wr={wr:.1f}%, avg={avg:+.2f}%")

    # 评分分布
    print(f"\n  调整后评分分布:")
    print(f"    min={df_scored['adj_score'].min():.0f}, "
          f"median={df_scored['adj_score'].median():.0f}, "
          f"max={df_scored['adj_score'].max():.0f}")

    # 参数变化
    print(f"\n  参数变化 (vs 默认):")
    changes = []
    for k, v in params.items():
        if v != DEFAULT_PARAMS.get(k):
            changes.append((k, DEFAULT_PARAMS.get(k), v))
    if changes:
        for name, old, new in sorted(changes):
            print(f"    {name}: {old} → {new}")
    else:
        print("    (无变化)")

    return params


def main():
    print("=" * 70)
    print("  全量历史回测重建 + 多轮参数优化")
    print("=" * 70)

    # 第1步: 解析所有报告
    print("\n[1/5] 解析历史报告...")
    df = parse_all_reports()

    # 第2步: 合并已有收益数据
    print("\n[2/5] 合并收益数据...")
    for col in ['return_1d', 'return_3d', 'return_5d', 'return_10d',
                'max_drawdown_5d', 'buy_date', 'buy_price']:
        if col not in df.columns:
            df[col] = np.nan
    df = get_returns_from_existing_csv(df)

    # 第3步: 获取缺失收益
    print("\n[3/5] 获取缺失收益数据...")
    df = fetch_missing_returns(df)

    # 去重
    before = len(df)
    df = df.sort_values('filename', ascending=False).drop_duplicates(
        subset=['code', 'report_date'], keep='first'
    ).sort_values(['report_date', 'rank']).reset_index(drop=True)
    after = len(df)
    if before != after:
        print(f"  去重: {before} → {after} (移除{before - after}条)")

    # 只保留有收益的数据
    df_valid = df[df['return_5d'].notna()].copy()
    print(f"\n  有效数据 (有5d收益): {len(df_valid)} 条, {df_valid['report_date'].nunique()} 个日期")

    # 特征覆盖率
    print(f"\n  特征覆盖率:")
    for col in ['chase_risk', 'rsi', 'day_change', 'sector_score', 'quant_score',
                'tech_score', 'buy_signals', 'sell_signals']:
        if col in df_valid.columns:
            filled = df_valid[col].notna().sum()
            print(f"    {col}: {filled}/{len(df_valid)} ({filled/len(df_valid)*100:.0f}%)")

    # 保存重建的CSV
    output_csv = os.path.join(RESULTS_DIR, f'backtest_rebuilt_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
    df.to_csv(output_csv, index=False, encoding='utf-8-sig')
    print(f"\n  已保存重建数据: {output_csv}")

    # 第4步: 多轮优化
    print("\n[4/5] 开始多轮优化...")
    params = dict(DEFAULT_PARAMS)

    # 基线评估
    base_result = evaluate(df_valid, params)
    print(f"\n  当前算法基线: wr={base_result['wr']:.1f}%, avg={base_result['avg']:+.2f}%, "
          f"n={base_result['n']}, top_wr={base_result['top_wr']:.1f}%")

    # Round 1: 单参数扫描
    params, improvements = round1_single_scan(df_valid, params)
    r1_result = evaluate(df_valid, params)
    print(f"\n  第1轮后: wr={r1_result['wr']:.1f}%, avg={r1_result['avg']:+.2f}%, n={r1_result['n']}")

    # Round 2: 精细化
    params = round2_refinement(df_valid, params)
    r2_result = evaluate(df_valid, params)
    print(f"\n  第2轮后: wr={r2_result['wr']:.1f}%, avg={r2_result['avg']:+.2f}%, n={r2_result['n']}")

    # Round 3: 组合搜索
    params = round3_combo_search(df_valid, params)
    r3_result = evaluate(df_valid, params)
    print(f"\n  第3轮后: wr={r3_result['wr']:.1f}%, avg={r3_result['avg']:+.2f}%, n={r3_result['n']}")

    # Round 4: 阈值搜索
    best_threshold = round4_threshold_search(df_valid, params)

    # 第5步: 最终结果
    print("\n[5/5] 最终结果...")
    final_params = print_final_results(df_valid, params, best_threshold)

    # 保存优化结果
    result_json = {
        'timestamp': datetime.now().isoformat(),
        'data_rows': len(df_valid),
        'data_dates': df_valid['report_date'].nunique(),
        'date_range': f"{df_valid['report_date'].min()} ~ {df_valid['report_date'].max()}",
        'optimal_threshold': best_threshold,
        'params': params,
        'baseline': {
            'wr': base_result['wr'],
            'avg': base_result['avg'],
            'n': base_result['n']
        },
        'optimized': {
            'wr': r3_result['wr'],
            'avg': r3_result['avg'],
            'n': r3_result['n']
        }
    }

    result_path = os.path.join(RESULTS_DIR, f'optimization_result_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, indent=2, ensure_ascii=False)
    print(f"\n  优化结果已保存: {result_path}")

    return params, best_threshold


if __name__ == '__main__':
    main()
