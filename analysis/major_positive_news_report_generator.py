#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重大利好消息挖掘报表生成器
生成包含TOP推荐、详细分析的HTML报表和CSV/Excel报表
"""

import os
import sys
from datetime import datetime
from typing import List, Dict
import json
import logging
import pandas as pd

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MajorPositiveNewsReportGenerator:
    """重大利好消息挖掘报表生成器"""

    def __init__(self, output_dir: str = "results"):
        """
        初始化报表生成器

        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_html_report(self, analysis_results: List[Dict],
                             report_title: str = "重大利好消息挖掘报告") -> str:
        """
        生成HTML报表

        Args:
            analysis_results: 分析结果列表
            report_title: 报表标题

        Returns:
            生成的HTML文件路径
        """
        logger.info(f"开始生成重大利好消息挖掘HTML报表...")

        # 统计数据
        total_count = len(analysis_results)
        high_confidence = [r for r in analysis_results if r.get('confidence_score', 0) >= 75]
        medium_confidence = [r for r in analysis_results if 50 <= r.get('confidence_score', 0) < 75]

        # 按置信度得分排序
        sorted_results = sorted(analysis_results, key=lambda x: x.get('confidence_score', 0), reverse=True)

        # TOP推荐
        top_10 = sorted_results[:10]

        # 生成HTML
        html_content = self._generate_html_content(
            report_title=report_title,
            total_count=total_count,
            high_confidence_count=len(high_confidence),
            medium_confidence_count=len(medium_confidence),
            top_10=top_10,
            all_results=sorted_results
        )

        # 保存文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"major_positive_news_{timestamp}.html"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"✓ HTML报表生成完成: {filepath}")

        return filepath

    def generate_markdown_report(self, analysis_results: List[Dict],
                                  report_title: str = "重大利好消息挖掘报告") -> str:
        """
        生成Markdown报表

        Args:
            analysis_results: 分析结果列表
            report_title: 报表标题

        Returns:
            生成的Markdown文件路径
        """
        logger.info(f"开始生成Markdown报表...")

        total_count = len(analysis_results)
        sorted_results = sorted(analysis_results, key=lambda x: x.get('confidence_score', 0), reverse=True)

        high_grade = [r for r in sorted_results if r.get('confidence_score', 0) >= 85]
        medium_grade = [r for r in sorted_results if 70 <= r.get('confidence_score', 0) < 85]
        low_grade = [r for r in sorted_results if r.get('confidence_score', 0) < 70]

        md_content = f"""# {report_title}

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | **发现机会**: {total_count}个

---

"""
        for i, result in enumerate(sorted_results[:10], 1):
            stock_code = result.get('stock_code', '')
            stock_name = result.get('stock_name', '')
            confidence_score = result.get('confidence_score', 0)
            confidence_rating = result.get('confidence_rating', 'C')
            news_type = result.get('news_type_name', '')
            news_title = result.get('news_title', '')
            news_content = result.get('news_content', '')
            news_source = result.get('news_source', '')
            news_url = result.get('news_url', '')
            publish_time = result.get('publish_time', '')
            investment_advice = result.get('investment_advice', '')
            risk_warning = result.get('risk_warning', '')

            confidence = result.get('confidence', {})
            scores = confidence.get('scores', {})
            source_reliability = scores.get('source_reliability', 0)
            timeliness = scores.get('timeliness', 0)
            content_quality = scores.get('content_quality', 0)
            market_validation = scores.get('market_validation', 0)
            historical_accuracy = scores.get('historical_accuracy', 0)
            technical_alignment = scores.get('technical_alignment', 0)

            raw_data = result.get('raw_data', {})
            sample_posts = raw_data.get('sample_posts', [])
            keywords = raw_data.get('keywords', [])
            sources = raw_data.get('sources', [])
            drill_analysis = result.get('drill_down_analysis', raw_data.get('drill_down_analysis', {}))

            rating_icon = "🔴" if confidence_score >= 90 else "🟠" if confidence_score >= 80 else "🟡" if confidence_score >= 65 else "⚪"

            md_content += f"""## {rating_icon} {i}. {stock_code} {stock_name} 【{confidence_rating}级 {confidence_score:.0f}分】

**{news_type}**: {news_title}

"""
            if news_content and len(news_content) > 10:
                md_content += f"""> {news_content}

"""

            if sample_posts:
                seen_titles = set()
                unique_posts = []
                for post in sample_posts[:5]:
                    post_title = post.get('title', '')
                    if post_title and post_title not in seen_titles:
                        seen_titles.add(post_title)
                        unique_posts.append(post)
                
                if unique_posts:
                    md_content += """**原始信息**:

"""
                    for idx, post in enumerate(unique_posts[:3], 1):
                        post_title = post.get('title', '')
                        post_url = post.get('url', '')
                        post_time = post.get('post_time', '')
                        post_source = post.get('source_name', post.get('source', ''))
                        
                        if post_url:
                            md_content += f"""- [{post_title}]({post_url}) ({post_source}, {post_time})
"""
                        else:
                            md_content += f"""- {post_title} ({post_source}, {post_time})
"""
                    md_content += "\n"

            event_timeline = result.get('event_timeline', {})
            if event_timeline and event_timeline.get('timeline_nodes'):
                event_type_cn = event_timeline.get('event_type_cn', '事件')
                current_stage = event_timeline.get('current_stage', '')
                
                md_content += f"""**事件进度**: {event_type_cn} - {current_stage}

"""
                key_dates = event_timeline.get('key_dates', {})
                if key_dates:
                    dates_str = " | ".join([f"{k}: {v}" for k, v in list(key_dates.items())[:3]])
                    md_content += f"""**关键日期**: {dates_str}

"""

            merger_analysis = result.get('merger_analysis', {})
            if merger_analysis and merger_analysis.get('analysis_completed'):
                acquirer_list = merger_analysis.get('acquirer_list', [])
                if acquirer_list:
                    md_content += """**潜在收购方分析**:

"""
                    for idx, acq in enumerate(acquirer_list[:3], 1):
                        acq_code = acq.get('code', '')
                        acq_name = acq.get('name', '')
                        acq_score = acq.get('overall_score', 0)
                        success_prob = acq.get('success_probability', '未知')
                        risk_level = acq.get('risk_level', '未知')
                        timeline = acq.get('timeline', '未知')
                        synergy = acq.get('synergy_potential', '')
                        
                        md_content += f"""| {idx}. **{acq_code} {acq_name}** | 匹配度: {acq_score:.0f}分 | 成功率: {success_prob} | 风险: {risk_level} | 预计周期: {timeline} |
"""
                        if synergy:
                            md_content += f"""|    协同效应: {synergy} |
"""
                        
                        key_factors = acq.get('key_success_factors', [])
                        if key_factors:
                            md_content += f"""|    关键成功因素: {', '.join(key_factors[:2])} |
"""
                        
                        critical_risks = acq.get('critical_risks', [])
                        if critical_risks:
                            md_content += f"""|    主要风险: {', '.join(critical_risks[:2])} |
"""
                    
                    md_content += "\n"

            md_content += f"""**建议**: {investment_advice}

**风险**: {risk_warning}

---

"""

        md_content += f"""---

*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Kronos 投资机会发现系统*
"""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"major_positive_news_{timestamp}.md"
        filepath = os.path.join(self.output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)

        logger.info(f"✓ Markdown报表生成完成: {filepath}")

        return filepath

    def generate_csv_report(self, analysis_results: List[Dict]) -> str:
        """
        生成CSV报表

        Args:
            analysis_results: 分析结果列表

        Returns:
            生成的CSV文件路径
        """
        logger.info(f"开始生成CSV报表...")

        # 准备数据
        data = []
        for result in analysis_results:
            stock_code = result.get('stock_code', '')
            stock_name = result.get('stock_name', '')
            confidence_score = result.get('confidence_score', 0)
            confidence_rating = result.get('confidence_rating', 'C')
            investment_advice = result.get('investment_advice', '')
            risk_warning = result.get('risk_warning', '')

            # 新闻信息
            news_type = result.get('news_type_name', '')
            news_title = result.get('news_title', '')
            news_date = result.get('publish_time', '')
            news_source = result.get('news_source', '')
            news_url = result.get('news_url', '')

            # 置信度详情
            confidence = result.get('confidence', {})
            source_reliability = confidence.get('scores', {}).get('source_reliability', 0)
            timeliness = confidence.get('scores', {}).get('timeliness', 0)
            content_quality = confidence.get('scores', {}).get('content_quality', 0)
            market_validation = confidence.get('scores', {}).get('market_validation', 0)
            historical_accuracy = confidence.get('scores', {}).get('historical_accuracy', 0)
            technical_alignment = confidence.get('scores', {}).get('technical_alignment', 0)

            data.append({
                '股票代码': stock_code,
                '股票名称': stock_name,
                '置信度得分': confidence_score,
                '置信度评级': confidence_rating,
                '利好类型': news_type,
                '利好标题': news_title,
                '利好日期': news_date,
                '消息来源': news_source,
                '新闻链接': news_url,
                '来源可信度': source_reliability,
                '时效性': timeliness,
                '内容质量': content_quality,
                '市场验证度': market_validation,
                '历史准确度': historical_accuracy,
                '技术面配合度': technical_alignment,
                '投资建议': investment_advice,
                '风险提示': risk_warning
            })

        # 创建DataFrame
        df = pd.DataFrame(data)

        # 保存CSV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"major_positive_news_{timestamp}.csv"
        filepath = os.path.join(self.output_dir, filename)

        df.to_csv(filepath, index=False, encoding='utf-8-sig')

        logger.info(f"✓ CSV报表生成完成: {filepath}")

        return filepath

    def generate_excel_report(self, analysis_results: List[Dict]) -> str:
        """
        生成Excel报表（包含多个工作表）

        Args:
            analysis_results: 分析结果列表

        Returns:
            生成的Excel文件路径
        """
        logger.info(f"开始生成Excel报表...")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"major_positive_news_{timestamp}.xlsx"
        filepath = os.path.join(self.output_dir, filename)

        # 创建Excel写入器
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            # 工作表1：汇总表
            summary_data = []
            for result in analysis_results:
                stock_code = result.get('stock_code', '')
                stock_name = result.get('stock_name', '')
                confidence_score = result.get('confidence_score', 0)
                confidence_rating = result.get('confidence_rating', 'C')
                investment_advice = result.get('investment_advice', '')

                news_type = result.get('news_type_name', '')
                news_title = result.get('news_title', '')
                news_date = result.get('publish_time', '')
                news_source = result.get('news_source', '')

                summary_data.append({
                    '股票代码': stock_code,
                    '股票名称': stock_name,
                    '置信度得分': confidence_score,
                    '置信度评级': confidence_rating,
                    '利好类型': news_type,
                    '利好标题': news_title,
                    '利好日期': news_date,
                    '消息来源': news_source,
                    '投资建议': investment_advice
                })

            df_summary = pd.DataFrame(summary_data)
            df_summary.to_excel(writer, sheet_name='汇总', index=False)

            # 工作表2：高置信度推荐（A+级以上）
            high_conf_data = []
            for result in analysis_results:
                if result.get('confidence_score', 0) >= 75:
                    stock_code = result.get('stock_code', '')
                    stock_name = result.get('stock_name', '')
                    confidence_score = result.get('confidence_score', 0)
                    confidence_rating = result.get('confidence_rating', 'C')
                    investment_advice = result.get('investment_advice', '')
                    risk_warning = result.get('risk_warning', '')

                    news_type = result.get('news_type_name', '')
                    news_title = result.get('news_title', '')
                    news_date = result.get('publish_time', '')
                    news_source = result.get('news_source', '')
                    news_url = result.get('news_url', '')

                    confidence = result.get('confidence', {})
                    source_reliability = confidence.get('scores', {}).get('source_reliability', 0)
                    timeliness = confidence.get('scores', {}).get('timeliness', 0)
                    content_quality = confidence.get('scores', {}).get('content_quality', 0)
                    market_validation = confidence.get('scores', {}).get('market_validation', 0)
                    historical_accuracy = confidence.get('scores', {}).get('historical_accuracy', 0)
                    technical_alignment = confidence.get('scores', {}).get('technical_alignment', 0)

                    high_conf_data.append({
                        '股票代码': stock_code,
                        '股票名称': stock_name,
                        '置信度得分': confidence_score,
                        '置信度评级': confidence_rating,
                        '利好类型': news_type,
                        '利好标题': news_title,
                        '利好日期': news_date,
                        '消息来源': news_source,
                        '新闻链接': news_url,
                        '来源可信度': source_reliability,
                        '时效性': timeliness,
                        '内容质量': content_quality,
                        '市场验证度': market_validation,
                        '历史准确度': historical_accuracy,
                        '技术面配合度': technical_alignment,
                        '投资建议': investment_advice,
                        '风险提示': risk_warning
                    })

            if high_conf_data:
                df_high_conf = pd.DataFrame(high_conf_data)
                df_high_conf.to_excel(writer, sheet_name='高置信度推荐', index=False)

            # 工作表3：所有详细数据
            detailed_data = []
            for result in analysis_results:
                stock_code = result.get('stock_code', '')
                stock_name = result.get('stock_name', '')
                confidence_score = result.get('confidence_score', 0)
                confidence_rating = result.get('confidence_rating', 'C')
                investment_advice = result.get('investment_advice', '')
                risk_warning = result.get('risk_warning', '')

                news_type = result.get('news_type_name', '')
                news_title = result.get('news_title', '')
                news_date = result.get('publish_time', '')
                news_source = result.get('news_source', '')
                news_url = result.get('news_url', '')

                confidence = result.get('confidence', {})
                source_reliability = confidence.get('scores', {}).get('source_reliability', 0)
                timeliness = confidence.get('scores', {}).get('timeliness', 0)
                content_quality = confidence.get('scores', {}).get('content_quality', 0)
                market_validation = confidence.get('scores', {}).get('market_validation', 0)
                historical_accuracy = confidence.get('scores', {}).get('historical_accuracy', 0)
                technical_alignment = confidence.get('scores', {}).get('technical_alignment', 0)

                detailed_data.append({
                    '股票代码': stock_code,
                    '股票名称': stock_name,
                    '置信度得分': confidence_score,
                    '置信度评级': confidence_rating,
                    '利好类型': news_type,
                    '利好标题': news_title,
                    '利好日期': news_date,
                    '消息来源': news_source,
                    '新闻链接': news_url,
                    '来源可信度': source_reliability,
                    '时效性': timeliness,
                    '内容质量': content_quality,
                    '市场验证度': market_validation,
                    '历史准确度': historical_accuracy,
                    '技术面配合度': technical_alignment,
                    '投资建议': investment_advice,
                    '风险提示': risk_warning
                })

            if detailed_data:
                df_detailed = pd.DataFrame(detailed_data)
                df_detailed.to_excel(writer, sheet_name='详细数据', index=False)

        logger.info(f"✓ Excel报表生成完成: {filepath}")

        return filepath

    def _generate_html_content(self, report_title: str, total_count: int,
                              high_confidence_count: int, medium_confidence_count: int,
                              top_10: List[Dict], all_results: List[Dict]) -> str:
        """生成HTML内容"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report_title}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
            overflow: hidden;
        }}

        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}

        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
        }}

        .header .subtitle {{
            font-size: 1.2em;
            opacity: 0.9;
        }}

        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            padding: 30px;
            background: #f8f9fa;
        }}

        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            text-align: center;
        }}

        .stat-card .number {{
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 5px;
        }}

        .stat-card .label {{
            color: #666;
            font-size: 0.9em;
        }}

        .section {{
            padding: 30px;
        }}

        .section-title {{
            font-size: 1.8em;
            margin-bottom: 20px;
            color: #333;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
        }}

        .stock-card {{
            background: white;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .stock-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
        }}

        .stock-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}

        .stock-info {{
            display: flex;
            align-items: center;
            gap: 15px;
        }}

        .stock-code {{
            font-size: 1.5em;
            font-weight: bold;
            color: #333;
        }}

        .rating-badge {{
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 1em;
        }}

        .rating-S {{
            background: #ff6b6b;
            color: white;
        }}

        .rating-A+ {{
            background: #ffa502;
            color: white;
        }}

        .rating-A {{
            background: #2ed573;
            color: white;
        }}

        .rating-B {{
            background: #1e90ff;
            color: white;
        }}

        .rating-C {{
            background: #a4b0be;
            color: white;
        }}

        .score-bar {{
            width: 100%;
            height: 20px;
            background: #f0f0f0;
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }}

        .score-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s;
        }}

        .news-details {{
            margin-top: 15px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
        }}

        .news-title {{
            font-size: 1.1em;
            font-weight: bold;
            color: #333;
            margin-bottom: 10px;
        }}

        .news-meta {{
            display: flex;
            gap: 20px;
            color: #666;
            font-size: 0.9em;
            margin-bottom: 10px;
        }}

        .confidence-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin-top: 15px;
        }}

        .confidence-item {{
            background: white;
            padding: 10px;
            border-radius: 6px;
            text-align: center;
            border: 1px solid #e0e0e0;
        }}

        .confidence-item .label {{
            font-size: 0.85em;
            color: #666;
            margin-bottom: 5px;
        }}

        .confidence-item .value {{
            font-size: 1.2em;
            font-weight: bold;
            color: #667eea;
        }}

        .advice-box {{
            margin-top: 15px;
            padding: 15px;
            background: #e8f5e9;
            border-left: 4px solid #4caf50;
            border-radius: 4px;
        }}

        .risk-box {{
            margin-top: 10px;
            padding: 15px;
            background: #ffebee;
            border-left: 4px solid #f44336;
            border-radius: 4px;
        }}

        .footer {{
            text-align: center;
            padding: 20px;
            background: #f8f9fa;
            color: #666;
            font-size: 0.9em;
        }}

        @media (max-width: 768px) {{
            .stock-header {{
                flex-direction: column;
                align-items: flex-start;
            }}

            .confidence-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 {report_title}</h1>
            <div class="subtitle">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
        </div>

        <div class="stats">
            <div class="stat-card">
                <div class="number">{total_count}</div>
                <div class="label">分析股票总数</div>
            </div>
            <div class="stat-card">
                <div class="number">{high_confidence_count}</div>
                <div class="label">高置信度推荐 (A+级以上)</div>
            </div>
            <div class="stat-card">
                <div class="number">{medium_confidence_count}</div>
                <div class="label">中等置信度 (A-B级)</div>
            </div>
        </div>

        <div class="section">
            <h2 class="section-title">🏆 TOP 10 推荐</h2>
"""

        # 添加TOP 10股票卡片
        for idx, stock in enumerate(top_10, 1):
            stock_code = stock.get('stock_code', '')
            stock_name = stock.get('stock_name', '')
            confidence_score = stock.get('confidence_score', 0)
            confidence_rating = stock.get('confidence_rating', 'C')
            investment_advice = stock.get('investment_advice', '')
            risk_warning = stock.get('risk_warning', '')

            news_type = stock.get('news_type_name', '')
            news_title = stock.get('news_title', '')
            news_date = stock.get('publish_time', '')
            news_source = stock.get('news_source', '')
            news_url = stock.get('news_url', '')

            confidence = stock.get('confidence', {})
            source_reliability = confidence.get('scores', {}).get('source_reliability', 0)
            timeliness = confidence.get('scores', {}).get('timeliness', 0)
            content_quality = confidence.get('scores', {}).get('content_quality', 0)
            market_validation = confidence.get('scores', {}).get('market_validation', 0)
            historical_accuracy = confidence.get('scores', {}).get('historical_accuracy', 0)
            technical_alignment = confidence.get('scores', {}).get('technical_alignment', 0)

            html += f"""
            <div class="stock-card">
                <div class="stock-header">
                    <div class="stock-info">
                        <span class="stock-code">#{idx} {stock_code} {stock_name}</span>
                        <span class="rating-badge rating-{confidence_rating}">{confidence_rating}级</span>
                    </div>
                </div>

                <div class="score-bar">
                    <div class="score-fill" style="width: {min(confidence_score, 100)}%"></div>
                </div>
                <div style="text-align: center; color: #666; font-size: 0.9em;">
                    置信度得分: {confidence_score:.1f}分
                </div>

                <div class="news-details">
                    <div class="news-title">📢 {news_type}</div>
                    <div class="news-title" style="font-size: 1em; margin-bottom: 10px;">{news_title}</div>
                    <div class="news-meta">
                        <span>📅 {news_date}</span>
                        <span>📰 {news_source}</span>
                    </div>

                    <div class="confidence-grid">
                        <div class="confidence-item">
                            <div class="label">来源可信度</div>
                            <div class="value">{source_reliability:.0f}</div>
                        </div>
                        <div class="confidence-item">
                            <div class="label">时效性</div>
                            <div class="value">{timeliness:.0f}</div>
                        </div>
                        <div class="confidence-item">
                            <div class="label">内容质量</div>
                            <div class="value">{content_quality:.0f}</div>
                        </div>
                        <div class="confidence-item">
                            <div class="label">市场验证度</div>
                            <div class="value">{market_validation:.0f}</div>
                        </div>
                        <div class="confidence-item">
                            <div class="label">历史准确度</div>
                            <div class="value">{historical_accuracy:.0f}</div>
                        </div>
                        <div class="confidence-item">
                            <div class="label">技术面配合度</div>
                            <div class="value">{technical_alignment:.0f}</div>
                        </div>
                    </div>
                </div>

                <div class="advice-box">
                    <strong>💡 投资建议:</strong> {investment_advice}
                </div>

                <div class="risk-box">
                    <strong>⚠️ 风险提示:</strong> {risk_warning}
                </div>
            </div>
"""

        html += """
        </div>

        <div class="section">
            <h2 class="section-title">📋 所有分析结果</h2>
"""

        # 添加所有股票的简要信息
        for stock in all_results:
            stock_code = stock.get('stock_code', '')
            overall_score = stock.get('overall_score', 0)
            overall_rating = stock.get('overall_rating', 'C')

            major_news = stock.get('major_news', [])
            if major_news:
                top_news = major_news[0]
                news_type = top_news.get('news_type_name', '')
                news_title = top_news.get('title', '')
            else:
                news_type = '无'
                news_title = '暂无利好消息'

            html += f"""
            <div class="stock-card" style="padding: 15px;">
                <div class="stock-header" style="margin-bottom: 10px;">
                    <div class="stock-info">
                        <span class="stock-code" style="font-size: 1.2em;">{stock_code}</span>
                        <span class="rating-badge rating-{overall_rating}" style="font-size: 0.9em;">{overall_rating}级</span>
                    </div>
                    <div style="color: #666;">{overall_score:.1f}分</div>
                </div>
                <div style="color: #333; font-size: 0.95em;">
                    <strong>{news_type}:</strong> {news_title}
                </div>
            </div>
"""

        html += f"""
        </div>

        <div class="footer">
            <p>本报告由 Kronos 重大利好消息挖掘系统自动生成</p>
            <p>投资有风险，入市需谨慎。本报告仅供参考，不构成投资建议。</p>
        </div>
    </div>
</body>
</html>
"""

        return html
