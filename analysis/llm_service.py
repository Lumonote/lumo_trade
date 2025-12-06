"""
LLM 服务模块
支持通义千问和 DeepSeek 大模型 API 调用
用于股票分析的 AI 智能预测和建议
"""

import json
import os
import re
import pandas as pd
from pathlib import Path
from typing import Dict, Optional, Tuple
import requests
from datetime import datetime


class LLMConfig:
    """LLM 配置管理类"""

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            # 默认配置路径
            self.config_path = Path(__file__).parent.parent / 'config' / 'llm_config.json'
        else:
            self.config_path = Path(config_path)

        self.config = self.load_config()

    def load_config(self) -> Dict:
        """加载配置文件"""
        if not self.config_path.exists():
            # 创建默认配置
            default_config = {
                "qwen": {
                    "enabled": False,
                    "api_key": "",
                    "model": "qwen3-max",
                    "base_url": "https://dashscope.aliyuncs.com/api/v1",
                    "register_url": "https://help.aliyun.com/zh/dashscope/developer-reference/activate-dashscope-and-create-an-api-key",
                    "description": "阿里云通义千问大模型"
                },
                "deepseek": {
                    "enabled": False,
                    "api_key": "",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com",
                    "register_url": "https://platform.deepseek.com/api_keys",
                    "description": "DeepSeek 大模型"
                }
            }
            self.save_config(default_config)
            return default_config

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载配置失败: {e}")
            return {}

    def save_config(self, config: Dict):
        """保存配置文件"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self.config = config
        except Exception as e:
            print(f"保存配置失败: {e}")

    def get_enabled_llm(self) -> Optional[str]:
        """获取启用且已配置 API Key 的首选 LLM 服务

        优先返回已启用且配置了 API Key 的服务；
        若都未配置 API Key，则返回已启用的服务（用于提示）。
        """
        # 优先选择“已启用且已配置API Key”的模型
        for name in ['qwen', 'deepseek']:
            cfg = self.config.get(name, {})
            if cfg.get('enabled') and cfg.get('api_key'):
                return name

        # 其次选择“仅启用但未配置API Key”的模型（用于 UI/提示）
        for name in ['qwen', 'deepseek']:
            cfg = self.config.get(name, {})
            if cfg.get('enabled'):
                return name

        return None

    def get_enabled_llms(self) -> list:
        """获取已启用且配置了 API Key 的所有LLM服务列表"""
        enabled = []
        for name in ['qwen', 'deepseek']:
            cfg = self.config.get(name, {})
            if cfg.get('enabled') and cfg.get('api_key'):
                enabled.append(name)
        return enabled

    def is_configured(self) -> bool:
        """检查是否已配置可用的 LLM（任一启用且有 API Key 即为已配置）"""
        return len(self.get_enabled_llms()) > 0

    def update_llm_config(self, llm_name: str, enabled: bool, api_key: str = None):
        """更新 LLM 配置"""
        if llm_name not in self.config:
            return False

        self.config[llm_name]['enabled'] = enabled
        if api_key is not None:
            self.config[llm_name]['api_key'] = api_key

        self.save_config(self.config)
        return True


class LLMAnalyzer:
    """LLM 分析器 - 统一的 LLM 调用接口"""

    def __init__(self, config: LLMConfig = None):
        self.config = config or LLMConfig()
        self.llm_name = self.config.get_enabled_llm()
        self.enabled_llms = self.config.get_enabled_llms()

    def _call_qwen_api(self, prompt: str, max_tokens: int = 2000) -> Tuple[bool, str]:
        """调用通义千问 API"""
        config = self.config.config.get('qwen', {})
        api_key = config.get('api_key')

        if not api_key:
            return False, "通义千问 API Key 未配置"

        try:
            url = f"{config['base_url']}/services/aigc/text-generation/generation"
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }

            data = {
                "model": config['model'],
                "input": {
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一位资深的股票分析师，擅长技术分析、基本面分析和市场研判。"
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                },
                "parameters": {
                    "max_tokens": max_tokens,
                    "temperature": 0.7
                }
            }

            response = requests.post(url, headers=headers, json=data, timeout=30)
            response.raise_for_status()

            result = response.json()

            # 兼容不同版本的 DashScope 返回结构
            # 1) 旧版: { output: { text: "..." } }
            output = result.get('output') or {}
            text = output.get('text')
            if isinstance(text, str) and text.strip():
                return True, text

            # 2) 新版: { output: { choices: [ { message: { content: "..." } } ] } }
            choices = output.get('choices')
            if isinstance(choices, list) and choices:
                first = choices[0] or {}
                # 优先 message.content
                msg = first.get('message') or {}
                content = msg.get('content')
                if isinstance(content, str) and content.strip():
                    return True, content
                # 兼容形态: choices[0].text
                if isinstance(first.get('text'), str) and first.get('text').strip():
                    return True, first.get('text')
                # 兼容形态: message.content 为数组（富文本）
                if isinstance(content, list) and content:
                    try:
                        # 将文本片段拼接
                        parts = []
                        for seg in content:
                            if isinstance(seg, str):
                                parts.append(seg)
                            elif isinstance(seg, dict):
                                txt = seg.get('text') or seg.get('content')
                                if isinstance(txt, str):
                                    parts.append(txt)
                        joined = "\n".join(parts).strip()
                        if joined:
                            return True, joined
                    except Exception:
                        pass

            # 3) 兜底: 常见的其他字段名
            for key in [
                'output_text', 'outputText', 'result', 'data'
            ]:
                val = result.get(key)
                if isinstance(val, str) and val.strip():
                    return True, val

            # 无法识别的返回结构，回传精简后的错误信息
            try:
                compact = json.dumps(result, ensure_ascii=False)[:1200]
            except Exception:
                compact = str(result)
            return False, f"API 返回格式异常: {compact}"

        except requests.exceptions.Timeout:
            return False, "请求超时，请检查网络连接"
        except requests.exceptions.RequestException as e:
            return False, f"API 调用失败: {str(e)}"
        except Exception as e:
            return False, f"未知错误: {str(e)}"

    def _call_deepseek_api(self, prompt: str, max_tokens: int = 2000) -> Tuple[bool, str]:
        """调用 DeepSeek API (OpenAI 兼容接口)"""
        config = self.config.config.get('deepseek', {})
        api_key = config.get('api_key')

        if not api_key:
            return False, "DeepSeek API Key 未配置"

        try:
            url = f"{config['base_url']}/v1/chat/completions"
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }

            data = {
                "model": config['model'],
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一位资深的股票分析师，擅长技术分析、基本面分析和市场研判。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "max_tokens": max_tokens,
                "temperature": 0.7
            }

            # 增加超时时间到60秒，避免批量分析时Read timed out
            response = requests.post(url, headers=headers, json=data, timeout=60)
            response.raise_for_status()

            result = response.json()
            if result.get('choices') and len(result['choices']) > 0:
                return True, result['choices'][0]['message']['content']
            else:
                return False, f"API 返回格式异常: {result}"

        except requests.exceptions.Timeout:
            return False, "请求超时，请检查网络连接"
        except requests.exceptions.RequestException as e:
            return False, f"API 调用失败: {str(e)}"
        except Exception as e:
            return False, f"未知错误: {str(e)}"

    def analyze_stock(self, stock_data: Dict) -> Tuple[bool, Dict]:
        """
        综合分析股票数据

        Args:
            stock_data: 包含以下信息的字典
                - code: 股票代码
                - name: 股票名称
                - current_price: 当前价格
                - kline_data: K线数据 (最近30天)
                - technical_analysis: 技术分析结果
                - fundamental_data: 基本面数据
                - news_sentiment: 消息面数据
                - market_env: 市场环境

        Returns:
            (success, analysis_result)
        """
        if not self.config.is_configured():
            return False, {"error": "未配置或启用任何 LLM 服务"}

        # 构建分析提示词
        prompt = self._build_analysis_prompt(stock_data)

        # 若启用多个模型，则分别调用并按模型分组返回
        if len(self.enabled_llms) > 1:
            aggregated: Dict[str, Dict] = {}
            any_success = False
            # 对每个启用模型进行调用；即使失败也记录占位，便于前端显示徽章与状态
            for name in self.enabled_llms:
                if name == 'qwen':
                    success, raw = self._call_qwen_api(prompt, max_tokens=3000)
                elif name == 'deepseek':
                    success, raw = self._call_deepseek_api(prompt, max_tokens=3000)
                else:
                    success, raw = False, f"未知的 LLM 服务: {name}"

                if success:
                    parsed = self.parse_llm_response(raw)
                    if parsed is not None:
                        parsed['llm_model'] = name
                        aggregated[name] = parsed
                        any_success = True
                    else:
                        aggregated[name] = {
                            'llm_model': name,
                            'error': f"{name} 返回数据无法解析为结构化JSON",
                            'raw_text': raw
                        }
                else:
                    aggregated[name] = {
                        'llm_model': name,
                        'error': raw
                    }

            # 只要聚合结果存在，就返回成功，让前端渲染多模型版块
            if aggregated:
                return True, aggregated
            else:
                return False, {"error": "所有模型调用失败"}

        # 单模型调用（保持兼容）
        if self.llm_name == 'qwen':
            success, result = self._call_qwen_api(prompt, max_tokens=3000)
        elif self.llm_name == 'deepseek':
            success, result = self._call_deepseek_api(prompt, max_tokens=3000)
        else:
            return False, {"error": "未知的 LLM 服务"}

        if not success:
            return False, {"error": result}

        parsed_result = self.parse_llm_response(result)
        if parsed_result is None:
            return False, {"error": f"LLM 返回的数据格式无效，原始响应：\n{result}"}

        # 注入模型来源，便于前端标注
        parsed_result['llm_model'] = self.llm_name or 'unknown'
        return True, parsed_result

    def parse_llm_response(self, llm_text: str) -> Optional[Dict]:
        """
        解析 LLM 返回的 JSON 格式分析结果

        Args:
            llm_text: LLM 返回的文本

        Returns:
            解析后的字典，如果解析失败返回 None
        """
        try:
            # 尝试直接解析JSON
            import re

            # 提取JSON代码块
            json_pattern = r'```json\s*(.*?)\s*```'
            matches = re.findall(json_pattern, llm_text, re.DOTALL)

            if matches:
                json_str = matches[0]
            else:
                # 尝试查找花括号包围的JSON
                json_pattern2 = r'\{[\s\S]*\}'
                matches2 = re.findall(json_pattern2, llm_text)
                if matches2:
                    json_str = matches2[0]
                else:
                    return None

            # 解析JSON
            result = json.loads(json_str)

            # 验证必要字段
            required_fields = ['kline_prediction', 'operation_advice', 'risk_assessment', 'strategy']
            if not all(field in result for field in required_fields):
                return None

            return result

        except json.JSONDecodeError as e:
            print(f"JSON 解析错误: {e}")
            return None
        except Exception as e:
            print(f"解析 LLM 响应时发生错误: {e}")
            return None

    def extract_predicted_kline(self, llm_analysis: Dict, base_date: datetime = None) -> pd.DataFrame:
        """
        从 LLM 分析结果中提取 K 线预测数据

        Args:
            llm_analysis: LLM 分析结果字典
            base_date: 基准日期（默认为今天）

        Returns:
            包含预测 K 线数据的 DataFrame
        """
        if base_date is None:
            base_date = datetime.now()

        predictions = llm_analysis.get('kline_prediction', {}).get('predictions', [])

        if not predictions:
            return pd.DataFrame()

        # 构建 DataFrame
        df_data = []
        for pred in predictions:
            df_data.append({
                'date': pred.get('date', ''),
                'open': pred.get('open', 0),
                'high': pred.get('high', 0),
                'low': pred.get('low', 0),
                'close': pred.get('close', 0),
                'change_pct': pred.get('change_pct', 0)
            })

        df = pd.DataFrame(df_data)

        # 确保日期格式正确
        if not df.empty and 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')

        return df

    def _build_analysis_prompt(self, stock_data: Dict) -> str:
        """构建分析提示词 - 要求返回结构化JSON数据"""
        code = stock_data.get('code', '未知')
        name = stock_data.get('name', '未知')
        current_price = stock_data.get('current_price', 0)

        prompt = f"""请对股票 {name}({code}) 进行全面分析，并给出投资建议。

## 基础信息
股票代码: {code}
股票名称: {name}
当前价格: {current_price}
分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

"""

        # 添加K线数据
        if 'kline_data' in stock_data:
            kline = stock_data['kline_data']
            prompt += f"""## 历史K线数据（最近30个交易日）
{kline}

"""

        # 添加技术分析
        if 'technical_analysis' in stock_data:
            tech = stock_data['technical_analysis']
            prompt += f"""## 技术面分析
{tech}

"""

        # 添加基本面数据
        if 'fundamental_data' in stock_data:
            fund = stock_data['fundamental_data']
            prompt += f"""## 基本面数据
{fund}

"""

        # 添加消息面
        if 'news_sentiment' in stock_data:
            news = stock_data['news_sentiment']
            prompt += f"""## 消息面分析
{news}

"""

        # 添加市场环境
        if 'market_env' in stock_data:
            market = stock_data['market_env']
            prompt += f"""## 市场环境
{market}

"""

        prompt += """## 分析要求
请基于以上信息，严格按照以下JSON格式输出分析结果（必须是有效的JSON格式，方便程序解析）：

```json
{
  "kline_prediction": {
    "predictions": [
      {
        "day": 1,
        "date": "2025-11-01",
        "open": 12.50,
        "high": 13.20,
        "low": 12.30,
        "close": 13.00,
        "change_pct": 4.0
      }
    ],
    "support_levels": [12.00, 11.50],
    "resistance_levels": [13.50, 14.00],
    "trend": "上涨",
    "confidence": 0.75
  },
  "operation_advice": {
    "action": "买入",
    "suggested_price_range": "12.50-12.80",
    "position_control": "半仓",
    "target_price": "13.50-14.00",
    "stop_loss": "11.50",
    "confidence": 0.80
  },
  "risk_assessment": {
    "risk_points": ["短期超买风险", "板块调整风险"],
    "risk_level": "中",
    "overall_score": 60
  },
  "strategy": {
    "short_term": "回调至12.50-12.70区间分批买入，短线目标13.20",
    "mid_term": "目标价位13.50-14.00，分批止盈，持仓1-2周",
    "position_strategy": "首次建仓30%，回调加仓20%，突破加仓20%，保留30%机动"
  },
  "summary": "综合分析认为该股票短期趋势向上，建议在回调时分批建仓，目标价位13.50-14.00，止损11.50。注意控制仓位，关注大盘走势。"
}
```

**重要说明**：
1. predictions 数组至少包含未来5个交易日的预测数据
2. 所有价格必须基于当前价格和技术分析合理推算
3. action 只能是：买入、持有、卖出 之一
4. position_control 只能是：轻仓、半仓、重仓 之一
5. risk_level 只能是：低、中、高 之一
6. 必须输出有效的JSON格式，不要包含注释或额外说明
7. 确保所有字段都有值，不要遗漏

请严格按照以上JSON格式输出，确保JSON格式正确无误。
"""

        return prompt

    def test_connection(self) -> Tuple[bool, str]:
        """测试 LLM 连接"""
        if not self.llm_name:
            return False, "未启用任何 LLM 服务"

        test_prompt = "你好，请简单介绍一下你自己。"

        if self.llm_name == 'qwen':
            return self._call_qwen_api(test_prompt, max_tokens=100)
        elif self.llm_name == 'deepseek':
            return self._call_deepseek_api(test_prompt, max_tokens=100)
        else:
            return False, "未知的 LLM 服务"


def main():
    """测试函数"""
    # 创建配置管理器
    config = LLMConfig()

    # 创建分析器
    analyzer = LLMAnalyzer(config)

    # 测试连接
    if config.is_configured():
        success, result = analyzer.test_connection()
        print(f"连接测试: {'成功' if success else '失败'}")
        print(f"结果: {result}")
    else:
        print("请先配置 LLM 服务")


if __name__ == "__main__":
    main()
