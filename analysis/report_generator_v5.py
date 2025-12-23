#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会挖掘报告生成器 v5 - 增强版
支持并发优化、市场环境分析、综合评分筛选的展示
优化了报表结构，增加信息清晰度
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
            result_df, stats, report_title
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
        self, result_df: pd.DataFrame, stats: Dict, title: str
    ) -> str:
        """生成Markdown摘要"""
        stats_dict = stats.to_dict() if hasattr(stats, 'to_dict') else stats

        lines = [
            f"# {title}",
            f"\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        ]

        # 统计信息
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

        # 结果汇总
        if not result_df.empty:
            lines.append("## 🏆 推荐股票\n")
            lines.append("| 排名 | 股票代码 | 综合评分 | 评级 | 建议 |")
            lines.append("|-----|--------|--------|-----|-----|")

            for idx, (_, row) in enumerate(result_df.iterrows(), 1):
                code = row.get('股票代码', '-')
                score = f"{row.get('综合评分', 0):.1f}"
                rating = row.get('评级', '-')
                advice = row.get('建议', '-')

                lines.append(
                    f"| {idx} | {code} | {score} | {rating} | {advice} |"
                )

        lines.append("\n---\n")
        lines.append("*由投资机会挖掘系统 v5 生成*")

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
