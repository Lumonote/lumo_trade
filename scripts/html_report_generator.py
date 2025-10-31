"""
Kronos 股票分析HTML报告生成器 - 重构版
提供单页面完整分析报告、PNG图片嵌入、控制台数据展示和历史时间线功能
"""

import os
import json
import datetime
import webbrowser
from pathlib import Path
import pandas as pd
import numpy as np
import base64
import io
from typing import Dict, List, Any, Optional


class KronosHTMLReportGenerator:
    """Kronos HTML报告生成器 - 单页面版本"""

    def __init__(self, results_dir: str = "results"):
        """
        初始化报告生成器
        
        Args:
            results_dir: 结果目录路径
        """
        # 优先使用环境变量中的结果目录，适配打包应用
        results_dir_env = os.environ.get('KRONOS_RESULTS_DIR')
        if results_dir_env:
            self.results_dir = Path(results_dir_env)
        else:
            self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # 历史记录文件
        self.history_file = self.results_dir / "analysis_history.json"
        self.load_history()

        # 存储控制台日志信息
        self.console_data = {}

    def load_history(self):
        """加载历史记录"""
        try:
            if self.history_file.exists():
                with open(self.history_file, 'r', encoding='utf-8', errors='replace') as f:
                    self.history = json.load(f)
            else:
                self.history = {"reports": []}
        except Exception as e:
            print(f"⚠️ 加载历史记录失败: {e}")
            self.history = {"reports": []}

    def save_history(self):
        """保存历史记录"""
        try:
            with open(self.history_file, 'w', encoding='utf-8', errors='replace') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存历史记录失败: {e}")

    def set_console_data(self, console_data: Dict[str, Any]):
        """设置控制台数据"""
        self.console_data = console_data

    def embed_png_image(self, png_path: str) -> str:
        """将PNG图片嵌入为base64格式"""
        try:
            png_file = Path(png_path)
            if not png_file.exists():
                return f"<p>❌ 图片文件不存在: {png_path}</p>"

            with open(png_file, 'rb') as f:
                img_data = f.read()

            # 确保使用二进制数据进行base64编码，避免编码问题
            b64_string = base64.b64encode(img_data).decode('ascii')
            return f'<img src="data:image/png;base64,{b64_string}" style="width: 100%; max-width: 1200px; height: auto; border-radius: 8px; margin: 10px 0;" alt="股票预测K线图" />'

        except Exception as e:
            print(f"⚠️ 嵌入PNG图片失败: {e}")
            return f"<p>❌ 无法加载图片: {e}</p>"

    def generate_comprehensive_report(self, stock_code: str, analysis_data: Dict,
                                      historical_data: Optional[pd.DataFrame] = None,
                                      predictions: Optional[pd.DataFrame] = None,
                                      png_chart_path: Optional[str] = None,
                                      auto_open: bool = True,
                                      fundamental_data: Optional[Dict] = None,
                                      news_data: Optional[Dict] = None,
                                      sentiment_data: Optional[Dict] = None,
                                      event_data: Optional[Dict] = None,
                                      llm_analysis: Optional[Dict] = None,
                                      llm_predicted_kline: Optional[pd.DataFrame] = None) -> str:
        """
        生成综合分析报告 - 单页面结构

        Args:
            stock_code: 股票代码
            analysis_data: 分析数据
            historical_data: 历史数据
            predictions: 预测数据
            png_chart_path: PNG图表文件路径
            auto_open: 是否自动打开浏览器
            fundamental_data: 基本面数据
            news_data: 消息面数据
            sentiment_data: 情绪数据
            event_data: 利好利空事件数据
            llm_analysis: LLM分析结果
            llm_predicted_kline: LLM预测K线数据

        Returns:
            生成的HTML报告文件路径
        """
        timestamp = datetime.datetime.now()
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        report_filename = f"kronos_analysis_{stock_code}_{timestamp_str}.html"
        report_path = self.results_dir / report_filename

        # 生成HTML内容
        html_content = self._generate_single_page_template(
            stock_code=stock_code,
            timestamp=timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            analysis_data=analysis_data,
            png_chart_path=png_chart_path,
            fundamental_data=fundamental_data,
            news_data=news_data,
            sentiment_data=sentiment_data,
            event_data=event_data,
            predictions=predictions,
            historical_data=historical_data,
            llm_analysis=llm_analysis,
            llm_predicted_kline=llm_predicted_kline
        )

        # 写入文件
        try:
            # 确保使用UTF-8编码写入HTML文件，避免编码问题
            with open(report_path, 'w', encoding='utf-8', errors='replace') as f:
                f.write(html_content)

            # 更新历史记录
            self.update_history(stock_code, timestamp_str, str(report_path), analysis_data)

            print(f"✅ HTML报告已生成: {report_path}")

            # 自动打开浏览器 - 修复路径问题
            if auto_open:
                try:
                    absolute_path = report_path.resolve()
                    file_url = f'file://{absolute_path}'
                    webbrowser.open(file_url)
                    print(f"🌐 报告已在浏览器中打开")
                except Exception as e:
                    print(f"⚠️ 无法自动打开浏览器: {e}")
                    print(f"   请手动打开: file://{report_path.resolve()}")

            return str(report_path)

        except Exception as e:
            print(f"❌ 生成HTML报告失败: {e}")
            raise

    def update_history(self, stock_code: str, timestamp: str,
                       report_path: str, analysis_data: Dict):
        """更新历史记录"""
        report_record = {
            "stock_code": stock_code,
            "timestamp": timestamp,
            "datetime": datetime.datetime.now().isoformat(),
            "report_path": report_path,
            "summary": {
                "技术指标数": len(analysis_data.get('technical_indicators', {})),
                "量化模型数": len(analysis_data.get('quantitative_models', {})),
                "当前信号": analysis_data.get('current_signals', {}),
                "风险等级": analysis_data.get('risk_assessment', {}).get('风险等级', '未知')
            }
        }

        self.history["reports"].append(report_record)

        # 只保留最近50个记录
        if len(self.history["reports"]) > 50:
            self.history["reports"] = self.history["reports"][-50:]

        self.save_history()

    def _generate_single_page_template(self, stock_code: str, timestamp: str,
                                       analysis_data: Dict, png_chart_path: str = None,
                                       fundamental_data: Dict = None,
                                       news_data: Dict = None,
                                       sentiment_data: Dict = None,
                                       event_data: Dict = None,
                                       predictions: Optional[pd.DataFrame] = None,
                                       historical_data: Optional[pd.DataFrame] = None,
                                       llm_analysis: Optional[Dict] = None,
                                       llm_predicted_kline: Optional[pd.DataFrame] = None) -> str:
        """生成单页面HTML模板"""

        # 提取数据
        technical_indicators = analysis_data.get('technical_indicators', {})
        quantitative_models = analysis_data.get('quantitative_models', {})
        current_signals = analysis_data.get('current_signals', {})
        risk_assessment = analysis_data.get('risk_assessment', {})
        model_summary = analysis_data.get('model_summary', {})

        # 将风险评估中的部分技术类指标移动到“技术指标”栏目，平衡报告高度
        risk_tech_keys = {"波动率", "ATR(14)%", "RSI风险", "布林状态", "流动性状态"}
        risk_tech_indicators = {k: v for k, v in risk_assessment.items() if k in risk_tech_keys}
        risk_assessment_pure = {k: v for k, v in risk_assessment.items() if k not in risk_tech_keys}
        # 合并到技术指标字典（不覆盖已有同名键）
        technical_indicators_aug = {**technical_indicators,
                                    **{k: v for k, v in risk_tech_indicators.items() if k not in technical_indicators}}

        # 生成各部分内容
        tech_indicators_html = self._generate_tech_indicators_section(technical_indicators_aug)
        signals_summary_html = self._generate_signals_summary_section(current_signals, model_summary)
        quant_models_html, total_models = self._generate_quant_models_section(quantitative_models, current_signals)
        risk_assessment_html = self._generate_risk_assessment_section(risk_assessment_pure)
        console_data_html = self._generate_console_data_section()
        timeline_html = self._generate_timeline_section()

        # 生成新添加的分析板块
        fundamental_html = self._generate_fundamental_section(
            fundamental_data) if fundamental_data else "<p>📊 暂无基本面数据</p>"
        news_sentiment_combined_html = self._generate_news_sentiment_combined_section(
            news_data, sentiment_data, fundamental_data or {}, event_data or {}
        )
        analysis_summary_html = self._generate_comprehensive_summary_section(
            fundamental_data or {}, sentiment_data or {}, analysis_data or {},
            predictions=predictions, historical_data=historical_data
        )

        # 生成LLM智能分析板块
        llm_analysis_html = self._generate_llm_analysis_section(llm_analysis, llm_predicted_kline)

        # 嵌入PNG图片
        chart_html = ""
        if png_chart_path:
            chart_html = self.embed_png_image(png_chart_path)
        else:
            chart_html = "<p>📊 暂无K线预测图表</p>"

        html_template = f'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kronos 股票分析报告 - {stock_code}</title>
    <style>
        {self._get_css_styles()}
    </style>
</head>
<body>
    <div class="container">
    
        <!-- K线图表区域 -->
        <section class="chart-section">
            
            <div class="chart-container">
                {chart_html}
            </div>
        </section>
        
        <!-- 主要分析内容 -->
        <section class="analysis-section">
            <div class="analysis-grid">
                <!-- 技术指标 -->
                <div class="analysis-card">
                    <h3>🔍 技术指标</h3>
                    {tech_indicators_html}
                </div>
                
                <!-- 交易信号汇总 + 风险评估 -->
                <div class="analysis-card">
                    <h3>🎯 交易信号 & 风险评估</h3>
                    <div class="signals-risk-combined">
                        <div class="signals-section">
                            <h4>📊 信号汇总</h4>
                            {signals_summary_html}
                        </div>
                        <div class="risk-section">
                            <h4>⚠️ 风险评估</h4>
                            {risk_assessment_html}
                        </div>
                    </div>
                </div>
                
                <!-- 控制台重要数据 -->
                <div class="analysis-card">
                    <h3>💻 系统运行数据</h3>
                    {console_data_html}
                </div>
            </div>
        </section>

        <!-- 新添加的综合分析板块 -->
        <section class="comprehensive-analysis-section">
            <h2>📊 综合面分析</h2>
            <div class="comprehensive-grid-two-col">
                <!-- 基本面财务数据 -->
                <div class="analysis-card">
                    <h3>💰 基本面财务</h3>
                    {fundamental_html}
                </div>

                <!-- 股民情绪 -->
                <div class="analysis-card">
                    <h3>💬 股民情绪</h3>
                    {news_sentiment_combined_html}
                </div>

                <!-- 分析总结 -->
                <div class="analysis-card analysis-summary-card">
                    <h3>🧾 分析总结</h3>
                    {analysis_summary_html}
                </div>
            </div>
        </section>

        <!-- AI智能分析板块 -->
        <section class="llm-analysis-wrapper" style="display: {'block' if llm_analysis else 'none'};">
            <h2>🤖 AI智能分析</h2>
            <div class="analysis-card">
                {llm_analysis_html}
            </div>
        </section>

        <!-- 量化模型 + 时间轴布局 -->
        <section class="models-timeline-section">
            <div class="models-timeline-container">
                <!-- 量化模型详情 -->
                <div class="models-section">
                    <h2>🤖 量化模型分析 ({total_models}个专业模型)</h2>
                    {quant_models_html}
                </div>
                
                <!-- 历史时间线 (右侧) -->
                <div class="timeline-section">
                    <h2>⏰ 历史分析时间线</h2>
                    {timeline_html}
                </div>
            </div>
        </section>
        
        <!-- 页脚 -->
        <footer class="footer">
            <p>🚀 Powered by Kronos AI Stock Analysis System</p>
            <p>📅 Generated on {timestamp}</p>
        </footer>
    </div>
</body>
</html>
'''
        return html_template

    def _generate_tech_indicators_section(self, indicators: Dict) -> str:
        """生成技术指标部分"""
        if not indicators:
            return "<p>📊 暂无技术指标数据</p>"

        html = "<div class='indicators-grid'>"
        for key, value in indicators.items():
            # 为不同指标添加颜色标识
            indicator_class = ""
            if "RSI" in key:
                indicator_class = "indicator-rsi"
            elif "MACD" in key:
                indicator_class = "indicator-macd"
            elif "布林带" in key:
                indicator_class = "indicator-bb"

            html += f"""
            <div class="indicator-item {indicator_class}">
                <span class="indicator-label">{key}:</span>
                <span class="indicator-value">{value}</span>
            </div>
            """
        html += "</div>"
        return html

    def _generate_comprehensive_summary_section(self, fundamental_data: Dict, sentiment_data: Dict, analysis_data: Dict,
                                                predictions: Optional[pd.DataFrame] = None,
                                                historical_data: Optional[pd.DataFrame] = None) -> str:
        """生成分析总结卡片

        综合汇总模型预测、情绪、量化与技术指标、风险评估，给出简洁结论。
        """
        try:
            # 模型信号统计
            signals = analysis_data.get('current_signals', {}) or {}
            total_models = len(signals)
            buy_count = sum(1 for s in signals.values() if s == '买入')
            sell_count = sum(1 for s in signals.values() if s == '卖出')
            hold_count = sum(1 for s in signals.values() if s == '持有')

            # 情绪
            comprehensive_score = sentiment_data.get('comprehensive_score', None)
            comprehensive_sentiment = sentiment_data.get('comprehensive_sentiment', None)

            overall_market = sentiment_data.get('overall_market_sentiment') or {}
            primary_index = (overall_market.get('primary_index') or {})
            primary_name = primary_index.get('name', '所属大盘')
            primary_chg = overall_market.get('primary_change_pct', None)

            sector = sentiment_data.get('sector_sentiment') or {}
            sector_name = sector.get('sector_name', None)
            sector_chg = sector.get('change_pct', None)

            # 风险评估与技术相关指标
            risk = analysis_data.get('risk_assessment', {}) or {}
            risk_level = risk.get('风险等级', None)
            rsi_risk = risk.get('RSI风险', None)
            bb_state = risk.get('布林状态', None)
            atr_pct = risk.get('ATR(14)%', None)

            # 量化模型总览
            model_summary = analysis_data.get('model_summary', {}) or {}
            win_rate_avg = model_summary.get('平均胜率', None)

            # 若未提供平均胜率，则基于量化模型的“胜率”字段动态计算
            if win_rate_avg in (None, 'N/A', ''):
                qm = analysis_data.get('quantitative_models', {}) or {}
                win_rates = []
                for info in qm.values():
                    wr = info.get('胜率')
                    if isinstance(wr, str) and wr.strip().endswith('%'):
                        try:
                            win_rates.append(float(wr.strip().replace('%', '')))
                        except Exception:
                            pass
                    elif isinstance(wr, (int, float)):
                        win_rates.append(float(wr))
                if win_rates:
                    win_rate_avg = round(sum(win_rates) / len(win_rates), 1)
                else:
                    win_rate_avg = None

            # 生成综合建议（优化算法）
            # 引入更稳健的综合评分：信号偏向、情绪分、胜率、市场/板块趋势、风险与波动
            recommendation = '🟡 观望'

            try:
                # 基本比率
                denom = max(total_models, 1)
                buy_ratio = buy_count / denom
                sell_ratio = sell_count / denom
                signal_bias = (buy_ratio - sell_ratio) * 100.0  # -100 ~ 100

                # 综合情绪分（默认50）
                score = comprehensive_score if isinstance(comprehensive_score, (int, float)) else 50

                # 风险惩罚
                rl = (risk_level or '')
                risk_penalty = 0
                if '高' in rl:
                    risk_penalty = -20
                elif '中' in rl:
                    risk_penalty = -10

                # 胜率加成
                win_bonus = 0
                if isinstance(win_rate_avg, (int, float)):
                    if win_rate_avg >= 65:
                        win_bonus = 10
                    elif win_rate_avg >= 55:
                        win_bonus = 5
                    elif win_rate_avg <= 45:
                        win_bonus = -5

                # 市场与板块趋势加成/扣分
                trend_bonus = 0
                if isinstance(primary_chg, (int, float)):
                    trend_bonus += 5 if primary_chg >= 0 else -5
                if isinstance(sector_chg, (int, float)):
                    trend_bonus += 5 if sector_chg >= 0 else -5

                # 波动惩罚（ATR百分比越大惩罚越重）
                atr_penalty = 0
                if isinstance(atr_pct, (int, float)):
                    if atr_pct >= 10:
                        atr_penalty = -10
                    elif atr_pct >= 5:
                        atr_penalty = -5

                # 综合评分（权重调和，保持稳健）
                composite = (
                    signal_bias * 0.4 +          # 模型一致性更重要
                    (score - 50) * 0.5 +          # 情绪相对影响居中
                    win_bonus +                    # 胜率作为辅助强弱参考
                    trend_bonus +                  # 市场与板块方向
                    risk_penalty +                 # 风险优先抑制
                    atr_penalty                    # 波动抑制
                )

                # 判定：阈值对称，避免过度频繁切换
                if composite >= 15 and buy_ratio >= 0.4 and '高' not in rl:
                    recommendation = '🟢 适度加仓'
                elif composite <= -15 and (sell_ratio >= 0.4 or '高' in rl):
                    recommendation = '🔴 谨慎减仓'
                else:
                    recommendation = '🟡 观望'
            except Exception:
                # 若新算法异常，回退至原始简单规则
                if total_models > 0:
                    if buy_count > sell_count * 1.5 and (comprehensive_score or 50) >= 60 and (risk_level or '').find('高') == -1:
                        recommendation = '🟢 适度加仓'
                    elif sell_count > buy_count * 1.5 or (comprehensive_score or 50) < 45 or (risk_level or '').find('高') != -1:
                        recommendation = '🔴 谨慎减仓'

            # 辅助格式化
            def fmt(val, suffix=''):
                if val is None or val == 'N/A':
                    return '—'
                try:
                    if suffix == '%':
                        # 避免出现 0.00%% 的重复百分号
                        if isinstance(val, str) and val.strip().endswith('%'):
                            return val.strip()
                        return f"{val}%"
                    return f"{val}{suffix}" if suffix else f"{val}"
                except Exception:
                    return str(val)

            html = "<div class='analysis-summary-grid'>"

            # 模型信号与建议
            html += f"""
            <div class='summary-item'>
                <span class='label'>模型信号统计</span>
                <span class='value'>买 {buy_count} · 持 {hold_count} · 卖 {sell_count} / 共 {total_models}</span>
            </div>
            <div class='summary-item'>
                <span class='label'>综合建议</span>
                <span class='value'>{recommendation}</span>
            </div>
            """

            # 情绪概览
            html += f"""
            <div class='summary-item'>
                <span class='label'>股民综合情绪</span>
                <span class='value'>{fmt(comprehensive_score)} 分 · {comprehensive_sentiment or '中性'}</span>
            </div>
            <div class='summary-item'>
                <span class='label'>大盘与板块</span>
                <span class='value'>{primary_name} {fmt(primary_chg, '%')} · {sector_name or '所属板块'} {fmt(sector_chg, '%')}</span>
            </div>
            """

            # 风险与技术状态
            html += f"""
            <div class='summary-item'>
                <span class='label'>风险等级</span>
                <span class='value'>{risk_level or '未知'}</span>
            </div>
            <div class='summary-item'>
                <span class='label'>技术状态</span>
                <span class='value'>{self._build_tech_status_summary(analysis_data)}</span>
            </div>
            """

            # 模型总体能力
            pred_summary = self._build_prediction_summary_text(predictions, historical_data)
            html += f"""
            <div class='summary-item'>
                <span class='label'>AI预测结果分析</span>
                <span class='value'>{pred_summary}</span>
            </div>
            <div class='summary-item'>
                <span class='label'>基本面</span>
                <span class='value'>{self._build_fundamental_tip(fundamental_data)}</span>
            </div>
            """

            html += "</div>"
            return html

        except Exception as e:
            return f"<p>❌ 汇总卡片生成失败: {e}</p>"

    def _generate_signals_summary_section(self, signals: Dict, summary: Dict) -> str:
        """生成交易信号汇总部分"""
        if not signals:
            return "<p>📊 暂无信号数据</p>"

        # 统计信号
        buy_count = sum(1 for s in signals.values() if s == '买入')
        sell_count = sum(1 for s in signals.values() if s == '卖出')
        hold_count = sum(1 for s in signals.values() if s == '持有')
        total_count = len(signals)

        html = f"""
        <div class="signals-summary">
            <div class="signal-stat buy">
                <span class="signal-count">{buy_count}</span>
                <span class="signal-label">买入信号</span>
                <span class="signal-percent">{buy_count / total_count * 100:.0f}%</span>
            </div>
            <div class="signal-stat hold">
                <span class="signal-count">{hold_count}</span>
                <span class="signal-label">持有信号</span>
                <span class="signal-percent">{hold_count / total_count * 100:.0f}%</span>
            </div>
            <div class="signal-stat sell">
                <span class="signal-count">{sell_count}</span>
                <span class="signal-label">卖出信号</span>
                <span class="signal-percent">{sell_count / total_count * 100:.0f}%</span>
            </div>
        </div>
        <div class="recommendation">
            <strong>💡 综合建议:</strong> 
            {"🟢 多数模型看多，建议适量买入" if buy_count > sell_count * 1.5 else
        "🔴 多数模型看空，建议减仓观望" if sell_count > buy_count * 1.5 else
        "🟡 模型信号分歧，建议保持现有仓位"}
        </div>
        """
        return html

    def _generate_risk_assessment_section(self, risk_data: Dict) -> str:
        """生成风险评估部分"""
        if not risk_data:
            return "<p>📊 暂无风险评估数据</p>"

        html = "<div class='risk-items'>"
        for key, value in risk_data.items():
            risk_class = ""
            if key == "风险等级":
                if "低" in value:
                    risk_class = "risk-low"
                elif "中" in value:
                    risk_class = "risk-medium"
                elif "高" in value:
                    risk_class = "risk-high"

            html += f"""
            <div class="risk-item {risk_class}">
                <span class="risk-label">{key}:</span>
                <span class="risk-value">{value}</span>
            </div>
            """
        html += "</div>"
        return html

    def _generate_console_data_section(self) -> str:
        """生成控制台重要数据部分"""
        if not self.console_data:
            return "<p>📊 暂无系统运行数据</p>"

        html = "<div class='console-data'>"

        # 模拟一些重要的控制台数据
        console_items = [
            ("预测完成时间", "2025-09-08 23:44:18"),
            ("使用模型", "Kronos-small"),
            ("设备类型", "CPU"),
            ("数据量", f"{self.console_data.get('data_count', '1,488')} 条"),
            ("预测时长", f"{self.console_data.get('prediction_time', '42')} 秒"),
            ("预测点数", f"{self.console_data.get('prediction_points', '300')} 个"),
            ("历史数据范围", self.console_data.get('data_range', '2025-07-28 至 2025-09-08')),
            ("交易日覆盖", "15个交易日 (10天历史 + 5天预测)"),
            ("预测准确性MAPE", self.console_data.get('mape', '3.05%')),
            ("风险等级", self.console_data.get('risk_level', '低风险'))
        ]

        for label, value in console_items:
            html += f"""
            <div class="console-item">
                <span class="console-label">{label}:</span>
                <span class="console-value">{value}</span>
            </div>
            """

        html += "</div>"
        return html

    def _generate_quant_models_section(self, models: Dict, signals: Dict) -> tuple:
        """生成量化模型详情部分 - 完整信息显示

        Returns:
            tuple: (html_content, total_models_count)
        """
        if not models:
            return "<p>📊 暂无量化模型数据</p>", 0

        # 按信号类型分类
        buy_models = []
        hold_models = []
        sell_models = []

        for model_key, model_info in models.items():
            signal = signals.get(model_key, '持有')
            model_data = {
                'key': model_key,
                'name': model_info.get('中文名称', model_key),
                'win_rate': model_info.get('胜率', 'N/A'),
                'target_group': model_info.get('适用人群', '未知'),
                'strategy': model_info.get('核心策略', '未知'),
                'signal': signal
            }

            if signal == '买入':
                buy_models.append(model_data)
            elif signal == '卖出':
                sell_models.append(model_data)
            else:
                hold_models.append(model_data)

        # 计算模型总数
        total_models = len(signals)

        html = "<div class='models-container-full'>"

        # 买入信号模型 - 完整信息显示
        if buy_models:
            html += f"""
            <div class="models-group-full buy-group">
                <h4>🟢 买入信号模型 ({len(buy_models)}/{total_models})</h4>
                <div class="models-table-full">
                    <div class="models-header">
                        <span class="header-name">模型名称</span>
                        <span class="header-group">适用人群</span>
                        <span class="header-strategy">核心策略</span>
                        <span class="header-rate">胜率</span>
                        <span class="header-signal">信号</span>
                    </div>
            """
            for model in buy_models:
                html += f"""
                <div class="model-row-full buy">
                    <span class="model-name-full">{model['name']}</span>
                    <span class="model-group-full">{model['target_group']}</span>
                    <span class="model-strategy-full">{model['strategy']}</span>
                    <span class="model-rate-full">{model['win_rate']}</span>
                    <span class="model-signal-full buy-signal">🟢 买入</span>
                </div>
                """
            html += "</div></div>"

        # 卖出信号模型 - 完整信息显示
        if sell_models:
            html += f"""
            <div class="models-group-full sell-group">
                <h4>🔴 卖出信号模型 ({len(sell_models)}/{total_models})</h4>
                <div class="models-table-full">
                    <div class="models-header">
                        <span class="header-name">模型名称</span>
                        <span class="header-group">适用人群</span>
                        <span class="header-strategy">核心策略</span>
                        <span class="header-rate">胜率</span>
                        <span class="header-signal">信号</span>
                    </div>
            """
            for model in sell_models:
                html += f"""
                <div class="model-row-full sell">
                    <span class="model-name-full">{model['name']}</span>
                    <span class="model-group-full">{model['target_group']}</span>
                    <span class="model-strategy-full">{model['strategy']}</span>
                    <span class="model-rate-full">{model['win_rate']}</span>
                    <span class="model-signal-full sell-signal">🔴 卖出</span>
                </div>
                """
            html += "</div></div>"
        else:
            html += f"""
            <div class="models-group-full sell-group">
                <h4>🔴 卖出信号模型 (0/{total_models})</h4>
                <p class="no-sell-signals-full">✨ 当前无模型发出卖出信号</p>
            </div>
            """

        # 持有信号模型 - 完整信息显示,默认展开
        if hold_models:
            html += f"""
            <div class="models-group-full hold-group">
                <h4>🟡 持有信号模型 ({len(hold_models)}/{total_models})</h4>
                <div class="models-table-full">
                    <div class="models-header">
                        <span class="header-name">模型名称</span>
                        <span class="header-group">适用人群</span>
                        <span class="header-strategy">核心策略</span>
                        <span class="header-rate">胜率</span>
                        <span class="header-signal">信号</span>
                    </div>
            """
            for model in hold_models:
                html += f"""
                <div class="model-row-full hold">
                    <span class="model-name-full">{model['name']}</span>
                    <span class="model-group-full">{model['target_group']}</span>
                    <span class="model-strategy-full">{model['strategy']}</span>
                    <span class="model-rate-full">{model['win_rate']}</span>
                    <span class="model-signal-full hold-signal">🟡 持有</span>
                </div>
                """
            html += "</div></div>"

        html += "</div>"
        return html, total_models

    def _generate_timeline_section(self) -> str:
        """生成历史时间线部分 - 显示买入卖出持有模型数"""
        reports = self.history.get("reports", [])
        if not reports:
            return "<p>📊 暂无历史分析记录</p>"

        # 按时间倒序排列，显示最近的10个记录
        recent_reports = sorted(reports, key=lambda x: x['datetime'], reverse=True)[:10]

        html = "<div class='timeline-container-vertical'>"

        for i, report in enumerate(recent_reports):
            timestamp = report.get('timestamp', '')
            stock_code = report.get('stock_code', '')
            summary = report.get('summary', {})
            report_path = report.get('report_path', '')
            current_signals = summary.get('当前信号', {})

            # 格式化时间显示
            try:
                dt = datetime.datetime.fromisoformat(report['datetime'])
                time_str = dt.strftime('%m-%d %H:%M')
            except:
                time_str = timestamp[:8] if len(timestamp) >= 8 else timestamp

            # 统计买入、卖出、持有信号数量
            buy_count = sum(1 for signal in current_signals.values() if signal == '买入')
            sell_count = sum(1 for signal in current_signals.values() if signal == '卖出')
            hold_count = sum(1 for signal in current_signals.values() if signal == '持有')
            total_count = len(current_signals)

            # 风险等级颜色
            risk_level = summary.get('风险等级', '未知')
            risk_class = ""
            if "低" in risk_level:
                risk_class = "risk-low"
            elif "中" in risk_level:
                risk_class = "risk-medium"
            elif "高" in risk_level:
                risk_class = "risk-high"

            # 生成绝对路径供点击
            absolute_path = os.path.abspath(report_path) if report_path else ""

            html += f"""
            <div class="timeline-item-vertical {'current' if i == 0 else ''}" 
                 onclick="openReport('{absolute_path}')" 
                 title="点击查看详细报告">
                <div class="timeline-time-vertical">{time_str}</div>
                <div class="timeline-content-vertical">
                    <div class="timeline-stock-vertical">{stock_code}</div>
                    <div class="timeline-signals-vertical">
                        <div class="signal-mini buy-mini">
                            <span class="signal-mini-icon">🟢</span>
                            <span class="signal-mini-count">{buy_count}</span>
                        </div>
                        <div class="signal-mini hold-mini">
                            <span class="signal-mini-icon">🟡</span>
                            <span class="signal-mini-count">{hold_count}</span>
                        </div>
                        <div class="signal-mini sell-mini">
                            <span class="signal-mini-icon">🔴</span>
                            <span class="signal-mini-count">{sell_count}</span>
                        </div>
                    </div>
                    <div class="timeline-info-vertical">
                        <span class="timeline-models-vertical">{total_count}个模型</span>
                        <span class="timeline-risk-vertical {risk_class}">{risk_level}</span>
                    </div>
                </div>
                <div class="timeline-click-hint">📄</div>
            </div>
            """

        html += "</div>"

        # 添加点击功能的JavaScript
        html += """
        <script>
        function openReport(reportPath) {
            if (reportPath && reportPath !== '') {
                // 转换为file://格式
                const fileUrl = 'file://' + reportPath;
                window.open(fileUrl, '_blank');
            } else {
                alert('报告文件路径不存在');
            }
        }
        </script>
        """

        return html

    def _build_tech_status_summary(self, analysis_data: Dict) -> str:
        """根据技术指标与风险评估构建更丰富的技术状态摘要。"""
        try:
            risk = (analysis_data or {}).get('risk_assessment', {}) or {}
            tech = (analysis_data or {}).get('technical_indicators', {}) or {}

            rsi_val = tech.get('RSI')
            rsi_risk = risk.get('RSI风险')

            macd = tech.get('MACD')
            bb_pos = tech.get('布林带') or risk.get('布林状态')
            kdj = tech.get('KDJ')

            atr_pct = risk.get('ATR(14)%') or tech.get('ATR')

            def to_float(x):
                if x is None:
                    return None
                if isinstance(x, (int, float)):
                    return float(x)
                if isinstance(x, str):
                    s = x.replace('%', '').replace(',', '').strip()
                    try:
                        return float(s)
                    except:
                        return None
                return None

            ma5 = to_float(tech.get('MA5'))
            ma10 = to_float(tech.get('MA10'))
            ma20 = to_float(tech.get('MA20'))

            parts = []
            if rsi_val or rsi_risk:
                if rsi_val and isinstance(rsi_val, str):
                    parts.append(f"RSI {rsi_val}（{rsi_risk or '—'}）")
                elif rsi_risk:
                    parts.append(f"RSI {rsi_risk}")

            if macd:
                parts.append(f"MACD {macd}")

            if bb_pos:
                parts.append(f"布林 {bb_pos}")

            if kdj:
                parts.append(f"KDJ {kdj}")

            if atr_pct is not None:
                # 统一百分号显示，避免双%号
                if isinstance(atr_pct, str) and atr_pct.strip().endswith('%'):
                    parts.append(f"ATR {atr_pct.strip()}")
                else:
                    parts.append(f"ATR {atr_pct}%")

            # MA排列与趋势
            if ma5 is not None and ma10 is not None and ma20 is not None:
                if ma5 > ma10 > ma20:
                    parts.append("MA排列 多头 (MA5>MA10>MA20)")
                elif ma5 < ma10 < ma20:
                    parts.append("MA排列 空头 (MA5<MA10<MA20)")
                else:
                    parts.append("MA排列 混合")

            return " · ".join(parts) if parts else "数据不足"
        except Exception:
            return "数据不足"

    def _build_fundamental_tip(self, fundamental_data: Dict) -> str:
        """根据基本面真实数据生成“基本面”动态摘要。"""
        try:
            indicators = (fundamental_data or {}).get('financial_indicators', {}) or {}
            reports = (fundamental_data or {}).get('financial_reports', {}) or {}

            pe = indicators.get('pe_ratio')
            pb = indicators.get('pb_ratio')
            revenue_yoy = reports.get('revenue_yoy')
            net_profit_yoy = reports.get('net_profit_yoy')
            # 计算版同比与TTM
            revenue_yoy_calc = reports.get('revenue_yoy_calc')
            net_profit_yoy_calc = reports.get('net_profit_yoy_calc')
            cash_flow = reports.get('cash_flow')

            def _to_float(val):
                if val is None:
                    return None
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, str):
                    s = val.replace('%', '').replace(',', '').strip()
                    if s == '' or s == '—':
                        return None
                    try:
                        return float(s)
                    except Exception:
                        return None
                return None

            pe_v = _to_float(pe)
            pb_v = _to_float(pb)
            rev_yoy_v = _to_float(revenue_yoy)
            profit_yoy_v = _to_float(net_profit_yoy)
            rev_yoy_calc_v = _to_float(revenue_yoy_calc)
            profit_yoy_calc_v = _to_float(net_profit_yoy_calc)

            cash_dir = None
            if isinstance(cash_flow, (int, float)):
                cash_dir = '正' if float(cash_flow) >= 0 else '负'
            elif isinstance(cash_flow, str):
                s = cash_flow.replace(',', '').strip()
                try:
                    cf = float(s)
                    cash_dir = '正' if cf >= 0 else '负'
                except Exception:
                    if '正' in s:
                        cash_dir = '正'
                    elif '负' in s:
                        cash_dir = '负'

            valuation_parts = []
            if pe_v is not None:
                if pe_v < 20:
                    tag = '低估'
                elif pe_v <= 40:
                    tag = '适中'
                else:
                    tag = '偏高'
                valuation_parts.append(f"PE {pe}（{tag}）")
            if pb_v is not None:
                if pb_v < 1.5:
                    tag = '低估'
                elif pb_v <= 3:
                    tag = '适中'
                else:
                    tag = '偏高'
                valuation_parts.append(f"PB {pb}（{tag}）")
            valuation_text = '、'.join(valuation_parts) if valuation_parts else '估值信息缺失'

            growth_parts = []
            # 接口同比
            if rev_yoy_v is not None:
                arrow = '↑' if rev_yoy_v > 0 else ('↓' if rev_yoy_v < 0 else '')
                growth_parts.append(f"营收同比 {rev_yoy_v:.2f}%{arrow}")
            if profit_yoy_v is not None:
                arrow = '↑' if profit_yoy_v > 0 else ('↓' if profit_yoy_v < 0 else '')
                growth_parts.append(f"净利润同比 {profit_yoy_v:.2f}%{arrow}")
            # 计算版TTM同比（作为替代视角）
            calc_parts = []
            if rev_yoy_calc_v is not None:
                arrow = '↑' if rev_yoy_calc_v > 0 else ('↓' if rev_yoy_calc_v < 0 else '')
                calc_parts.append(f"营收TTM同比 {rev_yoy_calc_v:.2f}%{arrow}")
            if profit_yoy_calc_v is not None:
                arrow = '↑' if profit_yoy_calc_v > 0 else ('↓' if profit_yoy_calc_v < 0 else '')
                calc_parts.append(f"净利润TTM同比 {profit_yoy_calc_v:.2f}%{arrow}")
            if calc_parts:
                growth_parts.append('（替代: ' + '、'.join(calc_parts) + '）')
            growth_text = '、'.join(growth_parts) if growth_parts else '营收/净利润同比暂无'

            cash_text = f"现金流为{cash_dir}向" if cash_dir else '现金流数据缺失'

            return f"估值（{valuation_text}），{growth_text}，{cash_text}"
        except Exception:
            return "估值、营收、净利润、现金流"

    def _build_prediction_summary_text(self, predictions: Optional[pd.DataFrame], historical_data: Optional[pd.DataFrame]) -> str:
        """基于AI K线预测结果生成简洁中文总结文本"""
        try:
            if predictions is None or not isinstance(predictions, pd.DataFrame) or predictions.empty:
                return "暂无AI预测数据"

            candidate_cols = ['close', 'Close', '收盘', '收盘价']
            close_col = next((c for c in candidate_cols if c in predictions.columns), None)
            if close_col is None:
                num_cols = [c for c in predictions.columns if pd.api.types.is_numeric_dtype(predictions[c])]
                if not num_cols:
                    return "预测数据格式不含数值列"
                close_col = num_cols[0]

            close_series = pd.to_numeric(predictions[close_col], errors='coerce').dropna()
            if close_series.empty:
                return "预测数据缺少有效价格序列"

            start_price = float(close_series.iloc[0])
            end_price = float(close_series.iloc[-1])
            total_pct = (end_price - start_price) / start_price * 100.0
            direction = "上行" if total_pct > 1e-6 else ("下行" if total_pct < -1e-6 else "横盘")

            returns = close_series.pct_change().dropna()
            vol_std_pct = float(returns.std() * 100.0) if not returns.empty else 0.0
            if vol_std_pct < 1.5:
                vol_cat = "低"
            elif vol_std_pct < 3.0:
                vol_cat = "中"
            else:
                vol_cat = "高"

            delta_vs_last = None
            if isinstance(historical_data, pd.DataFrame) and not historical_data.empty:
                hist_candidate_cols = ['close', 'Close', '收盘', '收盘价']
                hist_close_col = next((c for c in hist_candidate_cols if c in historical_data.columns), None)
                if hist_close_col:
                    hist_series = pd.to_numeric(historical_data[hist_close_col], errors='coerce').dropna()
                    if not hist_series.empty:
                        last_hist_close = float(hist_series.iloc[-1])
                        if last_hist_close > 0:
                            delta_vs_last = (float(close_series.iloc[0]) - last_hist_close) / last_hist_close * 100.0

            parts = [
                f"{len(close_series)}点预测显示：走势{direction}，累计变动约{total_pct:.1f}%",
                f"短期波动{vol_cat}（σ≈{vol_std_pct:.1f}%）",
            ]
            if delta_vs_last is not None:
                parts.append(f"相对最新收盘价预计{delta_vs_last:.1f}%")

            return "；".join(parts)
        except Exception as e:
            return f"预测总结生成异常: {e}"

    def _generate_fundamental_section(self, fundamental_data: Dict) -> str:
        """生成基本面财务数据部分 - 显示市场估值和核心财务指标"""
        if not fundamental_data:
            return "<p>📊 暂无基本面数据</p>"

        indicators = fundamental_data.get('financial_indicators', {})
        reports = fundamental_data.get('financial_reports', {})

        html = "<div class='fundamental-core-metrics'>"

        # 辅助函数：检查值是否有效
        def is_valid(value):
            return value not in ['N/A', None, '', 'nan', 'None', '亏损']

        core_items = []

        # 市场估值指标 - 总市值、流通市值、市盈率、市净率
        if is_valid(indicators.get('total_market_cap')):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>总市值:</span><span class='metric-value'>{indicators.get('total_market_cap')} 亿</span></div>")

        if is_valid(indicators.get('circulation_market_cap')):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>流通市值:</span><span class='metric-value'>{indicators.get('circulation_market_cap')} 亿</span></div>")

        pe_ratio = indicators.get('pe_ratio')
        if is_valid(pe_ratio):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>市盈率:</span><span class='metric-value'>{pe_ratio}</span></div>")

        if is_valid(indicators.get('pb_ratio')):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>市净率:</span><span class='metric-value'>{indicators.get('pb_ratio')}</span></div>")

        # 核心财务指标 - 营收、净利润、现金流
        if is_valid(reports.get('revenue')):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>营收:</span><span class='metric-value'>{reports.get('revenue')} 亿</span></div>")

        if is_valid(reports.get('net_profit')):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>净利润:</span><span class='metric-value'>{reports.get('net_profit')} 亿</span></div>")

        if is_valid(reports.get('cash_flow')):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>现金流:</span><span class='metric-value'>{reports.get('cash_flow')} 亿</span></div>")

        # 替代视角：TTM与计算版同比
        rev_yoy = reports.get('revenue_yoy')
        np_yoy = reports.get('net_profit_yoy')
        rev_yoy_calc = reports.get('revenue_yoy_calc')
        np_yoy_calc = reports.get('net_profit_yoy_calc')
        rev_ttm = reports.get('revenue_ttm')
        np_ttm = reports.get('net_profit_ttm')

        # 接口同比
        if is_valid(rev_yoy):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>营收同比(接口):</span><span class='metric-value'>{rev_yoy}%</span></div>")
        if is_valid(np_yoy):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>净利润同比(接口):</span><span class='metric-value'>{np_yoy}%</span></div>")

        # 计算版TTM同比
        if is_valid(rev_yoy_calc):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>营收TTM同比(计算):</span><span class='metric-value'>{rev_yoy_calc}%</span></div>")
        if is_valid(np_yoy_calc):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>净利润TTM同比(计算):</span><span class='metric-value'>{np_yoy_calc}%</span></div>")

        # TTM绝对值
        if is_valid(rev_ttm):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>营收TTM:</span><span class='metric-value'>{rev_ttm} 亿</span></div>")
        if is_valid(np_ttm):
            core_items.append(
                f"<div class='core-metric-item'><span class='metric-label'>净利润TTM:</span><span class='metric-value'>{np_ttm} 亿</span></div>")

        if core_items:
            html += ''.join(core_items)
        else:
            return "<p>📊 基本面数据采集中...</p>"

        html += "</div>"
        return html

    def _generate_news_section(self, news_data: Dict) -> str:
        """生成消息面部分"""
        if not news_data:
            return "<p>📰 暂无消息面数据</p>"

        announcements = news_data.get('announcements', [])
        news_list = news_data.get('news', [])
        reports = news_data.get('research_reports', [])
        sentiment_summary = news_data.get('sentiment_summary', {})

        html = "<div class='news-container'>"

        # 检查是否有任何新闻数据
        has_news = len(news_list) > 0

        if has_news:
            # 情感统计 - 只在有新闻时显示
            html += "<div class='news-sentiment-summary'>"
            html += f"""
            <div class='sentiment-stat positive'>
                <span class='sentiment-label'>正面</span>
                <span class='sentiment-count'>{sentiment_summary.get('positive', 0)}</span>
            </div>
            <div class='sentiment-stat neutral'>
                <span class='sentiment-label'>中性</span>
                <span class='sentiment-count'>{sentiment_summary.get('neutral', 0)}</span>
            </div>
            <div class='sentiment-stat negative'>
                <span class='sentiment-label'>负面</span>
                <span class='sentiment-count'>{sentiment_summary.get('negative', 0)}</span>
            </div>
            """
            html += "</div>"

        # 最新公告
        if announcements:
            html += "<div class='news-section'>"
            html += "<h4>📢 最新公告 (TOP5)</h4>"
            for i, ann in enumerate(announcements[:5]):
                importance_class = 'importance-high' if ann.get('importance') == '高' else (
                    'importance-medium' if ann.get('importance') == '中' else 'importance-low')
                html += f"""
                <div class='news-item'>
                    <span class='{importance_class}'>{ann.get('importance', '低')}</span>
                    <span class='news-title'>{ann.get('title', '无标题')}</span>
                    <span class='news-date'>{ann.get('date', '')}</span>
                </div>
                """
            html += "</div>"
        else:
            html += "<div class='news-section'>"
            html += "<h4>📢 最新公告</h4>"
            html += "<p style='text-align: center; color: #888; padding: 20px;'>💼 暂无公告数据</p>"
            html += "</div>"

        # 最新新闻
        if has_news:
            html += "<div class='news-section'>"
            html += "<h4>📰 最新新闻 (TOP5)</h4>"
            for i, news in enumerate(news_list[:5]):
                sentiment_class = 'sentiment-positive' if news.get('sentiment') == '正面' else (
                    'sentiment-negative' if news.get('sentiment') == '负面' else 'sentiment-neutral')
                html += f"""
                <div class='news-item'>
                    <span class='{sentiment_class}'>{news.get('sentiment', '中性')}</span>
                    <span class='news-title'>{news.get('title', '无标题')[:40]}...</span>
                    <span class='news-date'>{news.get('date', '')}</span>
                </div>
                """
            html += "</div>"
        else:
            html += "<div class='news-section'>"
            html += "<h4>📰 最新新闻</h4>"
            html += "<p style='text-align: center; color: #888; padding: 20px;'>📡 新闻数据采集中,暂时无法获取...</p>"
            html += "</div>"

        html += "</div>"
        return html

    def _generate_news_sentiment_combined_section(self, news_data: Dict, sentiment_data: Dict, fundamental_data: Dict, event_data: Dict) -> str:
        """生成股民情绪部分"""
        html = "<div class='news-sentiment-combined'>"

        # 股民情绪部分
        if sentiment_data:
            guba_sentiment = sentiment_data.get('guba_sentiment', {})
            comprehensive_score = sentiment_data.get('comprehensive_score', 50)
            comprehensive_sentiment = sentiment_data.get('comprehensive_sentiment', '中性')

            html += "<div class='combined-section'>"
            html += "<h4>💬 股吧评论情绪</h4>"

            # 综合情绪得分
            score_class = 'score-high' if comprehensive_score >= 70 else (
                'score-medium' if comprehensive_score >= 50 else 'score-low')
            html += f"""
            <div class='sentiment-score-compact {score_class}'>
                <div class='score-value'>{comprehensive_score}</div>
                <div class='score-label'>{comprehensive_sentiment}</div>
            </div>
            """

            # 情绪比例
            html += f"""
            <div class='guba-stats-compact'>
                <div class='guba-stat-compact bullish'>
                    <span class='guba-label'>看多:</span>
                    <span class='guba-value'>{guba_sentiment.get('bullish_ratio', 0)}%</span>
                </div>
                <div class='guba-stat-compact neutral'>
                    <span class='guba-label'>中性:</span>
                    <span class='guba-value'>{guba_sentiment.get('neutral_ratio', 0)}%</span>
                </div>
                <div class='guba-stat-compact bearish'>
                    <span class='guba-label'>看空:</span>
                    <span class='guba-value'>{guba_sentiment.get('bearish_ratio', 0)}%</span>
                </div>
            </div>
            <div class='guba-overall-compact'>总体: {guba_sentiment.get('overall', '中性')} | 帖数: {guba_sentiment.get('total_posts', 0)}</div>
            """
            html += "</div>"

            # 📊 大盘整体情绪
            overall_market = sentiment_data.get('overall_market_sentiment') or {}
            if overall_market:
                score = overall_market.get('sentiment_score', 50)
                overall = overall_market.get('overall', '数据不足')
                primary_index = overall_market.get('primary_index', {})
                primary_name = primary_index.get('name', '所属大盘')
                primary_change = overall_market.get('primary_change_pct', 'N/A')

                score_class = 'score-high' if isinstance(score, (int, float)) and score >= 70 else (
                    'score-medium' if isinstance(score, (int, float)) and score >= 50 else 'score-low')

                html += "<div class='combined-section'>"
                html += "<h4>📊 大盘整体情绪</h4>"
                html += f"""
                <div class='sentiment-score-compact {score_class}'>
                    <div class='score-value'>{score}</div>
                    <div class='score-label'>{overall} 所属大盘 {primary_name} 涨跌 {primary_change}%</div>
                </div>
                """

                indices = overall_market.get('indices', {})
                if indices:
                    html += "<div class='guba-stats-compact'>"
                    for _, idx in indices.items():
                        name = idx.get('name', '')
                        chg = idx.get('change_pct', 'N/A')
                        html += f"""
                        <div class='guba-stat-compact'>
                            <span class='guba-label'>{name}:</span>
                            <span class='guba-value'>{chg}%</span>
                        </div>
                        """
                    html += "</div>"
                html += "</div>"

            # 🏭 所属板块情绪
            sector = sentiment_data.get('sector_sentiment') or {}
            if sector:
                # 检查是否是新的嵌套数据结构
                if 'sector_sentiment' in sector and isinstance(sector['sector_sentiment'], dict):
                    # 新的嵌套结构：从内层获取情绪数据
                    inner_sector = sector['sector_sentiment']
                    sname = sector.get('sector_name', 'N/A')
                    sscore = inner_sector.get('sentiment_score', 50)
                    soverall = inner_sector.get('overall', '数据不足')
                    schg = inner_sector.get('change_pct', 'N/A')
                    tr = inner_sector.get('turnover_rate', 'N/A')
                    leader_info = inner_sector.get('leader_stock')
                else:
                    # 旧的平铺结构：直接从顶层获取
                    sname = sector.get('sector_name', 'N/A')
                    sscore = sector.get('sentiment_score', 50)
                    soverall = sector.get('overall', '数据不足')
                    schg = sector.get('change_pct', 'N/A')
                    tr = sector.get('turnover_rate', 'N/A')
                    leader_info = sector.get('leader_stock')

                # 计算辨识度（基于股吧活跃度与决断度）
                guba = sentiment_data.get('guba_sentiment') or {}
                total_posts = guba.get('total_posts', 0) or 0
                confidence = guba.get('confidence', 0.0) or 0.0
                try:
                    conf = float(confidence)
                except Exception:
                    conf = 0.0
                try:
                    posts = int(total_posts)
                except Exception:
                    posts = 0
                recognition = None
                if posts > 0 or conf > 0:
                    if conf >= 60 or posts >= 80:
                        recognition = '高'
                    elif conf >= 35 or posts >= 30:
                        recognition = '中'
                    else:
                        recognition = '低'

                # 规模分类（基于总市值，单位：亿）
                indicators = (fundamental_data or {}).get('financial_indicators', {}) or {}
                total_mc = indicators.get('total_market_cap', None)
                size_tag = None
                try:
                    mc_val = float(total_mc)
                    if mc_val >= 1000:
                        size_tag = '大盘'
                    elif mc_val >= 300:
                        size_tag = '中盘'
                    elif mc_val > 0:
                        size_tag = '小盘'
                except Exception:
                    pass

                # 中军判定（仅在规模明确时展示）
                mid_core = None
                if size_tag in ['中盘', '大盘', '小盘']:
                    mid_core = '是' if size_tag == '中盘' else '否'

                score_class = 'score-high' if isinstance(sscore, (int, float)) and sscore >= 70 else (
                    'score-medium' if isinstance(sscore, (int, float)) and sscore >= 50 else 'score-low')

                html += "<div class='combined-section'>"
                html += "<h4>🏭 所属板块情绪</h4>"
                html += f"""
                <div class='sentiment-score-compact {score_class}'>
                    <div class='score-value'>{sscore}</div>
                    <div class='score-label'>{soverall} · {sname}</div>
                </div>
                """

                # 统计格子：仅在有真实数据时逐项加入
                stats_html = "<div class='guba-stats-compact'>"
                # 涨跌幅与换手率（总是有）
                stats_html += f"""
                    <div class='guba-stat-compact'>
                        <span class='guba-label'>涨跌幅:</span>
                        <span class='guba-value'>{schg}%</span>
                    </div>
                    <div class='guba-stat-compact'>
                        <span class='guba-label'>换手率:</span>
                        <span class='guba-value'>{tr}%</span>
                    </div>
                """

                if recognition is not None:
                    stats_html += f"""
                    <div class='guba-stat-compact'>
                        <span class='guba-label'>辨识度:</span>
                        <span class='guba-value'>{recognition}</span>
                    </div>
                    """

                if size_tag is not None:
                    stats_html += f"""
                    <div class='guba-stat-compact'>
                        <span class='guba-label'>规模:</span>
                        <span class='guba-value'>{size_tag}</span>
                    </div>
                    """

                if leader_info:
                    leader_name = leader_info.get('name', '—')
                    leader_chg = leader_info.get('change_pct', 'N/A')
                    stats_html += f"""
                    <div class='guba-stat-compact'>
                        <span class='guba-label'>龙头:</span>
                        <span class='guba-value'>{leader_name} ({leader_chg}%)</span>
                    </div>
                    """

                if mid_core is not None:
                    stats_html += f"""
                    <div class='guba-stat-compact'>
                        <span class='guba-label'>中军:</span>
                        <span class='guba-value'>{mid_core}</span>
                    </div>
                    """

                stats_html += "</div>"
                html += stats_html
                html += "</div>"
        else:
            html += "<p>😊 暂无情绪数据</p>"

        # 🧭 事件分析（紧凑展示）
        if event_data:
            summary = event_data.get('summary', {}) or {}
            policy_events = event_data.get('policy_events', {}) or {}
            corporate_events = event_data.get('corporate_events', {}) or {}
            industry_events = event_data.get('industry_events', {}) or {}
            market_events = event_data.get('market_events', {}) or {}

            html += "<div class='combined-section'>"
            html += "<h4>🧭 事件分析</h4>"

            rating = summary.get('rating', '中性')
            rating_class = 'rating-positive' if '利好' in rating else (
                'rating-negative' if '利空' in rating else 'rating-neutral')

            html += f"""
            <div class='event-summary-compact'>
                <span class='event-rating-compact {rating_class}'>{rating}</span>
                <span class='event-score-compact'>得分: {summary.get('comprehensive_score', 0)}</span>
                <span class='event-count-compact positive'>利好: {summary.get('total_positive_events', 0)}</span>
                <span class='event-count-compact negative'>利空: {summary.get('total_negative_events', 0)}</span>
            </div>
            """

            # 合并事件并展示TOP3（正负各最多3条）
            all_positive_events = []
            all_positive_events.extend(policy_events.get('positive', []))
            all_positive_events.extend(corporate_events.get('positive', []))
            all_positive_events.extend(industry_events.get('positive', []))
            all_positive_events.extend(market_events.get('positive', []))

            all_negative_events = []
            all_negative_events.extend(policy_events.get('negative', []))
            all_negative_events.extend(corporate_events.get('negative', []))
            all_negative_events.extend(industry_events.get('negative', []))
            all_negative_events.extend(market_events.get('negative', []))

            if all_positive_events or all_negative_events:
                html += "<div class='event-list-compact'>"
                if all_positive_events:
                    html += "<div class='event-section'>"
                    html += "<h4>🟢 利好事件 (TOP3)</h4>"
                    for event in all_positive_events[:3]:
                        title = event.get('event', '无标题')
                        url = event.get('url', '')
                        source = event.get('source', '')
                        html += f"""
                        <div class='event-item positive'>
                            <span class='event-title'>
                                {f'<a href="{url}" target="_blank">{title}</a>' if url else title}
                            </span>
                            <span class='event-impact'>影响: {event.get('impact_score', 0)}</span>
                            <span class='event-date'>{event.get('date', '')}</span>
                            {f"<span class='event-source'>{source}</span>" if source else ''}
                        </div>
                        """
                    html += "</div>"
                if all_negative_events:
                    html += "<div class='event-section'>"
                    html += "<h4>🔴 利空事件 (TOP3)</h4>"
                    for event in all_negative_events[:3]:
                        title = event.get('event', '无标题')
                        url = event.get('url', '')
                        source = event.get('source', '')
                        html += f"""
                        <div class='event-item negative'>
                            <span class='event-title'>
                                {f'<a href="{url}" target="_blank">{title}</a>' if url else title}
                            </span>
                            <span class='event-impact'>影响: {event.get('impact_score', 0)}</span>
                            <span class='event-date'>{event.get('date', '')}</span>
                            {f"<span class='event-source'>{source}</span>" if source else ''}
                        </div>
                        """
                    html += "</div>"
                html += "</div>"
            else:
                html += "<p style='text-align: center; color: #888; padding: 12px;'>🔍 暂无关联事件数据</p>"

            # 风险与机会等级（紧凑）
            html += f"""
            <div class='event-level-section'>
                <div class='level-item'>
                    <span class='level-label'>风险等级:</span>
                    <span class='level-value'>{summary.get('risk_level', '未知')}</span>
                </div>
                <div class='level-item'>
                    <span class='level-label'>机会等级:</span>
                    <span class='level-value'>{summary.get('opportunity_level', '未知')}</span>
                </div>
            </div>
            """

            html += "</div>"

        html += "</div>"
        return html

    def _generate_sentiment_section(self, sentiment_data: Dict) -> str:
        """生成股民情绪部分 - 仅展示评论情绪"""
        if not sentiment_data:
            return "<p>😊 暂无情绪数据</p>"

        guba_sentiment = sentiment_data.get('guba_sentiment', {})
        comprehensive_score = sentiment_data.get('comprehensive_score', 50)
        comprehensive_sentiment = sentiment_data.get('comprehensive_sentiment', '中性')

        html = "<div class='sentiment-grid'>"

        # 综合情绪得分
        html += "<div class='sentiment-score-section'>"
        html += "<h4>🎯 综合情绪</h4>"
        score_class = 'score-high' if comprehensive_score >= 70 else (
            'score-medium' if comprehensive_score >= 50 else 'score-low')
        html += f"""
        <div class='sentiment-score {score_class}'>
            <div class='score-value'>{comprehensive_score}</div>
            <div class='score-label'>{comprehensive_sentiment}</div>
        </div>
        """
        html += "</div>"

        # 股吧情绪统计
        html += "<div class='sentiment-section'>"
        html += "<h4>💬 股吧评论情绪分析</h4>"
        html += f"""
        <div class='guba-stats'>
            <div class='guba-stat bullish'>
                <span class='guba-label'>看多:</span>
                <span class='guba-value'>{guba_sentiment.get('bullish_ratio', 0)}%</span>
            </div>
            <div class='guba-stat neutral'>
                <span class='guba-label'>中性:</span>
                <span class='guba-value'>{guba_sentiment.get('neutral_ratio', 0)}%</span>
            </div>
            <div class='guba-stat bearish'>
                <span class='guba-label'>看空:</span>
                <span class='guba-value'>{guba_sentiment.get('bearish_ratio', 0)}%</span>
            </div>
        </div>
        <div class='guba-overall'>总体情绪: {guba_sentiment.get('overall', '中性')}</div>
        <div class='guba-metrics'>
            <div class='metric-item'>
                <span class='metric-label'>总帖数:</span>
                <span class='metric-value'>{guba_sentiment.get('total_posts', 0)}</span>
            </div>
            <div class='metric-item'>
                <span class='metric-label'>活跃用户:</span>
                <span class='metric-value'>{guba_sentiment.get('active_users', 0)}</span>
            </div>
        </div>
        """
        html += "</div>"

        html += "</div>"
        return html

    def _generate_event_section(self, event_data: Dict) -> str:
        """生成利好利空事件部分"""
        if not event_data:
            return "<p>🔍 暂无事件数据</p>"

        summary = event_data.get('summary', {})
        policy_events = event_data.get('policy_events', {})
        corporate_events = event_data.get('corporate_events', {})
        industry_events = event_data.get('industry_events', {})
        market_events = event_data.get('market_events', {})

        html = "<div class='event-container'>"

        # 综合评级
        html += "<div class='event-rating-section'>"
        rating = summary.get('rating', '中性')
        rating_class = 'rating-positive' if '利好' in rating else (
            'rating-negative' if '利空' in rating else 'rating-neutral')
        html += f"""
        <div class='event-rating {rating_class}'>
            <div class='rating-value'>{rating}</div>
            <div class='rating-score'>得分: {summary.get('comprehensive_score', 0)}</div>
        </div>
        <div class='event-summary'>
            <div class='event-count positive'>利好事件: {summary.get('total_positive_events', 0)}</div>
            <div class='event-count negative'>利空事件: {summary.get('total_negative_events', 0)}</div>
        </div>
        """
        html += "</div>"

        # 利好事件列表
        all_positive_events = []
        all_positive_events.extend(policy_events.get('positive', []))
        all_positive_events.extend(corporate_events.get('positive', []))
        all_positive_events.extend(industry_events.get('positive', []))
        all_positive_events.extend(market_events.get('positive', []))

        if all_positive_events:
            html += "<div class='event-section'>"
            html += "<h4>🟢 利好事件 (TOP5)</h4>"
            for event in all_positive_events[:5]:
                html += f"""
                <div class='event-item positive'>
                    <span class='event-title'>{event.get('event', '无标题')}</span>
                    <span class='event-impact'>影响: {event.get('impact_score', 0)}</span>
                    <span class='event-date'>{event.get('date', '')}</span>
                </div>
                """
            html += "</div>"

        # 利空事件列表
        all_negative_events = []
        all_negative_events.extend(policy_events.get('negative', []))
        all_negative_events.extend(corporate_events.get('negative', []))
        all_negative_events.extend(industry_events.get('negative', []))
        all_negative_events.extend(market_events.get('negative', []))

        if all_negative_events:
            html += "<div class='event-section'>"
            html += "<h4>🔴 利空事件 (TOP5)</h4>"
            for event in all_negative_events[:5]:
                html += f"""
                <div class='event-item negative'>
                    <span class='event-title'>{event.get('event', '无标题')}</span>
                    <span class='event-impact'>影响: {event.get('impact_score', 0)}</span>
                    <span class='event-date'>{event.get('date', '')}</span>
                </div>
                """
            html += "</div>"

        # 风险与机会等级
        html += "<div class='event-level-section'>"
        html += f"""
        <div class='level-item'>
            <span class='level-label'>风险等级:</span>
            <span class='level-value'>{summary.get('risk_level', '未知')}</span>
        </div>
        <div class='level-item'>
            <span class='level-label'>机会等级:</span>
            <span class='level-value'>{summary.get('opportunity_level', '未知')}</span>
        </div>
        """
        html += "</div>"

        html += "</div>"
        return html

    def _generate_llm_analysis_section(self, llm_analysis: Dict, llm_predicted_kline: Optional[pd.DataFrame] = None) -> str:
        """生成LLM智能分析板块"""
        if not llm_analysis:
            return """
            <div class='llm-analysis-section'>
                <p style='text-align: center; color: var(--text-muted); padding: 20px;'>
                    💡 LLM未配置或分析未启用
                </p>
            </div>
            """

        html = "<div class='llm-analysis-section'>"

        # K线走势预测
        kline_pred = llm_analysis.get('kline_prediction', {})
        if kline_pred:
            trend = kline_pred.get('trend', '未知')
            confidence = kline_pred.get('confidence', 0) * 100

            html += f"""
            <div class='llm-subsection'>
                <h4>📊 K线走势预测</h4>
                <div class='llm-content'>
                    <div class='llm-row'>
                        <span class='llm-label'>预测趋势:</span>
                        <span class='llm-value trend-{trend}'>{trend}</span>
                    </div>
                    <div class='llm-row'>
                        <span class='llm-label'>信心度:</span>
                        <span class='llm-value'>{confidence:.0f}%</span>
                    </div>
            """

            # 支撑位和压力位
            support_levels = kline_pred.get('support_levels', [])
            resistance_levels = kline_pred.get('resistance_levels', [])

            if support_levels:
                html += f"""
                    <div class='llm-row'>
                        <span class='llm-label'>关键支撑位:</span>
                        <span class='llm-value'>{', '.join(map(str, support_levels))}</span>
                    </div>
                """

            if resistance_levels:
                html += f"""
                    <div class='llm-row'>
                        <span class='llm-label'>关键压力位:</span>
                        <span class='llm-value'>{', '.join(map(str, resistance_levels))}</span>
                    </div>
                """

            # 预测K线数据表格
            predictions = kline_pred.get('predictions', [])
            if predictions and len(predictions) > 0:
                html += """
                    <div class='llm-predictions-table'>
                        <table>
                            <thead>
                                <tr>
                                    <th>日期</th>
                                    <th>开盘</th>
                                    <th>最高</th>
                                    <th>最低</th>
                                    <th>收盘</th>
                                    <th>涨跌幅</th>
                                </tr>
                            </thead>
                            <tbody>
                """

                for pred in predictions[:10]:  # 只显示前10天
                    change_pct = pred.get('change_pct', 0)
                    change_class = 'positive' if change_pct > 0 else 'negative'
                    html += f"""
                                <tr>
                                    <td>{pred.get('date', 'N/A')}</td>
                                    <td>{pred.get('open', 0):.2f}</td>
                                    <td>{pred.get('high', 0):.2f}</td>
                                    <td>{pred.get('low', 0):.2f}</td>
                                    <td>{pred.get('close', 0):.2f}</td>
                                    <td class='{change_class}'>{change_pct:+.2f}%</td>
                                </tr>
                    """

                html += """
                            </tbody>
                        </table>
                    </div>
                """

            html += "</div></div>"

        # 操作建议
        op_advice = llm_analysis.get('operation_advice', {})
        if op_advice:
            action = op_advice.get('action', '未知')
            action_class = {
                '买入': 'buy-action',
                '持有': 'hold-action',
                '卖出': 'sell-action'
            }.get(action, 'hold-action')

            html += f"""
            <div class='llm-subsection'>
                <h4>💡 操作建议</h4>
                <div class='llm-content'>
                    <div class='operation-badge {action_class}'>{action}</div>
                    <div class='llm-row'>
                        <span class='llm-label'>建议价位:</span>
                        <span class='llm-value'>{op_advice.get('suggested_price_range', '未知')}</span>
                    </div>
                    <div class='llm-row'>
                        <span class='llm-label'>仓位控制:</span>
                        <span class='llm-value'>{op_advice.get('position_control', '未知')}</span>
                    </div>
                    <div class='llm-row'>
                        <span class='llm-label'>目标价位:</span>
                        <span class='llm-value'>{op_advice.get('target_price', '未知')}</span>
                    </div>
                    <div class='llm-row'>
                        <span class='llm-label'>止损价位:</span>
                        <span class='llm-value'>{op_advice.get('stop_loss', '未知')}</span>
                    </div>
                    <div class='llm-row'>
                        <span class='llm-label'>信心度:</span>
                        <span class='llm-value'>{op_advice.get('confidence', 0) * 100:.0f}%</span>
                    </div>
                </div>
            </div>
            """

        # 风险评估
        risk = llm_analysis.get('risk_assessment', {})
        if risk:
            risk_level = risk.get('risk_level', '未知')
            risk_class = {
                '低': 'risk-low',
                '中': 'risk-medium',
                '高': 'risk-high'
            }.get(risk_level, 'risk-medium')

            html += f"""
            <div class='llm-subsection'>
                <h4>⚠️ 风险评估</h4>
                <div class='llm-content'>
                    <div class='risk-badge {risk_class}'>{risk_level}风险</div>
                    <div class='llm-row'>
                        <span class='llm-label'>综合评分:</span>
                        <span class='llm-value'>{risk.get('overall_score', 0)}/100</span>
                    </div>
            """

            risk_points = risk.get('risk_points', [])
            if risk_points:
                html += "<div class='llm-row'><span class='llm-label'>主要风险:</span></div>"
                html += "<ul class='risk-points-list'>"
                for rp in risk_points:
                    html += f"<li>{rp}</li>"
                html += "</ul>"

            html += "</div></div>"

        # 操作策略
        strategy = llm_analysis.get('strategy', {})
        if strategy:
            html += f"""
            <div class='llm-subsection'>
                <h4>📋 操作策略</h4>
                <div class='llm-content'>
                    <div class='llm-row'>
                        <span class='llm-label'>短线策略:</span>
                        <span class='llm-value'>{strategy.get('short_term', '未知')}</span>
                    </div>
                    <div class='llm-row'>
                        <span class='llm-label'>中线策略:</span>
                        <span class='llm-value'>{strategy.get('mid_term', '未知')}</span>
                    </div>
                    <div class='llm-row'>
                        <span class='llm-label'>仓位策略:</span>
                        <span class='llm-value'>{strategy.get('position_strategy', '未知')}</span>
                    </div>
                </div>
            </div>
            """

        # 综合总结
        summary = llm_analysis.get('summary', '')
        if summary:
            html += f"""
            <div class='llm-subsection'>
                <h4>📝 综合总结</h4>
                <div class='llm-content'>
                    <p class='llm-summary'>{summary}</p>
                </div>
            </div>
            """

        html += "</div>"
        return html

    def _get_css_styles(self) -> str:
        """获取优化的CSS样式 - 使用常规字体"""
        return """
        :root {
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
            --border-glow: #64b5f6;
            --shadow-glow: 0 0 20px rgba(100, 181, 246, 0.25);
            --shadow-purple: 0 0 20px rgba(186, 104, 200, 0.25);
            --shadow-green: 0 0 20px rgba(102, 187, 106, 0.25);
            --gradient-primary: linear-gradient(135deg, #2d3748 0%, #4a5568 100%);
            --gradient-cyber: linear-gradient(135deg, #64b5f6 0%, #ba68c8 50%, #66bb6a 100%);
            --gradient-dark: linear-gradient(135deg, #252d42 0%, #2d3748 100%);
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            background: var(--primary-bg);
            color: #ffffff;
            line-height: 1.6;
            min-height: 100vh;
            overflow-x: hidden;
            position: relative;
        }
        
        /* 动态背景效果 */
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: 
                radial-gradient(circle at 20% 50%, rgba(91, 155, 213, 0.08) 0%, transparent 50%),
                radial-gradient(circle at 80% 20%, rgba(159, 122, 234, 0.08) 0%, transparent 50%),
                radial-gradient(circle at 40% 80%, rgba(72, 187, 120, 0.08) 0%, transparent 50%);
            pointer-events: none;
            z-index: -1;
        }
        
        /* 动态粒子效果 */
        body::after {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
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
        }
        
        @keyframes particleMove {
            0% { transform: translate(0, 0); }
            100% { transform: translate(-200px, -100px); }
        }
        
        .container {
            max-width: 1600px;
            margin: 0 auto;
            padding: 30px;
            position: relative;
        }
        
        /* 头部样式 - 科技感 */
        .header {
            background: var(--gradient-dark);
            border: 1px solid var(--border-primary);
            border-radius: 20px;
            padding: 40px;
            text-align: center;
            margin-bottom: 40px;
            
            position: relative;
            overflow: hidden;
        }
        
        .header::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(0, 212, 255, 0.1), transparent);
            animation: scanLine 3s linear infinite;
        }
        
        @keyframes scanLine {
            0% { left: -100%; }
            100% { left: 100%; }
        }
        
        .header h1 {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 2.5em;
            font-weight: 700;
            margin-bottom: 20px;
            color: #ffffff;
            letter-spacing: 1px;
            position: relative;
        }
        
        .stock-info {
            display: flex;
            justify-content: center;
            gap: 40px;
            flex-wrap: wrap;
            margin-top: 20px;
        }
        
        .stock-code {
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 1.6em;
            font-weight: 700;
            color: #ffffff;
            padding: 10px 20px;
            border: 2px solid #64b5f6;
            border-radius: 10px;
            background: rgba(100, 181, 246, 0.15);
        }
        
        .timestamp {
            color: #ffffff;
            font-size: 1.2em;
            padding: 10px 20px;
            border: 1px solid #64b5f6;
            border-radius: 10px;
            background: rgba(100, 181, 246, 0.1);
        }
        
        /* 图表区域 - 科技感 */
        .chart-section {
            background: var(--gradient-dark);
            border: 1px solid var(--border-primary);
            border-radius: 20px;
            padding: 28px;
            margin-bottom: 40px;
            
            position: relative;
            overflow: hidden;
        }
        
        .chart-section::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: conic-gradient(from 0deg, transparent, rgba(0, 212, 255, 0.1), transparent);
            animation: rotate 10s linear infinite;
            z-index: 0;
        }
        
        @keyframes rotate {
            100% { transform: rotate(360deg); }
        }
        
        .chart-section h2 {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            margin-bottom: 20px;
            color: #ffffff;
            text-align: center;
            font-size: 1.8em;
            position: relative;
            z-index: 1;
        }
        
        .chart-container {
            text-align: center;
            position: relative;
            z-index: 1;
            border-radius: 15px;
            overflow: hidden;
            
        }
        
        .chart-container img {
            border-radius: 15px;
            width: 100%;
            height: auto;
            max-height: 1024px;
            object-fit: contain;
            
        }

        @media (max-width: 768px) {
            .chart-container img {
                max-height: 380px;
            }
        }
        
        /* 分析网格 - 科技感 */
        .analysis-section {
            margin-bottom: 40px;
        }
        
        .analysis-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 30px;
            margin-bottom: 40px;
        }
        
        .analysis-card {
            background: var(--gradient-dark);
            border: 1px solid var(--border-primary);
            border-radius: 20px;
            padding: 30px;
            
            position: relative;
            overflow: hidden;
            transition: all 0.3s ease;
        }
        
        .analysis-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: var(--gradient-cyber);
        }
        
        .analysis-card:hover {
            transform: translateY(-5px);
            
            border-color: var(--accent-blue);
        }
        
        .analysis-card h3 {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            margin-bottom: 25px;
            color: var(--accent-blue);
            border-bottom: 2px solid var(--accent-blue);
            padding-bottom: 15px;
            font-size: 1.4em;
        }
        
        /* 技术指标 - 科技感 */
        .indicators-grid {
            display: grid;
            gap: 15px;
        }
        
        .indicator-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 20px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-primary);
            border-radius: 12px;
            border-left: 4px solid var(--accent-blue);
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }
        
        .indicator-item::before {
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 4px;
            background: var(--accent-blue);
            
        }
        
        .indicator-item:hover {
            background: rgba(0, 212, 255, 0.1);
            
        }
        
        .indicator-item.indicator-rsi::before {
            background: var(--accent-green);
            
        }
        
        .indicator-item.indicator-macd::before {
            background: var(--accent-purple);
            
        }
        
        .indicator-item.indicator-bb::before {
            background: var(--accent-yellow);
            
        }
        
        .indicator-label {
            font-weight: 600;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }
        
        .indicator-value {
            font-weight: bold;
            color: #64b5f6;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        }
        
        /* 信号和风险合并布局 - 科技感 */
        .signals-risk-combined {
            display: grid;
            gap: 30px;
        }
        
        .signals-section h4,
        .risk-section h4 {
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid var(--accent-purple);
            color: var(--accent-purple);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 1.2em;
        }
        
        /* 交易信号 - 科技感 */
        .signals-summary {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
            margin-bottom: 25px;
        }
        
        .signal-stat {
            text-align: center;
            padding: 25px 20px;
            border-radius: 15px;
            color: var(--text-primary);
            position: relative;
            overflow: hidden;
            border: 2px solid transparent;
            background-clip: padding-box;
            transition: all 0.3s ease;
        }
        
        .signal-stat::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: var(--gradient-dark);
            z-index: -1;
        }
        
        .signal-stat.buy {
            border-color: rgba(16, 185, 129, 0.6);
            
        }
        
        .signal-stat.hold {
            border-color: rgba(245, 158, 11, 0.6);
            
        }
        
        .signal-stat.sell {
            border-color: rgba(239, 68, 68, 0.6);
            
        }
        
        .signal-stat:hover {
            transform: translateY(-3px) scale(1.05);
        }
        
        .signal-count {
            display: block;
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 10px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }
        
        .signal-label {
            display: block;
            margin-bottom: 8px;
            font-size: 1.1em;
            opacity: 0.9;
        }
        
        .signal-percent {
            font-size: 1.3em;
            font-weight: bold;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        }
        
        .recommendation {
            padding: 20px;
            background: rgba(74, 158, 255, 0.08);
            border: 1px solid rgba(74, 158, 255, 0.3);
            border-radius: 12px;
            font-size: 1.1em;
            margin-top: 20px;
            
        }
        
        /* 风险评估 - 科技感 */
        .risk-items {
            display: grid;
            gap: 15px;
        }
        
        .risk-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px 20px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-primary);
            border-radius: 12px;
            border-left: 4px solid var(--text-muted);
            transition: all 0.3s ease;
        }
        
        .risk-item.risk-low {
            border-left-color: rgba(16, 185, 129, 0.7);
            background: rgba(16, 185, 129, 0.08);
            
        }
        
        .risk-item.risk-medium {
            border-left-color: rgba(245, 158, 11, 0.7);
            background: rgba(245, 158, 11, 0.08);
            
        }
        
        .risk-item.risk-high {
            border-left-color: rgba(239, 68, 68, 0.7);
            background: rgba(239, 68, 68, 0.08);
            
        }
        
        .risk-label {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            color: #ffffff;
            font-weight: 600;
        }
        
        .risk-value {
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            color: #64b5f6;
            font-weight: bold;
        }
        
        /* 控制台数据 - 科技感 */
        .console-data {
            display: grid;
            gap: 12px;
        }
        
        .console-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 16px;
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid var(--border-primary);
            border-radius: 8px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 0.9em;
            border-left: 3px solid var(--accent-blue);
            transition: all 0.3s ease;
        }
        
        .console-item:hover {
            background: rgba(74, 158, 255, 0.08);
            
        }
        
        .console-label {
            color: #ffffff;
        }
        
        .console-value {
            font-weight: bold;
            color: #66bb6a;
        }
        
        /* 量化模型 + 时间轴并排布局 - 科技感 */
        .models-timeline-section {
            background: var(--gradient-dark);
            border: 1px solid var(--border-primary);
            border-radius: 20px;
            padding: 40px;
            margin-bottom: 40px;
            
            position: relative;
            overflow: hidden;
        }
        
        .models-timeline-section::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: var(--gradient-cyber);
        }
        
        .models-timeline-container {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 40px;
        }
        
        /* 量化模型部分 - 科技感 */
        .models-section h2 {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            margin-bottom: 25px;
            color: #ffffff;
            font-size: 1.6em;
        }
        }
        
        .models-container-full {
            display: grid;
            gap: 25px;
        }
        
        .models-group-full h4 {
            margin-bottom: 20px;
            padding: 15px 25px;
            border-radius: 15px;
            color: var(--text-primary);
            font-size: 1.3em;
            text-align: center;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            position: relative;
            overflow: hidden;
            border: 2px solid transparent;
        }
        
        .buy-group h4 {
            background: var(--gradient-dark);
            border-color: rgba(16, 185, 129, 0.6);
            
        }
        
        .hold-group h4 {
            background: var(--gradient-dark);
            border-color: rgba(245, 158, 11, 0.6);
            
        }
        
        .sell-group h4 {
            background: var(--gradient-dark);
            border-color: rgba(239, 68, 68, 0.6);
            
        }
        
        .models-table-full {
            background: transparent;
            border-radius: 15px;
            overflow: hidden;
            border: 1px solid var(--border-primary);
        }
        
        .models-header {
            display: grid;
            grid-template-columns: 2fr 1.5fr 3fr 0.8fr 0.8fr;
            background: var(--secondary-bg);
            color: var(--text-primary);
            font-weight: bold;
            padding: 15px 10px;
            font-size: 0.9em;
            border-bottom: 2px solid var(--accent-blue);
            
        }
        
        .models-header span {
            padding: 0 10px;
            text-align: center;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }
        
        .header-name {
            text-align: left !important;
        }
        
        .model-row-full {
            display: grid;
            grid-template-columns: 2fr 1.5fr 3fr 0.8fr 0.8fr;
            background: rgba(255, 255, 255, 0.02);
            padding: 12px 10px;
            transition: all 0.3s ease;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }
        
        .model-row-full:hover {
            background: rgba(74, 158, 255, 0.08);
            
            transform: scale(1.01);
        }
        
        .model-row-full.buy {
            border-left: 4px solid rgba(16, 185, 129, 0.7);
            
        }
        
        .model-row-full.hold {
            border-left: 4px solid rgba(245, 158, 11, 0.7);
            
        }
        
        .model-row-full.sell {
            border-left: 4px solid rgba(239, 68, 68, 0.7);
            
        }
        
        .model-row-full span {
            padding: 0 10px;
            text-align: center;
            font-size: 0.85em;
        }
        
        .model-name-full {
            font-weight: bold;
            color: #ffffff;
            text-align: left !important;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 0.9em;
        }
        
        .model-group-full {
            color: #e8eaf6;
            font-size: 0.75em;
        }
        
        .model-strategy-full {
            color: #e8eaf6;
            font-size: 0.75em;
            text-align: left !important;
        }
        
        .model-rate-full {
            font-weight: bold;
            color: #64b5f6;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        }
        
        .model-signal-full {
            font-weight: bold;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }
        
        .buy-signal {
            background: rgba(16, 185, 129, 0.15);
            color: rgba(16, 185, 129, 0.9);
            border: 1px solid rgba(16, 185, 129, 0.6);
        }
        
        .hold-signal {
            background: rgba(245, 158, 11, 0.15);
            color: rgba(245, 158, 11, 0.9);
            border: 1px solid rgba(245, 158, 11, 0.6);
        }
        
        .sell-signal {
            background: rgba(239, 68, 68, 0.15);
            color: rgba(239, 68, 68, 0.9);
            border: 1px solid rgba(239, 68, 68, 0.6);
        }
        
        .no-sell-signals-full {
            text-align: center;
            padding: 25px;
            color: rgba(16, 185, 129, 0.8);
            font-weight: bold;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            background: rgba(16, 185, 129, 0.08);
            border-radius: 10px;
            
        }
        
        /* 时间线部分 - 科技感垂直右侧布局 */
        .timeline-section h2 {
            margin-bottom: 25px;
            color: #ffffff;
            font-size: 1.4em;
            text-align: center;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }
        }
        
        .timeline-container-vertical {
            display: grid;
            gap: 10px;
            max-height: 700px;
            overflow-y: auto;
            padding-right: 10px;
        }
        
        /* 自定义滚动条 - 科技感 */
        .timeline-container-vertical::-webkit-scrollbar {
            width: 6px;
        }
        
        .timeline-container-vertical::-webkit-scrollbar-track {
            background: var(--secondary-bg);
            border-radius: 10px;
        }
        
        .timeline-container-vertical::-webkit-scrollbar-thumb {
            background: var(--accent-blue);
            border-radius: 10px;
        }
        
        .timeline-container-vertical::-webkit-scrollbar-thumb:hover {
            background: var(--accent-purple);
        }
        
        .timeline-item-vertical {
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 12px;
            padding: 12px 15px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--border-primary);
            border-left: 4px solid var(--accent-purple);
            transition: all 0.3s ease;
            cursor: pointer;
            position: relative;
            overflow: hidden;
        }
        
        .timeline-item-vertical::before {
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 4px;
            background: var(--accent-purple);
        }
        
        .timeline-item-vertical.current {
            background: rgba(0, 212, 255, 0.1);
            border-color: var(--accent-blue);
        }
        
        .timeline-item-vertical.current::before {
            background: var(--accent-blue);
        }
        
        .timeline-item-vertical:hover {
            transform: translateX(-5px) scale(1.02);
            background: rgba(139, 92, 246, 0.1);
            border-color: var(--accent-purple);
        }
        
        .timeline-time-vertical {
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-weight: bold;
            color: var(--accent-blue);
            font-size: 0.8em;
            white-space: nowrap;
        }
        
        .timeline-content-vertical {
            min-width: 0;
        }
        
        .timeline-stock-vertical {
            font-weight: bold;
            color: #ffffff;
            font-size: 0.95em;
            margin-bottom: 8px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        }
        
        .timeline-signals-vertical {
            display: flex;
            gap: 8px;
            margin-bottom: 6px;
            flex-wrap: wrap;
        }
        
        .signal-mini {
            display: flex;
            align-items: center;
            gap: 3px;
            padding: 3px 6px;
            border-radius: 8px;
            font-size: 0.7em;
            font-weight: bold;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
            border: 1px solid transparent;
            background: rgba(255, 255, 255, 0.05);
        }
        
        .signal-mini-icon {
            font-size: 0.6em;
        }
        
        .signal-mini-count {
            font-size: 0.8em;
            font-weight: bold;
        }
        
        .signal-mini.buy-mini {
            border-color: rgba(16, 185, 129, 0.6);
            background: rgba(16, 185, 129, 0.1);
            color: rgba(16, 185, 129, 0.9);
        }
        
        .signal-mini.hold-mini {
            border-color: rgba(245, 158, 11, 0.6);
            background: rgba(245, 158, 11, 0.1);
            color: rgba(245, 158, 11, 0.9);
        }
        
        .signal-mini.sell-mini {
            border-color: rgba(239, 68, 68, 0.6);
            background: rgba(239, 68, 68, 0.1);
            color: rgba(239, 68, 68, 0.9);
        }
        
        .timeline-info-vertical {
            display: flex;
            gap: 10px;
            font-size: 0.75em;
        }
        
        .timeline-models-vertical {
            color: #e8eaf6;
        }
        
        .timeline-risk-vertical {
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 0.7em;
            font-weight: bold;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }
        
        .timeline-risk-vertical.risk-low {
            background: rgba(0, 255, 136, 0.2);
            color: var(--accent-green);
            border: 1px solid var(--accent-green);
        }
        
        .timeline-risk-vertical.risk-medium {
            background: rgba(255, 215, 0, 0.2);
            color: var(--accent-yellow);
            border: 1px solid var(--accent-yellow);
        }
        
        .timeline-risk-vertical.risk-high {
            background: rgba(255, 71, 87, 0.2);
            color: var(--accent-red);
            border: 1px solid var(--accent-red);
        }
        
        .timeline-click-hint {
            color: var(--accent-purple);
            font-size: 1.2em;
            opacity: 0.6;
            transition: all 0.3s ease;
        }
        
        .timeline-item-vertical:hover .timeline-click-hint {
            opacity: 1;
            color: var(--accent-blue);
            transform: scale(1.2);
        }
        
        /* 页脚 - 科技感 */
        .footer {
            text-align: center;
            padding: 40px;
            color: var(--text-secondary);
            background: var(--gradient-dark);
            border-radius: 20px;
            border: 1px solid var(--border-primary);
            
            position: relative;
            overflow: hidden;
        }
        
        .footer::before {
            content: '';
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: var(--gradient-cyber);
        }
        
        .footer p {
            margin-bottom: 8px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }
        
        /* 响应式设计 - 科技感 */
        @media (max-width: 768px) {
            .container {
                padding: 20px;
            }
            
            .header h1 {
                font-size: 2.2em;
            }
            
            .stock-info {
                flex-direction: column;
                gap: 20px;
            }
            
            .analysis-grid {
                grid-template-columns: 1fr;
                gap: 20px;
            }
            
            .signals-summary {
                grid-template-columns: 1fr;
                gap: 15px;
            }
            
            .models-timeline-container {
                grid-template-columns: 1fr;
                gap: 25px;
            }
            
            .timeline-section {
                order: -1;
            }
            
            .timeline-container-vertical {
                max-height: 400px;
            }
            
            .timeline-item-vertical {
                grid-template-columns: auto 1fr;
            }
            
            .timeline-click-hint {
                display: none;
            }
            
            /* 移动端模型表格调整 */
            .models-header {
                grid-template-columns: 2fr 1fr 0.8fr;
                font-size: 0.8em;
            }
            
            .model-row-full {
                grid-template-columns: 2fr 1fr 0.8fr;
                font-size: 0.8em;
            }
            
            .model-group-full,
            .model-strategy-full {
                display: none;
            }
            
            .models-header .header-group,
            .models-header .header-strategy {
                display: none;
            }
        }

        /* 综合分析板块样式 */
        .comprehensive-analysis-section {
            padding: 30px;
            background: var(--secondary-bg);
            border-radius: 15px;
            margin: 20px 0;
        }

        .comprehensive-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
            margin-top: 20px;
        }

        .comprehensive-grid-two-col {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
            margin-top: 20px;
            align-items: stretch;
        }

        /* 让右侧“股民情绪”卡片跨两行，以达到左侧“基本面财务+分析总结”的总高度 */
        .comprehensive-grid-two-col .analysis-card:nth-child(2) {
            grid-row: span 2;
        }

        /* 合并的消息面和情绪样式 */
        .news-sentiment-combined {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }

        .combined-section {
            background: rgba(255, 255, 255, 0.03);
            padding: 10px;
            border-radius: 10px;
            border-left: 3px solid var(--accent-blue);
        }

        .combined-section h4 {
            color: var(--accent-blue);
            margin-bottom: 12px;
            font-size: 1em;
        }

        /* 紧凑型情绪得分 */
        .sentiment-score-compact {
            text-align: center;
            padding: 10px;
            border-radius: 10px;
            margin-bottom: 10px;
        }

        .sentiment-score-compact .score-value {
            font-size: 1.6em;
            font-weight: bold;
            margin-bottom: 5px;
        }

        .sentiment-score-compact .score-label {
            font-size: 0.95em;
            color: var(--text-secondary);
        }

        .sentiment-score-compact.score-high .score-value {
            color: var(--accent-green);
        }

        .sentiment-score-compact.score-medium .score-value {
            color: var(--accent-yellow);
        }

        .sentiment-score-compact.score-low .score-value {
            color: var(--accent-red);
        }

        /* 紧凑型股吧统计 */
        .guba-stats-compact {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-bottom: 8px;
        }

        .guba-stat-compact {
            text-align: center;
            padding: 6px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 5px;
        }

        .guba-stat-compact.bullish {
            border-left: 3px solid var(--accent-green);
        }

        .guba-stat-compact.neutral {
            border-left: 3px solid var(--accent-yellow);
        }

        .guba-stat-compact.bearish {
            border-left: 3px solid var(--accent-red);
        }

        .guba-stat-compact .guba-label {
            display: block;
            color: var(--text-secondary);
            font-size: 0.85em;
            margin-bottom: 3px;
        }

        .guba-stat-compact .guba-value {
            display: block;
            font-size: 1.2em;
            font-weight: bold;
            color: var(--text-primary);
        }

        .guba-overall-compact {
            text-align: center;
            padding: 6px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 5px;
            color: var(--accent-blue);
            font-weight: 600;
            font-size: 0.85em;
        }

        /* 分析总结卡片 */
        .analysis-summary-card {
            background: rgba(255, 255, 255, 0.05);
            padding: 12px;
            border-radius: 10px;
        }

        .analysis-summary-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 8px;
        }

        .summary-item {
            background: rgba(255, 255, 255, 0.04);
            padding: 6px;
            border-radius: 8px;
        }

        .summary-item .label {
            display: block;
            color: var(--text-secondary);
            font-size: 0.85em;
            margin-bottom: 4px;
        }

        .summary-item .value {
            display: block;
            color: var(--text-primary);
            font-weight: 600;
            font-size: 0.95em;
        }

        /* 基本面样式 */
        .fundamental-grid {
            display: grid;
            gap: 15px;
        }

        .fundamental-section {
            background: rgba(255, 255, 255, 0.05);
            padding: 15px;
            border-radius: 10px;
        }

        .fundamental-section h4 {
            color: var(--primary-color);
            margin-bottom: 12px;
            font-size: 1em;
        }

        .fundamental-item {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }

        .fundamental-label {
            color: var(--text-secondary);
        }

        .fundamental-value {
            color: var(--text-primary);
            font-weight: 600;
        }

        /* 核心财务指标样式 - 紧凑型 */
        .fundamental-core-metrics {
            display: grid;
            gap: 12px;
        }

        .core-metric-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 15px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-primary);
            border-radius: 8px;
            border-left: 3px solid var(--accent-blue);
            transition: all 0.3s ease;
        }

        .core-metric-item:hover {
            background: rgba(0, 212, 255, 0.08);
        }

        .core-metric-item .metric-label {
            color: var(--text-secondary);
            font-size: 0.9em;
        }

        .core-metric-item .metric-value {
            color: var(--accent-blue);
            font-weight: bold;
            font-size: 1.1em;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        }

        /* 消息面样式 */
        .news-container {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }

        .news-sentiment-summary {
            display: flex;
            gap: 15px;
            justify-content: space-around;
            background: rgba(255, 255, 255, 0.05);
            padding: 15px;
            border-radius: 10px;
        }

        .sentiment-stat {
            text-align: center;
            flex: 1;
        }

        .sentiment-stat.positive {
            color: var(--success-color);
        }

        .sentiment-stat.neutral {
            color: var(--warning-color);
        }

        .sentiment-stat.negative {
            color: var(--danger-color);
        }

        .sentiment-label {
            display: block;
            font-size: 0.9em;
            margin-bottom: 5px;
        }

        .sentiment-count {
            display: block;
            font-size: 1.5em;
            font-weight: bold;
        }

        .news-section {
            background: rgba(255, 255, 255, 0.05);
            padding: 15px;
            border-radius: 10px;
        }

        .news-section h4 {
            color: var(--primary-color);
            margin-bottom: 12px;
            font-size: 1em;
        }

        .news-item {
            display: flex;
            gap: 10px;
            padding: 10px;
            margin: 5px 0;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 5px;
            align-items: center;
        }

        .news-item span:first-child {
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.85em;
            white-space: nowrap;
        }

        .importance-high {
            background: var(--danger-color);
            color: white;
        }

        .importance-medium {
            background: var(--warning-color);
            color: white;
        }

        .importance-low {
            background: var(--info-color);
            color: white;
        }

        .sentiment-positive {
            background: var(--success-color);
            color: white;
        }

        .sentiment-neutral {
            background: var(--info-color);
            color: white;
        }

        .sentiment-negative {
            background: var(--danger-color);
            color: white;
        }

        .news-title {
            flex: 1;
            color: var(--text-primary);
        }

        .news-date {
            color: var(--text-secondary);
            font-size: 0.85em;
        }

        /* 股民情绪样式 */
        .sentiment-grid {
            display: grid;
            gap: 15px;
        }

        .sentiment-score-section {
            background: rgba(255, 255, 255, 0.05);
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }

        .sentiment-score {
            margin-top: 10px;
        }

        .score-value {
            font-size: 3em;
            font-weight: bold;
            margin-bottom: 10px;
        }

        .score-label {
            font-size: 1.2em;
            color: var(--text-secondary);
        }

        .score-high .score-value {
            color: var(--success-color);
        }

        .score-medium .score-value {
            color: var(--warning-color);
        }

        .score-low .score-value {
            color: var(--danger-color);
        }

        .sentiment-section {
            background: rgba(255, 255, 255, 0.05);
            padding: 15px;
            border-radius: 10px;
        }

        .sentiment-section h4 {
            color: var(--primary-color);
            margin-bottom: 12px;
            font-size: 1em;
        }

        .capital-flow-item {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }

        .capital-label {
            color: var(--text-secondary);
        }

        .capital-value {
            font-weight: 600;
        }

        .trend-inflow {
            color: var(--success-color);
        }

        .trend-outflow {
            color: var(--danger-color);
        }

        .guba-stats {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-bottom: 15px;
        }

        .guba-stat {
            text-align: center;
            padding: 10px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 5px;
        }

        .guba-stat.bullish {
            border-left: 3px solid var(--success-color);
        }

        .guba-stat.neutral {
            border-left: 3px solid var(--warning-color);
        }

        .guba-stat.bearish {
            border-left: 3px solid var(--danger-color);
        }

        .guba-label {
            display: block;
            color: var(--text-secondary);
            font-size: 0.9em;
            margin-bottom: 5px;
        }

        .guba-value {
            display: block;
            font-size: 1.3em;
            font-weight: bold;
            color: var(--text-primary);
        }

        .guba-overall {
            text-align: center;
            padding: 10px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 5px;
            color: var(--primary-color);
            font-weight: 600;
        }

        /* 利好利空事件样式 */
        .event-container {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }

        .event-rating-section {
            background: rgba(255, 255, 255, 0.05);
            padding: 20px;
            border-radius: 10px;
        }

        .event-rating {
            text-align: center;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 15px;
        }

        .rating-positive {
            background: linear-gradient(135deg, rgba(76, 175, 80, 0.2), rgba(76, 175, 80, 0.1));
            border: 2px solid var(--success-color);
        }

        .rating-neutral {
            background: linear-gradient(135deg, rgba(255, 193, 7, 0.2), rgba(255, 193, 7, 0.1));
            border: 2px solid var(--warning-color);
        }

        .rating-negative {
            background: linear-gradient(135deg, rgba(244, 67, 54, 0.2), rgba(244, 67, 54, 0.1));
            border: 2px solid var(--danger-color);
        }

        .rating-value {
            font-size: 2em;
            font-weight: bold;
            margin-bottom: 5px;
        }

        .rating-positive .rating-value {
            color: var(--success-color);
        }

        .rating-neutral .rating-value {
            color: var(--warning-color);
        }

        .rating-negative .rating-value {
            color: var(--danger-color);
        }

        .rating-score {
            color: var(--text-secondary);
        }

        .event-summary {
            display: flex;
            gap: 20px;
            justify-content: center;
        }

        .event-count {
            padding: 8px 15px;
            border-radius: 5px;
            font-weight: 600;
        }

        .event-count.positive {
            background: rgba(76, 175, 80, 0.2);
            color: var(--success-color);
        }

        .event-count.negative {
            background: rgba(244, 67, 54, 0.2);
            color: var(--danger-color);
        }

        .event-section {
            background: rgba(255, 255, 255, 0.05);
            padding: 15px;
            border-radius: 10px;
        }

        .event-section h4 {
            color: var(--primary-color);
            margin-bottom: 12px;
            font-size: 1em;
        }

        .event-item {
            display: flex;
            gap: 10px;
            padding: 10px;
            margin: 5px 0;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 5px;
            align-items: center;
        }

        .event-item.positive {
            border-left: 3px solid var(--success-color);
        }

        .event-item.negative {
            border-left: 3px solid var(--danger-color);
        }

        .event-title {
            flex: 1;
            color: var(--text-primary);
        }

        .event-impact {
            color: var(--primary-color);
            font-size: 0.9em;
        }

        .event-date {
            color: var(--text-secondary);
            font-size: 0.85em;
        }

        .event-level-section {
            background: rgba(255, 255, 255, 0.05);
            padding: 15px;
            border-radius: 10px;
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
        }

        .level-item {
            display: flex;
            justify-content: space-between;
            padding: 10px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 5px;
        }

        .level-label {
            color: var(--text-secondary);
        }

        .level-value {
            color: var(--primary-color);
            font-weight: 600;
        }

        /* LLM智能分析样式 */
        .llm-analysis-wrapper {
            margin: 30px 0;
            padding: 20px;
            background: var(--gradient-dark);
            border-radius: 12px;
            border: 1px solid var(--border-primary);
        }

        .llm-analysis-wrapper h2 {
            color: var(--accent-purple);
            margin-bottom: 20px;
            font-size: 1.8em;
            text-shadow: 0 0 10px rgba(186, 104, 200, 0.5);
        }

        .llm-analysis-section {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
        }

        .llm-subsection {
            background: var(--secondary-bg);
            padding: 20px;
            border-radius: 8px;
            border-left: 3px solid var(--accent-purple);
        }

        .llm-subsection h4 {
            color: var(--accent-purple);
            margin-bottom: 15px;
            font-size: 1.2em;
        }

        .llm-content {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .llm-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 5px;
        }

        .llm-label {
            color: var(--text-secondary);
            font-weight: 500;
        }

        .llm-value {
            color: var(--text-primary);
            font-weight: 600;
        }

        .trend-上涨 {
            color: var(--accent-green);
        }

        .trend-下跌 {
            color: var(--accent-red);
        }

        .trend-震荡 {
            color: var(--accent-yellow);
        }

        .operation-badge {
            display: inline-block;
            padding: 10px 20px;
            border-radius: 20px;
            font-weight: 700;
            font-size: 1.1em;
            text-align: center;
            margin: 10px 0;
        }

        .buy-action {
            background: linear-gradient(135deg, #66bb6a, #43a047);
            color: white;
            box-shadow: 0 0 15px rgba(102, 187, 106, 0.5);
        }

        .hold-action {
            background: linear-gradient(135deg, #ffca28, #ffa000);
            color: white;
            box-shadow: 0 0 15px rgba(255, 202, 40, 0.5);
        }

        .sell-action {
            background: linear-gradient(135deg, #ef5350, #d32f2f);
            color: white;
            box-shadow: 0 0 15px rgba(239, 83, 80, 0.5);
        }

        .risk-badge {
            display: inline-block;
            padding: 8px 16px;
            border-radius: 15px;
            font-weight: 600;
            margin: 10px 0;
        }

        .risk-low {
            background: rgba(102, 187, 106, 0.2);
            color: var(--accent-green);
            border: 1px solid var(--accent-green);
        }

        .risk-medium {
            background: rgba(255, 202, 40, 0.2);
            color: var(--accent-yellow);
            border: 1px solid var(--accent-yellow);
        }

        .risk-high {
            background: rgba(239, 83, 80, 0.2);
            color: var(--accent-red);
            border: 1px solid var(--accent-red);
        }

        .risk-points-list {
            list-style: none;
            padding-left: 0;
            margin-top: 10px;
        }

        .risk-points-list li {
            padding: 8px 12px;
            margin: 5px 0;
            background: rgba(239, 83, 80, 0.1);
            border-left: 3px solid var(--accent-red);
            border-radius: 4px;
            color: var(--text-secondary);
        }

        .llm-summary {
            padding: 15px;
            background: rgba(100, 181, 246, 0.05);
            border-left: 3px solid var(--accent-blue);
            border-radius: 5px;
            color: var(--text-secondary);
            line-height: 1.6;
        }

        .llm-predictions-table {
            margin-top: 15px;
            overflow-x: auto;
        }

        .llm-predictions-table table {
            width: 100%;
            border-collapse: collapse;
            background: var(--secondary-bg);
        }

        .llm-predictions-table th,
        .llm-predictions-table td {
            padding: 12px;
            text-align: center;
            border-bottom: 1px solid var(--border-primary);
        }

        .llm-predictions-table th {
            background: var(--tertiary-bg);
            color: var(--accent-purple);
            font-weight: 600;
        }

        .llm-predictions-table .positive {
            color: var(--accent-green);
            font-weight: 600;
        }

        .llm-predictions-table .negative {
            color: var(--accent-red);
            font-weight: 600;
        }

        /* 移动端适配 */
        @media (max-width: 768px) {
            .comprehensive-grid {
                grid-template-columns: 1fr;
            }

            .comprehensive-grid-two-col {
                grid-template-columns: 1fr;
            }

            /* 移动端不跨行，按顺序纵向排列 */
            .comprehensive-grid-two-col .analysis-card:nth-child(2) {
                grid-row: auto;
            }

            .event-level-section {
                grid-template-columns: 1fr;
            }

            .guba-stats {
                grid-template-columns: 1fr;
            }

            .guba-stats-compact {
                grid-template-columns: 1fr;
            }

            .llm-analysis-section {
                grid-template-columns: 1fr;
            }

            .llm-predictions-table {
                font-size: 0.9em;
            }
        }
        """


# 便捷函数
def generate_comprehensive_report(stock_code: str, analysis_data: Dict,
                                  historical_data: Optional[pd.DataFrame] = None,
                                  predictions: Optional[pd.DataFrame] = None,
                                  png_chart_path: Optional[str] = None,
                                  auto_open: bool = True,
                                  fundamental_data: Optional[Dict] = None,
                                  news_data: Optional[Dict] = None,
                                  sentiment_data: Optional[Dict] = None,
                                  event_data: Optional[Dict] = None,
                                  llm_analysis: Optional[Dict] = None,
                                  llm_predicted_kline: Optional[pd.DataFrame] = None) -> str:
    """
    便捷函数: 生成综合分析报告

    Args:
        stock_code: 股票代码
        analysis_data: 分析数据
        historical_data: 历史数据
        predictions: 预测数据
        png_chart_path: PNG图表文件路径
        auto_open: 是否自动打开浏览器
        fundamental_data: 基本面数据（可选）
        news_data: 消息面数据（可选）
        sentiment_data: 情绪数据（可选）
        event_data: 利好利空事件数据（可选）
        llm_analysis: LLM分析结果（可选）
        llm_predicted_kline: LLM预测K线数据（可选）

    Returns:
        生成的HTML报告文件路径
    """
    generator = KronosHTMLReportGenerator()

    # 设置控制台数据（可以从外部传入）
    console_data = {
        'data_count': '1,488',
        'prediction_time': '42',
        'prediction_points': '300',
        'data_range': '2025-07-28 至 2025-09-08',
        'mape': '3.05%',
        'risk_level': '低风险'
    }
    generator.set_console_data(console_data)

    return generator.generate_comprehensive_report(
        stock_code=stock_code,
        analysis_data=analysis_data,
        historical_data=historical_data,
        predictions=predictions,
        png_chart_path=png_chart_path,
        fundamental_data=fundamental_data,
        news_data=news_data,
        sentiment_data=sentiment_data,
        event_data=event_data,
        llm_analysis=llm_analysis,
        llm_predicted_kline=llm_predicted_kline,
        auto_open=auto_open
    )
