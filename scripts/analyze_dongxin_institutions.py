"""东芯股份(688110.SH) 主力机构/操盘公司/量化资金深度挖掘分析

数据维度:
  1. 龙虎榜 (top_list + top_inst): 操盘券商营业部、机构席位
  2. 大宗交易 (block_trade): 主力大单成交
  3. 资金流向 (moneyflow): 超大单/大单/中单/小单
  4. 北向资金持股 (hk_hold): 外资机构动向
  5. 股东数据 (stk_holdernumber + top10_floatholders): 机构持仓变化
  6. 行情数据 (daily + daily_basic): 价格/换手率背景

输出: results/dongxin_institution_analysis/
"""
import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import tushare as ts

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'results', 'dongxin_institution_analysis')
os.makedirs(OUTPUT_DIR, exist_ok=True)

TS_CODE = '688110.SH'
STOCK_NAME = '东芯股份'
END_DATE = '20260527'
START_DATE = '20260427'


def get_pro():
    with open(os.path.join(PROJECT_ROOT, 'config', 'tushare_config.json'), 'r') as f:
        cfg = json.load(f)
    ts.set_token(cfg['tushare']['token'])
    return ts.pro_api()


def safe_call(fn, name, **kwargs):
    try:
        df = fn(**kwargs)
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        print(f'  [WARN] {name} failed: {e}')
        return pd.DataFrame()


def fetch_trade_calendar(pro, start_date, end_date):
    df = pro.trade_cal(exchange='SSE', start_date=start_date, end_date=end_date, is_open='1')
    return sorted(df['cal_date'].tolist())


def fetch_daily(pro):
    print('[1/8] 行情数据 daily ...')
    df = pro.daily(ts_code=TS_CODE, start_date=START_DATE, end_date=END_DATE)
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['pct_chg'] = df['pct_chg'].astype(float)
    df.to_csv(os.path.join(OUTPUT_DIR, '01_daily.csv'), index=False)
    print(f'  -> {len(df)} 行')
    return df


def fetch_daily_basic(pro):
    print('[2/8] 基本面指标 daily_basic ...')
    df = pro.daily_basic(ts_code=TS_CODE, start_date=START_DATE, end_date=END_DATE)
    df = df.sort_values('trade_date').reset_index(drop=True)
    df.to_csv(os.path.join(OUTPUT_DIR, '02_daily_basic.csv'), index=False)
    print(f'  -> {len(df)} 行')
    return df


def fetch_moneyflow(pro):
    print('[3/8] 资金流向 moneyflow ...')
    df = pro.moneyflow(ts_code=TS_CODE, start_date=START_DATE, end_date=END_DATE)
    df = df.sort_values('trade_date').reset_index(drop=True)
    df.to_csv(os.path.join(OUTPUT_DIR, '03_moneyflow.csv'), index=False)
    print(f'  -> {len(df)} 行')
    return df


def fetch_dragon_tiger(pro, trade_dates):
    print(f'[4/8] 龙虎榜 top_list (逐日扫描 {len(trade_dates)} 个交易日) ...')
    rows = []
    for d in trade_dates:
        df = safe_call(pro.top_list, 'top_list', trade_date=d, ts_code=TS_CODE)
        if not df.empty:
            rows.append(df)
    if rows:
        all_df = pd.concat(rows, ignore_index=True)
    else:
        all_df = pd.DataFrame()
    all_df.to_csv(os.path.join(OUTPUT_DIR, '04_top_list.csv'), index=False)
    print(f'  -> 上榜 {len(all_df)} 次')
    return all_df


def fetch_top_inst(pro, trade_dates_on_list):
    print(f'[5/8] 龙虎榜机构明细 top_inst ({len(trade_dates_on_list)} 个上榜日) ...')
    if not trade_dates_on_list:
        print('  -> 无上榜日，跳过')
        return pd.DataFrame()
    rows = []
    for d in trade_dates_on_list:
        df = safe_call(pro.top_inst, 'top_inst', trade_date=d, ts_code=TS_CODE)
        if not df.empty:
            rows.append(df)
    if rows:
        all_df = pd.concat(rows, ignore_index=True)
    else:
        all_df = pd.DataFrame()
    all_df.to_csv(os.path.join(OUTPUT_DIR, '05_top_inst.csv'), index=False)
    print(f'  -> {len(all_df)} 条机构席位记录')
    return all_df


def fetch_block_trade(pro):
    print('[6/8] 大宗交易 block_trade ...')
    df = pro.block_trade(ts_code=TS_CODE, start_date=START_DATE, end_date=END_DATE)
    if df is None:
        df = pd.DataFrame()
    df.to_csv(os.path.join(OUTPUT_DIR, '06_block_trade.csv'), index=False)
    print(f'  -> {len(df)} 笔')
    return df


def fetch_hk_hold(pro):
    print('[7/8] 北向资金持股 hk_hold ...')
    df = pro.hk_hold(ts_code=TS_CODE, start_date=START_DATE, end_date=END_DATE)
    if df is None:
        df = pd.DataFrame()
    df.to_csv(os.path.join(OUTPUT_DIR, '07_hk_hold.csv'), index=False)
    print(f'  -> {len(df)} 行 (科创板暂未纳入沪深港通时为空属正常)')
    return df


def fetch_shareholders(pro):
    print('[8/8] 股东数据 ...')
    holder_num = safe_call(pro.stk_holdernumber, 'stk_holdernumber',
                           ts_code=TS_CODE, start_date='20250101', end_date=END_DATE)
    holder_num.to_csv(os.path.join(OUTPUT_DIR, '08a_holder_number.csv'), index=False)
    print(f'  股东人数变化: {len(holder_num)} 期')

    top10 = safe_call(pro.top10_floatholders, 'top10_floatholders', ts_code=TS_CODE)
    if not top10.empty:
        top10['end_date'] = pd.to_datetime(top10['end_date'], format='%Y%m%d')
        recent_period = top10['end_date'].max()
        top10_recent = top10[top10['end_date'] == recent_period].sort_values('hold_ratio', ascending=False)
        top10_recent.to_csv(os.path.join(OUTPUT_DIR, '08b_top10_floatholders_latest.csv'), index=False)
        top10.to_csv(os.path.join(OUTPUT_DIR, '08c_top10_floatholders_history.csv'), index=False)
        print(f'  十大流通股东 (最新报告期 {recent_period.date()}): {len(top10_recent)} 位')
    else:
        top10_recent = pd.DataFrame()
        print('  十大流通股东: 无数据')

    holder_trade = safe_call(pro.stk_holdertrade, 'stk_holdertrade',
                             ts_code=TS_CODE, start_date='20250101', end_date=END_DATE)
    holder_trade.to_csv(os.path.join(OUTPUT_DIR, '08d_holder_trade.csv'), index=False)
    print(f'  股东增减持: {len(holder_trade)} 条')

    return holder_num, top10_recent, holder_trade


def classify_institution(name):
    """归类机构性质 - 操盘/量化/主力/普通"""
    if not isinstance(name, str):
        return '其他'
    if '机构专用' in name:
        return '机构席位 (公募/保险/资管)'
    if any(k in name for k in ['沪股通', '深股通', '港股通']):
        return '北向资金 (外资)'
    if any(k in name for k in ['总部', '本部', '机构客户部', '机构业务部']):
        return '券商机构客户部'
    if any(k in name for k in ['量化', '程序化', '高频']):
        return '量化席位'
    if any(k in name for k in ['证券', '营业部', '证券公司']):
        return '券商营业部 (游资/大户)'
    return '其他'


def classify_holder(name):
    """归类股东类型"""
    if not isinstance(name, str):
        return '其他'
    n = name
    if any(k in n for k in ['基金', 'ETF', '指数']):
        return '公募基金'
    if '社保' in n:
        return '社保基金'
    if any(k in n for k in ['保险', '人寿', '财产']):
        return '保险资金'
    if '证券' in n and '资管' in n:
        return '券商资管'
    if '资管' in n or '理财' in n:
        return '资管/理财'
    if any(k in n for k in ['QFII', 'RQFII', '香港中央', '中央结算']):
        return 'QFII/北向'
    if any(k in n for k in ['信托']):
        return '信托'
    if any(k in n for k in ['投资', '资本', '股权', '创投']):
        return '私募/产业资本'
    if any(k in n for k in ['有限公司', '股份有限公司', '集团']):
        return '产业资本/法人'
    if len(n) <= 4:
        return '个人股东'
    return '其他法人'


def aggregate_top_inst(top_inst):
    """按机构/营业部聚合龙虎榜数据"""
    if top_inst.empty:
        return pd.DataFrame()
    df = top_inst.copy()
    for col in ['buy', 'sell', 'buy_rate', 'sell_rate', 'net_buy']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    df['category'] = df['exalter'].apply(classify_institution)
    agg = df.groupby(['exalter', 'category']).agg(
        appearances=('trade_date', 'count'),
        total_buy=('buy', 'sum'),
        total_sell=('sell', 'sum'),
        total_net=('net_buy', 'sum'),
    ).reset_index()
    agg = agg.sort_values('total_net', ascending=False).reset_index(drop=True)
    agg['total_buy_万'] = (agg['total_buy'] / 10000).round(2)
    agg['total_sell_万'] = (agg['total_sell'] / 10000).round(2)
    agg['total_net_万'] = (agg['total_net'] / 10000).round(2)
    agg.to_csv(os.path.join(OUTPUT_DIR, '05b_inst_aggregated.csv'), index=False)
    return agg


def aggregate_moneyflow(mf):
    """资金流向汇总: 主力净流入 = 大单 + 超大单"""
    if mf.empty:
        return {}
    df = mf.copy()
    for c in df.columns:
        if c not in ('ts_code', 'trade_date'):
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    df['super_net_amount'] = df['buy_elg_amount'] - df['sell_elg_amount']
    df['big_net_amount'] = df['buy_lg_amount'] - df['sell_lg_amount']
    df['main_net_amount'] = df['super_net_amount'] + df['big_net_amount']
    df['mid_net_amount'] = df['buy_md_amount'] - df['sell_md_amount']
    df['small_net_amount'] = df['buy_sm_amount'] - df['sell_sm_amount']

    summary = {
        '总交易日': len(df),
        '超大单净流入合计_万': df['super_net_amount'].sum(),
        '大单净流入合计_万': df['big_net_amount'].sum(),
        '主力净流入合计_万': df['main_net_amount'].sum(),
        '中单净流入合计_万': df['mid_net_amount'].sum(),
        '小单净流入合计_万': df['small_net_amount'].sum(),
        '主力净流入日数': int((df['main_net_amount'] > 0).sum()),
        '主力净流出日数': int((df['main_net_amount'] < 0).sum()),
        '单日最大主力净流入_万': df['main_net_amount'].max(),
        '单日最大主力净流出_万': df['main_net_amount'].min(),
        '主力净流入最大日': df.loc[df['main_net_amount'].idxmax(), 'trade_date'] if df['main_net_amount'].max() > 0 else '-',
        '主力净流出最大日': df.loc[df['main_net_amount'].idxmin(), 'trade_date'] if df['main_net_amount'].min() < 0 else '-',
    }
    df.to_csv(os.path.join(OUTPUT_DIR, '03b_moneyflow_enriched.csv'), index=False)
    return summary, df


def fmt_money(v):
    """金额格式化 (万元)"""
    if pd.isna(v):
        return '-'
    if abs(v) >= 10000:
        return f'{v/10000:.2f}亿'
    return f'{v:.2f}万'


def fmt_pct(v):
    if pd.isna(v):
        return '-'
    return f'{v*100:.2f}%' if abs(v) < 1 else f'{v:.2f}%'


def main():
    pro = get_pro()
    print(f'\n{"="*60}')
    print(f'东芯股份 ({TS_CODE}) 主力机构/操盘公司深度挖掘')
    print(f'时间范围: {START_DATE} ~ {END_DATE}')
    print(f'输出目录: {OUTPUT_DIR}')
    print(f'{"="*60}\n')

    trade_dates = fetch_trade_calendar(pro, START_DATE, END_DATE)
    print(f'交易日: {len(trade_dates)} 天\n')

    daily = fetch_daily(pro)
    basic = fetch_daily_basic(pro)
    mf = fetch_moneyflow(pro)
    top_list = fetch_dragon_tiger(pro, trade_dates)

    inst_dates = sorted(top_list['trade_date'].unique().tolist()) if not top_list.empty else []
    top_inst = fetch_top_inst(pro, inst_dates)

    block = fetch_block_trade(pro)
    hk = fetch_hk_hold(pro)
    holder_num, top10, holder_trade = fetch_shareholders(pro)

    print('\n聚合分析...')
    mf_summary, mf_enriched = aggregate_moneyflow(mf)
    inst_agg = aggregate_top_inst(top_inst)

    # write context json
    ctx = {
        'ts_code': TS_CODE,
        'name': STOCK_NAME,
        'start': START_DATE,
        'end': END_DATE,
        'trade_days': len(trade_dates),
        'price_start': float(daily.iloc[0]['close']) if len(daily) else None,
        'price_end': float(daily.iloc[-1]['close']) if len(daily) else None,
        'pct_chg_total': float((daily.iloc[-1]['close'] / daily.iloc[0]['close'] - 1) * 100) if len(daily) > 1 else 0,
        'moneyflow_summary': {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in mf_summary.items()} if mf_summary else {},
        'top_list_count': len(top_list),
        'inst_records': len(top_inst),
        'block_trade_count': len(block),
        'hk_records': len(hk),
        'holder_num_periods': len(holder_num),
        'top10_holders_count': len(top10),
    }
    with open(os.path.join(OUTPUT_DIR, 'context.json'), 'w', encoding='utf-8') as f:
        json.dump(ctx, f, ensure_ascii=False, indent=2, default=str)

    print('\n数据采集完成. 关键数据预览:')
    print('-'*60)
    print(f'  日线: {len(daily)} 行, 价格 {ctx["price_start"]} -> {ctx["price_end"]} ({ctx["pct_chg_total"]:+.2f}%)')
    print(f'  资金流向: {len(mf)} 日')
    print(f'  龙虎榜上榜: {len(top_list)} 次')
    print(f'  龙虎榜席位记录: {len(top_inst)} 条')
    print(f'  大宗交易: {len(block)} 笔')
    print(f'  北向持股: {len(hk)} 条')
    print(f'  十大流通股东: {len(top10)} 位')
    print(f'  股东人数期: {len(holder_num)}')
    print('\nAll CSV files saved to:', OUTPUT_DIR)


if __name__ == '__main__':
    main()
