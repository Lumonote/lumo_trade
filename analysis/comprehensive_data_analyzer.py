#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全资源站点集成数据分析器 v1.0
===================================

集成所有可能的信息资源站点，进行全面数据分析
包括官方渠道、财经媒体、社交平台、研究机构等

核心功能：
1. 多站点数据源集成
2. 智能数据去重和清洗
3. 跨平台信息验证
4. 综合数据质量评估
5. 实时数据同步
"""

import os
import sys
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import json
import re
from collections import defaultdict, Counter
import hashlib

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from scripts.eastmoney_crawler import EastMoneyCrawler
from scripts.tonghuashun_crawler import TongHuaShunCrawler
from scripts.xueqiu_crawler import XueqiuCrawler
from scripts.browser_manager import BrowserManager
from scripts.anti_crawler_helper import RequestOptimizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ComprehensiveDataAnalyzer:
    """全资源站点集成数据分析器"""

    # 全面资源站点配置
    RESOURCE_SITES = {
        # 官方渠道
        'official': {
            'sse': {
                'name': '上海证券交易所',
                'url': 'http://www.sse.com.cn',
                'data_types': ['公告', '财务报告', '监管信息'],
                'priority': 1,
                'reliability': 0.98
            },
            'szse': {
                'name': '深圳证券交易所',
                'url': 'http://www.szse.cn',
                'data_types': ['公告', '财务报告', '交易数据'],
                'priority': 1,
                'reliability': 0.98
            },
            'csrc': {
                'name': '中国证监会',
                'url': 'http://www.csrc.gov.cn',
                'data_types': ['政策法规', '监管公告', '市场信息'],
                'priority': 1,
                'reliability': 0.99
            }
        },
        
        # 主流财经媒体
        'financial_media': {
            'sina_finance': {
                'name': '新浪财经',
                'url': 'https://finance.sina.com.cn',
                'data_types': ['新闻', '公告', '研报', '股吧'],
                'priority': 2,
                'reliability': 0.85
            },
            'eastmoney': {
                'name': '东方财富',
                'url': 'http://www.eastmoney.com',
                'data_types': ['股吧', '资讯', '数据', '研报'],
                'priority': 2,
                'reliability': 0.88
            },
            '163_money': {
                'name': '网易财经',
                'url': 'http://money.163.com',
                'data_types': ['新闻', '研报', '数据'],
                'priority': 3,
                'reliability': 0.82
            },
            'hexun': {
                'name': '和讯网',
                'url': 'http://www.hexun.com',
                'data_types': ['新闻', '股票', '期货', '基金'],
                'priority': 3,
                'reliability': 0.80
            }
        },
        
        # 专业投资平台
        'investment_platforms': {
            'xueqiu': {
                'name': '雪球',
                'url': 'https://xueqiu.com',
                'data_types': ['用户讨论', '投资观点', '实时行情'],
                'priority': 2,
                'reliability': 0.75
            },
            'tonghuashun': {
                'name': '同花顺',
                'url': 'http://www.10jqka.com.cn',
                'data_types': ['行情数据', '研报', '股吧'],
                'priority': 2,
                'reliability': 0.83
            },
            'taoguba': {
                'name': '淘股吧',
                'url': 'https://www.taoguba.com.cn',
                'data_types': ['用户讨论', '短线观点', '题材挖掘'],
                'priority': 3,
                'reliability': 0.70
            },
            'jrj': {
                'name': '金融界',
                'url': 'http://www.jrj.com.cn',
                'data_types': ['新闻', '股票', '基金', '理财'],
                'priority': 3,
                'reliability': 0.78
            }
        },
        
        # 研究机构
        'research_institutions': {
            'choice': {
                'name': '东方财富Choice',
                'url': 'http://choice.eastmoney.com',
                'data_types': ['专业数据', '研报', '宏观数据'],
                'priority': 1,
                'reliability': 0.95
            },
            'wind': {
                'name': '万得资讯',
                'url': 'https://www.wind.com.cn',
                'data_types': ['金融数据', '研究报告', '指数数据'],
                'priority': 1,
                'reliability': 0.96
            },
            'ifind': {
                'name': '同花顺iFind',
                'url': 'http://www.51ifind.com',
                'data_types': ['金融终端', '研报', '数据'],
                'priority': 2,
                'reliability': 0.90
            }
        },
        
        # 社交媒体平台
        'social_media': {
            'weibo': {
                'name': '微博',
                'url': 'https://weibo.com',
                'data_types': ['热点话题', '用户讨论', '舆情'],
                'priority': 4,
                'reliability': 0.60
            },
            'zhihu': {
                'name': '知乎',
                'url': 'https://www.zhihu.com',
                'data_types': ['专业讨论', '投资观点', '行业分析'],
                'priority': 3,
                'reliability': 0.72
            },
            'toutiao': {
                'name': '今日头条',
                'url': 'https://www.toutiao.com',
                'data_types': ['财经新闻', '热点资讯'],
                'priority': 4,
                'reliability': 0.65
            }
        },
        
        # 国际数据源
        'international': {
            'bloomberg': {
                'name': 'Bloomberg',
                'url': 'https://www.bloomberg.com',
                'data_types': ['国际财经', '市场数据', '分析报告'],
                'priority': 2,
                'reliability': 0.92
            },
            'reuters': {
                'name': 'Reuters',
                'url': 'https://www.reuters.com',
                'data_types': ['国际新闻', '市场分析'],
                'priority': 2,
                'reliability': 0.90
            },
            'yahoo_finance': {
                'name': 'Yahoo Finance',
                'url': 'https://finance.yahoo.com',
                'data_types': ['全球行情', '财务数据'],
                'priority': 3,
                'reliability': 0.85
            }
        },
        
        # 政府和监管机构
        'government': {
            'ndrc': {
                'name': '国家发改委',
                'url': 'https://www.ndrc.gov.cn',
                'data_types': ['政策法规', '发展规划', '项目审批'],
                'priority': 1,
                'reliability': 0.99
            },
            'mof': {
                'name': '财政部',
                'url': 'http://www.mof.gov.cn',
                'data_types': ['财税政策', '预算信息', '债券信息'],
                'priority': 1,
                'reliability': 0.99
            },
            'pboc': {
                'name': '中国人民银行',
                'url': 'http://www.pbc.gov.cn',
                'data_types': ['货币政策', '利率数据', '金融统计'],
                'priority': 1,
                'reliability': 0.99
            }
        },
        
        # 行业组织和协会
        'industry_associations': {
            'sac': {
                'name': '中国证券业协会',
                'url': 'http://www.sac.net.cn',
                'data_types': ['行业信息', '自律管理', '培训信息'],
                'priority': 2,
                'reliability': 0.90
            },
            'amac': {
                'name': '中国证券投资基金业协会',
                'url': 'http://www.amac.org.cn',
                'data_types': ['基金信息', '私募数据', '行业统计'],
                'priority': 2,
                'reliability': 0.92
            }
        }
    }

    # 数据类型权重配置
    DATA_TYPE_WEIGHTS = {
        '公告': 0.25,
        '财务报告': 0.20,
        '新闻': 0.15,
        '研报': 0.15,
        '用户讨论': 0.10,
        '政策法规': 0.08,
        '行情数据': 0.07
    }

    def __init__(self, output_dir: str = "comprehensive_analysis_results"):
        """初始化全资源站点集成数据分析器"""
        
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        # 初始化各种爬虫
        self.crawlers = {
            'eastmoney': EastMoneyCrawler(),
            'tonghuashun': TongHuaShunCrawler(),
            'xueqiu': XueqiuCrawler()
        }
        
        # 初始化浏览器管理器
        self.browser_manager = BrowserManager()
        self.request_optimizer = RequestOptimizer()
        
        # 数据去重和质量控制
        self.data_cache = {}
        self.content_hashes = set()
        self.quality_scores = {}
        
        # 执行统计
        self.execution_stats = {
            'total_sites_accessed': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'duplicate_content': 0,
            'unique_content': 0
        }
        
        logger.info("✓ 全资源站点集成数据分析器已初始化")

    def analyze_comprehensive_data(
        self,
        stock_code: str,
        analysis_type: str = 'all',
        time_range: int = 7,
        quality_threshold: float = 0.7
    ) -> Dict:
        """执行全面数据分析"""
        
        start_time = time.time()
        
        logger.info("=" * 80)
        logger.info("🌐 开始全资源站点集成数据分析")
        logger.info(f"📊 目标股票: {stock_code}")
        logger.info(f"🔍 分析类型: {analysis_type}")
        logger.info(f"📅 时间范围: {time_range}天")
        logger.info(f"⚡ 质量阈值: {quality_threshold}")
        logger.info("=" * 80)
        
        # 阶段1: 多站点数据收集
        logger.info("\n🔍 阶段1: 多站点数据收集")
        collected_data = self._collect_multi_site_data(stock_code, analysis_type, time_range)
        
        # 阶段2: 数据清洗和去重
        logger.info("\n🧹 阶段2: 数据清洗和去重")
        cleaned_data = self._clean_and_deduplicate_data(collected_data)
        
        # 阶段3: 跨平台信息验证
        logger.info("\n🔗 阶段3: 跨平台信息验证")
        verified_data = self._cross_platform_verification(cleaned_data, stock_code)
        
        # 阶段4: 质量评估和筛选
        logger.info("\n📊 阶段4: 质量评估和筛选")
        quality_filtered_data = self._quality_assessment_filtering(verified_data, quality_threshold)
        
        # 阶段5: 综合分析和整合
        logger.info("\n🎯 阶段5: 综合分析和整合")
        analysis_result = self._comprehensive_analysis_integration(quality_filtered_data, stock_code)
        
        # 阶段6: 结果输出和报告生成
        logger.info("\n📋 阶段6: 结果输出和报告生成")
        final_result = self._generate_comprehensive_report(analysis_result, stock_code)
        
        # 执行统计
        execution_time = time.time() - start_time
        final_result['execution_stats'] = {
            **self.execution_stats,
            'total_execution_time': execution_time,
            'analysis_efficiency': self.execution_stats['successful_requests'] / max(1, self.execution_stats['total_sites_accessed'])
        }
        
        logger.info("=" * 80)
        logger.info("🎯 全资源站点集成数据分析完成")
        logger.info(f"📊 访问站点数: {self.execution_stats['total_sites_accessed']}")
        logger.info(f"✅ 成功请求: {self.execution_stats['successful_requests']}")
        logger.info(f"💎 唯一内容: {self.execution_stats['unique_content']}")
        logger.info(f"⏱️  总耗时: {execution_time:.1f}秒")
        logger.info("=" * 80)
        
        return final_result

    def _collect_multi_site_data(self, stock_code: str, analysis_type: str, time_range: int) -> Dict:
        """收集多站点数据"""
        
        collected_data = {
            'official_data': [],
            'media_data': [],
            'social_data': [],
            'research_data': [],
            'international_data': [],
            'government_data': []
        }
        
        # 根据分析类型确定要访问的站点类别
        if analysis_type == 'all':
            site_categories = list(self.RESOURCE_SITES.keys())
        else:
            site_categories = [analysis_type] if analysis_type in self.RESOURCE_SITES else ['financial_media']
        
        # 并行收集各类站点数据
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = []
            
            for category in site_categories:
                future = executor.submit(self._collect_category_data, category, stock_code, time_range)
                futures.append((category, future))
            
            for category, future in futures:
                try:
                    category_data = future.result(timeout=120)  # 2分钟超时
                    collected_data[f'{category}_data'] = category_data
                    logger.info(f"  ✓ {category} 数据收集完成: {len(category_data)} 条")
                except Exception as e:
                    logger.error(f"  ❌ {category} 数据收集失败: {e}")
                    collected_data[f'{category}_data'] = []
        
        return collected_data

    def _collect_category_data(self, category: str, stock_code: str, time_range: int) -> List[Dict]:
        """收集特定类别的数据"""
        
        category_data = []
        sites = self.RESOURCE_SITES.get(category, {})
        
        for site_key, site_config in sites.items():
            try:
                self.execution_stats['total_sites_accessed'] += 1
                
                # 根据站点类型选择合适的数据收集方法
                if site_key == 'eastmoney':
                    site_data = self._collect_eastmoney_data(stock_code, time_range)
                elif site_key == 'xueqiu':
                    site_data = self._collect_xueqiu_data(stock_code, time_range)
                elif site_key == 'tonghuashun':
                    site_data = self._collect_tonghuashun_data(stock_code, time_range)
                else:
                    site_data = self._collect_general_site_data(site_config, stock_code, time_range)
                
                # 为数据添加来源信息
                for data_item in site_data:
                    data_item.update({
                        'source_site': site_key,
                        'source_category': category,
                        'site_reliability': site_config['reliability'],
                        'site_priority': site_config['priority'],
                        'collection_time': datetime.now().isoformat()
                    })
                
                category_data.extend(site_data)
                self.execution_stats['successful_requests'] += 1
                
                # 请求间隔
                time.sleep(random.uniform(1, 3))
                
            except Exception as e:
                logger.warning(f"    ⚠️  {site_key} 数据收集异常: {e}")
                self.execution_stats['failed_requests'] += 1
        
        return category_data

    def _collect_eastmoney_data(self, stock_code: str, time_range: int) -> List[Dict]:
        """收集东方财富数据"""
        data_list = []
        
        try:
            # 使用现有的东方财富爬虫
            crawler = self.crawlers['eastmoney']
            
            # 收集股吧讨论
            forum_data = self._safe_execute(
                lambda: crawler.get_stock_forum_discussions(stock_code, days=time_range)
            )
            if forum_data:
                for item in forum_data:
                    data_list.append({
                        'type': 'forum_discussion',
                        'title': item.get('title', ''),
                        'content': item.get('content', ''),
                        'author': item.get('author', ''),
                        'publish_time': item.get('time', ''),
                        'views': item.get('views', 0),
                        'replies': item.get('replies', 0),
                        'url': item.get('url', '')
                    })
            
            # 收集资讯新闻
            news_data = self._safe_execute(
                lambda: crawler.get_stock_news(stock_code, days=time_range)
            )
            if news_data:
                for item in news_data:
                    data_list.append({
                        'type': 'news',
                        'title': item.get('title', ''),
                        'content': item.get('summary', ''),
                        'publish_time': item.get('time', ''),
                        'source': item.get('source', ''),
                        'url': item.get('url', '')
                    })
                    
        except Exception as e:
            logger.error(f"东方财富数据收集错误: {e}")
        
        return data_list

    def _collect_xueqiu_data(self, stock_code: str, time_range: int) -> List[Dict]:
        """收集雪球数据"""
        data_list = []
        
        try:
            crawler = self.crawlers['xueqiu']
            
            # 收集用户讨论
            discussions = self._safe_execute(
                lambda: crawler.get_stock_discussions(stock_code, days=time_range)
            )
            if discussions:
                for item in discussions:
                    data_list.append({
                        'type': 'user_discussion',
                        'title': item.get('title', ''),
                        'content': item.get('text', ''),
                        'author': item.get('user_name', ''),
                        'publish_time': item.get('created_at', ''),
                        'likes': item.get('like_count', 0),
                        'comments': item.get('reply_count', 0),
                        'url': item.get('target', '')
                    })
                    
        except Exception as e:
            logger.error(f"雪球数据收集错误: {e}")
        
        return data_list

    def _collect_tonghuashun_data(self, stock_code: str, time_range: int) -> List[Dict]:
        """收集同花顺数据"""
        data_list = []
        
        try:
            crawler = self.crawlers['tonghuashun']
            
            # 收集研报信息
            reports = self._safe_execute(
                lambda: crawler.get_research_reports(stock_code, days=time_range)
            )
            if reports:
                for item in reports:
                    data_list.append({
                        'type': 'research_report',
                        'title': item.get('title', ''),
                        'content': item.get('summary', ''),
                        'institution': item.get('institution', ''),
                        'analyst': item.get('analyst', ''),
                        'publish_time': item.get('publish_date', ''),
                        'rating': item.get('rating', ''),
                        'url': item.get('url', '')
                    })
                    
        except Exception as e:
            logger.error(f"同花顺数据收集错误: {e}")
        
        return data_list

    def _collect_general_site_data(self, site_config: Dict, stock_code: str, time_range: int) -> List[Dict]:
        """收集通用站点数据"""
        data_list = []
        
        try:
            # 这里可以实现通用的网站数据收集逻辑
            # 基于站点配置进行数据抓取
            base_url = site_config['url']
            data_types = site_config['data_types']
            
            # 构建搜索URL（这里需要根据具体站点的URL结构调整）
            search_keywords = [stock_code, f"{stock_code[:6]}"]
            
            for keyword in search_keywords:
                # 模拟数据收集过程
                # 实际实现需要根据每个站点的具体API和页面结构
                pass
                
        except Exception as e:
            logger.error(f"通用站点 {site_config['name']} 数据收集错误: {e}")
        
        return data_list

    def _safe_execute(self, func, default=None):
        """安全执行函数"""
        try:
            return func()
        except Exception as e:
            logger.warning(f"函数执行异常: {e}")
            return default

    def _clean_and_deduplicate_data(self, collected_data: Dict) -> Dict:
        """数据清洗和去重"""
        
        cleaned_data = {}
        
        for category, data_list in collected_data.items():
            cleaned_category_data = []
            
            for data_item in data_list:
                # 内容去重
                content_hash = self._generate_content_hash(data_item)
                if content_hash in self.content_hashes:
                    self.execution_stats['duplicate_content'] += 1
                    continue
                
                self.content_hashes.add(content_hash)
                self.execution_stats['unique_content'] += 1
                
                # 数据清洗
                cleaned_item = self._clean_data_item(data_item)
                if cleaned_item:
                    cleaned_category_data.append(cleaned_item)
            
            cleaned_data[category] = cleaned_category_data
        
        return cleaned_data

    def _generate_content_hash(self, data_item: Dict) -> str:
        """生成内容哈希用于去重"""
        # 使用标题和内容的组合生成哈希
        title = data_item.get('title', '')
        content = data_item.get('content', '')
        combined_content = f"{title}:{content}"
        
        return hashlib.md5(combined_content.encode('utf-8')).hexdigest()

    def _clean_data_item(self, data_item: Dict) -> Optional[Dict]:
        """清洗单个数据项"""
        
        # 基础数据验证
        if not data_item.get('title') and not data_item.get('content'):
            return None
        
        # 文本清理
        title = self._clean_text(data_item.get('title', ''))
        content = self._clean_text(data_item.get('content', ''))
        
        # 长度验证
        if len(title) < 5 and len(content) < 10:
            return None
        
        # 构建清洗后的数据项
        cleaned_item = {
            'title': title,
            'content': content,
            'type': data_item.get('type', 'unknown'),
            'publish_time': self._parse_time(data_item.get('publish_time', '')),
            'source_site': data_item.get('source_site', ''),
            'source_category': data_item.get('source_category', ''),
            'site_reliability': data_item.get('site_reliability', 0.5),
            'url': data_item.get('url', ''),
            'metadata': {
                'author': data_item.get('author', ''),
                'views': data_item.get('views', 0),
                'likes': data_item.get('likes', 0),
                'replies': data_item.get('replies', 0)
            }
        }
        
        return cleaned_item

    def _clean_text(self, text: str) -> str:
        """清理文本内容"""
        if not text:
            return ""
        
        # 移除HTML标签
        text = re.sub(r'<[^>]+>', '', text)
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text)
        # 移除特殊字符
        text = re.sub(r'[^\w\s\u4e00-\u9fff.,!?;:()""''《》【】]', '', text)
        
        return text.strip()

    def _parse_time(self, time_str: str) -> str:
        """解析时间字符串"""
        if not time_str:
            return ""
        
        # 这里可以实现更复杂的时间解析逻辑
        try:
            # 尝试解析常见时间格式
            return time_str
        except:
            return time_str

    def _cross_platform_verification(self, cleaned_data: Dict, stock_code: str) -> Dict:
        """跨平台信息验证"""
        
        verified_data = {}
        
        # 收集所有数据项进行交叉验证
        all_data_items = []
        for category, data_list in cleaned_data.items():
            all_data_items.extend(data_list)
        
        # 按内容相似度分组
        content_groups = self._group_similar_content(all_data_items)
        
        # 验证每个内容组
        for group_id, group_items in content_groups.items():
            verification_score = self._calculate_verification_score(group_items)
            
            # 为每个项目添加验证分数
            for item in group_items:
                item['verification_score'] = verification_score
                item['group_size'] = len(group_items)
                item['cross_platform_verified'] = verification_score > 0.7
        
        # 重新分类验证后的数据
        for category, data_list in cleaned_data.items():
            verified_data[category] = [
                item for item in data_list 
                if item.get('verification_score', 0) > 0.3  # 最低验证阈值
            ]
        
        return verified_data

    def _group_similar_content(self, data_items: List[Dict]) -> Dict[str, List[Dict]]:
        """根据内容相似度分组"""
        
        content_groups = defaultdict(list)
        
        for item in data_items:
            # 生成内容特征
            content_features = self._extract_content_features(item)
            group_key = self._generate_group_key(content_features)
            content_groups[group_key].append(item)
        
        return dict(content_groups)

    def _extract_content_features(self, data_item: Dict) -> Set[str]:
        """提取内容特征"""
        
        title = data_item.get('title', '')
        content = data_item.get('content', '')
        combined_text = f"{title} {content}"
        
        # 提取关键词
        keywords = set()
        
        # 提取4字以上的词
        words = re.findall(r'[\u4e00-\u9fff]{4,}', combined_text)
        keywords.update(words)
        
        # 提取数字模式
        numbers = re.findall(r'\d+\.?\d*', combined_text)
        keywords.update(numbers)
        
        return keywords

    def _generate_group_key(self, features: Set[str]) -> str:
        """生成分组键"""
        # 使用特征的排序组合生成键
        if not features:
            return "empty"
        
        sorted_features = sorted(list(features))
        return hashlib.md5('|'.join(sorted_features[:5]).encode('utf-8')).hexdigest()[:8]

    def _calculate_verification_score(self, group_items: List[Dict]) -> float:
        """计算验证分数"""
        
        if len(group_items) <= 1:
            return 0.5
        
        # 基础分数：基于组内项目数量
        base_score = min(0.9, 0.3 + 0.1 * len(group_items))
        
        # 来源可靠性权重
        reliability_scores = [item.get('site_reliability', 0.5) for item in group_items]
        avg_reliability = np.mean(reliability_scores)
        
        # 来源多样性权重
        unique_sources = len(set(item.get('source_site', '') for item in group_items))
        diversity_bonus = min(0.3, 0.1 * unique_sources)
        
        # 时间一致性权重
        time_consistency = self._calculate_time_consistency(group_items)
        
        final_score = base_score * avg_reliability + diversity_bonus + time_consistency * 0.1
        
        return min(1.0, final_score)

    def _calculate_time_consistency(self, group_items: List[Dict]) -> float:
        """计算时间一致性"""
        
        # 如果时间信息不足，返回中性分数
        valid_times = [item.get('publish_time', '') for item in group_items if item.get('publish_time')]
        if len(valid_times) < 2:
            return 0.5
        
        # 简单的时间一致性检查
        # 这里可以实现更复杂的时间分析逻辑
        return 0.7

    def _quality_assessment_filtering(self, verified_data: Dict, quality_threshold: float) -> Dict:
        """质量评估和筛选"""
        
        quality_filtered_data = {}
        
        for category, data_list in verified_data.items():
            high_quality_items = []
            
            for item in data_list:
                quality_score = self._calculate_quality_score(item)
                item['quality_score'] = quality_score
                
                if quality_score >= quality_threshold:
                    high_quality_items.append(item)
            
            quality_filtered_data[category] = high_quality_items
            
            logger.info(f"  📊 {category}: {len(high_quality_items)}/{len(data_list)} 通过质量筛选")
        
        return quality_filtered_data

    def _calculate_quality_score(self, data_item: Dict) -> float:
        """计算数据质量分数"""
        
        score = 0.0
        
        # 内容长度权重 (20%)
        title_len = len(data_item.get('title', ''))
        content_len = len(data_item.get('content', ''))
        length_score = min(1.0, (title_len + content_len) / 200)
        score += length_score * 0.2
        
        # 来源可靠性权重 (30%)
        reliability = data_item.get('site_reliability', 0.5)
        score += reliability * 0.3
        
        # 验证分数权重 (25%)
        verification = data_item.get('verification_score', 0.5)
        score += verification * 0.25
        
        # 时效性权重 (15%)
        timeliness = self._calculate_timeliness(data_item.get('publish_time', ''))
        score += timeliness * 0.15
        
        # 互动性权重 (10%)
        interaction_score = self._calculate_interaction_score(data_item.get('metadata', {}))
        score += interaction_score * 0.1
        
        return min(1.0, score)

    def _calculate_timeliness(self, publish_time: str) -> float:
        """计算时效性分数"""
        
        if not publish_time:
            return 0.5
        
        # 简单的时效性计算，1天内=1.0分，逐渐递减
        try:
            # 这里需要根据实际时间格式实现
            return 0.8  # 默认分数
        except:
            return 0.5

    def _calculate_interaction_score(self, metadata: Dict) -> float:
        """计算互动性分数"""
        
        views = metadata.get('views', 0)
        likes = metadata.get('likes', 0)
        replies = metadata.get('replies', 0)
        
        # 基于互动数据计算分数
        interaction_total = views + likes * 5 + replies * 10
        
        if interaction_total == 0:
            return 0.3
        elif interaction_total < 100:
            return 0.5
        elif interaction_total < 1000:
            return 0.7
        else:
            return 1.0

    def _comprehensive_analysis_integration(self, quality_filtered_data: Dict, stock_code: str) -> Dict:
        """综合分析和整合"""
        
        analysis_result = {
            'stock_code': stock_code,
            'analysis_time': datetime.now().isoformat(),
            'data_summary': {},
            'key_findings': [],
            'sentiment_analysis': {},
            'risk_factors': [],
            'opportunities': [],
            'recommendation': {}
        }
        
        # 数据统计摘要
        total_items = 0
        for category, data_list in quality_filtered_data.items():
            total_items += len(data_list)
            analysis_result['data_summary'][category] = {
                'count': len(data_list),
                'avg_quality': np.mean([item.get('quality_score', 0) for item in data_list]) if data_list else 0
            }
        
        analysis_result['data_summary']['total_items'] = total_items
        
        # 关键发现提取
        analysis_result['key_findings'] = self._extract_key_findings(quality_filtered_data)
        
        # 情绪分析
        analysis_result['sentiment_analysis'] = self._perform_sentiment_analysis(quality_filtered_data)
        
        # 风险因素识别
        analysis_result['risk_factors'] = self._identify_risk_factors(quality_filtered_data)
        
        # 机会识别
        analysis_result['opportunities'] = self._identify_opportunities(quality_filtered_data)
        
        # 综合推荐
        analysis_result['recommendation'] = self._generate_comprehensive_recommendation(analysis_result)
        
        return analysis_result

    def _extract_key_findings(self, data: Dict) -> List[Dict]:
        """提取关键发现"""
        
        key_findings = []
        
        # 分析高质量内容
        all_items = []
        for category, data_list in data.items():
            all_items.extend(data_list)
        
        # 按质量分数排序
        sorted_items = sorted(all_items, key=lambda x: x.get('quality_score', 0), reverse=True)
        
        # 提取前10个高质量发现
        for item in sorted_items[:10]:
            finding = {
                'title': item.get('title', ''),
                'content_summary': item.get('content', '')[:200] + '...' if len(item.get('content', '')) > 200 else item.get('content', ''),
                'source': item.get('source_site', ''),
                'quality_score': item.get('quality_score', 0),
                'verification_score': item.get('verification_score', 0),
                'publish_time': item.get('publish_time', ''),
                'type': item.get('type', '')
            }
            key_findings.append(finding)
        
        return key_findings

    def _perform_sentiment_analysis(self, data: Dict) -> Dict:
        """执行情绪分析"""
        
        sentiment_result = {
            'overall_sentiment': 'neutral',
            'positive_ratio': 0.0,
            'negative_ratio': 0.0,
            'neutral_ratio': 0.0,
            'sentiment_distribution': {},
            'key_positive_points': [],
            'key_negative_points': []
        }
        
        # 简单的情绪分析实现
        positive_keywords = ['利好', '上涨', '买入', '推荐', '突破', '机会', '增长']
        negative_keywords = ['利空', '下跌', '卖出', '风险', '下调', '亏损', '减持']
        
        all_items = []
        for category, data_list in data.items():
            all_items.extend(data_list)
        
        positive_count = 0
        negative_count = 0
        neutral_count = 0
        
        for item in all_items:
            content = f"{item.get('title', '')} {item.get('content', '')}"
            
            positive_score = sum(1 for keyword in positive_keywords if keyword in content)
            negative_score = sum(1 for keyword in negative_keywords if keyword in content)
            
            if positive_score > negative_score:
                positive_count += 1
                if positive_score >= 2:  # 强烈正面
                    sentiment_result['key_positive_points'].append({
                        'title': item.get('title', ''),
                        'source': item.get('source_site', ''),
                        'score': positive_score
                    })
            elif negative_score > positive_score:
                negative_count += 1
                if negative_score >= 2:  # 强烈负面
                    sentiment_result['key_negative_points'].append({
                        'title': item.get('title', ''),
                        'source': item.get('source_site', ''),
                        'score': negative_score
                    })
            else:
                neutral_count += 1
        
        total_count = positive_count + negative_count + neutral_count
        if total_count > 0:
            sentiment_result['positive_ratio'] = positive_count / total_count
            sentiment_result['negative_ratio'] = negative_count / total_count
            sentiment_result['neutral_ratio'] = neutral_count / total_count
            
            # 确定整体情绪
            if sentiment_result['positive_ratio'] > 0.6:
                sentiment_result['overall_sentiment'] = 'positive'
            elif sentiment_result['negative_ratio'] > 0.6:
                sentiment_result['overall_sentiment'] = 'negative'
            else:
                sentiment_result['overall_sentiment'] = 'neutral'
        
        return sentiment_result

    def _identify_risk_factors(self, data: Dict) -> List[Dict]:
        """识别风险因素"""
        
        risk_factors = []
        risk_keywords = ['风险', '下跌', '亏损', '违规', '处罚', '停牌', '退市', '债务', '诉讼']
        
        all_items = []
        for category, data_list in data.items():
            all_items.extend(data_list)
        
        for item in all_items:
            content = f"{item.get('title', '')} {item.get('content', '')}"
            
            # 检查是否包含风险关键词
            risk_score = sum(1 for keyword in risk_keywords if keyword in content)
            
            if risk_score >= 2:  # 包含多个风险关键词
                risk_factor = {
                    'title': item.get('title', ''),
                    'description': item.get('content', '')[:200] + '...' if len(item.get('content', '')) > 200 else item.get('content', ''),
                    'source': item.get('source_site', ''),
                    'risk_level': 'high' if risk_score >= 4 else 'medium',
                    'publish_time': item.get('publish_time', ''),
                    'quality_score': item.get('quality_score', 0)
                }
                risk_factors.append(risk_factor)
        
        # 按风险等级和质量分数排序
        risk_factors.sort(key=lambda x: (x['risk_level'] == 'high', x['quality_score']), reverse=True)
        
        return risk_factors[:5]  # 返回前5个主要风险因素

    def _identify_opportunities(self, data: Dict) -> List[Dict]:
        """识别投资机会"""
        
        opportunities = []
        opportunity_keywords = ['重组', '并购', '利好', '突破', '增长', '合作', '订单', '政策', '技术', '创新']
        
        all_items = []
        for category, data_list in data.items():
            all_items.extend(data_list)
        
        for item in all_items:
            content = f"{item.get('title', '')} {item.get('content', '')}"
            
            # 检查是否包含机会关键词
            opportunity_score = sum(1 for keyword in opportunity_keywords if keyword in content)
            
            if opportunity_score >= 2:  # 包含多个机会关键词
                opportunity = {
                    'title': item.get('title', ''),
                    'description': item.get('content', '')[:200] + '...' if len(item.get('content', '')) > 200 else item.get('content', ''),
                    'source': item.get('source_site', ''),
                    'opportunity_level': 'high' if opportunity_score >= 4 else 'medium',
                    'publish_time': item.get('publish_time', ''),
                    'quality_score': item.get('quality_score', 0),
                    'verification_score': item.get('verification_score', 0)
                }
                opportunities.append(opportunity)
        
        # 按机会等级和质量分数排序
        opportunities.sort(key=lambda x: (x['opportunity_level'] == 'high', x['quality_score']), reverse=True)
        
        return opportunities[:5]  # 返回前5个主要投资机会

    def _generate_comprehensive_recommendation(self, analysis_result: Dict) -> Dict:
        """生成综合推荐"""
        
        sentiment = analysis_result['sentiment_analysis']
        risk_factors = analysis_result['risk_factors']
        opportunities = analysis_result['opportunities']
        
        # 基础评分计算
        sentiment_score = 0
        if sentiment['overall_sentiment'] == 'positive':
            sentiment_score = sentiment['positive_ratio'] * 100
        elif sentiment['overall_sentiment'] == 'negative':
            sentiment_score = (1 - sentiment['negative_ratio']) * 100
        else:
            sentiment_score = 50
        
        # 机会评分
        opportunity_score = len([opp for opp in opportunities if opp['opportunity_level'] == 'high']) * 20
        opportunity_score += len([opp for opp in opportunities if opp['opportunity_level'] == 'medium']) * 10
        opportunity_score = min(100, opportunity_score)
        
        # 风险评分 (风险越高，分数越低)
        risk_penalty = len([risk for risk in risk_factors if risk['risk_level'] == 'high']) * 20
        risk_penalty += len([risk for risk in risk_factors if risk['risk_level'] == 'medium']) * 10
        risk_score = max(0, 100 - risk_penalty)
        
        # 综合评分
        overall_score = (sentiment_score * 0.4 + opportunity_score * 0.35 + risk_score * 0.25)
        
        # 投资建议
        if overall_score >= 80:
            action = 'strong_buy'
            action_text = '强烈买入'
        elif overall_score >= 60:
            action = 'buy'
            action_text = '买入'
        elif overall_score >= 40:
            action = 'hold'
            action_text = '持有观望'
        else:
            action = 'avoid'
            action_text = '谨慎回避'
        
        recommendation = {
            'overall_score': round(overall_score, 1),
            'action': action,
            'action_text': action_text,
            'confidence_level': self._calculate_confidence_level(analysis_result),
            'key_reasons': self._extract_key_reasons(analysis_result),
            'risk_warning': self._generate_risk_warning(risk_factors),
            'time_horizon': self._suggest_time_horizon(analysis_result)
        }
        
        return recommendation

    def _calculate_confidence_level(self, analysis_result: Dict) -> str:
        """计算推荐置信度"""
        
        total_items = analysis_result['data_summary']['total_items']
        
        if total_items >= 20:
            return 'high'
        elif total_items >= 10:
            return 'medium'
        else:
            return 'low'

    def _extract_key_reasons(self, analysis_result: Dict) -> List[str]:
        """提取关键推荐理由"""
        
        reasons = []
        
        # 基于机会
        opportunities = analysis_result['opportunities']
        if opportunities:
            high_opp = [opp for opp in opportunities if opp['opportunity_level'] == 'high']
            if high_opp:
                reasons.append(f"发现{len(high_opp)}个高价值投资机会")
        
        # 基于情绪
        sentiment = analysis_result['sentiment_analysis']
        if sentiment['overall_sentiment'] == 'positive':
            reasons.append(f"市场情绪积极，正面信息占比{sentiment['positive_ratio']:.1%}")
        
        # 基于风险
        risk_factors = analysis_result['risk_factors']
        if not risk_factors:
            reasons.append("暂未发现重大风险因素")
        elif len(risk_factors) <= 2:
            reasons.append("风险因素相对可控")
        
        return reasons[:3]

    def _generate_risk_warning(self, risk_factors: List[Dict]) -> str:
        """生成风险警告"""
        
        if not risk_factors:
            return "当前数据显示风险相对较低，但投资需谨慎。"
        
        high_risks = [risk for risk in risk_factors if risk['risk_level'] == 'high']
        
        if high_risks:
            return f"警告：发现{len(high_risks)}个高风险因素，请特别关注市场变化。"
        else:
            return f"注意：发现{len(risk_factors)}个中等风险因素，建议控制仓位。"

    def _suggest_time_horizon(self, analysis_result: Dict) -> str:
        """建议投资时间周期"""
        
        opportunities = analysis_result['opportunities']
        
        # 基于机会类型判断时间周期
        short_term_keywords = ['短线', '突破', '涨停', '热点']
        long_term_keywords = ['重组', '并购', '政策', '技术', '战略']
        
        short_term_count = 0
        long_term_count = 0
        
        for opp in opportunities:
            title_content = f"{opp['title']} {opp['description']}"
            
            if any(keyword in title_content for keyword in short_term_keywords):
                short_term_count += 1
            if any(keyword in title_content for keyword in long_term_keywords):
                long_term_count += 1
        
        if long_term_count > short_term_count:
            return 'long_term'  # 长期(6个月以上)
        elif short_term_count > 0:
            return 'short_term'  # 短期(1-3个月)
        else:
            return 'medium_term'  # 中期(3-6个月)

    def _generate_comprehensive_report(self, analysis_result: Dict, stock_code: str) -> Dict:
        """生成综合报告"""
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 生成HTML报告
        html_path = os.path.join(self.output_dir, f"comprehensive_analysis_{stock_code}_{timestamp}.html")
        self._generate_html_report(analysis_result, html_path)
        
        # 生成Excel报告
        excel_path = os.path.join(self.output_dir, f"comprehensive_analysis_{stock_code}_{timestamp}.xlsx")
        self._generate_excel_report(analysis_result, excel_path)
        
        # 生成JSON数据
        json_path = os.path.join(self.output_dir, f"comprehensive_analysis_{stock_code}_{timestamp}.json")
        self._generate_json_report(analysis_result, json_path)
        
        # 更新分析结果
        analysis_result.update({
            'reports': {
                'html': html_path,
                'excel': excel_path,
                'json': json_path
            }
        })
        
        logger.info(f"  ✓ 报告生成完成:")
        logger.info(f"    HTML: {html_path}")
        logger.info(f"    Excel: {excel_path}")
        logger.info(f"    JSON: {json_path}")
        
        return analysis_result

    def _generate_html_report(self, analysis_result: Dict, html_path: str):
        """生成HTML报告"""
        
        # 这里可以实现详细的HTML报告生成
        # 类似于之前的报告生成器
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>全资源站点集成分析报告 - {analysis_result['stock_code']}</title>
            <meta charset="UTF-8">
        </head>
        <body>
            <h1>全资源站点集成分析报告</h1>
            <h2>股票代码: {analysis_result['stock_code']}</h2>
            <h2>分析时间: {analysis_result['analysis_time']}</h2>
            
            <h3>数据摘要</h3>
            <p>总数据项: {analysis_result['data_summary']['total_items']}</p>
            
            <h3>关键发现</h3>
            <ul>
            {''.join([f"<li>{finding['title']} - {finding['source']}</li>" for finding in analysis_result['key_findings'][:5]])}
            </ul>
            
            <h3>投资建议</h3>
            <p>综合评分: {analysis_result['recommendation']['overall_score']}</p>
            <p>投资建议: {analysis_result['recommendation']['action_text']}</p>
            
        </body>
        </html>
        """
        
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

    def _generate_excel_report(self, analysis_result: Dict, excel_path: str):
        """生成Excel报告"""
        
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            
            # 汇总信息
            summary_data = {
                '项目': ['股票代码', '分析时间', '总数据项', '综合评分', '投资建议', '置信度'],
                '值': [
                    analysis_result['stock_code'],
                    analysis_result['analysis_time'],
                    analysis_result['data_summary']['total_items'],
                    analysis_result['recommendation']['overall_score'],
                    analysis_result['recommendation']['action_text'],
                    analysis_result['recommendation']['confidence_level']
                ]
            }
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='汇总信息', index=False)
            
            # 关键发现
            if analysis_result['key_findings']:
                findings_df = pd.DataFrame(analysis_result['key_findings'])
                findings_df.to_excel(writer, sheet_name='关键发现', index=False)
            
            # 投资机会
            if analysis_result['opportunities']:
                opportunities_df = pd.DataFrame(analysis_result['opportunities'])
                opportunities_df.to_excel(writer, sheet_name='投资机会', index=False)
            
            # 风险因素
            if analysis_result['risk_factors']:
                risks_df = pd.DataFrame(analysis_result['risk_factors'])
                risks_df.to_excel(writer, sheet_name='风险因素', index=False)

    def _generate_json_report(self, analysis_result: Dict, json_path: str):
        """生成JSON数据报告"""
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(analysis_result, f, ensure_ascii=False, indent=2)


def main():
    """主函数 - 全资源站点集成数据分析"""
    
    print("🌐 Kronos 全资源站点集成数据分析器")
    print("=" * 60)
    
    # 获取用户输入
    stock_code = input("请输入股票代码 (例如: 000001): ").strip()
    if not stock_code:
        stock_code = "000001"
    
    analysis_type = input("请选择分析类型 (all/official/financial_media/social_media, 默认: all): ").strip()
    if not analysis_type:
        analysis_type = "all"
    
    time_range = input("请输入分析时间范围 (天数, 默认: 7): ").strip()
    try:
        time_range = int(time_range) if time_range else 7
    except:
        time_range = 7
    
    quality_threshold = input("请输入质量阈值 (0.0-1.0, 默认: 0.7): ").strip()
    try:
        quality_threshold = float(quality_threshold) if quality_threshold else 0.7
    except:
        quality_threshold = 0.7
    
    # 创建分析器
    analyzer = ComprehensiveDataAnalyzer()
    
    # 执行全面分析
    try:
        result = analyzer.analyze_comprehensive_data(
            stock_code=stock_code,
            analysis_type=analysis_type,
            time_range=time_range,
            quality_threshold=quality_threshold
        )
        
        print("\n" + "=" * 60)
        print("🎯 分析结果摘要")
        print("=" * 60)
        print(f"股票代码: {result['stock_code']}")
        print(f"总数据项: {result['data_summary']['total_items']}")
        print(f"关键发现: {len(result['key_findings'])}个")
        print(f"投资机会: {len(result['opportunities'])}个")
        print(f"风险因素: {len(result['risk_factors'])}个")
        print(f"综合评分: {result['recommendation']['overall_score']}")
        print(f"投资建议: {result['recommendation']['action_text']}")
        print(f"分析耗时: {result['execution_stats']['total_execution_time']:.1f}秒")
        
        print("\n📋 报告文件:")
        for report_type, report_path in result['reports'].items():
            print(f"  {report_type.upper()}: {report_path}")
        
    except Exception as e:
        print(f"❌ 分析过程出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()