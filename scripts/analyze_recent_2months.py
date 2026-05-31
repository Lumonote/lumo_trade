#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最近两个月(2026-04 ~ 2026-05)投资机会挖掘结果深度分析
==========================================================
解析 results/opportunity_top10_YYYYMMDD_HHMMSS.md 报告,
用本地 OHLCV 缓存计算每只入选股的前瞻收益(次日开盘买入, 第N日收盘卖出),
评估评分/评级/各因子对实际市场表现的预测力, 定位优化方向。
"""
import os, re, sys, glob, json
from datetime import datetime
import numpy as np
import pandas as pd

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
REPORT_DIR = os.path.join(PROJECT, 'results')

from data.cache.data_cache import get_ohlcv

# ----------------------------- 解析报告 -----------------------------
RE_ROW = re.compile(
    r'<tr>.*?<td[^>]*>(\d+)</td>'      # rank
    r'<td[^>]*>(\d{6})</td>'            # code
    r'<td[^>]*>(.*?)</td>'             # name
    r'<td[^>]*>([\d.]+)</td>'          # score
    r'<td[^>]*>(.*?)</td>\s*</tr>',    # detail blob
    re.S)

def _f(m, g=1, d=None):
    return float(m.group(g)) if m else d

def parse_detail(detail):
    out = {}
    m = re.search(r'评级\s*(A\+|S|A|B|C)', detail);  out['rating'] = m.group(1) if m else None
    m = re.search(r'【涨幅】当日:([+-]?[\d.]+)%[，,]3日:([+-]?[\d.]+)%[，,]5日:([+-]?[\d.]+)%', detail)
    out['ent_1d'], out['ent_3d'], out['ent_5d'] = (_f(m,1),_f(m,2),_f(m,3)) if m else (None,None,None)
    m = re.search(r'【板块】.*?\(([^,，()]+)[,，]\s*([^,，()]+)[,，]\s*(\d+)分\)', detail)
    out['sector_change'] = (None if not m or m.group(1).strip()=='—' else
                            _f(re.match(r'([+-]?[\d.]+)', m.group(1).strip()),1))
    out['sector_status'] = m.group(2).strip() if m else None
    out['sector_score'] = _f(m,3) if m else None
    m = re.search(r'【量化】买(\d+)/卖(\d+)/总(\d+)\((\d+)%\)[，,](\d+)分', detail)
    if m:
        out['buy_sig'],out['sell_sig'],out['tot_sig'],out['sig_pct'],out['quant_score'] = (
            int(m.group(1)),int(m.group(2)),int(m.group(3)),int(m.group(4)),float(m.group(5)))
    m = re.search(r'【技术】RSI:([\d.]+)[，,]MACD:([^，,]+)[，,].*?(\d+)分', detail)
    out['rsi'] = _f(m,1); out['macd'] = m.group(2).strip() if m else None; out['tech_score'] = _f(m,3)
    m = re.search(r'【基本面】营收:([+-]?[\d.]+)%[，,]利润:([+-]?[\d.]+)%[，,](\d+)分', detail)
    out['rev_yoy'],out['profit_yoy'],out['fund_score'] = (_f(m,1),_f(m,2),_f(m,3)) if m else (None,None,None)
    m = re.search(r'追高风险:\s*[^\(（]*[\(（](\d+)分', detail);  out['chase_risk'] = _f(m,1)
    m = re.search(r'高级评分:\s*([\d.]+)分', detail);            out['adv_score'] = _f(m,1)
    m = re.search(r'集中度([\d.]+)%', detail);                  out['chip_conc'] = _f(m,1)
    m = re.search(r'控盘评分([\d.]+)/100', detail);             out['control'] = _f(m,1)
    m = re.search(r'主力连续净(流入|流出)(\d+)天', detail)
    out['mf_dir'] = m.group(1) if m else None
    out['mf_days'] = (int(m.group(2)) * (1 if m and m.group(1)=='流入' else -1)) if m else None
    m = re.search(r'散户成交额占比([\d.]+)%', detail);          out['retail_pct'] = _f(m,1)
    out['has_momentum'] = 1 if '牛股动量识别' in detail else 0
    out['has_limitup_pen'] = 1 if '连板涨停惩罚' in detail else 0
    out['repeat_pick'] = 1 if '历史重复入选' in detail else 0
    return out

def latest_report_per_day(months):
    by_day = {}
    for path in glob.glob(os.path.join(REPORT_DIR, 'opportunity_top10_2*.md')):
        base = os.path.basename(path)
        if 'xueqiu' in base:
            continue
        m = re.search(r'(\d{8})_(\d{6})', base)
        if not m:
            continue
        ym = m.group(1)[:6]
        if ym not in months:
            continue
        day = m.group(1); ts = m.group(2)
        if day not in by_day or ts > by_day[day][0]:
            by_day[day] = (ts, path)
    return {d: v[1] for d, v in by_day.items()}

def extract():
    rows = []
    files = latest_report_per_day({'202604','202605'})
    for day in sorted(files):
        rdate = f"{day[:4]}-{day[4:6]}-{day[6:8]}"
        txt = open(files[day], encoding='utf-8').read()
        # 只取综合排名 TOP 表格区域(第一张表), 避免抓到其它表
        seg = txt.split('## 📈')[0] if '## 📈' in txt else txt
        for m in RE_ROW.finditer(seg):
            rank, code, name, score, detail = m.groups()
            rec = {'report_date': rdate, 'rank': int(rank), 'code': code,
                   'name': re.sub(r'<.*?>','',name).strip(), 'score': float(score)}
            rec.update(parse_detail(detail))
            rows.append(rec)
    return pd.DataFrame(rows)

# ----------------------------- 前瞻收益 -----------------------------
_price = {}
def price_df(code):
    if code not in _price:
        try:
            df = get_ohlcv(code, min_rows=2, max_age_seconds=10**12)
            if df is not None and len(df):
                tc = 'timestamps' if 'timestamps' in df.columns else 'timestamp'
                df = df.copy(); df['d'] = pd.to_datetime(df[tc]).dt.normalize()
                df = df.sort_values('d').reset_index(drop=True)
            _price[code] = df
        except Exception:
            _price[code] = None
    return _price[code]

def fwd_returns(code, rdate):
    df = price_df(code)
    out = {k: None for k in ['return_1d','return_3d','return_5d','return_10d','mdd_5d']}
    if df is None or not len(df):
        return out
    rdt = pd.to_datetime(rdate).normalize()
    fut = df[df['d'] > rdt].reset_index(drop=True)
    if len(fut) < 1:
        return out
    buy = fut.iloc[0]['open']
    if not buy or buy <= 0:
        return out
    for n, k in [(1,'return_1d'),(3,'return_3d'),(5,'return_5d'),(10,'return_10d')]:
        if len(fut) >= n:
            out[k] = (fut.iloc[n-1]['close']/buy - 1)*100
    if len(fut) >= 5:
        out['mdd_5d'] = (fut.iloc[:5]['low'].min()/buy - 1)*100
    return out

# ----------------------------- 统计工具 -----------------------------
def stat(s):
    s = pd.Series(s).dropna()
    if len(s)==0: return dict(n=0, avg=np.nan, wr=np.nan, med=np.nan)
    return dict(n=len(s), avg=s.mean(), wr=(s>0).mean()*100, med=s.median())

def show_buckets(df, col, edges, labels, ret='return_5d'):
    print(f"\n--- {col} 分桶 vs {ret} ---")
    print(f"{'桶':<16}{'n':>5}{'5d均收益':>10}{'胜率':>8}{'10d均':>9}")
    for i,(lo,hi) in enumerate(zip(edges[:-1],edges[1:])):
        sub = df[(df[col]>=lo)&(df[col]<hi)]
        st = stat(sub[ret]); st10 = stat(sub['return_10d'])
        if st['n']:
            print(f"{labels[i]:<16}{st['n']:>5}{st['avg']:>+9.2f}%{st['wr']:>7.1f}%{st10['avg']:>+8.2f}%")

def corr_table(df, cols, ret='return_5d'):
    print(f"\n=== 因子 vs {ret} 相关性 (Pearson / Spearman) ===")
    sub = df.dropna(subset=[ret])
    rows=[]
    for c in cols:
        v = sub[[c,ret]].dropna()
        if len(v) >= 20:
            pe = v[c].corr(v[ret]); sp = v[c].corr(v[ret], method='spearman')
            rows.append((c, pe, sp, len(v)))
    for c,pe,sp,n in sorted(rows, key=lambda x: x[1]):
        print(f"  {c:<14} pearson={pe:+.3f}  spearman={sp:+.3f}  (n={n})")

# ----------------------------- 主流程 -----------------------------
def main():
    df = extract()
    print(f"解析报告: {df['report_date'].nunique()} 个交易日, {len(df)} 条入选记录")
    print(f"日期范围: {df['report_date'].min()} ~ {df['report_date'].max()}")

    rr = df.apply(lambda r: fwd_returns(r['code'], r['report_date']), axis=1, result_type='expand')
    df = pd.concat([df, rr], axis=1)

    print("\n=== 前瞻收益覆盖率 ===")
    for c in ['return_1d','return_3d','return_5d','return_10d']:
        print(f"  {c}: {df[c].notna().sum()}/{len(df)}")

    # 仅保留有5日收益的样本用于核心分析
    d5 = df[df['return_5d'].notna()].copy()
    print(f"\n核心分析样本(有5日收益): {len(d5)} 条")

    print("\n" + "="*60)
    print("一、评级分层表现 (核心: 高评级是否=高收益?)")
    print("="*60)
    print(f"{'评级':<6}{'n':>5}{'5d均':>9}{'5d胜率':>9}{'5d中位':>9}{'10d均':>9}{'最大回撤':>10}")
    order = ['S','A+','A','B','C']
    for r in order:
        sub = d5[d5['rating']==r]
        if len(sub)==0: continue
        st=stat(sub['return_5d']); st10=stat(sub['return_10d']); mdd=stat(sub['mdd_5d'])
        print(f"{r:<6}{st['n']:>5}{st['avg']:>+8.2f}%{st['wr']:>8.1f}%{st['med']:>+8.2f}%{st10['avg']:>+8.2f}%{mdd['avg']:>+9.2f}%")

    print("\n" + "="*60)
    print("二、评分区间表现 + 单调性检验")
    print("="*60)
    print(f"{'区间':<12}{'n':>5}{'5d均':>9}{'5d胜率':>9}{'10d均':>9}")
    for lo,hi,lab in [(85,200,'≥85 (S)'),(82,85,'82-85(A+)'),(78,82,'78-82(A)'),
                      (74,78,'74-78'),(70,74,'70-74(B)'),(65,70,'65-70'),(0,65,'<65(C)')]:
        sub=d5[(d5['score']>=lo)&(d5['score']<hi)]
        st=stat(sub['return_5d']); st10=stat(sub['return_10d'])
        if st['n']:
            print(f"{lab:<12}{st['n']:>5}{st['avg']:>+8.2f}%{st['wr']:>8.1f}%{st10['avg']:>+8.2f}%")

    for ret in ['return_1d','return_3d','return_5d','return_10d']:
        v = d5.dropna(subset=[ret])
        if len(v)>=20:
            print(f"  score↔{ret}: pearson={v['score'].corr(v[ret]):+.3f} "
                  f"spearman={v['score'].corr(v[ret],method='spearman'):+.3f} (n={len(v)})")

    print("\n" + "="*60)
    print("三、各因子对5日收益的预测力")
    print("="*60)
    corr_table(d5, ['score','chase_risk','rsi','buy_sig','sell_sig','quant_score',
                    'tech_score','sector_score','fund_score','adv_score','chip_conc',
                    'control','mf_days','retail_pct','ent_1d','ent_3d','ent_5d','rank'])

    print("\n" + "="*60)
    print("四、关键因子分桶")
    print("="*60)
    show_buckets(d5,'chase_risk',[0,1,30,50,70,101],['0(无)','1-30','30-50','50-70','70+'])
    show_buckets(d5,'rsi',[0,40,50,60,70,200],['<40','40-50','50-60','60-70','70+'])
    show_buckets(d5,'sell_sig',[0,1,2,3,99],['0','1','2','3+'])
    show_buckets(d5,'buy_sig',[0,4,7,10,99],['<4','4-6','7-9','10+'])
    show_buckets(d5,'quant_score',[0,50,80,95,101],['<50','50-80','80-95','95+'])
    show_buckets(d5,'sector_score',[0,50,60,75,85,101],['<50','50-60','60-75','75-85','85+'])
    show_buckets(d5,'ent_5d',[-100,-3,3,10,18,999],['<-3%','-3~3%','3~10%','10~18%','18%+'])
    show_buckets(d5,'chip_conc',[0,20,30,40,999],['<20%','20-30%','30-40%','40%+'])
    show_buckets(d5,'adv_score',[0,45,50,55,999],['<45','45-50','50-55','55+'])

    print("\n" + "="*60)
    print("五、失败模式: 高分却亏损 (score≥78 且 5d≤-5%)")
    print("="*60)
    bad = d5[(d5['score']>=78)&(d5['return_5d']<=-5)].sort_values('return_5d')
    print(f"共 {len(bad)} 条 (占≥78分样本 {len(bad)}/{len(d5[d5['score']>=78])} = "
          f"{100*len(bad)/max(1,len(d5[d5['score']>=78])):.1f}%)")
    for _,r in bad.head(15).iterrows():
        print(f"  {r['report_date']} {r['code']} {r['name'][:6]:<7} 分{r['score']:.1f}({r['rating']}) "
              f"5d={r['return_5d']:+.1f}% | chase={r['chase_risk']:.0f} rsi={r['rsi']:.0f} "
              f"sell={r.get('sell_sig')} ent5d={r['ent_5d']:+.0f}% sec={r['sector_score']:.0f}")

    print("\n" + "="*60)
    print("六、错失牛股: 低分却大涨 (score<74 且 5d≥10%)")
    print("="*60)
    miss = d5[(d5['score']<74)&(d5['return_5d']>=10)].sort_values('return_5d',ascending=False)
    print(f"共 {len(miss)} 条")
    for _,r in miss.head(12).iterrows():
        print(f"  {r['report_date']} {r['code']} {r['name'][:6]:<7} 分{r['score']:.1f}({r['rating']}) "
              f"5d={r['return_5d']:+.1f}% | chase={r['chase_risk']:.0f} rsi={r['rsi']:.0f} "
              f"buy={r.get('buy_sig')} quant={r.get('quant_score')} sec={r['sector_score']:.0f}")

    print("\n" + "="*60)
    print("七、按月 & 按排名 表现")
    print("="*60)
    d5['month'] = d5['report_date'].str[:7]
    for mth in sorted(d5['month'].unique()):
        sub=d5[d5['month']==mth]; st=stat(sub['return_5d'])
        print(f"  {mth}: n={st['n']:>3}  5d均={st['avg']:+.2f}%  胜率={st['wr']:.1f}%")
    print("  --- 按排名 ---")
    for lo,hi,lab in [(1,4,'Top1-3'),(4,6,'4-5'),(6,11,'6-10'),(11,21,'11-20')]:
        sub=d5[(d5['rank']>=lo)&(d5['rank']<hi)]; st=stat(sub['return_5d'])
        if st['n']: print(f"  {lab:<8} n={st['n']:>3}  5d均={st['avg']:+.2f}%  胜率={st['wr']:.1f}%")

    print(f"\n  全样本5日: 均={d5['return_5d'].mean():+.2f}% 胜率={(d5['return_5d']>0).mean()*100:.1f}% "
          f"中位={d5['return_5d'].median():+.2f}%")

    out = os.path.join(REPORT_DIR, 'recent_2months_analysis.csv')
    df.to_csv(out, index=False, encoding='utf-8-sig')
    print(f"\n明细已保存: {out}")

if __name__ == '__main__':
    main()
