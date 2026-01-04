#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能数据源调度管理器 v1.0
============================

负责统一管理和调度所有数据源，实现：
1. 智能数据源选择和优先级管理
2. 负载均衡和故障转移
3. 数据质量监控和评估
4. 反爬虫策略和限流控制
5. 数据缓存和去重管理
"""

import os
import sys
import time
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set, Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from collections import defaultdict, deque
import random
import hashlib
import pickle
from dataclasses import dataclass, asdict
from enum import Enum
import requests
import pandas as pd
import numpy as np

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataSourceStatus(Enum):
    """数据源状态枚举"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    MAINTENANCE = "maintenance"


class DataQuality(Enum):
    """数据质量等级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass
class DataSourceMetrics:
    """数据源指标"""
    success_rate: float = 0.0
    response_time: float = 0.0
    data_quality_score: float = 0.0
    last_success_time: Optional[datetime] = None
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limit_hits: int = 0
    error_count: int = 0
    availability: float = 1.0


@dataclass
class DataRequest:
    """数据请求"""
    request_id: str
    stock_code: str
    data_types: List[str]
    time_range: int
    priority: int = 1
    quality_requirement: DataQuality = DataQuality.MEDIUM
    max_sources: int = 5
    timeout: int = 30
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class DataResponse:
    """数据响应"""
    request_id: str
    source_id: str
    data: List[Dict]
    quality_score: float
    response_time: float
    success: bool
    error_message: Optional[str] = None
    metadata: Optional[Dict] = None
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


class SmartDataSourceScheduler:
    """智能数据源调度管理器"""

    def __init__(self, config_path: str = None):
        """初始化智能数据源调度管理器"""
        
        # 加载配置
        self.config_path = config_path or os.path.join(project_root, "config", "comprehensive_data_sources.json")
        self.config = self._load_config()
        
        # 数据源管理
        self.data_sources = {}
        self.source_metrics = {}
        self.source_status = {}
        
        # 请求管理
        self.request_queue = deque()
        self.active_requests = {}
        self.request_history = deque(maxlen=10000)
        
        # 调度器状态
        self.scheduler_running = False
        self.worker_threads = []
        self.max_workers = 8
        
        # 缓存管理
        self.data_cache = {}
        self.cache_ttl = {}
        self.max_cache_size = 1000
        
        # 限流控制
        self.rate_limiters = {}
        self.request_windows = defaultdict(deque)
        
        # 质量监控
        self.quality_monitor = DataQualityMonitor()
        
        # 故障检测
        self.failure_detector = FailureDetector()
        
        # 统计信息
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'avg_response_time': 0.0,
            'data_quality_avg': 0.0
        }
        
        self._initialize_data_sources()
        logger.info("✓ 智能数据源调度管理器已初始化")

    def _load_config(self) -> Dict:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"配置文件加载失败: {e}")
            return {}

    def _initialize_data_sources(self):
        """初始化数据源"""
        
        comprehensive_sources = self.config.get('comprehensive_data_sources', {})
        
        for category, category_info in comprehensive_sources.items():
            sites = category_info.get('sites', {})
            
            for site_id, site_config in sites.items():
                # 创建数据源实例
                data_source = self._create_data_source(site_id, site_config, category)
                self.data_sources[site_id] = data_source
                
                # 初始化指标
                self.source_metrics[site_id] = DataSourceMetrics()
                self.source_status[site_id] = DataSourceStatus.ACTIVE
                
                # 初始化限流器
                rate_limit = site_config.get('rate_limit', '10/分钟')
                self.rate_limiters[site_id] = RateLimiter(rate_limit)
                
                logger.info(f"  ✓ 数据源已注册: {site_id} ({site_config['name']})")

    def _create_data_source(self, site_id: str, site_config: Dict, category: str) -> Dict:
        """创建数据源配置"""
        
        return {
            'id': site_id,
            'name': site_config['name'],
            'url': site_config['url'],
            'category': category,
            'priority': site_config.get('priority', 3),
            'reliability': site_config.get('reliability', 0.8),
            'data_types': site_config.get('data_types', []),
            'api_endpoints': site_config.get('api_endpoints', {}),
            'access_method': site_config.get('access_method', 'web_scraping'),
            'rate_limit': site_config.get('rate_limit', '10/分钟'),
            'anti_crawler': site_config.get('anti_crawler', {}),
            'subscription_required': site_config.get('subscription_required', False),
            'update_frequency': site_config.get('update_frequency', '每小时')
        }

    def start_scheduler(self):
        """启动调度器"""
        
        if self.scheduler_running:
            logger.warning("调度器已经在运行")
            return
        
        self.scheduler_running = True
        
        # 启动工作线程
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 主调度循环
            futures = []
            futures.append(executor.submit(self._main_scheduler_loop))
            futures.append(executor.submit(self._health_monitor_loop))
            futures.append(executor.submit(self._cache_cleanup_loop))
            futures.append(executor.submit(self._metrics_collection_loop))
            
            try:
                for future in as_completed(futures):
                    future.result()
            except KeyboardInterrupt:
                logger.info("调度器正在停止...")
                self.scheduler_running = False

    def stop_scheduler(self):
        """停止调度器"""
        self.scheduler_running = False
        logger.info("调度器已停止")

    def submit_request(self, request: DataRequest) -> str:
        """提交数据请求"""
        
        request_id = request.request_id
        self.request_queue.append(request)
        self.active_requests[request_id] = request
        self.stats['total_requests'] += 1
        
        logger.info(f"数据请求已提交: {request_id} (股票: {request.stock_code})")
        return request_id

    def get_request_status(self, request_id: str) -> Optional[Dict]:
        """获取请求状态"""
        
        request = self.active_requests.get(request_id)
        if not request:
            return None
        
        return {
            'request_id': request_id,
            'stock_code': request.stock_code,
            'status': 'processing',
            'created_at': request.created_at.isoformat(),
            'priority': request.priority
        }

    def _main_scheduler_loop(self):
        """主调度循环"""
        
        logger.info("主调度器循环已启动")
        
        while self.scheduler_running:
            try:
                # 处理请求队列
                if self.request_queue:
                    request = self.request_queue.popleft()
                    self._process_request(request)
                
                time.sleep(1)  # 避免CPU占用过高
                
            except Exception as e:
                logger.error(f"调度器主循环错误: {e}")
                time.sleep(5)

    def _process_request(self, request: DataRequest):
        """处理单个数据请求"""
        
        request_id = request.request_id
        logger.info(f"开始处理请求: {request_id}")
        
        try:
            # 检查缓存
            cached_data = self._check_cache(request)
            if cached_data:
                self._handle_cached_response(request, cached_data)
                return
            
            # 选择最优数据源
            selected_sources = self._select_optimal_sources(request)
            
            if not selected_sources:
                self._handle_request_failure(request, "没有可用的数据源")
                return
            
            # 并行从多个源收集数据
            responses = self._collect_from_multiple_sources(request, selected_sources)
            
            # 数据整合和质量评估
            final_response = self._integrate_responses(request, responses)
            
            # 缓存结果
            self._cache_response(request, final_response)
            
            # 更新统计信息
            self._update_success_stats(request, final_response)
            
            logger.info(f"请求处理完成: {request_id}")
            
        except Exception as e:
            logger.error(f"请求处理失败 {request_id}: {e}")
            self._handle_request_failure(request, str(e))
        finally:
            # 清理活跃请求
            if request_id in self.active_requests:
                del self.active_requests[request_id]

    def _check_cache(self, request: DataRequest) -> Optional[Dict]:
        """检查缓存"""
        
        cache_key = self._generate_cache_key(request)
        
        if cache_key in self.data_cache:
            cache_entry = self.data_cache[cache_key]
            cache_time = cache_entry['timestamp']
            ttl = self.cache_ttl.get(cache_key, 3600)  # 默认1小时
            
            if time.time() - cache_time < ttl:
                self.stats['cache_hits'] += 1
                logger.info(f"缓存命中: {request.request_id}")
                return cache_entry['data']
        
        self.stats['cache_misses'] += 1
        return None

    def _generate_cache_key(self, request: DataRequest) -> str:
        """生成缓存键"""
        
        key_data = {
            'stock_code': request.stock_code,
            'data_types': sorted(request.data_types),
            'time_range': request.time_range,
            'quality': request.quality_requirement.value
        }
        
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    def _select_optimal_sources(self, request: DataRequest) -> List[str]:
        """选择最优数据源"""
        
        suitable_sources = []
        
        # 筛选支持所需数据类型的源
        for source_id, source_config in self.data_sources.items():
            if self._source_supports_request(source_config, request):
                suitable_sources.append(source_id)
        
        # 按优先级和性能排序
        suitable_sources.sort(key=lambda x: self._calculate_source_score(x, request), reverse=True)
        
        # 限制数量
        max_sources = min(request.max_sources, len(suitable_sources))
        selected = suitable_sources[:max_sources]
        
        logger.info(f"为请求 {request.request_id} 选择了 {len(selected)} 个数据源: {selected}")
        return selected

    def _source_supports_request(self, source_config: Dict, request: DataRequest) -> bool:
        """检查数据源是否支持请求"""
        
        # 检查状态
        source_id = source_config['id']
        if self.source_status[source_id] != DataSourceStatus.ACTIVE:
            return False
        
        # 检查数据类型支持
        source_data_types = set(source_config.get('data_types', []))
        request_data_types = set(request.data_types)
        
        if not request_data_types.intersection(source_data_types):
            return False
        
        # 检查限流状态
        if not self.rate_limiters[source_id].can_proceed():
            return False
        
        return True

    def _calculate_source_score(self, source_id: str, request: DataRequest) -> float:
        """计算数据源评分"""
        
        source_config = self.data_sources[source_id]
        metrics = self.source_metrics[source_id]
        
        score = 0.0
        
        # 可靠性权重 (30%)
        reliability = source_config.get('reliability', 0.8)
        score += reliability * 30
        
        # 优先级权重 (25%)
        priority_score = (4 - source_config.get('priority', 3)) * 25 / 3
        score += priority_score
        
        # 成功率权重 (20%)
        success_rate = metrics.success_rate
        score += success_rate * 20
        
        # 响应时间权重 (15%)
        response_time = metrics.response_time
        time_score = max(0, (5 - response_time) / 5) * 15  # 5秒内满分
        score += time_score
        
        # 数据质量权重 (10%)
        quality_score = metrics.data_quality_score * 10
        score += quality_score
        
        return score

    def _collect_from_multiple_sources(self, request: DataRequest, source_ids: List[str]) -> List[DataResponse]:
        """从多个源并行收集数据"""
        
        responses = []
        
        with ThreadPoolExecutor(max_workers=len(source_ids)) as executor:
            # 提交收集任务
            futures = {}
            for source_id in source_ids:
                future = executor.submit(self._collect_from_source, request, source_id)
                futures[future] = source_id
            
            # 收集结果
            for future in as_completed(futures, timeout=request.timeout):
                source_id = futures[future]
                try:
                    response = future.result()
                    if response:
                        responses.append(response)
                        logger.info(f"数据源 {source_id} 返回 {len(response.data)} 条数据")
                except Exception as e:
                    logger.error(f"数据源 {source_id} 收集失败: {e}")
                    self._update_source_error(source_id, str(e))
        
        return responses

    def _collect_from_source(self, request: DataRequest, source_id: str) -> Optional[DataResponse]:
        """从单个数据源收集数据"""
        
        start_time = time.time()
        source_config = self.data_sources[source_id]
        
        try:
            # 检查限流
            if not self.rate_limiters[source_id].acquire():
                logger.warning(f"数据源 {source_id} 受限流限制")
                return None
            
            # 实际数据收集 (这里需要根据具体数据源实现)
            data = self._perform_data_collection(source_config, request)
            
            # 数据质量评估
            quality_score = self.quality_monitor.assess_data_quality(data)
            
            response_time = time.time() - start_time
            
            # 创建响应对象
            response = DataResponse(
                request_id=request.request_id,
                source_id=source_id,
                data=data,
                quality_score=quality_score,
                response_time=response_time,
                success=True
            )
            
            # 更新指标
            self._update_source_metrics(source_id, response_time, quality_score, True)
            
            return response
            
        except Exception as e:
            response_time = time.time() - start_time
            logger.error(f"数据源 {source_id} 收集错误: {e}")
            
            # 更新指标
            self._update_source_metrics(source_id, response_time, 0.0, False)
            
            return DataResponse(
                request_id=request.request_id,
                source_id=source_id,
                data=[],
                quality_score=0.0,
                response_time=response_time,
                success=False,
                error_message=str(e)
            )

    def _perform_data_collection(self, source_config: Dict, request: DataRequest) -> List[Dict]:
        """执行实际的数据收集"""
        
        # 这里是模拟实现，实际需要根据每个数据源的特点实现
        source_id = source_config['id']
        access_method = source_config.get('access_method', 'web_scraping')
        
        logger.info(f"从 {source_id} 收集数据，方法: {access_method}")
        
        # 模拟数据收集延迟
        time.sleep(random.uniform(0.5, 2.0))
        
        # 返回模拟数据
        mock_data = [
            {
                'title': f'模拟新闻标题 {i}',
                'content': f'模拟内容来自 {source_config["name"]}',
                'source': source_id,
                'timestamp': datetime.now().isoformat(),
                'stock_code': request.stock_code
            }
            for i in range(random.randint(1, 5))
        ]
        
        return mock_data

    def _update_source_metrics(self, source_id: str, response_time: float, quality_score: float, success: bool):
        """更新数据源指标"""
        
        metrics = self.source_metrics[source_id]
        
        metrics.total_requests += 1
        
        if success:
            metrics.successful_requests += 1
            metrics.last_success_time = datetime.now()
        else:
            metrics.failed_requests += 1
            metrics.error_count += 1
        
        # 更新成功率
        metrics.success_rate = metrics.successful_requests / metrics.total_requests
        
        # 更新平均响应时间
        if metrics.response_time == 0:
            metrics.response_time = response_time
        else:
            metrics.response_time = (metrics.response_time * 0.8) + (response_time * 0.2)
        
        # 更新数据质量分数
        if quality_score > 0:
            if metrics.data_quality_score == 0:
                metrics.data_quality_score = quality_score
            else:
                metrics.data_quality_score = (metrics.data_quality_score * 0.8) + (quality_score * 0.2)
        
        # 更新可用性
        metrics.availability = metrics.success_rate

    def _integrate_responses(self, request: DataRequest, responses: List[DataResponse]) -> Dict:
        """整合多个数据源的响应"""
        
        if not responses:
            return {'data': [], 'quality_score': 0.0, 'source_count': 0}
        
        # 合并数据
        all_data = []
        total_quality = 0.0
        successful_responses = 0
        
        for response in responses:
            if response.success and response.data:
                all_data.extend(response.data)
                total_quality += response.quality_score
                successful_responses += 1
        
        # 去重
        unique_data = self._deduplicate_data(all_data)
        
        # 计算平均质量分数
        avg_quality = total_quality / max(1, successful_responses)
        
        # 按质量排序
        sorted_data = sorted(unique_data, key=lambda x: x.get('quality_score', 0.5), reverse=True)
        
        integrated_result = {
            'data': sorted_data,
            'quality_score': avg_quality,
            'source_count': successful_responses,
            'total_items': len(sorted_data),
            'sources_used': [r.source_id for r in responses if r.success]
        }
        
        logger.info(f"数据整合完成: {len(sorted_data)} 条数据，质量分数: {avg_quality:.2f}")
        return integrated_result

    def _deduplicate_data(self, data_list: List[Dict]) -> List[Dict]:
        """数据去重"""
        
        seen_hashes = set()
        unique_data = []
        
        for item in data_list:
            # 生成内容哈希
            content_hash = self._generate_content_hash(item)
            
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                unique_data.append(item)
        
        logger.info(f"去重处理: {len(data_list)} -> {len(unique_data)}")
        return unique_data

    def _generate_content_hash(self, item: Dict) -> str:
        """生成内容哈希"""
        
        # 使用标题和内容生成哈希
        title = item.get('title', '')
        content = item.get('content', '')
        combined = f"{title}:{content}"
        
        return hashlib.md5(combined.encode('utf-8')).hexdigest()

    def _cache_response(self, request: DataRequest, response_data: Dict):
        """缓存响应数据"""
        
        cache_key = self._generate_cache_key(request)
        
        # 清理缓存空间
        if len(self.data_cache) >= self.max_cache_size:
            self._cleanup_cache()
        
        # 缓存数据
        self.data_cache[cache_key] = {
            'data': response_data,
            'timestamp': time.time(),
            'request_id': request.request_id
        }
        
        # 设置TTL
        quality_score = response_data.get('quality_score', 0.5)
        ttl = 3600 * (1 + quality_score)  # 质量越高，缓存时间越长
        self.cache_ttl[cache_key] = ttl

    def _cleanup_cache(self):
        """清理过期缓存"""
        
        current_time = time.time()
        expired_keys = []
        
        for cache_key, cache_entry in self.data_cache.items():
            cache_time = cache_entry['timestamp']
            ttl = self.cache_ttl.get(cache_key, 3600)
            
            if current_time - cache_time > ttl:
                expired_keys.append(cache_key)
        
        for key in expired_keys:
            del self.data_cache[key]
            if key in self.cache_ttl:
                del self.cache_ttl[key]
        
        logger.info(f"缓存清理: 删除 {len(expired_keys)} 个过期条目")

    def _handle_cached_response(self, request: DataRequest, cached_data: Dict):
        """处理缓存响应"""
        
        self._update_success_stats(request, cached_data)
        logger.info(f"请求 {request.request_id} 由缓存提供")

    def _handle_request_failure(self, request: DataRequest, error_message: str):
        """处理请求失败"""
        
        self.stats['failed_requests'] += 1
        logger.error(f"请求失败 {request.request_id}: {error_message}")

    def _update_success_stats(self, request: DataRequest, response_data: Dict):
        """更新成功统计"""
        
        self.stats['successful_requests'] += 1
        
        # 更新平均质量分数
        quality_score = response_data.get('quality_score', 0.0)
        if self.stats['data_quality_avg'] == 0:
            self.stats['data_quality_avg'] = quality_score
        else:
            self.stats['data_quality_avg'] = (self.stats['data_quality_avg'] * 0.9) + (quality_score * 0.1)

    def _update_source_error(self, source_id: str, error_message: str):
        """更新数据源错误"""
        
        metrics = self.source_metrics[source_id]
        metrics.error_count += 1
        
        # 检查是否需要暂停数据源
        if metrics.error_count >= 5:
            self.source_status[source_id] = DataSourceStatus.ERROR
            logger.warning(f"数据源 {source_id} 因错误过多被暂停")

    def _health_monitor_loop(self):
        """健康监控循环"""
        
        logger.info("健康监控循环已启动")
        
        while self.scheduler_running:
            try:
                self._perform_health_checks()
                time.sleep(60)  # 每分钟检查一次
            except Exception as e:
                logger.error(f"健康监控错误: {e}")
                time.sleep(30)

    def _perform_health_checks(self):
        """执行健康检查"""
        
        for source_id in self.data_sources:
            metrics = self.source_metrics[source_id]
            
            # 检查成功率
            if metrics.total_requests > 10 and metrics.success_rate < 0.3:
                self.source_status[source_id] = DataSourceStatus.ERROR
                logger.warning(f"数据源 {source_id} 成功率过低: {metrics.success_rate:.2f}")
            
            # 检查最后成功时间
            if metrics.last_success_time:
                time_since_success = (datetime.now() - metrics.last_success_time).total_seconds()
                if time_since_success > 3600:  # 1小时无成功
                    self.source_status[source_id] = DataSourceStatus.INACTIVE
                    logger.warning(f"数据源 {source_id} 长时间无响应")

    def _cache_cleanup_loop(self):
        """缓存清理循环"""
        
        logger.info("缓存清理循环已启动")
        
        while self.scheduler_running:
            try:
                self._cleanup_cache()
                time.sleep(300)  # 每5分钟清理一次
            except Exception as e:
                logger.error(f"缓存清理错误: {e}")
                time.sleep(60)

    def _metrics_collection_loop(self):
        """指标收集循环"""
        
        logger.info("指标收集循环已启动")
        
        while self.scheduler_running:
            try:
                self._collect_metrics()
                time.sleep(300)  # 每5分钟收集一次
            except Exception as e:
                logger.error(f"指标收集错误: {e}")
                time.sleep(60)

    def _collect_metrics(self):
        """收集系统指标"""
        
        # 更新全局统计
        total_requests = sum(m.total_requests for m in self.source_metrics.values())
        successful_requests = sum(m.successful_requests for m in self.source_metrics.values())
        
        if total_requests > 0:
            self.stats['avg_response_time'] = np.mean([
                m.response_time for m in self.source_metrics.values() 
                if m.response_time > 0
            ])

    def get_system_status(self) -> Dict:
        """获取系统状态"""
        
        # 数据源状态统计
        status_counts = {}
        for status in DataSourceStatus:
            status_counts[status.value] = sum(
                1 for s in self.source_status.values() if s == status
            )
        
        # Top数据源
        top_sources = sorted(
            self.data_sources.keys(),
            key=lambda x: self.source_metrics[x].success_rate,
            reverse=True
        )[:5]
        
        return {
            'scheduler_running': self.scheduler_running,
            'total_sources': len(self.data_sources),
            'source_status_counts': status_counts,
            'top_performing_sources': top_sources,
            'active_requests': len(self.active_requests),
            'cache_size': len(self.data_cache),
            'stats': self.stats.copy(),
            'uptime': time.time()  # 可以计算实际运行时间
        }


class RateLimiter:
    """限流器"""
    
    def __init__(self, rate_limit: str):
        """初始化限流器
        
        Args:
            rate_limit: 限流配置，如 "10/分钟", "100/小时"
        """
        self.rate_limit = rate_limit
        self.requests = deque()
        self.max_requests, self.time_window = self._parse_rate_limit(rate_limit)
    
    def _parse_rate_limit(self, rate_limit: str) -> Tuple[int, int]:
        """解析限流配置"""
        
        parts = rate_limit.split('/')
        if len(parts) != 2:
            return 10, 60  # 默认10/分钟
        
        max_requests = int(parts[0])
        
        time_unit = parts[1].lower()
        if '秒' in time_unit or 'second' in time_unit:
            time_window = 1
        elif '分' in time_unit or 'minute' in time_unit:
            time_window = 60
        elif '小时' in time_unit or 'hour' in time_unit:
            time_window = 3600
        elif '天' in time_unit or 'day' in time_unit:
            time_window = 86400
        else:
            time_window = 60  # 默认分钟
        
        return max_requests, time_window
    
    def can_proceed(self) -> bool:
        """检查是否可以继续请求"""
        current_time = time.time()
        
        # 清理过期请求
        while self.requests and current_time - self.requests[0] > self.time_window:
            self.requests.popleft()
        
        return len(self.requests) < self.max_requests
    
    def acquire(self) -> bool:
        """获取请求许可"""
        if self.can_proceed():
            self.requests.append(time.time())
            return True
        return False


class DataQualityMonitor:
    """数据质量监控器"""
    
    def assess_data_quality(self, data: List[Dict]) -> float:
        """评估数据质量"""
        
        if not data:
            return 0.0
        
        quality_score = 0.0
        
        # 完整性检查 (40%)
        completeness_score = self._check_completeness(data)
        quality_score += completeness_score * 0.4
        
        # 准确性检查 (30%)
        accuracy_score = self._check_accuracy(data)
        quality_score += accuracy_score * 0.3
        
        # 时效性检查 (20%)
        timeliness_score = self._check_timeliness(data)
        quality_score += timeliness_score * 0.2
        
        # 一致性检查 (10%)
        consistency_score = self._check_consistency(data)
        quality_score += consistency_score * 0.1
        
        return min(1.0, quality_score)
    
    def _check_completeness(self, data: List[Dict]) -> float:
        """检查数据完整性"""
        
        required_fields = ['title', 'content', 'timestamp']
        total_score = 0.0
        
        for item in data:
            item_score = 0.0
            for field in required_fields:
                if field in item and item[field]:
                    item_score += 1 / len(required_fields)
            
            total_score += item_score
        
        return total_score / len(data) if data else 0.0
    
    def _check_accuracy(self, data: List[Dict]) -> float:
        """检查数据准确性"""
        
        # 简单的准确性检查
        valid_items = 0
        
        for item in data:
            title = item.get('title', '')
            content = item.get('content', '')
            
            # 检查标题和内容长度
            if len(title) >= 5 and len(content) >= 10:
                valid_items += 1
        
        return valid_items / len(data) if data else 0.0
    
    def _check_timeliness(self, data: List[Dict]) -> float:
        """检查数据时效性"""
        
        current_time = datetime.now()
        timely_items = 0
        
        for item in data:
            timestamp_str = item.get('timestamp', '')
            if timestamp_str:
                try:
                    # 简单的时间检查
                    timely_items += 1
                except:
                    pass
        
        return timely_items / len(data) if data else 0.0
    
    def _check_consistency(self, data: List[Dict]) -> float:
        """检查数据一致性"""
        
        # 简单的一致性检查
        if not data:
            return 0.0
        
        # 检查数据结构一致性
        first_item_keys = set(data[0].keys())
        consistent_items = 0
        
        for item in data:
            item_keys = set(item.keys())
            similarity = len(first_item_keys & item_keys) / len(first_item_keys | item_keys)
            if similarity > 0.7:  # 70%以上字段一致
                consistent_items += 1
        
        return consistent_items / len(data)


class FailureDetector:
    """故障检测器"""
    
    def __init__(self):
        self.failure_history = defaultdict(list)
        self.recovery_times = defaultdict(list)
    
    def record_failure(self, source_id: str, error_type: str):
        """记录故障"""
        
        self.failure_history[source_id].append({
            'timestamp': time.time(),
            'error_type': error_type
        })
        
        # 保留最近100个故障记录
        self.failure_history[source_id] = self.failure_history[source_id][-100:]
    
    def record_recovery(self, source_id: str):
        """记录恢复"""
        
        self.recovery_times[source_id].append(time.time())
        self.recovery_times[source_id] = self.recovery_times[source_id][-50:]
    
    def predict_failure_probability(self, source_id: str) -> float:
        """预测故障概率"""
        
        failures = self.failure_history.get(source_id, [])
        if not failures:
            return 0.0
        
        # 基于最近故障频率预测
        recent_failures = [
            f for f in failures 
            if time.time() - f['timestamp'] < 3600  # 最近1小时
        ]
        
        if len(recent_failures) > 5:
            return 0.8  # 高故障概率
        elif len(recent_failures) > 2:
            return 0.5  # 中等故障概率
        else:
            return 0.2  # 低故障概率


def main():
    """主函数 - 智能数据源调度管理器演示"""
    
    print("🤖 Kronos 智能数据源调度管理器")
    print("=" * 60)
    
    # 创建调度器
    scheduler = SmartDataSourceScheduler()
    
    # 提交测试请求
    test_request = DataRequest(
        request_id="test_001",
        stock_code="000001",
        data_types=["新闻", "公告", "讨论"],
        time_range=7,
        priority=1,
        quality_requirement=DataQuality.HIGH
    )
    
    # 提交请求
    request_id = scheduler.submit_request(test_request)
    print(f"测试请求已提交: {request_id}")
    
    # 处理请求
    scheduler._process_request(test_request)
    
    # 显示系统状态
    status = scheduler.get_system_status()
    print("\n📊 系统状态:")
    print(f"总数据源数: {status['total_sources']}")
    print(f"活跃请求数: {status['active_requests']}")
    print(f"缓存大小: {status['cache_size']}")
    print(f"成功率: {status['stats']['successful_requests']}/{status['stats']['total_requests']}")


if __name__ == "__main__":
    main()