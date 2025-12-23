#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步投资机会打分系统
支持并发评分多支股票
"""

import asyncio
import pandas as pd
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import sys
import logging
from concurrent.futures import ThreadPoolExecutor

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from analysis.opportunity_scorer import OpportunityScorer
from analysis.opportunity_scorer_v4_1_integration import OpportunityScorerV41
from analysis.market_env_analyzer import MarketEnvAnalyzer
from analysis.comprehensive_score_filter import ComprehensiveScoreFilter

logger = logging.getLogger(__name__)


class AsyncOpportunityScorer:
    """异步投资机会打分系统 - 支持并发评分多支股票"""

    def __init__(
        self,
        max_concurrent: int = 5,
        timeout_per_stock: int = 15,
        use_v4_1: bool = True,
    ):
        """
        初始化异步打分系统

        Args:
            max_concurrent: 最大并发任务数
            timeout_per_stock: 每支股票的超时时间（秒）
            use_v4_1: 是否使用v4.1集成版本（支持市场环境分析）
        """
        self.max_concurrent = max_concurrent
        self.timeout_per_stock = timeout_per_stock
        self.use_v4_1 = use_v4_1
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # 初始化打分器和过滤器
        if use_v4_1:
            self.scorer = OpportunityScorerV41()
        else:
            self.scorer = OpportunityScorer()
        self.filter = ComprehensiveScoreFilter()
        
        # 线程池用于运行同步操作
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent)

    async def score_batch_stocks(
        self,
        stock_codes: List[str],
        market_data: Optional[Dict] = None,
        show_progress: bool = True,
        filter_strategy: str = "balanced",
    ) -> Tuple[Dict[str, Dict], Dict[str, Dict], List[str]]:
        """
        并发评分多支股票

        Args:
            stock_codes: 股票代码列表
            market_data: 市场环境数据（用于v4.1）
            show_progress: 是否显示进度
            filter_strategy: 过滤策略 ('conservative', 'balanced', 'aggressive', 'bottom_hunting')

        Returns:
            (通过过滤的股票, 未通过过滤的股票, 失败的股票代码列表)
        """
        tasks = []
        for stock_code in stock_codes:
            task = self._score_stock_with_timeout(stock_code, market_data)
            tasks.append(task)

        if show_progress:
            print(f"🔄 开始并发评分 {len(stock_codes)} 支股票...")

        results = await asyncio.gather(*tasks, return_exceptions=True)

        passed_stocks = {}
        failed_stocks = {}
        error_stocks = []

        # 设置过滤策略
        self.filter.set_strategy(filter_strategy)

        for stock_code, result in zip(stock_codes, results):
            if isinstance(result, Exception):
                logger.error(f"评分 {stock_code} 失败: {str(result)}")
                error_stocks.append(stock_code)
                if show_progress:
                    print(f"   ❌ {stock_code}: 评分失败")
            elif result is None:
                error_stocks.append(stock_code)
                if show_progress:
                    print(f"   ⚠️  {stock_code}: 评分为空")
            else:
                # 应用过滤
                passed, reason, details = self.filter.filter(result)
                
                if passed:
                    passed_stocks[stock_code] = result
                    if show_progress:
                        rating = result.get("rating", "?")
                        score = result.get("total_score", 0)
                        print(f"   ✅ {stock_code}: {rating} ({score:.1f}分) - 通过")
                else:
                    failed_stocks[stock_code] = {
                        "score": result.get("total_score", 0),
                        "rating": result.get("rating", "?"),
                        "reason": reason,
                        "full_result": result,
                    }
                    if show_progress:
                        print(f"   ⏭️  {stock_code}: 未通过 ({reason})")

        if show_progress:
            print(
                f"\n✅ 评分完成: {len(passed_stocks)}/{len(stock_codes)} 通过过滤, "
                f"{len(failed_stocks)} 未通过, {len(error_stocks)} 评分失败"
            )

        return passed_stocks, failed_stocks, error_stocks

    async def score_and_rank_stocks(
        self,
        stock_codes: List[str],
        market_data: Optional[Dict] = None,
        show_progress: bool = True,
        top_n: int = 10,
        filter_strategy: str = "balanced",
    ) -> Tuple[pd.DataFrame, Dict[str, Dict], List[str]]:
        """
        并发评分多支股票并排序

        Args:
            stock_codes: 股票代码列表
            market_data: 市场环境数据
            show_progress: 是否显示进度
            top_n: 返回排名前N的股票
            filter_strategy: 过滤策略

        Returns:
            (排序后的DataFrame, 未通过过滤的股票, 失败的股票代码列表)
        """
        passed_stocks, failed_stocks, error_stocks = await self.score_batch_stocks(
            stock_codes, market_data, show_progress, filter_strategy
        )

        # 转换为DataFrame并排序
        if passed_stocks:
            rows = []
            for code, result in passed_stocks.items():
                rows.append(
                    {
                        "股票代码": code,
                        "综合评分": result.get("total_score", 0),
                        "评级": result.get("rating", "?"),
                        "建议": result.get("recommendation", ""),
                        "量化": result.get("scores", {}).get("quantitative", 0),
                        "技术": result.get("scores", {}).get("technical", 0),
                        "位置": result.get("scores", {}).get("position_timing", 0),
                        "量价": result.get("scores", {}).get("volume_health", 0),
                    }
                )

            df = pd.DataFrame(rows)
            df = df.sort_values("综合评分", ascending=False)
            df = df.head(top_n)

            if show_progress:
                print(f"\n📊 排名前{top_n}的股票:\n{df.to_string(index=False)}")

            return df, failed_stocks, error_stocks
        else:
            if show_progress:
                print("\n⚠️  没有通过过滤的股票")
            return pd.DataFrame(), failed_stocks, error_stocks

    async def _score_stock_with_timeout(
        self, stock_code: str, market_data: Optional[Dict] = None
    ) -> Optional[Dict]:
        """评分单支股票（带超时控制和信号量限制）"""
        async with self.semaphore:
            try:
                loop = asyncio.get_event_loop()

                if self.use_v4_1:
                    # 使用v4.1版本（支持市场环境分析）
                    score_result = await asyncio.wait_for(
                        loop.run_in_executor(
                            self.executor,
                            self._score_v4_1_sync,
                            stock_code,
                            market_data,
                        ),
                        timeout=self.timeout_per_stock,
                    )
                else:
                    # 使用基础版本
                    score_result = await asyncio.wait_for(
                        loop.run_in_executor(
                            self.executor,
                            self._score_base_sync,
                            stock_code,
                        ),
                        timeout=self.timeout_per_stock,
                    )

                return score_result

            except asyncio.TimeoutError:
                logger.warning(f"{stock_code} 评分超时（{self.timeout_per_stock}s）")
                return None
            except Exception as e:
                logger.error(f"{stock_code} 评分异常: {str(e)}")
                return None

    def _score_v4_1_sync(
        self, stock_code: str, market_data: Optional[Dict] = None
    ) -> Optional[Dict]:
        """同步评分（v4.1版本）"""
        try:
            result = self.scorer.analyze_and_score(stock_code, market_data)
            return result
        except Exception as e:
            logger.error(f"v4.1评分异常: {str(e)}")
            return None

    def _score_base_sync(self, stock_code: str) -> Optional[Dict]:
        """同步评分（基础版本）"""
        try:
            result = self.scorer.calculate_comprehensive_score(stock_code)
            return result
        except Exception as e:
            logger.error(f"基础评分异常: {str(e)}")
            return None

    def shutdown(self):
        """关闭线程池"""
        self.executor.shutdown(wait=True)


async def batch_score_stocks(
    stock_codes: List[str],
    market_data: Optional[Dict] = None,
    max_concurrent: int = 5,
    timeout_per_stock: int = 15,
    use_v4_1: bool = True,
    filter_strategy: str = "balanced",
    return_ranked: bool = False,
    top_n: int = 10,
) -> Tuple[Dict, Dict, List[str]]:
    """
    便利函数：并发评分多支股票

    Args:
        stock_codes: 股票代码列表
        market_data: 市场环境数据
        max_concurrent: 最大并发数
        timeout_per_stock: 单支股票超时时间
        use_v4_1: 是否使用v4.1版本
        filter_strategy: 过滤策略
        return_ranked: 是否返回排序结果
        top_n: 返回排名前N

    Returns:
        (通过过滤的股票, 未通过过滤的股票, 失败的股票代码列表)
        或 (排序后的DataFrame, 未通过过滤的股票, 失败的股票代码列表)
    """
    scorer = AsyncOpportunityScorer(
        max_concurrent=max_concurrent,
        timeout_per_stock=timeout_per_stock,
        use_v4_1=use_v4_1,
    )

    try:
        if return_ranked:
            return await scorer.score_and_rank_stocks(
                stock_codes,
                market_data,
                show_progress=True,
                top_n=top_n,
                filter_strategy=filter_strategy,
            )
        else:
            passed, failed, errors = await scorer.score_batch_stocks(
                stock_codes,
                market_data,
                show_progress=True,
                filter_strategy=filter_strategy,
            )
            return passed, failed, errors
    finally:
        scorer.shutdown()


# 兼容同步接口的包装函数
def batch_score_stocks_sync(
    stock_codes: List[str],
    market_data: Optional[Dict] = None,
    max_concurrent: int = 5,
    timeout_per_stock: int = 15,
    use_v4_1: bool = True,
    filter_strategy: str = "balanced",
    return_ranked: bool = False,
    top_n: int = 10,
) -> Tuple[Dict, Dict, List[str]]:
    """
    同步包装函数：并发评分多支股票

    Args:
        stock_codes: 股票代码列表
        market_data: 市场环境数据
        max_concurrent: 最大并发数
        timeout_per_stock: 单支股票超时时间
        use_v4_1: 是否使用v4.1版本
        filter_strategy: 过滤策略
        return_ranked: 是否返回排序结果
        top_n: 返回排名前N

    Returns:
        (通过过滤的股票, 未通过过滤的股票, 失败的股票代码列表)
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(
            batch_score_stocks(
                stock_codes,
                market_data,
                max_concurrent,
                timeout_per_stock,
                use_v4_1,
                filter_strategy,
                return_ranked,
                top_n,
            )
        )
    finally:
        pass


if __name__ == "__main__":
    # 测试异步评分
    import time

    test_stocks = ["688343", "000001", "600519", "300750", "688111"]

    print("\n" + "=" * 60)
    print("异步打分系统 - 测试")
    print("=" * 60)

    start = time.time()

    async def main():
        # 测试基础评分
        passed, failed, errors = await batch_score_stocks(
            test_stocks,
            max_concurrent=3,
            timeout_per_stock=10,
            use_v4_1=False,
            filter_strategy="balanced",
        )

        print(f"\n✅ 评分完成:")
        print(f"  - 通过过滤: {len(passed)}")
        print(f"  - 未通过过滤: {len(failed)}")
        print(f"  - 评分失败: {len(errors)}")
        print(f"⏱️  耗时: {time.time() - start:.2f}s")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  评分被中断")
