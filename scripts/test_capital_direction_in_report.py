#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


from scripts.opportunity_report_generator import OpportunityReportGenerator


def _build(capital_flow_details):
    gen = OpportunityReportGenerator(output_dir='results')
    stock = {
        'scoring_result': {
            'details': {
                'advanced_analysis': {
                    'noop': True
                }
            },
            'advanced_analysis': {
                'overall_score': {'final_score': 50},
                'dimensions': {
                    'capital_flow': {
                        'details': capital_flow_details
                    }
                }
            }
        }
    }
    return gen._build_advanced_analysis_summary(stock)


def test_direction_from_trend_string_inflow():
    s = _build({'continuity': {'consecutive_inflow_days': 2, 'trend': 'inflow'}})
    assert '主力连续净流入2天' in s


def test_direction_from_trend_string_outflow():
    s = _build({'continuity': {'consecutive_outflow_days': 3, 'trend': 'outflow'}})
    assert '主力连续净流出3天' in s


def test_direction_from_numeric_net_inflow():
    s = _build({'continuity': {'consecutive_outflow_days': 1, 'trend': ''}, 'main_net_inflow': -1.0})
    assert '主力连续净流出1天' in s


def test_chip_control_and_retail_wording():
    s = _build({
        'continuity': {'consecutive_inflow_days': 2, 'trend': 'inflow'},
        'retail_ratio': 67.7,
        'data_source': 'tushare',
        'main_net_inflow': 1.0,
        'main_force_control': 60.4,
    })
    assert '散户成交额占比67.7%(tushare)' in s


def test_chip_control_display():
    gen = OpportunityReportGenerator(output_dir='results')
    stock = {
        'scoring_result': {
            'details': {
                'advanced_analysis': {
                    'noop': True
                }
            },
            'advanced_analysis': {
                'overall_score': {'final_score': 50},
                'dimensions': {
                    'chip': {
                        'details': {
                            'concentration_90': 10.0,
                            'main_force_control': 60.4,
                        }
                    }
                }
            }
        }
    }
    s = gen._build_advanced_analysis_summary(stock)
    assert '集中度10.0%' in s
    assert '控盘评分60.4/100' in s


def main():
    test_direction_from_trend_string_inflow()
    test_direction_from_trend_string_outflow()
    test_direction_from_numeric_net_inflow()
    test_chip_control_and_retail_wording()
    test_chip_control_display()
    print('OK')


if __name__ == '__main__':
    main()
