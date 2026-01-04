#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
论坛重大利好挖掘系统 v1.0
==========================

核心功能：
1. 从股票论坛中挖掘早期利好信号
2. 监测异常情绪变化和讨论热点
3. 识别关键词频繁出现的股票
4. 提前发现投资机会

论坛数据源：
- 东方财富股吧
- 同花顺股民学校
- 雪球讨论区
- 新浪股吧

监测指标：
1. 情绪突然转正面
2. 讨论量急剧增加
3. 关键利好词汇频率
4. 用户活跃度变化
5. 内幕消息传言
6. 机构观点转向

利好关键词：
- 重组、并购、收购
- 大订单、大合同
- 政策利好、扶持
- 技术突破、专利
- 业绩大增、超预期
- 战略合作、联盟
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import re
import logging
from collections import Counter, defaultdict
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.investor_sentiment import InvestorSentimentAnalyzer
from analysis.dynamic_crawler import DynamicCrawler
from scripts.hot_stocks_fetcher import HotStocksFetcher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ForumPositiveMiner:
    """论坛重大利好挖掘器"""

    # 重大利好关键词库（按重要性分级）
    MAJOR_POSITIVE_KEYWORDS = {
        'reorganization': {
            'keywords': ['重组', '并购', '收购', '资产重组', '重大重组', '整体上市', '借壳', '置入资产', '重组预期', 
                        '停牌重组', '筹划重组', '重组复牌', '重组获批', '重组草案', '重组方案', '注入资产'],
            'weight': 10,  # 最高权重
            'threshold': 3  # 出现3次以上触发
        },
        'major_contracts': {
            'keywords': ['大订单', '大合同', '签约', '中标', '百亿订单', '千万合同', '重大合同', '框架协议',
                        '战略订单', '长期合同', '供货协议', '采购协议', '销售合同', '工程合同', '建设合同'],
            'weight': 8,
            'threshold': 3
        },
        'policy_support': {
            'keywords': ['政策利好', '政策扶持', '纳入名单', '国家重点', '产业政策', '税收优惠', '财政补贴',
                        '政府支持', '列入规划', '政策倾斜', '扶持资金', '专项资金', '示范项目', '试点企业'],
            'weight': 7,
            'threshold': 2
        },
        'tech_breakthrough': {
            'keywords': ['技术突破', '专利', '核心技术', '技术领先', '研发成功', '技术创新', '科技成果',
                        '技术认证', '标准制定', '技术壁垒', '独家技术', '领先技术', '专利授权', '技术转让'],
            'weight': 6,
            'threshold': 2
        },
        'performance_surge': {
            'keywords': ['业绩大增', '利润暴增', '营收翻倍', '超预期', '业绩预增', '净利润增长', '业绩向好',
                        '盈利大增', '业绩修正', '业绩上调', '利润预告', '业绩靓丽', '业绩爆发', '业绩反转'],
            'weight': 6,
            'threshold': 2
        },
        'strategic_cooperation': {
            'keywords': ['战略合作', '深度合作', '全面合作', '战略联盟', '合作框架', '合资公司', '股权合作',
                        '产业合作', '技术合作', '业务合作', '平台合作', '生态合作', '战略投资', '战略入股'],
            'weight': 5,
            'threshold': 2
        },
        'insider_signals': {
            'keywords': ['内部消息', '小道消息', '听说', '据说', '传闻', '爆料', '消息人士', '知情人',
                        '内部人士', '可靠消息', '独家消息', '第一手消息', '打听到', '听到风声', '小道'],
            'weight': 4,
            'threshold': 1
        },
        'market_sentiment': {
            'keywords': ['主力', '机构', '庄家', '大资金', '北向资金', '外资', '机构调研', '主力建仓',
                        '资金流入', '大单买入', '放量', '突破', '起飞', '爆发', '拉升', '冲高'],
            'weight': 3,
            'threshold': 2
        }
    }

    # 情绪变化阈值
    SENTIMENT_THRESHOLDS = {
        'strong_positive': 0.7,     # 强烈看多
        'positive': 0.6,            # 看多
        'slight_positive': 0.55,    # 轻微看多
        'neutral': 0.5,             # 中性
        'volume_surge': 2.0         # 讨论量暴增（相对平均值的倍数）
    }

    def __init__(self):
        """初始化论坛利好挖掘器"""
        self.hot_fetcher = HotStocksFetcher()
        self.crawlers = {}  # 缓存爬虫实例

    def mine_from_forum_sentiment(self, stock_limit: int = 100, forum_posts_limit: int = 30) -> List[Dict]:
        """
        从论坛情绪中挖掘重大利好信号

        Args:
            stock_limit: 分析股票数量上限
            forum_posts_limit: 每只股票分析的论坛帖子数量

        Returns:
            挖掘结果列表
        """
        logger.info("=" * 70)
        logger.info("🎯 开始从论坛情绪中挖掘重大利好信号")
        logger.info("=" * 70)

        results = []
        processed_count = 0

        try:
            # 1. 获取热门股票列表
            logger.info(f"获取TOP {stock_limit} 热门股票...")
            hot_stocks = self._get_hot_stocks(stock_limit)
            
            if not hot_stocks:
                logger.warning("未能获取热门股票列表")
                return results

            logger.info(f"获得 {len(hot_stocks)} 只热门股票，开始分析论坛情绪...")

            # 2. 多线程并发分析论坛情绪
            with ThreadPoolExecutor(max_workers=5) as executor:
                # 提交任务
                future_to_stock = {
                    executor.submit(
                        self._analyze_stock_forum_sentiment, 
                        stock, 
                        forum_posts_limit
                    ): stock 
                    for stock in hot_stocks[:stock_limit]
                }

                # 收集结果
                for future in as_completed(future_to_stock):
                    stock = future_to_stock[future]
                    processed_count += 1
                    
                    try:
                        result = future.result(timeout=60)  # 60秒超时
                        if result and result.get('is_positive_signal', False):
                            results.append(result)
                            logger.info(f"✓ 发现利好信号: {stock['code']} {stock['name']} "
                                      f"(置信度: {result.get('confidence_score', 0):.1f})")
                        else:
                            logger.debug(f"- 无明显信号: {stock['code']} {stock['name']}")
                            
                    except Exception as e:
                        logger.warning(f"✗ 分析失败: {stock['code']} {stock['name']} - {e}")
                    
                    # 显示进度
                    if processed_count % 10 == 0:
                        logger.info(f"已处理 {processed_count}/{min(len(hot_stocks), stock_limit)} 只股票")

            # 3. 按置信度排序
            results.sort(key=lambda x: x.get('confidence_score', 0), reverse=True)

            logger.info(f"\n🎉 论坛利好挖掘完成!")
            logger.info(f"分析了 {processed_count} 只股票，发现 {len(results)} 个利好信号")

            return results

        except Exception as e:
            logger.error(f"论坛利好挖掘过程出错: {e}")
            import traceback
            traceback.print_exc()
            return results

    def _get_hot_stocks(self, limit: int) -> List[Dict]:
        """获取热门股票列表"""
        try:
            # 尝试多种方式获取热门股票
            stocks = []
            
            # 方法1：龙虎榜数据
            try:
                lhb_data = self.hot_fetcher.get_longhubang_data()
                if lhb_data and len(lhb_data) > 0:
                    for item in lhb_data[:limit//2]:  # 取一半
                        stocks.append({
                            'code': item.get('SECURITY_CODE', ''),
                            'name': item.get('SECURITY_NAME_ABBR', ''),
                            'reason': '龙虎榜',
                            'change_percent': item.get('CHANGE_RATE', 0)
                        })
                    logger.info(f"从龙虎榜获取 {len(stocks)} 只股票")
            except Exception as e:
                logger.warning(f"获取龙虎榜数据失败: {e}")

            # 方法2：涨停板数据
            try:
                zt_data = self.hot_fetcher.get_zhangting_data()
                if zt_data and len(zt_data) > 0:
                    zt_count = 0
                    for item in zt_data[:limit//3]:  # 取一部分
                        code = item.get('SECURITY_CODE', '')
                        if not any(s['code'] == code for s in stocks):  # 避免重复
                            stocks.append({
                                'code': code,
                                'name': item.get('SECURITY_NAME_ABBR', ''),
                                'reason': '涨停板',
                                'change_percent': item.get('CHANGE_RATE', 0)
                            })
                            zt_count += 1
                    logger.info(f"从涨停板获取 {zt_count} 只股票")
            except Exception as e:
                logger.warning(f"获取涨停板数据失败: {e}")

            # 方法3：成交量榜
            try:
                volume_data = self.hot_fetcher.get_volume_rank()
                if volume_data and len(volume_data) > 0:
                    vol_count = 0
                    for item in volume_data[:limit//3]:
                        code = item.get('SECURITY_CODE', '')
                        if not any(s['code'] == code for s in stocks):
                            stocks.append({
                                'code': code,
                                'name': item.get('SECURITY_NAME_ABBR', ''),
                                'reason': '成交量榜',
                                'volume': item.get('VOLUME', 0)
                            })
                            vol_count += 1
                    logger.info(f"从成交量榜获取 {vol_count} 只股票")
            except Exception as e:
                logger.warning(f"获取成交量榜数据失败: {e}")

            # 确保有足够的股票数据
            if len(stocks) < 20:
                # 添加一些常见的活跃股票作为备份
                backup_stocks = [
                    {'code': '000001', 'name': '平安银行', 'reason': '备选'},
                    {'code': '000002', 'name': '万科A', 'reason': '备选'},
                    {'code': '600000', 'name': '浦发银行', 'reason': '备选'},
                    {'code': '600036', 'name': '招商银行', 'reason': '备选'},
                    {'code': '600519', 'name': '贵州茅台', 'reason': '备选'},
                    {'code': '000858', 'name': '五粮液', 'reason': '备选'},
                ]
                for backup in backup_stocks:
                    if len(stocks) >= limit:
                        break
                    if not any(s['code'] == backup['code'] for s in stocks):
                        stocks.append(backup)

            return stocks[:limit]

        except Exception as e:
            logger.error(f"获取热门股票列表失败: {e}")
            return []

    def _analyze_stock_forum_sentiment(self, stock: Dict, posts_limit: int) -> Optional[Dict]:
        """
        分析单只股票的论坛情绪
        
        Args:
            stock: 股票信息字典
            posts_limit: 分析帖子数量限制
            
        Returns:
            分析结果字典或None
        """
        stock_code = stock['code']
        stock_name = stock['name']
        
        try:
            # 获取投资者情绪分析器
            sentiment_analyzer = InvestorSentimentAnalyzer(stock_code)
            
            # 获取股吧情绪数据
            guba_sentiment = sentiment_analyzer.get_guba_sentiment(limit=posts_limit)
            
            if not guba_sentiment or guba_sentiment.get('sentiment_score', 0) == 50:
                return None
            
            # 分析论坛帖子内容
            posts_analysis = self._analyze_forum_posts(stock_code, posts_limit)
            
            # 计算综合信号强度
            signal_strength = self._calculate_signal_strength(guba_sentiment, posts_analysis)
            
            # 判断是否为积极信号
            is_positive = self._is_positive_signal(guba_sentiment, posts_analysis)
            
            if not is_positive:
                return None
                
            # 计算置信度评分
            confidence_score = self._calculate_confidence_score(guba_sentiment, posts_analysis, signal_strength)
            
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'is_positive_signal': is_positive,
                'confidence_score': confidence_score,
                'confidence_rating': self._get_confidence_rating(confidence_score),
                'signal_type': posts_analysis.get('dominant_signal_type', 'unknown'),
                'sentiment_score': guba_sentiment.get('sentiment_score', 50),
                'bullish_ratio': guba_sentiment.get('bullish_ratio', 50),
                'bearish_ratio': guba_sentiment.get('bearish_ratio', 50),
                'discussion_volume': guba_sentiment.get('posts_count', 0),
                'key_keywords': posts_analysis.get('top_keywords', []),
                'signal_details': posts_analysis.get('signal_details', {}),
                'timestamp': datetime.now().isoformat(),
                'data_source': 'forum_sentiment'
            }
            
        except Exception as e:
            logger.debug(f"分析 {stock_code} 论坛情绪失败: {e}")
            return None

    def _analyze_forum_posts(self, stock_code: str, posts_limit: int) -> Dict:
        """
        分析论坛帖子内容，提取关键信号
        
        Args:
            stock_code: 股票代码
            posts_limit: 帖子数量限制
            
        Returns:
            帖子分析结果
        """
        try:
            # 使用动态爬虫获取论坛帖子
            posts = DynamicCrawler.crawl_guba_posts(stock_code, posts_limit)
            
            if not posts:
                return {'top_keywords': [], 'signal_details': {}}
            
            # 合并所有帖子内容
            all_content = ' '.join([
                post.get('title', '') + ' ' + post.get('content', '') 
                for post in posts
            ])
            
            # 分析关键词
            keyword_analysis = self._analyze_keywords_in_content(all_content)
            
            # 分析时间分布（检测是否有集中讨论）
            time_analysis = self._analyze_time_distribution(posts)
            
            # 分析用户活跃度
            user_analysis = self._analyze_user_activity(posts)
            
            return {
                'posts_count': len(posts),
                'top_keywords': keyword_analysis['top_keywords'],
                'signal_details': keyword_analysis['signal_details'],
                'dominant_signal_type': keyword_analysis['dominant_signal_type'],
                'time_concentration': time_analysis['concentration_score'],
                'active_users': user_analysis['active_user_count'],
                'avg_post_quality': user_analysis['avg_quality_score']
            }
            
        except Exception as e:
            logger.debug(f"分析 {stock_code} 论坛帖子失败: {e}")
            return {'top_keywords': [], 'signal_details': {}}

    def _analyze_keywords_in_content(self, content: str) -> Dict:
        """分析内容中的关键词"""
        keyword_counts = defaultdict(int)
        signal_details = defaultdict(list)
        signal_scores = defaultdict(float)
        
        # 清理文本
        content = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', ' ', content)
        content = ' '.join(content.split())  # 标准化空白字符
        
        # 分析每个类别的关键词
        for category, config in self.MAJOR_POSITIVE_KEYWORDS.items():
            category_count = 0
            found_keywords = []
            
            for keyword in config['keywords']:
                count = len(re.findall(keyword, content, re.IGNORECASE))
                if count > 0:
                    keyword_counts[keyword] = count
                    category_count += count
                    found_keywords.append(f"{keyword}({count})")
            
            if category_count >= config['threshold']:
                signal_score = category_count * config['weight']
                signal_scores[category] = signal_score
                signal_details[category] = {
                    'keywords': found_keywords,
                    'count': category_count,
                    'score': signal_score
                }
        
        # 确定主导信号类型
        dominant_signal_type = max(signal_scores, key=signal_scores.get) if signal_scores else 'none'
        
        # 获取TOP关键词
        top_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return {
            'top_keywords': top_keywords,
            'signal_details': dict(signal_details),
            'dominant_signal_type': dominant_signal_type,
            'total_signal_score': sum(signal_scores.values())
        }

    def _analyze_time_distribution(self, posts: List[Dict]) -> Dict:
        """分析帖子时间分布"""
        if not posts:
            return {'concentration_score': 0}
        
        # 简化的时间集中度分析
        now = datetime.now()
        recent_posts = [
            post for post in posts 
            if 'time' in post and self._parse_post_time(post['time']) > now - timedelta(hours=24)
        ]
        
        concentration_score = len(recent_posts) / len(posts) if posts else 0
        
        return {
            'concentration_score': concentration_score,
            'recent_posts_count': len(recent_posts),
            'total_posts_count': len(posts)
        }

    def _analyze_user_activity(self, posts: List[Dict]) -> Dict:
        """分析用户活跃度"""
        if not posts:
            return {'active_user_count': 0, 'avg_quality_score': 0}
        
        users = set()
        quality_scores = []
        
        for post in posts:
            if 'author' in post:
                users.add(post['author'])
            
            # 简单的质量评分（基于内容长度和点赞数）
            content_length = len(post.get('content', ''))
            likes = post.get('likes', 0)
            quality = min(content_length / 100 + likes / 10, 5)  # 最高5分
            quality_scores.append(quality)
        
        return {
            'active_user_count': len(users),
            'avg_quality_score': np.mean(quality_scores) if quality_scores else 0
        }

    def _parse_post_time(self, time_str: str) -> datetime:
        """解析帖子时间字符串"""
        try:
            # 处理各种时间格式
            if '分钟前' in time_str:
                minutes = int(re.search(r'(\d+)', time_str).group(1))
                return datetime.now() - timedelta(minutes=minutes)
            elif '小时前' in time_str:
                hours = int(re.search(r'(\d+)', time_str).group(1))
                return datetime.now() - timedelta(hours=hours)
            elif '天前' in time_str:
                days = int(re.search(r'(\d+)', time_str).group(1))
                return datetime.now() - timedelta(days=days)
            else:
                # 尝试解析具体日期
                return datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        except:
            return datetime.now()

    def _calculate_signal_strength(self, guba_sentiment: Dict, posts_analysis: Dict) -> float:
        """计算信号强度"""
        # 情绪得分权重 40%
        sentiment_score = guba_sentiment.get('sentiment_score', 50)
        sentiment_strength = max(0, (sentiment_score - 50) / 50) * 0.4
        
        # 关键词得分权重 30%
        keyword_strength = min(posts_analysis.get('signal_details', {}).get('total_signal_score', 0) / 100, 1) * 0.3
        
        # 讨论活跃度权重 20%
        posts_count = guba_sentiment.get('posts_count', 0)
        activity_strength = min(posts_count / 50, 1) * 0.2
        
        # 时间集中度权重 10%
        time_concentration = posts_analysis.get('time_concentration', 0) * 0.1
        
        return sentiment_strength + keyword_strength + activity_strength + time_concentration

    def _is_positive_signal(self, guba_sentiment: Dict, posts_analysis: Dict) -> bool:
        """判断是否为积极信号"""
        # 基本条件：情绪得分 > 中性
        sentiment_score = guba_sentiment.get('sentiment_score', 50)
        if sentiment_score <= self.SENTIMENT_THRESHOLDS['neutral'] * 100:
            return False
        
        # 看多比例要明显高于看空比例
        bullish_ratio = guba_sentiment.get('bullish_ratio', 50)
        bearish_ratio = guba_sentiment.get('bearish_ratio', 50)
        if bullish_ratio <= bearish_ratio:
            return False
        
        # 必须有关键词信号
        signal_details = posts_analysis.get('signal_details', {})
        if not signal_details:
            return False
        
        return True

    def _calculate_confidence_score(self, guba_sentiment: Dict, posts_analysis: Dict, signal_strength: float) -> float:
        """计算置信度评分 (0-100)"""
        # 基础评分基于信号强度
        base_score = signal_strength * 60  # 最高60分
        
        # 情绪指标加分
        sentiment_score = guba_sentiment.get('sentiment_score', 50)
        if sentiment_score > 70:
            base_score += 15
        elif sentiment_score > 60:
            base_score += 10
        
        # 讨论量加分
        posts_count = guba_sentiment.get('posts_count', 0)
        if posts_count > 30:
            base_score += 10
        elif posts_count > 20:
            base_score += 5
        
        # 关键词多样性加分
        signal_types = len(posts_analysis.get('signal_details', {}))
        if signal_types >= 3:
            base_score += 10
        elif signal_types >= 2:
            base_score += 5
        
        # 用户活跃度加分
        active_users = posts_analysis.get('active_users', 0)
        if active_users > 10:
            base_score += 5
        
        return min(base_score, 100)  # 最高100分

    def _get_confidence_rating(self, score: float) -> str:
        """根据分数获取置信度等级"""
        if score >= 85:
            return 'S'
        elif score >= 75:
            return 'A+'
        elif score >= 65:
            return 'A'
        elif score >= 50:
            return 'B'
        else:
            return 'C'