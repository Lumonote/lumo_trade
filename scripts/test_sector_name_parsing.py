#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.sector_api import _is_numeric_text, _pick_sector_name_from_stock_data


def test_is_numeric_text():
    assert _is_numeric_text('475.17') is True
    assert _is_numeric_text('-0.70') is True
    assert _is_numeric_text('+12') is True
    assert _is_numeric_text('5G通信') is False
    assert _is_numeric_text('互联网服务') is False
    assert _is_numeric_text('') is False


def test_pick_sector_name_from_stock_data():
    stock_data = {
        'f127': '475.17',
        'f100': '有色金属',
        'f58': '测试股票',
    }
    assert _pick_sector_name_from_stock_data(stock_data, ['f127', 'f100']) == '有色金属'

    stock_data2 = {
        'f127': '互联网服务',
        'f100': '0.00',
    }
    assert _pick_sector_name_from_stock_data(stock_data2, ['f127', 'f100']) == '互联网服务'

    stock_data3 = {
        'f127': '0',
        'f100': '--',
        'f128': 'nan',
    }
    assert _pick_sector_name_from_stock_data(stock_data3, ['f127', 'f100', 'f128']) == '未知'


def main():
    test_is_numeric_text()
    test_pick_sector_name_from_stock_data()
    print('OK')


if __name__ == '__main__':
    main()
