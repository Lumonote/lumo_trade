#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from scripts.run_opportunity_discovery import OpportunityDiscovery


def test_timeout_path():
    discovery = OpportunityDiscovery(max_workers=1)
    discovery.per_stock_timeout = 1

    def slow_analyze(_stock):
        time.sleep(3)
        return {'stock_code': '000001', 'name': '慢股'}

    discovery._analyze_single_stock = slow_analyze

    started = time.time()
    result = discovery._analyze_single_stock_with_timeout({'code': '000001', 'name': '慢股'})
    elapsed = time.time() - started

    assert elapsed < 2.5, f"timeout wrapper exceeded expected duration: {elapsed:.2f}s"
    assert result['stock_code'] == '000001'
    assert result['scoring_result']['error'] == '分析超时(1s)'


def test_success_path():
    discovery = OpportunityDiscovery(max_workers=1)
    discovery.per_stock_timeout = 1

    def fast_analyze(stock):
        return {
            'stock_code': stock['code'],
            'name': stock['name'],
            'scoring_result': {'total_score': 66, 'rating': 'B'}
        }

    discovery._analyze_single_stock = fast_analyze
    result = discovery._analyze_single_stock_with_timeout({'code': '000002', 'name': '快股'})

    assert result['stock_code'] == '000002'
    assert result['name'] == '快股'
    assert result['scoring_result']['rating'] == 'B'


def main():
    test_timeout_path()
    test_success_path()
    print('OK')


if __name__ == '__main__':
    main()
