#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批处理管理器
协调异步数据采集和评分，支持超时控制、进度跟踪、结果汇总
"""

import asyncio
import pandas as pd
from typing import List, Dict, Tuple, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import sys
import logging
import json

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from analysis.async_data_collector import AsyncDataCollector
from analysis.async_opportunity_scorer import AsyncOpportunityScorer

logger = logging.getLogger(__name__)


@dataclass
class ProcessingStats:
    """处理统计信息"""

    total_stocks: int = 0
    completed_stocks: int = 0
    failed_stocks: int = 0
    collection_success: int = 0
    collection_failed: int = 0
    scoring_passed: int = 0
    scoring_failed: int = 0
    
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    elapsed_seconds: float = 0.0
    avg_time_per_stock: float = 0.0

    def calculate_elapsed(self):
        """计算耗时"""
        if self.start_time and self.end_time:
            self.elapsed_seconds = (self.end_time - self.start_time).total_seconds()
            if self.completed_stocks > 0:
                self.avg_time_per_stock = self.elapsed_seconds / self.completed_stocks

    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)

    def to_summary_text(self) -> str:
        """生成摘要文本"""
        success_rate = (
            (self.collection_success / self.total_stocks * 100)
            if self.total_stocks > 0
            else 0
        )
        passed_rate = (
            (self.scoring_passed / self.collection_success * 100)
            if self.collection_success > 0
            else 0
        )

        return f"""
╔════════════════════════════════════════════╗
║         批处理执行统计                      ║
╚════════════════════════════════════════════╝
  总处理股票数:     {self.total_stocks}
  已完成:          {self.completed_stocks}
  处理失败:        {self.failed_stocks}
  
  数据采集:
    ✅ 成功:       {self.collection_success}
    ❌ 失败:       {self.collection_failed}
    成功率:       {success_rate:.1f}%
    
  评分过滤:
    ✅ 通过:       {self.scoring_passed}
    ❌ 未通过:     {self.scoring_failed}
    通过率:       {passed_rate:.1f}%
    
  性能指标:
    总耗时:       {self.elapsed_seconds:.2f}s
    平均/支:      {self.avg_time_per_stock:.2f}s
"""


class BatchProcessor:
    """批处理管理器 - 协调异步采集和评分"""

    def __init__(
        self,
        max_concurrent: int = 5,
        collection_timeout: int = 30,
        scoring_timeout: int = 15,
        enable_progress_bar: bool = True,
    ):
        """
        初始化批处理管理器

        Args:
            max_concurrent: 最大并发数
            collection_timeout: 数据采集超时（秒）
            scoring_timeout: 评分超时（秒）
            enable_progress_bar: 是否显示进度条
        """
        self.max_concurrent = max_concurrent
        self.collection_timeout = collection_timeout
        self.scoring_timeout = scoring_timeout
        self.enable_progress_bar = enable_progress_bar

        self.stats = ProcessingStats()
        self.progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable[[str], None]):
        """设置进度回调函数"""
        self.progress_callback = callback

    async def process_batch(
        self,
        stock_codes: List[str],
        data_types: List[str] = None,
        market_data: Optional[Dict] = None,
        filter_strategy: str = "balanced",
        skip_scoring: bool = False,
    ) -> Tuple[pd.DataFrame, Dict, ProcessingStats]:
        """
        处理一批股票（完整流程：采集 → 评分 → 过滤 → 排序）

        Args:
            stock_codes: 股票代码列表
            data_types: 数据类型列表 (['fundamental', 'sentiment', 'comprehensive'])
            market_data: 市场环境数据
            filter_strategy: 过滤策略
            skip_scoring: 是否跳过评分（仅进行数据采集）

        Returns:
            (排序后的结果DataFrame, 详细结果字典, 统计信息)
        """
        if data_types is None:
            data_types = ["comprehensive"]

        self.stats = ProcessingStats(
            total_stocks=len(stock_codes),
            start_time=datetime.now(),
        )

        self._log("🚀 开始批处理...")
        self._log(f"  📊 股票总数: {len(stock_codes)}")
        self._log(f"  🔄 数据类型: {', '.join(data_types)}")
        self._log(f"  ⏱️  采集超时: {self.collection_timeout}s")
        self._log(f"  ⏱️  评分超时: {self.scoring_timeout}s")

        # 阶段1：数据采集
        self._log("\n【阶段1】数据采集中...")
        collected_data, collection_failed = await self._collect_data_phase(
            stock_codes, data_types
        )

        self.stats.collection_success = len(collected_data)
        self.stats.collection_failed = len(collection_failed)

        if not collected_data:
            self._log("❌ 没有成功采集任何数据，中止处理")
            self.stats.end_time = datetime.now()
            self.stats.calculate_elapsed()
            return pd.DataFrame(), {}, self.stats

        # 阶段2：评分过滤（可选）
        if not skip_scoring:
            self._log("\n【阶段2】评分和过滤中...")
            passed_stocks, failed_stocks = await self._scoring_phase(
                list(collected_data.keys()), market_data, filter_strategy
            )

            self.stats.scoring_passed = len(passed_stocks)
            self.stats.scoring_failed = len(failed_stocks)
        else:
            self._log("\n【阶段2】已跳过评分（仅数据采集模式）")
            passed_stocks = {code: {} for code in collected_data.keys()}
            failed_stocks = {}

        # 阶段3：结果整合和排序
        self._log("\n【阶段3】结果整合...")
        result_df, detailed_results = self._aggregate_results(
            collected_data, passed_stocks, failed_stocks
        )

        self.stats.completed_stocks = len(passed_stocks)
        self.stats.failed_stocks = len(failed_stocks)
        self.stats.end_time = datetime.now()
        self.stats.calculate_elapsed()

        # 显示统计
        self._log(self.stats.to_summary_text())

        return result_df, detailed_results, self.stats

    async def _collect_data_phase(
        self, stock_codes: List[str], data_types: List[str]
    ) -> Tuple[Dict[str, Dict], List[str]]:
        """阶段1：并发采集数据"""
        collected_all = {}
        failed_all = set()

        async with AsyncDataCollector(
            max_concurrent=self.max_concurrent,
            timeout_per_stock=self.collection_timeout,
        ) as collector:
            for data_type in data_types:
                self._log(f"\n  📥 采集 {data_type} 数据...")

                if data_type == "fundamental":
                    success, failed = await collector.collect_batch_fundamental_data(
                        stock_codes, show_progress=False
                    )
                elif data_type == "sentiment":
                    success, failed = await collector.collect_batch_news_sentiment(
                        stock_codes, show_progress=False
                    )
                else:  # comprehensive
                    success, failed = await collector.collect_batch_comprehensive(
                        stock_codes, show_progress=False
                    )

                # 合并数据
                for code in success:
                    if code not in collected_all:
                        collected_all[code] = {}
                    collected_all[code][data_type] = success[code]

                failed_all.update(failed)

        success_count = len(collected_all)
        failed_count = len(failed_all)

        self._log(
            f"  ✅ 采集完成: {success_count} 成功, {failed_count} 失败"
        )

        return collected_all, list(failed_all)

    async def _scoring_phase(
        self, stock_codes: List[str], market_data: Optional[Dict], filter_strategy: str
    ) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
        """阶段2：并发评分和过滤"""
        scorer = AsyncOpportunityScorer(
            max_concurrent=self.max_concurrent,
            timeout_per_stock=self.scoring_timeout,
            use_v4_1=market_data is not None,
        )

        try:
            passed, failed, errors = await scorer.score_batch_stocks(
                stock_codes,
                market_data=market_data,
                show_progress=False,
                filter_strategy=filter_strategy,
            )

            self._log(
                f"  ✅ 评分完成: {len(passed)} 通过, {len(failed)} 未通过, {len(errors)} 异常"
            )

            return passed, failed
        finally:
            scorer.shutdown()

    def _aggregate_results(
        self,
        collected_data: Dict,
        passed_stocks: Dict,
        failed_stocks: Dict,
    ) -> Tuple[pd.DataFrame, Dict]:
        """阶段3：整合结果"""
        rows = []

        def make_row(stock_code: str, score_data: Dict, filter_status: str, reason: str = ""):
            scores = score_data.get("scores", {}) if isinstance(score_data, dict) else {}
            return {
                "股票代码": stock_code,
                "综合评分": score_data.get("total_score", 0),
                "评级": score_data.get("rating", "?"),
                "建议": score_data.get("recommendation", ""),
                "过滤状态": filter_status,
                "未通过原因": reason,
                "量化": scores.get("quantitative", 0),
                "技术": scores.get("technical", 0),
                "位置": scores.get("position_timing", 0),
                "量价": scores.get("volume_health", 0),
                "情绪": scores.get("sentiment", 0),
                "板块": scores.get("sector", 0),
            }

        for stock_code, score_data in passed_stocks.items():
            rows.append(make_row(stock_code, score_data, "通过"))

        for stock_code, fail_info in failed_stocks.items():
            score_data = fail_info.get("full_result") if isinstance(fail_info, dict) else None
            if not isinstance(score_data, dict):
                score_data = {
                    "total_score": fail_info.get("score", 0) if isinstance(fail_info, dict) else 0,
                    "rating": fail_info.get("rating", "?") if isinstance(fail_info, dict) else "?",
                }
            reason = fail_info.get("reason", "") if isinstance(fail_info, dict) else ""
            rows.append(make_row(stock_code, score_data, "未通过", reason))

        if rows:
            df = pd.DataFrame(rows)
            df = df.sort_values("综合评分", ascending=False)
        else:
            df = pd.DataFrame()

        detailed = {
            "passed": passed_stocks,
            "failed": failed_stocks,
            "statistics": self.stats.to_dict(),
        }

        return df, detailed

    def _log(self, message: str):
        """输出日志信息"""
        if self.enable_progress_bar:
            print(message)
        logger.info(message)

        if self.progress_callback:
            self.progress_callback(message)

    def save_results(
        self,
        result_df: pd.DataFrame,
        detailed_results: Dict,
        output_dir: str = "results",
    ):
        """保存处理结果"""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True, parents=True)

        # 保存CSV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file = output_path / f"batch_results_{timestamp}.csv"
        result_df.to_csv(csv_file, index=False, encoding="utf-8-sig")
        self._log(f"✅ 结果已保存到: {csv_file}")

        # 保存JSON详情
        json_file = output_path / f"batch_details_{timestamp}.json"

        def _serialize(value):
            if isinstance(value, datetime):
                return value.isoformat()
            raise TypeError(f"Unserializable type {type(value).__name__}")

        json_safe_details = {
            "statistics": detailed_results.get("statistics", {}),
            "passed_count": len(detailed_results.get("passed", {})),
            "failed_count": len(detailed_results.get("failed", {})),
        }

        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(json_safe_details, f, ensure_ascii=False, indent=2, default=_serialize)
        self._log(f"✅ 详情已保存到: {json_file}")

        return csv_file, json_file


async def process_stocks_batch(
    stock_codes: List[str],
    data_types: List[str] = None,
    market_data: Optional[Dict] = None,
    filter_strategy: str = "balanced",
    max_concurrent: int = 5,
    collection_timeout: int = 30,
    scoring_timeout: int = 15,
) -> Tuple[pd.DataFrame, Dict, ProcessingStats]:
    """
    便利函数：处理一批股票

    Args:
        stock_codes: 股票代码列表
        data_types: 数据类型
        market_data: 市场环境数据
        filter_strategy: 过滤策略
        max_concurrent: 最大并发数
        collection_timeout: 采集超时
        scoring_timeout: 评分超时

    Returns:
        (结果DataFrame, 详细结果, 统计信息)
    """
    processor = BatchProcessor(
        max_concurrent=max_concurrent,
        collection_timeout=collection_timeout,
        scoring_timeout=scoring_timeout,
        enable_progress_bar=True,
    )

    return await processor.process_batch(
        stock_codes,
        data_types=data_types,
        market_data=market_data,
        filter_strategy=filter_strategy,
    )


# 同步包装
def process_stocks_batch_sync(
    stock_codes: List[str],
    data_types: List[str] = None,
    market_data: Optional[Dict] = None,
    filter_strategy: str = "balanced",
    max_concurrent: int = 5,
    collection_timeout: int = 30,
    scoring_timeout: int = 15,
) -> Tuple[pd.DataFrame, Dict, ProcessingStats]:
    """同步包装：处理一批股票"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(
            process_stocks_batch(
                stock_codes,
                data_types,
                market_data,
                filter_strategy,
                max_concurrent,
                collection_timeout,
                scoring_timeout,
            )
        )
    finally:
        pass


if __name__ == "__main__":
    # 测试批处理
    import time

    test_stocks = ["688343", "000001", "600519", "300750", "688111", "601988"]

    print("\n" + "=" * 60)
    print("批处理管理器 - 测试")
    print("=" * 60)

    start = time.time()

    async def main():
        result_df, details, stats = await process_stocks_batch(
            test_stocks,
            data_types=["comprehensive"],
            max_concurrent=3,
            collection_timeout=20,
            scoring_timeout=10,
        )

        print(f"\n📊 处理结果:\n{result_df}")
        print(f"\n⏱️  总耗时: {time.time() - start:.2f}s")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  处理被中断")
