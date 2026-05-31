"""
高级分析模块 v1.0
包含：筹码分析、板块联动、分时特征、情绪周期、资金流向、形态识别、时间窗口等

作者：Kronos Team
日期：2025-01
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class AdvancedAnalyzer:
    """高级分析器 - 整合多维度分析功能"""
    
    def __init__(self):
        self.chip_analyzer = ChipAnalyzer()
        self.sector_analyzer = SectorLinkageAnalyzer()
        self.intraday_analyzer = IntradayAnalyzer()
        self.sentiment_cycle = SentimentCycleAnalyzer()
        self.capital_flow = CapitalFlowAnalyzer()
        self.pattern_detector = PatternDetector()
        self.time_window = TimeWindowAnalyzer()
    
    def full_analysis(self, stock_code: str, 
                      historical_data: pd.DataFrame,
                      intraday_data: Optional[pd.DataFrame] = None,
                      fundamental_data: Optional[Dict] = None,
                      market_data: Optional[Dict] = None) -> Dict:
        """
        执行完整的高级分析
        
        Returns:
            包含所有维度分析结果的字典
        """
        result = {
            'stock_code': stock_code,
            'analysis_time': datetime.now().isoformat(),
            'dimensions': {}
        }
        
        try:
            result['dimensions']['chip'] = self.chip_analyzer.analyze(
                stock_code, historical_data
            )
        except Exception as e:
            logger.warning(f"筹码分析失败: {e}")
            result['dimensions']['chip'] = {'error': str(e)}
        
        try:
            result['dimensions']['sector'] = self.sector_analyzer.analyze(
                stock_code, market_data
            )
        except Exception as e:
            logger.warning(f"板块联动分析失败: {e}")
            result['dimensions']['sector'] = {'error': str(e)}
        
        try:
            if intraday_data is not None:
                result['dimensions']['intraday'] = self.intraday_analyzer.analyze(
                    stock_code, intraday_data
                )
        except Exception as e:
            logger.warning(f"分时分析失败: {e}")
            result['dimensions']['intraday'] = {'error': str(e)}
        
        try:
            result['dimensions']['sentiment_cycle'] = self.sentiment_cycle.analyze(
                market_data
            )
        except Exception as e:
            logger.warning(f"情绪周期分析失败: {e}")
            result['dimensions']['sentiment_cycle'] = {'error': str(e)}
        
        try:
            result['dimensions']['capital_flow'] = self.capital_flow.analyze(
                stock_code, historical_data
            )
        except Exception as e:
            logger.warning(f"资金流向分析失败: {e}")
            result['dimensions']['capital_flow'] = {'error': str(e)}
        
        try:
            result['dimensions']['patterns'] = self.pattern_detector.detect_all(
                historical_data
            )
        except Exception as e:
            logger.warning(f"形态识别失败: {e}")
            result['dimensions']['patterns'] = {'error': str(e)}
        
        try:
            result['dimensions']['time_window'] = self.time_window.analyze(
                stock_code, fundamental_data
            )
        except Exception as e:
            logger.warning(f"时间窗口分析失败: {e}")
            result['dimensions']['time_window'] = {'error': str(e)}
        
        result['overall_score'] = self._calculate_overall_score(result['dimensions'])
        
        return result
    
    def _calculate_overall_score(self, dimensions: Dict) -> Dict:
        """计算综合评分"""
        scores = {}
        weights = {
            'chip': 0.15,
            'sector': 0.10,
            'intraday': 0.10,
            'sentiment_cycle': 0.10,
            'capital_flow': 0.20,
            'patterns': 0.20,
            'time_window': 0.15
        }
        
        total_score = 0
        total_weight = 0
        
        for dim, weight in weights.items():
            if dim in dimensions and 'score' in dimensions[dim]:
                score = dimensions[dim]['score']
                scores[dim] = score
                total_score += score * weight
                total_weight += weight
        
        if total_weight > 0:
            final_score = total_score / total_weight
        else:
            final_score = 50.0
        
        return {
            'final_score': round(final_score, 2),
            'dimension_scores': scores,
            'weights_used': weights
        }


class ChipAnalyzer:
    """筹码分析器 - 分析主力控盘度和筹码分布"""
    
    def analyze(self, stock_code: str, historical_data: pd.DataFrame) -> Dict:
        """
        分析筹码集中度
        
        核心指标：
        - 90%筹码成本集中度
        - 主力控盘程度
        - 锁仓形态识别
        """
        result = {
            'score': 50.0,
            'signals': [],
            'details': {}
        }
        
        if historical_data is None or len(historical_data) < 60:
            return result
        
        try:
            close = historical_data['close'].values
            volume = historical_data['volume'].values
            high = historical_data['high'].values
            low = historical_data['low'].values
            
            chip_distribution = self._calculate_chip_distribution(
                close, volume, high, low
            )
            result['details']['chip_distribution'] = chip_distribution
            
            concentration = self._calculate_concentration(chip_distribution)
            result['details']['concentration_90'] = concentration
            
            control_degree = self._estimate_main_force_control(
                close, volume, historical_data.get('turnover', None)
            )
            result['details']['main_force_control'] = control_degree
            
            lock_pattern = self._detect_lock_pattern(
                close, volume, concentration, control_degree
            )
            result['details']['lock_pattern'] = lock_pattern
            
            score = 50.0
            
            if concentration < 10:
                score += 25
                result['signals'].append('🔥 筹码高度集中(<10%)')
            elif concentration < 15:
                score += 15
                result['signals'].append('筹码集中度良好(<15%)')
            elif concentration > 30:
                score -= 15
                result['signals'].append('⚠️ 筹码分散(>30%)')
            
            if control_degree > 70:
                score += 20
                result['signals'].append('🔥 高控盘(>70%)')
            elif control_degree > 50:
                score += 10
                result['signals'].append('中等控盘(50-70%)')
            elif control_degree < 30:
                score -= 10
                result['signals'].append('低控盘(<30%)')
            
            if lock_pattern['detected']:
                score += 15
                result['signals'].append(f"🔒 锁仓形态: {lock_pattern['type']}")
            
            result['score'] = max(0, min(100, score))
            
        except Exception as e:
            logger.error(f"筹码分析错误: {e}")
            result['error'] = str(e)
        
        return result
    
    def _calculate_chip_distribution(self, close: np.ndarray, volume: np.ndarray,
                                      high: np.ndarray, low: np.ndarray,
                                      lookback: int = 60) -> Dict:
        """计算筹码分布"""
        recent_close = close[-lookback:]
        recent_volume = volume[-lookback:]
        recent_high = high[-lookback:]
        recent_low = low[-lookback:]
        
        price_min = float(recent_low.min())
        price_max = float(recent_high.max())
        
        num_bins = 100
        price_bins = np.linspace(price_min, price_max, num_bins + 1)
        chip_dist = np.zeros(num_bins)
        
        decay_factor = 0.95
        
        for i in range(lookback):
            day_idx = lookback - 1 - i
            day_weight = (decay_factor ** i) * recent_volume[day_idx]
            
            day_low = recent_low[day_idx]
            day_high = recent_high[day_idx]
            day_close = recent_close[day_idx]
            
            for j in range(num_bins):
                bin_low = price_bins[j]
                bin_high = price_bins[j + 1]
                bin_mid = (bin_low + bin_high) / 2
                
                if day_low <= bin_mid <= day_high:
                    distance_from_close = abs(bin_mid - day_close)
                    day_range = day_high - day_low if day_high > day_low else 1
                    weight = 1 - (distance_from_close / day_range) * 0.5
                    chip_dist[j] += day_weight * max(0.5, weight)
        
        if chip_dist.sum() > 0:
            chip_dist = chip_dist / chip_dist.sum() * 100
        
        return {
            'price_bins': price_bins.tolist(),
            'distribution': chip_dist.tolist(),
            'price_range': [price_min, price_max]
        }
    
    def _calculate_concentration(self, chip_dist: Dict) -> float:
        """计算90%筹码集中度"""
        distribution = np.array(chip_dist['distribution'])
        price_bins = np.array(chip_dist['price_bins'])
        
        if distribution.sum() == 0:
            return 50.0
        
        cumsum = np.cumsum(distribution)
        
        idx_5 = np.searchsorted(cumsum, 5)
        idx_95 = np.searchsorted(cumsum, 95)
        
        if idx_5 >= len(price_bins) - 1:
            idx_5 = 0
        if idx_95 >= len(price_bins) - 1:
            idx_95 = len(price_bins) - 2
        
        price_5 = price_bins[idx_5]
        price_95 = price_bins[idx_95]
        
        mid_price = (price_5 + price_95) / 2
        if mid_price > 0:
            concentration = (price_95 - price_5) / mid_price * 100
        else:
            concentration = 50.0
        
        return round(concentration, 2)
    
    def _estimate_main_force_control(self, close: np.ndarray, volume: np.ndarray,
                                      turnover: Optional[np.ndarray] = None) -> float:
        """估算主力控盘程度"""
        if len(close) < 60:
            return 50.0
        
        recent_close = close[-60:]
        recent_volume = volume[-60:]
        
        returns = np.diff(recent_close) / recent_close[:-1]
        volatility = np.std(returns) * 100
        
        avg_volume = np.mean(recent_volume)
        volume_stability = 1 - (np.std(recent_volume) / avg_volume) if avg_volume > 0 else 0
        
        if turnover is not None and len(turnover) >= 60:
            avg_turnover = np.mean(turnover[-60:])
            turnover_factor = max(0, 1 - avg_turnover / 10)
        else:
            turnover_factor = 0.5
        
        control_degree = (
            (1 - min(volatility / 5, 1)) * 40 +
            volume_stability * 30 +
            turnover_factor * 30
        )
        
        return round(min(100, max(0, control_degree)), 2)
    
    def _detect_lock_pattern(self, close: np.ndarray, volume: np.ndarray,
                              concentration: float, control_degree: float) -> Dict:
        """检测锁仓形态"""
        result = {
            'detected': False,
            'type': None,
            'confidence': 0
        }
        
        if concentration < 15 and control_degree > 60:
            recent_volume = volume[-20:]
            avg_volume = np.mean(volume[-60:-20]) if len(volume) >= 60 else np.mean(volume)
            
            if avg_volume > 0:
                vol_shrink_ratio = np.mean(recent_volume) / avg_volume
                
                if vol_shrink_ratio < 0.6:
                    result['detected'] = True
                    result['type'] = '高控盘缩量锁仓'
                    result['confidence'] = min(95, 60 + (0.6 - vol_shrink_ratio) * 100)
                elif vol_shrink_ratio < 0.8:
                    result['detected'] = True
                    result['type'] = '温和控盘锁仓'
                    result['confidence'] = min(80, 50 + (0.8 - vol_shrink_ratio) * 75)
        
        return result


class SectorLinkageAnalyzer:
    """板块联动分析器"""
    
    def analyze(self, stock_code: str, market_data: Optional[Dict] = None) -> Dict:
        """
        分析板块联动关系
        
        核心分析：
        - 所属板块表现
        - 与龙头股对比
        - 板块资金流向
        - 板块轮动位置
        """
        result = {
            'score': 50.0,
            'signals': [],
            'details': {}
        }
        
        if market_data is None:
            return result
        
        try:
            sector_info = market_data.get('sector_info', {})
            result['details']['sector_name'] = sector_info.get('name', '未知')
            result['details']['sector_change'] = sector_info.get('change_pct', 0)
            result['details']['sector_rank'] = sector_info.get('rank', 0)
            
            leader_info = market_data.get('sector_leader', {})
            result['details']['leader_code'] = leader_info.get('code', '')
            result['details']['leader_name'] = leader_info.get('name', '')
            result['details']['leader_change'] = leader_info.get('change_pct', 0)
            
            sector_flow = market_data.get('sector_capital_flow', {})
            result['details']['sector_net_inflow'] = sector_flow.get('net_inflow', 0)
            result['details']['sector_main_inflow'] = sector_flow.get('main_inflow', 0)
            
            rotation_phase = market_data.get('rotation_phase', 'unknown')
            result['details']['rotation_phase'] = rotation_phase
            
            score = 50.0
            
            sector_change = sector_info.get('change_pct', 0)
            if sector_change > 3:
                score += 20
                result['signals'].append(f'🔥 板块强势(+{sector_change:.1f}%)')
            elif sector_change > 1:
                score += 10
                result['signals'].append(f'板块偏强(+{sector_change:.1f}%)')
            elif sector_change < -3:
                score -= 20
                result['signals'].append(f'⚠️ 板块弱势({sector_change:.1f}%)')
            elif sector_change < -1:
                score -= 10
            
            sector_rank = sector_info.get('rank', 50)
            if sector_rank <= 10:
                score += 15
                result['signals'].append(f'板块排名前10(第{sector_rank}名)')
            elif sector_rank <= 30:
                score += 5
            elif sector_rank > 80:
                score -= 10
                result['signals'].append(f'⚠️ 板块排名靠后(第{sector_rank}名)')
            
            net_inflow = sector_flow.get('net_inflow', 0)
            if net_inflow > 5:
                score += 15
                result['signals'].append(f'🔥 板块资金净流入{net_inflow:.1f}亿')
            elif net_inflow > 1:
                score += 8
            elif net_inflow < -5:
                score -= 15
                result['signals'].append(f'⚠️ 板块资金净流出{abs(net_inflow):.1f}亿')
            elif net_inflow < -1:
                score -= 8
            
            if rotation_phase == 'early':
                score += 10
                result['signals'].append('板块轮动初期')
            elif rotation_phase == 'peak':
                score -= 5
                result['signals'].append('⚠️ 板块轮动高峰期')
            elif rotation_phase == 'late':
                score -= 15
                result['signals'].append('⚠️ 板块轮动末期')
            
            result['score'] = max(0, min(100, score))
            
        except Exception as e:
            logger.error(f"板块联动分析错误: {e}")
            result['error'] = str(e)
        
        return result


class IntradayAnalyzer:
    """分时图分析器"""
    
    def analyze(self, stock_code: str, intraday_data: pd.DataFrame) -> Dict:
        """
        分析分时图特征
        
        核心分析：
        - 早盘异动检测(9:30-10:00)
        - 尾盘拉升/砸盘预警
        - 主力对倒识别
        - 分时量价配合
        """
        result = {
            'score': 50.0,
            'signals': [],
            'details': {}
        }
        
        if intraday_data is None or len(intraday_data) < 10:
            return result
        
        try:
            morning_analysis = self._analyze_morning_session(intraday_data)
            result['details']['morning'] = morning_analysis
            
            afternoon_analysis = self._analyze_afternoon_session(intraday_data)
            result['details']['afternoon'] = afternoon_analysis
            
            manipulation = self._detect_manipulation(intraday_data)
            result['details']['manipulation'] = manipulation
            
            volume_price = self._analyze_intraday_volume_price(intraday_data)
            result['details']['volume_price'] = volume_price
            
            score = 50.0
            
            if morning_analysis.get('strong_open', False):
                score += 15
                result['signals'].append('🔥 早盘强势开盘')
            if morning_analysis.get('big_order_buy', False):
                score += 10
                result['signals'].append('早盘大单买入')
            
            if afternoon_analysis.get('late_surge', False):
                score -= 10
                result['signals'].append('⚠️ 尾盘拉升(警惕次日低开)')
            if afternoon_analysis.get('late_dump', False):
                score -= 20
                result['signals'].append('🚨 尾盘砸盘')
            
            if manipulation.get('detected', False):
                score -= 25
                result['signals'].append(f"🚨 疑似对倒: {manipulation.get('type', '')}")
            
            if volume_price.get('healthy', False):
                score += 10
                result['signals'].append('分时量价配合良好')
            
            result['score'] = max(0, min(100, score))
            
        except Exception as e:
            logger.error(f"分时分析错误: {e}")
            result['error'] = str(e)
        
        return result
    
    def _analyze_morning_session(self, data: pd.DataFrame) -> Dict:
        """分析早盘(9:30-10:00)"""
        result = {
            'strong_open': False,
            'weak_open': False,
            'big_order_buy': False,
            'big_order_sell': False,
            'open_change_pct': 0
        }
        
        if 'time' in data.columns:
            morning_data = data[data['time'] <= '10:00:00']
        else:
            morning_data = data.head(30)
        
        if len(morning_data) < 5:
            return result
        
        open_price = float(morning_data.iloc[0]['price']) if 'price' in morning_data.columns else 0
        first_30min_high = float(morning_data['price'].max()) if 'price' in morning_data.columns else 0
        first_30min_low = float(morning_data['price'].min()) if 'price' in morning_data.columns else 0
        
        if open_price > 0:
            result['open_change_pct'] = (first_30min_high / open_price - 1) * 100
            
            if result['open_change_pct'] > 3:
                result['strong_open'] = True
            elif result['open_change_pct'] < -3:
                result['weak_open'] = True
        
        if 'amount' in morning_data.columns:
            morning_amount = morning_data['amount'].sum()
            if morning_amount > 0:
                result['morning_amount'] = morning_amount
        
        return result
    
    def _analyze_afternoon_session(self, data: pd.DataFrame) -> Dict:
        """分析尾盘(14:30-15:00)"""
        result = {
            'late_surge': False,
            'late_dump': False,
            'closing_change_pct': 0
        }
        
        if 'time' in data.columns:
            afternoon_data = data[data['time'] >= '14:30:00']
        else:
            afternoon_data = data.tail(30)
        
        if len(afternoon_data) < 5:
            return result
        
        if 'price' in afternoon_data.columns:
            start_price = float(afternoon_data.iloc[0]['price'])
            end_price = float(afternoon_data.iloc[-1]['price'])
            
            if start_price > 0:
                change = (end_price / start_price - 1) * 100
                result['closing_change_pct'] = change
                
                if change > 2:
                    result['late_surge'] = True
                elif change < -2:
                    result['late_dump'] = True
        
        return result
    
    def _detect_manipulation(self, data: pd.DataFrame) -> Dict:
        """检测对倒行为"""
        result = {
            'detected': False,
            'type': None,
            'confidence': 0
        }
        
        if 'volume' not in data.columns or 'price' not in data.columns:
            return result
        
        volumes = data['volume'].values
        prices = data['price'].values
        
        if len(volumes) < 50:
            return result
        
        avg_volume = np.mean(volumes)
        std_volume = np.std(volumes)
        
        spike_threshold = avg_volume + 3 * std_volume
        spikes = volumes > spike_threshold
        
        if spikes.sum() > len(volumes) * 0.1:
            price_changes = np.abs(np.diff(prices))
            spike_price_changes = price_changes[spikes[1:]]
            
            if len(spike_price_changes) > 0:
                avg_spike_change = np.mean(spike_price_changes)
                avg_normal_change = np.mean(price_changes[~spikes[1:]])
                
                if avg_spike_change < avg_normal_change * 0.5:
                    result['detected'] = True
                    result['type'] = '对倒拉升'
                    result['confidence'] = 70
        
        return result
    
    def _analyze_intraday_volume_price(self, data: pd.DataFrame) -> Dict:
        """分析分时量价配合"""
        result = {
            'healthy': False,
            'correlation': 0
        }
        
        if 'volume' not in data.columns or 'price' not in data.columns:
            return result
        
        volumes = data['volume'].values
        prices = data['price'].values
        
        if len(volumes) < 20:
            return result
        
        price_changes = np.diff(prices)
        volume_changes = np.diff(volumes)
        
        if len(price_changes) > 0 and np.std(price_changes) > 0 and np.std(volume_changes) > 0:
            correlation = np.corrcoef(price_changes, volume_changes[0:len(price_changes)])[0, 1]
            result['correlation'] = round(correlation, 3)
            
            if correlation > 0.3:
                result['healthy'] = True
        
        return result


class SentimentCycleAnalyzer:
    """市场情绪周期分析器"""
    
    def analyze(self, market_data: Optional[Dict] = None) -> Dict:
        """
        分析市场情绪周期
        
        核心指标：
        - 恐惧贪婪指数
        - 连板高度
        - 涨停家数/跌停家数
        - 两市成交额
        - 北向资金
        """
        result = {
            'score': 50.0,
            'signals': [],
            'details': {}
        }
        
        if market_data is None:
            return result
        
        try:
            fear_greed = self._calculate_fear_greed_index(market_data)
            result['details']['fear_greed_index'] = fear_greed
            
            limit_analysis = self._analyze_limit_boards(market_data)
            result['details']['limit_analysis'] = limit_analysis
            
            volume_analysis = self._analyze_market_volume(market_data)
            result['details']['volume_analysis'] = volume_analysis
            
            north_flow = market_data.get('north_flow', {})
            result['details']['north_flow'] = north_flow
            
            cycle_phase = self._determine_cycle_phase(
                fear_greed, limit_analysis, volume_analysis
            )
            result['details']['cycle_phase'] = cycle_phase
            
            score = 50.0
            
            if fear_greed['index'] > 70:
                score -= 15
                result['signals'].append(f"⚠️ 市场贪婪({fear_greed['index']})")
            elif fear_greed['index'] < 30:
                score += 15
                result['signals'].append(f"🔥 市场恐惧({fear_greed['index']}),可能见底")
            elif 40 <= fear_greed['index'] <= 60:
                score += 5
                result['signals'].append(f"市场情绪中性({fear_greed['index']})")
            
            max_streak = limit_analysis.get('max_streak', 0)
            if max_streak >= 7:
                score += 10
                result['signals'].append(f"🔥 连板高度{max_streak}板,情绪高涨")
            elif max_streak <= 3:
                score -= 10
                result['signals'].append(f"连板高度仅{max_streak}板,情绪低迷")
            
            limit_up_count = limit_analysis.get('limit_up_count', 0)
            limit_down_count = limit_analysis.get('limit_down_count', 0)
            if limit_up_count > 100:
                score += 10
                result['signals'].append(f"涨停{limit_up_count}家,赚钱效应好")
            elif limit_down_count > 50:
                score -= 15
                result['signals'].append(f"⚠️ 跌停{limit_down_count}家,亏钱效应")
            
            north_net = north_flow.get('net_buy', 0)
            if north_net > 50:
                score += 10
                result['signals'].append(f"🔥 北向净买入{north_net:.0f}亿")
            elif north_net < -50:
                score -= 10
                result['signals'].append(f"⚠️ 北向净卖出{abs(north_net):.0f}亿")
            
            if cycle_phase == 'bottom':
                score += 15
                result['signals'].append('市场周期:底部区域')
            elif cycle_phase == 'rising':
                score += 10
                result['signals'].append('市场周期:上升期')
            elif cycle_phase == 'top':
                score -= 15
                result['signals'].append('⚠️ 市场周期:顶部区域')
            elif cycle_phase == 'falling':
                score -= 10
                result['signals'].append('市场周期:下降期')
            
            result['score'] = max(0, min(100, score))
            
        except Exception as e:
            logger.error(f"情绪周期分析错误: {e}")
            result['error'] = str(e)
        
        return result
    
    def _calculate_fear_greed_index(self, market_data: Dict) -> Dict:
        """计算恐惧贪婪指数 (0-100)"""
        index = 50
        factors = {}
        
        up_ratio = market_data.get('up_ratio', 0.5)
        factors['up_ratio'] = up_ratio
        index += (up_ratio - 0.5) * 40
        
        avg_change = market_data.get('avg_change_pct', 0)
        factors['avg_change'] = avg_change
        index += avg_change * 5
        
        volume_ratio = market_data.get('volume_ratio_vs_ma5', 1.0)
        factors['volume_ratio'] = volume_ratio
        if volume_ratio > 1.2:
            index += 10
        elif volume_ratio < 0.8:
            index -= 10
        
        index = max(0, min(100, index))
        
        if index >= 75:
            emotion = '极度贪婪'
        elif index >= 55:
            emotion = '贪婪'
        elif index >= 45:
            emotion = '中性'
        elif index >= 25:
            emotion = '恐惧'
        else:
            emotion = '极度恐惧'
        
        return {
            'index': round(index, 1),
            'emotion': emotion,
            'factors': factors
        }
    
    def _analyze_limit_boards(self, market_data: Dict) -> Dict:
        """分析涨跌停情况"""
        return {
            'limit_up_count': market_data.get('limit_up_count', 0),
            'limit_down_count': market_data.get('limit_down_count', 0),
            'max_streak': market_data.get('max_limit_streak', 0),
            'natural_limit_up': market_data.get('natural_limit_up', 0),
            'broken_limit_up': market_data.get('broken_limit_up', 0)
        }
    
    def _analyze_market_volume(self, market_data: Dict) -> Dict:
        """分析两市成交额"""
        total_amount = market_data.get('total_amount', 0)
        ma5_amount = market_data.get('ma5_amount', total_amount)
        
        volume_ratio = total_amount / ma5_amount if ma5_amount > 0 else 1.0
        
        if total_amount > 15000:
            level = '极度活跃'
        elif total_amount > 10000:
            level = '活跃'
        elif total_amount > 7000:
            level = '正常'
        else:
            level = '低迷'
        
        return {
            'total_amount_yi': round(total_amount / 100000000, 1) if total_amount > 1e8 else total_amount,
            'volume_ratio': round(volume_ratio, 2),
            'level': level
        }
    
    def _determine_cycle_phase(self, fear_greed: Dict, 
                                limit_analysis: Dict,
                                volume_analysis: Dict) -> str:
        """判断市场周期阶段"""
        fg_index = fear_greed['index']
        max_streak = limit_analysis.get('max_streak', 0)
        volume_ratio = volume_analysis.get('volume_ratio', 1.0)
        
        if fg_index < 25 and max_streak <= 3:
            return 'bottom'
        elif fg_index < 50 and volume_ratio > 1.1:
            return 'rising'
        elif fg_index > 75 and max_streak >= 6:
            return 'top'
        elif fg_index > 50 and volume_ratio < 0.9:
            return 'falling'
        else:
            return 'consolidation'


class CapitalFlowAnalyzer:
    """资金流向分析器 - 接入真实Tushare/东方财富资金流向数据"""

    _moneyflow_cache: Dict = {}  # class-level cache: {stock_code: (timestamp, DataFrame)}
    _tushare_pro = None
    _tushare_token: Optional[str] = None
    _last_api_call: float = 0

    @classmethod
    def _get_tushare_pro(cls):
        """懒加载 Tushare Pro API"""
        if cls._tushare_pro is not None:
            return cls._tushare_pro
        try:
            import tushare as ts
        except ImportError:
            logger.debug("Tushare未安装")
            return None
        if cls._tushare_token is None:
            import os, json
            config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       'config', 'tushare_config.json')
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                cls._tushare_token = config.get('tushare', {}).get('token', '')
            except Exception:
                cls._tushare_token = ''
        if not cls._tushare_token:
            logger.debug("Tushare Token未配置")
            return None
        try:
            import tushare as ts
            cls._tushare_pro = ts.pro_api(cls._tushare_token)
            return cls._tushare_pro
        except Exception as e:
            logger.warning(f"Tushare Pro API初始化失败: {e}")
            return None

    @staticmethod
    def _to_ts_code(stock_code: str) -> str:
        """股票代码转Tushare格式: 000001 -> 000001.SZ"""
        code = stock_code.strip().split('.')[0]
        if code.startswith(('6',)):
            return f"{code}.SH"
        return f"{code}.SZ"

    def _fetch_tushare_moneyflow(self, stock_code: str, days: int = 20) -> Optional[pd.DataFrame]:
        """从Tushare获取个股资金流向数据"""
        import time as _time

        cache_key = stock_code
        now = _time.time()
        if cache_key in self._moneyflow_cache:
            ts_cached, df_cached = self._moneyflow_cache[cache_key]
            if now - ts_cached < 3600:
                return df_cached

        pro = self._get_tushare_pro()
        if pro is None:
            return None

        # 速率限制: 0.3s间隔
        elapsed = now - self.__class__._last_api_call
        if elapsed < 0.3:
            _time.sleep(0.3 - elapsed)

        ts_code = self._to_ts_code(stock_code)
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days + 15)).strftime('%Y%m%d')  # 多取15天buffer应对节假日

        try:
            self.__class__._last_api_call = _time.time()
            df = pro.moneyflow(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is not None and not df.empty:
                df = df.sort_values('trade_date', ascending=False).head(days).reset_index(drop=True)
                self._moneyflow_cache[cache_key] = (_time.time(), df)
                return df
        except Exception as e:
            logger.debug(f"Tushare moneyflow获取失败({ts_code}): {e}")

        self._moneyflow_cache[cache_key] = (_time.time(), None)
        return None

    def _fetch_db_moneyflow(self, stock_code: str, days: int = 20) -> Optional[pd.DataFrame]:
        """E5：读已入库 market_flow_daily（177k 行，密集逐股，东财各档净额/单位万元）。

        命中返回按 trade_date 降序的 df（附 net_mf_amount 别名，复用连续性循环），否则 None。
        """
        try:
            from data_store import market_snapshot_repo
            df = market_snapshot_repo.get_flow_by_code(self._to_ts_code(stock_code), limit=days)
        except Exception as e:  # noqa: BLE001 —— 库不可用时静默回退实时抓取
            logger.debug(f"market_flow_daily 读取异常({stock_code}): {e}")
            return None
        if df is None or df.empty:
            return None
        df = df.copy()
        df['net_mf_amount'] = df['net_amount']  # 仅看符号，与 Tushare moneyflow 字段对齐
        return df

    def _fetch_eastmoney_capital_flow(self, stock_code: str) -> Optional[Dict]:
        """东方财富资金流向数据回退"""
        try:
            from analysis.investor_sentiment import InvestorSentimentAnalyzer
            analyzer = InvestorSentimentAnalyzer(stock_code)
            cf = analyzer.get_capital_flow()
            if not cf or (cf.get('trend') == '未知' and cf.get('main_inflow', 0) == 0):
                return None
            return {
                'super_large_net': cf.get('super_large_inflow', 0),
                'large_net': cf.get('large_inflow', 0),
                'medium_net': cf.get('medium_inflow', 0),
                'small_net': cf.get('small_inflow', 0),
                'main_net_inflow': cf.get('main_inflow', 0),
                'retail_net_inflow': cf.get('retail_inflow', 0),
                'data_source': 'eastmoney',
            }
        except Exception as e:
            logger.debug(f"东方财富资金流向获取失败({stock_code}): {e}")
            return None

    def analyze(self, stock_code: str, historical_data: pd.DataFrame) -> Dict:
        """
        分析资金流向

        数据来源优先级: Tushare moneyflow > 东方财富API > 合成估算(兜底)
        """
        result = {
            'score': 50.0,
            'signals': [],
            'details': {}
        }

        if historical_data is None or len(historical_data) < 5:
            return result

        try:
            order_analysis = self._analyze_order_sizes(stock_code, historical_data)
            result['details']['order_analysis'] = order_analysis

            continuity = self._analyze_main_force_continuity(stock_code, historical_data)
            result['details']['continuity'] = continuity

            retail_ratio = self._estimate_retail_ratio(order_analysis)
            result['details']['retail_ratio'] = retail_ratio
            result['details']['data_source'] = order_analysis.get('data_source', 'synthetic')

            score = 50.0

            # Tushare/东方财富数据单位是元, 阈值用万元级别判断
            main_net = order_analysis.get('main_net_inflow', 0)
            data_source = order_analysis.get('data_source', 'synthetic')

            # 真实数据(market_flow_daily/tushare/eastmoney, 单位元)阈值: 5000万=大幅, 1000万=中等
            if data_source != 'synthetic':
                thresh_high = 50000000   # 5000万
                thresh_low = 10000000    # 1000万
                def _fmt(v): return f"{abs(v)/100000000:.2f}亿" if abs(v) >= 100000000 else f"{abs(v)/10000:.0f}万"
            else:
                # 合成数据保留原有阈值(成交额比例,量级较小)
                thresh_high = 5000
                thresh_low = 1000
                def _fmt(v): return f"{abs(v)/10000:.1f}万"

            if main_net > thresh_high:
                score += 25
                result['signals'].append(f'🔥 主力大幅净流入{_fmt(main_net)}')
            elif main_net > thresh_low:
                score += 15
                result['signals'].append(f'主力净流入{_fmt(main_net)}')
            elif main_net < -thresh_high:
                score -= 25
                result['signals'].append(f'🚨 主力大幅净流出{_fmt(main_net)}')
            elif main_net < -thresh_low:
                score -= 15
                result['signals'].append(f'⚠️ 主力净流出{_fmt(main_net)}')

            if continuity.get('consecutive_inflow_days', 0) >= 5:
                score += 20
                result['signals'].append(f"🔥 连续{continuity['consecutive_inflow_days']}日主力净流入")
            elif continuity.get('consecutive_outflow_days', 0) >= 5:
                score -= 20
                result['signals'].append(f"🚨 连续{continuity['consecutive_outflow_days']}日主力净流出")

            if retail_ratio > 70:
                score -= 15
                result['signals'].append(f'⚠️ 散户占比过高({retail_ratio:.0f}%)')
            elif retail_ratio < 30:
                score += 10
                result['signals'].append(f'主力主导({100-retail_ratio:.0f}%)')

            result['score'] = max(0, min(100, score))

        except Exception as e:
            logger.error(f"资金流向分析错误: {e}")
            result['error'] = str(e)

        return result

    def _analyze_order_sizes(self, stock_code: str, data: pd.DataFrame) -> Dict:
        """分析不同大小订单 - 优先真实数据"""
        default = {
            'super_large_net': 0,
            'large_net': 0,
            'medium_net': 0,
            'small_net': 0,
            'main_net_inflow': 0,
            'retail_net_inflow': 0,
            'data_source': 'synthetic',
        }

        # 0) 已入库 market_flow_daily（优先，spec §6.6：命中即用本地真实数据，省去实时抓取）
        dfb = self._fetch_db_moneyflow(stock_code, days=1)
        if dfb is not None and not dfb.empty:
            latest = dfb.iloc[0]

            def _f(v):
                try:
                    return float(v) if v is not None and not pd.isna(v) else 0.0
                except (TypeError, ValueError):
                    return 0.0

            result = dict(default)
            # 东财 moneyflow_dc：buy_*_amount 已是各档「净额」（万元）→ ×1e4 转元
            result['super_large_net'] = _f(latest.get('buy_elg_amount')) * 1e4
            result['large_net'] = _f(latest.get('buy_lg_amount')) * 1e4
            result['medium_net'] = _f(latest.get('buy_md_amount')) * 1e4
            result['small_net'] = _f(latest.get('buy_sm_amount')) * 1e4
            result['main_net_inflow'] = result['super_large_net'] + result['large_net']
            result['retail_net_inflow'] = result['medium_net'] + result['small_net']
            result['data_source'] = 'market_flow_daily'
            return result

        # 1) Tushare moneyflow (优先)
        df = self._fetch_tushare_moneyflow(stock_code, days=20)
        if df is not None and not df.empty:
            latest = df.iloc[0]  # 最新一天
            # Tushare moneyflow 金额单位: 千元, 转为元
            result = dict(default)
            buy_elg = float(latest.get('buy_elg_amount', 0) or 0) * 1000
            sell_elg = float(latest.get('sell_elg_amount', 0) or 0) * 1000
            buy_lg = float(latest.get('buy_lg_amount', 0) or 0) * 1000
            sell_lg = float(latest.get('sell_lg_amount', 0) or 0) * 1000
            buy_md = float(latest.get('buy_md_amount', 0) or 0) * 1000
            sell_md = float(latest.get('sell_md_amount', 0) or 0) * 1000
            buy_sm = float(latest.get('buy_sm_amount', 0) or 0) * 1000
            sell_sm = float(latest.get('sell_sm_amount', 0) or 0) * 1000

            result['super_large_net'] = buy_elg - sell_elg
            result['large_net'] = buy_lg - sell_lg
            result['medium_net'] = buy_md - sell_md
            result['small_net'] = buy_sm - sell_sm
            result['main_net_inflow'] = result['super_large_net'] + result['large_net']
            result['retail_net_inflow'] = result['medium_net'] + result['small_net']
            # 成交额(买+卖)用于计算散户占比(净额因总和恒为0无法区分)
            result['main_turnover'] = buy_elg + sell_elg + buy_lg + sell_lg
            result['retail_turnover'] = buy_md + sell_md + buy_sm + sell_sm
            result['data_source'] = 'tushare'
            return result

        # 2) 东方财富回退
        em = self._fetch_eastmoney_capital_flow(stock_code)
        if em:
            return em

        # 3) 兜底: 合成估算(保留原逻辑)
        result = dict(default)
        if 'amount' not in data.columns:
            return result
        amounts = data['amount'].values
        close = data['close'].values
        avg_amount = np.mean(amounts[-20:]) if len(amounts) >= 20 else np.mean(amounts)
        if avg_amount > 0 and len(close) > 1:
            direction = 1 if close[-1] > close[-2] else -1
            total_amount = amounts[-1]
            result['super_large_net'] = total_amount * 0.3 * direction
            result['large_net'] = total_amount * 0.25 * direction
            result['medium_net'] = total_amount * 0.25 * (0.5 * direction)
            result['small_net'] = total_amount * 0.2 * (-0.3 * direction)
            result['main_net_inflow'] = result['super_large_net'] + result['large_net']
            result['retail_net_inflow'] = result['medium_net'] + result['small_net']
        return result

    def _analyze_main_force_continuity(self, stock_code: str, data: pd.DataFrame) -> Dict:
        """分析主力资金连续性 - 优先用Tushare真实数据"""
        result = {
            'consecutive_inflow_days': 0,
            'consecutive_outflow_days': 0,
            'trend': 'neutral'
        }

        # E5: 优先读已入库 market_flow_daily，缺时回退 Tushare（均按 net_mf_amount 符号判断）
        df = self._fetch_db_moneyflow(stock_code, days=20)
        if df is None or len(df) < 3:
            df = self._fetch_tushare_moneyflow(stock_code, days=20)
        if df is not None and len(df) >= 3:
            inflow_days = 0
            outflow_days = 0
            # df已按trade_date降序排列, iloc[0]是最新
            for i in range(len(df)):
                net_mf = float(df.iloc[i].get('net_mf_amount', 0) or 0)
                if net_mf > 0:
                    if outflow_days == 0:
                        inflow_days += 1
                    else:
                        break
                elif net_mf < 0:
                    if inflow_days == 0:
                        outflow_days += 1
                    else:
                        break
                else:
                    break
            result['consecutive_inflow_days'] = inflow_days
            result['consecutive_outflow_days'] = outflow_days
            if inflow_days >= 3:
                result['trend'] = 'inflow'
            elif outflow_days >= 3:
                result['trend'] = 'outflow'
            return result

        # 回退: 原有close/volume近似逻辑
        if len(data) < 5:
            return result

        close = data['close'].values
        volume = data['volume'].values

        inflow_days = 0
        outflow_days = 0

        for i in range(1, min(20, len(close))):
            idx = -i
            if close[idx] > close[idx-1] and volume[idx] > volume[idx-1]:
                if outflow_days == 0:
                    inflow_days += 1
                else:
                    break
            elif close[idx] < close[idx-1] and volume[idx] > volume[idx-1]:
                if inflow_days == 0:
                    outflow_days += 1
                else:
                    break
            else:
                break

        result['consecutive_inflow_days'] = inflow_days
        result['consecutive_outflow_days'] = outflow_days

        if inflow_days >= 3:
            result['trend'] = 'inflow'
        elif outflow_days >= 3:
            result['trend'] = 'outflow'

        return result

    def _estimate_retail_ratio(self, order_analysis: Dict) -> float:
        """计算散户资金占比 - 优先用成交额占比(真实数据), 回退用净额占比"""
        # 真实数据: 用成交额(买+卖)占比, 因为净额四类加总恒为0
        main_turnover = order_analysis.get('main_turnover', 0)
        retail_turnover = order_analysis.get('retail_turnover', 0)
        total_turnover = main_turnover + retail_turnover
        if total_turnover > 0:
            return retail_turnover / total_turnover * 100

        # 回退: 合成数据用净额占比
        main_net = abs(order_analysis.get('main_net_inflow', 0))
        retail_net = abs(order_analysis.get('retail_net_inflow', 0))
        total = main_net + retail_net
        if total > 0:
            return retail_net / total * 100
        return 50.0


class PatternDetector:
    """K线形态识别器"""
    
    def detect_all(self, historical_data: pd.DataFrame) -> Dict:
        """
        检测所有K线形态
        
        支持形态：
        - 杯柄形态
        - 头肩底
        - 双底/W底
        - 突破回踩
        - 三角形整理
        - 楔形
        """
        result = {
            'score': 50.0,
            'signals': [],
            'patterns': [],
            'details': {}
        }
        
        if historical_data is None or len(historical_data) < 60:
            return result
        
        try:
            close = historical_data['close'].values
            high = historical_data['high'].values
            low = historical_data['low'].values
            volume = historical_data['volume'].values
            
            cup_handle = self._detect_cup_and_handle(close, volume)
            if cup_handle['detected']:
                result['patterns'].append(cup_handle)
                result['signals'].append(f"🔥 杯柄形态(置信度{cup_handle['confidence']}%)")
            
            head_shoulders = self._detect_head_shoulders_bottom(close, low)
            if head_shoulders['detected']:
                result['patterns'].append(head_shoulders)
                result['signals'].append(f"🔥 头肩底形态(置信度{head_shoulders['confidence']}%)")
            
            double_bottom = self._detect_double_bottom(close, low)
            if double_bottom['detected']:
                result['patterns'].append(double_bottom)
                result['signals'].append(f"🔥 双底/W底形态(置信度{double_bottom['confidence']}%)")
            
            breakout_pullback = self._detect_breakout_pullback(close, high, volume)
            if breakout_pullback['detected']:
                result['patterns'].append(breakout_pullback)
                result['signals'].append(f"突破回踩确认(置信度{breakout_pullback['confidence']}%)")
            
            triangle = self._detect_triangle(close, high, low)
            if triangle['detected']:
                result['patterns'].append(triangle)
                result['signals'].append(f"三角形整理({triangle['type']})")
            
            score = 50.0
            for pattern in result['patterns']:
                confidence = pattern.get('confidence', 50)
                pattern_type = pattern.get('type', '')
                
                if '杯柄' in pattern_type or '头肩底' in pattern_type:
                    score += confidence * 0.3
                elif '双底' in pattern_type or '突破回踩' in pattern_type:
                    score += confidence * 0.25
                else:
                    score += confidence * 0.15
            
            result['score'] = max(0, min(100, score))
            result['details']['pattern_count'] = len(result['patterns'])
            
        except Exception as e:
            logger.error(f"形态识别错误: {e}")
            result['error'] = str(e)
        
        return result
    
    def _detect_cup_and_handle(self, close: np.ndarray, volume: np.ndarray,
                                min_cup_length: int = 30) -> Dict:
        """检测杯柄形态"""
        result = {
            'detected': False,
            'type': '杯柄形态',
            'confidence': 0
        }
        
        if len(close) < min_cup_length + 10:
            return result
        
        cup_data = close[-min_cup_length-10:-10]
        handle_data = close[-10:]
        
        cup_high_idx = np.argmax(cup_data)
        cup_low_idx = np.argmin(cup_data)
        
        if cup_low_idx > cup_high_idx:
            left_rim = cup_data[0]
            right_rim = cup_data[-1]
            cup_bottom = cup_data[cup_low_idx]
            
            rim_diff = abs(left_rim - right_rim) / left_rim
            cup_depth = (left_rim - cup_bottom) / left_rim
            
            if rim_diff < 0.05 and 0.12 <= cup_depth <= 0.35:
                handle_high = np.max(handle_data)
                handle_low = np.min(handle_data)
                handle_depth = (handle_high - handle_low) / handle_high
                
                if handle_depth < cup_depth * 0.5:
                    result['detected'] = True
                    result['confidence'] = int(70 + (0.05 - rim_diff) * 200 + (0.35 - cup_depth) * 50)
                    result['confidence'] = min(95, result['confidence'])
        
        return result
    
    def _detect_head_shoulders_bottom(self, close: np.ndarray, low: np.ndarray) -> Dict:
        """检测头肩底形态"""
        result = {
            'detected': False,
            'type': '头肩底',
            'confidence': 0
        }
        
        if len(low) < 60:
            return result
        
        recent_low = low[-60:]
        
        local_mins = []
        for i in range(5, len(recent_low) - 5):
            if recent_low[i] == np.min(recent_low[i-5:i+6]):
                local_mins.append((i, recent_low[i]))
        
        if len(local_mins) >= 3:
            for i in range(len(local_mins) - 2):
                left_shoulder = local_mins[i]
                head = local_mins[i + 1]
                right_shoulder = local_mins[i + 2]
                
                if head[1] < left_shoulder[1] and head[1] < right_shoulder[1]:
                    shoulder_diff = abs(left_shoulder[1] - right_shoulder[1]) / left_shoulder[1]
                    
                    if shoulder_diff < 0.05:
                        neckline = max(
                            recent_low[left_shoulder[0]:head[0]].max(),
                            recent_low[head[0]:right_shoulder[0]].max()
                        )
                        
                        current_price = close[-1]
                        if current_price > neckline:
                            result['detected'] = True
                            result['confidence'] = int(75 + (0.05 - shoulder_diff) * 400)
                            result['confidence'] = min(95, result['confidence'])
                            result['neckline'] = float(neckline)
                            break
        
        return result
    
    def _detect_double_bottom(self, close: np.ndarray, low: np.ndarray) -> Dict:
        """检测双底形态"""
        result = {
            'detected': False,
            'type': '双底/W底',
            'confidence': 0
        }
        
        if len(low) < 40:
            return result
        
        recent_low = low[-40:]
        
        local_mins = []
        for i in range(3, len(recent_low) - 3):
            if recent_low[i] == np.min(recent_low[i-3:i+4]):
                local_mins.append((i, recent_low[i]))
        
        if len(local_mins) >= 2:
            for i in range(len(local_mins) - 1):
                bottom1 = local_mins[i]
                bottom2 = local_mins[i + 1]
                
                price_diff = abs(bottom1[1] - bottom2[1]) / bottom1[1]
                time_diff = bottom2[0] - bottom1[0]
                
                if price_diff < 0.03 and 10 <= time_diff <= 30:
                    neckline = recent_low[bottom1[0]:bottom2[0]].max()
                    current_price = close[-1]
                    
                    if current_price > neckline:
                        result['detected'] = True
                        result['confidence'] = int(70 + (0.03 - price_diff) * 500)
                        result['confidence'] = min(95, result['confidence'])
                        result['neckline'] = float(neckline)
                        break
        
        return result
    
    def _detect_breakout_pullback(self, close: np.ndarray, high: np.ndarray,
                                   volume: np.ndarray) -> Dict:
        """检测突破回踩形态"""
        result = {
            'detected': False,
            'type': '突破回踩',
            'confidence': 0
        }
        
        if len(close) < 30:
            return result
        
        resistance_20d = np.max(high[-30:-5])
        
        recent_high = np.max(high[-5:])
        if recent_high > resistance_20d * 1.02:
            current_price = close[-1]
            pullback = (recent_high - current_price) / recent_high
            
            if 0.02 <= pullback <= 0.08:
                if current_price >= resistance_20d * 0.98:
                    avg_vol_before = np.mean(volume[-30:-5])
                    breakout_vol = np.max(volume[-5:])
                    
                    if breakout_vol > avg_vol_before * 1.5:
                        result['detected'] = True
                        result['confidence'] = int(65 + (1 - pullback / 0.08) * 30)
                        result['resistance'] = float(resistance_20d)
        
        return result
    
    def _detect_triangle(self, close: np.ndarray, high: np.ndarray,
                          low: np.ndarray) -> Dict:
        """检测三角形整理形态"""
        result = {
            'detected': False,
            'type': '',
            'confidence': 0
        }
        
        if len(close) < 20:
            return result
        
        recent_high = high[-20:]
        recent_low = low[-20:]
        
        high_slope = (recent_high[-1] - recent_high[0]) / len(recent_high)
        low_slope = (recent_low[-1] - recent_low[0]) / len(recent_low)
        
        range_start = recent_high[0] - recent_low[0]
        range_end = recent_high[-1] - recent_low[-1]
        
        if range_end < range_start * 0.6:
            if high_slope < 0 and low_slope > 0:
                result['detected'] = True
                result['type'] = '对称三角形'
                result['confidence'] = 70
            elif high_slope < 0 and abs(low_slope) < 0.001:
                result['detected'] = True
                result['type'] = '下降三角形'
                result['confidence'] = 65
            elif abs(high_slope) < 0.001 and low_slope > 0:
                result['detected'] = True
                result['type'] = '上升三角形'
                result['confidence'] = 75
        
        return result


class TimeWindowAnalyzer:
    """时间窗口分析器"""
    
    def analyze(self, stock_code: str, fundamental_data: Optional[Dict] = None) -> Dict:
        """
        分析时间敏感窗口
        
        核心分析：
        - 季报/年报披露前后
        - 限售股解禁
        - 分红除权
        - 重要会议/事件
        """
        result = {
            'score': 50.0,
            'signals': [],
            'details': {},
            'warnings': [],
            'opportunities': []
        }
        
        try:
            today = datetime.now()
            
            earnings_window = self._check_earnings_window(today, fundamental_data)
            result['details']['earnings'] = earnings_window
            
            unlock_window = self._check_unlock_window(today, fundamental_data)
            result['details']['unlock'] = unlock_window
            
            dividend_window = self._check_dividend_window(today, fundamental_data)
            result['details']['dividend'] = dividend_window
            
            event_window = self._check_event_window(today)
            result['details']['events'] = event_window
            
            score = 50.0
            
            if earnings_window.get('approaching', False):
                days = earnings_window.get('days_until', 30)
                if days <= 7:
                    score -= 15
                    result['warnings'].append(f'⚠️ 财报发布在即({days}天后),不确定性高')
                elif days <= 15:
                    score -= 5
                    result['signals'].append(f'财报将于{days}天后发布')
            
            if earnings_window.get('just_released', False):
                if earnings_window.get('beat_expectation', False):
                    score += 20
                    result['opportunities'].append('🔥 财报超预期')
                elif earnings_window.get('miss_expectation', False):
                    score -= 20
                    result['warnings'].append('🚨 财报不及预期')
            
            if unlock_window.get('approaching', False):
                days = unlock_window.get('days_until', 30)
                unlock_ratio = unlock_window.get('unlock_ratio', 0)
                
                if days <= 30 and unlock_ratio > 10:
                    score -= 25
                    result['warnings'].append(f'🚨 大额解禁({unlock_ratio:.1f}%)将于{days}天后')
                elif days <= 30 and unlock_ratio > 5:
                    score -= 15
                    result['warnings'].append(f'⚠️ 解禁({unlock_ratio:.1f}%)将于{days}天后')
            
            if dividend_window.get('approaching', False):
                if dividend_window.get('high_dividend', False):
                    score += 10
                    result['opportunities'].append('高股息分红在即')
            
            if event_window.get('major_event', False):
                event_type = event_window.get('event_type', '')
                if '两会' in event_type or '中央经济' in event_type:
                    score += 5
                    result['signals'].append(f'重要会议窗口: {event_type}')
            
            result['score'] = max(0, min(100, score))
            
        except Exception as e:
            logger.error(f"时间窗口分析错误: {e}")
            result['error'] = str(e)
        
        return result
    
    def _check_earnings_window(self, today: datetime, 
                                fundamental_data: Optional[Dict]) -> Dict:
        """检查财报披露窗口"""
        result = {
            'approaching': False,
            'just_released': False,
            'days_until': None,
            'report_type': None
        }
        
        month = today.month
        
        if month in [1, 4, 7, 10]:
            result['approaching'] = True
            if month == 1:
                result['report_type'] = '年报'
            elif month == 4:
                result['report_type'] = '一季报'
            elif month == 7:
                result['report_type'] = '中报'
            else:
                result['report_type'] = '三季报'
            
            result['days_until'] = 30 - today.day if today.day < 30 else 0
        
        if fundamental_data:
            last_report_date = fundamental_data.get('last_report_date')
            if last_report_date:
                try:
                    report_date = datetime.strptime(last_report_date, '%Y-%m-%d')
                    if (today - report_date).days <= 7:
                        result['just_released'] = True
                        result['beat_expectation'] = fundamental_data.get('beat_expectation', False)
                        result['miss_expectation'] = fundamental_data.get('miss_expectation', False)
                except:
                    pass
        
        return result
    
    def _check_unlock_window(self, today: datetime,
                              fundamental_data: Optional[Dict]) -> Dict:
        """检查限售股解禁窗口"""
        result = {
            'approaching': False,
            'days_until': None,
            'unlock_ratio': 0,
            'unlock_amount': 0
        }
        
        if fundamental_data:
            unlock_date = fundamental_data.get('next_unlock_date')
            if unlock_date:
                try:
                    unlock_dt = datetime.strptime(unlock_date, '%Y-%m-%d')
                    days_until = (unlock_dt - today).days
                    
                    if 0 < days_until <= 60:
                        result['approaching'] = True
                        result['days_until'] = days_until
                        result['unlock_ratio'] = fundamental_data.get('unlock_ratio', 0)
                        result['unlock_amount'] = fundamental_data.get('unlock_amount', 0)
                except:
                    pass
        
        return result
    
    def _check_dividend_window(self, today: datetime,
                                fundamental_data: Optional[Dict]) -> Dict:
        """检查分红除权窗口"""
        result = {
            'approaching': False,
            'ex_dividend_date': None,
            'dividend_yield': 0,
            'high_dividend': False
        }
        
        if fundamental_data:
            ex_date = fundamental_data.get('ex_dividend_date')
            if ex_date:
                try:
                    ex_dt = datetime.strptime(ex_date, '%Y-%m-%d')
                    days_until = (ex_dt - today).days
                    
                    if 0 < days_until <= 30:
                        result['approaching'] = True
                        result['ex_dividend_date'] = ex_date
                        result['dividend_yield'] = fundamental_data.get('dividend_yield', 0)
                        
                        if result['dividend_yield'] > 3:
                            result['high_dividend'] = True
                except:
                    pass
        
        return result
    
    def _check_event_window(self, today: datetime) -> Dict:
        """检查重要事件窗口"""
        result = {
            'major_event': False,
            'event_type': None
        }
        
        month = today.month
        day = today.day
        
        if month == 3 and day <= 15:
            result['major_event'] = True
            result['event_type'] = '两会'
        
        if month == 12 and day >= 10:
            result['major_event'] = True
            result['event_type'] = '中央经济工作会议'
        
        if month == 10 and 1 <= day <= 7:
            result['major_event'] = True
            result['event_type'] = '国庆假期'
        
        if month == 1 or month == 2:
            if (month == 1 and day >= 20) or (month == 2 and day <= 10):
                result['major_event'] = True
                result['event_type'] = '春节假期'
        
        return result
