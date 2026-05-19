"""分析现有回测样本在不同大盘 regime 下的表现差异。
目的: 决定是否值得做 regime 自适应权重。

判定标准:
- 差异 > 5pp 且 p < 0.05 → 值得做
- 差异 < 3pp → regime 自适应是浪费
"""
import os, sys, glob, json
from datetime import datetime
import pandas as pd
import tushare as ts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_api():
    cfg = json.load(open(os.path.join(ROOT, 'config', 'tushare_config.json')))
    ts.set_token(cfg['tushare']['token'])
    return ts.pro_api()


def assess_regime_at(date_str, hs300_df):
    """根据 date_str (YYYYMMDD) 之前的沪深300数据判定 regime"""
    # date_str 是报告日,我们要看报告日前的市场情况
    past = hs300_df[hs300_df['trade_date'] <= date_str].sort_values('trade_date')
    if len(past) < 21:
        return 'unknown'
    today_close = float(past.iloc[-1]['close'])
    close_5d = float(past.iloc[-6]['close']) if len(past) >= 6 else None
    close_20d = float(past.iloc[-21]['close']) if len(past) >= 21 else None
    if close_5d is None or close_20d is None:
        return 'unknown'
    chg_5d = (today_close - close_5d) / close_5d * 100
    chg_20d = (today_close - close_20d) / close_20d * 100
    if chg_5d <= -3 or (chg_5d <= -1 and chg_20d <= -5):
        return 'risk_off'
    if chg_5d >= 3 and chg_20d >= 3:
        return 'risk_on'
    return 'neutral'


def main():
    # 加载现有 v23 重打分回测
    csv = sorted(glob.glob(os.path.join(ROOT, 'results', 'backtest_v20rescore_*.csv')))[-1]
    df = pd.read_csv(csv)
    print(f'加载: {csv}')
    print(f'  样本: {len(df)} 条, 覆盖日期: {df.report_date.nunique()} 天')

    # 拉沪深 300 历史
    api = load_api()
    start = df.report_date.min().replace('-', '')
    end = (datetime.now()).strftime('%Y%m%d')
    print(f'\n拉沪深300 ({start} ~ {end})...')
    hs300 = api.index_daily(ts_code='000300.SH', start_date=start, end_date=end)
    print(f'  拿到 {len(hs300)} 条')

    # 给每个样本标注 regime
    print('\n标注每个报告日的 regime...')
    df['report_date_str'] = df.report_date.str.replace('-', '')
    df['regime'] = df.report_date_str.apply(lambda d: assess_regime_at(d, hs300))

    # 分组统计
    print('\n=== Regime 分布 ===')
    print(df.regime.value_counts())

    print('\n=== 按 regime + 评分区间分组的胜率 ===')
    df['bin'] = pd.cut(df.v20_score, bins=[80, 82, 85, 90, 200], right=False)
    grp = df.groupby(['regime', 'bin'], observed=True).agg(
        n=('ret', 'count'),
        avg=('ret', 'mean'),
        win=('ret', lambda s: (s > 0).mean() * 100),
    ).round(2)
    print(grp.to_string())

    print('\n=== 按 regime 整体表现(≥80 全样本) ===')
    by_regime = df.groupby('regime').agg(
        n=('ret', 'count'),
        avg=('ret', 'mean'),
        win=('ret', lambda s: (s > 0).mean() * 100),
        median=('ret', 'median'),
    ).round(2)
    print(by_regime.to_string())

    # 显著性检验:risk_on vs risk_off (如果都有足够样本)
    print('\n=== 显著性检验 ===')
    from scipy import stats
    regimes = df.regime.unique()
    for i in range(len(regimes)):
        for j in range(i + 1, len(regimes)):
            r1, r2 = regimes[i], regimes[j]
            s1 = df[df.regime == r1].ret
            s2 = df[df.regime == r2].ret
            if len(s1) < 5 or len(s2) < 5:
                continue
            wr1 = (s1 > 0).mean()
            wr2 = (s2 > 0).mean()
            # 二项分布的 z 检验近似
            n1, n2 = len(s1), len(s2)
            p_pool = (s1.gt(0).sum() + s2.gt(0).sum()) / (n1 + n2)
            se = (p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) ** 0.5
            z = (wr1 - wr2) / se if se > 0 else 0
            from scipy.stats import norm
            p = 2 * (1 - norm.cdf(abs(z)))
            verdict = '✅ 显著' if p < 0.05 else '⚠️ 不显著'
            print(f'  {r1} vs {r2}: wr {wr1*100:.1f}% vs {wr2*100:.1f}% (Δ {(wr1-wr2)*100:+.1f}pp, n={n1}/{n2}, z={z:.2f}, p={p:.3f}) {verdict}')

    # 决策
    print('\n=== 是否值得做 regime 自适应 ===')
    if 'risk_off' in by_regime.index and 'risk_on' in by_regime.index:
        diff = abs(by_regime.loc['risk_on', 'win'] - by_regime.loc['risk_off', 'win'])
        if diff > 5:
            print(f'  ✅ risk_on vs risk_off 胜率差 {diff:.1f}pp > 5pp,值得做')
        else:
            print(f'  ❌ risk_on vs risk_off 胜率差 {diff:.1f}pp < 5pp,不值得做')
    elif 'risk_off' not in by_regime.index:
        print('  ⚠️ 历史数据里没有 risk_off 样本(全是牛市/震荡),无法判定')
    else:
        print('  ⚠️ 数据不足,无法判定')


if __name__ == '__main__':
    main()
