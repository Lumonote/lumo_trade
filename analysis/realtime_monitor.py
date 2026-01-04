#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时监控与告警系统 v1.0
========================

功能:
1. 实时监控多个数据源的投资机会
2. 基于规则的告警触发
3. 告警通知（控制台/文件/Webhook）
4. 历史记录和去重
"""

import os
import sys
import time
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from collections import deque
import hashlib

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.optimized_opportunity_discovery import OptimizedOpportunityDiscovery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class AlertRule:
    """告警规则"""

    def __init__(
        self,
        name: str,
        condition: Callable[[Dict], bool],
        priority: str = 'medium',
        cooldown_minutes: int = 30
    ):
        self.name = name
        self.condition = condition
        self.priority = priority
        self.cooldown_minutes = cooldown_minutes
        self.last_triggered = {}

    def check(self, opportunity: Dict) -> bool:
        stock_code = opportunity.get('stock_code', '')
        
        if stock_code in self.last_triggered:
            elapsed = (datetime.now() - self.last_triggered[stock_code]).total_seconds() / 60
            if elapsed < self.cooldown_minutes:
                return False

        if self.condition(opportunity):
            self.last_triggered[stock_code] = datetime.now()
            return True

        return False


class AlertNotifier:
    """告警通知器"""

    def __init__(self, output_dir: str = "alerts"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.alert_history = deque(maxlen=1000)

    def notify(self, alert: Dict):
        self.alert_history.append(alert)

        self._console_notify(alert)
        self._file_notify(alert)

    def _console_notify(self, alert: Dict):
        priority = alert.get('priority', 'medium')
        stock_code = alert.get('stock_code', '')
        rule_name = alert.get('rule_name', '')
        score = alert.get('confidence_score', 0)

        if priority == 'high':
            icon = "🚨"
        elif priority == 'medium':
            icon = "⚠️"
        else:
            icon = "📢"

        print(f"\n{icon} [{priority.upper()}] 告警: {stock_code}")
        print(f"   规则: {rule_name}")
        print(f"   置信度: {score:.1f}分")
        print(f"   时间: {alert.get('timestamp', '')}")
        print(f"   标题: {alert.get('title', '')[:50]}...")

    def _file_notify(self, alert: Dict):
        date_str = datetime.now().strftime('%Y%m%d')
        filepath = os.path.join(self.output_dir, f"alerts_{date_str}.json")

        alerts = []
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    alerts = json.load(f)
            except:
                alerts = []

        alerts.append(alert)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)


class RealtimeMonitor:
    """实时监控系统"""

    DEFAULT_RULES = [
        {
            'name': 'S级机会',
            'condition': lambda o: o.get('confidence_rating') == 'S',
            'priority': 'high',
            'cooldown': 60
        },
        {
            'name': 'A+级机会',
            'condition': lambda o: o.get('confidence_rating') == 'A+',
            'priority': 'high',
            'cooldown': 30
        },
        {
            'name': '重组消息',
            'condition': lambda o: any(cat in str(o.get('categories', [])) for cat in ['重组', '并购', '借壳']),
            'priority': 'high',
            'cooldown': 30
        },
        {
            'name': '多源验证',
            'condition': lambda o: len(o.get('sources', [])) >= 3,
            'priority': 'medium',
            'cooldown': 20
        },
        {
            'name': '高热度讨论',
            'condition': lambda o: o.get('posts_count', 0) >= 5,
            'priority': 'medium',
            'cooldown': 15
        },
        {
            'name': '内幕情报',
            'condition': lambda o: '内幕情报' in str(o.get('categories', [])),
            'priority': 'high',
            'cooldown': 60
        }
    ]

    def __init__(
        self,
        output_dir: str = "monitor_results",
        check_interval: int = 300
    ):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        self.check_interval = check_interval
        self.is_running = False
        self.monitor_thread = None

        self.discovery = OptimizedOpportunityDiscovery(output_dir)
        self.notifier = AlertNotifier(os.path.join(output_dir, "alerts"))

        self.rules = []
        self._init_default_rules()

        self.seen_opportunities = set()
        self.stats = {
            'total_checks': 0,
            'total_opportunities': 0,
            'total_alerts': 0,
            'start_time': None
        }

        logger.info("🔍 实时监控系统初始化完成")

    def _init_default_rules(self):
        for rule_config in self.DEFAULT_RULES:
            self.add_rule(
                name=rule_config['name'],
                condition=rule_config['condition'],
                priority=rule_config['priority'],
                cooldown_minutes=rule_config['cooldown']
            )

    def add_rule(
        self,
        name: str,
        condition: Callable[[Dict], bool],
        priority: str = 'medium',
        cooldown_minutes: int = 30
    ):
        rule = AlertRule(name, condition, priority, cooldown_minutes)
        self.rules.append(rule)
        logger.info(f"  ✓ 添加告警规则: {name} (优先级: {priority})")

    def start(self):
        if self.is_running:
            logger.warning("监控已在运行中")
            return

        self.is_running = True
        self.stats['start_time'] = datetime.now()

        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

        logger.info(f"🚀 实时监控已启动 (检查间隔: {self.check_interval}秒)")

    def stop(self):
        self.is_running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        logger.info("⏹️ 实时监控已停止")

    def _monitor_loop(self):
        while self.is_running:
            try:
                self._check_opportunities()
            except Exception as e:
                logger.error(f"监控检查出错: {e}")

            time.sleep(self.check_interval)

    def _check_opportunities(self):
        logger.info(f"\n🔄 [{datetime.now().strftime('%H:%M:%S')}] 执行监控检查...")

        self.stats['total_checks'] += 1

        result = self.discovery.discover_opportunities(
            keyword_limit=8,
            min_confidence=50.0,
            generate_report=False
        )

        opportunities = result.get('opportunities', [])
        self.stats['total_opportunities'] += len(opportunities)

        new_alerts = 0
        for opp in opportunities:
            opp_hash = self._get_opportunity_hash(opp)

            if opp_hash in self.seen_opportunities:
                continue

            self.seen_opportunities.add(opp_hash)

            for rule in self.rules:
                if rule.check(opp):
                    alert = self._create_alert(opp, rule)
                    self.notifier.notify(alert)
                    new_alerts += 1
                    self.stats['total_alerts'] += 1

        logger.info(f"✓ 检查完成: 发现 {len(opportunities)} 个机会, 触发 {new_alerts} 个告警")

    def _get_opportunity_hash(self, opp: Dict) -> str:
        key = f"{opp.get('stock_code', '')}_{','.join(sorted(opp.get('keywords', [])))}"
        return hashlib.md5(key.encode()).hexdigest()

    def _create_alert(self, opportunity: Dict, rule: AlertRule) -> Dict:
        return {
            'stock_code': opportunity.get('stock_code', ''),
            'stock_name': opportunity.get('stock_name', ''),
            'rule_name': rule.name,
            'priority': rule.priority,
            'confidence_score': opportunity.get('confidence_score', 0),
            'confidence_rating': opportunity.get('confidence_rating', ''),
            'categories': list(opportunity.get('categories', [])),
            'keywords': list(opportunity.get('keywords', [])),
            'sources': list(opportunity.get('sources', [])),
            'title': opportunity.get('news_title', ''),
            'timestamp': datetime.now().isoformat(),
            'posts_count': opportunity.get('posts_count', 0)
        }

    def get_stats(self) -> Dict:
        stats = self.stats.copy()
        if stats['start_time']:
            elapsed = (datetime.now() - stats['start_time']).total_seconds()
            stats['running_time_minutes'] = round(elapsed / 60, 1)
        return stats

    def run_once(self, keyword_limit: int = 15, min_confidence: float = 50.0) -> Dict:
        """单次运行监控检查"""
        logger.info("🔍 执行单次监控检查...")

        result = self.discovery.discover_opportunities(
            keyword_limit=keyword_limit,
            min_confidence=min_confidence,
            generate_report=True
        )

        opportunities = result.get('opportunities', [])
        alerts = []

        for opp in opportunities:
            for rule in self.rules:
                if rule.check(opp):
                    alert = self._create_alert(opp, rule)
                    self.notifier.notify(alert)
                    alerts.append(alert)

        result['alerts'] = alerts
        result['alert_count'] = len(alerts)

        logger.info(f"✓ 单次检查完成: {len(opportunities)} 个机会, {len(alerts)} 个告警")

        return result


def main():
    """主函数"""
    print("=" * 80)
    print("🔍 Kronos 实时监控与告警系统")
    print("=" * 80)

    print("\n选择运行模式:")
    print("  1. 单次检查")
    print("  2. 持续监控")

    try:
        mode = input("\n请选择模式 (1/2, 默认1): ").strip() or '1'

        monitor = RealtimeMonitor(
            output_dir="monitor_results",
            check_interval=300
        )

        if mode == '2':
            print("\n启动持续监控模式...")
            print("按 Ctrl+C 停止监控")

            monitor.start()

            try:
                while True:
                    time.sleep(60)
                    stats = monitor.get_stats()
                    print(f"\n📊 监控统计: 检查{stats['total_checks']}次, "
                          f"发现{stats['total_opportunities']}个机会, "
                          f"触发{stats['total_alerts']}个告警")
            except KeyboardInterrupt:
                monitor.stop()
                print("\n监控已停止")

        else:
            result = monitor.run_once(keyword_limit=15, min_confidence=50.0)

            print(f"\n✅ 检查完成!")
            print(f"   发现机会: {len(result.get('opportunities', []))}")
            print(f"   触发告警: {result.get('alert_count', 0)}")

            if result.get('reports'):
                print(f"\n📊 报告已生成:")
                for report_type, path in result['reports'].items():
                    print(f"   {report_type}: {path}")

    except KeyboardInterrupt:
        print("\n用户取消操作")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
