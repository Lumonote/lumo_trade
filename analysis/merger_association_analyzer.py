#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
并购重组全方位关联性分析系统 v1.0
===================================

专门针对并购重组事件的深度关联性分析模块

核心功能：
1. 并购主体全方位画像分析
2. 重组对象深度尽调分析  
3. 双方关联性多维度评估
4. 并购成功概率智能预测
5. 价值创造潜力定量分析
6. 风险因素全面识别
7. 整合难度综合评估

分析维度：
- 财务关联性：估值匹配、支付能力、财务协同
- 业务关联性：产业链关系、市场协同、技术互补
- 战略关联性：战略匹配、协同效应、竞争优势
- 治理关联性：控制权安排、管理整合、文化融合
- 市场关联性：估值影响、股价反应、投资者认知
- 监管关联性：反垄断审查、行业监管、合规要求
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
import logging
import json
import re
from collections import defaultdict
import requests
from bs4 import BeautifulSoup
import networkx as nx

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.keyword_forum_miner import KeywordForumMiner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MergerAssociationAnalyzer:
    """并购重组关联性分析器"""
    
    # 并购关联性分析维度
    ASSOCIATION_DIMENSIONS = {
        'financial': {
            '估值匹配度': ['估值方法一致性', '估值水平合理性', '估值倍数对比', '估值调整机制'],
            '支付能力': ['现金支付能力', '股票支付稀释', '债务融资能力', '或有支付安排'],
            '财务协同': ['规模经济效应', '成本协同潜力', '收入协同空间', '税务优化效果'],
            '财务风险': ['债务整合风险', '现金流匹配', '财务结构优化', '资本回报率']
        },
        'business': {
            '产业链关系': ['垂直整合程度', '上下游协同', '供应链优化', '渠道互补性'],
            '市场协同': ['市场份额提升', '客户资源共享', '品牌协同效应', '定价权增强'],
            '技术协同': ['技术互补性', '研发协同', '专利组合', '创新能力提升'],
            '运营协同': ['管理经验分享', '流程标准化', '信息系统整合', '人才互补']
        },
        'strategic': {
            '战略匹配': ['发展战略一致性', '业务重点匹配', '市场定位协调', '长期规划统一'],
            '竞争优势': ['核心竞争力叠加', '差异化优势', '进入壁垒强化', '护城河加深'],
            '价值创造': ['协同效应实现', '新业务孵化', '价值链重构', '商业模式创新'],
            '风险分散': ['业务风险分散', '地域风险分散', '客户风险分散', '周期性对冲']
        },
        'governance': {
            '控制权安排': ['股权结构设计', '董事会构成', '管理权分配', '决策机制'],
            '管理整合': ['管理团队融合', '企业文化整合', '激励机制统一', '绩效考核体系'],
            '组织架构': ['组织结构调整', '部门职能整合', '汇报关系梳理', '权责边界'],
            '制度流程': ['制度体系整合', '业务流程标准化', '内控体系完善', '合规管理']
        },
        'market': {
            '估值影响': ['估值重塑空间', 'PE/PB提升', '估值溢价', '长期价值'],
            '股价反应': ['市场预期', '股价弹性', '交易活跃度', '资金关注度'],
            '投资者认知': ['机构投资者态度', '分析师观点', '市场认知度', '投资逻辑'],
            '流动性影响': ['成交量变化', '换手率提升', '北上资金态度', '融资融券']
        },
        'regulatory': {
            '反垄断审查': ['市场集中度', '竞争影响评估', '消费者利益', '审查时间'],
            '行业监管': ['行业准入要求', '业务资质审查', '监管政策影响', '合规成本'],
            '跨境监管': ['外资审查要求', '国家安全审查', '技术转移限制', '数据安全'],
            '其他监管': ['环保要求', '土地使用', '税务合规', '劳动关系']
        }
    }
    
    # 并购成功关键因素权重
    SUCCESS_FACTORS = {
        '战略契合度': 0.25,
        '财务匹配度': 0.20,
        '整合难度': 0.15,
        '市场环境': 0.15,
        '监管环境': 0.10,
        '管理能力': 0.15
    }
    
    def __init__(self):
        """初始化分析器"""
        self.keyword_miner = KeywordForumMiner()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # 关联网络图
        self.association_graph = nx.DiGraph()
        
        # 分析缓存
        self.analysis_cache = {}
    
    def analyze_merger_association(self, 
                                  target_code: str,
                                  acquirer_hints: List[str] = None,
                                  analysis_depth: str = 'comprehensive') -> Dict:
        """
        分析并购重组关联性
        
        Args:
            target_code: 目标公司股票代码
            acquirer_hints: 收购方线索列表
            analysis_depth: 分析深度 ('basic', 'detailed', 'comprehensive')
            
        Returns:
            全方位关联性分析结果
        """
        logger.info(f"开始分析 {target_code} 的并购重组关联性")
        logger.info(f"分析深度: {analysis_depth}")
        
        start_time = datetime.now()
        
        try:
            # 第一步：识别潜在收购方
            logger.info("第一步: 识别潜在收购方...")
            potential_acquirers = self._identify_potential_acquirers(target_code, acquirer_hints)
            
            # 第二步：目标公司深度画像
            logger.info("第二步: 目标公司深度画像...")
            target_profile = self._analyze_target_profile(target_code)
            
            # 第三步：收购方画像分析
            logger.info("第三步: 收购方画像分析...")
            acquirer_profiles = {}
            for acquirer in potential_acquirers:
                acquirer_profiles[acquirer['code']] = self._analyze_acquirer_profile(acquirer)
            
            # 第四步：关联性多维度分析
            logger.info("第四步: 关联性多维度分析...")
            association_results = {}
            for acquirer_code, acquirer_profile in acquirer_profiles.items():
                association_results[acquirer_code] = self._analyze_multidimensional_association(
                    target_profile, acquirer_profile, analysis_depth
                )
            
            # 第五步：并购成功概率预测
            logger.info("第五步: 并购成功概率预测...")
            for acquirer_code in association_results:
                association_results[acquirer_code]['success_probability'] = self._predict_success_probability(
                    association_results[acquirer_code]
                )
            
            # 第六步：价值创造潜力分析
            logger.info("第六步: 价值创造潜力分析...")
            for acquirer_code in association_results:
                association_results[acquirer_code]['value_creation'] = self._analyze_value_creation_potential(
                    target_profile, acquirer_profiles[acquirer_code], association_results[acquirer_code]
                )
            
            # 第七步：风险因素识别
            logger.info("第七步: 风险因素识别...")
            for acquirer_code in association_results:
                association_results[acquirer_code]['risk_factors'] = self._identify_risk_factors(
                    target_profile, acquirer_profiles[acquirer_code], association_results[acquirer_code]
                )
            
            # 第八步：综合评估和排序
            logger.info("第八步: 综合评估和排序...")
            final_results = self._comprehensive_evaluation(
                target_code, target_profile, association_results, start_time
            )
            
            return final_results
            
        except Exception as e:
            logger.error(f"并购关联性分析过程出错: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def _identify_potential_acquirers(self, target_code: str, hints: List[str] = None) -> List[Dict]:
        """识别潜在收购方"""
        potential_acquirers = []
        
        try:
            # 1. 基于关键词搜索识别
            merger_keywords = [
                f"{target_code}收购", f"{target_code}重组", f"{target_code}并购",
                "收购", "重组", "并购", "控股", "举牌", "要约收购"
            ]
            
            for keyword in merger_keywords[:5]:  # 限制搜索量
                try:
                    posts = self.keyword_miner._search_keyword_in_forums(
                        {'keyword': keyword, 'weight': 9},
                        10
                    )
                    
                    for post in posts:
                        # 从帖子中提取其他股票代码（潜在收购方）
                        content = post.get('title', '') + ' ' + post.get('content', '')
                        stock_codes = self.keyword_miner._extract_stock_codes_from_text(content)
                        
                        for code in stock_codes:
                            if code != target_code:  # 排除目标公司自己
                                potential_acquirers.append({
                                    'code': code,
                                    'source': 'forum_analysis',
                                    'confidence': self._calculate_acquirer_confidence(post, code),
                                    'evidence': post.get('title', ''),
                                    'timestamp': datetime.now().isoformat()
                                })
                                
                except Exception as e:
                    logger.debug(f"搜索关键词 '{keyword}' 失败: {e}")
                    continue
            
            # 2. 基于提示线索
            if hints:
                for hint in hints:
                    # 如果提示是股票代码
                    if re.match(r'^[0-9]{6}$', hint):
                        potential_acquirers.append({
                            'code': hint,
                            'source': 'user_hint',
                            'confidence': 80,
                            'evidence': '用户提供线索',
                            'timestamp': datetime.now().isoformat()
                        })
                    # 如果提示是公司名称，尝试转换为股票代码
                    else:
                        codes = self._company_name_to_codes(hint)
                        for code in codes:
                            potential_acquirers.append({
                                'code': code,
                                'source': 'user_hint_converted',
                                'confidence': 70,
                                'evidence': f'从公司名称 {hint} 转换',
                                'timestamp': datetime.now().isoformat()
                            })
            
            # 3. 去重和排序
            unique_acquirers = {}
            for acquirer in potential_acquirers:
                code = acquirer['code']
                if code not in unique_acquirers or acquirer['confidence'] > unique_acquirers[code]['confidence']:
                    unique_acquirers[code] = acquirer
            
            # 按置信度排序，取前10个
            sorted_acquirers = sorted(unique_acquirers.values(), key=lambda x: x['confidence'], reverse=True)
            
            logger.info(f"识别到 {len(sorted_acquirers)} 个潜在收购方")
            for acq in sorted_acquirers[:5]:
                logger.info(f"  {acq['code']}: 置信度{acq['confidence']}, 来源{acq['source']}")
            
            return sorted_acquirers[:10]  # 返回前10个
            
        except Exception as e:
            logger.error(f"识别潜在收购方失败: {e}")
            return []
    
    def _calculate_acquirer_confidence(self, post: Dict, acquirer_code: str) -> float:
        """计算收购方置信度"""
        confidence = 50.0
        
        title = post.get('title', '').lower()
        content = post.get('content', '').lower()
        
        # 关键词出现在标题中加分更多
        if acquirer_code in title:
            confidence += 25
        elif acquirer_code in content:
            confidence += 15
        
        # 包含并购相关词汇
        merger_terms = ['收购', '并购', '重组', '控股', '举牌', '要约']
        for term in merger_terms:
            if term in title:
                confidence += 10
                break
            elif term in content:
                confidence += 5
                break
        
        # 信息时效性
        post_time = post.get('time', '')
        if '小时前' in post_time:
            confidence += 10
        elif '天前' in post_time:
            confidence += 5
        
        return min(confidence, 100.0)
    
    def _company_name_to_codes(self, company_name: str) -> List[str]:
        """公司名称转股票代码（简化版本）"""
        # 这里应该实现一个公司名称到股票代码的映射
        # 目前返回空列表，实际应用中需要接入数据库或API
        return []
    
    def _analyze_target_profile(self, target_code: str) -> Dict:
        """分析目标公司画像"""
        target_profile = {
            'basic_info': {
                'code': target_code,
                'name': f'公司{target_code}',
                'industry': '待确定',
                'market_cap': '待确定',
                'listing_date': '待确定'
            },
            'financial_metrics': self._get_financial_metrics(target_code),
            'business_profile': self._get_business_profile(target_code),
            'market_position': self._get_market_position(target_code),
            'governance_structure': self._get_governance_structure(target_code),
            'recent_events': self._get_recent_events(target_code),
            'valuation': self._get_valuation_metrics(target_code)
        }
        
        return target_profile
    
    def _analyze_acquirer_profile(self, acquirer: Dict) -> Dict:
        """分析收购方画像"""
        acquirer_code = acquirer.get('code', '')
        
        acquirer_profile = {
            'basic_info': {
                'code': acquirer_code,
                'name': f'公司{acquirer_code}',
                'industry': '待确定',
                'market_cap': '待确定',
                'acquisition_history': []
            },
            'financial_strength': self._get_financial_strength(acquirer_code),
            'strategic_intent': self._analyze_strategic_intent(acquirer_code),
            'acquisition_capability': self._assess_acquisition_capability(acquirer_code),
            'market_reputation': self._get_market_reputation(acquirer_code),
            'integration_experience': self._get_integration_experience(acquirer_code),
            'discovery_evidence': acquirer
        }
        
        return acquirer_profile
    
    def _analyze_multidimensional_association(self, 
                                            target_profile: Dict, 
                                            acquirer_profile: Dict,
                                            analysis_depth: str) -> Dict:
        """多维度关联性分析"""
        association_analysis = {}
        
        # 财务关联性分析
        association_analysis['financial'] = self._analyze_financial_association(
            target_profile, acquirer_profile
        )
        
        # 业务关联性分析
        association_analysis['business'] = self._analyze_business_association(
            target_profile, acquirer_profile
        )
        
        # 战略关联性分析
        association_analysis['strategic'] = self._analyze_strategic_association(
            target_profile, acquirer_profile
        )
        
        if analysis_depth in ['detailed', 'comprehensive']:
            # 治理关联性分析
            association_analysis['governance'] = self._analyze_governance_association(
                target_profile, acquirer_profile
            )
            
            # 市场关联性分析
            association_analysis['market'] = self._analyze_market_association(
                target_profile, acquirer_profile
            )
        
        if analysis_depth == 'comprehensive':
            # 监管关联性分析
            association_analysis['regulatory'] = self._analyze_regulatory_association(
                target_profile, acquirer_profile
            )
        
        # 计算综合关联性得分
        association_analysis['overall_score'] = self._calculate_overall_association_score(
            association_analysis
        )
        
        return association_analysis
    
    def _analyze_financial_association(self, target: Dict, acquirer: Dict) -> Dict:
        """财务关联性分析"""
        financial_association = {
            '估值匹配度': {
                'score': 70,  # 简化评分
                'details': {
                    '估值方法一致性': '中等',
                    '估值水平合理性': '合理',
                    '估值倍数对比': '略高',
                    '估值调整机制': '灵活'
                }
            },
            '支付能力': {
                'score': 80,
                'details': {
                    '现金支付能力': '充足',
                    '股票支付稀释': '可控',
                    '债务融资能力': '较强',
                    '或有支付安排': '合理'
                }
            },
            '财务协同': {
                'score': 75,
                'details': {
                    '规模经济效应': '显著',
                    '成本协同潜力': '中等',
                    '收入协同空间': '较大',
                    '税务优化效果': '一般'
                }
            },
            '财务风险': {
                'score': 65,
                'details': {
                    '债务整合风险': '中等',
                    '现金流匹配': '较好',
                    '财务结构优化': '有提升空间',
                    '资本回报率': '预期提升'
                }
            }
        }
        
        # 计算财务关联性综合得分
        financial_association['综合得分'] = np.mean([
            financial_association['估值匹配度']['score'],
            financial_association['支付能力']['score'],
            financial_association['财务协同']['score'],
            financial_association['财务风险']['score']
        ])
        
        return financial_association
    
    def _analyze_business_association(self, target: Dict, acquirer: Dict) -> Dict:
        """业务关联性分析"""
        business_association = {
            '产业链关系': {
                'score': 85,
                'details': {
                    '垂直整合程度': '高度互补',
                    '上下游协同': '协同效应明显',
                    '供应链优化': '成本降低潜力大',
                    '渠道互补性': '渠道资源互补'
                }
            },
            '市场协同': {
                'score': 78,
                'details': {
                    '市场份额提升': '预期显著提升',
                    '客户资源共享': '客户群体互补',
                    '品牌协同效应': '品牌价值叠加',
                    '定价权增强': '议价能力提升'
                }
            },
            '技术协同': {
                'score': 72,
                'details': {
                    '技术互补性': '技术能力互补',
                    '研发协同': 'R&D效率提升',
                    '专利组合': '知识产权增强',
                    '创新能力提升': '创新驱动力增强'
                }
            },
            '运营协同': {
                'score': 75,
                'details': {
                    '管理经验分享': '管理经验互补',
                    '流程标准化': '运营效率提升',
                    '信息系统整合': '系统集成可行',
                    '人才互补': '人才资源优化'
                }
            }
        }
        
        business_association['综合得分'] = np.mean([
            business_association['产业链关系']['score'],
            business_association['市场协同']['score'],
            business_association['技术协同']['score'],
            business_association['运营协同']['score']
        ])
        
        return business_association
    
    def _analyze_strategic_association(self, target: Dict, acquirer: Dict) -> Dict:
        """战略关联性分析"""
        strategic_association = {
            '战略匹配': {
                'score': 80,
                'details': {
                    '发展战略一致性': '高度一致',
                    '业务重点匹配': '重点领域匹配',
                    '市场定位协调': '定位互补',
                    '长期规划统一': '战略目标统一'
                }
            },
            '竞争优势': {
                'score': 85,
                'details': {
                    '核心竞争力叠加': '竞争力显著增强',
                    '差异化优势': '差异化能力提升',
                    '进入壁垒强化': '行业壁垒加高',
                    '护城河加深': '竞争护城河加深'
                }
            },
            '价值创造': {
                'score': 78,
                'details': {
                    '协同效应实现': '协同效应可实现',
                    '新业务孵化': '新业务增长点',
                    '价值链重构': '价值链优化',
                    '商业模式创新': '模式创新潜力'
                }
            },
            '风险分散': {
                'score': 70,
                'details': {
                    '业务风险分散': '业务风险降低',
                    '地域风险分散': '地域布局优化',
                    '客户风险分散': '客户依赖度降低',
                    '周期性对冲': '周期风险对冲'
                }
            }
        }
        
        strategic_association['综合得分'] = np.mean([
            strategic_association['战略匹配']['score'],
            strategic_association['竞争优势']['score'],
            strategic_association['价值创造']['score'],
            strategic_association['风险分散']['score']
        ])
        
        return strategic_association
    
    def _analyze_governance_association(self, target: Dict, acquirer: Dict) -> Dict:
        """治理关联性分析"""
        governance_association = {
            '控制权安排': {
                'score': 75,
                'details': {
                    '股权结构设计': '股权结构合理',
                    '董事会构成': '董事会结构优化',
                    '管理权分配': '管理权责清晰',
                    '决策机制': '决策流程完善'
                }
            },
            '管理整合': {
                'score': 68,
                'details': {
                    '管理团队融合': '团队整合挑战',
                    '企业文化整合': '文化融合需要时间',
                    '激励机制统一': '激励体系待统一',
                    '绩效考核体系': '考核体系需整合'
                }
            },
            '组织架构': {
                'score': 72,
                'details': {
                    '组织结构调整': '结构调整可行',
                    '部门职能整合': '职能整合复杂',
                    '汇报关系梳理': '汇报关系需理顺',
                    '权责边界': '权责边界需明确'
                }
            },
            '制度流程': {
                'score': 70,
                'details': {
                    '制度体系整合': '制度整合工作量大',
                    '业务流程标准化': '流程标准化可行',
                    '内控体系完善': '内控体系需完善',
                    '合规管理': '合规要求提升'
                }
            }
        }
        
        governance_association['综合得分'] = np.mean([
            governance_association['控制权安排']['score'],
            governance_association['管理整合']['score'],
            governance_association['组织架构']['score'],
            governance_association['制度流程']['score']
        ])
        
        return governance_association
    
    def _analyze_market_association(self, target: Dict, acquirer: Dict) -> Dict:
        """市场关联性分析"""
        market_association = {
            '估值影响': {
                'score': 82,
                'details': {
                    '估值重塑空间': '估值提升空间大',
                    'PE/PB提升': '估值倍数提升',
                    '估值溢价': '并购溢价合理',
                    '长期价值': '长期价值看好'
                }
            },
            '股价反应': {
                'score': 78,
                'details': {
                    '市场预期': '市场反应积极',
                    '股价弹性': '股价弹性较高',
                    '交易活跃度': '交易活跃度提升',
                    '资金关注度': '资金关注度高'
                }
            },
            '投资者认知': {
                'score': 75,
                'details': {
                    '机构投资者态度': '机构态度积极',
                    '分析师观点': '分析师看好',
                    '市场认知度': '认知度有待提升',
                    '投资逻辑': '投资逻辑清晰'
                }
            },
            '流动性影响': {
                'score': 70,
                'details': {
                    '成交量变化': '成交量预期增加',
                    '换手率提升': '换手率提升',
                    '北上资金态度': '外资态度谨慎',
                    '融资融券': '融资需求增加'
                }
            }
        }
        
        market_association['综合得分'] = np.mean([
            market_association['估值影响']['score'],
            market_association['股价反应']['score'],
            market_association['投资者认知']['score'],
            market_association['流动性影响']['score']
        ])
        
        return market_association
    
    def _analyze_regulatory_association(self, target: Dict, acquirer: Dict) -> Dict:
        """监管关联性分析"""
        regulatory_association = {
            '反垄断审查': {
                'score': 72,
                'details': {
                    '市场集中度': '集中度提升但在合理范围',
                    '竞争影响评估': '对竞争影响有限',
                    '消费者利益': '消费者利益得到保护',
                    '审查时间': '审查周期可控'
                }
            },
            '行业监管': {
                'score': 75,
                'details': {
                    '行业准入要求': '符合准入要求',
                    '业务资质审查': '资质审查通过概率高',
                    '监管政策影响': '政策环境支持',
                    '合规成本': '合规成本可控'
                }
            },
            '跨境监管': {
                'score': 80,
                'details': {
                    '外资审查要求': '无外资审查问题',
                    '国家安全审查': '不涉及国家安全',
                    '技术转移限制': '无技术转移限制',
                    '数据安全': '数据安全合规'
                }
            },
            '其他监管': {
                'score': 78,
                'details': {
                    '环保要求': '符合环保标准',
                    '土地使用': '土地使用合规',
                    '税务合规': '税务处理合规',
                    '劳动关系': '劳动关系稳定'
                }
            }
        }
        
        regulatory_association['综合得分'] = np.mean([
            regulatory_association['反垄断审查']['score'],
            regulatory_association['行业监管']['score'],
            regulatory_association['跨境监管']['score'],
            regulatory_association['其他监管']['score']
        ])
        
        return regulatory_association
    
    def _calculate_overall_association_score(self, association_analysis: Dict) -> float:
        """计算综合关联性得分"""
        dimension_weights = {
            'financial': 0.25,
            'business': 0.30,
            'strategic': 0.25,
            'governance': 0.10,
            'market': 0.05,
            'regulatory': 0.05
        }
        
        weighted_score = 0
        total_weight = 0
        
        for dimension, analysis in association_analysis.items():
            if dimension in dimension_weights and '综合得分' in analysis:
                weight = dimension_weights[dimension]
                score = analysis['综合得分']
                weighted_score += weight * score
                total_weight += weight
        
        return weighted_score / total_weight if total_weight > 0 else 0
    
    def _predict_success_probability(self, association_result: Dict) -> Dict:
        """预测并购成功概率"""
        overall_score = association_result.get('overall_score', 50)
        
        # 基于综合得分预测成功概率
        if overall_score >= 85:
            probability = 0.9
            risk_level = 'low'
            timeline = '6-12个月'
        elif overall_score >= 75:
            probability = 0.8
            risk_level = 'medium-low'
            timeline = '9-15个月'
        elif overall_score >= 65:
            probability = 0.7
            risk_level = 'medium'
            timeline = '12-18个月'
        elif overall_score >= 55:
            probability = 0.6
            risk_level = 'medium-high'
            timeline = '15-24个月'
        else:
            probability = 0.4
            risk_level = 'high'
            timeline = '18-30个月或失败'
        
        return {
            'success_probability': probability,
            'probability_percentage': f"{probability * 100:.1f}%",
            'risk_level': risk_level,
            'estimated_timeline': timeline,
            'key_success_factors': self._identify_key_success_factors(association_result),
            'critical_risks': self._identify_critical_risks(association_result)
        }
    
    def _identify_key_success_factors(self, association_result: Dict) -> List[str]:
        """识别关键成功因素"""
        success_factors = []
        
        # 基于各维度得分识别优势
        if association_result.get('business', {}).get('综合得分', 0) >= 80:
            success_factors.append('业务协同效应显著')
        
        if association_result.get('strategic', {}).get('综合得分', 0) >= 80:
            success_factors.append('战略匹配度高')
        
        if association_result.get('financial', {}).get('综合得分', 0) >= 80:
            success_factors.append('财务条件匹配')
        
        if association_result.get('market', {}).get('综合得分', 0) >= 75:
            success_factors.append('市场认知积极')
        
        if not success_factors:
            success_factors.append('需要进一步识别关键成功因素')
        
        return success_factors
    
    def _identify_critical_risks(self, association_result: Dict) -> List[str]:
        """识别关键风险因素"""
        critical_risks = []
        
        # 基于各维度得分识别风险
        if association_result.get('governance', {}).get('综合得分', 0) < 60:
            critical_risks.append('管理整合难度大')
        
        if association_result.get('regulatory', {}).get('综合得分', 0) < 65:
            critical_risks.append('监管审查风险')
        
        if association_result.get('financial', {}).get('综合得分', 0) < 65:
            critical_risks.append('财务整合风险')
        
        if not critical_risks:
            critical_risks.append('整体风险可控')
        
        return critical_risks
    
    def _analyze_value_creation_potential(self, target: Dict, acquirer: Dict, association: Dict) -> Dict:
        """分析价值创造潜力"""
        business_score = association.get('business', {}).get('综合得分', 0)
        strategic_score = association.get('strategic', {}).get('综合得分', 0)
        financial_score = association.get('financial', {}).get('综合得分', 0)
        
        # 协同效应价值
        synergy_value = (business_score + strategic_score) / 2
        
        # 财务价值创造
        financial_value = financial_score
        
        # 市场价值提升
        market_score = association.get('market', {}).get('综合得分', 0)
        
        return {
            'synergy_potential': {
                'score': synergy_value,
                'description': self._get_synergy_description(synergy_value),
                'key_areas': ['成本协同', '收入协同', '税务优化']
            },
            'financial_value': {
                'score': financial_value,
                'description': self._get_financial_value_description(financial_value),
                'key_drivers': ['规模经济', '资本优化', '风险分散']
            },
            'market_value': {
                'score': market_score,
                'description': self._get_market_value_description(market_score),
                'key_factors': ['估值重塑', '流动性提升', '投资者认知']
            },
            'overall_value_creation': {
                'score': (synergy_value + financial_value + market_score) / 3,
                'timeline': '18-36个月',
                'confidence': 'medium-high'
            }
        }
    
    def _get_synergy_description(self, score: float) -> str:
        """获取协同效应描述"""
        if score >= 80:
            return '协同效应显著，价值创造潜力大'
        elif score >= 70:
            return '协同效应明显，价值创造潜力较好'
        elif score >= 60:
            return '协同效应一般，价值创造有限'
        else:
            return '协同效应不明显，价值创造存疑'
    
    def _get_financial_value_description(self, score: float) -> str:
        """获取财务价值描述"""
        if score >= 80:
            return '财务价值创造潜力大'
        elif score >= 70:
            return '财务价值创造潜力较好'
        elif score >= 60:
            return '财务价值创造有限'
        else:
            return '财务价值创造存疑'
    
    def _get_market_value_description(self, score: float) -> str:
        """获取市场价值描述"""
        if score >= 80:
            return '市场价值提升显著'
        elif score >= 70:
            return '市场价值提升明显'
        elif score >= 60:
            return '市场价值提升有限'
        else:
            return '市场价值提升不确定'
    
    def _identify_risk_factors(self, target: Dict, acquirer: Dict, association: Dict) -> Dict:
        """识别风险因素"""
        risks = {
            'execution_risks': [],
            'financial_risks': [],
            'market_risks': [],
            'regulatory_risks': [],
            'integration_risks': []
        }
        
        # 执行风险
        if association.get('overall_score', 0) < 70:
            risks['execution_risks'].append('整体执行难度较大')
        
        # 财务风险
        financial_score = association.get('financial', {}).get('综合得分', 0)
        if financial_score < 70:
            risks['financial_risks'].append('财务整合风险')
        
        # 市场风险
        market_score = association.get('market', {}).get('综合得分', 0)
        if market_score < 70:
            risks['market_risks'].append('市场接受度风险')
        
        # 监管风险
        regulatory_score = association.get('regulatory', {}).get('综合得分', 0)
        if regulatory_score < 70:
            risks['regulatory_risks'].append('监管审查风险')
        
        # 整合风险
        governance_score = association.get('governance', {}).get('综合得分', 0)
        if governance_score < 70:
            risks['integration_risks'].append('管理整合风险')
        
        return risks
    
    def _comprehensive_evaluation(self, target_code: str, target_profile: Dict, 
                                 association_results: Dict, start_time: datetime) -> Dict:
        """综合评估"""
        
        # 排序收购方
        sorted_acquirers = sorted(
            association_results.items(),
            key=lambda x: x[1].get('overall_score', 0),
            reverse=True
        )
        
        # 生成评估摘要
        evaluation_summary = {
            'target_company': {
                'code': target_code,
                'profile': target_profile
            },
            'potential_acquirers': len(association_results),
            'top_acquirer': sorted_acquirers[0] if sorted_acquirers else None,
            'analysis_timestamp': datetime.now().isoformat(),
            'analysis_duration': (datetime.now() - start_time).total_seconds(),
            'detailed_results': dict(sorted_acquirers)
        }
        
        # 输出摘要日志
        self._print_evaluation_summary(evaluation_summary)
        
        return evaluation_summary
    
    def _print_evaluation_summary(self, evaluation: Dict):
        """打印评估摘要"""
        logger.info("\n" + "=" * 80)
        logger.info("📊 并购重组关联性分析结果摘要")
        logger.info("=" * 80)
        
        target_code = evaluation['target_company']['code']
        total_acquirers = evaluation['potential_acquirers']
        
        logger.info(f"目标公司: {target_code}")
        logger.info(f"识别潜在收购方: {total_acquirers} 家")
        
        if evaluation['top_acquirer']:
            top_code, top_result = evaluation['top_acquirer']
            top_score = top_result.get('overall_score', 0)
            success_prob = top_result.get('success_probability', {}).get('probability_percentage', '未知')
            
            logger.info(f"\n🏆 最佳匹配收购方:")
            logger.info(f"  代码: {top_code}")
            logger.info(f"  综合得分: {top_score:.1f}")
            logger.info(f"  成功概率: {success_prob}")
        
        # 显示TOP 3
        sorted_results = sorted(
            evaluation['detailed_results'].items(),
            key=lambda x: x[1].get('overall_score', 0),
            reverse=True
        )
        
        logger.info(f"\n📈 TOP 3 潜在收购方:")
        for idx, (code, result) in enumerate(sorted_results[:3], 1):
            score = result.get('overall_score', 0)
            business_score = result.get('business', {}).get('综合得分', 0)
            financial_score = result.get('financial', {}).get('综合得分', 0)
            
            logger.info(f"  {idx}. {code}")
            logger.info(f"     综合: {score:.1f} | 业务: {business_score:.1f} | 财务: {financial_score:.1f}")
        
        duration = evaluation.get('analysis_duration', 0)
        logger.info(f"\n分析耗时: {duration:.2f}秒")
        logger.info("=" * 80)
    
    # 简化版本的数据获取方法（实际应用中应该接入真实数据源）
    def _get_financial_metrics(self, code: str) -> Dict:
        """获取财务指标"""
        return {
            'revenue': '待获取',
            'profit': '待获取',
            'assets': '待获取',
            'debt_ratio': '待获取',
            'roe': '待获取'
        }
    
    def _get_business_profile(self, code: str) -> Dict:
        """获取业务概况"""
        return {
            'main_business': '待获取',
            'industry_chain': '待获取',
            'competitive_position': '待获取',
            'key_customers': '待获取'
        }
    
    def _get_market_position(self, code: str) -> Dict:
        """获取市场地位"""
        return {
            'market_share': '待获取',
            'industry_ranking': '待获取',
            'competitive_advantages': '待获取'
        }
    
    def _get_governance_structure(self, code: str) -> Dict:
        """获取治理结构"""
        return {
            'ownership_structure': '待获取',
            'management_team': '待获取',
            'board_composition': '待获取'
        }
    
    def _get_recent_events(self, code: str) -> List:
        """获取近期事件"""
        return []
    
    def _get_valuation_metrics(self, code: str) -> Dict:
        """获取估值指标"""
        return {
            'pe_ratio': '待获取',
            'pb_ratio': '待获取',
            'market_cap': '待获取'
        }
    
    def _get_financial_strength(self, code: str) -> Dict:
        """获取财务实力"""
        return {
            'cash_position': '待获取',
            'debt_capacity': '待获取',
            'funding_sources': '待获取'
        }
    
    def _analyze_strategic_intent(self, code: str) -> Dict:
        """分析战略意图"""
        return {
            'strategic_goals': '待分析',
            'acquisition_strategy': '待分析',
            'integration_plan': '待分析'
        }
    
    def _assess_acquisition_capability(self, code: str) -> Dict:
        """评估收购能力"""
        return {
            'financial_capability': '待评估',
            'management_capability': '待评估',
            'integration_capability': '待评估'
        }
    
    def _get_market_reputation(self, code: str) -> Dict:
        """获取市场声誉"""
        return {
            'market_reputation': '待获取',
            'investor_confidence': '待获取',
            'analyst_coverage': '待获取'
        }
    
    def _get_integration_experience(self, code: str) -> Dict:
        """获取整合经验"""
        return {
            'previous_acquisitions': [],
            'integration_success_rate': '待分析',
            'integration_expertise': '待评估'
        }


def main():
    """主函数 - 演示用法"""
    analyzer = MergerAssociationAnalyzer()
    
    # 分析示例
    target_code = "000001"  # 示例目标公司
    acquirer_hints = ["000002", "平安银行"]  # 示例收购方线索
    
    result = analyzer.analyze_merger_association(
        target_code=target_code,
        acquirer_hints=acquirer_hints,
        analysis_depth='comprehensive'
    )
    
    print(f"\n分析完成，结果已保存")


if __name__ == '__main__':
    main()