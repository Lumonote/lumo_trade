import datetime
from pathlib import Path
import pandas as pd

from html_report_generator import KronosHTMLReportGenerator


def make_demo_predictions(start_date: str, days: int = 5, base: float = 28.7) -> list:
    dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    rows = []
    for i in range(days):
        d = dt + datetime.timedelta(days=i)
        open_p = base + i * 0.1
        high_p = open_p + 0.3
        low_p = open_p - 0.2
        close_p = open_p + 0.15
        change_pct = (close_p - open_p) / open_p * 100
        rows.append({
            "date": d.strftime("%Y-%m-%d"),
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "change_pct": round(change_pct, 2)
        })
    return rows


def generate_demo_reports():
    gen = KronosHTMLReportGenerator()

    analysis_data = {
        "indicators": {},
        "signals": {},
        "summary": {
            "risk_level": "低风险",
            "opportunity_level": "中等"
        }
    }

    # 多模型：DeepSeek 有结构化数据，Qwen 返回错误占位
    llm_multi = {
        "deepseek": {
            "kline_prediction": {
                "trend": "看涨",
                "confidence": 0.65,
                "support_levels": [28.8, 28.2],
                "resistance_levels": [29.2, 29.8],
                "predictions": make_demo_predictions("2025-11-10", 5, 28.7)
            },
            "operation_advice": {"advice": "逢低吸纳，分批建仓"},
            "risk_assessment": {"risks": ["短期波动风险"], "level": "中等"},
            "strategy": {"plan": "突破29.2跟进，跌破28.4止损"},
            "summary": "趋势偏上行，量能温和放大"
        },
        "qwen": {
            "error": "模型未返回结构化JSON"
        }
    }

    # 单模型：仅 Qwen，测试单列满宽
    llm_single = {
        "qwen": {
            "kline_prediction": {
                "trend": "看涨",
                "confidence": 0.72,
                "support_levels": [28.6, 28.3],
                "resistance_levels": [29.1, 29.6],
                "predictions": make_demo_predictions("2025-11-10", 5, 28.6)
            },
            "operation_advice": {"advice": "突破跟随，量缩谨慎"},
            "risk_assessment": {"risks": ["消息面扰动"], "level": "中低"},
            "strategy": {"plan": "29.1-29.3试仓，29.7附近减仓"},
            "summary": "整体偏强，注意节奏"
        }
    }

    # 生成两个报告
    path_multi = gen.generate_comprehensive_report(
        stock_code="300290",
        analysis_data=analysis_data,
        llm_analysis=llm_multi,
        auto_open=False
    )

    path_single = gen.generate_comprehensive_report(
        stock_code="300290",
        analysis_data=analysis_data,
        llm_analysis=llm_single,
        auto_open=False
    )

    return path_multi, path_single


if __name__ == "__main__":
    p_multi, p_single = generate_demo_reports()
    print("MULTI:", p_multi)
    print("SINGLE:", p_single)