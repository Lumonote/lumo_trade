"""
LLM 服务模块 - 基于配置的Provider架构

配置文件分工:
- llm_provider_config.json: 模型定义 (Provider、model_id、endpoint、description)
- llm_config.json: 用户配置 (enabled_models、api_keys)
"""

import json
import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import requests


class LLMConfig:
    """LLM 配置管理 - 分离通用配置和用户配置"""

    def __init__(self, config_path: Optional[Path] = None, provider_config_path: Optional[Path] = None):
        # 用户配置路径
        if config_path is None:
            config_dir = os.environ.get('KRONOS_CONFIG_DIR')
            if config_dir:
                self.config_path = Path(config_dir) / 'llm_config.json'
            else:
                self.config_path = Path(__file__).parent.parent / 'config' / 'llm_config.json'
        else:
            self.config_path = Path(config_path)

        # 通用配置路径
        if provider_config_path is None:
            self.provider_config_path = Path(__file__).parent.parent / 'config' / 'llm_provider_config.json'
        else:
            self.provider_config_path = Path(provider_config_path)

        self.config = self.load_user_config()
        self.provider_config = self.load_provider_config()

    def load_user_config(self) -> Dict:
        """加载用户配置 (enabled_models, api_keys)"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return json.loads(self._strip_json_comments(text))
            except Exception as e:
                print(f"加载用户配置失败: {e}")
        return {"enabled_models": [], "api_keys": {}}

    @staticmethod
    def _strip_json_comments(text: str) -> str:
        result = []
        in_string = False
        escaped = False
        index = 0
        while index < len(text):
            char = text[index]
            next_char = text[index + 1] if index + 1 < len(text) else ''
            if in_string:
                result.append(char)
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    in_string = False
                index += 1
                continue
            if char == '"':
                in_string = True
                result.append(char)
                index += 1
                continue
            if char == '/' and next_char == '/':
                while index < len(text) and text[index] not in '\r\n':
                    index += 1
                continue
            result.append(char)
            index += 1
        return ''.join(result)

    def load_provider_config(self) -> Dict:
        """加载通用配置 (Provider、模型定义)"""
        if self.provider_config_path.exists():
            try:
                with open(self.provider_config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载通用配置失败: {e}")
        return {"providers": {}}

    def save_user_config(self, config: Dict = None):
        """保存用户配置"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            config_to_save = config or self.config
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=2, ensure_ascii=False)
            self.config = config_to_save
        except Exception as e:
            print(f"保存用户配置失败: {e}")

    def get_providers(self) -> Dict:
        """获取所有Provider配置"""
        return self.provider_config.get('providers', {})

    def get_enabled_providers(self) -> List[str]:
        """获取已启用的Provider列表"""
        return [name for name, cfg in self.get_providers().items() if cfg.get('enabled', False)]

    def get_enabled_models(self) -> List[Tuple[str, str, Dict]]:
        """获取所有启用的模型 [(provider_name, model_key, model_config), ...]"""
        enabled = self.config.get('enabled_models', [])
        enabled_set = set(enabled)

        result = []
        for provider_name, provider_cfg in self.get_providers().items():
            if not provider_cfg.get('enabled', False):
                continue
            models = provider_cfg.get('models', {})
            for model_key, model_cfg in models.items():
                model_full_key = f"{provider_name}/{model_key}"
                if model_full_key in enabled_set:
                    result.append((provider_name, model_key, model_cfg))
        return result

    def get_enabled_model_names(self) -> List[str]:
        """获取所有启用的模型名称列表"""
        return self.config.get('enabled_models', [])

    def get_enabled_llm(self) -> str:
        """Backward-compatible display name for the first enabled model."""
        enabled_models = self.get_enabled_model_names()
        return enabled_models[0] if enabled_models else ''

    def is_configured(self) -> bool:
        """检查是否已配置至少一个启用的模型"""
        return len(self.get_enabled_models()) > 0

    def set_model_enabled(self, model_full_key: str, enabled: bool):
        """设置模型启用状态"""
        enabled_models = self.config.get('enabled_models', [])
        if enabled and model_full_key not in enabled_models:
            enabled_models.append(model_full_key)
        elif not enabled and model_full_key in enabled_models:
            enabled_models.remove(model_full_key)
        self.config['enabled_models'] = enabled_models
        self.save_user_config()

    def set_api_key(self, provider_name: str, api_key: str):
        """设置Provider的API Key"""
        api_keys = self.config.get('api_keys', {})
        api_keys[provider_name] = api_key.strip()
        self.config['api_keys'] = api_keys
        self.save_user_config()

    def get_api_key(self, provider_name: str) -> str:
        """获取Provider的API Key"""
        return self.config.get('api_keys', {}).get(provider_name, '')

    def get_model_description(self, provider_name: str, model_key: str) -> str:
        """获取模型描述"""
        provider_cfg = self.get_providers().get(provider_name, {})
        models = provider_cfg.get('models', {})
        model_cfg = models.get(model_key, {})
        return model_cfg.get('description', f"{provider_name}/{model_key}")

    def get_model_info(self, model_full_key: str) -> Optional[Dict]:
        """根据完整模型key获取模型信息"""
        for provider_name, provider_cfg in self.get_providers().items():
            models = provider_cfg.get('models', {})
            for model_key, model_cfg in models.items():
                if f"{provider_name}/{model_key}" == model_full_key:
                    return {
                        'provider_name': provider_name,
                        'model_key': model_key,
                        'model_config': model_cfg,
                        'api_key': self.get_api_key(provider_name)
                    }
        return None


class LLMProvider(ABC):
    """LLM Provider 抽象基类"""

    def __init__(self, config: Dict, provider_name: str):
        self.config = config
        self.provider_name = provider_name
        self.base_url = config.get('base_url', '').rstrip('/')
        self.api_style = config.get('api_style', 'openai')

    @abstractmethod
    def call_api(self, prompt: str, model_config: Dict, max_tokens: int = 2000) -> Tuple[bool, str]:
        pass

    def _get_headers(self, api_key: str) -> Dict:
        return {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }


class OpenAIProvider(LLMProvider):
    """OpenAI兼容接口的Provider"""

    def __init__(self, config: Dict, provider_name: str):
        super().__init__(config, provider_name)

    def call_api(self, prompt: str, model_config: Dict, max_tokens: int = 2000) -> Tuple[bool, str]:
        api_key = model_config.get('api_key', '')
        if not api_key:
            return False, f"[{self.provider_name}] API Key 未配置"

        model_id = model_config.get('model_id', '')
        endpoint = model_config.get('endpoint', '/v1/chat/completions')
        url = f"{self.base_url}{endpoint}"

        timeout = model_config.get('timeout', 60)
        if isinstance(timeout, list):
            timeout = tuple(timeout)

        # 瞬时连接级错误——SSL EOF(UNEXPECTED_EOF_WHILE_READING)、连接重置、读/连超时——
        # 是网络波动而非逻辑错误。即使用户没在配置里打开 retry_enabled,也要带退避自动重试:
        # 否则一次抖动就会让整次分析失败(线上 DeepSeek 官方报错即此类)。
        # HTTP 4xx 与解析失败是确定性结果,绝不重试。
        try:
            configured_retries = int(model_config.get('retry_times', 3))
        except (TypeError, ValueError):
            configured_retries = 3
        # 瞬时错误至少尝试 3 次(含首次),retry_times 更大则取更大值
        max_attempts = max(configured_retries, 3) if configured_retries > 0 else 3
        retry_enabled = model_config.get('retry_enabled', False)
        retry_delay = 2
        last_error = ''

        for attempt in range(max_attempts):
            is_last = attempt >= max_attempts - 1
            try:
                data = {
                    "model": model_id,
                    "messages": [
                        {"role": "system", "content": "你是一位资深的股票分析师，擅长技术分析、基本面分析和市场研判。"},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": min(max_tokens, model_config.get('max_tokens', 4096)),
                    "temperature": model_config.get('temperature', 0.7)
                }

                response = requests.post(
                    url, headers=self._get_headers(api_key), json=data, timeout=timeout
                )

                if response.status_code == 400:
                    return False, f"[{self.provider_name}] API请求错误: {response.text}"

                response.raise_for_status()
                result = response.json()
                return self._parse_response(result)

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                # ConnectionError 同时覆盖 SSLError(含 UNEXPECTED_EOF)、连接重置、代理错误、ConnectTimeout
                last_error = self._describe_transient_error(e)
                if not is_last:
                    print(f"  ⚠️ [{self.provider_name}] 连接异常，第{attempt + 1}/{max_attempts}次重试: {last_error}")
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 15)
                    continue
                return False, (
                    f"[{self.provider_name}] API调用失败（连接异常，已重试{max_attempts}次）: {last_error}。"
                    f"多为网络波动/代理/TLS 中断，请稍后重试或检查网络与代理设置"
                )

            except requests.exceptions.RequestException as e:
                # 非连接级请求错误(如 5xx)。仅在用户显式开启 retry_enabled 时重试。
                last_error = str(e)
                if retry_enabled and not is_last:
                    print(f"  ⚠️ [{self.provider_name}] 请求失败，第{attempt + 1}/{max_attempts}次重试: {last_error}")
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 15)
                    continue
                return False, f"[{self.provider_name}] API调用失败: {last_error}"

            except Exception as e:
                return False, f"[{self.provider_name}] 未知错误: {str(e)}"

        return False, f"[{self.provider_name}] 请求失败: {last_error}"

    @staticmethod
    def _describe_transient_error(exc: Exception) -> str:
        """把瞬时网络错误压成一句可读原因。

        SSL EOF / 连接重置经 urllib3 包装后字符串极长(HTTPSConnectionPool... Caused by...),
        直接抛给用户既看不懂也刷屏;这里识别常见类型给出短提示,其余截断到首段。
        """
        text = str(exc)
        low = text.lower()
        if isinstance(exc, requests.exceptions.SSLError) or 'unexpected_eof' in low or 'eof occurred' in low:
            return 'SSL 连接被意外中断（UNEXPECTED_EOF）'
        if isinstance(exc, requests.exceptions.ProxyError) or 'proxy' in low:
            return '代理连接失败'
        if isinstance(exc, requests.exceptions.Timeout) or 'timed out' in low:
            return '请求超时'
        if 'reset by peer' in low or 'connection aborted' in low or 'connection refused' in low:
            return '连接被重置/拒绝'
        # 去掉 urllib3 的 "(Caused by ...)" 长尾,只留首段
        head = text.split('(Caused by')[0].strip()
        return head or text[:160]

    def _parse_response(self, result: Dict) -> Tuple[bool, str]:
        if result.get('choices') and len(result['choices']) > 0:
            message = result['choices'][0].get('message', {}) or {}
            content = (message.get('content') or '').strip()
            if content:
                return True, content
            # 推理模型(如 deepseek-v4-pro)在 token 预算被思维链耗尽时可能只返回 reasoning_content、
            # content 为空。正常情况 content 已含最终答案不会走到这里；此处兜底取思维链，
            # 避免把一次成功的调用误判成「API返回格式异常」。
            reasoning = (message.get('reasoning_content') or '').strip()
            if reasoning:
                return True, reasoning
        return False, f"[{self.provider_name}] API返回格式异常"


class DashScopeProvider(LLMProvider):
    """DashScope（通义千问）接口的Provider"""

    def __init__(self, config: Dict, provider_name: str):
        super().__init__(config, provider_name)

    def call_api(self, prompt: str, model_config: Dict, max_tokens: int = 2000) -> Tuple[bool, str]:
        api_key = model_config.get('api_key', '')
        if not api_key:
            return False, f"[{self.provider_name}] API Key 未配置"

        model_id = model_config.get('model_id', '')
        endpoint = model_config.get('endpoint', '/services/aigc/text-generation/generation')
        url = f"{self.base_url}{endpoint}"

        try:
            data = {
                "model": model_id,
                "input": {
                    "messages": [
                        {"role": "system", "content": "你是一位资深的股票分析师，擅长技术分析、基本面分析和市场研判。"},
                        {"role": "user", "content": prompt}
                    ]
                },
                "parameters": {
                    "max_tokens": min(max_tokens, model_config.get('max_tokens', 4096)),
                    "temperature": model_config.get('temperature', 0.7)
                }
            }

            response = requests.post(url, headers=self._get_headers(api_key), json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
            return self._parse_response(result)

        except requests.exceptions.Timeout:
            return False, f"[{self.provider_name}] 请求超时"
        except requests.exceptions.RequestException as e:
            return False, f"[{self.provider_name}] API调用失败: {str(e)}"
        except Exception as e:
            return False, f"[{self.provider_name}] 未知错误: {str(e)}"

    def _parse_response(self, result: Dict) -> Tuple[bool, str]:
        output = result.get('output') or {}
        text = output.get('text')
        if isinstance(text, str) and text.strip():
            return True, text

        choices = output.get('choices')
        if isinstance(choices, list) and choices:
            first = choices[0] or {}
            msg = first.get('message') or {}
            content = msg.get('content')
            if isinstance(content, str) and content.strip():
                return True, content

        for key in ['output_text', 'result']:
            val = result.get(key)
            if isinstance(val, str) and val.strip():
                return True, val

        return False, f"[{self.provider_name}] API返回格式异常"


class LLMProviderFactory:
    """LLM Provider 工厂类"""

    _providers = {'openai': OpenAIProvider, 'dashscope': DashScopeProvider}

    @classmethod
    def create_provider(cls, provider_name: str, provider_config: Dict) -> LLMProvider:
        api_style = provider_config.get('api_style', 'openai').lower()
        provider_class = cls._providers.get(api_style)
        if not provider_class:
            raise ValueError(f"不支持的API风格: {api_style}")
        return provider_class(provider_config, provider_name)


class LLMAnalyzer:
    """LLM 分析器"""

    def __init__(self, config: LLMConfig = None):
        self.config = config or LLMConfig()
        self._provider_cache: Dict[str, Tuple[LLMProvider, Dict]] = {}

    def _get_provider_and_model(self, provider_name: str, model_key: str) -> Tuple[Optional[LLMProvider], Optional[Dict]]:
        cache_key = f"{provider_name}:{model_key}"
        if cache_key in self._provider_cache:
            return self._provider_cache[cache_key]

        provider_cfg = self.config.get_providers().get(provider_name)
        if not provider_cfg:
            return None, None

        models = provider_cfg.get('models', {})
        model_cfg = models.get(model_key, {})

        # 合并API Key
        api_key = self.config.get_api_key(provider_name)
        model_cfg['api_key'] = api_key

        provider = LLMProviderFactory.create_provider(provider_name, provider_cfg)
        self._provider_cache[cache_key] = (provider, model_cfg)
        return provider, model_cfg

    def analyze_stock(self, stock_data: Dict, model_full_key: str = None) -> Tuple[bool, Dict]:
        """分析股票"""
        prompt = self._build_analysis_prompt(stock_data)

        # 获取启用的模型
        if model_full_key:
            info = self.config.get_model_info(model_full_key)
            if not info:
                return False, {"error": f"模型 {model_full_key} 未找到"}
            provider_name = info['provider_name']
            model_key = info['model_key']
        else:
            enabled = self.config.get_enabled_models()
            if not enabled:
                return False, {"error": "未配置任何启用的模型"}
            provider_name, model_key, _ = enabled[0]
            model_full_key = f"{provider_name}/{model_key}"

        provider, model_cfg = self._get_provider_and_model(provider_name, model_key)
        if not provider:
            return False, {"error": f"模型 {model_full_key} 未配置"}

        if not model_cfg.get('api_key'):
            return False, {"error": f"模型 {model_full_key} 未配置 API Key"}

        success, result = provider.call_api(prompt, model_cfg, max_tokens=3000)

        if not success:
            return False, {"error": result}

        parsed_result = self.parse_llm_response(result)
        if parsed_result is None:
            return False, {"error": "LLM返回的数据格式无效"}

        parsed_result['llm_model'] = model_key
        return True, parsed_result

    def analyze_stock_multi_model(self, stock_data: Dict, model_keys: List[str] = None) -> Dict:
        """多模型分析"""
        prompt = self._build_analysis_prompt(stock_data)

        if model_keys is None:
            model_keys = self.config.get_enabled_model_names()

        if not model_keys:
            return {"error": "未配置任何启用的模型"}

        results = {}

        for model_full_key in model_keys:
            info = self.config.get_model_info(model_full_key)
            if not info:
                results[model_full_key] = {'llm_model': model_full_key, 'error': "模型未找到"}
                continue

            provider_name = info['provider_name']
            model_key = info['model_key']
            model_cfg = info['model_config']
            model_cfg['api_key'] = info['api_key']

            # 从provider配置中获取默认超时
            provider_cfg = self.config.get_providers().get(provider_name, {})
            if 'timeout' not in model_cfg:
                default_timeout = provider_cfg.get('default_timeout', 90)
                model_cfg['timeout'] = default_timeout

            provider = LLMProviderFactory.create_provider(provider_name, provider_cfg)

            if not model_cfg.get('api_key'):
                results[model_full_key] = {'llm_model': model_key, 'error': "未配置 API Key"}
                continue

            success, raw = provider.call_api(prompt, model_cfg, max_tokens=3000)

            if success:
                parsed = self.parse_llm_response(raw)
                if parsed:
                    parsed['llm_model'] = model_key
                    results[model_full_key] = parsed
                else:
                    results[model_full_key] = {'llm_model': model_key, 'error': "返回数据无法解析"}
            else:
                results[model_full_key] = {'llm_model': model_key, 'error': raw}

        return results if results else {"error": "所有模型调用失败"}

    def parse_llm_response(self, llm_text: str):
        """解析LLM返回的JSON"""
        try:
            import re
            json_pattern = r'```json\s*(.*?)\s*```'
            matches = re.findall(json_pattern, llm_text, re.DOTALL)

            if matches:
                json_str = matches[0]
            else:
                json_pattern2 = r'\{[\s\S]*\}'
                matches2 = re.findall(json_pattern2, llm_text)
                if matches2:
                    json_str = matches2[0]
                else:
                    return None

            result = json.loads(json_str)
            required_fields = ['kline_prediction', 'operation_advice', 'risk_assessment', 'strategy']
            if not all(field in result for field in required_fields):
                return None
            return result

        except json.JSONDecodeError:
            return None
        except Exception:
            return None

    def extract_predicted_kline(self, llm_analysis: Dict):
        """从LLM分析结果中提取K线预测数据"""
        import pandas as pd

        if not llm_analysis or 'kline_prediction' not in llm_analysis:
            return None

        predictions = llm_analysis['kline_prediction'].get('predictions', [])
        if not predictions:
            return None

        predicted_data = []
        for pred in predictions:
            predicted_data.append({
                'date': pred.get('date', ''),
                'open': pred.get('open'),
                'high': pred.get('high'),
                'low': pred.get('low'),
                'close': pred.get('close'),
                'change_pct': pred.get('change_pct')
            })

        return pd.DataFrame(predicted_data) if predicted_data else None

    def _build_analysis_prompt(self, stock_data: Dict) -> str:
        """构建分析提示词"""
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

        if 'kline_data' in stock_data:
            prompt += f"## 历史K线数据\n{stock_data['kline_data']}\n\n"
        if 'technical_analysis' in stock_data:
            prompt += f"## 技术面分析\n{stock_data['technical_analysis']}\n\n"
        if 'fundamental_data' in stock_data:
            prompt += f"## 基本面数据\n{stock_data['fundamental_data']}\n\n"
        if 'news_sentiment' in stock_data:
            prompt += f"## 消息面分析\n{stock_data['news_sentiment']}\n\n"

        prompt += """## 分析要求
请严格按照以下JSON格式输出分析结果：

```json
{
  "kline_prediction": {
    "predictions": [
      {"day": 1, "date": "2025-11-01", "open": 12.50, "high": 13.20, "low": 12.30, "close": 13.00, "change_pct": 4.0}
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
    "risk_points": ["短期超买风险"],
    "risk_level": "中",
    "overall_score": 60
  },
  "strategy": {
    "short_term": "回调买入",
    "mid_term": "目标13.50-14.00",
    "position_strategy": "首次建仓30%"
  },
  "summary": "综合分析认为..."
}
```

请严格按照JSON格式输出。"""
        return prompt

    def interpret_stock_markdown(
        self,
        payload: Dict,
        model_full_key: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[int]]:
        """Call LLM provider and return (success, raw_markdown, total_tokens).

        Unlike analyze_stock() which JSON-parses the response, this returns the
        provider's raw text. Token usage may be None if the provider doesn't
        report it (best-effort extraction).
        """
        prompt = (payload or {}).get("prompt") or ""
        if not prompt:
            return False, "prompt 为空", None
        try:
            ok, text, usage = self._call_provider_raw(prompt, model_full_key, max_tokens=3000)
        except Exception as exc:  # noqa: BLE001
            return False, f"LLM 调用异常：{exc}", None
        tokens: Optional[int] = None
        if isinstance(usage, dict):
            for key in ("total_tokens", "totalTokens", "total"):
                if key in usage and isinstance(usage[key], (int, float)):
                    tokens = int(usage[key])
                    break
        return ok, text, tokens

    def _call_provider_raw(
        self,
        prompt: str,
        model_full_key: Optional[str],
        max_tokens: int = 3000,
    ) -> Tuple[bool, str, Optional[Dict]]:
        """Provider-agnostic raw call returning (success, text, usage_dict_or_None).

        Best-effort token tracking: providers in this codebase return Tuple[bool, str]
        without usage info, so usage is typically None. Tests stub this method
        directly so they can inject usage dicts.
        """
        # Resolve enabled model
        if model_full_key:
            info = self.config.get_model_info(model_full_key)
            if not info:
                return False, f"模型 {model_full_key} 未找到", None
            provider_name = info['provider_name']
            model_key = info['model_key']
        else:
            enabled = self.config.get_enabled_models()
            if not enabled:
                return False, "未配置任何启用的模型", None
            provider_name, model_key, _ = enabled[0]

        try:
            provider, model_cfg = self._get_provider_and_model(provider_name, model_key)
        except Exception as exc:  # noqa: BLE001
            return False, f"模型解析失败：{exc}", None
        if provider is None or model_cfg is None:
            return False, f"模型 {provider_name}/{model_key} 未配置", None
        if not model_cfg.get('api_key'):
            return False, f"模型 {provider_name}/{model_key} 未配置 API Key", None

        try:
            result = provider.call_api(prompt, model_cfg, max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001
            return False, f"provider 调用失败：{exc}", None
        # Provider may return (success, text) or (success, text, usage) — normalize
        if isinstance(result, tuple) and len(result) >= 2:
            success = bool(result[0])
            text = str(result[1]) if result[1] is not None else ""
            usage = result[2] if len(result) >= 3 and isinstance(result[2], dict) else None
            return success, text, usage
        return False, "provider 返回格式异常", None


def main():
    """测试"""
    print("=== LLM 配置测试 ===\n")

    config = LLMConfig()
    print(f"用户配置: {config.config_path}")
    print(f"通用配置: {config.provider_config_path}")

    print(f"\n✅ 已启用模型:")
    for provider, model_key, model_cfg in config.get_enabled_models():
        desc = model_cfg.get('description', '')
        api_key = config.get_api_key(provider)
        has_key = "✓" if api_key else "✗"
        print(f"  - [{provider}] {model_key}: {desc} [API Key: {has_key}]")

    print(f"\n是否已配置: {config.is_configured()}")


if __name__ == "__main__":
    main()
