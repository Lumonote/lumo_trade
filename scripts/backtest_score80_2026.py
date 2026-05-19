"""
回测脚本: 2026-01-01 起, 综合得分>=80分股票
买入: 报告次日开盘价
卖出: 第5个交易日收盘价
计算: 平均收益、胜率、年化收益
"""
import os
import re
import json
import glob
import time
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd
import tushare as ts

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, 'results')
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'config', 'tushare_config.json')

START_DATE = '2026-01-01'
SCORE_THRESHOLD = 80.0
HOLD_DAYS = int(os.environ.get('HOLD_DAYS', 5))  # 第N个交易日收盘卖出


def load_tushare():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    token = cfg.get('tushare', {}).get('token', '')
    ts.set_token(token)
    return ts.pro_api()


def parse_report(filepath):
    """从一个报告文件抽取 (code, score) 列表."""
    with open(filepath, encoding='utf-8') as f:
        text = f.read()

    rows = []

    # 形式1: HTML表格 <tr><td>rank</td><td>code</td><td>name</td><td>score</td>...
    html_pattern = re.compile(
        r'<tr>\s*<td[^>]*>\s*(\d+)\s*</td>\s*'
        r'<td[^>]*>\s*(\d{6})\s*</td>\s*'
        r'<td[^>]*>([^<]+)</td>\s*'
        r'<td[^>]*>\s*([\d.]+)\s*</td>',
        re.DOTALL,
    )
    for m in html_pattern.finditer(text):
        try:
            rows.append((m.group(2), float(m.group(4))))
        except ValueError:
            pass

    if rows:
        return rows

    # 形式2: markdown表 | rank | code | name | score |
    md_pattern = re.compile(
        r'\|\s*\d+\s*\|\s*(\d{6})\s*\|\s*[^|]+\|\s*([\d.]+)\s*\|',
    )
    for m in md_pattern.finditer(text):
        try:
            rows.append((m.group(1), float(m.group(2))))
        except ValueError:
            pass

    return rows


def collect_report_data():
    """归并按日期, 同日取最后一个文件 (排除wechat文件)."""
    pattern = os.path.join(RESULTS_DIR, 'opportunity_top10_*.md')
    files = sorted(glob.glob(pattern))

    by_date = {}
    for fp in files:
        base = os.path.basename(fp)
        if 'wechat' in base or 'alignment' in base or 'xueqiu' in base:
            continue
        m = re.search(r'(\d{8})_\d{6}\.md$', base)
        if not m:
            continue
        date_str = m.group(1)
        date_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        if date_iso < START_DATE:
            continue
        by_date[date_iso] = fp  # sorted, 后面的覆盖前面 → 同日最后一个

    selections = []
    for date_iso in sorted(by_date.keys()):
        fp = by_date[date_iso]
        rows = parse_report(fp)
        for code, score in rows:
            if score >= SCORE_THRESHOLD:
                selections.append({
                    'report_date': date_iso,
                    'code': code,
                    'score': score,
                    'file': os.path.basename(fp),
                })
    return selections


def to_ts_code(code):
    if code.startswith(('6', '9')):
        return f"{code}.SH"
    if code.startswith(('0', '3', '2')):
        return f"{code}.SZ"
    if code.startswith(('8', '4')):
        return f"{code}.BJ"
    return f"{code}.SZ"


def get_trade_calendar(api, start, end):
    cal = api.trade_cal(exchange='SSE', start_date=start, end_date=end)
    return sorted(cal[cal['is_open'] == 1]['cal_date'].tolist())


def main():
    print(f"扫描 {RESULTS_DIR} 报告 (>= {START_DATE}, score >= {SCORE_THRESHOLD})...")
    selections = collect_report_data()
    if not selections:
        print("没有找到符合条件的记录。")
        return

    print(f"  入选记录: {len(selections)} 条")
    df_sel = pd.DataFrame(selections)
    print(f"  覆盖日期: {df_sel['report_date'].nunique()} 天 ({df_sel['report_date'].min()} ~ {df_sel['report_date'].max()})")

    api = load_tushare()

    cutoff = (datetime.now() - timedelta(days=HOLD_DAYS + 2)).strftime('%Y-%m-%d')
    df_sel = df_sel[df_sel['report_date'] <= cutoff].reset_index(drop=True)
    print(f"  可回测记录(预留{HOLD_DAYS+2}天): {len(df_sel)} 条")

    cal_start = df_sel['report_date'].min().replace('-', '')
    cal_end = (datetime.now() + timedelta(days=10)).strftime('%Y%m%d')
    trade_days = get_trade_calendar(api, cal_start, cal_end)

    def next_n(date_iso, n):
        d = date_iso.replace('-', '')
        fut = [t for t in trade_days if t > d]
        return fut[n - 1] if len(fut) >= n else None

    results = []
    api_calls = 0
    for _, row in df_sel.iterrows():
        code = row['code']
        ts_code = to_ts_code(code)
        buy_day = next_n(row['report_date'], 1)
        # 持仓 HOLD_DAYS 个交易日: 第1日买入, 第HOLD_DAYS日卖出 (买入当日算第1日)
        sell_day = next_n(row['report_date'], HOLD_DAYS)
        if not buy_day or not sell_day:
            continue
        try:
            df_p = api.daily(ts_code=ts_code, start_date=buy_day, end_date=sell_day)
            api_calls += 1
            if df_p is None or len(df_p) == 0:
                continue
            df_p = df_p.sort_values('trade_date')
            prices = {r['trade_date']: r for _, r in df_p.iterrows()}
            if buy_day not in prices or sell_day not in prices:
                continue
            buy_open = float(prices[buy_day]['open'])
            sell_close = float(prices[sell_day]['close'])
            if buy_open <= 0:
                continue
            ret_pct = (sell_close - buy_open) / buy_open * 100
            results.append({
                'report_date': row['report_date'],
                'code': code,
                'score': row['score'],
                'buy_date': buy_day,
                'buy_open': buy_open,
                'sell_date': sell_day,
                'sell_close': sell_close,
                'return_pct': ret_pct,
            })
        except Exception as e:
            print(f"  ⚠️ {code} {row['report_date']} 失败: {e}")
        if api_calls % 50 == 0 and api_calls > 0:
            time.sleep(1)
        else:
            time.sleep(0.15)

    print(f"\nAPI 调用 {api_calls} 次, 成功 {len(results)} 条")
    if not results:
        print("无可用回测记录")
        return

    df_r = pd.DataFrame(results)
    out_csv = os.path.join(RESULTS_DIR, f"backtest_score80_2026_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    df_r.to_csv(out_csv, index=False)

    avg_ret = df_r['return_pct'].mean()
    median_ret = df_r['return_pct'].median()
    win_rate = (df_r['return_pct'] > 0).mean() * 100
    n = len(df_r)
    cycles_per_year = 252 / HOLD_DAYS  # 一年250-252交易日
    annualized = ((1 + avg_ret / 100) ** cycles_per_year - 1) * 100

    print("\n" + "=" * 60)
    print(f"回测结果: 报告日 >= {START_DATE}, 综合得分 >= {SCORE_THRESHOLD}")
    print(f"持仓策略: 报告次日开盘买入, 第{HOLD_DAYS}个交易日收盘卖出")
    print("=" * 60)
    print(f"  样本数:        {n}")
    print(f"  平均单次收益:  {avg_ret:.3f}%")
    print(f"  中位数收益:    {median_ret:.3f}%")
    print(f"  胜率:          {win_rate:.2f}%")
    print(f"  最大单笔收益:  {df_r['return_pct'].max():.2f}%")
    print(f"  最大单笔亏损:  {df_r['return_pct'].min():.2f}%")
    print(f"  覆盖日期数:    {df_r['report_date'].nunique()}")
    print(f"  年化收益估算:  {annualized:.2f}%  (按 252/{HOLD_DAYS} = {cycles_per_year:.1f} 次复利)")
    print(f"\n结果已保存: {out_csv}")

    by_score = df_r.copy()
    by_score['score_bin'] = pd.cut(by_score['score'], bins=[80, 82, 85, 90, 100], right=False)
    bin_stats = by_score.groupby('score_bin', observed=True).agg(
        n=('return_pct', 'count'),
        avg=('return_pct', 'mean'),
        win=('return_pct', lambda s: (s > 0).mean() * 100),
    )
    print("\n分段统计:")
    print(bin_stats.to_string())


if __name__ == '__main__':
    main()
