"""生成瑞银证券花园石桥路营业部近一个月交易报告"""
import pandas as pd
import os
from datetime import datetime

DATA_DIR = 'results/dongxin_institution_analysis'

agg = pd.read_csv(f'{DATA_DIR}/ubs_garden_stone_by_stock.csv')
df = pd.read_csv(f'{DATA_DIR}/ubs_garden_stone_trades_with_names.csv')

lines = []
L = lines.append

today = datetime.now().strftime('%Y-%m-%d')

L('# 瑞银证券(花园石桥路)营业部近一个月交易股票全图谱')
L('')
L(f'> **席位**: 瑞银证券有限责任公司上海花园石桥路证券营业部  ')
L(f'> **数据周期**: 2026-04-27 ~ 2026-05-27 (近一个月, 19个交易日)  ')
L(f'> **数据来源**: Tushare Pro API (top_inst)  ')
L(f'> **分析时间**: {today}')
L('')
L('---')
L('')

# Summary
L('## 一、汇总指标')
L('')
total_records = len(df)
total_stocks = df['ts_code'].nunique()
total_buy = df['buy'].sum()
total_sell = df['sell'].sum()
total_net = df['net_buy'].sum()
days_with_activity = df['trade_date'].nunique()

L('| 指标 | 数值 |')
L('|------|------|')
L(f'| 交易股票总数 | **{total_stocks}** 只 |')
L(f'| 累计上榜记录 | **{total_records}** 条 |')
L(f'| 有交易记录的交易日 | {days_with_activity} 天 / 19 |')
L(f'| 累计买入金额 | **{total_buy/1e8:.2f}** 亿元 |')
L(f'| 累计卖出金额 | **{total_sell/1e8:.2f}** 亿元 |')
L(f'| 累计净额 | **{total_net/1e8:+.2f}** 亿元 |')
L(f'| 日均交易股票数 | {total_records/days_with_activity:.1f} 只 |')
L(f'| 上榜≥3次的股票 | {len(agg[agg["appearances"]>=3])} 只 (高频跟踪) |')
L(f'| 上榜≥5次的股票 | {len(agg[agg["appearances"]>=5])} 只 (重点跟踪) |')

# 单日双向操作
day_stock = df.groupby(['trade_date', 'ts_code'])['side'].nunique().reset_index()
both_sides = day_stock[day_stock['side'] == 2]
L(f'| 单日双向操作记录 | **{len(both_sides)}** 次 (量化对冲特征) |')
L('')

L('> **关键特征**: 单日交易超过10只股票, 单日双向操作 72次, 显示典型的量化高频/统计套利策略。')
L('')

# 行业分布
L('## 二、行业分布 (Top 15)')
L('')
ind = df.groupby('industry').agg(
    records=('trade_date', 'count'),
    stocks=('ts_code', 'nunique'),
    buy=('buy', 'sum'),
    sell=('sell', 'sum'),
    net=('net_buy', 'sum'),
).reset_index().sort_values('records', ascending=False).head(15)

L('| 行业 | 涉及股票 | 上榜次数 | 累计买入(万) | 累计卖出(万) | 净额(万) |')
L('|------|----------|----------|--------------|--------------|---------:|')
for _, r in ind.iterrows():
    L(f'| {r["industry"]} | {int(r["stocks"])} | {int(r["records"])} | '
      f'{r["buy"]/1e4:,.1f} | {r["sell"]/1e4:,.1f} | {r["net"]/1e4:+,.1f} |')
L('')
L('> **重仓赛道**: 半导体 + 元器件 合计 37 只股票, 89 条记录, 占总记录 24%, 显示对硬科技板块的高度专注。')
L('')

# 市场分布
L('## 三、市场板块分布')
L('')
mkt = df.groupby('market').agg(
    records=('trade_date', 'count'),
    stocks=('ts_code', 'nunique'),
).reset_index().sort_values('records', ascending=False)
L('| 板块 | 涉及股票 | 上榜次数 |')
L('|------|----------|----------|')
for _, r in mkt.iterrows():
    L(f'| {r["market"]} | {int(r["stocks"])} | {int(r["records"])} |')
L('')

# 高频股票
L('## 四、高频上榜股票 (≥3次, 重点跟踪标的)')
L('')
high_freq = agg[agg['appearances'] >= 3].sort_values('appearances', ascending=False).reset_index(drop=True)
L(f'**共 {len(high_freq)} 只股票被瑞银花园石桥路反复操作**')
L('')
L('| # | 代码 | 名称 | 行业 | 上榜次数 | 累计买入(万) | 累计卖出(万) | **净额(万)** | 对冲率% | 首次 | 末次 |')
L('|---|------|------|------|---------:|-------------:|-------------:|-------------:|--------:|------|------|')
for i, r in high_freq.iterrows():
    L(f'| {i+1} | {r["ts_code"]} | **{r["name"]}** | {r["industry"]} | {int(r["appearances"])} | '
      f'{r["total_buy_万"]:,.1f} | {r["total_sell_万"]:,.1f} | **{r["total_net_万"]:+,.1f}** | '
      f'{r["hedge_ratio"]:.1f}% | {r["first_date"]} | {r["last_date"]} |')
L('')

# 经典量化对冲案例
L('## 五、经典量化对冲案例 (≥3次 且 对冲率≥70%)')
L('')
L('> **筛选逻辑**: 反复操作(≥3次)且买卖几乎相等(对冲率≥70%)的股票, 是程序化双边做市/统计套利策略的典型标的。')
L('')
quant = agg[(agg['appearances'] >= 3) & (agg['hedge_ratio'] >= 70)].sort_values(['appearances', 'hedge_ratio'], ascending=[False, False]).reset_index(drop=True)
L(f'**共 {len(quant)} 只股票符合量化对冲特征**')
L('')
L('| # | 代码 | 名称 | 行业 | 上榜次数 | 累计买入(万) | 累计卖出(万) | **净额(万)** | 对冲率% |')
L('|---|------|------|------|---------:|-------------:|-------------:|-------------:|--------:|')
for i, r in quant.iterrows():
    L(f'| {i+1} | {r["ts_code"]} | **{r["name"]}** | {r["industry"]} | {int(r["appearances"])} | '
      f'{r["total_buy_万"]:,.1f} | {r["total_sell_万"]:,.1f} | **{r["total_net_万"]:+,.1f}** | '
      f'{r["hedge_ratio"]:.1f}% |')
L('')

# Top 净买入
L('## 六、Top 20 净买入股票')
L('')
top_buy = agg.sort_values('total_net', ascending=False).head(20).reset_index(drop=True)
L('| # | 代码 | 名称 | 行业 | 上榜 | 买入(万) | 卖出(万) | **净额(万)** | 对冲率% |')
L('|---|------|------|------|-----:|---------:|---------:|-------------:|--------:|')
for i, r in top_buy.iterrows():
    L(f'| {i+1} | {r["ts_code"]} | **{r["name"]}** | {r["industry"]} | {int(r["appearances"])} | '
      f'{r["total_buy_万"]:,.1f} | {r["total_sell_万"]:,.1f} | **{r["total_net_万"]:+,.1f}** | {r["hedge_ratio"]:.1f}% |')
L('')

# Top 净卖出
L('## 七、Top 20 净卖出股票')
L('')
top_sell = agg.sort_values('total_net', ascending=True).head(20).reset_index(drop=True)
L('| # | 代码 | 名称 | 行业 | 上榜 | 买入(万) | 卖出(万) | **净额(万)** | 对冲率% |')
L('|---|------|------|------|-----:|---------:|---------:|-------------:|--------:|')
for i, r in top_sell.iterrows():
    L(f'| {i+1} | {r["ts_code"]} | **{r["name"]}** | {r["industry"]} | {int(r["appearances"])} | '
      f'{r["total_buy_万"]:,.1f} | {r["total_sell_万"]:,.1f} | **{r["total_net_万"]:+,.1f}** | {r["hedge_ratio"]:.1f}% |')
L('')

# 操盘画像
L('## 八、操盘画像与策略推断')
L('')
L('### 8.1 席位特征')
L('')
L(f'- **交易广度**: 19 个交易日覆盖 **{total_stocks} 只股票**, 平均每日交易 **{total_records/days_with_activity:.1f} 只**, 远超普通游资席位 → **量化策略特征**')
L(f'- **双向操作**: 单日双向操作 **{len(both_sides)} 次**, 占总记录 **{len(both_sides)/total_records*100:.1f}%** → **对冲/套利特征**')
L(f'- **总净额**: 累计净额 **{total_net/1e8:+.2f}亿元** (买卖近乎平衡) → 非方向性策略, 倾向于做市/统计套利')
L(f'- **行业集中**: 前2大行业(半导体+元器件)占 24% 记录 → 专注硬科技赛道')
L('')

L('### 8.2 策略类型推断')
L('')
L('| 策略类型 | 证据 | 置信度 |')
L('|----------|------|--------|')
L('| **股票多空配对交易** | 同板块内股票交替买卖, 如半导体板块23只双向操作 | ⭐⭐⭐⭐⭐ |')
L('| **统计套利** | 红板科技16次双向(73.8%对冲)、东芯99.9%对冲 | ⭐⭐⭐⭐⭐ |')
L('| **指数增强** | 大量上榜成分股(中芯国际/中船特气/盛合晶微等科创板权重) | ⭐⭐⭐⭐ |')
L('| **事件驱动** | 烽火通信、长电科技单次大额 (4-7亿单边) | ⭐⭐⭐ |')
L('| **流动性提供** | 总净额平衡, 大量双向操作 | ⭐⭐⭐⭐ |')
L('')

L('### 8.3 重点跟踪股票池 (供交易参考)')
L('')
L('**最经典量化对冲标的**: ' + ', '.join([f'**{r["name"]}**({r["ts_code"]})' for _, r in quant.head(8).iterrows()]))
L('')
L('**单次大额买入**: ')
single_big_buy = agg[(agg['appearances'] == 1) & (agg['total_buy_万'] >= 10000)].sort_values('total_buy_万', ascending=False).head(8)
L(' | '.join([f'**{r["name"]}**({r["ts_code"]}) {r["total_buy_万"]:,.0f}万' for _, r in single_big_buy.iterrows()]))
L('')
L('**单次大额卖出**: ')
single_big_sell = agg[(agg['appearances'] == 1) & (agg['total_sell_万'] >= 10000)].sort_values('total_sell_万', ascending=False).head(8)
L(' | '.join([f'**{r["name"]}**({r["ts_code"]}) {r["total_sell_万"]:,.0f}万' for _, r in single_big_sell.iterrows()]))
L('')

# 时间分布
L('## 九、每日活跃度时序')
L('')
day_summary = df.groupby('trade_date').agg(
    records=('ts_code', 'count'),
    stocks=('ts_code', 'nunique'),
    buy=('buy', 'sum'),
    sell=('sell', 'sum'),
    net=('net_buy', 'sum'),
).reset_index().sort_values('trade_date')

L('| 日期 | 交易股票数 | 上榜记录数 | 买入(万) | 卖出(万) | 净额(万) |')
L('|------|-----------:|-----------:|---------:|---------:|---------:|')
for _, r in day_summary.iterrows():
    L(f'| {r["trade_date"]} | {int(r["stocks"])} | {int(r["records"])} | '
      f'{r["buy"]/1e4:,.1f} | {r["sell"]/1e4:,.1f} | {r["net"]/1e4:+,.1f} |')
L('')

# 附录
L('---')
L('')
L('## 附录: 原始数据')
L('')
L('| 文件 | 内容 |')
L('|------|------|')
L('| `ubs_garden_stone_trades.csv` | 全部377条原始记录 |')
L('| `ubs_garden_stone_trades_with_names.csv` | 含股票名称/行业/板块的明细 |')
L('| `ubs_garden_stone_by_stock.csv` | 按股票聚合的统计 |')
L('')

output_path = f'{DATA_DIR}/瑞银花园石桥路_近一月交易公司全图谱.md'
with open(output_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print(f'✓ 报告: {output_path}')
print(f'  长度: {len(lines)} 行 / {sum(len(l) for l in lines)} 字符')
