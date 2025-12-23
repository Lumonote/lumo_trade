#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重试机制工具包 - 提升数据采集稳定性
=====================================

核心功能:
1. 指数退避重试装饰器 - 自动重试失败操作
2. 多源回退策略 - 主源失败自动切换备选源
3. 数据质量验证器 - 确保采集数据质量

应用场景:
- 网络不稳定导致的临时失败
- 数据源API故障
- 数据格式异常
"""

import time
import random
import logging
import functools
from typing import Callable, Any, List, Optional, Dict, Tuple
import pandas as pd

logger = logging.getLogger(__name__)


def exponential_backoff_with_jitter(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retry_on: Optional[List[type]] = None
):
    """
    指数退避重试装饰器 - 自动重试失败操作
    
    特性:
    - 指数退避延迟（1s → 2s → 4s → ...）
    - 随机抖动避免惊群效应（±25%）
    - 可配置重试异常类型
    - 自动日志记录
    
    Args:
        max_retries: 最大重试次数（默认3次）
        base_delay: 基础延迟时间（秒，默认1.0）
        max_delay: 最大延迟时间（秒，默认30.0）
        exponential_base: 指数增长基数（默认2.0）
        jitter: 是否添加随机抖动（默认True）
        retry_on: 需要重试的异常类型列表（默认Exception）
    
    使用示例:
        @exponential_backoff_with_jitter(max_retries=3, base_delay=1.0)
        def fetch_stock_data(code):
            # 可能失败的操作
            return api.get_data(code)
    """
    if retry_on is None:
        retry_on = [Exception]
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    logger.debug(f"执行 {func.__name__}(attempt {attempt + 1}/{max_retries})")
                    return func(*args, **kwargs)
                
                except tuple(retry_on) as e:
                    last_exception = e
                    
                    if attempt < max_retries - 1:
                        # 计算延迟时间
                        delay = base_delay * (exponential_base ** attempt)
                        delay = min(delay, max_delay)
                        
                        # 添加随机抖动（±25%）
                        if jitter:
                            jitter_range = delay * 0.25
                            delay += random.uniform(-jitter_range, jitter_range)
                            delay = max(0, delay)  # 确保延迟非负
                        
                        logger.warning(
                            f"{func.__name__} 失败(attempt {attempt + 1}/{max_retries}): {e}. "
                            f"将在 {delay:.2f}s 后重试..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"{func.__name__} 重试次数已耗尽(失败 {max_retries} 次): {e}"
                        )
            
            # 所有重试都失败
            if last_exception:
                raise last_exception
            else:
                raise RuntimeError(f"{func.__name__} 失败，无具体异常信息")
        
        return wrapper
    return decorator


def retry_with_fallback(
    primary_func: Callable,
    fallback_funcs: Optional[List[Callable]] = None,
    max_retries_per_func: int = 2,
    retry_on: Optional[List[type]] = None
) -> Any:
    """
    多源回退策略 - 主源失败自动切换备选源
    
    工作流程:
    1. 尝试主要函数（最多 max_retries_per_func 次）
    2. 主源全部失败后，依次尝试备选函数
    3. 每个备选函数也有 max_retries_per_func 次重试机会
    4. 返回第一个成功的结果
    
    Args:
        primary_func: 主要数据源函数
        fallback_funcs: 备选函数列表
        max_retries_per_func: 每个函数的最大重试次数（默认2）
        retry_on: 需要重试的异常类型列表
    
    Returns:
        函数执行结果（任意类型）
    
    使用示例:
        result = retry_with_fallback(
            primary_func=lambda: fetch_from_eastmoney(),
            fallback_funcs=[
                lambda: fetch_from_tonghuashun(),
                lambda: fetch_from_xueqiu()
            ],
            max_retries_per_func=2
        )
    """
    if fallback_funcs is None:
        fallback_funcs = []
    
    if retry_on is None:
        retry_on = [Exception]
    
    # 准备所有函数列表
    all_funcs = [primary_func] + fallback_funcs
    func_names = ['primary'] + [f'fallback_{i}' for i in range(len(fallback_funcs))]
    
    last_exception = None
    
    for func_idx, (func, func_name) in enumerate(zip(all_funcs, func_names)):
        for attempt in range(max_retries_per_func):
            try:
                logger.info(
                    f"尝试 {func_name} (attempt {attempt + 1}/{max_retries_per_func})"
                )
                result = func()
                logger.info(f"✓ {func_name} 成功!")
                return result
            
            except tuple(retry_on) as e:
                last_exception = e
                logger.warning(
                    f"{func_name} 失败 (attempt {attempt + 1}/{max_retries_per_func}): {e}"
                )
                
                # 如果不是最后一次尝试，等待后重试
                if attempt < max_retries_per_func - 1:
                    delay = 1.0 * (2 ** attempt)
                    logger.debug(f"等待 {delay}s 后重试...")
                    time.sleep(delay)
        
        # 当前函数所有重试都失败，记录并继续下一个源
        if func_idx < len(all_funcs) - 1:
            logger.warning(f"{func_name} 所有重试都失败，切换到下一个源...")
    
    # 所有源都失败
    logger.error("所有数据源都已失败")
    if last_exception:
        raise last_exception
    else:
        raise RuntimeError("所有数据源都已失败，无具体异常信息")


def validate_data_quality(
    data: Any,
    required_fields: Optional[List[str]] = None,
    min_rows: int = 30,
    data_type: str = "数据"
) -> Tuple[bool, Optional[str]]:
    """
    数据质量验证器 - 确保采集数据符合质量标准
    
    验证项:
    1. 数据非空
    2. 包含所有必需字段
    3. 数据行数符合最小要求
    4. 数据格式有效
    
    Args:
        data: 要验证的数据（通常是 DataFrame）
        required_fields: 必需字段列表
        min_rows: 最小行数要求
        data_type: 数据类型描述（用于日志）
    
    Returns:
        (is_valid, error_message)
        - is_valid: True 表示数据质量符合要求
        - error_message: 如果 is_valid=False，包含错误描述
    
    使用示例:
        is_valid, error_msg = validate_data_quality(
            data=df,
            required_fields=['open', 'close', 'volume'],
            min_rows=30,
            data_type="历史K线数据"
        )
        if not is_valid:
            raise ValueError(error_msg)
    """
    if required_fields is None:
        required_fields = []
    
    try:
        # 检查1: 数据非空
        if data is None:
            return False, f"{data_type}为空"
        
        # 检查2: 如果是 DataFrame
        if isinstance(data, pd.DataFrame):
            # 检查行数
            if len(data) < min_rows:
                return False, f"{data_type}行数不足: {len(data)} < {min_rows}"
            
            # 检查必需列
            missing_fields = set(required_fields) - set(data.columns)
            if missing_fields:
                return False, f"{data_type}缺少必需列: {', '.join(missing_fields)}"
            
            # 检查是否为空
            if data.empty:
                return False, f"{data_type}为空 DataFrame"
            
            # 检查必需列是否有空值
            for field in required_fields:
                if data[field].isna().all():
                    return False, f"{data_type}的 {field} 列全为空值"
        
        # 检查3: 如果是字典
        elif isinstance(data, dict):
            missing_fields = set(required_fields) - set(data.keys())
            if missing_fields:
                return False, f"{data_type}缺少必需字段: {', '.join(missing_fields)}"
            
            if not data:
                return False, f"{data_type}为空字典"
        
        # 检查4: 如果是列表
        elif isinstance(data, list):
            if len(data) < min_rows:
                return False, f"{data_type}元素数不足: {len(data)} < {min_rows}"
            
            if not data:
                return False, f"{data_type}为空列表"
        
        logger.debug(f"{data_type}质量验证通过")
        return True, None
    
    except Exception as e:
        error_msg = f"{data_type}质量验证异常: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def handle_missing_fields(
    data: Dict,
    field_defaults: Dict[str, Any]
) -> Dict:
    """
    缺失字段处理 - 填充缺失的字段
    
    如果数据源返回的数据缺少某些字段，使用默认值填充
    
    Args:
        data: 原始数据字典
        field_defaults: 字段默认值映射 {field_name: default_value}
    
    Returns:
        补齐后的数据字典
    
    使用示例:
        data = {'pe_ratio': 15.5}
        data = handle_missing_fields(
            data,
            field_defaults={
                'pe_ratio': None,
                'pb_ratio': None,
                'dividend_yield': 0.0
            }
        )
        # 返回: {'pe_ratio': 15.5, 'pb_ratio': None, 'dividend_yield': 0.0}
    """
    if data is None:
        data = {}
    
    result = data.copy()
    
    for field, default_value in field_defaults.items():
        if field not in result:
            result[field] = default_value
            logger.debug(f"字段 {field} 缺失，使用默认值: {default_value}")
    
    return result


# 预定义的重试装饰器（常用配置）

def retry_light(func):
    """轻度重试（1次重试，延迟0.5s）"""
    return exponential_backoff_with_jitter(
        max_retries=2,
        base_delay=0.5,
        max_delay=5.0
    )(func)


def retry_normal(func):
    """标准重试（3次重试，延迟1s）"""
    return exponential_backoff_with_jitter(
        max_retries=3,
        base_delay=1.0,
        max_delay=15.0
    )(func)


def retry_heavy(func):
    """重度重试（5次重试，延迟2s）"""
    return exponential_backoff_with_jitter(
        max_retries=5,
        base_delay=2.0,
        max_delay=30.0
    )(func)
