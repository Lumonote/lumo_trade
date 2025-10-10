#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos 数据处理模块
统一不同数据源的数据格式转换
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
import json
import re
from pathlib import Path
import logging
import os


class DataProcessor:
    """数据处理器 - 统一不同数据源的数据格式"""

    def __init__(self, config_path: str = "config/crawler_config.json"):
        """初始化数据处理器"""
        self.config = self._load_config(config_path)
        self.validation_rules = self.config.get('validation', {})
        self.data_settings = self.config.get('data_settings', {})

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"⚠️  配置文件不存在: {config_path}，使用默认配置")
            return self._get_default_config()
        except json.JSONDecodeError as e:
            print(f"⚠️  配置文件格式错误: {e}，使用默认配置")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            'validation': {
                'min_price': 0.01,
                'max_price': 10000,
                'min_volume': 0,
                'max_volume': 1000000000,
                'price_change_threshold': 0.2,
                'required_fields': ['timestamps', 'open', 'high', 'low', 'close', 'volume']
            },
            'data_settings': {
                'columns': ['timestamps', 'open', 'high', 'low', 'close', 'volume', 'amount'],
                'date_format': '%Y-%m-%d %H:%M:%S'
            }
        }

    def _standardize_csv_format(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化CSV格式，确保列名和数据格式符合示例文件要求"""
        if df is None or df.empty:
            return df

        # 列名映射 - 统一为标准格式
        column_mapping = {
            'timestamp': 'timestamps',
            'time': 'timestamps',
            'datetime': 'timestamps',
            'date': 'timestamps',
            'price': 'close',
            'current': 'close',
            'current_price': 'close',
            'vol': 'volume',
            'turnover': 'amount'
        }

        # 重命名列
        df = df.rename(columns=column_mapping)

        # 确保必需的列存在
        required_columns = ['timestamps', 'open', 'high', 'low', 'close', 'volume', 'amount']

        # 如果缺少OHLC数据，使用close价格填充
        if 'close' in df.columns:
            for col in ['open', 'high', 'low']:
                if col not in df.columns:
                    df[col] = df['close']
                    print(f"⚠️  缺少{col}列，使用close价格填充")

        # 如果缺少成交量和成交额，设为0
        if 'volume' not in df.columns:
            df['volume'] = 0
            print("⚠️  缺少volume列，设为0")

        if 'amount' not in df.columns:
            df['amount'] = 0
            print("⚠️  缺少amount列，设为0")

        # 处理时间戳格式
        if 'timestamps' in df.columns:
            try:
                # 检查时间戳数据类型和格式
                print(f"🔍 时间戳列数据类型: {df['timestamps'].dtype}")
                print(f"🔍 时间戳样本数据: {df['timestamps'].iloc[0] if len(df) > 0 else 'Empty'}")

                # 如果已经是字符串格式，直接使用
                if df['timestamps'].dtype == 'object':
                    # 尝试转换为datetime再转回字符串以标准化格式
                    df['timestamps'] = pd.to_datetime(df['timestamps'], errors='coerce')
                    # 删除转换失败的行
                    df = df.dropna(subset=['timestamps'])
                    if len(df) > 0:
                        df['timestamps'] = df['timestamps'].dt.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    # 如果是其他类型，先转换为datetime
                    df['timestamps'] = pd.to_datetime(df['timestamps'], errors='coerce')
                    df = df.dropna(subset=['timestamps'])
                    if len(df) > 0:
                        df['timestamps'] = df['timestamps'].dt.strftime('%Y-%m-%d %H:%M:%S')

                print(f"✅ 时间戳转换完成，剩余数据: {len(df)} 行")
            except Exception as e:
                print(f"⚠️  时间格式转换失败: {e}")
                import traceback
                traceback.print_exc()
        else:
            # 如果没有时间戳，使用当前时间
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            df['timestamps'] = current_time
            print("⚠️  缺少timestamps列，使用当前时间")

        # 确保列的顺序正确
        df = df[required_columns]

        # 按时间排序
        try:
            df = df.sort_values('timestamps').reset_index(drop=True)
        except:
            pass

        # 数据类型转换
        numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'amount']
        for col in numeric_columns:
            if col in df.columns:
                try:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                except:
                    df[col] = 0

        print(f"📊 数据标准化完成: {len(df)} 行 x {len(df.columns)} 列")
        print(f"📋 列名: {list(df.columns)}")

        return df

    def process_eastmoney_data(self, raw_data: Dict[str, Any], symbol: str) -> Optional[pd.DataFrame]:
        """处理东方财富数据"""
        try:
            print(f"🔍 东方财富数据处理器收到数据类型: {type(raw_data)}")

            # 检查是否是直接的实时数据格式（包含f43等字段）
            if isinstance(raw_data, dict) and 'f43' in raw_data:
                print(f"✅ 识别为东方财富实时数据格式（直接格式）")
                return self._process_eastmoney_realtime(raw_data, symbol)

            # 检查是否是包装格式（有data字段）
            if isinstance(raw_data, dict) and 'data' in raw_data and raw_data['data']:
                data = raw_data['data']
                print(f"📈 提取到的data字段类型: {type(data)}")
                print(f"🔍 data字段所有键: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")

                # 处理K线数据 - 检查是否包含klines字段
                if isinstance(data, dict) and 'klines' in data:
                    print(f"✅ 识别为K线数据格式（包含klines字段）")
                    klines = data['klines']
                    print(f"🔍 klines字段类型: {type(klines)}")
                    print(f"🔍 klines字段内容: {klines[:2] if isinstance(klines, list) and len(klines) > 0 else klines}")
                    if isinstance(klines, list):
                        if len(klines) == 0:
                            print(f"❌ klines数组为空，可能是API参数问题或数据不存在")
                            return None
                        return self._process_eastmoney_kline(klines, symbol)
                    else:
                        print(f"❌ klines字段不是列表格式: {type(klines)}")
                        return None

                # 处理实时数据
                elif isinstance(data, dict):
                    print(f"✅ 识别为实时数据格式（包装格式）")
                    return self._process_eastmoney_realtime(data, symbol)

                # 处理K线数据（直接列表格式）
                elif isinstance(data, list):
                    print(f"✅ 识别为K线数据格式（直接列表）")
                    return self._process_eastmoney_kline(data, symbol)

            print(f"❌ 未知的东方财富数据格式")
            print(f"🔑 数据键: {list(raw_data.keys()) if isinstance(raw_data, dict) else 'Not a dict'}")
            return None

        except Exception as e:
            print(f"❌ 处理东方财富数据失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _process_eastmoney_realtime(self, data: Dict[str, Any], symbol: str) -> pd.DataFrame:
        """处理东方财富实时数据"""
        # 东方财富实时数据字段映射
        # f43: 最新价, f44: 最高价, f45: 最低价, f46: 今开, f47: 成交量, f48: 成交额
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        df_data = {
            'timestamp': [current_time],
            'open': [data.get('f46', 0)],
            'high': [data.get('f44', 0)],
            'low': [data.get('f45', 0)],
            'close': [data.get('f43', 0)],
            'volume': [data.get('f47', 0)],
            'amount': [data.get('f48', 0)]
        }

        df = pd.DataFrame(df_data)
        return self._standardize_csv_format(df)

    def _process_eastmoney_kline(self, data: List[str], symbol: str) -> pd.DataFrame:
        """处理东方财富K线数据"""
        df_data = []

        for item in data:
            # 东方财富K线数据格式: "时间,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率"
            parts = item.split(',')
            if len(parts) >= 7:
                df_data.append({
                    'timestamp': parts[0],
                    'open': float(parts[1]) if parts[1] else 0,
                    'close': float(parts[2]) if parts[2] else 0,
                    'high': float(parts[3]) if parts[3] else 0,
                    'low': float(parts[4]) if parts[4] else 0,
                    'volume': float(parts[5]) if parts[5] else 0,
                    'amount': float(parts[6]) if parts[6] else 0
                })

        df = pd.DataFrame(df_data)
        return self._standardize_csv_format(df)

    def process_tonghuashun_data(self, raw_data: Union[str, Dict[str, Any]], symbol: str) -> Optional[pd.DataFrame]:
        """处理同花顺数据"""
        try:
            print(f"🔍 同花顺数据处理器接收到数据类型: {type(raw_data)}")
            print(f"🔍 同花顺数据内容: {str(raw_data)[:200]}...")

            # 处理不同格式的数据
            if isinstance(raw_data, dict):
                # 检查是否包含同花顺API的标准字段
                if 'data' in raw_data:
                    # 处理包含data字段的响应
                    data = raw_data['data']
                    print(f"🔍 提取data字段: {str(data)[:200]}...")
                    return self._process_tonghuashun_dict_data(data)
                else:
                    # 直接处理字典数据
                    print(f"🔍 处理直接字典格式数据")
                    return self._process_tonghuashun_dict_data(raw_data)
            elif not isinstance(raw_data, str):
                print(f"❌ 同花顺数据格式不支持: {type(raw_data)}")
                return None

            # 同花顺返回的是JavaScript格式，需要解析
            # 格式类似: quotebridge_v6_line_hs_000001_01_last(["时间","价格","成交量",...])

            # 提取JSON数据
            match = re.search(r'\[(.+)\]', raw_data)
            if not match:
                return None

            json_str = '[' + match.group(1) + ']'
            data = json.loads(json_str)

            if not data or len(data) < 2:
                return None

            # 第一个元素是字段名，后续是数据
            fields = data[0].split(',')
            records = data[1:]

            df_data = []
            for record in records:
                values = record.split(',')
                if len(values) >= 6:
                    df_data.append({
                        'timestamp': values[0],
                        'open': float(values[1]) if values[1] else 0,
                        'high': float(values[2]) if values[2] else 0,
                        'low': float(values[3]) if values[3] else 0,
                        'close': float(values[4]) if values[4] else 0,
                        'volume': float(values[5]) if values[5] else 0,
                        'amount': float(values[6]) if len(values) > 6 and values[6] else 0
                    })

            df = pd.DataFrame(df_data)
            return self._standardize_csv_format(df)

        except Exception as e:
            print(f"❌ 处理同花顺数据失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _process_tonghuashun_dict_data(self, data: Union[str, Dict[str, Any]]) -> Optional[pd.DataFrame]:
        """处理同花顺字典格式数据"""
        try:
            from datetime import datetime
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # 检查数据类型
            if isinstance(data, str):
                print(f"🔍 同花顺数据为字符串格式，长度: {len(data)}")
                # 解析CSV格式的数据字符串
                # 格式: 日期,开盘,最高,最低,收盘,成交量,成交额,涨跌幅,...
                lines = data.strip().split(';')
                if not lines:
                    print("❌ 同花顺数据为空")
                    return None

                # 取最后一条数据（最新数据）
                last_line = lines[-1].strip()
                if not last_line:
                    if len(lines) > 1:
                        last_line = lines[-2].strip()
                    else:
                        print("❌ 同花顺数据无有效记录")
                        return None

                print(f"🔍 解析最新数据行: {last_line}")
                fields = last_line.split(',')

                if len(fields) < 7:
                    print(f"❌ 同花顺数据字段不足: {len(fields)} < 7")
                    return None

                # 解析字段: 日期,开盘,最高,最低,收盘,成交量,成交额
                try:
                    date_str = fields[0]
                    open_price = float(fields[1]) if fields[1] else 0
                    high_price = float(fields[2]) if fields[2] else 0
                    low_price = float(fields[3]) if fields[3] else 0
                    close_price = float(fields[4]) if fields[4] else 0
                    volume = float(fields[5]) if fields[5] else 0
                    amount = float(fields[6]) if fields[6] else 0

                    # 转换日期格式
                    if len(date_str) == 8:  # YYYYMMDD
                        timestamp = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 15:00:00"
                    else:
                        timestamp = current_time

                    df_data = {
                        'timestamp': [timestamp],
                        'open': [open_price],
                        'high': [high_price],
                        'low': [low_price],
                        'close': [close_price],
                        'volume': [volume],
                        'amount': [amount]
                    }

                    print(
                        f"✅ 同花顺数据转换完成: open={open_price}, high={high_price}, low={low_price}, close={close_price}")
                    df = pd.DataFrame(df_data)
                    return self._standardize_csv_format(df)

                except (ValueError, IndexError) as e:
                    print(f"❌ 同花顺数据解析失败: {e}")
                    return None

            elif isinstance(data, dict):
                print(f"🔍 同花顺字典数据键名: {list(data.keys())}")

                # 尝试从不同可能的字段中提取数据
                price_fields = ['price', 'current', 'last_price', 'close']
                open_fields = ['open', 'open_price']
                high_fields = ['high', 'high_price', 'max']
                low_fields = ['low', 'low_price', 'min']
                volume_fields = ['volume', 'vol', 'turnover_volume']
                amount_fields = ['amount', 'turnover', 'turnover_amount']

                # 提取价格数据
                current_price = 0
                for field in price_fields:
                    if field in data and data[field] is not None:
                        current_price = float(data[field])
                        break

                open_price = current_price
                for field in open_fields:
                    if field in data and data[field] is not None:
                        open_price = float(data[field])
                        break

                high_price = current_price
                for field in high_fields:
                    if field in data and data[field] is not None:
                        high_price = float(data[field])
                        break

                low_price = current_price
                for field in low_fields:
                    if field in data and data[field] is not None:
                        low_price = float(data[field])
                        break

                volume = 0
                for field in volume_fields:
                    if field in data and data[field] is not None:
                        volume = float(data[field])
                        break

                amount = 0
                for field in amount_fields:
                    if field in data and data[field] is not None:
                        amount = float(data[field])
                        break

                df_data = {
                    'timestamp': [current_time],
                    'open': [open_price],
                    'high': [high_price],
                    'low': [low_price],
                    'close': [current_price],
                    'volume': [volume],
                    'amount': [amount]
                }

                print(
                    f"✅ 同花顺数据转换完成: open={open_price}, high={high_price}, low={low_price}, close={current_price}")
                df = pd.DataFrame(df_data)
                return self._standardize_csv_format(df)

            else:
                print(f"❌ 同花顺数据类型不支持: {type(data)}")
                return None

        except Exception as e:
            print(f"❌ 处理同花顺字典数据失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def process_xueqiu_data(self, raw_data: Dict[str, Any], symbol: str) -> Optional[pd.DataFrame]:
        """处理雪球数据"""
        try:
            # 检查是否是雪球爬虫返回的标准格式数据
            if 'current_price' in raw_data and 'source' in raw_data:
                return self._process_xueqiu_standard_format(raw_data)

            # 处理原始API响应数据
            if 'data' not in raw_data:
                return None

            data = raw_data['data']

            # 处理实时数据
            if 'quote' in data:
                return self._process_xueqiu_realtime(data['quote'], symbol)

            # 处理K线数据
            elif 'item' in data:
                return self._process_xueqiu_kline(data['item'], symbol)

            return None

        except Exception as e:
            print(f"❌ 处理雪球数据失败: {e}")
            return None

    def _process_xueqiu_standard_format(self, data: Dict[str, Any]) -> pd.DataFrame:
        """处理雪球爬虫返回的标准格式数据"""
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        df_data = {
            'timestamp': [current_time],
            'open': [data.get('open', 0)],
            'high': [data.get('high', 0)],
            'low': [data.get('low', 0)],
            'close': [data.get('current_price', 0)],
            'volume': [data.get('volume', 0)],
            'amount': [data.get('turnover', 0)]
        }

        df = pd.DataFrame(df_data)
        return self._standardize_csv_format(df)

    def _process_xueqiu_realtime(self, data: Dict[str, Any], symbol: str) -> pd.DataFrame:
        """处理雪球实时数据"""
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        df_data = {
            'timestamp': [current_time],
            'open': [data.get('open', 0)],
            'high': [data.get('high', 0)],
            'low': [data.get('low', 0)],
            'close': [data.get('current', 0)],
            'volume': [data.get('volume', 0)],
            'amount': [data.get('amount', 0)]
        }

        df = pd.DataFrame(df_data)
        return self._standardize_csv_format(df)

    def _process_xueqiu_kline(self, data: List[List], symbol: str) -> pd.DataFrame:
        """处理雪球K线数据"""
        df_data = []

        for item in data:
            # 雪球K线数据格式: [时间戳, 成交量, 开盘, 最高, 最低, 收盘, 涨跌额, 涨跌幅, 换手率, 成交额]
            if len(item) >= 10:
                timestamp = datetime.fromtimestamp(item[0] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                df_data.append({
                    'timestamp': timestamp,
                    'open': float(item[2]) if item[2] else 0,
                    'high': float(item[3]) if item[3] else 0,
                    'low': float(item[4]) if item[4] else 0,
                    'close': float(item[5]) if item[5] else 0,
                    'volume': float(item[1]) if item[1] else 0,
                    'amount': float(item[9]) if item[9] else 0
                })

        return pd.DataFrame(df_data)

    def validate_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """数据验证和清洗"""
        if df is None or df.empty:
            return df

        # 检查必需字段 - 支持timestamp和timestamps字段名
        required_fields = self.validation_rules.get('required_fields', [])
        # 创建字段映射，支持timestamp和timestamps
        field_mapping = {'timestamp': 'timestamps'}

        missing_fields = []
        for field in required_fields:
            # 检查原字段名或映射后的字段名是否存在
            mapped_field = field_mapping.get(field, field)
            if field not in df.columns and mapped_field not in df.columns:
                missing_fields.append(field)

        if missing_fields:
            print(f"⚠️  缺少必需字段: {missing_fields}")
            return pd.DataFrame()

        # 数据类型转换
        numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'amount']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 时间戳处理
        timestamp_col = 'timestamps' if 'timestamps' in df.columns else 'timestamp'
        if timestamp_col in df.columns:
            # 检查时间戳是否已经是字符串格式
            if df[timestamp_col].dtype == 'object':
                # 如果是字符串，尝试转换为datetime
                try:
                    df[timestamp_col] = pd.to_datetime(df[timestamp_col], errors='coerce')
                except:
                    print(f"⚠️  时间戳转换失败，保持原格式")
            else:
                # 如果不是字符串，直接转换
                df[timestamp_col] = pd.to_datetime(df[timestamp_col], errors='coerce')

        # 删除无效数据
        df = df.dropna(subset=[timestamp_col, 'open', 'high', 'low', 'close'])

        # 价格范围验证
        min_price = self.validation_rules.get('min_price', 0.01)
        max_price = self.validation_rules.get('max_price', 10000)

        price_columns = ['open', 'high', 'low', 'close']
        for col in price_columns:
            if col in df.columns:
                df = df[(df[col] >= min_price) & (df[col] <= max_price)]

        # 成交量范围验证
        if 'volume' in df.columns:
            min_volume = self.validation_rules.get('min_volume', 0)
            max_volume = self.validation_rules.get('max_volume', 1000000000)
            df = df[(df['volume'] >= min_volume) & (df['volume'] <= max_volume)]

        # OHLC逻辑验证
        df = df[(df['high'] >= df['low']) &
                (df['high'] >= df['open']) &
                (df['high'] >= df['close']) &
                (df['low'] <= df['open']) &
                (df['low'] <= df['close'])]

        # 按时间排序
        timestamp_col = 'timestamps' if 'timestamps' in df.columns else 'timestamp'
        if timestamp_col in df.columns:
            df = df.sort_values(timestamp_col).reset_index(drop=True)

        # 去重
        df = df.drop_duplicates(subset=[timestamp_col]).reset_index(drop=True)

        return df

    def normalize_data(self, df: pd.DataFrame, source: str) -> pd.DataFrame:
        """数据标准化"""
        if df is None or df.empty:
            return df

        # 确保列顺序 - 使用timestamps而不是timestamp
        target_columns = ['timestamps', 'open', 'high', 'low', 'close', 'volume', 'amount']

        # 处理时间戳列名统一
        if 'timestamp' in df.columns and 'timestamps' not in df.columns:
            df = df.rename(columns={'timestamp': 'timestamps'})

        # 添加缺失列
        for col in target_columns:
            if col not in df.columns:
                if col == 'amount' and 'volume' in df.columns and 'close' in df.columns:
                    # 估算成交额
                    df[col] = df['volume'] * df['close']
                else:
                    df[col] = 0

        # 重新排列列顺序
        df = df[target_columns]

        # 时间格式标准化 - 保持原始时间戳格式，不进行转换
        # 因为时间戳已经在validate_data中处理过了，这里不需要再次转换

        return df

    def merge_data_sources(self, data_list: List[pd.DataFrame],
                           sources: List[str]) -> pd.DataFrame:
        """合并多个数据源的数据"""
        if not data_list:
            return pd.DataFrame()

        # 过滤空数据
        valid_data = [(df, src) for df, src in zip(data_list, sources)
                      if df is not None and not df.empty]

        if not valid_data:
            return pd.DataFrame()

        # 如果只有一个数据源，直接返回
        if len(valid_data) == 1:
            return valid_data[0][0]

        # 合并多个数据源
        merged_df = pd.DataFrame()
        for df, source in valid_data:
            if merged_df.empty:
                merged_df = df.copy()
            else:
                # 按时间戳合并，优先使用第一个数据源的数据
                merged_df = pd.concat([merged_df, df], ignore_index=True)
                merged_df = merged_df.drop_duplicates(subset=['timestamp'], keep='first')
                merged_df = merged_df.sort_values('timestamp').reset_index(drop=True)

        return merged_df

    def process_realtime_data(self, raw_data: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
        """处理实时数据 - 统一入口"""
        try:
            if source == 'eastmoney':
                df = self.process_eastmoney_data(raw_data, '')
            elif source == 'tonghuashun':
                df = self.process_tonghuashun_data(raw_data, '')
            elif source == 'xueqiu':
                df = self.process_xueqiu_data(raw_data, '')
            else:
                return None

            if df is None or df.empty:
                return None

            # 验证和标准化数据
            df = self.validate_data(df)
            df = self.normalize_data(df, source)

            if df.empty:
                return None

            # 转换为字典格式返回最新一条数据
            latest_data = df.iloc[-1].to_dict()
            return latest_data

        except Exception as e:
            print(f"❌ 处理 {source} 实时数据失败: {e}")
            return None

    def process_kline_data(self, raw_data: Dict[str, Any], source: str) -> Optional[List[Dict[str, Any]]]:
        """处理K线数据 - 统一入口"""
        try:
            if source == 'eastmoney':
                df = self.process_eastmoney_data(raw_data, '')
            elif source == 'tonghuashun':
                df = self.process_tonghuashun_data(raw_data, '')
            elif source == 'xueqiu':
                df = self.process_xueqiu_data(raw_data, '')
            else:
                return None

            if df is None or df.empty:
                return None

            # 验证和标准化数据
            df = self.validate_data(df)
            df = self.normalize_data(df, source)

            if df.empty:
                return None

            # 转换为字典列表返回
            return df.to_dict('records')

        except Exception as e:
            print(f"❌ 处理 {source} K线数据失败: {e}")
            return None

    def process_minute_data(self, raw_data: Dict[str, Any], source: str) -> Optional[List[Dict[str, Any]]]:
        """处理分时数据 - 统一入口"""
        # 分时数据处理逻辑与K线数据类似
        return self.process_kline_data(raw_data, source)

    def convert_to_dataframe(self, kline_data: List[Dict[str, Any]], period: str) -> Optional[pd.DataFrame]:
        """
        将K线数据转换为DataFrame格式
        
        Args:
            kline_data: K线数据列表
            period: 数据周期
            
        Returns:
            DataFrame格式的数据
        """
        if not kline_data:
            return None

        try:
            # 将字典列表转换为DataFrame
            df = pd.DataFrame(kline_data)

            # 验证和标准化数据
            df = self.validate_data(df)
            df = self.normalize_data(df, 'crawler')

            # 针对分钟级周期，统一将时间戳对齐到区间起始
            # 例如东财5分钟K线通常以区间结束时间标记（09:35代表09:30-09:35），
            # 为保证从09:30开盘开始，需将时间戳减去一个周期长度
            try:
                if isinstance(period, str) and period.endswith('m'):
                    # 提取周期分钟数，如 '5m' -> 5
                    minutes = int(period[:-1])
                    # 统一使用 'timestamps' 列
                    ts_col = 'timestamps' if 'timestamps' in df.columns else (
                        'timestamp' if 'timestamp' in df.columns else None)
                    if ts_col:
                        # 转为datetime进行偏移
                        df[ts_col] = pd.to_datetime(df[ts_col], errors='coerce')
                        df = df.dropna(subset=[ts_col])
                        # 向区间起始对齐
                        df[ts_col] = df[ts_col] - pd.to_timedelta(minutes, unit='m')
                        # 排序并去重（防止潜在的时间重叠）
                        df = df.sort_values(ts_col).drop_duplicates(subset=[ts_col]).reset_index(drop=True)
            except Exception as e:
                print(f"⚠️ 分钟周期时间对齐失败: {e}")

            if df.empty:
                print("⚠️ 数据验证或标准化后为空")
                return None

            print(f"✅ 数据转换成功: {len(df)} 条记录")
            return df

        except Exception as e:
            print(f"❌ 数据转换失败: {e}")
            return None

    def save_processed_data(self, df: pd.DataFrame, symbol: str,
                            freq: str = '5min', source: str = 'crawler') -> str:
        """保存处理后的数据为标准CSV格式"""
        if df is None or df.empty:
            print("❌ 数据为空，无法保存")
            return ""

        # 确保数据格式符合标准：timestamps,open,high,low,close,volume,amount
        df = self._standardize_csv_format(df)

        # 创建输出目录
        output_dir = Path('./data/')
        output_dir.mkdir(parents=True, exist_ok=True)

        # 转换交易所代码格式 (SZ -> XSHE, SH -> XSHG)
        if '.' in symbol:
            code, exchange = symbol.split('.')
            if exchange == 'SZ':
                exchange_code = 'XSHE'
            elif exchange == 'SH':
                exchange_code = 'XSHG'
            else:
                exchange_code = exchange
        else:
            exchange_code = 'XSHG'  # 默认
            code = symbol

        # 生成文件名 (格式: XSHG_5min_600977.csv)
        filename = f"{exchange_code}_{freq}_{code}.csv"
        filepath = output_dir / filename

        try:
            # 保存为CSV文件，使用标准格式
            df.to_csv(filepath, index=False, encoding='utf-8')
            print(f"✅ 数据已保存到标准CSV格式: {filepath} ({len(df)} 条记录)")
            return str(filepath)
        except Exception as e:
            print(f"❌ 保存数据失败: {e}")
            return ""

        # 转换股票代码格式
        if '.' in symbol:
            code, exchange = symbol.split('.')
            if exchange == 'SZ':
                exchange_code = 'XSHE'
            elif exchange == 'SH':
                exchange_code = 'XSHG'
            else:
                exchange_code = exchange
        else:
            exchange_code = 'XSHG'
            code = symbol

        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{exchange_code}_{freq}_{code}_{source}_{timestamp}.csv"
        filepath = output_dir / filename

        try:
            # 保存数据（不包含source列）
            save_df = df.drop(columns=['source'], errors='ignore')
            save_df.to_csv(filepath, index=False, encoding='utf-8')
            print(f"✅ 数据已保存: {filepath}")
            return str(filepath)
        except Exception as e:
            print(f"❌ 保存数据失败: {e}")
            return ""
