#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会挖掘报表生成器
生成包含漏斗筛选、TOP推荐、详细分析的HTML报表
"""

import os
import sys
from datetime import datetime
from typing import List, Dict
import json
import logging

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _fmt_money(num):
    try:
        val = float(num)
        abs_val = abs(val)
        if abs_val >= 100000000:
            return f"{val/100000000:+.2f}亿"
        elif abs_val >= 10000:
            return f"{val/10000:+.2f}万"
        else:
            return f"{val:+.2f}"
    except:
        return '—'


def _generate_selection_reason(stock: Dict) -> str:
    """
    根据股票的评分数据生成有意义的入选原因
    """
    try:
        scoring = stock.get('scoring_result') or {}
        scores = scoring.get('scores') or {}
        details = scoring.get('details') or {}

        reasons = []
        rating = stock.get('rating') or scoring.get('rating') or 'C'
        final_score = float(stock.get('final_score', 0) or 0)

        tech_score = float(scores.get('technical', 0) or 0)
        sent_score = float(scores.get('sentiment', 0) or 0)
        quant_score = float(scores.get('quantitative', 0) or 0)
        sector_score = float(scores.get('sector', 0) or 0)

        sec = details.get('sector') or {}
        sector_name = sec.get('sector_name', '')
        sector_chg = float(sec.get('change_pct', 0) or 0)

        cf = details.get('sentiment', {}).get('capital_flow') or {}
        cf_trend = cf.get('trend', '')

        qd = details.get('quantitative') or {}
        buy_count = int(qd.get('buy_count', 0) or 0)

        ed = details.get('events') or {}
        pos_events = int(ed.get('positive_events', 0) or 0)
        ev_rating = ed.get('rating', '')

        price_changes = details.get('price_changes') or {}
        change_1d = float(price_changes.get('change_1d', 0) or 0)
        change_3d = float(price_changes.get('change_3d', 0) or 0)

        if rating == 'A':
            reasons.append("综合评级A级")
        elif rating == 'B' and final_score >= 80:
            reasons.append("综合评分优秀")

        if tech_score >= 75:
            reasons.append(f"技术面强势({tech_score:.0f}分)")
        elif tech_score >= 65:
            reasons.append(f"技术指标向好({tech_score:.0f}分)")

        if sector_name and sector_name != '未知':
            if sector_chg >= 5:
                reasons.append(f"{sector_name}领涨+{sector_chg:.1f}%")
            elif sector_chg >= 2:
                reasons.append(f"{sector_name}板块走强+{sector_chg:.1f}%")
            elif sector_chg > 0:
                reasons.append(f"{sector_name}板块温和上涨+{sector_chg:.1f}%")

        if cf_trend == 'inflow':
            reasons.append("资金持续流入")
        elif cf_trend == 'strong_inflow':
            reasons.append("资金大幅流入")

        if buy_count >= 3:
            reasons.append(f"{buy_count}个量化模型发出买入信号")
        elif buy_count >= 2:
            reasons.append(f"{buy_count}个量化模型共振看涨")

        if pos_events >= 2:
            reasons.append(f"{pos_events}条利好事件驱动")

        if ev_rating == '利好':
            reasons.append("消息面偏正面")

        if change_3d >= 5:
            reasons.append(f"三日涨幅{change_3d:+.1f}%")

        if len(reasons) >= 2:
            return "；".join(reasons[:3])
        elif len(reasons) == 1:
            return reasons[0]
        else:
            if final_score >= 70:
                return f"综合评分{final_score:.0f}分，各维度表现良好"
            elif final_score >= 60:
                return f"综合评分{final_score:.0f}分，具备投资价值"
            else:
                return "通过多维度筛选，满足投资条件"
    except Exception:
        return "综合评分达标"


class OpportunityReportGenerator:
    """投资机会挖掘报表生成器"""

    def __init__(self, output_dir: str = "results"):
        """
        初始化报表生成器

        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_report(self, analysis_results: List[Dict],
                       report_title: str = "投资机会挖掘报告",
                       global_hot_news: List[Dict] = None,
                       sector_hot_news: List[Dict] = None,
                       hot_news_title: str = None) -> str:
        """
        生成投资机会挖掘HTML报表

        Args:
            analysis_results: 分析结果列表，每个元素是OpportunityFilter的输出
            report_title: 报告标题

        Returns:
            生成的HTML文件路径
        """
        logger.info(f"开始生成投资机会挖掘报表...")

        # 统计数据
        total_count = len(analysis_results)
        passed_stocks = [r for r in analysis_results if r.get('passed', False)]
        passed_count = len(passed_stocks)

        # 按阶段统计淘汰情况
        stage_stats = self._calculate_stage_statistics(analysis_results)

        # 生成漏斗数据
        funnel_data = self._generate_funnel_data(stage_stats, total_count)

        # TOP 推荐（完整排序，前端默认显示20行并可滚动）
        top_20 = sorted(passed_stocks, key=lambda x: x.get('final_score', 0), reverse=True)

        # 量化优先排名（量化模型数量优先 + 分数排名）
        def quant_sort_key(stock):
            score = stock.get('final_score', 0)
            details = (stock.get('scoring_result') or {}).get('details') or {}
            quant = details.get('quantitative') or {}
            models = quant.get('top_buy_models') or []
            model_count = len(models)
            return (model_count, score)

        quant_top_20 = sorted(passed_stocks, key=quant_sort_key, reverse=True)

        # 按淘汰阶段分组
        grouped_stocks = self._group_by_elimination_stage(analysis_results)

        # 记录热门话题，供Markdown报表复用
        self._latest_global_hot_news = global_hot_news or []

        # 生成HTML
        html_content = self._generate_html(
            report_title=report_title,
            total_count=total_count,
            passed_count=passed_count,
            stage_stats=stage_stats,
            funnel_data=funnel_data,
            top_20=top_20,
            quant_top_20=quant_top_20,
            grouped_stocks=grouped_stocks,
            global_hot_news=self._latest_global_hot_news,
            sector_hot_news=sector_hot_news or [],
            hot_news_title=hot_news_title
        )

        # 保存文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"opportunity_discovery_{timestamp}.html"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"✓ 报表生成完成: {filepath}")

        try:
            md_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            md_filename = f"opportunity_top10_{md_timestamp}.md"
            md_path = os.path.join(self.output_dir, md_filename)

            MODEL_DISPLAY_MAP = {
                'balance_dual_moving': '均衡双均线', 'multi_breakthrough': '多重突破', 'support_resistance': '支撑阻力',
                'trend_pullback': '趋势回踩', 'ma_resonance': '均线共振', 'super_reversal': '超级反转',
                'capital_trend': '资金趋势', 'volume_breakthrough': '量能突破', 'three_sisters': '三姐妹形态',
                'macd_axis_golden_cross': '轴心MACD金叉', 'six_dimension_resonance': '六维共振',
                'statistical_quantitative': '统计量化', 'super_profit_limit_up': '超额涨停',
                'turtle_trading_system': '海龟交易', 'atr_momentum': 'ATR动量', 'cta_trend_strategy': 'CTA趋势',
                'machine_learning_rf': '机器学习RF', 'multi_factor_alpha': '多因子Alpha',
                'pairs_trading_arbitrage': '配对交易套利', 'hft_microstructure': '高频微结构',
                'ichimoku_cloud': '一目均衡云', 'bollinger_squeeze': '布林收敛', 'rsi_divergence': 'RSI背离',
                'stochastic_momentum': '随机动量', 'volume_price_trend': '量价趋势', 'parabolic_sar': '抛物转向SAR',
                'chaikin_money_flow': '切金资金流', 'elder_ray': 'Elder射线', 'vwap_deviation': 'VWAP偏离',
                'fractal_adaptive_ma': '分形自适应均线'
            }

            lines = []
            lines.append("# 投资机会挖掘 TOP20 报告")
            lines.append(f"\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

            # 综合排名 TOP20
            lines.append("## 🏆 综合排名 TOP20")
            lines.append(" | 排名 | 代码 | 股票名称 | 综合得分 | 详细分析 | ")
            lines.append(" |------|------|----------|----------|----------| ")

            for i, stock in enumerate(top_20[:20], 1):
                code = stock.get('stock_code') or stock.get('code') or '未知'
                name_txt = stock.get('name', '未知')
                score = float(stock.get('final_score', 0) or 0)

                summary_txt = self._build_full_indicator_summary(stock)
                advanced_txt = self._build_advanced_analysis_summary(stock)
                
                # 合并展示：指标信息 + 高级分析
                full_analysis = f"{summary_txt}<br><b>【高级分析】</b>{advanced_txt}"
                
                lines.append(f" | {i} | {code} | {name_txt} | {score:.2f} | {full_analysis} | ")

            # 添加股吧话题精选（如果有）
            topics = getattr(self, '_latest_global_hot_news', None)
            if topics:
                lines.append("\n---\n")
                lines.append("## 💬 股吧话题精选\n")
                idx = 1
                for t in topics:
                    title = t.get('title', '') or ''
                    if not title or '【有奖】' in title:
                        continue
                    raw_url = t.get('url', '') or ''
                    if raw_url.startswith('http'):
                        url = raw_url
                    else:
                        base = 'https://gubatopic.eastmoney.com/'
                        if raw_url.startswith('/'):
                            url = base.rstrip('/') + raw_url
                        else:
                            url = base.rstrip('/') + '/' + raw_url
                    heat = t.get('heat', 0)
                    lines.append(f"{idx}. [{title}]({url}) - 热度: {heat}")
                    idx += 1

            # 添加板块分组股票表格
            lines.append("\n---\n")
            lines.append("## 📊 热点股票板块分布\n")
            lines.append(" | 所属板块 | 股票列表 |")
            lines.append(" |-------------------|----------|")

            # 按板块分组所有股票，存储板块涨幅
            sector_stocks = {}
            sector_change_candidates = {}

            def _is_numeric_text(text) -> bool:
                try:
                    stripped = str(text).strip()
                except Exception:
                    return False
                if not stripped:
                    return False
                if stripped.startswith(('+', '-')):
                    stripped = stripped[1:]
                if stripped.count('.') > 1:
                    return False
                parts = stripped.split('.')
                if not all(p.isdigit() for p in parts if p != ''):
                    return False
                return any(p != '' for p in parts)

            def _pick_sector_change(candidates):
                if not candidates:
                    return None
                usable = []
                for c in candidates:
                    if c is None:
                        continue
                    if isinstance(c, bool):
                        continue
                    if isinstance(c, (int, float)):
                        usable.append(float(c))
                        continue
                    if isinstance(c, str):
                        s = c.strip()
                        if not s or _is_numeric_text(s) is False:
                            continue
                        try:
                            usable.append(float(s))
                        except Exception:
                            continue
                if not usable:
                    return None
                rounded = [round(v, 2) for v in usable]
                freq = {}
                for v in rounded:
                    freq[v] = freq.get(v, 0) + 1
                best = max(freq.items(), key=lambda x: (x[1], abs(x[0])))[0]
                return float(best)
            for stock in analysis_results:
                details = stock.get('scoring_result', {}).get('details', {})
                sector = details.get('sector') or {}
                sector_name = sector.get('sector_name', '')
                sector_chg = sector.get('change_pct', None)

                if sector_name is not None:
                    sector_name = str(sector_name).strip()

                # 将未知板块归类为"其他"
                if (not sector_name) or sector_name == '未知' or _is_numeric_text(sector_name):
                    sector_name = '其他'

                if sector_name not in sector_stocks:
                    sector_stocks[sector_name] = []
                    sector_change_candidates[sector_name] = []
                sector_change_candidates[sector_name].append(sector_chg)
                sector_stocks[sector_name].append(stock)

            # 如果没有板块数据，提示用户
            if not sector_stocks:
                lines.append(" | 暂无板块数据 | — |")
            else:
                # 按股票数量降序排序，相同数量的按涨幅降序排序
                sorted_sectors = sorted(
                    sector_stocks.items(),
                    key=lambda x: (-len(x[1]), _pick_sector_change(sector_change_candidates.get(x[0])) or 0),
                    reverse=False
                )

                # 输出每个板块
                for sector_name, stocks in sorted_sectors:
                    sector_chg = _pick_sector_change(sector_change_candidates.get(sector_name))
                    if sector_chg is not None:
                        sector_chg_str = f"{sector_chg:+.2f}%"
                        sector_header = f"{sector_name}({sector_chg_str})"
                    else:
                        sector_header = sector_name

                    stock_parts = []
                    for stock in stocks:
                        code = stock.get('stock_code') or stock.get('code') or '未知'
                        name = stock.get('name', '未知')
                        price_changes = stock.get('scoring_result', {}).get('details', {}).get('price_changes', {})
                        change_pct = price_changes.get('change_1d') if price_changes else None
                        
                        if change_pct is not None:
                            change_str = f"{change_pct:+.2f}%"
                            stock_parts.append(f"**{name}({code})** {change_str}")
                        else:
                            stock_parts.append(f"**{name}({code})**")

                    stocks_str = " ".join(stock_parts)
                    lines.append(f" | {sector_header} | {stocks_str} |")

            # 添加LLM智能分析结果
            llm_stocks = [s for s in top_20[:20] if s.get('llm_analysis')]
            if llm_stocks:
                lines.append("\n---\n")
                lines.append("## 🤖 AI智能分析结果\n")
                for stock in llm_stocks:
                    llm_result = stock.get('llm_analysis', {})
                    stock_name = stock.get('name', '未知')
                    stock_code = stock.get('stock_code', '')
                    rating = stock.get('rating', 'C')

                    lines.append(f"### {stock_name}({stock_code}) - {rating}级\n")

                    # 处理多模型或单模型结果
                    results_to_show = []
                    if any(k in llm_result for k in ['qwen', 'deepseek']):
                        for model_name, model_result in llm_result.items():
                            if isinstance(model_result, dict) and 'error' not in model_result:
                                results_to_show.append((model_name, model_result))
                    else:
                        results_to_show.append((llm_result.get('llm_model', 'AI'), llm_result))

                    for model_name, result in results_to_show:
                        model_display = {'qwen': '通义千问', 'deepseek': 'DeepSeek'}.get(model_name, model_name.upper()) if model_name else 'AI'
                        lines.append(f"**{model_display}分析:**\n")

                        # 操作建议
                        operation = result.get('operation_advice', {})
                        action = operation.get('action', '-')
                        position = operation.get('position_control', '-')
                        target = operation.get('target_price', '-')
                        stop_loss = operation.get('stop_loss', '-')
                        confidence = operation.get('confidence', 0)
                        lines.append(f"- **操作建议**: {action} | 仓位: {position} | 目标价: {target} | 止损: {stop_loss} | 置信度: {confidence*100:.0f}%")

                        # 风险评估
                        risk = result.get('risk_assessment', {})
                        risk_level = risk.get('risk_level', '-')
                        risk_score = risk.get('overall_score', 0)
                        risk_points = risk.get('risk_points', [])
                        lines.append(f"- **风险评估**: {risk_level}风险 | 评分: {risk_score} | 风险点: {', '.join(risk_points[:3]) if risk_points else '无'}")

                        # 趋势预测
                        kline = result.get('kline_prediction', {})
                        trend = kline.get('trend', '-')
                        pred_conf = kline.get('confidence', 0)
                        support = kline.get('support_levels', [])
                        resistance = kline.get('resistance_levels', [])
                        lines.append(f"- **趋势预测**: {trend} | 置信度: {pred_conf*100:.0f}% | 支撑: {support[:2]} | 阻力: {resistance[:2]}")

                        # 策略
                        strategy = result.get('strategy', {})
                        short_term = strategy.get('short_term', '')
                        mid_term = strategy.get('mid_term', '')
                        if short_term:
                            lines.append(f"- **短线策略**: {short_term}")
                        if mid_term:
                            lines.append(f"- **中线策略**: {mid_term}")

                        # 总结
                        summary = result.get('summary', '')
                        if summary:
                            lines.append(f"- **综合建议**: {summary}")

                        lines.append("")

            lines.append("\n---\n")
            lines.append("*说明: 以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。*")

            with open(md_path, 'w', encoding='utf-8') as mf:
                mf.write('\n'.join(lines))
            logger.info(f"✓ TOP20统计Markdown已生成: {md_path}")
        except Exception as e:
            logger.warning(f"生成TOP20 Markdown失败: {e}")
        return filepath

    def _calculate_stage_statistics(self, analysis_results: List[Dict]) -> Dict:
        """
        计算各阶段统计数据

        Returns:
            {
                'stage1': {'passed': 60, 'eliminated': 40},
                'stage2': {'passed': 40, 'eliminated': 20},
                ...
            }
        """
        stats = {
            'stage0': {'passed': len(analysis_results), 'eliminated': 0},  # 初始数量
            'stage1': {'passed': 0, 'eliminated': 0},
            'stage2': {'passed': 0, 'eliminated': 0},
            'stage3': {'passed': 0, 'eliminated': 0},
            'stage4': {'passed': 0, 'eliminated': 0}
        }

        for result in analysis_results:
            eliminated_at = result.get('eliminated_at_stage', 0)

            if eliminated_at == 0:  # 通过所有阶段（显示至阶段4）
                for stage in range(1, 5):
                    stats[f'stage{stage}']['passed'] += 1
            else:
                # 仅统计至阶段4
                passed_before = min(max(eliminated_at - 1, 0), 4)
                for stage in range(1, passed_before + 1):
                    stats[f'stage{stage}']['passed'] += 1

                # 在阶段1-4被淘汰计入统计；阶段5淘汰忽略（事件面已移除）
                if 1 <= eliminated_at <= 4:
                    stats[f'stage{eliminated_at}']['eliminated'] += 1

        return stats

    def _generate_funnel_data(self, stage_stats: Dict, total: int) -> List[Dict]:
        """
        生成漏斗图数据

        Returns:
            [
                {'stage': '初始候选', 'count': 100, 'percentage': 100},
                {'stage': '量化筛选', 'count': 60, 'percentage': 60},
                ...
            ]
        """
        stage_names = {
            0: '初始候选',
            1: '量化筛选',
            2: '技术筛选',
            3: '情绪筛选',
            4: '基本面筛选'
        }

        funnel_data = []

        # 阶段0: 初始
        funnel_data.append({
            'stage': stage_names[0],
            'count': total,
            'percentage': 100
        })

        # 阶段1-4
        for i in range(1, 5):
            count = stage_stats[f'stage{i}']['passed']
            percentage = (count / total * 100) if total > 0 else 0

            funnel_data.append({
                'stage': stage_names[i],
                'count': count,
                'percentage': round(percentage, 1)
            })

        return funnel_data

    def _group_by_elimination_stage(self, analysis_results: List[Dict]) -> Dict:
        """
        按淘汰阶段分组

        Returns:
            {
                'passed': [...],  # 通过所有筛选的股票
                'stage1': [...],  # 在阶段1被淘汰
                'stage2': [...],
                ...
            }
        """
        grouped = {
            'passed': [],
            'stage1': [],
            'stage2': [],
            'stage3': [],
            'stage4': []
        }

        for result in analysis_results:
            if result.get('passed', False):
                grouped['passed'].append(result)
            else:
                stage = result.get('eliminated_at_stage', 0)
                if 1 <= stage <= 4:
                    grouped[f'stage{stage}'].append(result)

        # 排序：通过的按分数降序，淘汰的按分数降序
        for key in grouped:
            grouped[key] = sorted(grouped[key], key=lambda x: x.get('final_score', 0), reverse=True)

        return grouped

    def _generate_html(self, report_title: str, total_count: int, passed_count: int,
                      stage_stats: Dict, funnel_data: List[Dict], top_20: List[Dict], quant_top_20: List[Dict],
                      grouped_stocks: Dict, global_hot_news: List[Dict], sector_hot_news: List[Dict], hot_news_title: str = None) -> str:
        """生成HTML内容"""

        # 构建热门新闻关联股票映射
        related_map = {}
        def _mk_key(item):
            url = (item.get('url') or '').strip()
            if url:
                return url
            return f"{(item.get('source') or '').strip()}|{(item.get('title') or '').strip()}"

        # 收集所有股票并去重
        all_stocks = []
        try:
            for k in ['passed', 'stage1', 'stage2', 'stage3', 'stage4', 'stage5']:
                all_stocks.extend(grouped_stocks.get(k, []))
            seen = set()
            deduped = []
            for s in all_stocks:
                code = s.get('stock_code') or s.get('code') or ''
                if code and code not in seen:
                    seen.add(code)
                    deduped.append(s)
            all_stocks = deduped
        except Exception:
            pass

        # 预建键（与展示数量一致，改为9条）
        for item in (global_hot_news or [])[:9]:
            related_map[_mk_key(item)] = []

        # 遍历股票提取关联热门新闻
        try:
            for s in all_stocks:
                scoring_result = s.get('scoring_result') or {}
                events = (scoring_result.get('details') or {}).get('events') or {}
                matches = events.get('hot_news_matches') or []
                for m in matches:
                    key = _mk_key(m)
                    if key in related_map:
                        related_map[key].append({
                            'name': s.get('name') or s.get('stock_name') or '未知',
                            'stock_code': s.get('stock_code') or s.get('code') or '',
                            'rating': s.get('rating') or scoring_result.get('rating') or 'C',
                            'final_score': s.get('final_score') or scoring_result.get('final_score') or 0
                        })
        except Exception:
            pass

        # 生成热门新闻HTML
        hot_news_html = ''
        # 热门话题/新闻展示数量改为9条
        for item in (global_hot_news or [])[:9]:
            key = _mk_key(item)
            stocks = related_map.get(key, [])[:8]
            title = (item.get('title') or '').replace('"', '&quot;')
            url = (item.get('url') or '').strip()
            source = item.get('source') or ''
            publish_time = item.get('publish_time') or ''
            heat = item.get('heat') or ''
            rank = item.get('rank') or ''
            # 优先使用采集器解析到的关联股票（related_stocks）
            try:
                rel = item.get('related_stocks') or []
                if rel:
                    # 通过代码或名称映射到已评分股票，补充评级与分数用于标签渲染
                    idx = {}
                    name_idx = {}
                    for s in all_stocks:
                        code = s.get('stock_code') or s.get('code') or ''
                        if code:
                            idx[code] = s
                        nm0 = s.get('name') or s.get('stock_name') or ''
                        nm_key = (nm0 or '').replace(' ', '').lower()
                        if nm_key:
                            name_idx[nm_key] = s
                    rich = []
                    for r in rel:
                        code = r.get('stock_code') or ''
                        name = r.get('name') or ''
                        s = idx.get(code)
                        if (not s) and name:
                            s = name_idx.get((name or '').replace(' ', '').lower())
                        if s:
                            rich.append({
                                'name': s.get('name') or s.get('stock_name') or name or '未知',
                                'stock_code': s.get('stock_code') or s.get('code') or code,
                                'rating': s.get('rating') or (s.get('scoring_result') or {}).get('rating') or 'C',
                                'final_score': s.get('final_score') or (s.get('scoring_result') or {}).get('final_score') or 0
                            })
                        else:
                            # 若评分集中未出现该股，仍保留标签但不给分
                            rich.append({
                                'name': name or '未知',
                                'stock_code': code,
                                'rating': 'C',
                                'final_score': 0
                            })
                    rich = sorted(rich, key=lambda x: x.get('final_score', 0), reverse=True)
                    stocks = rich[:8]
            except Exception:
                pass
            if not stocks and title:
                # 回退：标题包含股票名称则展示相应股票标签
                try:
                    candidates = []
                    t = title
                    for s in all_stocks:
                        nm = s.get('name') or s.get('stock_name') or ''
                        if nm and (nm in t):
                            candidates.append({
                                'name': s.get('name') or s.get('stock_name') or '未知',
                                'stock_code': s.get('stock_code') or s.get('code') or '',
                                'rating': s.get('rating') or (s.get('scoring_result') or {}).get('rating') or 'C',
                                'final_score': s.get('final_score') or (s.get('scoring_result') or {}).get('final_score') or 0
                            })
                    if candidates:
                        candidates = sorted(candidates, key=lambda x: x.get('final_score', 0), reverse=True)
                        stocks = candidates[:5]
                except Exception:
                    pass
            tags_html = ''
            for st in stocks:
                rating_class = f"rating-{str(st.get('rating', 'C')).replace('+', '-plus')}"
                code_txt = st.get('stock_code', '')
                name_txt = st.get('name', '未知')
                display_txt = f"{name_txt}{f'({code_txt})' if code_txt else ''}"
                tags_html += f"<span class=\"stock-tag\"><span class=\"rating-badge {rating_class}\">{st.get('rating', 'C')}</span> {display_txt}</span>"
            # 新增：展示采集器识别的相关板块关键词
            sector_tags_html = ''
            # try:
            #     sectors = item.get('related_sectors') or []
            #     for sec in sectors[:4]:
            #         sector_tags_html += f"<span class=\"stock-tag muted\">{sec}</span>"
            # except Exception:
            #     pass
            meta_parts = []
            if source and ('股吧话题' not in source):
                meta_parts.append(f"<span class=\"source-badge\">{source}</span>")
            if publish_time:
                meta_parts.append(f"<span>时间: {publish_time}</span>")
            meta_parts.append(f"<span class=\"heat-badge\">热度 {heat}</span>")
            meta_parts.append(f"<span class=\"rank-badge small\">{rank if rank else '-'}</span>")
            meta_html = f"<div class=\"news-meta\">{''.join(meta_parts)}</div>"
            stock_tags_section = f"<div class=\"stock-tags\">{tags_html}{sector_tags_html}</div>" if (tags_html or sector_tags_html) else ""
            hot_news_html += (
                f"<div class=\"hot-news-item\">"
                f"<a href=\"{url}\" target=\"_blank\" class=\"news-title\">{title}</a>"
                f"{meta_html}"
                # f"{stock_tags_section}"
                f"</div>"
            )

        # 构建板块 -> 相关股票映射（用于板块新闻标签）
        sector_to_stocks = {}
        try:
            for s in all_stocks:
                scoring_result = s.get('scoring_result') or {}
                secd = (scoring_result.get('details') or {}).get('sector') or {}
                sec_name = (secd.get('sector_name') or '').strip()
                if not sec_name:
                    continue
                info = {
                    'name': s.get('name') or s.get('stock_name') or '未知',
                    'stock_code': s.get('stock_code') or s.get('code') or '',
                    'rating': s.get('rating') or scoring_result.get('rating') or 'C',
                    'final_score': s.get('final_score') or scoring_result.get('final_score') or 0
                }
                sector_to_stocks.setdefault(sec_name, []).append(info)

            # 各板块按分数排序
            for k in list(sector_to_stocks.keys()):
                sector_to_stocks[k] = sorted(sector_to_stocks[k], key=lambda x: x.get('final_score', 0), reverse=True)
        except Exception:
            pass

        # 生成板块新闻HTML（仅展示与板块内股票强相关的新闻）
        def _get_stocks_for_sector(name: str):
            n = (name or '').strip()
            if not n:
                return []
            # 1) 精确匹配
            exact = sector_to_stocks.get(n)
            if exact:
                return exact
            # 2) 子串模糊匹配（如“半导体及元件”匹配“半导体”）
            collected = []
            for k, v in sector_to_stocks.items():
                if n in k or k in n:
                    collected.extend(v)
            if collected:
                seen = set()
                dedup = []
                for s in collected:
                    code = s.get('stock_code', '')
                    if code and code not in seen:
                        seen.add(code)
                        dedup.append(s)
                return sorted(dedup, key=lambda x: x.get('final_score', 0), reverse=True)
            # 3) 同义词近似匹配
            syn = {
                '半导体': ['芯片', '集成电路', 'IC', '晶圆'],
                '光伏': ['太阳能', '硅料', '硅片', '电池片', '组件'],
                '锂电': ['动力电池', '电池', '电池产业链', '正极', '负极', '隔膜', '电解液'],
                '新能源': ['风电', '储能', '氢能'],
                '算力': ['数据中心', 'AI算力', 'GPU', '服务器'],
                '人工智能': ['AI', '大模型', 'AIGC'],
                '汽车': ['整车', '新能源车', '车企', '乘用车'],
                '券商': ['证券', '经纪'],
                '银行': ['商业银行'],
                '保险': ['寿险', '财险'],
                '地产': ['房地产', '房企']
            }
            candidates = []
            for k, vs in syn.items():
                if k in n or any(v in n for v in vs):
                    for sk, sv in sector_to_stocks.items():
                        if k in sk or any(v in sk for v in vs):
                            candidates.extend(sv)
            seen = set()
            dedup = []
            for s in candidates:
                code = s.get('stock_code', '')
                if code and code not in seen:
                    seen.add(code)
                    dedup.append(s)
            return sorted(dedup, key=lambda x: x.get('final_score', 0), reverse=True)

        sector_news_html = ''
        for item in (sector_hot_news or [])[:6]:
            sector_name = (item.get('sector_name') or '').strip()
            stocks = _get_stocks_for_sector(sector_name)[:8]
            if not stocks:
                # 若没有板块内高相关股票，跳过该新闻以避免空版块
                continue
            tags_html = ''
            for st in stocks:
                rating_class = f"rating-{str(st.get('rating', 'C')).replace('+', '-plus')}"
                tags_html += f"<span class=\"stock-tag\"><span class=\"rating-badge {rating_class}\">{st.get('rating', 'C')}</span> {st.get('name', '未知')}({st.get('stock_code', '')})</span>"

            title = (item.get('title') or '').replace('"', '&quot;')
            url = (item.get('url') or '').strip()
            source = item.get('source') or ''
            publish_time = item.get('publish_time') or ''
            heat = item.get('heat') or ''
            rank = item.get('rank') or ''

            # 板块徽章
            sector_badge = f"<span class=\"sector-badge\">{sector_name or '板块'}</span>"

            sector_news_html += (
                f"<div class=\"hot-news-item\">"
                f"<a href=\"{url}\" target=\"_blank\" class=\"news-title\">{title}</a>"
                f"<div class=\"news-meta\">{sector_badge}<span class=\"source-badge\">{source}</span><span>时间: {publish_time}</span><span class=\"heat-badge\">热度 {heat}</span><span class=\"rank-badge small\">{rank if rank else '-'}</span></div>"
                # f"<div class=\"stock-tags\">{tags_html}</div>"
                f"</div>"
            )

        # 若无板块新闻，则不渲染该版块
        sector_section_html = ''
        if sector_news_html.strip():
            sector_section_html = (
                '<div class="section">'
                '<div class="section-title">📈 热门板块相关新闻</div>'
                f'<div class="hot-news-list">{sector_news_html}</div>'
                '</div>'
            )

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report_title}</title>
    <style>
        :root {{
            --primary-bg: #1a1f2e;
            --secondary-bg: #252d42;
            --tertiary-bg: #2d3748;
            --accent-blue: #64b5f6;
            --accent-purple: #ba68c8;
            --accent-green: #66bb6a;
            --accent-red: #ef5350;
            --accent-yellow: #ffca28;
            --text-primary: #ffffff;
            --text-secondary: #e8eaf6;
            --text-muted: #b0bec5;
            --border-primary: #4a5568;
            --gradient-dark: linear-gradient(135deg, #252d42 0%, #2d3748 100%);
            /* 卡片主题（浅色背景） */
            --card-bg: #ffffff;
            --card-text-primary: #1f2937; /* 深色文本，提高可读性 */
            --card-text-secondary: #374151; /* 次级文本，降低灰度 */
            --card-text-muted: #4b5563; /* 辅助文本，避免过灰 */
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: var(--primary-bg);
            padding: 20px;
            color: var(--text-primary);
            line-height: 1.6;
            min-height: 100vh;
            overflow-x: hidden;
            position: relative;
        }}

        /* 动态背景与粒子效果，保持与批量分析风格一致 */
        body::before {{
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background:
                radial-gradient(circle at 20% 50%, rgba(91,155,213,0.08) 0%, transparent 50%),
                radial-gradient(circle at 80% 20%, rgba(159,122,234,0.08) 0%, transparent 50%),
                radial-gradient(circle at 40% 80%, rgba(72,187,120,0.08) 0%, transparent 50%);
            pointer-events: none;
            z-index: -1;
        }}

        body::after {{
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background-image:
                radial-gradient(1px 1px at 20px 30px, var(--accent-blue), transparent),
                radial-gradient(1px 1px at 40px 70px, var(--accent-purple), transparent),
                radial-gradient(1px 1px at 90px 40px, var(--accent-green), transparent),
                radial-gradient(1px 1px at 130px 80px, var(--accent-yellow), transparent);
            background-repeat: repeat;
            background-size: 200px 100px;
            animation: particleMove 20s linear infinite;
            opacity: 0.08;
            pointer-events: none;
            z-index: -1;
        }}

        @keyframes particleMove {{
            0% {{ transform: translate(0, 0); }}
            100% {{ transform: translate(-200px, -100px); }}
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .header {{
            background: var(--gradient-dark);
            border: 1px solid var(--border-primary);
            border-radius: 20px;
            padding: 40px;
            margin-bottom: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
            text-align: center;
            position: relative;
            overflow: hidden;
        }}

        .header::before {{
            content: '';
            position: absolute;
            top: 0; left: -100%;
            width: 100%; height: 100%;
            background: linear-gradient(90deg, transparent, rgba(0,212,255,0.1), transparent);
            animation: scanLine 3s linear infinite;
        }}

        @keyframes scanLine {{
            0% {{ left: -100%; }}
            100% {{ left: 100%; }}
        }}

        .header h1 {{
            font-size: 30px;
            color: var(--text-primary);
            margin-bottom: 8px;
            font-weight: 700;
        }}

        .header .subtitle {{
            font-size: 16px;
            color: var(--text-muted);
            margin-bottom: 20px;
        }}

        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .summary-card {{
            background: var(--secondary-bg);
            border: 1px solid var(--border-primary);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.25);
            transition: transform 0.3s ease;
        }}

        .summary-card:hover {{
            transform: translateY(-5px);
        }}

        .summary-card h3 {{
            font-size: 14px;
            color: var(--text-muted);
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        .summary-card .value {{
            font-size: 36px;
            font-weight: bold;
            color: var(--accent-blue);
        }}

        .summary-card .label {{
            font-size: 14px;
            color: var(--text-secondary);
            margin-top: 5px;
        }}

        .section {{
            background: white;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.08);
        }}

        .section-title {{
            font-size: 24px;
            color: var(--text-primary);
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 3px solid var(--accent-blue);
            font-weight: 600;
        }}

        /* 热门新闻版块样式 */
        .hot-news-list {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
            gap: 10px;
        }}
        .hot-news-item {{
            background: var(--card-bg);
            border: 1px solid #eee;
            border-radius: 10px;
            padding: 10px;
        }}
        .news-title {{
            font-size: 16px;
            color: var(--card-text-primary);
            text-decoration: none;
            font-weight: 600;
        }}
        .news-title:hover {{ text-decoration: underline; }}
        .news-meta {{
            margin-top: 6px;
            font-size: 12px;
            color: var(--card-text-secondary);
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .sector-badge {{
            background: #e8f5e9;
            color: #1b5e20;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            border: 1px solid #c8e6c9;
        }}
        .source-badge {{
            background: #f1f5f9;
            color: #374151;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            border: 1px solid #e5e7eb;
        }}
        .heat-badge {{
            background: #fff7ed;
            color: #c2410c;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            border: 1px solid #fed7aa;
        }}
        .rank-badge.small {{
            width: 20px; height: 20px; line-height: 20px; font-size: 12px;
        }}
        .stock-tags {{
            margin-top: 8px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .stock-tag {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #f8fafc;
            border: 1px solid #e5e7eb;
            color: #374151;
            border-radius: 16px;
            padding: 4px 8px;
            font-size: 12px;
        }}
        .stock-tag.muted {{
            background: #f9fafb;
            color: #6b7280;
            border-style: dashed;
        }}

        /* 漏斗图样式（对齐股票分析报告的现代风格） */
        .funnel-container {{
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px 0;
        }}

        .funnel-stage {{
            position: relative;
            margin: 10px 0;
            text-align: center;
            transition: all 0.3s ease;
        }}

        .funnel-bar {{
            background: linear-gradient(90deg, #667eea, #764ba2);
            border-radius: 12px;
            padding: 18px 24px;
            color: white;
            font-weight: 600;
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.25);
            clip-path: polygon(0 0, 100% 0, 95% 100%, 5% 100%);
        }}

        .funnel-stage:hover .funnel-bar {{
            box-shadow: 0 6px 25px rgba(102, 126, 234, 0.5);
            transform: scale(1.02);
        }}

        .funnel-label {{
            font-size: 16px;
            margin-bottom: 5px;
        }}

        .funnel-count {{
            font-size: 24px;
            font-weight: bold;
            text-shadow: 0 1px 2px rgba(0,0,0,0.25);
        }}

        /* 漏斗阶段配色 */
        .funnel-bar.stage-0 {{ background: linear-gradient(90deg, #a18cd1, #fbc2eb); }}
        .funnel-bar.stage-1 {{ background: linear-gradient(90deg, #43e97b, #38f9d7); }}
        .funnel-bar.stage-2 {{ background: linear-gradient(90deg, #4facfe, #00f2fe); }}
        .funnel-bar.stage-3 {{ background: linear-gradient(90deg, #f6d365, #fda085); }}
        .funnel-bar.stage-4 {{ background: linear-gradient(90deg, #fa709a, #fee140); }}
        .funnel-bar.stage-5 {{ background: linear-gradient(90deg, #f093fb, #f5576c); }}

        /* TOP列表容器，默认显示约10行并允许滚动 */
        .top-table-container {{
            max-height: 540px;
            overflow-y: auto;
            border-radius: 12px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.25);
            border: 1px solid var(--border-primary);
            background: var(--secondary-bg);
        }}

        /* TOP 10 表格 */
        .top10-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}

        .top10-table th {{
            background: var(--tertiary-bg);
            color: var(--text-secondary);
            padding: 12px;
            text-align: left;
            font-weight: 600;
            font-size: 13px;
            border-bottom: 1px solid var(--border-primary);
            position: sticky;
            top: 0;
            z-index: 5;
        }}

        .top10-table td {{
            padding: 12px;
            border-bottom: 1px solid var(--border-primary);
            font-size: 13px;
            color: var(--text-primary);
        }}

        .top10-table tr {{ height: 48px; }}

        .top10-table tr:hover {{
            background-color: rgba(100, 181, 246, 0.08);
        }}

        .rank-badge {{
            display: inline-block;
            width: 30px;
            height: 30px;
            line-height: 30px;
            border-radius: 50%;
            text-align: center;
            font-weight: bold;
            color: white;
        }}

        .rank-1 {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }}
        .rank-2 {{ background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }}
        .rank-3 {{ background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); }}
        .rank-other {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}

        .rating-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 12px;
        }}

        .rating-S {{ background: #ff6b6b; color: white; }}
        .rating-A-plus {{ background: #ee5a6f; color: white; }}
        .rating-A {{ background: #4ecdc4; color: white; }}
        .rating-B {{ background: #95e1d3; color: #333; }}
        .rating-C {{ background: #dddddd; color: #333; }}

        .score-bar {{
            width: 100%;
            height: 8px;
            background: #eee;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 5px;
        }}

        .score-fill {{
            height: 100%;
            background: #3b82f6;
            border-radius: 4px;
            transition: width 0.5s ease;
        }}

        /* 分组股票列表 */
        .group-section {{
            margin-bottom: 30px;
        }}

        .group-header {{
            background: #f0f3f8;
            color: #222;
            padding: 15px 20px;
            border-radius: 10px;
            margin-bottom: 15px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            user-select: none;
            transition: all 0.3s ease;
            border: 1px solid #e9edf3;
        }}

        .group-header:hover {{
            transform: translateX(3px);
            box-shadow: none;
            border-color: #d9dfeb;
        }}

        .group-header .count {{
            float: right;
            background: rgba(255, 255, 255, 0.2);
            padding: 2px 12px;
            border-radius: 15px;
            font-size: 14px;
        }}

        .stock-list {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}

        .stock-card {{
            background: var(--card-bg);
            border: 1px solid #eee;
            border-radius: 10px;
            padding: 15px;
            transition: all 0.3s ease;
        }}

        .stock-card:hover {{
            border-color: #667eea;
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.15);
            transform: translateY(-3px);
        }}

        .stock-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}

        .stock-name {{
            font-size: 16px;
            font-weight: 600;
            color: var(--card-text-primary);
        }}

        .stock-code {{
            font-size: 12px;
            color: var(--card-text-muted);
            margin-left: 8px;
        }}

        .filter-brief {{
            font-size: 12px;
            color: var(--card-text-secondary);
            margin-top: 4px;
        }}

        .filter-history {{
            margin-top: 10px;
        }}

        /* 每个阶段的维度元信息（合并到阶段卡片，替代顶部摘要） */
        .stage-meta {{
            font-size: 12px;
            color: var(--card-text-secondary);
            margin-top: 4px;
        }}

        .filter-stage {{
            padding: 8px 10px;
            margin: 5px 0;
            border-radius: 5px;
            font-size: 13px;
            background: #f8f9ff;
            border-left: 3px solid #667eea;
        }}

        .filter-stage.passed {{
            border-left-color: #4ecdc4;
        }}

        .filter-stage.failed {{
            border-left-color: #ff6b6b;
        }}

        .stage-name {{
             color: #333;
            font-weight: 600;
            margin-bottom: 3px;
        }}

        .stage-reason {{
            font-size: 12px;
            color: var(--card-text-secondary);
            line-height: 1.5;
        }}

        /* AI分析卡片样式 */
        .ai-analysis-card {{
            margin-top: 12px;
            padding: 12px;
            background: linear-gradient(135deg, #f8faff 0%, #f0f7ff 100%);
            border: 1px solid #e0e8f0;
            border-radius: 8px;
        }}
        .ai-card-title {{
            font-size: 13px;
            font-weight: 600;
            color: #4a5568;
            margin-bottom: 8px;
        }}
        .ai-model-section {{
            margin-bottom: 8px;
            padding: 8px;
            background: white;
            border-radius: 6px;
            border: 1px solid #e5e7eb;
        }}
        .ai-model-badge {{
            display: inline-block;
            padding: 2px 8px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 11px;
            font-weight: 600;
            border-radius: 12px;
            margin-bottom: 6px;
        }}
        .ai-metrics-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 4px;
        }}
        .ai-action {{
            display: inline-block;
            padding: 2px 10px;
            font-size: 12px;
            font-weight: 600;
            border-radius: 4px;
        }}
        .ai-action.action-buy {{ background: #dcfce7; color: #166534; }}
        .ai-action.action-sell {{ background: #fee2e2; color: #991b1b; }}
        .ai-action.action-hold {{ background: #fef3c7; color: #92400e; }}
        .ai-metric {{
            font-size: 11px;
            color: #4b5563;
            background: #f3f4f6;
            padding: 2px 6px;
            border-radius: 4px;
        }}
        .ai-risk {{
            display: inline-block;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 500;
            border-radius: 4px;
        }}
        .ai-risk.risk-low {{ background: #dcfce7; color: #166534; }}
        .ai-risk.risk-medium {{ background: #fef3c7; color: #92400e; }}
        .ai-risk.risk-high {{ background: #fee2e2; color: #991b1b; }}
        .ai-strategy {{
            font-size: 11px;
            color: #4b5563;
            margin-top: 4px;
            padding: 4px 6px;
            background: #f9fafb;
            border-radius: 4px;
        }}
        .ai-summary {{
            font-size: 12px;
            color: #374151;
            margin-top: 6px;
            padding: 6px 8px;
            background: #fffbeb;
            border-left: 3px solid #f59e0b;
            border-radius: 4px;
        }}
        /* TOP表格中的AI简短分析样式 */
        .ai-brief {{
            margin-top: 6px;
            padding: 4px 8px;
            background: linear-gradient(135deg, #f0f7ff 0%, #e8f4f8 100%);
            border: 1px solid #d0e8f0;
            border-radius: 6px;
            font-size: 11px;
            color: #374151;
        }}
        .ai-tag {{
            display: inline-block;
            padding: 1px 6px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 10px;
            font-weight: 600;
            border-radius: 8px;
            margin-right: 6px;
        }}

        .footer {{
            background: var(--card-bg);
            border-radius: 15px;
            padding: 20px;
            text-align: center;
            color: var(--card-text-muted);
            font-size: 14px;
            margin-top: 30px;
        }}

        @media (max-width: 768px) {{
            .summary-cards {{
                grid-template-columns: 1fr;
            }}

            .stock-list {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
  
        <!-- 已移除筛选漏斗以节省空间并聚焦核心内容 -->

        <!-- 热门新闻/话题精选（动态标题） -->
        <div class="section">
            <div class="section-title">{hot_news_title or '🔥 全市场最热新闻精选'}</div>
            <div class="hot-news-list">
                {hot_news_html}
            </div>
        </div>

        {sector_section_html}

        <!-- TOP 推荐（默认展示10个，支持滚动到末尾） -->
        <div class="section">
            <div class="section-title">⭐ TOP 投资机会</div>
            <div class="top-table-container">
            <table class="top10-table">
                <thead>
                    <tr>
                        <th>排名</th>
                        <th>股票</th>
                        <th>评级</th>
                        <th>综合得分</th>
                        <th>描述</th>
                        <th>建议</th>
                    </tr>
                </thead>
                <tbody>
'''

        for i, stock in enumerate(top_20, 1):
            rank_class = f"rank-{i}" if i <= 3 else "rank-other"
            rating = stock.get('rating', 'C')
            rating_class = f"rating-{rating.replace('+', '-plus')}"
            score = stock.get('final_score', 0)

            # 为TOP表格生成简短分析
            analysis_brief = self._build_short_analysis(stock)

            # 生成AI简短分析（如果有LLM分析结果）
            ai_brief = self._build_ai_brief_for_table(stock)

            html += f'''
                    <tr>
                        <td><span class="rank-badge {rank_class}">{i}</span></td>
                        <td>
                            <strong>{stock.get('name', '未知')}</strong>
                            <span class="stock-code">({stock.get('stock_code', '')})</span>
                            <div class="filter-brief">筛选结果: {'全部通过' if stock.get('eliminated_at_stage', 0) in (0, None) else f"阶段{stock.get('eliminated_at_stage')}淘汰"}</div>
                        </td>
                        <td><span class="rating-badge {rating_class}">{rating}</span></td>
                        <td>
                            {score:.2f} 分
                            <div class="score-bar">
                                <div class="score-fill" style="width: {score}%;"></div>
                            </div>
                        </td>
                        <td>{analysis_brief}{ai_brief}</td>
                        <td>{self._get_recommendation_text(rating)}</td>
                    </tr>
'''

        html += '''
                </tbody>
            </table>
            </div>
        </div>
'''

        # 已移除单独的LLM智能分析版块，AI分析结果已整合到每只股票卡片中

        html += '''
        <!-- 所有股票分组 -->
        <div class="section">
            <div class="section-title">📋 完整筛选结果</div>
'''

        # 通过筛选的股票
        html += self._generate_group_html("通过所有筛选", grouped_stocks['passed'], is_passed=True)

        # 各阶段淘汰的股票
        stage_names = {
            'stage1': '阶段1: 量化模型筛选 - 淘汰',
            'stage2': '阶段2: 技术面筛选 - 淘汰',
            'stage3': '阶段3: 情绪面筛选 - 淘汰',
            'stage4': '阶段4: 基本面筛选 - 淘汰'
        }

        for stage_key, stage_name in stage_names.items():
            html += self._generate_group_html(stage_name, grouped_stocks[stage_key], is_passed=False)

        html += '''
        </div>

        <!-- 页脚 -->
        <div class="footer">
            <p>📈 基于深度学习的金融预测系统</p>
            <p>本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。</p>
        </div>
    </div>

    <script>
        // 点击分组标题展开/收起
        document.querySelectorAll('.group-header').forEach(header => {
            header.addEventListener('click', function() {
                const content = this.nextElementSibling;
                if (content.style.display === 'none') {
                    content.style.display = 'grid';
                } else {
                    content.style.display = 'none';
                }
            });
        });

        // 页面加载动画
        window.addEventListener('load', function() {
            const scoreFills = document.querySelectorAll('.score-fill');
            scoreFills.forEach((fill, index) => {
                setTimeout(() => {
                    fill.style.width = fill.style.width;
                }, index * 50);
            });
        });
    </script>
</body>
</html>
'''

        return html

    def _build_full_indicator_summary(self, stock: Dict) -> str:
        try:
            scoring = stock.get('scoring_result') or {}
            scores = scoring.get('scores') or {}
            details = scoring.get('details') or {}

            code = stock.get('stock_code') or stock.get('code') or ''
            rating = stock.get('rating') or scoring.get('rating') or 'C'
            passed = stock.get('passed', False)
            eliminated = stock.get('eliminated_at_stage', 0)

            # 辅助格式化
            def _fmt(v, default='—'):
                if isinstance(v, float):
                    return f"{v:.2f}"
                return str(v) if v is not None and v != '' else default
            def _fmt_pct(v, digits=1):
                try:
                    return f"{float(v):+.{digits}f}%" if v is not None else '—'
                except: return '—'
            def _fmt_score(v):
                try:
                    return f"{float(v):.0f}" if isinstance(v, (int,float)) else '0'
                except: return '0'
            
            # 1. 板块
            sec = details.get('sector') or {}
            sector_name = sec.get('sector_name') or '未知'
            sec_chg = _fmt_pct(sec.get('change_pct'))
            sec_turn = _fmt_pct(sec.get('turnover_rate'))
            sec_overall = sec.get('overall') or '中性'
            sec_score = scores.get('sector')
            
            # 判断板块数据是否有效：如果板块未知，或者涨跌和换手都是0.0%且分数为50，则认为无效
            is_valid_sector = True
            if sector_name == '未知' or (sec.get('change_pct') == 0 and sec.get('turnover_rate') == 0 and sec_score == 50):
                is_valid_sector = False
                
            sec_str = f"{sector_name}({sec_chg}, 换手{sec_turn}, {sec_overall}, {_fmt_score(sec_score)}分)"

            # 2. 量化
            qd = details.get('quantitative') or {}
            buy_count = qd.get('buy_count') or 0
            sell_count = qd.get('sell_count') or 0
            total_count = qd.get('total_count') or 0
            buy_ratio = qd.get('buy_ratio')
            buy_pct = f"{int(round(float(buy_ratio)*100))}%" if buy_ratio is not None else '—'
            quant_score = scores.get('quantitative')
            
            models = qd.get('top_buy_models') or []
            MODEL_DISPLAY_MAP = {
                'balance_dual_moving': '均衡双均线',
                'multi_breakthrough': '多重突破',
                'support_resistance': '支撑阻力',
                'trend_pullback': '趋势回踩',
                'ma_resonance': '均线共振',
                'super_reversal': '超级反转',
                'capital_trend': '资金趋势',
                'volume_breakthrough': '量能突破',
                'three_sisters': '三姐妹形态',
                'macd_axis_golden_cross': '轴心MACD金叉',
                'six_dimension_resonance': '六维共振',
                'statistical_quantitative': '统计量化',
                'super_profit_limit_up': '超额涨停',
                'turtle_trading_system': '海龟交易',
                'atr_momentum': 'ATR动量',
                'cta_trend_strategy': 'CTA趋势',
                'machine_learning_rf': '机器学习RF',
                'multi_factor_alpha': '多因子Alpha',
                'pairs_trading_arbitrage': '配对交易套利',
                'hft_microstructure': '高频微结构',
                'ichimoku_cloud': '一目均衡云',
                'bollinger_squeeze': '布林收敛',
                'rsi_divergence': 'RSI背离',
                'stochastic_momentum': '随机动量',
                'volume_price_trend': '量价趋势',
                'parabolic_sar': '抛物转向SAR',
                'chaikin_money_flow': '切金资金流',
                'elder_ray': 'Elder射线',
                'vwap_deviation': 'VWAP偏离',
                'fractal_adaptive_ma': '分形自适应均线'
            }
            model_names = '、'.join([MODEL_DISPLAY_MAP.get(m, m) for m in models[:3]]) if models else '无'
            quant_str = f"买{buy_count}/卖{sell_count}/总{total_count}({buy_pct})，{_fmt_score(quant_score)}分，模型[{model_names}]"

            # 3. 技术
            tech = details.get('technical') or {}
            tech_score = scores.get('technical')
            rsi = _fmt(tech.get('RSI'), '—')
            macd = _fmt(tech.get('MACD'), '—')
            boll = _fmt(tech.get('Bollinger'), '—')
            tech_str = f"RSI:{rsi}，MACD:{macd}，布林:{boll}，{_fmt_score(tech_score)}分"

            # 4. 基本面
            fd = details.get('fundamental') or {}
            fund_score = scores.get('fundamental')
            pe = _fmt(fd.get('pe_ratio'), '—')
            rev = _fmt_pct(fd.get('revenue_yoy'))
            prof = _fmt_pct(fd.get('net_profit_yoy'))
            # fund_str = f"PE:{pe}，营收:{rev}，利润:{prof}，{_fmt_score(fund_score)}分"
            fund_str = f"营收:{rev}，利润:{prof}，{_fmt_score(fund_score)}分"

            # 5. 情绪 & 资金
            sd = details.get('sentiment') or {}
            sent_score = scores.get('sentiment')
            inv_sent = sd.get('comprehensive_sentiment') or '中性'
            
            cf = sd.get('capital_flow') or {}
            cf_trend = cf.get('trend') or '—'
            cf_str = cf.get('strength') or '—'
            cf_amt = _fmt_money(cf.get('main_inflow'))
            
            dt = sd.get('dragon_tiger') or {}
            dt_signal = dt.get('last_signal') or '—'
            dt_date = dt.get('last_date')
            dt_net = _fmt_money(dt.get('net_buy_amount'))

            cf_parts = []
            has_cf_trend = cf_trend not in ('—', '未知', None)
            has_cf_strength = cf_str not in ('—', '未知', None)
            has_cf_amt = cf_amt not in ('—', '+0.00')
            if has_cf_trend or has_cf_strength or has_cf_amt:
                amt_str = f", 净额{cf_amt}" if has_cf_amt else ""
                strength_str = cf_str if has_cf_strength else "—"
                cf_parts.append(f"资金:{cf_trend}({strength_str}{amt_str})")

            dt_parts = []
            valid_dt_date = bool(dt_date) and str(dt_date) != 'N/A'
            valid_dt_net = dt_net not in ('—', None)
            valid_dt_signal = dt_signal not in ('—', '中性', None)
            if valid_dt_date or valid_dt_net or valid_dt_signal:
                date_str = f"({dt_date})" if valid_dt_date else ""
                net_str = f"(净额{dt_net})" if valid_dt_net else ""
                signal_str = dt_signal if dt_signal else '—'
                dt_parts.append(f"龙虎榜:{signal_str}{net_str}{date_str}")

            sent_subparts = []
            if cf_parts:
                sent_subparts.append(cf_parts[0])
            if dt_parts:
                sent_subparts.append(dt_parts[0])
            if sent_subparts:
                sent_str = f"情绪:{inv_sent}，" + "，".join(sent_subparts) + f"，{_fmt_score(sent_score)}分"
            else:
                sent_str = f"情绪:{inv_sent}，{_fmt_score(sent_score)}分"

            # 6. 事件
            ed = details.get('events') or {}
            ev_score = scores.get('events')
            pos = ed.get('positive_events') or 0
            neg = ed.get('negative_events') or 0
            ev_rating = ed.get('rating') or '中性'
            events_str = f"评级:{ev_rating}，利好{pos}/利空{neg}，{_fmt_score(ev_score)}分"

            suggestion = self._get_recommendation_text(rating)
            filter_res = '' if eliminated in (0, None) else f'阶段{eliminated}淘汰'

            # 获取涨幅数据
            price_changes = stock.get('scoring_result', {}).get('details', {}).get('price_changes', {})
            change_1d = price_changes.get('change_1d') if price_changes else None
            change_3d = price_changes.get('change_3d') if price_changes else None
            change_5d = price_changes.get('change_5d') if price_changes else None
            sector_chg = sec.get('change_pct', 0)

            change_1d_str = f"{change_1d:+.2f}%" if change_1d is not None else "—"
            change_3d_str = f"{change_3d:+.2f}%" if change_3d is not None else "—"
            change_5d_str = f"{change_5d:+.2f}%" if change_5d is not None else "—"
            sector_chg_str = f"{sector_chg:+.2f}%" if sector_chg is not None else "—"

            overview = f"【概览】评级{rating}，建议：{suggestion}<br>【涨幅】当日:{change_1d_str}，3日:{change_3d_str}，5日:{change_5d_str}"
            if filter_res:
                overview = f"【概览】评级{rating}，{filter_res}，建议：{suggestion}<br>【涨幅】当日:{change_1d_str}，3日:{change_3d_str}，5日:{change_5d_str}"

            parts = [overview]
            
            # 仅在数据有效时展示板块信息
            if is_valid_sector:
                parts.append(f"【板块】{sec_str}")
                
            parts.extend([
                f"【量化】{quant_str}",
                f"【技术】{tech_str}",
                f"【基本面】{fund_str}",
                f"【情绪资金】{sent_str}",
                f"【消息】{events_str}"
            ])

            # 新增：入选原因与最新动态
            reason = _generate_selection_reason(stock)
            parts.append(f"【入选原因】{reason if reason else '无'}")
            
            latest_news = stock.get('latest_news')
            if latest_news:
                def _valid_title(t: str) -> bool:
                    if not t:
                        return False
                    ts = t.strip()
                    if len(ts) < 8:
                        return False
                    bad_keywords = ['上交所', '深交所', '证券交易所']
                    if any(bk in ts for bk in bad_keywords) and len(ts) < 20:
                        return False
                    return True

                titles = []
                for n in latest_news:
                    t = n.get('title', '')
                    if _valid_title(t):
                        titles.append(t)
                    if len(titles) >= 2:
                        break

                if titles:
                    news_str = "; ".join(titles)
                    parts.append(f"【最新动态】{news_str}")

            return '<br>'.join(parts)
        except Exception as e:
            total = stock.get('final_score') or (scoring.get('total_score') if 'scoring_result' in stock else 0)
            return f"综合{float(total or 0):.2f}分；数据解析错误: {str(e)}"

    def _build_advanced_analysis_summary(self, stock: Dict) -> str:
        """生成高级分析摘要（用于Markdown表格）"""
        try:
            parts = []
            scoring_result = stock.get('scoring_result') or {}
            details = scoring_result.get('details') or {}
            advanced = stock.get('advanced_analysis') or scoring_result.get('advanced_analysis') or {}
            
            # 1. 追高风险 (来自 details.momentum)
            momentum = details.get('momentum') or {}
            chase_risk = momentum.get('chase_risk_level', '')
            chase_score = momentum.get('chase_risk_score', 0)
            if chase_risk:
                risk_emoji = {'low': '🟢', 'low_medium': '🟡', 'medium': '🟠', 'high': '🔴'}.get(chase_risk, '⚪')
                risk_cn = {'low': '低', 'low_medium': '中低', 'medium': '中等', 'high': '偏高'}.get(chase_risk, chase_risk)
                safe_score = max(0, min(100, float(chase_score or 0)))
                parts.append(f"**追高风险**: {risk_emoji} {risk_cn}({safe_score:.0f}分)")

            # 2. 量价形态 (来自 details.volume_health)
            volume_health = details.get('volume_health') or {}
            patterns = volume_health.get('patterns') or {}
            if patterns:
                p_list = []
                for p_type, p_data in patterns.items():
                    if isinstance(p_data, dict) and p_data.get('detected'):
                        days = p_data.get('consecutive_days', 0)
                        p_name = {'vol_up_price_up': '放量上涨', 'vol_down_price_down': '缩量下跌', 
                                 'vol_up_price_down': '放量下跌', 'vol_down_price_up': '缩量上涨'}.get(p_type, p_type)
                        p_list.append(f"{p_name}({days}天)")
                if p_list:
                    parts.append(f"**量价**: {', '.join(p_list)}")

            # 3. 高级分析维度 (来自 advanced_analysis)
            if advanced:
                # 兼容两种结构：直接中文Key(旧) 或 English Key(新)
                
                # 3.1 综合评分
                adv_score = 0
                if 'overall_score' in advanced:
                    adv_score = advanced['overall_score'].get('final_score', 0)
                else:
                    adv_score = advanced.get('综合评分', 0)
                
                parts.append(f"**高级评分**: {adv_score:.1f}分")
                
                dimensions = advanced.get('dimensions', {})
                
                # 3.2 筹码 (Chip)
                chip = dimensions.get('chip', {}).get('details', {}) or advanced.get('筹码分析', {})
                if chip:
                    conc = chip.get('concentration_90') or chip.get('90%筹码集中度', 0)
                    control = chip.get('main_force_control') or chip.get('主力控盘度', 0)
                    lock_raw = chip.get('lock_pattern') or chip.get('锁仓形态')
                    lock_str = ''
                    if isinstance(lock_raw, dict):
                         if lock_raw.get('detected'):
                             lock_str = f"🔒 {lock_raw.get('type', '锁仓')}"
                    elif isinstance(lock_raw, str):
                        lock_str = lock_raw
                    
                    chip_parts = []
                    if conc: chip_parts.append(f"集中度{conc:.1f}%")
                    if control: chip_parts.append(f"控盘{control:.1f}") # 控盘度可能是0-1或0-100，这里假设是数值
                    if lock_str and lock_str != '无': chip_parts.append(lock_str)
                    
                    if chip_parts:
                        parts.append(f"**筹码**: {', '.join(chip_parts)}")
                
                # 3.3 板块 (Sector)
                sector = dimensions.get('sector', {}).get('details', {}) or advanced.get('板块联动', {})
                if sector:
                    s_name = sector.get('sector_name') or sector.get('所属板块', '')
                    s_rank = sector.get('sector_rank') or sector.get('板块排名', 0)
                    s_rot = sector.get('rotation_phase') or sector.get('轮动阶段', '')
                    
                    sec_parts = []
                    if s_name: sec_parts.append(f"{s_name}(排名{s_rank})")
                    if s_rot and s_rot != 'unknown': sec_parts.append(s_rot)
                    
                    if sec_parts:
                        parts.append(f"**板块**: {', '.join(sec_parts)}")

                # 3.4 资金 (Capital)
                capital = dimensions.get('capital_flow', {}).get('details', {}) or advanced.get('资金流向', {})
                if capital:
                    cont_dict = capital.get('continuity', {})
                    main_cont = cont_dict.get('consecutive_inflow_days', 0) if isinstance(cont_dict, dict) else capital.get('主力连续性', 0)
                    cont_trend = cont_dict.get('trend', '') if isinstance(cont_dict, dict) else capital.get('trend', '')
                    retail = capital.get('retail_ratio') or capital.get('散户占比', 0)

                    def _infer_main_force_direction() -> str:
                        trend_val = ''
                        if isinstance(cont_trend, str):
                            trend_val = cont_trend.strip().lower()
                        elif cont_trend is not None:
                            trend_val = str(cont_trend).strip().lower()

                        if trend_val:
                            if any(k in trend_val for k in ['inflow', 'in_flow', 'net_in', 'in', 'buy', 'long', 'positive', '流入', '净流入', '买入']):
                                return '买入'
                            if any(k in trend_val for k in ['outflow', 'out_flow', 'net_out', 'out', 'sell', 'short', 'negative', '流出', '净流出', '卖出']):
                                return '卖出'

                        for k in ['main_net_inflow', 'main_force_net_inflow', 'net_inflow', '主力净流入', '主力资金净流入']:
                            if k in capital:
                                try:
                                    v = float(capital.get(k) or 0)
                                    if v > 0:
                                        return '买入'
                                    if v < 0:
                                        return '卖出'
                                except Exception:
                                    pass

                        if isinstance(cont_dict, dict):
                            inflow_days = cont_dict.get('consecutive_inflow_days', 0) or cont_dict.get('inflow_days', 0) or 0
                            outflow_days = cont_dict.get('consecutive_outflow_days', 0) or cont_dict.get('outflow_days', 0) or 0
                            try:
                                inflow_days = int(inflow_days)
                            except Exception:
                                inflow_days = 0
                            try:
                                outflow_days = int(outflow_days)
                            except Exception:
                                outflow_days = 0
                            if inflow_days > 0 and outflow_days <= 0:
                                return '买入'
                            if outflow_days > 0 and inflow_days <= 0:
                                return '卖出'
                        return ''
                    
                    cap_parts = []
                    if main_cont > 0:
                        direction = _infer_main_force_direction()
                        direction_str = f"({direction})" if direction else ""
                        cap_parts.append(f"主力连续{main_cont}天{direction_str}")
                    if retail > 0 and abs(retail - 50.0) > 0.1: cap_parts.append(f"散户{retail:.1f}%")
                    
                    if cap_parts:
                        parts.append(f"**资金**: {', '.join(cap_parts)}")

                # 3.5 情绪 (Sentiment)
                sent_dim = dimensions.get('sentiment_cycle', {})
                sent_details = sent_dim.get('details', {})
                # 旧版可能直接在 sent_dim 或 advanced.get('情绪周期')
                
                market_cycle = sent_details.get('market_cycle') or advanced.get('情绪周期', {}).get('市场周期', '')
                fg_index = sent_details.get('fear_greed_index') or advanced.get('情绪周期', {}).get('恐惧贪婪指数', 0)
                
                if market_cycle or fg_index:
                    parts.append(f"**情绪**: {market_cycle or '-'}, 恐贪{fg_index:.0f}")

                # 3.6 分时 (Intraday)
                intra = dimensions.get('intraday', {}).get('details', {}) or advanced.get('分时特征', {})
                if intra:
                    manip = intra.get('manipulation', {})
                    manip_type = manip.get('type') if isinstance(manip, dict) else intra.get('操盘痕迹', '')
                    if manip_type:
                        parts.append(f"**分时**: {manip_type}")

                # 3.7 K线形态 (Patterns)
                # pattern_detector returns {'patterns': {'detected_patterns': [...]}} usually
                pats_dim = dimensions.get('patterns', {})
                pats_list = pats_dim.get('details', {}).get('detected_patterns', []) or advanced.get('K线形态', {}).get('识别形态', [])
                if pats_list:
                    # pats_list 可能是 [{'name': '...'}, ...] 或 ['...', ...]
                    pat_names = []
                    for p in pats_list:
                        if isinstance(p, dict):
                            pat_names.append(p.get('name', ''))
                        elif isinstance(p, str):
                            pat_names.append(p)
                    if pat_names:
                        parts.append(f"**形态**: {', '.join(pat_names[:2])}")
                
            return ' '.join(parts) if parts else "—"
        except Exception as e:
            return f"解析错误: {str(e)}"

    def _generate_group_html(self, group_name: str, stocks: List[Dict], is_passed: bool) -> str:
        """生成分组HTML"""
        if not stocks:
            return ""

        status_icon = "✓" if is_passed else "✗"
        html = f'''
            <div class="group-section">
                <div class="group-header">
                    {status_icon} {group_name}
                    <span class="count">{len(stocks)} 只</span>
                </div>
                <div class="stock-list">
'''

        for stock in stocks:
            rating = stock.get('rating', 'C')
            rating_class = f"rating-{rating.replace('+', '-plus')}"
            score = stock.get('final_score', 0)
            scoring_result = stock.get('scoring_result', {})
            scores = (scoring_result.get('scores') or {})
            weights_used = (scoring_result.get('weights_used') or {})

            def wpct(key):
                w = weights_used.get(key)
                return f"{int(round(w*100))}%" if isinstance(w, (int, float)) else "-"

            # 安全格式化工具
            def _fmt_float(val, digits=1, default='未知', signed=False):
                try:
                    if val is None or (isinstance(val, str) and val.strip() == ''):
                        return default
                    v = float(val)
                    return f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
                except Exception:
                    return str(val) if val is not None else default

            def _fmt_pct(val, digits=2, default='未知', signed=True):
                s = _fmt_float(val, digits=digits, default=default, signed=signed)
                return s + '%' if s and s != default else default

            # 量化统计
            qd = (scoring_result.get('details', {}).get('quantitative') or {})
            buy = qd.get('buy_count', None)
            sell = qd.get('sell_count', None)
            total = qd.get('total_count', None)
            buy_ratio = qd.get('buy_ratio', None)
            buy_ratio_pct = None
            if isinstance(buy_ratio, (int, float)):
                try:
                    buy_ratio_pct = f"{int(round(buy_ratio*100))}%"
                except Exception:
                    buy_ratio_pct = None

            # 技术指标
            td = (scoring_result.get('details', {}).get('technical') or {})
            rsi = td.get('RSI', None)
            macd = td.get('MACD', None)
            boll = td.get('Bollinger', None)
            rsi_str = _fmt_float(rsi, 1, default='未知')
            macd_str = macd if macd else '未知'
            boll_str = boll if boll else '未知'

            # 股民情绪
            sd = (scoring_result.get('details', {}).get('sentiment') or {})
            inv_score = sd.get('comprehensive_score', None)
            inv_sent = sd.get('comprehensive_sentiment', None)
            inv_score_str = _fmt_float(inv_score, 1, default='未知')
            # 新增：资金流与龙虎榜
            cf = sd.get('capital_flow', {}) or {}
            cf_trend = cf.get('trend', None)
            cf_strength = cf.get('strength', None)
            cf_amt = cf.get('main_inflow', None)
            cf_amt_str = _fmt_money(cf_amt)

            dt = sd.get('dragon_tiger', {}) or {}
            dt_signal = dt.get('last_signal', None)
            dt_date = dt.get('last_date', None)

            # 板块情绪
            secd = (scoring_result.get('details', {}).get('sector') or {})
            sec_name = secd.get('sector_name', None)
            sec_chg = secd.get('change_pct', None)
            sec_turn = secd.get('turnover_rate', None)
            sec_overall = secd.get('overall', None)
            sec_chg_str = _fmt_pct(sec_chg, 2, default='')
            sec_turn_str = _fmt_pct(sec_turn, 2, default='')

            # 基本面
            fd = (scoring_result.get('details', {}).get('fundamental') or {})
            pe = fd.get('pe_ratio', None)
            rev = fd.get('revenue_yoy', None)
            prof = fd.get('net_profit_yoy', None)
            pe_str = _fmt_float(pe, 1, default='未知')
            rev_str = _fmt_pct(rev, 1, default='未知')
            prof_str = _fmt_pct(prof, 1, default='未知')

            # 消息面
            ed = (scoring_result.get('details', {}).get('events') or {})
            ev_rating = ed.get('rating', None)
            ev_pos = ed.get('positive_events', None)
            ev_neg = ed.get('negative_events', None)

            html += f'''
                    <div class="stock-card">
                        <div class="stock-header">
                            <div>
                                <span class="stock-name">{stock.get('name', '未知')}</span>
                                <span class="stock-code">{stock.get('stock_code', '')}</span>
                            </div>
                            <div>
                                <span class="rating-badge {rating_class}">{rating}</span>
                                <span style="margin-left: 8px; font-weight: 600; color: #667eea;">{score:.1f}分</span>
                            </div>
                        </div>
                        <!-- 维度分数与权重摘要 -->
                        <div class="filter-history">
'''

            # 显示筛选历程
            for stage in stock.get('filter_history', []):
                status_class = "passed" if stage['passed'] else "failed"
                status_icon = "✓" if stage['passed'] else "✗"
                # 从阶段名称解析阶段号（如“阶段1: ...”）
                stage_num = None
                try:
                    name_str = str(stage.get('stage_name', ''))
                    for ch in name_str:
                        if ch.isdigit():
                            stage_num = int(ch)
                            break
                except Exception:
                    stage_num = None

                name_str = str(stage.get('stage_name', ''))
                if stage_num == 5:
                    continue

                # 构造合并后的维度元信息
                meta = ''
                if stage_num == 1:
                    meta = f"维度得分 {scores.get('quantitative', 0):.1f}分 · 权重 {wpct('quantitative')} · 买 {'' if buy is None else buy}/{'' if total is None else total} · 卖 {'' if sell is None else sell}{'' if not buy_ratio_pct else f' · 买比例 {buy_ratio_pct}'}"
                elif stage_num == 2:
                    meta = f"维度得分 {scores.get('technical', 0):.1f}分 · 权重 {wpct('technical')} · RSI {rsi_str} · MACD {macd_str} · 布林 {boll_str}"
                elif stage_num == 3:
                    meta = (
                        f"股民 {scores.get('sentiment', 0):.1f}分 · 权重 {wpct('sentiment')} · 综情 {inv_score_str} · {inv_sent or '中性'}"
                        f" · 资金 {cf_trend or '未知'}({cf_strength or '未知'}) · 净额 {cf_amt_str}；"
                        f"板块 {scores.get('sector', 0):.1f}分 · 权重 {wpct('sector')} · {sec_name or '所属板块'} {sec_chg_str} · 换手 {sec_turn_str} · {sec_overall or '中性'}"
                        f" · 龙虎榜 {dt_signal or '中性'}(净额{_fmt_money(dt.get('net_buy_amount'))}){'' if not dt_date else f'({dt_date})'}"
                    )
                elif stage_num == 4:
                    meta = f"维度得分 {scores.get('fundamental', 0):.1f}分 · 权重 {wpct('fundamental')} · PE {pe_str} · 营收 {rev_str} · 利润 {prof_str}"
                elif stage_num == 5:
                    meta = f"维度得分 {scores.get('events', 0):.1f}分 · 权重 {wpct('events')} · 评级 {ev_rating or '中性'} · 利好 {'' if ev_pos is None else ev_pos} · 利空 {'' if ev_neg is None else ev_neg}"

                meta_html = f'<div class="stage-meta">{meta}</div>' if meta else ''

                html += f'''
                            <div class="filter-stage {status_class}">
                                <div class="stage-name">{status_icon} {stage['stage_name']}</div>
                                <div class="stage-reason">{stage['reason']}</div>
                                {meta_html}
                            </div>
'''

            # 新增：入选原因与最新动态
            selection_reason = _generate_selection_reason(stock)
            latest_news = stock.get('latest_news')
            news_html = ''
            
            if selection_reason or latest_news:
                news_html = '<div class="stock-news-section" style="margin-top: 12px; padding-top: 12px; border-top: 1px dashed #e2e8f0;">'
                
                if selection_reason:
                    news_html += f'<div class="selection-reason" style="margin-bottom: 8px;"><span style="font-weight: 600; color: #4a5568;">🔍 入选原因:</span> <span style="color: #2d3748;">{selection_reason}</span></div>'
                    
                if latest_news:
                    news_html += '<div class="latest-news"><div style="font-weight: 600; color: #4a5568; margin-bottom: 4px;">📰 最新动态:</div>'
                    for news in latest_news[:2]:
                        title = news.get('title', '未知标题')
                        url = news.get('url', '#')
                        date = news.get('publish_time') or news.get('date') or ''
                        if len(date) > 10: date = date[:10]
                        
                        news_html += f'<div style="font-size: 12px; margin-bottom: 4px;"><a href="{url}" target="_blank" style="color: #3182ce; text-decoration: none;">{title}</a> <span style="color: #a0aec0; margin-left: 4px;">{date}</span></div>'
                    news_html += '</div>'
                    
                news_html += '</div>'

            # 在卡片底部添加AI分析结果（如果有）
            ai_analysis_html = self._build_ai_analysis_for_card(stock)

            html += f'''
                        </div>
                        {news_html}
                        {ai_analysis_html}
                    </div>
'''

        html += '''
                </div>
            </div>
'''

        return html

    def _build_ai_brief_for_table(self, stock: Dict) -> str:
        """为TOP表格生成AI简短分析（一行展示）"""
        llm_result = stock.get('llm_analysis')
        if not llm_result:
            return ''

        try:
            # 收集所有有效的模型结果
            valid_results = []
            
            # 1. 尝试作为多模型结果处理：优先按固定顺序检查已知模型
            if isinstance(llm_result, dict):
                for known_model in ['qwen', 'deepseek']:
                    if known_model in llm_result:
                        mr = llm_result[known_model]
                        if isinstance(mr, dict) and 'error' not in mr:
                            valid_results.append((known_model, mr))

            # 2. 如果未找到多模型结果，尝试作为单模型结果处理
            if not valid_results and isinstance(llm_result, dict) and 'operation_advice' in llm_result:
                model_name = llm_result.get('llm_model', 'AI')
                valid_results.append((model_name, llm_result))

            if not valid_results:
                return ''

            html_output = []
            
            # 对每个有效结果生成简短分析 HTML
            for model_name, result in valid_results:
                # 提取关键信息
                operation = result.get('operation_advice', {})
                action = operation.get('action', '')
                position = operation.get('position_control', '')
                confidence = operation.get('confidence', 0)

                risk = result.get('risk_assessment', {})
                risk_level = risk.get('risk_level', '')

                kline = result.get('kline_prediction', {})
                trend = kline.get('trend', '')

                # 构建简短AI分析
                parts = []
                if action:
                    action_icon = '🟢' if action == '买入' else ('🔴' if action == '卖出' else '🟡')
                    parts.append(f"{action_icon}{action}")
                if position:
                    parts.append(f"仓位{position}")
                if trend:
                    parts.append(f"趋势{trend}")
                if risk_level:
                    parts.append(f"{risk_level}风险")
                if confidence:
                    parts.append(f"置信{confidence*100:.0f}%")

                if parts:
                    model_tag = {'qwen': '千问', 'deepseek': 'DS'}.get(model_name, model_name.upper() if len(model_name) <= 3 else 'AI')
                    html_output.append(f'<div class="ai-brief"><span class="ai-tag">{model_tag}</span>{" · ".join(parts)}</div>')

            return "".join(html_output)

        except Exception as e:
            pass

        return ''

    def _build_ai_analysis_for_card(self, stock: Dict) -> str:
        """为股票卡片生成AI分析详情展示"""
        llm_result = stock.get('llm_analysis')
        if not llm_result:
            return ''

        try:
            # 处理多模型或单模型结果
            results_to_show = []
            if any(k in llm_result for k in ['qwen', 'deepseek']):
                for model_name, model_result in llm_result.items():
                    if isinstance(model_result, dict) and 'error' not in model_result:
                        results_to_show.append((model_name, model_result))
            else:
                results_to_show.append((llm_result.get('llm_model', 'AI'), llm_result))

            if not results_to_show:
                return ''

            html_parts = ['<div class="ai-analysis-card">']
            html_parts.append('<div class="ai-card-title">🤖 AI智能分析</div>')

            for model_name, result in results_to_show:
                model_display = {'qwen': '通义千问', 'deepseek': 'DeepSeek'}.get(model_name, model_name.upper() if model_name else 'AI')

                # 操作建议
                operation = result.get('operation_advice', {})
                action = operation.get('action', '-')
                position = operation.get('position_control', '-')
                target = operation.get('target_price', '-')
                stop_loss = operation.get('stop_loss', '-')
                confidence = operation.get('confidence', 0)

                action_class = 'action-buy' if action == '买入' else ('action-sell' if action == '卖出' else 'action-hold')

                # 风险评估
                risk = result.get('risk_assessment', {})
                risk_level = risk.get('risk_level', '-')
                risk_points = risk.get('risk_points', [])
                risk_class = 'risk-low' if risk_level == '低' else ('risk-high' if risk_level == '高' else 'risk-medium')

                # K线预测
                kline = result.get('kline_prediction', {})
                trend = kline.get('trend', '-')
                pred_conf = kline.get('confidence', 0)
                support = kline.get('support_levels', [])
                resistance = kline.get('resistance_levels', [])

                # 策略
                strategy = result.get('strategy', {})
                short_term = strategy.get('short_term', '')

                # 总结
                summary = result.get('summary', '')

                html_parts.append(f'''
                <div class="ai-model-section">
                    <span class="ai-model-badge">{model_display}</span>
                    <div class="ai-metrics-row">
                        <span class="ai-action {action_class}">{action}</span>
                        <span class="ai-metric">仓位: {position}</span>
                        <span class="ai-metric">目标: {target}</span>
                        <span class="ai-metric">止损: {stop_loss}</span>
                        <span class="ai-metric">置信: {confidence*100:.0f}%</span>
                    </div>
                    <div class="ai-metrics-row">
                        <span class="ai-risk {risk_class}">{risk_level}风险</span>
                        <span class="ai-metric">趋势: {trend}</span>
                        <span class="ai-metric">支撑: {", ".join(str(x) for x in support[:2]) if support else "-"}</span>
                        <span class="ai-metric">阻力: {", ".join(str(x) for x in resistance[:2]) if resistance else "-"}</span>
                    </div>
                    {f'<div class="ai-strategy">短线: {short_term[:60]}{"..." if len(short_term) > 60 else ""}</div>' if short_term else ''}
                    {f'<div class="ai-summary">💡 {summary[:80]}{"..." if len(summary) > 80 else ""}</div>' if summary else ''}
                </div>
                ''')

            html_parts.append('</div>')
            return '\n'.join(html_parts)

        except Exception as e:
            return ''

    def _build_short_analysis(self, stock: Dict) -> str:
        """根据评分与细节生成简短分析文本（≤45字）。
        优先展示量化买入模型，其次技术面要点与板块/事件倾向。
        """
        try:
            scoring = stock.get('scoring_result') or {}
            scores = scoring.get('scores') or {}
            details = scoring.get('details') or {}

            phrases = []

            # 量化模型简述（阶段1）
            MODEL_DISPLAY_MAP = {
                'balance_dual_moving': '均衡双均线',
                'multi_breakthrough': '多重突破',
                'support_resistance': '支撑阻力',
                'trend_pullback': '趋势回踩',
                'ma_resonance': '均线共振',
                'super_reversal': '超级反转',
                'capital_trend': '资金趋势',
                'volume_breakthrough': '量能突破',
                'three_sisters': '三姐妹形态',
                'macd_axis_golden_cross': '轴心MACD金叉',
                'six_dimension_resonance': '六维共振',
                'statistical_quantitative': '统计量化',
                'super_profit_limit_up': '超额涨停',
                'turtle_trading_system': '海龟交易',
                'atr_momentum': 'ATR动量',
                'cta_trend_strategy': 'CTA趋势',
                'machine_learning_rf': '机器学习RF',
                'multi_factor_alpha': '多因子Alpha',
                'pairs_trading_arbitrage': '配对交易套利',
                'hft_microstructure': '高频微结构',
                'ichimoku_cloud': '一目均衡云',
                'bollinger_squeeze': '布林收敛',
                'rsi_divergence': 'RSI背离',
                'stochastic_momentum': '随机动量',
                'volume_price_trend': '量价趋势',
                'parabolic_sar': '抛物转向SAR',
                'chaikin_money_flow': '切金资金流',
                'elder_ray': 'Elder射线',
                'vwap_deviation': 'VWAP偏离',
                'fractal_adaptive_ma': '分形自适应均线'
            }

            try:
                for st in stock.get('filter_history', []) or []:
                    if str(st.get('stage_name', '')).startswith('阶段1'):
                        models = (st.get('details', {}) or {}).get('top_buy_models') or (st.get('details', {}) or {}).get('top_models') or []
                        if models:
                            phrases.append('量化: ' + '、'.join([MODEL_DISPLAY_MAP.get(m, m) for m in models[:2]]))
                        break
            except Exception:
                pass

            # 技术面要点
            tech = details.get('technical') or {}
            macd = tech.get('MACD')
            boll = tech.get('Bollinger')
            rsi = tech.get('RSI')
            tech_parts = []
            if isinstance(macd, str) and macd in {'金叉', '死叉'}:
                tech_parts.append(f'MACD{macd}')
            if isinstance(boll, str) and boll in {'下轨附近', '上轨附近', '中轨附近'}:
                tech_parts.append(f'布林{boll}')
            if isinstance(rsi, (int, float)):
                if rsi < 30:
                    tech_parts.append('RSI超卖')
                elif rsi > 70:
                    tech_parts.append('RSI超买')
                elif 40 <= rsi <= 60:
                    tech_parts.append('RSI中性偏多')
            if tech_parts:
                phrases.append('技术: ' + ' · '.join(tech_parts[:2]))

            # 板块与事件倾向
            sector_score = scores.get('sector')
            if isinstance(sector_score, (int, float)):
                if sector_score >= 70:
                    phrases.append('板块景气')
                elif sector_score <= 40:
                    phrases.append('板块偏弱')

            events = details.get('events') or {}
            ev_rating = str(events.get('rating', '')).strip()
            # if ev_rating:
            #     if '利好' in ev_rating:
            #         phrases.append('事件利好')
            #     elif '利空' in ev_rating:
            #         phrases.append('事件利空')
            #     else:
            #         phrases.append('事件中性')

            # 兜底：至少给出综合分与评级
            if not phrases:
                total = scoring.get('total_score', 0)
                rating = scoring.get('rating', 'C')
                phrases = [f'综合{float(total):.1f}分 · {rating}级']

            text = ' · '.join(phrases)
            return (text[:44] + '…') if len(text) > 45 else text
        except Exception:
            total = (stock.get('scoring_result') or {}).get('total_score', 0)
            rating = (stock.get('scoring_result') or {}).get('rating', 'C')
            return f'综合{float(total):.1f}分 · {rating}级'

    def _generate_llm_analysis_section(self, stocks: List[Dict]) -> str:
        """
        生成LLM智能分析版块HTML

        Args:
            stocks: 股票列表（包含llm_analysis字段的股票）

        Returns:
            LLM分析版块的HTML字符串
        """
        # 筛选有LLM分析结果的股票
        llm_stocks = [s for s in stocks if s.get('llm_analysis')]
        if not llm_stocks:
            return ''

        html = '''
        <!-- LLM智能分析 -->
        <div class="section">
            <div class="section-title">🤖 AI智能分析（大模型深度解读）</div>
            <div class="llm-analysis-container">
'''

        for stock in llm_stocks:
            llm_result = stock.get('llm_analysis', {})
            stock_name = stock.get('name', '未知')
            stock_code = stock.get('stock_code', '')
            rating = stock.get('rating', 'C')
            rating_class = f"rating-{rating.replace('+', '-plus')}"

            # 支持多模型聚合结果
            if any(k in llm_result for k in ['qwen', 'deepseek']):
                # 多模型结果
                for model_name, model_result in llm_result.items():
                    if isinstance(model_result, dict) and 'error' not in model_result:
                        html += self._render_single_llm_card(
                            stock_name, stock_code, rating, rating_class,
                            model_result, model_name
                        )
            else:
                # 单模型结果
                model_name = llm_result.get('llm_model', 'AI')
                html += self._render_single_llm_card(
                    stock_name, stock_code, rating, rating_class,
                    llm_result, model_name
                )

        html += '''
            </div>
        </div>
'''
        return html

    def _render_single_llm_card(self, stock_name: str, stock_code: str,
                                 rating: str, rating_class: str,
                                 result: Dict, model_name: str = None) -> str:
        """
        渲染单个LLM分析卡片

        Args:
            stock_name: 股票名称
            stock_code: 股票代码
            rating: 评级
            rating_class: 评级CSS类
            result: LLM分析结果
            model_name: 模型名称

        Returns:
            单个LLM卡片的HTML
        """
        model_badge = ''
        if model_name:
            model_display = {'qwen': '通义千问', 'deepseek': 'DeepSeek'}.get(model_name, model_name.upper())
            model_badge = f'<span class="llm-model-badge">{model_display}</span>'

        # 操作建议
        operation = result.get('operation_advice', {})
        action = operation.get('action', '未知')
        position = operation.get('position_control', '未知')
        target_price = operation.get('target_price', '未知')
        stop_loss = operation.get('stop_loss', '未知')
        confidence = operation.get('confidence', 0)

        action_class = 'action-buy' if action == '买入' else ('action-sell' if action == '卖出' else 'action-hold')

        # 风险评估
        risk = result.get('risk_assessment', {})
        risk_level = risk.get('risk_level', '未知')
        risk_score = risk.get('overall_score', 0)
        risk_points = risk.get('risk_points', [])
        risk_class = 'risk-low' if risk_level == '低' else ('risk-high' if risk_level == '高' else 'risk-medium')

        # K线预测
        kline_pred = result.get('kline_prediction', {})
        trend = kline_pred.get('trend', '未知')
        pred_confidence = kline_pred.get('confidence', 0)
        support_levels = kline_pred.get('support_levels', [])
        resistance_levels = kline_pred.get('resistance_levels', [])

        # 策略
        strategy = result.get('strategy', {})
        short_term = strategy.get('short_term', '')
        mid_term = strategy.get('mid_term', '')
        position_strategy = strategy.get('position_strategy', '')

        # 总结
        summary = result.get('summary', '')

        # 构建HTML
        html = f'''
                <div class="llm-card">
                    <div class="llm-card-header">
                        <div class="llm-stock-info">
                            <span class="stock-name">{stock_name}</span>
                            <span class="stock-code">({stock_code})</span>
                            <span class="rating-badge {rating_class}">{rating}</span>
                            {model_badge}
                        </div>
                        <div class="llm-action {action_class}">
                            {action}
                        </div>
                    </div>

                    <div class="llm-card-body">
                        <!-- 操作建议 -->
                        <div class="llm-section">
                            <div class="llm-section-title">📈 操作建议</div>
                            <div class="llm-metrics">
                                <div class="llm-metric">
                                    <span class="metric-label">仓位控制</span>
                                    <span class="metric-value">{position}</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">目标价</span>
                                    <span class="metric-value">{target_price}</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">止损价</span>
                                    <span class="metric-value">{stop_loss}</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">置信度</span>
                                    <span class="metric-value">{confidence*100:.0f}%</span>
                                </div>
                            </div>
                        </div>

                        <!-- 风险评估 -->
                        <div class="llm-section">
                            <div class="llm-section-title">⚠️ 风险评估</div>
                            <div class="llm-risk">
                                <span class="risk-badge {risk_class}">{risk_level}风险</span>
                                <span class="risk-score">评分: {risk_score}</span>
                            </div>
                            <div class="risk-points">
                                {' · '.join(risk_points[:3]) if risk_points else '暂无风险提示'}
                            </div>
                        </div>

                        <!-- 趋势预测 -->
                        <div class="llm-section">
                            <div class="llm-section-title">📉 趋势预测</div>
                            <div class="llm-metrics">
                                <div class="llm-metric">
                                    <span class="metric-label">趋势</span>
                                    <span class="metric-value">{trend}</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">置信度</span>
                                    <span class="metric-value">{pred_confidence*100:.0f}%</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">支撑位</span>
                                    <span class="metric-value">{', '.join(str(x) for x in support_levels[:2]) if support_levels else '-'}</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">阻力位</span>
                                    <span class="metric-value">{', '.join(str(x) for x in resistance_levels[:2]) if resistance_levels else '-'}</span>
                                </div>
                            </div>
                        </div>

                        <!-- 策略建议 -->
                        <div class="llm-section">
                            <div class="llm-section-title">🎯 策略建议</div>
                            <div class="strategy-item">
                                <span class="strategy-label">短线:</span>
                                <span class="strategy-text">{short_term if short_term else '暂无'}</span>
                            </div>
                            <div class="strategy-item">
                                <span class="strategy-label">中线:</span>
                                <span class="strategy-text">{mid_term if mid_term else '暂无'}</span>
                            </div>
                        </div>

                        <!-- 综合建议 -->
                        <div class="llm-summary">
                            <div class="llm-section-title">💡 综合建议</div>
                            <p>{summary if summary else '暂无综合建议'}</p>
                        </div>
                    </div>
                </div>
'''
        return html

    def _get_recommendation_text(self, rating: str) -> str:
        """获取评级对应的建议文本"""
        recommendations = {
            'S': '🌟 强烈推荐',
            'A+': '⭐ 推荐',
            'A': '✓ 可考虑',
            'B': '△ 谨慎',
            'C': '✗ 不建议'
        }
        return recommendations.get(rating, '未知')


def main():
    """测试报表生成器"""
    print("=" * 60)
    print("投资机会挖掘报表生成器 - 测试")
    print("=" * 60)

    # 创建模拟数据
    mock_results = []

    # 10只通过所有筛选的股票
    for i in range(10):
        mock_results.append({
            'stock_code': f"60000{i}",
            'name': f"测试股票{i+1}",
            'passed': True,
            'eliminated_at_stage': 0,
            'final_score': 90 - i * 2,
            'rating': 'S' if i < 2 else 'A+' if i < 5 else 'A',
            'filter_history': [
                {'stage': j, 'stage_name': f'阶段{j}', 'passed': True, 'reason': f'✓ 通过阶段{j}筛选'}
                for j in range(1, 5)
            ]
        })

    # 在各阶段被淘汰的股票（仅阶段1-4）
    for stage in range(1, 5):
        for i in range(18):
            stock_idx = len(mock_results)
            mock_results.append({
                'stock_code': f"00{stock_idx:04d}",
                'name': f"测试股票{stock_idx+1}",
                'passed': False,
                'eliminated_at_stage': stage,
                'final_score': 70 - stage * 5 - i,
                'rating': 'B' if stage <= 2 else 'C',
                'filter_history': [
                    {'stage': j, 'stage_name': f'阶段{j}', 'passed': j < stage,
                     'reason': f"✓ 通过阶段{j}筛选" if j < stage else f"✗ 在阶段{j}被淘汰"}
                    for j in range(1, stage + 1)
                ]
            })

    # 生成报表
    generator = OpportunityReportGenerator()
    report_path = generator.generate_report(mock_results, "投资机会挖掘报告 (测试)")

    print(f"\n✓ 测试报表生成成功: {report_path}")


if __name__ == "__main__":
    main()
