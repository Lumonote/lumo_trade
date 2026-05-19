"""核查回测: 分别测试两种口径并按算法版本时间切分."""
import os, re, json, glob, time
from datetime import datetime, timedelta

import pandas as pd
import tushare as ts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT, 'results')

def load_api():
    with open(os.path.join(ROOT, 'config', 'tushare_config.json')) as f:
        cfg = json.load(f)
    ts.set_token(cfg['tushare']['token'])
    return ts.pro_api()

def parse_report(fp):
    txt = open(fp, encoding='utf-8').read()
    rows = []
    pat = re.compile(r'<tr>\s*<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>\s*(\d{6})\s*</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>')
    for m in pat.finditer(txt):
        rows.append((m.group(2), float(m.group(4))))
    if rows:
        return rows
    pat2 = re.compile(r'\|\s*\d+\s*\|\s*(\d{6})\s*\|\s*[^|]+\|\s*([\d.]+)\s*\|')
    for m in pat2.finditer(txt):
        rows.append((m.group(1), float(m.group(2))))
    return rows

def collect():
    files = sorted(glob.glob(os.path.join(RESULTS_DIR, 'opportunity_top10_*.md')))
    by_date = {}
    for fp in files:
        b = os.path.basename(fp)
        if 'wechat' in b or 'alignment' in b or 'xueqiu' in b:
            continue
        m = re.search(r'(\d{8})_\d{6}\.md$', b)
        if not m:
            continue
        d = m.group(1)
        di = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if di < '2026-01-01':
            continue
        by_date[di] = fp
    out = []
    for di in sorted(by_date):
        for code, score in parse_report(by_date[di]):
            if score >= 80:
                out.append({'report_date': di, 'code': code, 'score': score, 'file': os.path.basename(by_date[di])})
    return pd.DataFrame(out)

def to_ts(c):
    if c.startswith(('6','9')): return c+'.SH'
    if c.startswith(('0','3','2')): return c+'.SZ'
    return c+'.BJ'

def main():
    df_sel = collect()
    print(f'入选 {len(df_sel)} 条, {df_sel.report_date.nunique()} 天')

    api = load_api()
    cutoff = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
    df_sel = df_sel[df_sel.report_date <= cutoff].reset_index(drop=True)
    print(f'预留12交易日后可回测: {len(df_sel)} 条')

    cal_start = df_sel.report_date.min().replace('-','')
    cal_end = (datetime.now()+timedelta(days=10)).strftime('%Y%m%d')
    cal = api.trade_cal(exchange='SSE', start_date=cal_start, end_date=cal_end)
    tdays = sorted(cal[cal.is_open==1].cal_date.tolist())

    def nxt(di, n):
        d = di.replace('-','')
        f = [t for t in tdays if t > d]
        return f[n-1] if len(f) >= n else None

    rows = []
    for i, r in df_sel.iterrows():
        code = r.code
        ts_code = to_ts(code)
        # 拉取 T+1 ~ T+11 区间(覆盖两种口径)
        d_buy = nxt(r.report_date, 1)         # T+1
        d_t5  = nxt(r.report_date, 5)         # T+5
        d_t6  = nxt(r.report_date, 6)         # T+6
        d_t11 = nxt(r.report_date, 11)        # T+11
        if not (d_buy and d_t5 and d_t6):
            continue
        try:
            df_p = api.daily(ts_code=ts_code, start_date=d_buy, end_date=d_t11 or d_t6)
            if df_p is None or len(df_p)==0: continue
            p = {row.trade_date: row for _, row in df_p.sort_values('trade_date').iterrows()}
            if d_buy not in p or d_t5 not in p or d_t6 not in p: continue
            buy_open  = float(p[d_buy].open)
            buy_close = float(p[d_buy].close)
            t5_close  = float(p[d_t5].close)
            t6_close  = float(p[d_t6].close)
            if buy_open<=0 or buy_close<=0: continue
            rows.append({
                'report_date': r.report_date, 'code': code, 'score': r.score,
                'buy_open': buy_open, 'buy_close': buy_close,
                't5_close': t5_close, 't6_close': t6_close,
                # 口径A(用户): T+1 open → T+5 close
                'ret_user': (t5_close-buy_open)/buy_open*100,
                # 口径B(项目标准): T+1 close → T+6 close = 持5个交易日
                'ret_proj': (t6_close-buy_close)/buy_close*100,
                # 口径C: T+1 open → T+6 close
                'ret_open_t6':(t6_close-buy_open)/buy_open*100,
            })
        except Exception as e:
            pass
        if (i+1)%50==0: time.sleep(1)
        else: time.sleep(0.12)

    df = pd.DataFrame(rows)
    print(f'\n实际成功记录: {len(df)} 条\n')
    if len(df)==0: return

    def stats(s, name):
        wr = (s>0).mean()*100
        return f'{name}: n={len(s)}, avg={s.mean():.3f}%, median={s.median():.3f}%, win={wr:.2f}%'

    print('='*70)
    print('全样本 (2026-01-05 ~ 2026-04-22 左右)')
    print('='*70)
    print(stats(df.ret_user,  '口径A: T+1 open  → T+5 close (用户要求)    '))
    print(stats(df.ret_proj,  '口径B: T+1 close → T+6 close (项目 simulate)'))
    print(stats(df.ret_open_t6,'口径C: T+1 open  → T+6 close             '))

    # 按 v16 算法修复日 2026-03-08 切分(项目记忆: 之前分组信号惩罚是死代码)
    cut = '2026-03-08'
    pre  = df[df.report_date <  cut]
    post = df[df.report_date >= cut]
    print('\n'+'='*70)
    print(f'切分: 2026-03-08 是 v16 重大 bug 修复日 (惩罚机制此前形同虚设)')
    print('='*70)
    for label, sub in [('PRE  (旧算法,惩罚未生效)', pre), ('POST (修复后,惩罚正常)', post)]:
        if len(sub)==0: continue
        print(f'\n{label}  n={len(sub)}, 日期 {sub.report_date.min()} ~ {sub.report_date.max()}')
        print('  '+stats(sub.ret_user, '口径A T+1open→T+5close'))
        print('  '+stats(sub.ret_proj, '口径B T+1close→T+6close'))

    # 按分数区间
    print('\n'+'='*70)
    print('按 score 区间(口径A 用户) — 全样本')
    print('='*70)
    df['bin'] = pd.cut(df.score, bins=[80,82,85,90,200], right=False)
    print(df.groupby('bin', observed=True).agg(
        n=('ret_user','count'),
        avg_user=('ret_user','mean'),
        win_user=('ret_user', lambda s:(s>0).mean()*100),
        avg_proj=('ret_proj','mean'),
        win_proj=('ret_proj', lambda s:(s>0).mean()*100),
    ).round(2).to_string())

    out = os.path.join(RESULTS_DIR, f'backtest_score80_diag_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
    df.to_csv(out, index=False)
    print(f'\n明细保存: {out}')

if __name__=='__main__':
    main()
