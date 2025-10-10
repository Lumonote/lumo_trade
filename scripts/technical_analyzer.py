import pandas as pd
import numpy as np
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

# 不再依赖talib，使用pandas内置计算方法
try:
    import talib

    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False
    print("⚠️  TA-Lib库不可用，使用内置计算方法")


class TechnicalAnalyzer:
    """技术指标分析器"""

    def __init__(self):
        self.indicators = {}
        self.signals = {}
        self.market_sentiment = {}

    def analyze_stock(self, df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
        """分析股票技术指标"""
        if df is None or df.empty or len(df) < 26:
            print(f"❌ {symbol} 数据不足，无法进行技术分析")
            return {}

        print(f"\n📊 开始分析 {symbol} 技术指标...")

        # 准备数据
        close = df['close'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        volume = df['volume'].values.astype(float)

        analysis_result = {
            'symbol': symbol,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'current_price': float(close[-1]),
            'indicators': {},
            'signals': {},
            'market_sentiment': {}
        }

        # 计算技术指标
        try:
            # MACD指标
            macd_result = self._calculate_macd(close)
            analysis_result['indicators']['MACD'] = macd_result

            # 移动平均线
            ma_result = self._calculate_moving_averages(close)
            analysis_result['indicators']['MA'] = ma_result

            # RSI指标
            rsi_result = self._calculate_rsi(close)
            analysis_result['indicators']['RSI'] = rsi_result

            # 布林带
            bb_result = self._calculate_bollinger_bands(close)
            analysis_result['indicators']['BB'] = bb_result

            # KDJ指标
            kdj_result = self._calculate_kdj(high, low, close)
            analysis_result['indicators']['KDJ'] = kdj_result

            # 成交量指标
            volume_result = self._calculate_volume_indicators(close, volume)
            analysis_result['indicators']['VOLUME'] = volume_result

            # 威廉指标
            wr_result = self._calculate_williams_r(high, low, close)
            analysis_result['indicators']['WR'] = wr_result

            # CCI指标
            cci_result = self._calculate_cci(high, low, close)
            analysis_result['indicators']['CCI'] = cci_result

            # 动量指标
            momentum_result = self._calculate_momentum(close)
            analysis_result['indicators']['MOMENTUM'] = momentum_result

            # 抛物线SAR
            sar_result = self._calculate_sar(high, low)
            analysis_result['indicators']['SAR'] = sar_result

            # ADX趋势强度指标
            adx_result = self._calculate_adx(high, low, close)
            analysis_result['indicators']['ADX'] = adx_result

            # 生成交易信号
            analysis_result['signals'] = self._generate_signals(analysis_result['indicators'])

            # 计算市场情绪
            analysis_result['market_sentiment'] = self._calculate_market_sentiment(analysis_result['indicators'])

            # 输出分析结果到控制台
            self._print_analysis_result(analysis_result)

        except Exception as e:
            print(f"❌ 技术分析计算失败: {e}")
            import traceback
            traceback.print_exc()

        return analysis_result

    def _calculate_macd(self, close: np.ndarray) -> Dict[str, Any]:
        """计算MACD指标"""
        try:
            if TALIB_AVAILABLE:
                # 使用talib计算MACD
                macd, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
            else:
                # 使用pandas内置方法计算MACD
                close_series = pd.Series(close)
                ema12 = close_series.ewm(span=12).mean()
                ema26 = close_series.ewm(span=26).mean()
                macd = (ema12 - ema26).values
                macd_signal = pd.Series(macd).ewm(span=9).mean().values
                macd_hist = macd - macd_signal

            # 获取最新值
            current_macd = macd[-1] if not np.isnan(macd[-1]) else 0
            current_signal = macd_signal[-1] if not np.isnan(macd_signal[-1]) else 0
            current_hist = macd_hist[-1] if not np.isnan(macd_hist[-1]) else 0

            # 判断金叉死叉
            golden_cross = False
            death_cross = False

            if len(macd) >= 2 and len(macd_signal) >= 2:
                prev_macd = macd[-2] if not np.isnan(macd[-2]) else 0
                prev_signal = macd_signal[-2] if not np.isnan(macd_signal[-2]) else 0

                # 金叉：MACD从下方穿越信号线
                if prev_macd <= prev_signal and current_macd > current_signal:
                    golden_cross = True
                # 死叉：MACD从上方跌破信号线
                elif prev_macd >= prev_signal and current_macd < current_signal:
                    death_cross = True

            return {
                'macd': float(current_macd),
                'signal': float(current_signal),
                'histogram': float(current_hist),
                'golden_cross': golden_cross,
                'death_cross': death_cross,
                'trend': '看涨' if current_macd > current_signal else '看跌'
            }
        except Exception as e:
            print(f"❌ MACD计算失败: {e}")
            return {}

    def _calculate_moving_averages(self, close: np.ndarray) -> Dict[str, Any]:
        """计算移动平均线"""
        try:
            if TALIB_AVAILABLE:
                ma5 = talib.SMA(close, timeperiod=5)
                ma10 = talib.SMA(close, timeperiod=10)
                ma20 = talib.SMA(close, timeperiod=20)
                ma60 = talib.SMA(close, timeperiod=60) if len(close) >= 60 else np.full(len(close), np.nan)
            else:
                # 使用pandas内置方法计算移动平均线
                close_series = pd.Series(close)
                ma5 = close_series.rolling(window=5).mean().values
                ma10 = close_series.rolling(window=10).mean().values
                ma20 = close_series.rolling(window=20).mean().values
                ma60 = close_series.rolling(window=60).mean().values if len(close) >= 60 else np.full(len(close),
                                                                                                      np.nan)

            current_price = close[-1]
            current_ma5 = ma5[-1] if not np.isnan(ma5[-1]) else 0
            current_ma10 = ma10[-1] if not np.isnan(ma10[-1]) else 0
            current_ma20 = ma20[-1] if not np.isnan(ma20[-1]) else 0
            current_ma60 = ma60[-1] if not np.isnan(ma60[-1]) else 0

            # 判断多头排列
            bullish_alignment = False
            if current_ma5 > 0 and current_ma10 > 0 and current_ma20 > 0:
                if len(close) >= 60 and current_ma60 > 0:
                    bullish_alignment = (current_price > current_ma5 > current_ma10 > current_ma20 > current_ma60)
                else:
                    bullish_alignment = (current_price > current_ma5 > current_ma10 > current_ma20)

            # 判断空头排列
            bearish_alignment = False
            if current_ma5 > 0 and current_ma10 > 0 and current_ma20 > 0:
                if len(close) >= 60 and current_ma60 > 0:
                    bearish_alignment = (current_price < current_ma5 < current_ma10 < current_ma20 < current_ma60)
                else:
                    bearish_alignment = (current_price < current_ma5 < current_ma10 < current_ma20)

            return {
                'MA5': float(current_ma5),
                'MA10': float(current_ma10),
                'MA20': float(current_ma20),
                'MA60': float(current_ma60) if current_ma60 > 0 else None,
                'bullish_alignment': bullish_alignment,
                'bearish_alignment': bearish_alignment,
                'trend': '多头排列' if bullish_alignment else ('空头排列' if bearish_alignment else '震荡')
            }
        except Exception as e:
            print(f"❌ 移动平均线计算失败: {e}")
            return {}

    def _calculate_rsi(self, close: np.ndarray) -> Dict[str, Any]:
        """计算RSI指标"""
        try:
            if TALIB_AVAILABLE:
                rsi = talib.RSI(close, timeperiod=14)
            else:
                # 使用pandas内置方法计算RSI
                close_series = pd.Series(close)
                delta = close_series.diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = (100 - (100 / (1 + rs))).values

            current_rsi = rsi[-1] if not np.isnan(rsi[-1]) else 50

            # RSI信号判断
            if current_rsi >= 70:
                signal = '超买'
                trend = '看跌'
            elif current_rsi <= 30:
                signal = '超卖'
                trend = '看涨'
            else:
                signal = '正常'
                trend = '中性'

            return {
                'RSI': float(current_rsi),
                'signal': signal,
                'trend': trend
            }
        except Exception as e:
            print(f"❌ RSI计算失败: {e}")
            return {}

    def _calculate_bollinger_bands(self, close: np.ndarray) -> Dict[str, Any]:
        """计算布林带指标"""
        try:
            if TALIB_AVAILABLE:
                upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
            else:
                # 使用pandas内置方法计算布林带
                close_series = pd.Series(close)
                middle = close_series.rolling(window=20).mean().values
                std = close_series.rolling(window=20).std().values
                upper = middle + (std * 2)
                lower = middle - (std * 2)

            current_price = close[-1]
            current_upper = upper[-1] if not np.isnan(upper[-1]) else 0
            current_middle = middle[-1] if not np.isnan(middle[-1]) else 0
            current_lower = lower[-1] if not np.isnan(lower[-1]) else 0

            # 布林带位置判断
            if current_upper > 0 and current_lower > 0:
                bb_position = (current_price - current_lower) / (current_upper - current_lower)

                if bb_position >= 0.8:
                    signal = '接近上轨'
                    trend = '可能回调'
                elif bb_position <= 0.2:
                    signal = '接近下轨'
                    trend = '可能反弹'
                else:
                    signal = '中轨附近'
                    trend = '震荡'
            else:
                bb_position = 0.5
                signal = '计算中'
                trend = '中性'

            return {
                'upper': float(current_upper),
                'middle': float(current_middle),
                'lower': float(current_lower),
                'position': float(bb_position),
                'signal': signal,
                'trend': trend
            }
        except Exception as e:
            print(f"❌ 布林带计算失败: {e}")
            return {}

    def _calculate_kdj(self, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Dict[str, Any]:
        """计算KDJ指标"""
        try:
            if TALIB_AVAILABLE:
                k, d = talib.STOCH(high, low, close, fastk_period=9, slowk_period=3, slowd_period=3)
                j = 3 * k - 2 * d
            else:
                # 使用内置方法计算KDJ
                period = 9
                if len(high) < period:
                    return {}

                # 计算RSV (Raw Stochastic Value)
                rsv = np.zeros(len(close))
                for i in range(period - 1, len(close)):
                    highest = np.max(high[i - period + 1:i + 1])
                    lowest = np.min(low[i - period + 1:i + 1])
                    if highest != lowest:
                        rsv[i] = (close[i] - lowest) / (highest - lowest) * 100
                    else:
                        rsv[i] = 50

                # 计算K、D值
                k = np.zeros(len(close))
                d = np.zeros(len(close))
                k[period - 1] = rsv[period - 1]
                d[period - 1] = k[period - 1]

                for i in range(period, len(close)):
                    k[i] = (2 / 3) * k[i - 1] + (1 / 3) * rsv[i]
                    d[i] = (2 / 3) * d[i - 1] + (1 / 3) * k[i]

                j = 3 * k - 2 * d

            current_k = k[-1] if not np.isnan(k[-1]) else 50
            current_d = d[-1] if not np.isnan(d[-1]) else 50
            current_j = j[-1] if not np.isnan(j[-1]) else 50

            # KDJ信号判断
            if current_k >= 80 and current_d >= 80:
                signal = '超买'
                trend = '看跌'
            elif current_k <= 20 and current_d <= 20:
                signal = '超卖'
                trend = '看涨'
            else:
                signal = '正常'
                trend = '中性'

            # 金叉死叉判断
            golden_cross = False
            death_cross = False
            if len(k) >= 2 and len(d) >= 2:
                prev_k = k[-2] if not np.isnan(k[-2]) else 50
                prev_d = d[-2] if not np.isnan(d[-2]) else 50

                if prev_k <= prev_d and current_k > current_d:
                    golden_cross = True
                elif prev_k >= prev_d and current_k < current_d:
                    death_cross = True

            return {
                'K': float(current_k),
                'D': float(current_d),
                'J': float(current_j),
                'signal': signal,
                'trend': trend,
                'golden_cross': golden_cross,
                'death_cross': death_cross
            }
        except Exception as e:
            print(f"❌ KDJ计算失败: {e}")
            return {}

    def _calculate_volume_indicators(self, close: np.ndarray, volume: np.ndarray) -> Dict[str, Any]:
        """计算成交量指标"""
        try:
            # 成交量移动平均
            if TALIB_AVAILABLE:
                vol_ma5 = talib.SMA(volume, timeperiod=5)
                vol_ma10 = talib.SMA(volume, timeperiod=10)
            else:
                # 使用pandas内置方法计算移动平均
                vol_series = pd.Series(volume)
                vol_ma5 = vol_series.rolling(window=5, min_periods=1).mean().values
                vol_ma10 = vol_series.rolling(window=10, min_periods=1).mean().values

            current_volume = volume[-1]
            current_vol_ma5 = vol_ma5[-1] if not np.isnan(vol_ma5[-1]) else 0
            current_vol_ma10 = vol_ma10[-1] if not np.isnan(vol_ma10[-1]) else 0

            # 量价关系分析
            price_change = (close[-1] - close[-2]) / close[-2] if len(close) >= 2 else 0
            volume_ratio = current_volume / current_vol_ma5 if current_vol_ma5 > 0 else 1

            # 成交量信号
            if volume_ratio >= 2:
                vol_signal = '放量'
            elif volume_ratio <= 0.5:
                vol_signal = '缩量'
            else:
                vol_signal = '正常'

            # 量价配合分析
            if price_change > 0.02 and volume_ratio >= 1.5:
                vol_price_signal = '量价齐升'
                trend = '强势上涨'
            elif price_change < -0.02 and volume_ratio >= 1.5:
                vol_price_signal = '量价齐跌'
                trend = '弱势下跌'
            elif price_change > 0.02 and volume_ratio < 0.8:
                vol_price_signal = '价涨量缩'
                trend = '上涨乏力'
            elif price_change < -0.02 and volume_ratio < 0.8:
                vol_price_signal = '价跌量缩'
                trend = '下跌放缓'
            else:
                vol_price_signal = '量价平衡'
                trend = '震荡整理'

            return {
                'current_volume': float(current_volume),
                'vol_ma5': float(current_vol_ma5),
                'vol_ma10': float(current_vol_ma10),
                'volume_ratio': float(volume_ratio),
                'vol_signal': vol_signal,
                'vol_price_signal': vol_price_signal,
                'trend': trend
            }
        except Exception as e:
            print(f"❌ 成交量指标计算失败: {e}")
            return {}

    def _calculate_williams_r(self, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Dict[str, Any]:
        """计算威廉指标(%R)"""
        try:
            if TALIB_AVAILABLE:
                wr = talib.WILLR(high, low, close, timeperiod=14)
            else:
                # 使用内置方法计算Williams %R
                high_series = pd.Series(high)
                low_series = pd.Series(low)
                close_series = pd.Series(close)

                highest_high = high_series.rolling(window=14).max()
                lowest_low = low_series.rolling(window=14).min()
                wr = -100 * (highest_high - close_series) / (highest_high - lowest_low)
                wr = wr.values

            current_wr = wr[-1] if not np.isnan(wr[-1]) else -50

            # 威廉指标信号判断
            if current_wr <= -80:
                signal = '超卖'
                trend = '看涨'
            elif current_wr >= -20:
                signal = '超买'
                trend = '看跌'
            else:
                signal = '正常'
                trend = '中性'

            return {
                'WR': float(current_wr),
                'signal': signal,
                'trend': trend
            }
        except Exception as e:
            print(f"❌ 威廉指标计算失败: {e}")
            return {}

    def _calculate_cci(self, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Dict[str, Any]:
        """计算CCI指标"""
        try:
            if TALIB_AVAILABLE:
                cci = talib.CCI(high, low, close, timeperiod=14)
            else:
                # 使用内置方法计算CCI
                high_series = pd.Series(high)
                low_series = pd.Series(low)
                close_series = pd.Series(close)

                tp = (high_series + low_series + close_series) / 3  # 典型价格
                sma_tp = tp.rolling(window=14).mean()  # 典型价格的移动平均
                mad = tp.rolling(window=14).apply(lambda x: np.mean(np.abs(x - x.mean())))  # 平均绝对偏差
                cci = (tp - sma_tp) / (0.015 * mad)
                cci = cci.values

            current_cci = cci[-1] if not np.isnan(cci[-1]) else 0

            # CCI信号判断
            if current_cci >= 100:
                signal = '超买'
                trend = '看跌'
            elif current_cci <= -100:
                signal = '超卖'
                trend = '看涨'
            else:
                signal = '正常'
                trend = '中性'

            return {
                'CCI': float(current_cci),
                'signal': signal,
                'trend': trend
            }
        except Exception as e:
            print(f"❌ CCI指标计算失败: {e}")
            return {}

    def _calculate_momentum(self, close: np.ndarray) -> Dict[str, Any]:
        """计算动量指标"""
        try:
            if TALIB_AVAILABLE:
                momentum = talib.MOM(close, timeperiod=10)
            else:
                # 使用内置方法计算动量
                close_series = pd.Series(close)
                momentum = close_series - close_series.shift(10)
                momentum = momentum.values

            current_momentum = momentum[-1] if not np.isnan(momentum[-1]) else 0

            # 动量信号判断
            if current_momentum > 0:
                signal = '上涨动量'
                trend = '看涨'
            elif current_momentum < 0:
                signal = '下跌动量'
                trend = '看跌'
            else:
                signal = '无动量'
                trend = '中性'

            # 动量强度判断
            abs_momentum = abs(current_momentum)
            if abs_momentum > 2:
                strength = '强'
            elif abs_momentum > 1:
                strength = '中'
            else:
                strength = '弱'

            return {
                'MOMENTUM': float(current_momentum),
                'signal': signal,
                'trend': trend,
                'strength': strength
            }
        except Exception as e:
            print(f"❌ 动量指标计算失败: {e}")
            return {}

    def _calculate_sar(self, high: np.ndarray, low: np.ndarray) -> Dict[str, Any]:
        """计算抛物线SAR指标"""
        try:
            if TALIB_AVAILABLE:
                sar = talib.SAR(high, low, acceleration=0.02, maximum=0.2)
            else:
                # 使用简化的SAR计算方法
                sar = np.full_like(high, np.nan)
                if len(high) > 1:
                    # 简化版SAR：使用前一日的最低价作为SAR值
                    sar[1:] = low[:-1]
                    sar[0] = low[0]

            current_sar = sar[-1] if not np.isnan(sar[-1]) else 0
            current_price = (high[-1] + low[-1]) / 2

            # SAR信号判断
            if current_price > current_sar:
                signal = '上升趋势'
                trend = '看涨'
            elif current_price < current_sar:
                signal = '下降趋势'
                trend = '看跌'
            else:
                signal = '转折点'
                trend = '中性'

            # 趋势转换判断
            trend_change = False
            if len(sar) >= 2:
                prev_sar = sar[-2] if not np.isnan(sar[-2]) else current_sar
                prev_price = (high[-2] + low[-2]) / 2 if len(high) >= 2 else current_price

                # 检测趋势转换
                if (prev_price <= prev_sar and current_price > current_sar) or \
                        (prev_price >= prev_sar and current_price < current_sar):
                    trend_change = True

            return {
                'SAR': float(current_sar),
                'current_price': float(current_price),
                'signal': signal,
                'trend': trend,
                'trend_change': trend_change
            }
        except Exception as e:
            print(f"❌ SAR指标计算失败: {e}")
            return {}

    def _calculate_adx(self, high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Dict[str, Any]:
        """计算ADX趋势强度指标"""
        try:
            if TALIB_AVAILABLE:
                adx = talib.ADX(high, low, close, timeperiod=14)
                plus_di = talib.PLUS_DI(high, low, close, timeperiod=14)
                minus_di = talib.MINUS_DI(high, low, close, timeperiod=14)

                current_adx = adx[-1] if not np.isnan(adx[-1]) else 0
                current_plus_di = plus_di[-1] if not np.isnan(plus_di[-1]) else 0
                current_minus_di = minus_di[-1] if not np.isnan(minus_di[-1]) else 0
            else:
                # 使用内置方法计算ADX
                current_adx, current_plus_di, current_minus_di = self._calculate_adx_builtin(high, low, close)

            # ADX趋势强度判断
            if current_adx >= 50:
                strength = '极强趋势'
            elif current_adx >= 25:
                strength = '强趋势'
            elif current_adx >= 20:
                strength = '中等趋势'
            else:
                strength = '弱趋势或震荡'

            # 趋势方向判断
            if current_plus_di > current_minus_di:
                direction = '上升趋势'
                trend = '看涨'
            elif current_minus_di > current_plus_di:
                direction = '下降趋势'
                trend = '看跌'
            else:
                direction = '无明确趋势'
                trend = '中性'

            return {
                'ADX': float(current_adx),
                'PLUS_DI': float(current_plus_di),
                'MINUS_DI': float(current_minus_di),
                'strength': strength,
                'direction': direction,
                'trend': trend
            }
        except Exception as e:
            print(f"❌ ADX指标计算失败: {e}")
            return {}

    def _calculate_adx_builtin(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> Tuple[
        float, float, float]:
        """使用内置方法计算ADX指标"""
        if len(high) < period + 1:
            return 0.0, 0.0, 0.0

        try:
            # 计算True Range
            tr1 = high - low
            tr2 = np.abs(high - np.roll(close, 1))
            tr3 = np.abs(low - np.roll(close, 1))
            tr = np.maximum(tr1, np.maximum(tr2, tr3))
            tr = tr[1:]  # 去除第一个无效值

            # 计算Directional Movement
            high_diff = high[1:] - high[:-1]
            low_diff = low[:-1] - low[1:]

            plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
            minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)

            if len(tr) < period:
                return 0.0, 0.0, 0.0

            # 计算ATR (Average True Range)
            atr = np.mean(tr[-period:])

            # 计算DI+ 和 DI-
            plus_di_sum = np.mean(plus_dm[-period:])
            minus_di_sum = np.mean(minus_dm[-period:])

            if atr == 0:
                return 0.0, 0.0, 0.0

            plus_di = (plus_di_sum / atr) * 100
            minus_di = (minus_di_sum / atr) * 100

            # 计算ADX
            dx = abs(plus_di - minus_di) / (plus_di + minus_di + 0.000001) * 100
            adx = dx  # 简化版本，实际应该是DX的移动平均

            return adx, plus_di, minus_di

        except Exception as e:
            print(f"⚠️  ADX内置计算失败: {e}")
            return 0.0, 0.0, 0.0

    def _generate_signals(self, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """生成交易信号"""
        signals = {
            'buy_signals': [],
            'sell_signals': [],
            'overall_signal': '中性',
            'confidence': 0
        }

        buy_score = 0
        sell_score = 0

        # MACD信号
        if 'MACD' in indicators and indicators['MACD']:
            macd = indicators['MACD']
            if macd.get('golden_cross'):
                signals['buy_signals'].append('MACD金叉')
                buy_score += 2
            elif macd.get('death_cross'):
                signals['sell_signals'].append('MACD死叉')
                sell_score += 2

        # 均线信号
        if 'MA' in indicators and indicators['MA']:
            ma = indicators['MA']
            if ma.get('bullish_alignment'):
                signals['buy_signals'].append('均线多头排列')
                buy_score += 3
            elif ma.get('bearish_alignment'):
                signals['sell_signals'].append('均线空头排列')
                sell_score += 3

        # RSI信号
        if 'RSI' in indicators and indicators['RSI']:
            rsi = indicators['RSI']
            if rsi.get('signal') == '超卖':
                signals['buy_signals'].append('RSI超卖')
                buy_score += 1
            elif rsi.get('signal') == '超买':
                signals['sell_signals'].append('RSI超买')
                sell_score += 1

        # KDJ信号
        if 'KDJ' in indicators and indicators['KDJ']:
            kdj = indicators['KDJ']
            if kdj.get('golden_cross'):
                signals['buy_signals'].append('KDJ金叉')
                buy_score += 1
            elif kdj.get('death_cross'):
                signals['sell_signals'].append('KDJ死叉')
                sell_score += 1

        # 成交量信号
        if 'VOLUME' in indicators and indicators['VOLUME']:
            volume = indicators['VOLUME']
            if volume.get('vol_price_signal') == '量价齐升':
                signals['buy_signals'].append('量价齐升')
                buy_score += 2
            elif volume.get('vol_price_signal') == '量价齐跌':
                signals['sell_signals'].append('量价齐跌')
                sell_score += 2

        # 综合信号判断
        total_score = buy_score + sell_score
        if total_score > 0:
            if buy_score > sell_score:
                signals['overall_signal'] = '买入'
                signals['confidence'] = min(buy_score / total_score * 100, 100)
            elif sell_score > buy_score:
                signals['overall_signal'] = '卖出'
                signals['confidence'] = min(sell_score / total_score * 100, 100)
            else:
                signals['overall_signal'] = '中性'
                signals['confidence'] = 50

        return signals

    def _calculate_market_sentiment(self, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """计算市场情绪"""
        sentiment = {
            'overall_sentiment': '中性',
            'sentiment_score': 50,
            'risk_level': '中等',
            'market_phase': '震荡'
        }

        bullish_factors = 0
        bearish_factors = 0
        total_factors = 0

        # 分析各项指标的情绪倾向
        if 'MACD' in indicators and indicators['MACD']:
            total_factors += 1
            if indicators['MACD'].get('trend') == '看涨':
                bullish_factors += 1
            elif indicators['MACD'].get('trend') == '看跌':
                bearish_factors += 1

        if 'MA' in indicators and indicators['MA']:
            total_factors += 1
            if indicators['MA'].get('bullish_alignment'):
                bullish_factors += 1
            elif indicators['MA'].get('bearish_alignment'):
                bearish_factors += 1

        if 'RSI' in indicators and indicators['RSI']:
            total_factors += 1
            if indicators['RSI'].get('trend') == '看涨':
                bullish_factors += 1
            elif indicators['RSI'].get('trend') == '看跌':
                bearish_factors += 1

        if 'KDJ' in indicators and indicators['KDJ']:
            total_factors += 1
            if indicators['KDJ'].get('trend') == '看涨':
                bullish_factors += 1
            elif indicators['KDJ'].get('trend') == '看跌':
                bearish_factors += 1

        if 'VOLUME' in indicators and indicators['VOLUME']:
            total_factors += 1
            vol_trend = indicators['VOLUME'].get('trend', '')
            if '上涨' in vol_trend or '强势' in vol_trend:
                bullish_factors += 1
            elif '下跌' in vol_trend or '弱势' in vol_trend:
                bearish_factors += 1

        # 计算情绪得分
        if total_factors > 0:
            bullish_ratio = bullish_factors / total_factors
            bearish_ratio = bearish_factors / total_factors

            if bullish_ratio >= 0.7:
                sentiment['overall_sentiment'] = '乐观'
                sentiment['sentiment_score'] = 70 + (bullish_ratio - 0.7) * 100
                sentiment['risk_level'] = '较低'
                sentiment['market_phase'] = '上升'
            elif bearish_ratio >= 0.7:
                sentiment['overall_sentiment'] = '悲观'
                sentiment['sentiment_score'] = 30 - (bearish_ratio - 0.7) * 100
                sentiment['risk_level'] = '较高'
                sentiment['market_phase'] = '下降'
            elif bullish_ratio > bearish_ratio:
                sentiment['overall_sentiment'] = '偏乐观'
                sentiment['sentiment_score'] = 50 + (bullish_ratio - bearish_ratio) * 50
                sentiment['risk_level'] = '中等'
                sentiment['market_phase'] = '震荡偏强'
            elif bearish_ratio > bullish_ratio:
                sentiment['overall_sentiment'] = '偏悲观'
                sentiment['sentiment_score'] = 50 - (bearish_ratio - bullish_ratio) * 50
                sentiment['risk_level'] = '中等'
                sentiment['market_phase'] = '震荡偏弱'

        return sentiment

    def _print_analysis_result(self, result: Dict[str, Any]):
        """打印分析结果到控制台"""
        print(f"\n{'=' * 60}")
        print(f"📈 {result['symbol']} 技术分析报告")
        print(f"⏰ 分析时间: {result['timestamp']}")
        print(f"💰 当前价格: ¥{result['current_price']:.2f}")
        print(f"{'=' * 60}")

        # MACD分析
        if 'MACD' in result['indicators'] and result['indicators']['MACD']:
            macd = result['indicators']['MACD']
            print(f"\n📊 MACD指标分析:")
            print(f"   MACD值: {macd.get('macd', 0):.4f}")
            print(f"   信号线: {macd.get('signal', 0):.4f}")
            print(f"   柱状图: {macd.get('histogram', 0):.4f}")
            print(f"   趋势: {macd.get('trend', '中性')}")
            if macd.get('golden_cross'):
                print(f"   🟢 MACD金叉 - 买入信号!")
            elif macd.get('death_cross'):
                print(f"   🔴 MACD死叉 - 卖出信号!")

        # 移动平均线分析
        if 'MA' in result['indicators'] and result['indicators']['MA']:
            ma = result['indicators']['MA']
            print(f"\n📈 移动平均线分析:")
            print(f"   MA5: ¥{ma.get('MA5', 0):.2f}")
            print(f"   MA10: ¥{ma.get('MA10', 0):.2f}")
            print(f"   MA20: ¥{ma.get('MA20', 0):.2f}")
            if ma.get('MA60'):
                print(f"   MA60: ¥{ma.get('MA60', 0):.2f}")
            print(f"   趋势: {ma.get('trend', '震荡')}")
            if ma.get('bullish_alignment'):
                print(f"   🟢 均线多头排列 - 强势上涨!")
            elif ma.get('bearish_alignment'):
                print(f"   🔴 均线空头排列 - 弱势下跌!")

        # RSI分析
        if 'RSI' in result['indicators'] and result['indicators']['RSI']:
            rsi = result['indicators']['RSI']
            print(f"\n🎯 RSI指标分析:")
            print(f"   RSI值: {rsi.get('RSI', 50):.2f}")
            print(f"   信号: {rsi.get('signal', '正常')}")
            print(f"   趋势: {rsi.get('trend', '中性')}")

        # KDJ分析
        if 'KDJ' in result['indicators'] and result['indicators']['KDJ']:
            kdj = result['indicators']['KDJ']
            print(f"\n⚡ KDJ指标分析:")
            print(f"   K值: {kdj.get('K', 50):.2f}")
            print(f"   D值: {kdj.get('D', 50):.2f}")
            print(f"   J值: {kdj.get('J', 50):.2f}")
            print(f"   信号: {kdj.get('signal', '正常')}")
            if kdj.get('golden_cross'):
                print(f"   🟢 KDJ金叉 - 买入信号!")
            elif kdj.get('death_cross'):
                print(f"   🔴 KDJ死叉 - 卖出信号!")

        # 成交量分析
        if 'VOLUME' in result['indicators'] and result['indicators']['VOLUME']:
            volume = result['indicators']['VOLUME']
            print(f"\n📊 成交量分析:")
            print(f"   当前成交量: {volume.get('current_volume', 0):,.0f}")
            print(f"   5日均量: {volume.get('vol_ma5', 0):,.0f}")
            print(f"   量比: {volume.get('volume_ratio', 1):.2f}")
            print(f"   成交量信号: {volume.get('vol_signal', '正常')}")
            print(f"   量价关系: {volume.get('vol_price_signal', '量价平衡')}")
            print(f"   趋势: {volume.get('trend', '震荡整理')}")

        # 交易信号
        if 'signals' in result and result['signals']:
            signals = result['signals']
            print(f"\n🎯 交易信号分析:")
            print(f"   综合信号: {signals.get('overall_signal', '中性')}")
            print(f"   信号强度: {signals.get('confidence', 0):.1f}%")

            if signals.get('buy_signals'):
                print(f"   🟢 买入信号: {', '.join(signals['buy_signals'])}")

            if signals.get('sell_signals'):
                print(f"   🔴 卖出信号: {', '.join(signals['sell_signals'])}")

        # 市场情绪
        if 'market_sentiment' in result and result['market_sentiment']:
            sentiment = result['market_sentiment']
            print(f"\n🌡️ 市场情绪分析:")
            print(f"   整体情绪: {sentiment.get('overall_sentiment', '中性')}")
            print(f"   情绪得分: {sentiment.get('sentiment_score', 50):.1f}/100")
            print(f"   风险等级: {sentiment.get('risk_level', '中等')}")
            print(f"   市场阶段: {sentiment.get('market_phase', '震荡')}")

        print(f"\n{'=' * 60}")
        print(f"📝 分析完成")
        print(f"{'=' * 60}\n")

    def analyze_and_print(self, df: pd.DataFrame, symbol: str):
        """分析股票并打印结果"""
        result = self.analyze_stock(df, symbol)
        return result
