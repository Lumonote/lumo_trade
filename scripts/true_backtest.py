#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真回测系统 - 全市场候选池 + 完整评分pipeline
=============================================
从Tushare历史数据重建候选池，对每只股票跑30个量化模型+完整评分，
验证v20评分算法在历史数据上的真实表现。

用法:
    python scripts/true_backtest.py --days 30 --top-n 10
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# 统一数据缓存层
from data.cache.data_cache import (
    get_trade_calendar, get_ohlcv, batch_fetch_ohlcv,
    get_market_daily, get_market_basic, get_market_flow,
    fetch_market_data, OHLCV_DIR, MARKET_DIR,
    _init_tushare, _code_to_ts as code_to_ts_code
)

# 输出目录 (回测结果, 不含缓存)
BASE_DIR = os.path.join(project_root, 'results', 'true_backtest')
DAILY_RESULTS_DIR = os.path.join(BASE_DIR, 'daily_results')


def ts_code_to_code(ts_code: str) -> str:
    """tushare格式转6位代码"""
    return ts_code.split('.')[0]


class TrueBacktester:
    def __init__(self, backtest_days=30, top_n=10, workers=3, api_sleep=0.35):
        self.backtest_days = backtest_days
        self.top_n = top_n
        self.workers = workers
        self.api_sleep = api_sleep
        self.pro = _init_tushare()

        # 创建结果目录
        for d in [BASE_DIR, DAILY_RESULTS_DIR]:
            os.makedirs(d, exist_ok=True)

        self.trade_days = []  # 所有交易日
        self.backtest_dates = []  # 要回测的日期
        self.all_candidates = {}  # {date: [codes]}
        self.unique_codes = set()

    # ==================== Phase 1: 数据准备 ====================

    def _get_trade_calendar(self):
        """获取交易日历 (使用统一缓存)"""
        self.trade_days = get_trade_calendar()
        print(f"  交易日历: {len(self.trade_days)} 天 ({self.trade_days[0]} ~ {self.trade_days[-1]})")

    def _select_backtest_dates(self):
        """选择回测日期（确保有10日收益数据）"""
        today = datetime.now().strftime('%Y%m%d')
        # 需要report_date + 11个交易日后有数据（buy_date+10d）
        # 安全起见，选 today-15个交易日 之前的日期
        cutoff_idx = None
        for i, d in enumerate(self.trade_days):
            if d >= today:
                cutoff_idx = i
                break
        if cutoff_idx is None:
            cutoff_idx = len(self.trade_days)

        # 回退15个交易日确保10d收益可计算
        safe_idx = max(0, cutoff_idx - 15)
        available = self.trade_days[:safe_idx]

        self.backtest_dates = available[-self.backtest_days:]
        print(f"  回测日期: {len(self.backtest_dates)} 天 ({self.backtest_dates[0]} ~ {self.backtest_dates[-1]})")

    def _fetch_market_data(self):
        """获取每日全市场数据 (使用统一缓存)"""
        print(f"\n[Phase 1] 获取市场数据...")
        fetched = 0
        for i, date in enumerate(self.backtest_dates):
            result = fetch_market_data(date, pro=self.pro, sleep=self.api_sleep)
            if not all(result.values()):
                fetched += 1  # 有新获取

            if (i + 1) % 10 == 0:
                print(f"  进度: {i+1}/{len(self.backtest_dates)} 天")

        print(f"  市场数据准备完成: {len(self.backtest_dates)} 天")

    # ==================== Phase 2: 候选池重建 ====================

    def _reconstruct_candidates(self):
        """为每个回测日重建候选池 (使用统一缓存)"""
        print(f"\n[Phase 2] 重建候选池...")

        for date in self.backtest_dates:
            candidates = set()

            # --- 1. 高换手率股（热股代理）---
            df_basic = get_market_basic(date)
            if df_basic is not None:
                # 过滤: 排除ST, BJ (北交所8/4开头), 新股(上市不足60天)
                df_basic = df_basic[df_basic['ts_code'].notna()]
                df_basic = df_basic[~df_basic['ts_code'].str.startswith(('8', '4', '9'))]
                if 'turnover_rate' in df_basic.columns:
                    top_turnover = df_basic.nlargest(100, 'turnover_rate')['ts_code'].tolist()
                    candidates.update(ts_code_to_code(c) for c in top_turnover)

            # --- 2. 资金净流入股 ---
            df_flow = get_market_flow(date)
            if df_flow is not None and 'net_amount' in df_flow.columns:
                    top_flow = df_flow.nlargest(40, 'net_amount')['ts_code'].tolist()
                    candidates.update(ts_code_to_code(c) for c in top_flow)

            # --- 3. 涨幅前50 ---
            df_daily = get_market_daily(date)
            if df_daily is not None:
                df_daily = df_daily[df_daily['ts_code'].notna()]
                df_daily = df_daily[~df_daily['ts_code'].str.startswith(('8', '4', '9'))]
                if 'pct_chg' in df_daily.columns:
                    top_gainers = df_daily[df_daily['pct_chg'] > 3].nlargest(50, 'pct_chg')['ts_code'].tolist()
                    candidates.update(ts_code_to_code(c) for c in top_gainers)

            # 过滤非法代码
            candidates = {c for c in candidates if len(c) == 6 and c.isdigit()
                         and not c.startswith(('8', '4', '9'))}

            self.all_candidates[date] = sorted(candidates)
            self.unique_codes.update(candidates)

        total_cands = sum(len(v) for v in self.all_candidates.values())
        avg_cands = total_cands / len(self.backtest_dates) if self.backtest_dates else 0
        print(f"  候选池: 日均 {avg_cands:.0f} 只, 唯一股票 {len(self.unique_codes)} 只")

    # ==================== Phase 3: K线数据采集 ====================

    def _fetch_ohlcv_data(self):
        """批量获取候选股的历史K线数据 (使用统一缓存, 2年历史)"""
        print(f"\n[Phase 3] 获取K线数据 (2年历史)...")

        # 计算需要的日期范围: 向前推2年 + 向后推15天
        earliest = self.backtest_dates[0]
        latest = self.backtest_dates[-1]
        start_date = (datetime.strptime(earliest, '%Y%m%d') - timedelta(days=750)).strftime('%Y%m%d')
        end_date = (datetime.strptime(latest, '%Y%m%d') + timedelta(days=20)).strftime('%Y%m%d')

        batch_fetch_ohlcv(
            self.unique_codes, pro=self.pro,
            start_date=start_date, end_date=end_date,
            sleep=self.api_sleep
        )

    # ==================== Phase 4: 评分 ====================

    def _score_single_stock(self, scorer, code, date, fund_data):
        """评分单只股票"""
        df = get_ohlcv(code, min_rows=60)
        if df is None:
            return None

        try:
            # 截止到回测日（防止未来数据泄露）
            cutoff = pd.Timestamp(datetime.strptime(date, '%Y%m%d'))
            df = df[df['timestamps'] <= cutoff].copy()

            if len(df) < 60:
                return None

            # 准备基本面数据
            fundamental = None
            if fund_data is not None and code in fund_data:
                fd = fund_data[code]
                fundamental = {
                    'pe_ratio': fd.get('pe_ttm'),
                    'pb_ratio': fd.get('pb'),
                    'total_market_cap': fd.get('total_mv', 0) / 10000 if fd.get('total_mv') else None,  # 万元→亿元
                    'circulation_market_cap': fd.get('circ_mv', 0) / 10000 if fd.get('circ_mv') else None,
                }

            result = scorer.calculate_comprehensive_score(
                code,
                historical_data=df,
                fundamental_data=fundamental
            )

            quant_details = result.get('details', {}).get('quantitative', {})
            tech_details = result.get('details', {}).get('technical', {})
            momentum_details = result.get('details', {}).get('momentum', {})

            return {
                'code': code,
                'name': result.get('details', {}).get('stock_name', code),
                'score': result.get('total_score', 0),
                'rating': result.get('rating', 'C'),
                'buy_signals': quant_details.get('buy_count', 0),
                'sell_signals': quant_details.get('sell_count', 0),
                'quant_score': result.get('scores', {}).get('quantitative', 0),
                'tech_score': result.get('scores', {}).get('technical', 0),
                'rsi': tech_details.get('RSI', None),
                'chase_risk': momentum_details.get('chase_risk_score', None),
                'position_pct': momentum_details.get('position_pct', None),
                'day_change': result.get('details', {}).get('price_changes', {}).get('change_1d', None),
                'change_3d': result.get('details', {}).get('price_changes', {}).get('change_3d', None),
                'change_5d': result.get('details', {}).get('price_changes', {}).get('change_5d', None),
            }
        except Exception as e:
            logger.debug(f"  {code} 评分失败: {e}")
            return None

    def _score_all(self):
        """对所有回测日的候选股评分"""
        print(f"\n[Phase 4] 评分 (30个量化模型 + 完整pipeline)...")

        from analysis.historical_scorer import HistoricalScorer

        all_results = []

        for date_idx, date in enumerate(self.backtest_dates):
            candidates = self.all_candidates.get(date, [])
            if not candidates:
                continue

            # 加载当日基本面数据
            fund_data = {}
            df_basic = get_market_basic(date)
            if df_basic is not None:
                for _, row in df_basic.iterrows():
                    code = ts_code_to_code(str(row.get('ts_code', '')))
                    fund_data[code] = row.to_dict()

            # 每个日期创建新的scorer实例（避免状态污染）
            scorer = HistoricalScorer()

            scored = []
            failed = 0

            # 并行评分
            if self.workers > 1:
                with ThreadPoolExecutor(max_workers=self.workers) as executor:
                    futures = {
                        executor.submit(self._score_single_stock, scorer, code, date, fund_data): code
                        for code in candidates
                    }
                    for future in as_completed(futures):
                        result = future.result()
                        if result:
                            scored.append(result)
                        else:
                            failed += 1
            else:
                for code in candidates:
                    result = self._score_single_stock(scorer, code, date, fund_data)
                    if result:
                        scored.append(result)
                    else:
                        failed += 1

            # 按分数排序，取top_n
            scored.sort(key=lambda x: x['score'], reverse=True)

            # 保存当日全部结果
            if scored:
                df_day = pd.DataFrame(scored)
                df_day['report_date'] = date
                df_day.to_csv(os.path.join(DAILY_RESULTS_DIR, f'{date}.csv'), index=False)

                # Top N
                for rank, item in enumerate(scored[:self.top_n], 1):
                    item['report_date'] = date
                    item['rank'] = rank
                    # 置信度分级
                    s = item['score']
                    if s >= 85:
                        item['confidence_tier'] = 'S'
                    elif s >= 78:
                        item['confidence_tier'] = 'A'
                    elif s >= 70:
                        item['confidence_tier'] = 'B'
                    else:
                        item['confidence_tier'] = 'C'
                    all_results.append(item)

            n_scored = len(scored)
            top_score = scored[0]['score'] if scored else 0
            top_code = scored[0]['code'] if scored else '-'
            print(f"  [{date_idx+1}/{len(self.backtest_dates)}] {date}: "
                  f"候选{len(candidates)}, 评分{n_scored}, 失败{failed}, "
                  f"Top1: {top_code}({top_score:.1f}分)")

        self.results_df = pd.DataFrame(all_results) if all_results else pd.DataFrame()
        print(f"\n  总入选: {len(self.results_df)} 条 ({len(self.backtest_dates)} 天 × Top{self.top_n})")

    # ==================== Phase 5: 收益计算 ====================

    def _compute_returns(self):
        """计算实际收益"""
        if self.results_df.empty:
            return
        print(f"\n[Phase 5] 计算实际收益...")

        def next_trade_day(date_str, n=1):
            d = date_str.replace('-', '')
            future = [t for t in self.trade_days if t > d]
            return future[n - 1] if len(future) >= n else None

        computed = 0
        for idx, row in self.results_df.iterrows():
            code = str(row['code']).zfill(6)
            report_date = str(row['report_date'])

            buy_day = next_trade_day(report_date, 1)
            day_1 = next_trade_day(report_date, 2)
            day_3 = next_trade_day(report_date, 4)
            day_5 = next_trade_day(report_date, 6)
            day_10 = next_trade_day(report_date, 11)

            if not buy_day or not day_5:
                continue

            df = get_ohlcv(code, min_rows=1)
            if df is None:
                continue

            try:
                df['date_str'] = df['timestamps'].dt.strftime('%Y%m%d')
                prices = dict(zip(df['date_str'], df['close']))
                opens = dict(zip(df['date_str'], df['open']))

                # 用次日开盘价买入
                buy_price = opens.get(buy_day)
                if buy_price is None or buy_price == 0:
                    # fallback: 用次日收盘价
                    buy_price = prices.get(buy_day)
                if buy_price is None or buy_price == 0:
                    continue

                self.results_df.at[idx, 'buy_date'] = buy_day
                self.results_df.at[idx, 'buy_price'] = buy_price

                for label, target_day in [('return_1d', day_1), ('return_3d', day_3),
                                           ('return_5d', day_5), ('return_10d', day_10)]:
                    if target_day and target_day in prices:
                        ret = (prices[target_day] - buy_price) / buy_price * 100
                        self.results_df.at[idx, label] = ret

                # 5日最大回撤
                if day_5:
                    window = df[(df['date_str'] >= buy_day) & (df['date_str'] <= day_5)]
                    if len(window) > 0:
                        min_low = window['low'].min()
                        self.results_df.at[idx, 'max_drawdown_5d'] = (min_low - buy_price) / buy_price * 100

                computed += 1
            except Exception:
                continue

        print(f"  收益计算完成: {computed}/{len(self.results_df)} 条")

    # ==================== Phase 6: 报告生成 ====================

    def _generate_report(self):
        """生成回测报告"""
        if self.results_df.empty:
            print("  无数据，跳过报告生成")
            return

        df = self.results_df
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 保存主CSV
        csv_path = os.path.join(BASE_DIR, f'backtest_true_{timestamp}.csv')
        df.to_csv(csv_path, index=False)
        print(f"\n  主数据: {csv_path}")

        # 生成Markdown报告
        lines = []
        lines.append("# 真回测报告 - 全市场候选池 + 完整评分Pipeline")
        lines.append("")
        lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**回测范围**: {self.backtest_dates[0]} ~ {self.backtest_dates[-1]}")
        lines.append(f"**回测天数**: {len(self.backtest_dates)} 个交易日")
        lines.append(f"**候选池**: Tushare换手率Top100 + 资金流入Top40 + 涨幅前50")
        lines.append(f"**评分方式**: 完整30个量化模型 + v20 penalty/bonus")
        lines.append(f"**每日选股**: Top {self.top_n}")
        lines.append(f"**总入选**: {len(df)} 条")
        lines.append("")

        # 核心指标
        lines.append("## 一、核心指标")
        lines.append("")
        for period, label in [('return_1d', '1日'), ('return_3d', '3日'),
                               ('return_5d', '5日'), ('return_10d', '10日')]:
            if period not in df.columns:
                continue
            valid = df[period].dropna()
            if len(valid) > 0:
                wr = (valid > 0).mean() * 100
                avg = valid.mean()
                med = valid.median()
                pf = abs(valid[valid > 0].sum() / valid[valid < 0].sum()) if (valid < 0).any() and valid[valid < 0].sum() != 0 else float('inf')
                pf_str = f"{pf:.2f}" if pf != float('inf') else "INF"
                lines.append(f"- **{label}收益**: 均值 {avg:+.2f}%, 中位数 {med:+.2f}%, "
                           f"胜率 {wr:.1f}%, 盈亏比 {pf_str}")
        lines.append("")

        # 置信度分级
        lines.append("## 二、置信度分级表现")
        lines.append("")
        lines.append("| 置信度 | 说明 | 数量 | 5日均收益 | 5日胜率 | 10日均收益 | 盈亏比 |")
        lines.append("|--------|------|------|-----------|---------|-----------|--------|")

        for tier, desc in [('S', '强烈推荐(≥85)'), ('A', '可考虑(≥78)'), ('B', '谨慎(≥70)'), ('C', '不建议(<70)')]:
            sub = df[df['confidence_tier'] == tier]
            if len(sub) == 0:
                lines.append(f"| {tier} | {desc} | 0 | - | - | - | - |")
                continue
            r5 = sub['return_5d'].dropna() if 'return_5d' in sub.columns else pd.Series(dtype=float)
            r10 = sub['return_10d'].dropna() if 'return_10d' in sub.columns else pd.Series(dtype=float)
            if len(r5) > 0:
                pf = abs(r5[r5 > 0].sum() / r5[r5 < 0].sum()) if (r5 < 0).any() and r5[r5 < 0].sum() != 0 else float('inf')
                pf_str = f"{pf:.2f}" if pf != float('inf') else "INF"
                r10_avg = r10.mean() if len(r10) > 0 else 0
                lines.append(f"| {tier} | {desc} | {len(sub)} | "
                           f"{r5.mean():+.2f}% | {(r5 > 0).mean()*100:.1f}% | "
                           f"{r10_avg:+.2f}% | {pf_str} |")
            else:
                lines.append(f"| {tier} | {desc} | {len(sub)} | - | - | - | - |")
        lines.append("")

        # 按排名表现
        lines.append("## 三、按排名表现")
        lines.append("")
        lines.append("| 排名 | 数量 | 5日均收益 | 5日胜率 | 10日均收益 |")
        lines.append("|------|------|-----------|---------|-----------|")
        for rank in range(1, self.top_n + 1):
            sub = df[df['rank'] == rank]
            r5 = sub['return_5d'].dropna() if 'return_5d' in sub.columns else pd.Series(dtype=float)
            r10 = sub['return_10d'].dropna() if 'return_10d' in sub.columns else pd.Series(dtype=float)
            if len(r5) > 0:
                lines.append(f"| {rank} | {len(r5)} | {r5.mean():+.2f}% | "
                           f"{(r5>0).mean()*100:.1f}% | "
                           f"{r10.mean() if len(r10) > 0 else 0:+.2f}% |")
        lines.append("")

        # 评分区间表现
        lines.append("## 四、评分区间表现")
        lines.append("")
        lines.append("| 评分区间 | 数量 | 5日均收益 | 5日胜率 | 3日均收益 |")
        lines.append("|----------|------|-----------|---------|-----------|")
        bins = [(85, 999, '85+'), (80, 85, '80-85'), (75, 80, '75-80'),
                (70, 75, '70-75'), (60, 70, '60-70'), (0, 60, '<60')]
        for low, high, label in bins:
            sub = df[df['score'] >= low] if high == 999 else df[(df['score'] >= low) & (df['score'] < high)]
            if len(sub) == 0:
                lines.append(f"| {label} | 0 | - | - | - |")
                continue
            r5 = sub['return_5d'].dropna() if 'return_5d' in sub.columns else pd.Series(dtype=float)
            r3 = sub['return_3d'].dropna() if 'return_3d' in sub.columns else pd.Series(dtype=float)
            if len(r5) > 0:
                lines.append(f"| {label} | {len(sub)} | {r5.mean():+.2f}% | "
                           f"{(r5 > 0).mean()*100:.1f}% | "
                           f"{r3.mean():+.2f}% |")
        lines.append("")

        # 每日Top3展示
        lines.append("## 五、每日Top3选股")
        lines.append("")
        lines.append("| 日期 | Top1 | Top2 | Top3 | 5日均收益 |")
        lines.append("|------|------|------|------|-----------|")
        for date in self.backtest_dates:
            day_data = df[df['report_date'] == date].sort_values('rank')
            if len(day_data) == 0:
                continue
            tops = []
            for _, row in day_data.head(3).iterrows():
                code = str(row['code']).zfill(6)
                score = row['score']
                r5 = row.get('return_5d', None)
                r5_str = f"{r5:+.1f}%" if pd.notna(r5) else "?"
                tops.append(f"{code}({score:.0f},{r5_str})")
            while len(tops) < 3:
                tops.append("-")
            day_r5 = day_data['return_5d'].dropna()
            avg_r5 = f"{day_r5.mean():+.2f}%" if len(day_r5) > 0 else "-"
            date_fmt = f"{date[:4]}-{date[4:6]}-{date[6:]}"
            lines.append(f"| {date_fmt} | {tops[0]} | {tops[1]} | {tops[2]} | {avg_r5} |")
        lines.append("")

        report_path = os.path.join(BASE_DIR, 'true_backtest_report.md')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"  报告: {report_path}")

    # ==================== 主入口 ====================

    def run(self):
        """运行完整回测"""
        print("=" * 70)
        print("  真回测系统 - 全市场候选池 + 完整评分Pipeline")
        print("=" * 70)
        start_time = time.time()

        # Phase 1: 准备
        print(f"\n[准备] 初始化...")
        self._get_trade_calendar()
        self._select_backtest_dates()
        self._fetch_market_data()

        # Phase 2: 候选池
        self._reconstruct_candidates()

        # Phase 3: K线数据
        self._fetch_ohlcv_data()

        # Phase 4: 评分
        self._score_all()

        # Phase 5: 收益
        self._compute_returns()

        # Phase 6: 报告
        self._generate_report()

        elapsed = time.time() - start_time
        print(f"\n{'=' * 70}")
        print(f"  回测完成! 耗时 {elapsed/60:.1f} 分钟")
        print(f"  输出目录: {BASE_DIR}")
        print(f"{'=' * 70}")

        # 打印关键指标
        if not self.results_df.empty:
            r5 = self.results_df['return_5d'].dropna()
            if len(r5) > 0:
                print(f"\n  === 关键指标 ===")
                print(f"  5日均收益: {r5.mean():+.2f}%")
                print(f"  5日胜率: {(r5 > 0).mean()*100:.1f}%")
                print(f"  5日中位数: {r5.median():+.2f}%")

                for tier in ['S', 'A', 'B', 'C']:
                    sub = self.results_df[self.results_df['confidence_tier'] == tier]
                    tr5 = sub['return_5d'].dropna()
                    if len(tr5) > 0:
                        print(f"  {tier}级: n={len(sub)}, wr={((tr5>0).mean()*100):.1f}%, avg={tr5.mean():+.2f}%")


def main():
    parser = argparse.ArgumentParser(description='真回测系统')
    parser.add_argument('--days', type=int, default=30, help='回测天数 (默认30)')
    parser.add_argument('--top-n', type=int, default=10, help='每日选股数 (默认10)')
    parser.add_argument('--workers', type=int, default=3, help='并行评分线程 (默认3)')
    parser.add_argument('--api-sleep', type=float, default=0.35, help='API间隔秒数 (默认0.35)')
    args = parser.parse_args()

    bt = TrueBacktester(
        backtest_days=args.days,
        top_n=args.top_n,
        workers=args.workers,
        api_sleep=args.api_sleep,
    )
    bt.run()


if __name__ == '__main__':
    main()
