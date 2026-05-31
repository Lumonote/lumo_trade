"""生成东芯股份机构分析综合报告"""
import json
import os
import pandas as pd
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'results', 'dongxin_institution_analysis')


def fmt_amount(v):
    if pd.isna(v) or v == 0:
        return '-'
    v_yi = v / 1e8
    if abs(v_yi) >= 1:
        return f'{v_yi:+.2f}亿' if v != 0 else '-'
    return f'{v/1e4:+.2f}万'


def fmt_amount_unsigned(v):
    if pd.isna(v) or v == 0:
        return '-'
    v_yi = v / 1e8
    if abs(v_yi) >= 1:
        return f'{v_yi:.2f}亿'
    return f'{v/1e4:.2f}万'


def classify_inst(name):
    if not isinstance(name, str):
        return '其他'
    if '机构专用' in name:
        return '机构席位'
    if any(k in name for k in ['沪股通', '深股通']):
        return '北向资金'
    if any(k in name for k in ['高盛', '摩根大通', '瑞银', '摩根士丹利', '花旗', '汇丰', 'UBS', 'JP', '野村']):
        return '外资投行(量化系)'
    if '总部' in name or '机构客户' in name:
        return '券商机构客户部'
    if '分公司' in name and '营业部' not in name:
        return '券商分公司(机构通道)'
    if any(k in name for k in ['营业部']):
        return '券商营业部(游资/大户)'
    return '其他'


def main():
    with open(os.path.join(DATA_DIR, 'context.json'), 'r', encoding='utf-8') as f:
        ctx = json.load(f)

    daily = pd.read_csv(os.path.join(DATA_DIR, '01_daily.csv'))
    basic = pd.read_csv(os.path.join(DATA_DIR, '02_daily_basic.csv'))
    mf = pd.read_csv(os.path.join(DATA_DIR, '03b_moneyflow_enriched.csv'))
    top_list = pd.read_csv(os.path.join(DATA_DIR, '04_top_list.csv'))
    top_inst = pd.read_csv(os.path.join(DATA_DIR, '05_top_inst.csv'))
    inst_agg = pd.read_csv(os.path.join(DATA_DIR, '05b_inst_aggregated.csv'))
    block = pd.read_csv(os.path.join(DATA_DIR, '06_block_trade.csv'))
    top10 = pd.read_csv(os.path.join(DATA_DIR, '08b_top10_floatholders_latest.csv'))
    top10_hist = pd.read_csv(os.path.join(DATA_DIR, '08c_top10_floatholders_history.csv'))
    holder_num = pd.read_csv(os.path.join(DATA_DIR, '08a_holder_number.csv'))
    holder_trade = pd.read_csv(os.path.join(DATA_DIR, '08d_holder_trade.csv'))

    daily['trade_date'] = daily['trade_date'].astype(str)
    basic['trade_date'] = basic['trade_date'].astype(str)
    mf['trade_date'] = mf['trade_date'].astype(str)

    daily_full = daily.merge(basic[['trade_date', 'turnover_rate', 'turnover_rate_f', 'volume_ratio', 'pe', 'pb', 'total_mv', 'circ_mv']],
                              on='trade_date', how='left')

    # category for agg
    inst_agg['category_v2'] = inst_agg['exalter'].apply(classify_inst)

    # Group by category
    cat_summary = inst_agg.groupby('category_v2').agg(
        机构数=('exalter', 'nunique'),
        合计买入_元=('total_buy', 'sum'),
        合计卖出_元=('total_sell', 'sum'),
        合计净额_元=('total_net', 'sum'),
        累计上榜=('appearances', 'sum'),
    ).reset_index().sort_values('合计净额_元', ascending=False)

    # Build report
    lines = []
    L = lines.append
    today = datetime.now().strftime('%Y-%m-%d')

    L(f'# 东芯股份 (688110.SH) 主力机构/操盘公司深度挖掘报告')
    L('')
    L(f'> **分析时间**: {today}  ')
    L(f'> **数据周期**: {ctx["start"]} ~ {ctx["end"]} (近一个月, {ctx["trade_days"]} 个交易日)  ')
    L(f'> **数据来源**: Tushare Pro API (top_list / top_inst / moneyflow / block_trade / hk_hold / top10_floatholders)  ')
    L(f'> **公司属性**: 半导体行业 | 科创板 | 存储芯片设计')
    L('')
    L('---')
    L('')

    # ============== 1. 行情概览 ==============
    L('## 一、近一月行情概览')
    L('')
    first = daily_full.iloc[0]
    last = daily_full.iloc[-1]
    max_high = daily_full['high'].max()
    min_low = daily_full['low'].min()
    avg_turnover = daily_full['turnover_rate'].mean()
    total_amount = daily_full['amount'].sum()

    L('| 指标 | 数值 |')
    L('|------|------|')
    L(f'| 期初收盘 ({first["trade_date"]}) | {first["close"]:.2f} 元 |')
    L(f'| 期末收盘 ({last["trade_date"]}) | {last["close"]:.2f} 元 |')
    L(f'| 区间涨跌幅 | **{ctx["pct_chg_total"]:+.2f}%** |')
    L(f'| 区间最高价 | {max_high:.2f} 元 |')
    L(f'| 区间最低价 | {min_low:.2f} 元 |')
    L(f'| 振幅 | {(max_high/min_low-1)*100:.2f}% |')
    # Tushare daily.amount 单位为千元 -> 除以1e5 得亿元
    L(f'| 区间累计成交额 | {total_amount/1e5:.2f} 亿元 |')
    L(f'| 平均日换手率 | {avg_turnover:.2f}% |')
    L(f'| 期末总市值 | {last["total_mv"]/10000:.2f} 亿元 |')
    L(f'| 期末流通市值 | {last["circ_mv"]/10000:.2f} 亿元 |')
    L(f'| 期末市盈率 (PE) | {last["pe"] if pd.notna(last["pe"]) and last["pe"]>0 else "亏损/N/A"} |')
    L(f'| 期末市净率 (PB) | {last["pb"]:.2f} |')
    L('')

    L('### 1.1 日线行情明细')
    L('')
    L('| 日期 | 开盘 | 最高 | 最低 | 收盘 | 涨跌幅 | 成交量(万手) | 成交额(亿元) | 换手率% |')
    L('|------|------|------|------|------|--------|--------------|--------------|---------|')
    for _, r in daily_full.iterrows():
        L(f'| {r["trade_date"]} | {r["open"]:.2f} | {r["high"]:.2f} | {r["low"]:.2f} | {r["close"]:.2f} | '
          f'{r["pct_chg"]:+.2f}% | {r["vol"]/10000:.2f} | {r["amount"]/1e5:.2f} | {r.get("turnover_rate", 0):.2f} |')
    L('')

    # ============== 2. 龙虎榜上榜情况 ==============
    L('## 二、龙虎榜上榜情况')
    L('')
    L(f'**近一个月共上榜 {len(top_list)} 次**')
    L('')
    if not top_list.empty:
        L('| 日期 | 收盘 | 涨跌幅 | 换手率 | 成交额(亿) | 上榜成交额(亿) | 上榜净额(亿) | 上榜原因 |')
        L('|------|------|--------|--------|------------|----------------|--------------|----------|')
        for _, r in top_list.iterrows():
            L(f'| {r["trade_date"]} | {r["close"]:.2f} | {r["pct_change"]:+.2f}% | {r["turnover_rate"]:.2f}% | '
              f'{r["amount"]/1e8:.2f} | {r["l_amount"]/1e8:.2f} | {r["net_amount"]/1e8:+.2f} | {r["reason"]} |')
    L('')

    # ============== 3. 操盘券商/机构席位深度分析 ==============
    L('## 三、操盘券商/机构席位深度分析 (核心)')
    L('')
    L('### 3.1 按机构性质分类汇总')
    L('')
    L('| 机构性质 | 涉及机构数 | 累计上榜次数 | 合计买入 | 合计卖出 | **净额** |')
    L('|----------|------------|--------------|----------|----------|---------|')
    for _, r in cat_summary.iterrows():
        L(f'| **{r["category_v2"]}** | {int(r["机构数"])} 家 | {int(r["累计上榜"])} 次 | '
          f'{fmt_amount_unsigned(r["合计买入_元"])} | {fmt_amount_unsigned(r["合计卖出_元"])} | '
          f'**{fmt_amount(r["合计净额_元"])}** |')
    L('')

    L('### 3.2 全部上榜机构席位明细 (按净买入排序)')
    L('')
    L('| 排名 | 操盘机构/营业部 | 性质 | 上榜次数 | 累计买入 | 累计卖出 | **累计净额** |')
    L('|------|-----------------|------|----------|----------|----------|--------------|')
    for i, r in inst_agg.iterrows():
        L(f'| {i+1} | {r["exalter"]} | {r["category_v2"]} | {int(r["appearances"])} | '
          f'{fmt_amount_unsigned(r["total_buy"])} | {fmt_amount_unsigned(r["total_sell"])} | '
          f'**{fmt_amount(r["total_net"])}** |')
    L('')

    L('### 3.3 逐次上榜席位明细')
    L('')
    for trade_date in sorted(top_inst['trade_date'].unique()):
        day_inst = top_inst[top_inst['trade_date'] == trade_date]
        day_top = top_list[top_list['trade_date'].astype(str) == str(trade_date)]
        if not day_top.empty:
            reason = day_top.iloc[0]['reason']
            pct = day_top.iloc[0]['pct_change']
            L(f'#### 📅 {trade_date}  涨跌幅 **{pct:+.2f}%** — {reason}')
        else:
            L(f'#### 📅 {trade_date}')
        L('')

        buy_side = day_inst[day_inst['side'] == 0].sort_values('buy', ascending=False)
        sell_side = day_inst[day_inst['side'] == 1].sort_values('sell', ascending=False)

        L('**🟢 买入席位 Top 5:**')
        L('')
        L('| 营业部/席位 | 性质 | 买入金额 | 占成交比% |')
        L('|-------------|------|----------|-----------|')
        for _, r in buy_side.iterrows():
            cat = classify_inst(r['exalter'])
            L(f'| {r["exalter"]} | {cat} | {r["buy"]/1e8:.4f}亿 | {r["buy_rate"]:.2f}% |')
        L('')

        L('**🔴 卖出席位 Top 5:**')
        L('')
        L('| 营业部/席位 | 性质 | 卖出金额 | 占成交比% |')
        L('|-------------|------|----------|-----------|')
        for _, r in sell_side.iterrows():
            cat = classify_inst(r['exalter'])
            L(f'| {r["exalter"]} | {cat} | {r["sell"]/1e8:.4f}亿 | {r["sell_rate"]:.2f}% |')
        L('')

    # ============== 4. 量化席位识别 ==============
    L('## 四、量化资金/外资量化席位识别')
    L('')
    L('> **识别逻辑**: 外资投行系列(高盛/摩根大通/瑞银等)在中国 A 股是程序化交易+量化基金的主要通道；')
    L('> 多次双向高频出现且净额接近零的席位 = 典型量化对冲行为；')
    L('> 申万宏源海宁路、中信上海等知名活跃营业部 = 游资席位。')
    L('')
    quant_inst = inst_agg[inst_agg['category_v2'].isin(['外资投行(量化系)'])]
    if not quant_inst.empty:
        L('### 4.1 外资量化机构席位')
        L('')
        L('| 量化机构 | 上榜次数 | 双向操作特征 | 累计买入 | 累计卖出 | 净额 | 量化特征评分 |')
        L('|----------|----------|--------------|----------|----------|------|---------------|')
        for _, r in quant_inst.iterrows():
            buy = r['total_buy']
            sell = r['total_sell']
            if buy + sell > 0:
                hedge_ratio = min(buy, sell) / max(buy, sell, 1) * 100
            else:
                hedge_ratio = 0
            if hedge_ratio > 80:
                feature = '⭐⭐⭐⭐⭐ 极强对冲'
            elif hedge_ratio > 50:
                feature = '⭐⭐⭐⭐ 强对冲'
            elif hedge_ratio > 20:
                feature = '⭐⭐⭐ 中等对冲'
            else:
                feature = '⭐⭐ 单边为主'
            two_way = '双向' if buy > 0 and sell > 0 else ('单边买入' if buy > 0 else '单边卖出')
            L(f'| {r["exalter"]} | {int(r["appearances"])} | {two_way} (对冲率{hedge_ratio:.1f}%) | '
              f'{fmt_amount_unsigned(buy)} | {fmt_amount_unsigned(sell)} | {fmt_amount(r["total_net"])} | {feature} |')
        L('')

    L('### 4.2 量化资金分析结论')
    L('')
    L('- **高盛(中国)证券浦东**: 4次上榜(2买2卖),累计买入3.21亿、卖出2.14亿、净额+1.07亿 → 典型外资量化席位,)'
      '在2026-05-21暴跌日和05-25暴涨日均同时双向操作,符合量化高频对冲特征。')
    L('- **瑞银证券花园石桥路**: 4次上榜(2买2卖),累计买卖均约2.85亿,净额近乎为零 → **极强对冲特征**,几乎可')
    L('  确认为程序化双边做市/统计套利策略席位。')
    L('- **摩根大通(中国)上海银城中路**: 1次单边大幅买入1.20亿 → 可能为外资基金/QFII单向建仓,而非高频量化。')
    L('- **国泰海通总部**: 4次上榜(2买2卖),净流入1.76亿 → 机构客户部(公募/私募/保险通道),主要承载机构')
    L('  投资人指令,买入意愿明显大于卖出。')
    L('')

    # ============== 5. 主力机构/北向 ==============
    L('## 五、主力机构与北向资金动向')
    L('')
    L('### 5.1 北向资金(沪股通)操作')
    L('')
    L('| 日期 | 方向 | 金额 | 占当日成交比% |')
    L('|------|------|------|---------------|')
    hk_lines = top_inst[top_inst['exalter'] == '沪股通专用']
    for _, r in hk_lines.iterrows():
        direction = '🟢 买入' if r['side'] == 0 else '🔴 卖出'
        amt = r['buy'] if r['side'] == 0 else r['sell']
        rate = r['buy_rate'] if r['side'] == 0 else r['sell_rate']
        L(f'| {r["trade_date"]} | {direction} | {amt/1e8:.4f}亿 | {rate:.2f}% |')
    hk_net = hk_lines.apply(lambda x: x['buy'] if x['side'] == 0 else -x['sell'], axis=1).sum()
    L(f'| **合计** | **净额** | **{hk_net/1e8:+.4f}亿** | - |')
    L('')

    L('### 5.2 机构客户部(主力机构通道)')
    L('')
    L('国泰海通证券总部是公募基金、保险资管、私募基金等机构投资者的常用通道，其上榜行为通常代表机构操盘动向:')
    L('')
    L('| 日期 | 国泰海通总部操作 | 金额 | 占成交比% |')
    L('|------|-------------------|------|-----------|')
    gth = top_inst[top_inst['exalter'] == '国泰海通证券股份有限公司总部']
    for _, r in gth.iterrows():
        direction = '🟢 买入' if r['side'] == 0 else '🔴 卖出'
        amt = r['buy'] if r['side'] == 0 else r['sell']
        rate = r['buy_rate'] if r['side'] == 0 else r['sell_rate']
        L(f'| {r["trade_date"]} | {direction} | {amt/1e8:.4f}亿 | {rate:.2f}% |')
    L('')

    # ============== 6. 大宗交易 ==============
    L('## 六、大宗交易明细 (机构对敲)')
    L('')
    if not block.empty:
        L('| 日期 | 价格 | 数量(万股) | 金额(万元) | 买方营业部 | 卖方营业部 | 折溢价 |')
        L('|------|------|------------|------------|------------|------------|--------|')
        for _, r in block.iterrows():
            close_price = daily[daily['trade_date'] == str(r['trade_date'])]
            if not close_price.empty:
                cp = close_price.iloc[0]['close']
                disc = (r['price'] / cp - 1) * 100
                disc_str = f'{disc:+.2f}%'
            else:
                disc_str = '-'
            L(f'| {r["trade_date"]} | {r["price"]:.2f} | {r["vol"]:.2f} | {r["amount"]:.2f} | '
              f'{r["buyer"]} | {r["seller"]} | {disc_str} |')
    else:
        L('近一月无大宗交易')
    L('')

    # ============== 7. 资金流向 ==============
    L('## 七、主力资金流向分析 (按单子规模)')
    L('')
    L('> **口径说明**: 超大单 = 单笔成交额 ≥ 100万；大单 = 20-100万；中单 = 4-20万；小单 = < 4万；')
    L('> 主力净流入 = 超大单 + 大单净流入。')
    L('')

    super_sum = mf['super_net_amount'].sum()
    big_sum = mf['big_net_amount'].sum()
    main_sum = mf['main_net_amount'].sum()
    mid_sum = mf['mid_net_amount'].sum()
    small_sum = mf['small_net_amount'].sum()

    L('### 7.1 资金流向汇总(单位:万元)')
    L('')
    L('| 资金类别 | 累计净额(万元) | 累计净额(亿元) | 净流入日数 | 净流出日数 |')
    L('|----------|---------------:|---------------:|------------|------------|')
    for label, col, total in [
        ('🔥 超大单(主力1)', 'super_net_amount', super_sum),
        ('🔥 大单(主力2)', 'big_net_amount', big_sum),
        ('💪 主力合计(超大+大)', 'main_net_amount', main_sum),
        ('🪙 中单(中户)', 'mid_net_amount', mid_sum),
        ('🐜 小单(散户)', 'small_net_amount', small_sum),
    ]:
        in_days = int((mf[col] > 0).sum())
        out_days = int((mf[col] < 0).sum())
        L(f'| {label} | {total:+,.2f} | {total/1e4:+.4f} | {in_days} 日 | {out_days} 日 |')
    L('')

    L('### 7.2 单日主力资金流向明细(万元)')
    L('')
    L('| 日期 | 收盘 | 涨跌幅 | 超大单净额 | 大单净额 | 主力净额 | 中单净额 | 小单净额 |')
    L('|------|------|--------|-----------|---------|---------|---------|---------|')
    for _, r in mf.iterrows():
        d = daily[daily['trade_date'] == r['trade_date']]
        close = d.iloc[0]['close'] if not d.empty else 0
        pct = d.iloc[0]['pct_chg'] if not d.empty else 0
        emoji = '🔼' if r['main_net_amount'] > 0 else '🔽'
        L(f'| {r["trade_date"]} | {close:.2f} | {pct:+.2f}% | {r["super_net_amount"]:+,.0f} | '
          f'{r["big_net_amount"]:+,.0f} | {emoji} **{r["main_net_amount"]:+,.0f}** | '
          f'{r["mid_net_amount"]:+,.0f} | {r["small_net_amount"]:+,.0f} |')
    L('')

    # ============== 8. 十大流通股东 ==============
    L('## 八、最新十大流通股东构成')
    L('')
    if not top10.empty:
        L(f'**报告期: {top10.iloc[0]["end_date"][:10]}**')
        L('')
        L('| 排名 | 股东名称 | 股东类型 | 持股数(股) | 占流通股% | 较上期变动(股) |')
        L('|------|----------|----------|------------|-----------|----------------|')
        type_map = {
            '东方恒信集团有限公司': '产业资本(实控人)',
            '苏州东芯科创股权投资合伙企业(有限合伙)': '早期投资/员工持股',
            '中信证券股份有限公司-嘉实上证科创板芯片交易型开放式指数证券投资基金': '公募ETF(芯片主题)',
            '香港中央结算有限公司': '北向资金/QFII',
            '泽丰瑞熙私募证券基金管理(广东)有限公司-泽丰春华秋实4号私募证券投资基金': '私募基金',
            '财通基金-亨通集团有限公司-财通基金玉泉1886号单一资产管理计划': '公募专户(单一)',
            '广发证券股份有限公司-鹏华上证科创板100交易型开放式指数证券投资基金': '公募ETF(科创100)',
        }
        for i, r in top10.iterrows():
            stype = type_map.get(r['holder_name'], '个人投资者' if len(r['holder_name']) <= 4 else '其他法人')
            change = r['hold_change']
            change_str = f'{change:+,.0f}' if pd.notna(change) and change != 0 else ('-' if pd.isna(change) else '0')
            L(f'| {i+1} | {r["holder_name"]} | {stype} | {r["hold_amount"]:,.0f} | {r["hold_ratio"]:.4f}% | {change_str} |')
        L('')

    # Trend of top10 holders across periods
    if not top10_hist.empty:
        L('### 8.1 历史十大流通股东持股变化趋势')
        L('')
        top10_hist['end_date'] = pd.to_datetime(top10_hist['end_date'])
        recent_periods = sorted(top10_hist['end_date'].unique())[-4:]
        names_recent = top10_hist[top10_hist['end_date'].isin(recent_periods)]['holder_name'].unique()
        # find names appearing in most recent period
        latest_names = top10_hist[top10_hist['end_date'] == recent_periods[-1]]['holder_name'].unique()
        L('| 股东 | ' + ' | '.join([d.strftime('%Y-%m-%d') for d in recent_periods]) + ' |')
        L('|------|' + '|'.join([' --- ' for _ in recent_periods]) + '|')
        for name in latest_names[:10]:
            row = [name[:25]]
            for d in recent_periods:
                rec = top10_hist[(top10_hist['holder_name'] == name) & (top10_hist['end_date'] == d)]
                if not rec.empty:
                    row.append(f'{rec.iloc[0]["hold_amount"]/10000:.1f}万股({rec.iloc[0]["hold_ratio"]:.2f}%)')
                else:
                    row.append('-')
            L('| ' + ' | '.join(row) + ' |')
        L('')

    # ============== 9. 股东人数 ==============
    L('## 九、股东人数变化趋势 (筹码集中度)')
    L('')
    holder_num_unique = holder_num.drop_duplicates(subset='end_date').sort_values('end_date')
    L('| 报告期 | 股东户数 | 较上期变化 | 集中度判断 |')
    L('|--------|----------|------------|------------|')
    prev_num = None
    for _, r in holder_num_unique.iterrows():
        n = r['holder_num']
        if prev_num is not None:
            change = n - prev_num
            change_pct = change / prev_num * 100
            if change_pct > 20:
                judge = '🔴 严重分散(筹码涣散)'
            elif change_pct > 5:
                judge = '🟡 适度分散'
            elif change_pct < -5:
                judge = '🟢 显著集中(机构吸筹)'
            else:
                judge = '⚪ 基本稳定'
            change_str = f'{change:+,.0f} ({change_pct:+.1f}%)'
        else:
            judge = '基期'
            change_str = '-'
        L(f'| {r["end_date"]} | {n:,.0f} | {change_str} | {judge} |')
        prev_num = n
    L('')

    # ============== 10. 大股东增减持 ==============
    L('## 十、大股东(产业资本)增减持记录')
    L('')
    if not holder_trade.empty:
        L('| 公告日 | 股东 | 类型 | 方向 | 变动股数 | 变动比例 | 变动后持股 | 变动后占比 | 均价 |')
        L('|--------|------|------|------|----------|----------|-------------|-------------|------|')
        type_map_full = {'C': '法人股东', 'P': '个人股东', 'G': '高管'}
        dir_map = {'IN': '🟢 增持', 'DE': '🔴 减持'}
        for _, r in holder_trade.iterrows():
            stype = type_map_full.get(r['holder_type'], r['holder_type'])
            direction = dir_map.get(r['in_de'], r['in_de'])
            after_share = f'{r["after_share"]:,.0f}' if pd.notna(r['after_share']) else '-'
            after_ratio = f'{r["after_ratio"]:.4f}%' if pd.notna(r['after_ratio']) else '-'
            avg_price = f'{r["avg_price"]:.2f}' if pd.notna(r['avg_price']) else '-'
            L(f'| {r["ann_date"]} | {r["holder_name"]} | {stype} | {direction} | '
              f'{r["change_vol"]:,.0f} | {r["change_ratio"]:.4f}% | {after_share} | {after_ratio} | {avg_price} |')
    L('')

    # ============== 11. 综合结论 ==============
    L('## 十一、综合结论与操盘画像')
    L('')

    # Compute summary metrics
    total_quant_appearances = inst_agg[inst_agg['category_v2'] == '外资投行(量化系)']['appearances'].sum()
    quant_buy = inst_agg[inst_agg['category_v2'] == '外资投行(量化系)']['total_buy'].sum()
    quant_sell = inst_agg[inst_agg['category_v2'] == '外资投行(量化系)']['total_sell'].sum()

    L('### 11.1 关键事实摘要')
    L('')
    L(f'1. **价格表现**: 区间涨幅 **{ctx["pct_chg_total"]:+.2f}%**, 振幅 {(max_high/min_low-1)*100:.2f}%, 在 5/21 暴跌15.81% 后于 5/25 暴涨20.00%, 波动剧烈。')
    L(f'2. **主力资金**: 累计净流出 **{main_sum/1e4:.2f}亿元** ({int((mf["main_net_amount"]>0).sum())}日净流入 / {int((mf["main_net_amount"]<0).sum())}日净流出), 主力席位以分批兑现为主。')
    L(f'3. **龙虎榜**: 近一月上榜 **{len(top_list)} 次**, 共涉及 **{inst_agg["exalter"].nunique()} 个机构席位**。')
    L(f'4. **外资量化**: 高盛/瑞银/摩根大通三大外资席位累计上榜 **{int(total_quant_appearances)} 次**, 买入 {quant_buy/1e8:.2f}亿、卖出 {quant_sell/1e8:.2f}亿。')
    L(f'5. **北向资金**: 沪股通累计净 **{hk_net/1e8:+.2f}亿** (5/21日大幅卖出2.34亿)。')
    L(f'6. **机构主力**: 国泰海通总部累计净买入 **+1.76亿元**, 是本月最强机构买入通道。')
    L(f'7. **筹码结构**: 股东户数从 2025Q1 的 2.04万户 → 2026Q1 的 4.88万户 (**+139%**), 筹码大幅分散, 散户化加剧。')
    L(f'8. **实控人**: 东方恒信集团 2025-08-28 减持 8411537 股(约1.90%), 持股降至 32.38%, 后稳定在 30.88%。')
    L('')

    L('### 11.2 操盘公司画像')
    L('')
    L('| 操盘类型 | 代表机构 | 操盘特征 | 持仓属性 |')
    L('|----------|----------|----------|----------|')
    L('| **机构主力买方** | 国泰海通总部 | 4次上榜净买入1.76亿, 是机构客户主要通道 | 公募/保险/私募指令通道 |')
    L('| **外资量化对冲** | 瑞银证券花园石桥路 | 4次上榜买卖几乎相等(净额-1.8万元) | 极强对冲, 程序化做市 |')
    L('| **外资量化高频** | 高盛中国浦东 | 4次上榜双向操作, 净+1.07亿 | 统计套利+方向性头寸 |')
    L('| **外资单边建仓** | 摩根大通中国 | 1次单边买入1.20亿 | QFII/外资公募单向建仓 |')
    L('| **北向资金** | 沪股通专用 | 2次出现, 净卖出2.34亿 | 外资战略性减仓 |')
    L('| **知名游资** | 申万宏源海宁路 | 1次卖出0.92亿 | 短线游资兑现 |')
    L('| **券商机构客户** | 中信上海分公司 | 3次上榜净额仅+0.10亿 | 机构客户分散指令 |')
    L('')

    L('### 11.3 主力机构席位 vs 量化席位识别表')
    L('')
    L('```')
    L('量化席位识别度评分(基于对冲率):')
    for _, r in inst_agg.iterrows():
        buy = r['total_buy']
        sell = r['total_sell']
        if buy + sell > 0:
            hedge_ratio = min(buy, sell) / max(buy, sell, 1) * 100
        else:
            hedge_ratio = 0
        bar = '█' * int(hedge_ratio / 10)
        L(f'  {r["exalter"][:30]:30s} | 对冲率 {hedge_ratio:5.1f}% | {bar}')
    L('```')
    L('')
    L('> **解读**: 对冲率 > 80% 强烈暗示量化双边做市/统计套利; 20-50% 通常是机构基于风控的部分对冲;')
    L('> < 20% 则为单边建仓/兑现行为。')
    L('')

    L('### 11.4 投资参考结论')
    L('')
    L('**短期(1-2周)**:')
    L('- 5/21 跌停日北向资金大幅净卖出 2.34亿, 提示外资策略性减仓信号;')
    L('- 5/25 涨停日国泰海通总部单日买入 2.49亿, 机构资金抄底动作明显;')
    L('- 主力资金近一月累计净流出 23亿元, 整体筹码处于派发末期。')
    L('')
    L('**中期(1-3月)**:')
    L('- 股东户数从 1.9万 → 5.1万 (Q2→Q3 2025) 是去年大涨后的散户接盘高峰, 这部分浮筹是后续上行的最大阻力;')
    L('- 大股东东方恒信2025-08已减持1.9%, 后续若继续减持需警惕(目前持股30.88%);')
    L('- 北向资金通过香港中央结算稳定增持(2026Q1+318万股), 与沪股通单日大额卖出形成对比,显示外资内部分化。')
    L('')
    L('**操盘特征**:')
    L('- 该股是典型的"外资量化高度参与+机构资金间歇性介入"的标的, 单日波动主要由外资量化高频对冲驱动;')
    L('- 公募基金持仓集中于科创板芯片ETF(嘉实/鹏华)被动通道, 主动机构进入较少;')
    L('- 主力席位偏好"短期波段"操作, 长期持仓机构较少 → 适合波段策略, 不适合长线持有。')
    L('')

    L('---')
    L('')
    L('## 附录: 原始数据文件清单')
    L('')
    L('全部明细 CSV 已保存到 `results/dongxin_institution_analysis/`:')
    L('')
    L('| 文件 | 内容 | 行数 |')
    L('|------|------|------|')
    files_info = [
        ('01_daily.csv', '日线行情数据', len(daily)),
        ('02_daily_basic.csv', '每日基本面指标(换手率/市值/PE/PB)', len(basic)),
        ('03_moneyflow.csv', '原始资金流向', len(mf)),
        ('03b_moneyflow_enriched.csv', '资金流向(含计算字段:主力净额等)', len(mf)),
        ('04_top_list.csv', '龙虎榜上榜记录', len(top_list)),
        ('05_top_inst.csv', '龙虎榜全部席位明细', len(top_inst)),
        ('05b_inst_aggregated.csv', '机构席位聚合(按净买入排序)', len(inst_agg)),
        ('06_block_trade.csv', '大宗交易记录', len(block)),
        ('07_hk_hold.csv', '北向资金持股(科创板沪股通已纳入)', '0'),
        ('08a_holder_number.csv', '股东人数历史数据', len(holder_num)),
        ('08b_top10_floatholders_latest.csv', '最新十大流通股东', len(top10)),
        ('08c_top10_floatholders_history.csv', '历史十大流通股东', len(top10_hist)),
        ('08d_holder_trade.csv', '大股东增减持记录', len(holder_trade)),
        ('context.json', '分析上下文/汇总指标', '-'),
    ]
    for fn, desc, n in files_info:
        L(f'| `{fn}` | {desc} | {n} |')
    L('')
    L(f'**报告生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  ')
    L(f'**数据源**: Tushare Pro API  ')
    L(f'**生成工具**: `scripts/analyze_dongxin_institutions.py` + `scripts/generate_dongxin_report.py`')

    report_path = os.path.join(DATA_DIR, '东芯股份_主力机构操盘公司深度分析报告.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f'\n✓ 报告已生成: {report_path}')
    print(f'  报告长度: {len(lines)} 行')
    print(f'  报告字数: {sum(len(l) for l in lines)} 字符')


if __name__ == '__main__':
    main()
