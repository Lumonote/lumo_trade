"""
Kronos股票预测系统 - 技术分析模块
"""

__all__ = ['TechnicalAnalysis', 'QuantitativeModels']


def __getattr__(name):
    if name in __all__:
        from .technical_analysis import QuantitativeModels, TechnicalAnalysis

        exports = {
            'TechnicalAnalysis': TechnicalAnalysis,
            'QuantitativeModels': QuantitativeModels,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
