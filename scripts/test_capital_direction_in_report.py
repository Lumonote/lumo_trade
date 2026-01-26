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
    assert '主力连续2天(买入)' in s


def test_direction_from_trend_string_outflow():
    s = _build({'continuity': {'consecutive_inflow_days': 3, 'trend': 'outflow'}})
    assert '主力连续3天(卖出)' in s


def test_direction_from_numeric_net_inflow():
    s = _build({'continuity': {'consecutive_inflow_days': 1, 'trend': ''}, 'main_net_inflow': -1.0})
    assert '主力连续1天(卖出)' in s


def main():
    test_direction_from_trend_string_inflow()
    test_direction_from_trend_string_outflow()
    test_direction_from_numeric_net_inflow()
    print('OK')


if __name__ == '__main__':
    main()
