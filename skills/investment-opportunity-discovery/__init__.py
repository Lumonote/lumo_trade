#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Investment Opportunity Discovery Skill

A comprehensive multi-dimensional stock analysis and investment
opportunity discovery system for financial markets.

Usage:
    from skills.investment_opportunity_discovery import OpportunityDiscovery

    discovery = OpportunityDiscovery()
    report_path = discovery.run(limit=100)
"""

__version__ = "1.0.0"
__author__ = "Kronos Team"

from scripts.discover_opportunities import OpportunityDiscovery

__all__ = [
    'OpportunityDiscovery'
]
