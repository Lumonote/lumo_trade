#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会挖掘报告生成器 v5.5 - 全维度增强版
支持并发优化、市场环境分析、综合评分筛选的展示
优化了报表结构，增加信息清晰度

v5.5更新：
- 新增量价形态分析展示（放量上涨/缩量下跌）
- 新增追高风险评估展示
- 新增高级分析维度（筹码/板块/分时/情绪周期/资金流向/形态/时间窗口）
"""

import os
import sys
import json
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import pandas as pd
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import logging
logger = logging.getLogger(__name__)


class ReportGeneratorV5:
    """投资机会挖掘报告生成器 v5"""

    def __init__(self, output_dir: str = "results"):
        """
        初始化报告生成器

        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir
        Path(output_dir).mkdir(exist_ok=True, parents=True)

    def generate_concurrent_report(
        self,
        result_df: pd.DataFrame,
        detailed_results: Dict,
        stats: Dict,
        report_title: str = "投资机会挖掘报告 - 并发优化版",
        market_environment: Optional[str] = None,
    ) -> str:
        """
        生成并发优化版报告（HTML + Markdown）

        Args:
            result_df: 结果DataFrame
            detailed_results: 详细结果字典
            stats: 统计信息
            report_title: 报告标题
            market_environment: 市场环境描述

        Returns:
            生成的HTML文件路径
        """
        logger.info("开始生成并发优化版报告...")

        # 生成HTML报告
        html_content = self._generate_html_report(
            result_df, detailed_results, stats, report_title, market_environment
        )

        # 生成Markdown摘要
        md_content = self._generate_markdown_summary(
            result_df, stats, report_title, detailed_results
        )

        # 保存文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        html_file = self._save_html(html_content, timestamp)
        md_file = self._save_markdown(md_content, timestamp)

        logger.info(f"✅ 报告生成完成:\n  - HTML: {html_file}\n  - Markdown: {md_file}")

        return html_file

    def _generate_html_report(
        self,
        result_df: pd.DataFrame,
        detailed_results: Dict,
        stats: Dict,
        report_title: str,
        market_environment: Optional[str],
    ) -> str:
        """生成HTML报告内容"""
        stats_dict = stats.to_dict() if hasattr(stats, 'to_dict') else stats

        html_parts = []
        html_parts.append(self._generate_html_header(report_title))

        # 执行摘要
        html_parts.append(self._generate_summary_section(stats_dict, market_environment))

        # 处理统计信息
        html_parts.append(self._generate_statistics_section(stats_dict))

        # 结果汇总
        if not result_df.empty:
            html_parts.append(self._generate_results_section(result_df))

        # 高级分析详情（v5.5新增）
        html_parts.append(self._generate_advanced_analysis_section(detailed_results))

        # 详细信息
        html_parts.append(self._generate_details_section(detailed_results))

        # 性能分析
        html_parts.append(self._generate_performance_section(stats_dict))

        # 页脚
        html_parts.append(self._generate_html_footer())

        return "\n".join(html_parts)

    def _generate_html_header(self, title: str) -> str:
        """HTML头部"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f7fa; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 40px; border-radius: 8px; margin-bottom: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .header h1 {{ font-size: 32px; margin-bottom: 10px; }}
        .header p {{ font-size: 14px; opacity: 0.9; }}
        .card {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
        .card h2 {{ color: #333; font-size: 20px; margin-bottom: 15px; border-bottom: 3px solid #667eea; padding-bottom: 10px; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
        .stat-box {{ background: #f8f9fa; padding: 15px; border-radius: 6px; border-left: 4px solid #667eea; }}
        .stat-box .label {{ color: #666; font-size: 12px; text-transform: uppercase; }}
        .stat-box .value {{ color: #333; font-size: 24px; font-weight: bold; margin-top: 5px; }}
        .stat-box.success {{ border-left-color: #10b981; }}
        .stat-box.warning {{ border-left-color: #f59e0b; }}
        .stat-box.danger {{ border-left-color: #ef4444; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        th {{ background: #f3f4f6; color: #333; padding: 12px; text-align: left; font-weight: 600; border-bottom: 2px solid #e5e7eb; }}
        td {{ padding: 12px; border-bottom: 1px solid #e5e7eb; }}
        tr:hover {{ background: #f9fafb; }}
        .badge {{ display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
        .badge-s {{ background: #dbeafe; color: #1e40af; }}
        .badge-a {{ background: #dcfce7; color: #166534; }}
        .badge-b {{ background: #fef3c7; color: #92400e; }}
        .badge-c {{ background: #fee2e2; color: #991b1b; }}
        .metric {{ display: inline-block; margin-right: 20px; margin-bottom: 10px; }}
        .metric-label {{ color: #666; font-size: 12px; }}
        .metric-value {{ color: #333; font-size: 18px; font-weight: bold; }}
        .progress-bar {{ background: #e5e7eb; height: 20px; border-radius: 10px; overflow: hidden; }}
        .progress-fill {{ height: 100%; background: linear-gradient(90deg, #667eea 0%, #764ba2 100%); transition: width 0.3s ease; }}
        .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 {title}</h1>
            <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
"""

    def _generate_summary_section(self, stats: Dict, market_env: Optional[str]) -> str:
        """执行摘要"""
        total = stats.get('total_stocks', 0)
        success = stats.get('collection_success', 0)
        passed = stats.get('scoring_passed', 0)
        elapsed = stats.get('elapsed_seconds', 0)

        success_rate = (success / total * 100) if total > 0 else 0
        passed_rate = (passed / success * 100) if success > 0 else 0

        market_info = f"<p><strong>市场环境:</strong> {market_env}</p>" if market_env else ""

        return f"""
        <div class="card">
            <h2>📋 执行摘要</h2>
            {market_info}
            <div class="metric">
                <div class="metric-label">处理股票总数</div>
                <div class="metric-value">{total}</div>
            </div>
            <div class="metric">
                <div class="metric-label">采集成功</div>
                <div class="metric-value">{success} <span style="font-size: 12px; color: #666;">({success_rate:.1f}%)</span></div>
            </div>
            <div class="metric">
                <div class="metric-label">评分通过</div>
                <div class="metric-value">{passed} <span style="font-size: 12px; color: #666;">({passed_rate:.1f}%)</span></div>
            </div>
            <div class="metric">
                <div class="metric-label">总耗时</div>
                <div class="metric-value">{elapsed:.2f}s</div>
            </div>
        </div>
"""

    def _generate_statistics_section(self, stats: Dict) -> str:
        """统计信息"""
        total = stats.get('total_stocks', 0)
        completed = stats.get('completed_stocks', 0)
        failed = stats.get('failed_stocks', 0)
        collection_success = stats.get('collection_success', 0)
        collection_failed = stats.get('collection_failed', 0)
        scoring_passed = stats.get('scoring_passed', 0)
        scoring_failed = stats.get('scoring_failed', 0)
        elapsed = stats.get('elapsed_seconds', 0)
        avg_time = stats.get('avg_time_per_stock', 0)

        collection_rate = (collection_success / total * 100) if total > 0 else 0
        scoring_rate = (scoring_passed / collection_success * 100) if collection_success > 0 else 0

        return f"""
        <div class="card">
            <h2>📈 详细统计</h2>
            <div class="stats-grid">
                <div class="stat-box success">
                    <div class="label">数据采集</div>
                    <div class="value">{collection_success}/{total}</div>
                    <div style="font-size: 12px; color: #666; margin-top: 5px;">{collection_rate:.1f}% 成功率</div>
                </div>
                <div class="stat-box success">
                    <div class="label">评分通过</div>
                    <div class="value">{scoring_passed}/{collection_success}</div>
                    <div style="font-size: 12px; color: #666; margin-top: 5px;">{scoring_rate:.1f}% 通过率</div>
                </div>
                <div class="stat-box warning">
                    <div class="label">采集失败</div>
                    <div class="value">{collection_failed}</div>
                </div>
                <div class="stat-box warning">
                    <div class="label">评分未通过</div>
                    <div class="value">{scoring_failed}</div>
                </div>
            </div>
        </div>
"""

    def _generate_results_section(self, result_df: pd.DataFrame) -> str:
        """结果汇总"""
        if result_df.empty:
            return '<div class="card"><h2>结果汇总</h2><p>暂无通过过滤的股票</p></div>'

        # 生成表格
        table_html = '<table>\n<thead>\n<tr>'

        for col in result_df.columns:
            table_html += f'<th>{col}</th>'

        table_html += '</tr>\n</thead>\n<tbody>\n'

        for _, row in result_df.iterrows():
            table_html += '<tr>'
            for col in result_df.columns:
                val = row[col]

                # 评级特殊处理
                if col == '评级':
                    badge_class = f"badge-{val}"
                    table_html += f'<td><span class="badge {badge_class}">{val}</span></td>'
                # 评分特殊处理
                elif col in ['综合评分', '量化', '技术', '位置', '量价', '情绪', '板块']:
                    try:
                        score = float(val)
                        table_html += f'<td>{score:.1f}</td>'
                    except:
                        table_html += f'<td>{val}</td>'
                else:
                    table_html += f'<td>{val}</td>'

            table_html += '</tr>\n'

        table_html += '</tbody>\n</table>'

        return f"""
        <div class="card">
            <h2>🏆 推荐股票 TOP{min(10, len(result_df))}</h2>
            {table_html}
        </div>
"""

    def _generate_details_section(self, details: Dict) -> str:
        """详细信息"""
        passed_count = len(details.get('passed', {}))
        failed_count = len(details.get('failed', {}))

        return f"""
        <div class="card">
            <h2>📝 详细信息</h2>
            <div class="metric">
                <div class="metric-label">通过过滤的股票</div>
                <div class="metric-value">{passed_count}</div>
            </div>
            <div class="metric">
                <div class="metric-label">未通过过滤的股票</div>
                <div class="metric-value">{failed_count}</div>
            </div>
        </div>
"""

    def _generate_advanced_analysis_section(self, details: Dict) -> str:
        """生成高级分析详情部分 - v5.5新增"""
        passed_stocks = details.get('passed', {})
        if not passed_stocks:
            return ""
        
        html_parts = []
        html_parts.append("""
        <div class="card">
            <h2>🔬 高级分析详情 (v4.5)</h2>
            <p style="color: #666; font-size: 14px; margin-bottom: 20px;">
                包含量价形态、追高风险、筹码分析、板块联动、资金流向、K线形态、时间窗口等多维度分析
            </p>
        """)
        
        for stock_code, stock_data in list(passed_stocks.items())[:10]:
            scoring_result = stock_data.get('scoring_result', {})
            advanced = scoring_result.get('advanced_analysis', {})
            score_details = scoring_result.get('details', {})
            
            html_parts.append(f"""
            <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 15px; margin-bottom: 15px;">
                <h3 style="color: #1e40af; margin-bottom: 10px;">
                    📈 {stock_code} - 综合评分: {scoring_result.get('total_score', 0):.1f}分
                    {f" | 高级分析: {scoring_result.get('combined_score', 0):.1f}分" if 'combined_score' in scoring_result else ""}
                </h3>
            """)
            
            momentum = score_details.get('momentum', {})
            if momentum:
                chase_risk = momentum.get('chase_risk_level', 'unknown')
                chase_score = momentum.get('chase_risk_score', 0)
                chase_factors = momentum.get('chase_risk_factors', [])
                position_pct = momentum.get('position_pct', 0)
                
                risk_color = {'extreme': '#dc2626', 'high': '#ea580c', 'medium': '#ca8a04', 'low': '#16a34a', 'low_medium': '#65a30d'}.get(chase_risk, '#6b7280')
                
                html_parts.append(f"""
                <div style="background: #fef3c7; padding: 10px; border-radius: 6px; margin-bottom: 10px;">
                    <strong>⚠️ 追高风险评估:</strong>
                    <span style="color: {risk_color}; font-weight: bold;">{chase_risk.upper()} ({chase_score}分)</span>
                    <span style="color: #666;"> | 位置: {position_pct*100:.1f}%</span>
                    {f'<br><small style="color: #92400e;">风险因素: {", ".join(chase_factors[:3])}</small>' if chase_factors else ''}
                </div>
                """)
            
            vol_health = score_details.get('volume_health', {})
            if vol_health:
                vol_patterns = vol_health.get('volume_price_patterns', {})
                vol_signals = vol_health.get('signals', [])
                vol_score = scoring_result.get('scores', {}).get('volume_health', 0)
                
                html_parts.append(f"""
                <div style="background: #dbeafe; padding: 10px; border-radius: 6px; margin-bottom: 10px;">
                    <strong>📊 量价形态分析:</strong> 评分 {vol_score:.0f}分 | 健康度: {vol_health.get('volume_health', '未知')}
                """)
                
                if vol_patterns:
                    for pattern_name, pattern_data in vol_patterns.items():
                        if pattern_data:
                            days = pattern_data.get('consecutive_days', 0)
                            strength = pattern_data.get('pattern_strength', '')
                            vol_ratio = pattern_data.get('avg_volume_ratio', 1)
                            gain = pattern_data.get('total_gain_pct', 0)
                            pattern_label = {'vol_up_price_up': '🔥放量上涨', 'vol_down_price_down': '✅缩量下跌', 'vol_up_price_down': '⚠️放量下跌', 'vol_down_price_up': '⚡缩量上涨'}.get(pattern_name, pattern_name)
                            html_parts.append(f"""
                    <br><span style="margin-left: 10px;">{pattern_label}: 连续{days}天, 量比{vol_ratio:.1f}x, 涨跌{gain:+.1f}%, 强度{strength}</span>
                            """)
                
                if vol_signals:
                    html_parts.append(f"""
                    <br><small style="color: #1e40af;">信号: {' | '.join(vol_signals[:5])}</small>
                    """)
                
                html_parts.append("</div>")
            
            if advanced and 'dimensions' in advanced:
                dims = advanced['dimensions']
                overall = advanced.get('overall_score', {})
                
                html_parts.append(f"""
                <div style="background: #f0fdf4; padding: 10px; border-radius: 6px; margin-bottom: 10px;">
                    <strong>🔬 高级分析维度:</strong> 综合评分 {overall.get('final_score', 0):.1f}分
                    <div style="display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px;">
                """)
                
                dim_labels = {
                    'chip': ('🎯 筹码', '#8b5cf6'),
                    'sector': ('📦 板块', '#0891b2'),
                    'intraday': ('⏰ 分时', '#0d9488'),
                    'sentiment_cycle': ('💭 情绪', '#d946ef'),
                    'capital_flow': ('💰 资金', '#f59e0b'),
                    'patterns': ('📐 形态', '#6366f1'),
                    'time_window': ('📅 时间', '#84cc16')
                }
                
                for dim_key, (label, color) in dim_labels.items():
                    dim_data = dims.get(dim_key, {})
                    if isinstance(dim_data, dict) and 'score' in dim_data:
                        dim_score = dim_data['score']
                        dim_signals = dim_data.get('signals', [])
                        
                        html_parts.append(f"""
                        <div style="background: white; border: 1px solid {color}; border-radius: 4px; padding: 8px; min-width: 150px;">
                            <div style="color: {color}; font-weight: bold;">{label}: {dim_score:.0f}分</div>
                            {'<small style="color: #666;">' + dim_signals[0][:30] + '...</small>' if dim_signals else ''}
                        </div>
                        """)
                
                html_parts.append("</div></div>")
                
                for dim_key in ['chip', 'patterns', 'time_window']:
                    dim_data = dims.get(dim_key, {})
                    if isinstance(dim_data, dict):
                        signals = dim_data.get('signals', [])
                        warnings = dim_data.get('warnings', [])
                        opportunities = dim_data.get('opportunities', [])
                        patterns = dim_data.get('patterns', [])
                        
                        if signals or warnings or opportunities or patterns:
                            html_parts.append(f"""
                <div style="margin-top: 8px; padding-left: 10px; border-left: 3px solid #e5e7eb;">
                            """)
                            
                            if patterns:
                                for p in patterns[:3]:
                                    if isinstance(p, dict):
                                        html_parts.append(f"""
                    <span style="background: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 10px; margin-right: 5px; font-size: 12px;">
                        📐 {p.get('type', '')}: {p.get('confidence', 0)}%
                    </span>
                                        """)
                            
                            if opportunities:
                                for opp in opportunities[:2]:
                                    html_parts.append(f"""
                    <span style="background: #dcfce7; color: #166534; padding: 2px 8px; border-radius: 10px; margin-right: 5px; font-size: 12px;">
                        🎯 {opp}
                    </span>
                                    """)
                            
                            if warnings:
                                for warn in warnings[:2]:
                                    html_parts.append(f"""
                    <span style="background: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 10px; margin-right: 5px; font-size: 12px;">
                        ⚠️ {warn}
                    </span>
                                    """)
                            
                            html_parts.append("</div>")
            
            html_parts.append("</div>")
        
        html_parts.append("</div>")
        return "\n".join(html_parts)

    def _generate_performance_section(self, stats: Dict) -> str:
        """性能分析"""
        elapsed = stats.get('elapsed_seconds', 0)
        avg_time = stats.get('avg_time_per_stock', 0)
        total = stats.get('total_stocks', 0)

        throughput = (total / elapsed * 1000) if elapsed > 0 else 0  # 每秒处理数

        return f"""
        <div class="card">
            <h2>⚡ 性能指标</h2>
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="label">总耗时</div>
                    <div class="metric-value">{elapsed:.2f}s</div>
                </div>
                <div class="stat-box">
                    <div class="label">平均每支耗时</div>
                    <div class="metric-value">{avg_time:.3f}s</div>
                </div>
                <div class="stat-box">
                    <div class="label">吞吐量</div>
                    <div class="metric-value">{throughput:.1f}/s</div>
                </div>
                <div class="stat-box">
                    <div class="label">并发优化效果</div>
                    <div class="metric-value">✅ 已启用</div>
                </div>
            </div>
        </div>
"""

    def _generate_html_footer(self) -> str:
        """HTML页脚"""
        return """
        <div class="footer">
            <p>投资机会挖掘系统 v5 - 并发优化版 | 生成时间: """ + datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ) + """</p>
        </div>
    </div>
</body>
</html>
"""

    def _generate_markdown_summary(
        self, result_df: pd.DataFrame, stats: Dict, title: str,
        detailed_results: Optional[Dict] = None
    ) -> str:
        """生成Markdown摘要 - v5.5增强版，包含完整高级分析"""
        stats_dict = stats.to_dict() if hasattr(stats, 'to_dict') else stats

        lines = [
            f"# {title}",
            f"\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"\n**系统版本**: v5.5 全维度增强版\n",
        ]

        lines.append("## 📊 执行统计\n")
        lines.append(f"- **处理股票总数**: {stats_dict.get('total_stocks', 0)}")
        lines.append(
            f"- **采集成功**: {stats_dict.get('collection_success', 0)}"
        )
        lines.append(f"- **评分通过**: {stats_dict.get('scoring_passed', 0)}")
        lines.append(f"- **总耗时**: {stats_dict.get('elapsed_seconds', 0):.2f}s")
        lines.append(
            f"- **平均耗时/支**: {stats_dict.get('avg_time_per_stock', 0):.3f}s\n"
        )

        if not result_df.empty:
            lines.append("## 🏆 推荐股票\n")
            lines.append("| 排名 | 股票代码 | 综合评分 | 高级评分 | 评级 | 建议 |")
            lines.append("|-----|--------|--------|--------|-----|-----|")

            for idx, (_, row) in enumerate(result_df.iterrows(), 1):
                code = row.get('股票代码', '-')
                score = f"{row.get('综合评分', 0):.1f}"
                adv_score = row.get('高级评分', '-')
                if adv_score != '-':
                    adv_score = f"{float(adv_score):.1f}"
                rating = row.get('评级', '-')
                advice = row.get('建议', '-')

                lines.append(
                    f"| {idx} | {code} | {score} | {adv_score} | {rating} | {advice} |"
                )

        if detailed_results:
            passed_stocks = detailed_results.get('passed', {})
            if passed_stocks:
                lines.append("\n## 🔬 高级分析详情\n")
                
                for stock_code, stock_data in list(passed_stocks.items())[:10]:
                    scoring_result = stock_data.get('scoring_result', {})
                    advanced = scoring_result.get('advanced_analysis', {})
                    score_details = scoring_result.get('details', {})
                    
                    total_score = scoring_result.get('total_score', 0)
                    combined_score = scoring_result.get('combined_score', 0)
                    
                    lines.append(f"### 📈 {stock_code}")
                    lines.append(f"- **综合评分**: {total_score:.1f}分")
                    if combined_score:
                        lines.append(f"- **高级分析评分**: {combined_score:.1f}分")
                    lines.append("")
                    
                    momentum = score_details.get('momentum', {})
                    if momentum:
                        chase_risk = momentum.get('chase_risk_level', 'unknown')
                        chase_score = momentum.get('chase_risk_score', 0)
                        chase_factors = momentum.get('chase_risk_factors', [])
                        position_pct = momentum.get('position_pct', 0)
                        
                        lines.append("#### ⚠️ 追高风险评估")
                        lines.append(f"| 指标 | 数值 |")
                        lines.append("|------|------|")
                        lines.append(f"| 风险等级 | **{chase_risk.upper()}** |")
                        lines.append(f"| 风险分数 | {chase_score}分 |")
                        lines.append(f"| 位置百分比 | {position_pct*100:.1f}% |")
                        if chase_factors:
                            lines.append(f"| 风险因素 | {', '.join(chase_factors[:3])} |")
                        lines.append("")
                    
                    vol_health = score_details.get('volume_health', {})
                    if vol_health:
                        vol_patterns = vol_health.get('volume_price_patterns', {})
                        vol_signals = vol_health.get('signals', [])
                        vol_health_level = vol_health.get('volume_health', '未知')
                        vol_score = scoring_result.get('scores', {}).get('volume_health', 0)
                        
                        lines.append("#### 📊 量价形态分析")
                        lines.append(f"- **评分**: {vol_score:.0f}分")
                        lines.append(f"- **健康度**: {vol_health_level}")
                        
                        if vol_patterns:
                            lines.append("\n| 形态类型 | 连续天数 | 量比 | 涨跌幅 | 强度 |")
                            lines.append("|----------|---------|------|--------|------|")
                            pattern_labels = {
                                'vol_up_price_up': '🔥放量上涨',
                                'vol_down_price_down': '✅缩量下跌',
                                'vol_up_price_down': '⚠️放量下跌',
                                'vol_down_price_up': '⚡缩量上涨'
                            }
                            for pattern_name, pattern_data in vol_patterns.items():
                                if pattern_data:
                                    label = pattern_labels.get(pattern_name, pattern_name)
                                    days = pattern_data.get('consecutive_days', 0)
                                    vol_ratio = pattern_data.get('avg_volume_ratio', 1)
                                    gain = pattern_data.get('total_gain_pct', 0)
                                    strength = pattern_data.get('pattern_strength', '')
                                    lines.append(f"| {label} | {days}天 | {vol_ratio:.1f}x | {gain:+.1f}% | {strength} |")
                        
                        if vol_signals:
                            lines.append(f"\n**信号**: {' | '.join(vol_signals[:5])}")
                        lines.append("")
                    
                    if advanced and 'dimensions' in advanced:
                        dims = advanced['dimensions']
                        overall = advanced.get('overall_score', {})
                        
                        lines.append("#### 🔬 高级分析维度")
                        lines.append(f"**综合评分**: {overall.get('final_score', 0):.1f}分\n")
                        
                        lines.append("| 维度 | 评分 | 关键信号 |")
                        lines.append("|------|------|----------|")
                        
                        dim_info = {
                            'chip': '🎯 筹码分析',
                            'sector': '📦 板块联动',
                            'intraday': '⏰ 分时特征',
                            'sentiment_cycle': '💭 情绪周期',
                            'capital_flow': '💰 资金流向',
                            'patterns': '📐 K线形态',
                            'time_window': '📅 时间窗口'
                        }
                        
                        for dim_key, label in dim_info.items():
                            dim_data = dims.get(dim_key, {})
                            if isinstance(dim_data, dict) and 'score' in dim_data:
                                dim_score = dim_data['score']
                                dim_signals = dim_data.get('signals', [])
                                signal_str = dim_signals[0][:40] + '...' if dim_signals else '-'
                                lines.append(f"| {label} | {dim_score:.0f}分 | {signal_str} |")
                        
                        lines.append("")
                        
                        chip_data = dims.get('chip', {})
                        if isinstance(chip_data, dict) and chip_data.get('details'):
                            details = chip_data['details']
                            lines.append("##### 🎯 筹码详情")
                            lines.append(f"- **90%筹码集中度**: {details.get('concentration_90', 0):.1f}%")
                            lines.append(f"- **主力控盘度**: {details.get('main_force_control', 0):.1f}%")
                            lock = details.get('lock_pattern', {})
                            if lock.get('detected'):
                                lines.append(f"- **锁仓形态**: {lock.get('type', '')} (置信度{lock.get('confidence', 0)}%)")
                            lines.append("")
                        
                        sector_data = dims.get('sector', {})
                        if isinstance(sector_data, dict) and sector_data.get('details'):
                            details = sector_data['details']
                            lines.append("##### 📦 板块详情")
                            lines.append(f"- **所属板块**: {details.get('sector_name', '未知')}")
                            lines.append(f"- **板块涨跌**: {details.get('sector_change', 0):+.1f}%")
                            lines.append(f"- **板块排名**: 第{details.get('sector_rank', 0)}名")
                            lines.append(f"- **板块净流入**: {details.get('sector_net_inflow', 0):.1f}亿")
                            lines.append(f"- **轮动位置**: {details.get('rotation_phase', '未知')}")
                            lines.append("")
                        
                        intraday_data = dims.get('intraday', {})
                        if isinstance(intraday_data, dict) and intraday_data.get('details'):
                            details = intraday_data['details']
                            lines.append("##### ⏰ 分时详情")
                            morning = details.get('morning', {})
                            afternoon = details.get('afternoon', {})
                            manipulation = details.get('manipulation', {})
                            if morning.get('strong_open'):
                                lines.append("- **早盘**: 🔥强势开盘")
                            if morning.get('big_order_buy'):
                                lines.append("- **早盘大单**: 买入")
                            if afternoon.get('late_surge'):
                                lines.append("- **尾盘**: ⚠️尾盘拉升")
                            if afternoon.get('late_dump'):
                                lines.append("- **尾盘**: 🚨尾盘砸盘")
                            if manipulation.get('detected'):
                                lines.append(f"- **异常**: 🚨{manipulation.get('type', '疑似对倒')}")
                            lines.append("")
                        
                        sentiment_data = dims.get('sentiment_cycle', {})
                        if isinstance(sentiment_data, dict) and sentiment_data.get('details'):
                            details = sentiment_data['details']
                            fg = details.get('fear_greed_index', {})
                            limit = details.get('limit_analysis', {})
                            lines.append("##### 💭 市场情绪")
                            lines.append(f"- **恐惧贪婪指数**: {fg.get('index', 50)} ({fg.get('emotion', '中性')})")
                            lines.append(f"- **连板高度**: {limit.get('max_streak', 0)}板")
                            lines.append(f"- **涨停家数**: {limit.get('limit_up_count', 0)}")
                            lines.append(f"- **跌停家数**: {limit.get('limit_down_count', 0)}")
                            lines.append(f"- **市场周期**: {details.get('cycle_phase', '未知')}")
                            lines.append("")
                        
                        capital_data = dims.get('capital_flow', {})
                        if isinstance(capital_data, dict) and capital_data.get('details'):
                            details = capital_data['details']
                            order = details.get('order_analysis', {})
                            continuity = details.get('continuity', {})
                            lines.append("##### 💰 资金流向")
                            lines.append(f"- **超大单净额**: {order.get('super_large_net', 0)/10000:.1f}万")
                            lines.append(f"- **大单净额**: {order.get('large_net', 0)/10000:.1f}万")
                            lines.append(f"- **主力净流入**: {order.get('main_net_inflow', 0)/10000:.1f}万")
                            lines.append(f"- **散户占比**: {details.get('retail_ratio', 50):.0f}%")
                            if continuity.get('consecutive_inflow_days', 0) > 0:
                                lines.append(f"- **连续流入**: {continuity['consecutive_inflow_days']}天")
                            if continuity.get('consecutive_outflow_days', 0) > 0:
                                lines.append(f"- **连续流出**: {continuity['consecutive_outflow_days']}天")
                            lines.append("")
                        
                        pattern_data = dims.get('patterns', {})
                        if isinstance(pattern_data, dict):
                            patterns = pattern_data.get('patterns', [])
                            if patterns:
                                lines.append("##### 📐 K线形态识别")
                                for p in patterns[:5]:
                                    if isinstance(p, dict):
                                        lines.append(f"- **{p.get('type', '')}**: 置信度 {p.get('confidence', 0)}%")
                                lines.append("")
                        
                        time_data = dims.get('time_window', {})
                        if isinstance(time_data, dict):
                            warnings = time_data.get('warnings', [])
                            opportunities = time_data.get('opportunities', [])
                            details = time_data.get('details', {})
                            
                            if warnings or opportunities or details:
                                lines.append("##### 📅 时间窗口")
                                
                                earnings = details.get('earnings', {})
                                if earnings.get('approaching'):
                                    lines.append(f"- **财报**: {earnings.get('report_type', '')}将于{earnings.get('days_until', 0)}天后发布")
                                
                                unlock = details.get('unlock', {})
                                if unlock.get('approaching'):
                                    lines.append(f"- **解禁**: ⚠️{unlock.get('unlock_ratio', 0):.1f}%解禁将于{unlock.get('days_until', 0)}天后")
                                
                                dividend = details.get('dividend', {})
                                if dividend.get('approaching'):
                                    lines.append(f"- **分红**: 除权日{dividend.get('ex_dividend_date', '')}, 股息率{dividend.get('dividend_yield', 0):.1f}%")
                                
                                for opp in opportunities:
                                    lines.append(f"- 🎯 {opp}")
                                for warn in warnings:
                                    lines.append(f"- ⚠️ {warn}")
                                lines.append("")
                    
                    lines.append("---\n")

        lines.append("\n---\n")
        lines.append("*由投资机会挖掘系统 v5.5 全维度增强版 生成*")

        return "\n".join(lines)

    def _save_html(self, content: str, timestamp: str) -> str:
        """保存HTML文件"""
        filename = f"opportunity_report_v5_{timestamp}.html"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return filepath

    def _save_markdown(self, content: str, timestamp: str) -> str:
        """保存Markdown文件"""
        filename = f"opportunity_summary_v5_{timestamp}.md"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return filepath


if __name__ == "__main__":
    # 测试报告生成
    import pandas as pd

    print("测试报告生成器v5...")

    # 创建示例数据
    test_df = pd.DataFrame(
        {
            "股票代码": ["688343", "000001", "600519"],
            "综合评分": [85.5, 78.2, 72.1],
            "评级": ["S", "A+", "A"],
            "建议": ["强烈推荐", "推荐", "可关注"],
            "量化": [88.0, 75.0, 70.0],
            "技术": [82.0, 78.0, 72.0],
            "位置": [80.0, 76.0, 68.0],
            "量价": [85.0, 80.0, 74.0],
        }
    )

    test_stats = {
        "total_stocks": 100,
        "collection_success": 95,
        "collection_failed": 5,
        "scoring_passed": 3,
        "scoring_failed": 92,
        "elapsed_seconds": 45.5,
        "avg_time_per_stock": 0.455,
    }

    generator = ReportGeneratorV5()
    html_file = generator.generate_concurrent_report(
        test_df,
        {"passed": {}, "failed": {}},
        test_stats,
        report_title="测试报告 - 并发优化版",
        market_environment="沪深300强势，创业板弱势",
    )

    print(f"✅ 报告已生成: {html_file}")
