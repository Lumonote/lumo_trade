"""
用 v20 当前算法 (simulate_v5_backtest.apply_v8_scoring) 对 2026-01-01 起所有报告重新打分
筛 v8_score>=80, T+1 开盘买, T+5 收盘卖 — 验证算法迭代是否真的有效
"""
import os, sys, re, json, glob, time
from datetime import datetime, timedelta
import pandas as pd
import tushare as ts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
RESULTS = os.path.join(ROOT, 'results')

from scripts.rebuild_and_optimize import parse_new_format, parse_old_format
from scripts.simulate_v5_backtest import apply_v8_scoring


def load_api():
    cfg = json.load(open(os.path.join(ROOT, 'config', 'tushare_config.json')))
    ts.set_token(cfg['tushare']['token'])
    return ts.pro_api()


def parse_one(fp):
    txt = open(fp, encoding='utf-8').read()
    is_new = '【概览】' in txt or '【涨幅】' in txt
    rows = []

    # HTML 形式 (recent)
    pat_html = re.compile(
        r'<tr>\s*<td[^>]*>\s*(\d+)\s*</td>\s*'
        r'<td[^>]*>\s*(\d{6})\s*</td>\s*'
        r'<td[^>]*>([^<]+)</td>\s*'
        r'<td[^>]*>\s*([\d.]+)\s*</td>\s*'
        r'<td[^>]*>(.+?)</td>\s*</tr>',
        re.DOTALL,
    )
    for m in pat_html.finditer(txt):
        rank = int(m.group(1))
        if rank > 20:
            continue
        code = m.group(2)
        name = m.group(3).strip()
        score = float(m.group(4))
        detail = re.sub(r'<[^>]+>', ' ', m.group(5))
        feat = parse_new_format(detail, code) if is_new else parse_old_format(detail, code)
        rows.append({'rank': rank, 'code': code, 'name': name, 'score': score, **feat})
    if rows:
        return rows

    # Markdown 形式
    pat_md = re.compile(
        r'\|\s*(\d+)\s*\|\s*(\d{6})\s*\|\s*(.+?)\s*\|\s*(\d+\.?\d*)\s*\|\s*(.+?)\s*\|',
    )
    for m in pat_md.finditer(txt):
        rank = int(m.group(1))
        if rank > 20:
            continue
        code = m.group(2)
        name = m.group(3).strip().replace(' ', '')
        score = float(m.group(4))
        detail = m.group(5)
        feat = parse_new_format(detail, code) if is_new else parse_old_format(detail, code)
        rows.append({'rank': rank, 'code': code, 'name': name, 'score': score, **feat})
    return rows


def collect():
    files = sorted(glob.glob(os.path.join(RESULTS, 'opportunity_top10_*.md')))
    by_date = {}
    for fp in files:
        b = os.path.basename(fp)
        if 'wechat' in b or 'alignment' in b or 'xueqiu' in b:
            continue
        m = re.search(r'(\d{8})_\d{6}\.md$', b)
        if not m:
            continue
        d = m.group(1)
        di = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
        if di < '2025-11-01':
            continue
        by_date[di] = fp  # 同日最后一个

    all_rows = []
    for di in sorted(by_date):
        for r in parse_one(by_date[di]):
            r['report_date'] = di
            r['filename'] = os.path.basename(by_date[di])
            all_rows.append(r)
    return pd.DataFrame(all_rows)


def to_ts(c):
    if c.startswith(('6', '9')): return c + '.SH'
    if c.startswith(('0', '3', '2')): return c + '.SZ'
    return c + '.BJ'


def main():
    print('解析所有报告 (>=2026-01-01)...')
    df = collect()
    print(f'  入选 (top20 全集): {len(df)} 条, {df.report_date.nunique()} 天')

    # 关键特征覆盖率
    for col in ['rsi', 'day_change', 'change_3d', 'change_5d', 'chase_risk',
                'buy_signals', 'sell_signals', 'sector_score', 'quant_score', 'tech_score']:
        cov = df[col].notna().mean() * 100 if col in df.columns else 0
        print(f'    {col}: {cov:.1f}% 覆盖率')

    print('\n应用 v20 算法 (simulate_v5_backtest.apply_v8_scoring)...')
    df_v20 = apply_v8_scoring(df)
    print(f'  原始 score: min={df_v20.score.min():.1f} mean={df_v20.score.mean():.1f} max={df_v20.score.max():.1f}')
    print(f'  v20 score : min={df_v20.v8_score.min():.1f} mean={df_v20.v8_score.mean():.1f} max={df_v20.v8_score.max():.1f}')

    sel = df_v20[df_v20.v8_score >= 80].copy()
    print(f'\n  v20_score>=80: {len(sel)} 条 (vs 原始 score>=80: {(df_v20.score>=80).sum()} 条)')

    # cutoff
    cutoff = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
    sel = sel[sel.report_date <= cutoff].reset_index(drop=True)
    print(f'  预留10日后可回测: {len(sel)} 条')

    api = load_api()
    cal_start = sel.report_date.min().replace('-', '')
    cal_end = (datetime.now() + timedelta(days=10)).strftime('%Y%m%d')
    cal = api.trade_cal(exchange='SSE', start_date=cal_start, end_date=cal_end)
    tdays = sorted(cal[cal.is_open == 1].cal_date.tolist())

    def nxt(di, n):
        d = di.replace('-', '')
        f = [t for t in tdays if t > d]
        return f[n - 1] if len(f) >= n else None

    rows = []
    for i, r in sel.iterrows():
        buy_d = nxt(r.report_date, 1)
        sell_d = nxt(r.report_date, 5)
        if not (buy_d and sell_d):
            continue
        try:
            tsc = to_ts(r.code)
            df_p = api.daily(ts_code=tsc, start_date=buy_d, end_date=sell_d)
            if df_p is None or len(df_p) == 0:
                continue
            p = {x.trade_date: x for _, x in df_p.iterrows()}
            if buy_d not in p or sell_d not in p:
                continue
            bo = float(p[buy_d].open)
            sc = float(p[sell_d].close)
            if bo <= 0:
                continue
            rows.append({
                'report_date': r.report_date, 'code': r.code, 'name': r.get('name', ''),
                'orig_score': r.score, 'v20_score': r.v8_score,
                'rsi': r.get('rsi'), 'buy_sig': r.get('buy_signals'), 'sell_sig': r.get('sell_signals'),
                'chase': r.get('chase_risk'), 'day_chg': r.get('day_change'),
                'buy_open': bo, 'sell_close': sc,
                'ret': (sc - bo) / bo * 100,
            })
        except Exception:
            pass
        if (i + 1) % 50 == 0:
            time.sleep(0.8)
        else:
            time.sleep(0.12)

    df_r = pd.DataFrame(rows)
    print(f'\n实际成交 {len(df_r)} 条')
    if len(df_r) == 0:
        return

    out = os.path.join(RESULTS, f'backtest_v20rescore_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
    df_r.to_csv(out, index=False)

    print('\n' + '=' * 70)
    print('用 v20 当前算法重打分后筛 ≥80 的实盘回测结果')
    print('=' * 70)
    n = len(df_r)
    print(f'  样本数:        {n}')
    print(f'  平均收益:      {df_r.ret.mean():.3f}%')
    print(f'  中位数收益:    {df_r.ret.median():.3f}%')
    print(f'  胜率:          {(df_r.ret > 0).mean() * 100:.2f}%')
    print(f'  最大盈利:      {df_r.ret.max():.2f}%')
    print(f'  最大亏损:      {df_r.ret.min():.2f}%')
    print(f'  覆盖日期数:    {df_r.report_date.nunique()}')
    cycles = 252 / 5
    ann = ((1 + df_r.ret.mean() / 100) ** cycles - 1) * 100
    print(f'  年化估算:      {ann:.2f}%  (252/5={cycles:.1f}次复利)')

    print('\n— 对照: 原始 markdown 字面 score>=80 (上一轮已得 42% wr)')

    # 按 v20_score 区间
    df_r['bin'] = pd.cut(df_r.v20_score, bins=[80, 82, 85, 90, 200], right=False)
    print('\n按 v20 重打分区间:')
    print(df_r.groupby('bin', observed=True).agg(
        n=('ret', 'count'),
        avg=('ret', 'mean'),
        win=('ret', lambda s: (s > 0).mean() * 100),
    ).round(2).to_string())

    # PRE/POST 切分
    print('\nPRE/POST 2026-03-08 切分:')
    for lab, sub in [('PRE  ', df_r[df_r.report_date < '2026-03-08']),
                      ('POST ', df_r[df_r.report_date >= '2026-03-08'])]:
        if len(sub) == 0: continue
        print(f'  {lab} n={len(sub):3d}  avg={sub.ret.mean():+.3f}%  win={(sub.ret > 0).mean() * 100:.2f}%')

    print(f'\n明细: {out}')


if __name__ == '__main__':
    main()
