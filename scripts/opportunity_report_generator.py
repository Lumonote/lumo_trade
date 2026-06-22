#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会挖掘报表生成器
生成包含漏斗筛选、TOP推荐、详细分析的HTML报表
"""

import os
import sys
import re
import calendar
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
import logging
import requests
from urllib.parse import quote
from scripts.stock_filter_utils import (
    filter_st_stocks,
    load_tushare_token,
    load_tushare_stock_name_map,
)

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.scoring_rules import RULESET_VERSION  # noqa: E402  v24共享规则版本号

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _fmt_money(num):
    try:
        val = float(num)
        abs_val = abs(val)
        if abs_val >= 100000000:
            return f"{val/100000000:+.2f}亿"
        elif abs_val >= 10000:
            return f"{val/10000:+.2f}万"
        else:
            return f"{val:+.2f}"
    except:
        return '—'


def _to_float_safe(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().replace('%', '')
        if not stripped:
            return None
        try:
            return float(stripped)
        except Exception:
            return None
    return None


def _is_missing_display_value(value) -> bool:
    if value is None:
        return True
    try:
        if value != value:
            return True
    except Exception:
        pass
    text = str(value).strip()
    if not text:
        return True
    if text.lower() in ('nan', 'none', 'null', 'n/a', 'na', 'unknown'):
        return True
    if text in ('未知', 'N/A', 'None'):
        return True
    return False


def _normalize_stock_code(value) -> str:
    if _is_missing_display_value(value):
        return ''
    if isinstance(value, int):
        return str(value).zfill(6)
    if isinstance(value, float):
        try:
            if value.is_integer():
                return str(int(value)).zfill(6)
        except Exception:
            pass
    text = str(value).strip()
    if text.endswith('.0') and text[:-2].isdigit():
        return text[:-2].zfill(6)
    if '.' in text:
        left, right = text.split('.', 1)
        if left.isdigit() and right.isalpha():
            return left.zfill(6)
    if text.isdigit():
        return text.zfill(6)
    return text


def _pick_display_text(*values, default='未知') -> str:
    for value in values:
        if _is_missing_display_value(value):
            continue
        return str(value).strip()
    return default


def _pick_stock_display_name(name=None, stock_name=None, code=None, default='未知') -> str:
    return _pick_display_text(name, stock_name, _normalize_stock_code(code), default=default)


def _stock_final_score(stock: Dict) -> float:
    try:
        return float(stock.get('final_score', 0) or 0)
    except Exception:
        return 0.0


def _is_degraded_opportunity(stock: Dict) -> bool:
    scoring = stock.get('scoring_result') or {}
    details = scoring.get('details') or {}
    quant = details.get('quantitative') or {}
    return bool(
        scoring.get('degraded')
        or quant.get('degraded')
        or quant.get('error') == '无历史数据'
    )


def _get_displayable_sector_change(
    change_value,
    turnover_value=None,
    score=None,
    overall=None,
    data_source=None,
    leader_stock=None
):
    change = _to_float_safe(change_value)
    if change is None:
        return None

    turnover = _to_float_safe(turnover_value)
    score_num = _to_float_safe(score)
    overall_text = str(overall or '').strip()
    source_text = str(data_source or '').strip().lower()
    leader = leader_stock if isinstance(leader_stock, dict) else {}
    has_leader = any(str(leader.get(key) or '').strip() for key in ('name', 'code'))

    if abs(change) < 1e-9:
        if source_text in ('', 'default', 'none'):
            return None
        if overall_text in ('', '未知', 'N/A', 'Unknown', '数据不足'):
            return None
        if turnover in (None, 0.0) and (score_num is None or abs(score_num - 50.0) < 1e-9) and not has_leader:
            return None

    return change


def _generate_selection_reason(stock: Dict) -> str:
    """
    根据股票的评分数据生成有意义的入选原因
    """
    try:
        scoring = stock.get('scoring_result') or {}
        scores = scoring.get('scores') or {}
        details = scoring.get('details') or {}

        reasons = []
        rating = stock.get('rating') or scoring.get('rating') or 'C'
        final_score = float(stock.get('final_score', 0) or 0)

        tech_score = float(scores.get('technical', 0) or 0)
        sent_score = float(scores.get('sentiment', 0) or 0)
        quant_score = float(scores.get('quantitative', 0) or 0)
        sector_score = float(scores.get('sector', 0) or 0)

        sec = details.get('sector') or {}
        sector_name = sec.get('sector_name', '')
        sector_chg = _get_displayable_sector_change(
            sec.get('change_pct'),
            turnover_value=sec.get('turnover_rate'),
            score=sector_score,
            overall=sec.get('overall'),
            data_source=sec.get('data_source'),
            leader_stock=sec.get('leader_stock')
        )
        if sector_chg is None:
            sector_chg = 0.0

        cf = details.get('sentiment', {}).get('capital_flow') or {}
        cf_trend = cf.get('trend', '')

        qd = details.get('quantitative') or {}
        buy_count = int(qd.get('buy_count', 0) or 0)

        ed = details.get('events') or {}
        pos_events = int(ed.get('positive_events', 0) or 0)
        ev_rating = ed.get('rating', '')

        price_changes = details.get('price_changes') or {}
        change_1d = float(price_changes.get('change_1d', 0) or 0)
        change_3d = float(price_changes.get('change_3d', 0) or 0)

        if rating == 'S':
            reasons.append("综合评级S级(强烈推荐)")
        elif rating == 'A+':
            reasons.append("综合评级A+级(推荐)")
        elif rating == 'A':
            reasons.append("综合评级A级")
        elif rating == 'B' and final_score >= 75:
            reasons.append("综合评分尚可")

        if tech_score >= 75:
            reasons.append(f"技术面强势({tech_score:.0f}分)")
        elif tech_score >= 65:
            reasons.append(f"技术指标向好({tech_score:.0f}分)")

        if sector_name and sector_name != '未知':
            if sector_chg >= 5:
                reasons.append(f"{sector_name}领涨+{sector_chg:.1f}%")
            elif sector_chg >= 2:
                reasons.append(f"{sector_name}板块走强+{sector_chg:.1f}%")
            elif sector_chg > 0:
                reasons.append(f"{sector_name}板块温和上涨+{sector_chg:.1f}%")

        if cf_trend == 'inflow':
            reasons.append("资金持续流入")
        elif cf_trend == 'strong_inflow':
            reasons.append("资金大幅流入")

        if buy_count >= 3:
            reasons.append(f"{buy_count}个量化模型发出买入信号")
        elif buy_count >= 2:
            reasons.append(f"{buy_count}个量化模型共振看涨")

        if pos_events >= 2:
            reasons.append(f"{pos_events}条利好事件驱动")

        if ev_rating == '利好':
            reasons.append("消息面偏正面")

        if change_3d >= 5:
            reasons.append(f"三日涨幅{change_3d:+.1f}%")

        if len(reasons) >= 2:
            return "；".join(reasons[:3])
        elif len(reasons) == 1:
            return reasons[0]
        else:
            if final_score >= 70:
                return f"综合评分{final_score:.0f}分，各维度表现良好"
            elif final_score >= 60:
                return f"综合评分{final_score:.0f}分，具备投资价值"
            else:
                return "通过多维度筛选，满足投资条件"
    except Exception:
        return "综合评分达标"


def _md_to_html_body(lines: List[str]) -> str:
    """Convert the structured markdown report lines to well-formatted HTML body.

    The report markdown uses a specific structure:
    - ``## Heading`` → ``<h2>``
    - ``### Heading`` → ``<h3>``
    - ``---`` → ``<hr>``
    - ``> text`` → ``<blockquote>``
    - ``- **key**: value`` → ``<li>``
    - ``1. text`` → ``<ol><li>``
    - ``[text](url)`` → ``<a href="...">``
    - Inline ``**bold**`` → ``<strong>``
    - Embedded HTML tables / divs → pass through unchanged
    - Regular text paragraphs are wrapped in ``<p>``.
    """
    import re as _re_md

    html_parts = []
    i = 0
    n = len(lines)

    # Block-level accumulators
    list_buffer = []       # for - items or 1. items
    list_type = None       # 'ul' or 'ol'
    para_buffer = []       # for inline text lines
    blockquote_buffer = [] # for > lines

    def _flush_list():
        nonlocal list_buffer, list_type
        if not list_buffer:
            return
        tag = list_type or 'ul'
        html_parts.append(f'<{tag}>')
        for item in list_buffer:
            html_parts.append(f'<li>{item}</li>')
        html_parts.append(f'</{tag}>')
        list_buffer = []
        list_type = None

    def _flush_para():
        nonlocal para_buffer
        if para_buffer:
            text = ' '.join(para_buffer)
            html_parts.append(f'<p>{text}</p>')
            para_buffer = []

    def _flush_blockquote():
        nonlocal blockquote_buffer
        if blockquote_buffer:
            text = ' '.join(blockquote_buffer)
            html_parts.append(f'<blockquote>{text}</blockquote>')
            blockquote_buffer = []

    def _inline(text: str) -> str:
        """Convert inline markdown: **bold**, [text](url), `code`."""
        t = text
        # links [text](url)
        t = _re_md.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', t)
        # bold **text**
        t = _re_md.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', t)
        # inline code `text`
        t = _re_md.sub(r'`([^`]+)`', r'<code>\1</code>', t)
        return t

    def _is_html_line(line: str) -> bool:
        return bool(_re_md.match(r'^\s*<', line))

    def _is_table_row(line: str) -> bool:
        return bool(_re_md.match(r'^\s*<(tr|/tr|td|/td|th|/th|thead|/thead|tbody|/tbody|table|/table|colgroup|/colgroup|col|div)', line))

    while i < n:
        line = lines[i]

        # Skip empty lines but flush buffered content
        if not line.strip():
            _flush_list()
            _flush_para()
            _flush_blockquote()
            i += 1
            continue

        # HTML comments pass through
        if line.strip().startswith('<!--') and line.strip().endswith('-->'):
            _flush_list()
            _flush_para()
            _flush_blockquote()
            html_parts.append(line)
            i += 1
            continue

        # Embedded HTML (tables, divs) pass through with surrounding flushes
        if _is_html_line(line) or _is_table_row(line):
            _flush_list()
            _flush_para()
            _flush_blockquote()
            # Collect contiguous HTML block
            html_block = [line]
            j = i + 1
            while j < n:
                next_line = lines[j]
                if not next_line.strip():
                    break
                if _is_html_line(next_line) or _is_table_row(next_line) or next_line.strip().startswith('</'):
                    html_block.append(next_line)
                    j += 1
                else:
                    break
            html_parts.append('\n'.join(html_block))
            i = j
            continue

        stripped = line.strip()

        # h3 / h2
        if stripped.startswith('### '):
            _flush_list()
            _flush_para()
            _flush_blockquote()
            html_parts.append(f'<h3>{_inline(stripped[4:])}</h3>')
            i += 1
            continue

        if stripped.startswith('## '):
            _flush_list()
            _flush_para()
            _flush_blockquote()
            html_parts.append(f'<h2>{_inline(stripped[3:])}</h2>')
            i += 1
            continue

        # <hr>
        if stripped == '---':
            _flush_list()
            _flush_para()
            _flush_blockquote()
            html_parts.append('<hr>')
            i += 1
            continue

        # Blockquote
        if stripped.startswith('> '):
            _flush_list()
            _flush_para()
            txt = stripped[2:]
            # Always process inline markdown (links, bold, code)
            txt = _inline(txt)
            blockquote_buffer.append(txt)
            i += 1
            continue

        # Unordered list
        if _re_md.match(r'^-\s', stripped):
            _flush_para()
            _flush_blockquote()
            if list_type and list_type != 'ul':
                _flush_list()
            list_type = 'ul'
            item_text = _re_md.sub(r'^-\s+', '', stripped, count=1)
            list_buffer.append(_inline(item_text))
            i += 1
            continue

        # Ordered list
        if _re_md.match(r'^\d+\.\s', stripped):
            _flush_para()
            _flush_blockquote()
            if list_type and list_type != 'ol':
                _flush_list()
            list_type = 'ol'
            item_text = _re_md.sub(r'^\d+\.\s+', '', stripped, count=1)
            list_buffer.append(_inline(item_text))
            i += 1
            continue

        # Regular text
        _flush_list()
        _flush_blockquote()
        txt = _inline(stripped)
        para_buffer.append(txt)
        i += 1

    # Flush remaining
    _flush_list()
    _flush_para()
    _flush_blockquote()

    return '\n'.join(html_parts)


class OpportunityReportGenerator:
    """投资机会挖掘报表生成器"""

    def __init__(self, output_dir: str = "results"):
        """
        初始化报表生成器

        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self._recent_repeat_cache = {}
        self._price_history_cache = {}
        self._historical_stock_name_cache = None
        self._tushare_name_cache = None  # 6位代码 → 中文名 (lazy)
        self._local_stock_name_cache = None
        self._quote_stock_name_cache = {}
        self.latest_top_report_path = None

    def _normalize_topic_url(self, raw_url: str, title: str = '') -> str:
        url = (raw_url or '').strip()
        if url.startswith('http://') or url.startswith('https://'):
            return url
        if url:
            base = 'https://gubatopic.eastmoney.com/'
            if url.startswith('/'):
                return base.rstrip('/') + url
            return base.rstrip('/') + '/' + url
        if title:
            return f"https://so.eastmoney.com/search.htm?q={quote(title)}"
        return "https://gubatopic.eastmoney.com/"

    def _parse_opportunity_report_datetime(self, filename: str) -> Optional[datetime]:
        match = re.match(r'^opportunity_top10_(\d{8})_(\d{6})\.md$', filename)
        if not match:
            return None
        try:
            return datetime.strptime(''.join(match.groups()), '%Y%m%d%H%M%S')
        except Exception:
            return None

    def _extract_ranked_stocks_from_markdown(self, filepath: str, report_date: str) -> List[Dict]:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return []

        table_match = re.search(
            r'## 🏆 综合排名 TOP20.*?<tbody>(.*?)</tbody></table>',
            content,
            flags=re.S
        )
        if not table_match:
            return []

        row_pattern = re.compile(
            r'<tr><td[^>]*>\s*(\d+)\s*</td><td[^>]*>\s*([0-9A-Za-z]+)\s*</td><td>(.*?)</td><td[^>]*>\s*([0-9.]+)\s*</td>',
            flags=re.S
        )

        stocks = []
        for rank_text, code_text, name_text, score_text in row_pattern.findall(table_match.group(1)):
            try:
                stocks.append({
                    'rank': int(rank_text),
                    'code': _normalize_stock_code(code_text),
                    'name': re.sub(r'<[^>]+>', '', str(name_text)).strip(),
                    'score': float(score_text),
                    'report_date': report_date
                })
            except Exception:
                continue
        return stocks

    def _sanitize_stock_name(self, raw_name, code: str = '') -> str:
        name = re.sub(r'<[^>]+>', '', str(raw_name or ''))
        name = name.replace('&nbsp;', ' ').strip()
        if _is_missing_display_value(name):
            return ''
        normalized_code = _normalize_stock_code(code)
        if normalized_code and name == normalized_code:
            return ''
        return name

    def _load_stock_name_cache_from_reports(self) -> Dict[str, str]:
        if self._historical_stock_name_cache is not None:
            return self._historical_stock_name_cache

        name_by_code = {}
        report_files = []

        try:
            filenames = os.listdir(self.output_dir)
        except Exception:
            filenames = []

        for filename in filenames:
            report_dt = self._parse_opportunity_report_datetime(filename)
            if report_dt is None:
                continue
            report_files.append((report_dt, os.path.join(self.output_dir, filename)))

        pattern_specs = [
            (
                re.compile(r'^\s*\|\s*\d+\s*\|\s*(\d{6})\s*\|\s*([^|]+?)\s*\|', flags=re.M),
                'code_first'
            ),
            (
                re.compile(r'<td[^>]*>\s*(\d{6})\s*</td><td[^>]*>\s*([^<]+?)\s*</td>', flags=re.S),
                'code_first'
            ),
            (
                re.compile(r'###\s*([^()\n]+?)\((\d{6})\)\s*-\s*', flags=re.M),
                'name_first'
            ),
            (
                re.compile(r'\*\*([^()\n]+?)\((\d{6})\)\*\*'),
                'name_first'
            ),
            (
                re.compile(r'<strong>\s*([^<()\n]+?)\s*</strong>\((\d{6})\)'),
                'name_first'
            ),
        ]

        for _, filepath in sorted(report_files, key=lambda item: item[0], reverse=True):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                continue

            for pattern, order in pattern_specs:
                for match in pattern.finditer(content):
                    if order == 'code_first':
                        code, raw_name = match.group(1), match.group(2)
                    else:
                        raw_name, code = match.group(1), match.group(2)

                    code = _normalize_stock_code(code)
                    name = self._sanitize_stock_name(raw_name, code)
                    if code and name and code not in name_by_code:
                        name_by_code[code] = name

        self._historical_stock_name_cache = name_by_code
        return name_by_code

    def _load_tushare_name_map(self) -> Dict[str, str]:
        """通过 Tushare stock_basic 拉全市场代码→中文名映射，结果缓存到实例。
        失败时返回 {} 并不再重试。"""
        if self._tushare_name_cache is not None:
            return self._tushare_name_cache
        self._tushare_name_cache = load_tushare_stock_name_map()
        if self._tushare_name_cache:
            logger.info(f"✓ Tushare 股票名称映射加载: {len(self._tushare_name_cache)} 只")
            return self._tushare_name_cache

        self._tushare_name_cache = {}  # 默认空,失败也不重试
        try:
            import tushare as _ts
            _token = load_tushare_token()
            if not _token:
                return self._tushare_name_cache
            _ts.set_token(_token)
            pro = _ts.pro_api()
            df = pro.stock_basic(exchange='', list_status='L',
                                 fields='ts_code,symbol,name')
            if df is None or df.empty:
                return self._tushare_name_cache
            mapping = {}
            for _, row in df.iterrows():
                code = str(row.get('symbol') or '').strip()
                nm = str(row.get('name') or '').strip()
                if code and nm:
                    mapping[code.zfill(6)] = nm
            self._tushare_name_cache = mapping
            logger.info(f"✓ Tushare 股票名称映射加载: {len(mapping)} 只")
        except Exception as e:
            logger.debug(f"Tushare 股票名称加载失败: {e}")
        return self._tushare_name_cache

    def _load_local_stock_name_map(self) -> Dict[str, str]:
        """从本地 SQLite/缓存中读取代码→名称映射，不依赖 TuShare。"""
        if self._local_stock_name_cache is not None:
            return self._local_stock_name_cache

        mapping: Dict[str, str] = {}

        def add(code, name):
            normalized_code = _normalize_stock_code(code)
            clean_name = self._sanitize_stock_name(name, normalized_code)
            if normalized_code and clean_name and normalized_code not in mapping:
                mapping[normalized_code] = clean_name

        try:
            from data_store.connection import get_conn
            conn = get_conn()
            for sql in (
                "SELECT code, name FROM opportunity_item WHERE name IS NOT NULL AND name <> '' ORDER BY run_id DESC",
                "SELECT ts_code AS code, name FROM moneyflow_dc WHERE name IS NOT NULL AND name <> '' ORDER BY trade_date DESC",
            ):
                try:
                    for row in conn.execute(sql).fetchall():
                        add(row["code"], row["name"])
                except Exception:
                    continue

            try:
                row = conn.execute(
                    "SELECT payload FROM kv_cache WHERE namespace='hot_stocks' AND key='latest'"
                ).fetchone()
                payload = json.loads(row["payload"]) if row else None
                candidates = payload
                if isinstance(payload, dict):
                    candidates = payload.get("stocks") or payload.get("data") or payload.get("items") or []
                if isinstance(candidates, list):
                    for item in candidates:
                        if isinstance(item, dict):
                            add(item.get("code") or item.get("stock_code"), item.get("name") or item.get("stock_name"))
            except Exception:
                pass
        except Exception as exc:
            logger.debug(f"本地股票名称映射加载失败: {exc}")

        self._local_stock_name_cache = mapping
        return mapping

    def _fetch_tencent_stock_names(self, codes: List[str]) -> Dict[str, str]:
        """从腾讯行情接口补股票名。该接口免 token，用于打包环境兜底。"""
        missing = []
        for code in codes:
            normalized_code = _normalize_stock_code(code)
            if normalized_code and normalized_code not in self._quote_stock_name_cache:
                missing.append(normalized_code)
        if not missing:
            return self._quote_stock_name_cache

        symbols = [
            ("sh" if code.startswith(("5", "6", "9")) else "sz") + code
            for code in missing
        ]
        try:
            resp = requests.get(
                "https://qt.gtimg.cn/q=" + ",".join(symbols),
                timeout=5,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.encoding = "gbk"
            for line in resp.text.splitlines():
                if '="' not in line:
                    continue
                left, right = line.split('="', 1)
                api_code = left.strip().replace("v_", "")
                code = _normalize_stock_code(api_code)
                fields = right.strip().strip('";').split("~")
                name = fields[1] if len(fields) > 1 else ""
                clean = self._sanitize_stock_name(name, code)
                if code and clean:
                    self._quote_stock_name_cache[code] = clean
        except Exception as exc:
            logger.debug(f"腾讯行情股票名称补全失败: {exc}")

        return self._quote_stock_name_cache

    def _filter_st_analysis_results(self, analysis_results: List[Dict], context: str) -> List[Dict]:
        """报表生成前最终过滤 ST/退市股票，防止上游漏网。"""
        filtered, removed = filter_st_stocks(analysis_results, self._load_tushare_name_map())
        if removed:
            logger.info(f"{context}: 过滤ST/退市股票 {len(removed)} 只: {', '.join(removed)}")
        return filtered

    def _resolve_stock_display_name_from_reports(
        self,
        code=None,
        name=None,
        stock_name=None,
        default='未知'
    ) -> str:
        normalized_code = _normalize_stock_code(code)
        display_name = self._sanitize_stock_name(
            _pick_display_text(name, stock_name, default=''),
            normalized_code
        )
        if display_name:
            return display_name

        # 1) 本地历史报告缓存
        cached_name = self._load_stock_name_cache_from_reports().get(normalized_code, '')
        cached_name = self._sanitize_stock_name(cached_name, normalized_code)
        if cached_name:
            return cached_name

        # 2) Tushare stock_basic 兜底
        ts_name = self._load_tushare_name_map().get(normalized_code, '')
        ts_name = self._sanitize_stock_name(ts_name, normalized_code)
        if ts_name:
            return ts_name

        # 3) 本地库/缓存兜底
        local_name = self._load_local_stock_name_map().get(normalized_code, '')
        local_name = self._sanitize_stock_name(local_name, normalized_code)
        if local_name:
            return local_name

        # 4) 免 token 行情接口兜底
        quote_name = self._fetch_tencent_stock_names([normalized_code]).get(normalized_code, '')
        quote_name = self._sanitize_stock_name(quote_name, normalized_code)
        if quote_name:
            return quote_name

        # 5) 仍然找不到 → 显示代码
        return _pick_stock_display_name(None, '', normalized_code, default=default)

    def _load_price_history(self, stock_code: str):
        code = _normalize_stock_code(stock_code)
        if not code:
            return None
        if code in self._price_history_cache:
            return self._price_history_cache[code]

        df = None

        try:
            from data.cache.data_cache import get_ohlcv, fetch_and_cache_ohlcv
            df = get_ohlcv(code, min_rows=2, max_age_seconds=43200)
            if df is None or df.empty:
                if fetch_and_cache_ohlcv(code):
                    df = get_ohlcv(code, min_rows=2)
        except Exception:
            df = None

        if df is None or getattr(df, 'empty', True):
            try:
                import tushare as ts
                import pandas as pd

                token = load_tushare_token()
                if token:
                    pro = ts.pro_api(token)
                    ts_code = f"{code}.SH" if code.startswith(('5', '6', '9')) else f"{code}.SZ"
                    start_date = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
                    end_date = (datetime.now() + timedelta(days=1)).strftime('%Y%m%d')
                    df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
                    if df is not None and not df.empty:
                        df = df.rename(columns={'trade_date': 'timestamps'})
                        df['timestamps'] = pd.to_datetime(df['timestamps'])
                        df = df.sort_values('timestamps').reset_index(drop=True)
            except Exception:
                df = None

        if df is not None and not getattr(df, 'empty', True):
            try:
                import pandas as pd

                normalized = df.copy()
                if 'timestamp' in normalized.columns and 'timestamps' not in normalized.columns:
                    normalized = normalized.rename(columns={'timestamp': 'timestamps'})
                normalized['timestamps'] = pd.to_datetime(normalized['timestamps'])
                normalized = normalized.sort_values('timestamps').reset_index(drop=True)
                self._price_history_cache[code] = normalized
                return normalized
            except Exception:
                pass

        self._price_history_cache[code] = None
        return None

    def _calculate_post_selection_return(self, stock_code: str, report_date: str) -> Optional[float]:
        try:
            import pandas as pd

            price_df = self._load_price_history(stock_code)
            if price_df is None or price_df.empty or 'timestamps' not in price_df.columns:
                return None

            report_dt = pd.to_datetime(report_date).normalize()
            normalized_df = price_df.copy()
            normalized_df['trade_date'] = pd.to_datetime(normalized_df['timestamps']).dt.normalize()
            future_data = normalized_df[normalized_df['trade_date'] > report_dt].copy()
            if future_data.empty:
                return None

            buy_price = _to_float_safe(future_data.iloc[0].get('open'))
            latest_close = _to_float_safe(future_data.iloc[-1].get('close'))
            if buy_price in (None, 0) or latest_close is None:
                return None

            return (latest_close - buy_price) / buy_price * 100
        except Exception:
            return None

    def _collect_recent_repeat_entries(
        self,
        target_codes: List[str],
        current_report_dt: datetime,
        window_days: Optional[int] = None
    ) -> Dict[str, List[Dict]]:
        normalized_codes = sorted({
            _normalize_stock_code(code)
            for code in (target_codes or [])
            if _normalize_stock_code(code)
        })
        if not normalized_codes:
            return {}

        cache_key = (
            tuple(normalized_codes),
            current_report_dt.strftime('%Y-%m-%d'),
            window_days
        )
        cached = self._recent_repeat_cache.get(cache_key)
        if cached is not None:
            return cached

        recent_files_by_day = {}
        window_start = None
        if window_days is not None:
            window_start = current_report_dt.date() - timedelta(days=window_days)

        try:
            filenames = os.listdir(self.output_dir)
        except Exception:
            filenames = []

        for filename in filenames:
            report_dt = self._parse_opportunity_report_datetime(filename)
            if report_dt is None:
                continue
            report_day = report_dt.date()
            if report_day >= current_report_dt.date():
                continue
            if window_start is not None and report_day < window_start:
                continue

            current_best = recent_files_by_day.get(report_day)
            if current_best is None or report_dt > current_best['report_dt']:
                recent_files_by_day[report_day] = {
                    'report_dt': report_dt,
                    'path': os.path.join(self.output_dir, filename)
                }

        history_by_code = {}
        for report_day in sorted(recent_files_by_day.keys(), reverse=True):
            report_path = recent_files_by_day[report_day]['path']
            report_date = report_day.strftime('%Y-%m-%d')
            stocks = self._extract_ranked_stocks_from_markdown(report_path, report_date)

            for stock in stocks:
                code = stock.get('code')
                if code not in normalized_codes:
                    continue

                if code not in history_by_code:
                    history_by_code[code] = []

                history_by_code[code].append({
                    'report_date': report_date,
                    'rank': stock.get('rank'),
                    'score': stock.get('score'),
                    'return_since_buy': self._calculate_post_selection_return(code, report_date)
                })

        self._recent_repeat_cache[cache_key] = history_by_code
        return history_by_code

    def _build_recent_repeat_selection_summary(
        self,
        stock_code: str,
        repeat_entries: Optional[List[Dict]],
        window_days: Optional[int] = None
    ) -> str:
        code = _normalize_stock_code(stock_code)
        entries = repeat_entries or []
        if not code or not entries:
            return ""

        parts = []
        for entry in entries:
            return_value = entry.get('return_since_buy')
            if return_value is None:
                return_text = "待更新"
            else:
                return_text = f"{return_value:+.2f}%"

            parts.append(
                f"{entry.get('report_date', '未知日期')}"
                f"(第{entry.get('rank', '—')}名/{float(entry.get('score', 0) or 0):.2f}分，"
                f"入选后买入涨幅{return_text})"
            )

        if window_days is None:
            prefix = "【历史重复入选】"
        else:
            prefix = f"【近{window_days}日重复入选】"
        return f"{prefix}共{len(entries)}次：" + "；".join(parts) + "；"

    def _append_html_table_start(self, lines: List[str], headers: List[str], col_widths: List[str]):
        lines.append('<table style="width:100%; table-layout:fixed;">')
        lines.append("<colgroup>")
        for w in col_widths:
            lines.append(f'<col style="width:{w};">')
        lines.append("</colgroup>")
        lines.append("<thead>")
        lines.append("<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>")
        lines.append("</thead>")
        lines.append("<tbody>")

    def _append_html_table_row(self, lines: List[str], cells: List[str]):
        lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")

    def _append_html_table_end(self, lines: List[str]):
        lines.append("</tbody>")
        lines.append("</table>")

    def _load_trade_days_until(self, report_dt: datetime, lookback_days: int = 120) -> List[str]:
        base_str = report_dt.strftime('%Y%m%d')
        freshness_floor = (report_dt - timedelta(days=20)).strftime('%Y%m%d')

        try:
            from data.cache.data_cache import get_trade_calendar

            trade_days = sorted(str(day) for day in get_trade_calendar() if str(day) <= base_str)
            if trade_days and trade_days[-1] >= freshness_floor:
                return trade_days
        except Exception:
            pass

        try:
            import tushare as ts

            token = load_tushare_token()
            if token:
                pro = ts.pro_api(token)
                start_str = (report_dt - timedelta(days=lookback_days)).strftime('%Y%m%d')
                cal_df = pro.trade_cal(
                    exchange='SSE',
                    start_date=start_str,
                    end_date=base_str,
                    fields='cal_date,is_open'
                )
                if cal_df is not None and not cal_df.empty:
                    cal_df = cal_df[cal_df['is_open'] == 1].copy()
                    if not cal_df.empty:
                        return sorted(cal_df['cal_date'].astype(str).tolist())
        except Exception:
            pass

        trade_days = []
        current = report_dt
        floor_dt = report_dt - timedelta(days=lookback_days)
        while current >= floor_dt:
            if current.weekday() < 5:
                trade_days.append(current.strftime('%Y%m%d'))
            current -= timedelta(days=1)
        return sorted(trade_days)

    def _compute_backtest_report_cutoff(self, report_dt: datetime, reserve_trade_days: int = 10) -> Optional[datetime]:
        trade_days = self._load_trade_days_until(report_dt)
        if len(trade_days) <= reserve_trade_days:
            return None

        cutoff_ymd = trade_days[-(reserve_trade_days + 1)]
        try:
            return datetime.strptime(cutoff_ymd, '%Y%m%d')
        except Exception:
            return None

    def _shift_one_month_back(self, anchor_dt: datetime) -> datetime:
        year = anchor_dt.year
        month = anchor_dt.month - 1
        if month == 0:
            year -= 1
            month = 12
        day = min(anchor_dt.day, calendar.monthrange(year, month)[1])
        return anchor_dt.replace(year=year, month=month, day=day)

    def _prepare_backtest_history(
        self,
        current_report_dt: datetime,
        lookback_days: int = 30,
        reserve_trade_days: int = 10
    ):
        import os as _os
        import pandas as _pd

        _results_dir = _os.path.join(project_root, 'results')
        bt_with_returns = None
        _score_col = '_bt_score'

        # 机会挖掘报表优先使用真实推荐回测记录
        _rec_csv = _os.path.join(_results_dir, 'backtest', 'recommendations.csv')
        if _os.path.exists(_rec_csv):
            _rec_df = _pd.read_csv(_rec_csv)
            if len(_rec_df) > 0:
                _rec_df = _rec_df.copy()
                _rec_df['code'] = _rec_df['code'].apply(_normalize_stock_code)
                _rec_df['report_date'] = _rec_df['report_date'].astype(str).str[:10]
                _rec_df['_bt_score'] = _pd.to_numeric(_rec_df.get('score'), errors='coerce')
                bt_with_returns = _rec_df.copy()

        # recommendations 不足时才回退到历史重建
        if bt_with_returns is None or len(bt_with_returns) < 10:
            _rebuilt_csvs = sorted([
                f for f in _os.listdir(_results_dir)
                if f.startswith('backtest_rebuilt_') and f.endswith('.csv')
            ])
            if _rebuilt_csvs:
                _csv_path = _os.path.join(_results_dir, _rebuilt_csvs[-1])
                from scripts.simulate_v5_backtest import apply_v8_scoring
                _raw_df = _pd.read_csv(_csv_path)
                _scored_df = apply_v8_scoring(_raw_df)
                bt_with_returns = _scored_df.copy()
                bt_with_returns['_bt_score'] = _pd.to_numeric(bt_with_returns.get('v8_score'), errors='coerce')

        if bt_with_returns is None or len(bt_with_returns) < 10:
            _analysis_csvs = sorted([
                f for f in _os.listdir(_results_dir)
                if f.startswith('backtest_analysis_') and f.endswith('.csv')
            ])
            if _analysis_csvs:
                _csv_path = _os.path.join(_results_dir, _analysis_csvs[-1])
                from scripts.simulate_v5_backtest import load_backtest_data, apply_v8_scoring as _apply_scoring
                _raw_df = load_backtest_data(_csv_path)
                _scored_df = _apply_scoring(_raw_df)
                bt_with_returns = _scored_df.copy()
                bt_with_returns['_bt_score'] = _pd.to_numeric(bt_with_returns.get('v8_score'), errors='coerce')

        if bt_with_returns is not None and len(bt_with_returns) > 0:
            bt_with_returns = bt_with_returns.copy()
            bt_with_returns['code'] = bt_with_returns['code'].apply(_normalize_stock_code)
            bt_with_returns['report_date'] = bt_with_returns['report_date'].astype(str).str[:10]

        if bt_with_returns is None or len(bt_with_returns) == 0:
            return None, _score_col, None, None

        cutoff_dt = self._compute_backtest_report_cutoff(current_report_dt, reserve_trade_days=reserve_trade_days)
        anchor_dt = cutoff_dt or current_report_dt
        if lookback_days == 30:
            window_start_dt = self._shift_one_month_back(anchor_dt).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        else:
            window_start_dt = (anchor_dt - timedelta(days=lookback_days)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        bt_with_returns = bt_with_returns.copy()
        bt_with_returns['_report_dt'] = _pd.to_datetime(bt_with_returns['report_date'], errors='coerce')
        bt_with_returns = bt_with_returns[bt_with_returns['_report_dt'].notna()].copy()
        bt_with_returns = bt_with_returns[bt_with_returns['_report_dt'] >= _pd.Timestamp(window_start_dt.date())].copy()
        if cutoff_dt is not None:
            bt_with_returns = bt_with_returns[bt_with_returns['_report_dt'] <= _pd.Timestamp(cutoff_dt.date())].copy()
        bt_with_returns['report_date'] = bt_with_returns['_report_dt'].dt.strftime('%Y-%m-%d')
        bt_with_returns = bt_with_returns.drop(columns=['_report_dt'])

        return bt_with_returns, _score_col, cutoff_dt, window_start_dt

    def _build_market_regime_alert(self, regime_info: Optional[Dict],
                                    s_count: int, a_count: int,
                                    passed_count: int) -> List[str]:
        """生成大盘环境提示 + 候选不足时的"放空一天的勇气"提醒。

        触发情况:
        - 大盘 risk_off (沪深300 5日跌≥3%): 强烈建议观望
        - S 级 = 0 且 A 级 < 5: 候选质量偏低，建议观望
        - S 级 + A 级 < 3: 没有像样的标的
        正常情况下也会显示一行简短的市场状态。
        """
        lines = []
        regime = (regime_info or {}).get('regime', 'unknown')
        chg5 = (regime_info or {}).get('hs300_chg_5d')
        chg20 = (regime_info or {}).get('hs300_chg_20d')

        # 严重情况判定
        is_thin = (s_count == 0 and a_count < 5) or (s_count + a_count < 3)
        is_bear = regime == 'risk_off'

        if is_bear or is_thin:
            warn_parts = []
            if is_bear and chg5 is not None:
                warn_parts.append(
                    f"⚠️ <strong>大盘走弱</strong>(沪深300 近5日 {chg5:+.2f}%, 近20日 {chg20:+.2f}%)，整体环境不利"
                )
            if is_thin:
                warn_parts.append(
                    f"⚠️ <strong>今日候选质量偏低</strong>(S 级 {s_count} 只 / A 级 {a_count} 只 / 通过筛选 {passed_count} 只)"
                )
            lines.append("\n## 🛑 风险提示")
            lines.append('<div style="border: 2px solid #d32f2f; background: #ffebee; padding: 12px; border-radius: 6px; font-size: 14px;">')
            for p in warn_parts:
                lines.append(f'<p style="margin: 4px 0;">{p}</p>')
            lines.append('<p style="margin: 8px 0 0; font-weight: bold; color: #c62828;">📍 建议:今日观望或仅参与 S 级标的，控制总仓位 ≤ 30%</p>')
            lines.append('</div>')
            lines.append("")
        elif regime in ('risk_on', 'neutral') and chg5 is not None:
            tag = '✅ 风险偏好' if regime == 'risk_on' else '🟡 中性'
            lines.append(
                f"\n> **市场环境**: {tag} | 沪深300 近5日 {chg5:+.2f}% / 近20日 {chg20:+.2f}% | 今日 S 级 {s_count} 只, A 级 {a_count} 只\n"
            )
        return lines

    def _build_yesterday_recap(self, current_report_dt: datetime) -> List[str]:
        """读取上一份报告的 Top10，计算其推荐股票"昨日开盘买入"截至现在的实际涨跌。

        返回若干 markdown 行；找不到上一份报告或数据不足时返回 []。
        """
        try:
            import glob as _glob
            pattern = os.path.join(self.output_dir, 'opportunity_top10_*.md')
            files = sorted(_glob.glob(pattern))
            if not files:
                return []
            cur_stamp = current_report_dt.strftime('%Y%m%d_%H%M%S')
            prev_files = [
                f for f in files
                if 'wechat' not in os.path.basename(f)
                and 'alignment' not in os.path.basename(f)
                and 'xueqiu' not in os.path.basename(f)
                and re.search(r'_(\d{8}_\d{6})\.md$', os.path.basename(f))
                and re.search(r'_(\d{8}_\d{6})\.md$', os.path.basename(f)).group(1) < cur_stamp
            ]
            if not prev_files:
                return []
            prev_path = prev_files[-1]
            prev_basename = os.path.basename(prev_path)
            m = re.search(r'_(\d{8})_\d{6}\.md$', prev_basename)
            if not m:
                return []
            prev_date_str = m.group(1)
            prev_date_iso = f"{prev_date_str[:4]}-{prev_date_str[4:6]}-{prev_date_str[6:8]}"

            stocks = self._extract_ranked_stocks_from_markdown(prev_path, prev_date_iso)
            if not stocks:
                return []
            top10 = stocks[:10]

            # 取 Tushare 日线，取上一报告日"次个交易日"开盘价 → 最新可用收盘价
            try:
                import tushare as _ts
                _token = load_tushare_token()
                if not _token:
                    return []
                _ts.set_token(_token)
                pro = _ts.pro_api()
            except Exception:
                return []

            try:
                cal = pro.trade_cal(
                    exchange='SSE',
                    start_date=prev_date_str,
                    end_date=current_report_dt.strftime('%Y%m%d'),
                    is_open='1',
                )
                tdays = sorted(cal['cal_date'].tolist())
            except Exception:
                return []
            if len(tdays) < 1:
                return []
            future = [t for t in tdays if t > prev_date_str]
            if not future:
                return []
            buy_day = future[0]
            latest_day = tdays[-1]

            rows_data = []
            wins = 0
            losses = 0
            total_ret = 0.0
            for s in top10:
                code = str(s.get('code') or '').zfill(6)
                if not code or len(code) != 6:
                    continue
                ts_code = f"{code}.SH" if code.startswith(('6', '9')) else f"{code}.SZ"
                try:
                    df = pro.daily(
                        ts_code=ts_code,
                        start_date=buy_day,
                        end_date=latest_day,
                    )
                except Exception:
                    continue
                if df is None or len(df) == 0:
                    continue
                df = df.sort_values('trade_date').reset_index(drop=True)
                if df.iloc[0]['trade_date'] != buy_day:
                    continue
                buy_open = float(df.iloc[0]['open'])
                last_close = float(df.iloc[-1]['close'])
                if buy_open <= 0:
                    continue
                ret = (last_close - buy_open) / buy_open * 100
                total_ret += ret
                if ret > 0:
                    wins += 1
                elif ret < 0:
                    losses += 1
                rows_data.append({
                    'rank': s.get('rank'),
                    'code': code,
                    'name': s.get('name') or '',
                    'score': s.get('score'),
                    'buy_open': buy_open,
                    'last_close': last_close,
                    'ret': ret,
                    'days': len(df),
                })

            if not rows_data:
                return []

            n = len(rows_data)
            avg_ret = total_ret / n
            wr = wins / n * 100 if n else 0
            tag = '✅' if avg_ret > 0 else ('🟡' if avg_ret > -1 else '❌')

            lines = []
            lines.append("\n## 📅 昨日选股复盘")
            lines.append(
                f"\n> **上一份报告**: ({prev_date_iso}) | "
                f"**买入日**: {buy_day[:4]}-{buy_day[4:6]}-{buy_day[6:8]} 开盘 → "
                f"**截至**: {latest_day[:4]}-{latest_day[4:6]}-{latest_day[6:8]} 收盘 | "
                f"{tag} **平均收益 {avg_ret:+.2f}%** | 胜率 {wr:.1f}% ({wins}赚 / {losses}亏 / {n - wins - losses}平)"
            )
            lines.append('<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 13px;">')
            lines.append('<thead><tr><th>原排名</th><th>代码</th><th>股票</th><th>原评分</th><th>买入价</th><th>最新价</th><th>持有N日</th><th>累计涨跌</th></tr></thead>')
            lines.append('<tbody>')
            rows_data.sort(key=lambda x: -x['ret'])
            for r in rows_data:
                color = '#2e7d32' if r['ret'] > 0 else ('#c62828' if r['ret'] < 0 else '#666')
                lines.append(
                    f'<tr><td style="text-align: center;">#{r["rank"]}</td>'
                    f'<td style="text-align: center;">{r["code"]}</td>'
                    f'<td>{r["name"]}</td>'
                    f'<td style="text-align: center;">{(r["score"] or 0):.2f}</td>'
                    f'<td style="text-align: center;">{r["buy_open"]:.2f}</td>'
                    f'<td style="text-align: center;">{r["last_close"]:.2f}</td>'
                    f'<td style="text-align: center;">{r["days"]}</td>'
                    f'<td style="text-align: center; font-weight: bold; color: {color};">{r["ret"]:+.2f}%</td></tr>'
                )
            lines.append('</tbody></table>\n')
            return lines
        except Exception as e:
            logger.debug(f"昨日复盘段渲染失败: {e}")
            return []

    def generate_report(self, analysis_results: List[Dict],
                       report_title: str = "投资机会挖掘报告",
                       global_hot_news: List[Dict] = None,
                       sector_hot_news: List[Dict] = None,
                       hot_news_title: str = None,
                       market_regime: Optional[Dict] = None,
                       run_meta: Optional[Dict] = None) -> str:
        """
        生成投资机会挖掘HTML报表

        Args:
            analysis_results: 分析结果列表，每个元素是OpportunityFilter的输出
            report_title: 报告标题

        Returns:
            生成的HTML文件路径
        """
        logger.info(f"开始生成投资机会挖掘报表...")
        analysis_results = self._filter_st_analysis_results(analysis_results, "报表生成")

        # 统计数据
        total_count = len(analysis_results)
        passed_stocks = [r for r in analysis_results if r.get('passed', False)]
        passed_count = len(passed_stocks)

        # 按阶段统计淘汰情况
        stage_stats = self._calculate_stage_statistics(analysis_results)

        # 生成漏斗数据
        funnel_data = self._generate_funnel_data(stage_stats, total_count)

        degraded_count = sum(1 for stock in passed_stocks if _is_degraded_opportunity(stock))
        if degraded_count:
            logger.warning(
                "机会挖掘存在数据降级候选: %s/%s，Top榜排序将优先展示非降级样本",
                degraded_count,
                passed_count,
            )

        # TOP 推荐（完整排序，前端默认显示20行并可滚动）
        # 历史行情缺失时，情绪/消息分可能把降级样本推高；排序层必须把正常样本放在前面。
        top_20 = sorted(
            passed_stocks,
            key=lambda stock: (not _is_degraded_opportunity(stock), _stock_final_score(stock)),
            reverse=True,
        )

        # 量化优先排名（量化模型数量优先 + 分数排名）
        def quant_sort_key(stock):
            score = _stock_final_score(stock)
            details = (stock.get('scoring_result') or {}).get('details') or {}
            quant = details.get('quantitative') or {}
            models = quant.get('top_buy_models') or []
            model_count = len(models)
            return (not _is_degraded_opportunity(stock), model_count, score)

        quant_top_20 = sorted(passed_stocks, key=quant_sort_key, reverse=True)

        # 按淘汰阶段分组
        grouped_stocks = self._group_by_elimination_stage(analysis_results)

        # 记录热门话题，供Markdown报表复用
        self._latest_global_hot_news = global_hot_news or []

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_filename = f"opportunity_discovery_{timestamp}.html"
        filepath = os.path.join(self.output_dir, html_filename)

        try:
            md_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            md_filename = f"opportunity_top10_{md_timestamp}.md"
            md_path = os.path.join(self.output_dir, md_filename)
            current_report_dt = datetime.strptime(md_timestamp, "%Y%m%d_%H%M%S")

            MODEL_DISPLAY_MAP = {
                'balance_dual_moving': '均衡双均线', 'multi_breakthrough': '多重突破', 'support_resistance': '支撑阻力',
                'trend_pullback': '趋势回踩', 'ma_resonance': '均线共振', 'super_reversal': '超级反转',
                'capital_trend': '资金趋势', 'volume_breakthrough': '量能突破', 'three_sisters': '三姐妹形态',
                'macd_axis_golden_cross': '轴心MACD金叉', 'six_dimension_resonance': '六维共振',
                'statistical_quantitative': '统计量化', 'super_profit_limit_up': '超额涨停',
                'turtle_trading_system': '海龟交易', 'atr_momentum': 'ATR动量', 'cta_trend_strategy': 'CTA趋势',
                'machine_learning_rf': '机器学习RF', 'multi_factor_alpha': '多因子Alpha',
                'pairs_trading_arbitrage': '配对交易套利', 'hft_microstructure': '高频微结构',
                'ichimoku_cloud': '一目均衡云', 'bollinger_squeeze': '布林收敛', 'rsi_divergence': 'RSI背离',
                'stochastic_momentum': '随机动量', 'volume_price_trend': '量价趋势', 'parabolic_sar': '抛物转向SAR',
                'chaikin_money_flow': '切金资金流', 'elder_ray': 'Elder射线', 'vwap_deviation': 'VWAP偏离',
                'fractal_adaptive_ma': '分形自适应均线'
            }

            lines = []

            # === 运行元信息: 机器可读注释 + 人可读一行(桌面端/解析器用于区分 run 与评分版本) ===
            if run_meta:
                try:
                    _meta_payload = {
                        'run_at': run_meta.get('run_at'),
                        'source': run_meta.get('source'),
                        'candidate_limit': run_meta.get('candidate_limit'),
                        'mode': run_meta.get('mode'),
                        'ruleset_version': run_meta.get('ruleset_version'),
                        'config_hash': run_meta.get('config_hash'),
                        'candidates': run_meta.get('candidates'),
                        'analyzed': run_meta.get('analyzed'),
                    }
                    lines.append(f"<!-- kronos-run-meta {json.dumps(_meta_payload, ensure_ascii=False)} -->")
                    _meta_bits = [f"运行 {str(run_meta.get('run_at') or '')[:16].replace('T', ' ')}"]
                    if run_meta.get('ruleset_version'):
                        _meta_bits.append(f"评分规则 {run_meta['ruleset_version']}")
                    if run_meta.get('source'):
                        _meta_bits.append(f"来源 {run_meta['source']}")
                    if run_meta.get('candidate_limit'):
                        _meta_bits.append(f"候选上限 {run_meta['candidate_limit']}")
                    if run_meta.get('config_hash'):
                        _meta_bits.append(f"配置 {run_meta['config_hash']}")
                    lines.append(f"> 🧾 {' · '.join(_meta_bits)}\n")
                except Exception as _me:
                    logger.debug(f"运行元信息写入失败: {_me}")

            if degraded_count:
                if passed_count and degraded_count == passed_count:
                    lines.append("## 🛑 数据质量提示")
                    lines.append(
                        '<div style="border: 2px solid #d32f2f; background: #ffebee; '
                        'padding: 12px; border-radius: 6px; font-size: 14px;">'
                        '<p style="margin: 4px 0;"><strong>本次机会挖掘全部候选缺少有效历史行情数据。</strong>'
                        '量化与技术评分已降级，Top 榜仅用于诊断，不应视为正常推荐。</p>'
                        '<p style="margin: 8px 0 0;">请检查 TuShare token、网络与本地 K 线缓存后重新运行。</p>'
                        '</div>'
                    )
                    lines.append("---\n")
                else:
                    lines.append(
                        f"> ⚠️ 本次有 {degraded_count}/{passed_count} 只候选缺少有效历史行情数据，"
                        "已在 Top 榜排序中排到非降级样本之后。\n"
                    )

            # === 头部增强: 昨日推荐复盘 + 大盘环境/候选不足提示 ===
            try:
                _recap = self._build_yesterday_recap(current_report_dt)
                if _recap:
                    lines.extend(_recap)
                    lines.append("---\n")
            except Exception as _re:
                logger.debug(f"昨日复盘失败: {_re}")

            try:
                _s_count = sum(1 for _s in top_20 if _stock_final_score(_s) >= 85)
                _a_count = sum(1 for _s in top_20 if 78 <= _stock_final_score(_s) < 85)
                _alert = self._build_market_regime_alert(market_regime, _s_count, _a_count, passed_count)
                if _alert:
                    lines.extend(_alert)
                    lines.append("---\n")
            except Exception as _ae:
                logger.debug(f"大盘提示失败: {_ae}")

            lines.append("## 🏆 综合排名 TOP20")
            lines.append('<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 14px;">')
            lines.append('<thead><tr><th>排名</th><th>代码</th><th>股票名称</th><th>综合得分</th><th>详细分析</th></tr></thead>')
            lines.append('<tbody>')

            recent_repeat_map = self._collect_recent_repeat_entries(
                [stock.get('stock_code') or stock.get('code') for stock in top_20[:20]],
                current_report_dt=current_report_dt,
                window_days=None
            )

            for i, stock in enumerate(top_20[:20], 1):
                code = _normalize_stock_code(stock.get('stock_code') or stock.get('code') or '未知') or '未知'
                name_txt = self._resolve_stock_display_name_from_reports(
                    code=code,
                    name=stock.get('name'),
                    stock_name=stock.get('stock_name'),
                    default=code,
                )
                score = float(stock.get('final_score', 0) or 0)

                summary_txt = (self._build_full_indicator_summary(stock) or "").replace('<br>', '；')
                advanced_txt = self._build_advanced_analysis_summary(stock)
                repeat_summary = self._build_recent_repeat_selection_summary(
                    code,
                    recent_repeat_map.get(code),
                    window_days=None
                )

                analysis_parts = []
                if repeat_summary:
                    analysis_parts.append(repeat_summary)
                if summary_txt:
                    analysis_parts.append(summary_txt)
                if advanced_txt and advanced_txt != "—":
                    analysis_parts.append(f"【高级】{advanced_txt}")
                full_analysis = "；".join(part for part in analysis_parts if part)
                
                lines.append(f'<tr><td style="text-align: center;">{i}</td><td style="text-align: center;">{code}</td><td>{name_txt}</td><td style="text-align: center;">{score:.2f}</td><td>{full_analysis}</td></tr>')

            lines.append('</tbody></table>')

            # v8.0: 添加置信度分级统计 + 历史回测表现
            lines.append("\n---\n")
            lines.append("## 📈 置信度分级 & 历史回测表现\n")

            # 当日推荐的置信度分布
            tier_counts = {'S': 0, 'A': 0, 'B': 0, 'C': 0}

            def _resolve_tier_by_display_score(stock_item: Dict) -> str:
                try:
                    score_val = float(stock_item.get('final_score', 0) or 0)
                except Exception:
                    score_val = 0.0
                if score_val >= 85:
                    return 'S'
                if score_val >= 78:
                    return 'A'
                if score_val >= 70:
                    return 'B'
                return 'C'

            for stock in top_20[:20]:
                tier = _resolve_tier_by_display_score(stock)
                if tier in tier_counts:
                    tier_counts[tier] += 1

            lines.append("### 当日推荐置信度分布")
            lines.append('<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 14px;">')
            lines.append('<thead><tr><th>置信度</th><th>说明</th><th>数量</th></tr></thead>')
            lines.append('<tbody>')
            tier_info = [
                ('S', '强烈推荐(≥85分)'),
                ('A', '可考虑(≥78分)'),
                ('B', '谨慎(≥70分)'),
                ('C', '不建议(<70分)')
            ]
            for tier, desc in tier_info:
                count = tier_counts.get(tier, 0)
                lines.append(f'<tr><td style="text-align: center; font-weight: bold;">{tier}</td><td>{desc}</td><td style="text-align: center;">{count}</td></tr>')
            lines.append('</tbody></table>')

            # 历史回测统计（使用 v8.0 评分的回测分析数据）
            try:
                import json as _json
                import pandas as _pd

                bt_with_returns, _score_col, _cutoff_dt, _window_start_dt = self._prepare_backtest_history(current_report_dt)

                # 自动补充缺失的收益数据
                if bt_with_returns is not None and len(bt_with_returns) >= 10:
                    _missing_mask = bt_with_returns['return_10d'].isna() & bt_with_returns['return_5d'].notna()
                    _missing_count = _missing_mask.sum()
                    if _missing_count > 0:
                        try:
                            _token = load_tushare_token()
                            if _token:
                                import tushare as _ts
                                _ts.set_token(_token)
                                _pro = _ts.pro_api()
                                _filled = 0
                                for _idx in bt_with_returns[_missing_mask].index:
                                    try:
                                        _code = str(int(bt_with_returns.at[_idx, 'code'])).zfill(6)
                                        _rd = str(bt_with_returns.at[_idx, 'report_date']).replace('-', '')
                                        _ts_code = f"{_code}.SH" if _code.startswith(('6', '9')) else f"{_code}.SZ"
                                        _price_df = _pro.daily(
                                            ts_code=_ts_code,
                                            start_date=_rd,
                                            end_date=current_report_dt.strftime('%Y%m%d')
                                        )
                                        if _price_df is not None and len(_price_df) > 0:
                                            _price_df = _price_df.sort_values('trade_date').reset_index(drop=True)
                                            _buy_idx = None
                                            for _i, _d in enumerate(_price_df['trade_date'].tolist()):
                                                if _d > _rd:
                                                    _buy_idx = _i
                                                    break
                                            if _buy_idx is not None and _buy_idx + 10 <= len(_price_df):
                                                _bp = _price_df.iloc[_buy_idx]['open']
                                                if _bp > 0:
                                                    _p10 = _price_df.iloc[_buy_idx + 9]['close']
                                                    bt_with_returns.at[_idx, 'return_10d'] = (_p10 - _bp) / _bp * 100
                                                    _filled += 1
                                                    # 同时补充5d如果也缺失
                                                    if _pd.isna(bt_with_returns.at[_idx, 'return_5d']) and _buy_idx + 5 <= len(_price_df):
                                                        _p5 = _price_df.iloc[_buy_idx + 4]['close']
                                                        bt_with_returns.at[_idx, 'return_5d'] = (_p5 - _bp) / _bp * 100
                                    except Exception:
                                        pass
                                if _filled > 0:
                                    logger.info(f"自动补充了 {_filled}/{_missing_count} 条缺失的10日收益数据")
                        except Exception as _fill_err:
                            logger.debug(f"自动补充收益数据失败: {_fill_err}")

                if bt_with_returns is not None and len(bt_with_returns) >= 10:
                    lines.append("\n> **备注**: 每月第一个交易日将根据前一个月量化选股结果进行AI自我回测及算法优化，如有需求意见也可在留言中反馈，如有AI相关业务落地咨询的可私聊博主。\n")
                    lines.append("\n### 历史回测表现（基于已验证数据）")
                    if _cutoff_dt is not None:
                        lines.append(
                            f"\n**统计窗口**: {_window_start_dt.strftime('%Y-%m-%d')} ~ {_cutoff_dt.strftime('%Y-%m-%d')}"
                            f"（先预留最近10个交易日，再向前回看1个月）\n"
                        )
                    lines.append("\n**样本口径**: 历史每日Top10推荐（不是全量候选池），因此高分样本占比会明显更高。\n**交易规则**: 报告次日开盘价买入，第5个交易日收盘价卖出（年化按 252/5≈50.4 次复利估算）。")
                    lines.append('<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 13px;">')
                    lines.append('<thead><tr><th>评分区间</th><th>数量</th><th>5日均收益</th><th>5日胜率</th><th>10日均收益</th><th>盈亏比</th><th>年化估算</th></tr></thead>')
                    lines.append('<tbody>')

                    score_bins = [
                        (85, 999, 'S 级 (≥85分)', '#d32f2f'),
                        (80, 85, 'A 级 (80-85分)', '#f57c00'),
                        (70, 80, '70-80分', '#1565c0'),
                        (60, 70, '60-70分', '#757575'),
                        (0, 60, '60分以下', '#9e9e9e')
                    ]

                    _ANN_CYCLES = 252.0 / 5.0  # 5日持仓 → 一年约 50.4 次复利

                    for low, high, label, color in score_bins:
                        if high == 999:
                            subset = bt_with_returns[bt_with_returns[_score_col] >= low]
                        else:
                            subset = bt_with_returns[(bt_with_returns[_score_col] >= low) & (bt_with_returns[_score_col] < high)]

                        if len(subset) == 0:
                            lines.append(f'<tr><td style="font-weight: bold;">{label}</td><td style="text-align: center;">0</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>')
                            continue

                        r5 = subset['return_5d'].dropna()
                        r10 = subset['return_10d'].dropna()
                        if len(r5) > 0:
                            wr = (r5 > 0).mean() * 100
                            avg5 = r5.mean()
                            avg10_str = f"{r10.mean():+.2f}%" if len(r10) > 0 else "数据不足"
                            wins = r5[r5 > 0].sum()
                            losses = r5[r5 < 0].sum()
                            pf = abs(wins / losses) if losses != 0 else float('inf')
                            pf_str = f"{pf:.2f}" if pf != float('inf') else "∞"
                            try:
                                ann = ((1 + avg5 / 100.0) ** _ANN_CYCLES - 1) * 100
                                ann_str = f"{ann:+.1f}%"
                            except Exception:
                                ann_str = "—"
                            lines.append(f'<tr><td style="font-weight: bold; color: {color};">{label}</td><td style="text-align: center;">{len(subset)}</td><td style="text-align: center;">{avg5:+.2f}%</td><td style="text-align: center;">{wr:.1f}%</td><td style="text-align: center;">{avg10_str}</td><td style="text-align: center;">{pf_str}</td><td style="text-align: center; font-weight: bold;">{ann_str}</td></tr>')
                        else:
                            lines.append(f'<tr><td style="font-weight: bold; color: {color};">{label}</td><td style="text-align: center;">{len(subset)}</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>')
                    lines.append('</tbody></table>')

                    # 核心阈值提示（按80分以上统计）
                    _above80 = bt_with_returns[bt_with_returns[_score_col] >= 80]
                    _r5_80 = _above80['return_5d'].dropna()
                    if len(_r5_80) > 0:
                        try:
                            _ann80 = ((1 + _r5_80.mean() / 100.0) ** _ANN_CYCLES - 1) * 100
                            _ann80_str = f" | 年化估算: {_ann80:+.1f}%"
                        except Exception:
                            _ann80_str = ""
                        lines.append(f"\n**核心统计(评分≥80)**: {len(_above80)}条 | "
                                    f"已验证{len(_r5_80)}条 | "
                                    f"5日胜率: {(_r5_80 > 0).mean()*100:.1f}% | "
                                    f"5日均收益: {_r5_80.mean():+.2f}%"
                                    f"{_ann80_str}")

                    # 全样本统计
                    total_r5 = bt_with_returns['return_5d'].dropna()
                    _total_rows = len(bt_with_returns)
                    _verified_rows = len(total_r5)
                    _date_min = bt_with_returns['report_date'].min()
                    _date_max = bt_with_returns['report_date'].max()
                    if len(total_r5) > 0:
                        _pending = _total_rows - _verified_rows
                        _pending_str = f"(其中{_pending}条待验证)" if _pending > 0 else ""
                        try:
                            _ann_total = ((1 + total_r5.mean() / 100.0) ** _ANN_CYCLES - 1) * 100
                            _ann_total_str = f" | 年化估算: {_ann_total:+.1f}%"
                        except Exception:
                            _ann_total_str = ""
                        lines.append(f"\n**全样本**: {_total_rows}条{_pending_str} | "
                                    f"已验证{_verified_rows}条 | "
                                    f"5日均收益: {total_r5.mean():+.2f}% | "
                                    f"5日胜率: {(total_r5 > 0).mean()*100:.1f}%"
                                    f"{_ann_total_str} | "
                                    f"数据范围: {_date_min} ~ {_date_max}")

                    # 分档收益分布
                    lines.append("\n### 收益分档分布")
                    _return_col = 'return_5d'
                    _valid = bt_with_returns.dropna(subset=[_return_col])
                    _has_name = 'name' in _valid.columns
                    _has_date = 'report_date' in _valid.columns

                    lines.append('<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 13px;">')
                    lines.append('<thead><tr><th>5日收益区间</th><th>数量</th><th>占比</th><th>代表个股</th></tr></thead>')
                    lines.append('<tbody>')

                    _tiers = [
                        (50, '≥50%'),
                        (30, '≥30%'),
                        (10, '≥10%'),
                        (0, '≥0%(盈利)'),
                        (-10, '-10%~0%'),
                        (-9999, '<-10%'),
                    ]

                    for _ti, (_threshold, _label) in enumerate(_tiers):
                        if _threshold == -9999:
                            _tier_df = _valid[_valid[_return_col] < -10]
                        elif _threshold == 0:
                            _tier_df = _valid[(_valid[_return_col] >= 0) & (_valid[_return_col] < 10)]
                        elif _threshold == -10:
                            _tier_df = _valid[(_valid[_return_col] >= -10) & (_valid[_return_col] < 0)]
                        else:
                            _next_t = _tiers[_ti - 1][0] if _ti > 0 else 9999
                            if _next_t == 9999:
                                _tier_df = _valid[_valid[_return_col] >= _threshold]
                            else:
                                _tier_df = _valid[(_valid[_return_col] >= _threshold) & (_valid[_return_col] < _next_t)]

                        _cnt = len(_tier_df)
                        _pct = _cnt / len(_valid) * 100

                        _examples = ""
                        if _cnt > 0:
                            _top = _tier_df.nlargest(min(3, _cnt), _return_col)
                            _parts = []
                            for _, _row in _top.iterrows():
                                _sname = self._resolve_stock_display_name_from_reports(
                                    code=_row.get('code'),
                                    name=_row.get('name'),
                                    stock_name=_row.get('stock_name'),
                                    default='未知'
                                )
                                _sdate = str(_row.get('report_date', ''))[:10] if _has_date else ''
                                _sret = _row[_return_col]
                                if _sdate:
                                    _parts.append(f"{_sname}({_sdate},{_sret:+.1f}%)")
                                else:
                                    _parts.append(f"{_sname}({_sret:+.1f}%)")
                            _examples = " ".join(_parts)

                        lines.append(f'<tr><td style="font-weight: bold; text-align: center;">{_label}</td><td style="text-align: center;">{_cnt}</td><td style="text-align: center;">{_pct:.1f}%</td><td>{_examples}</td></tr>')
                    lines.append('</tbody></table>')
            except Exception as _e:
                logger.debug(f"回测统计加载失败: {_e}")
                pass  # 无回测数据时静默跳过

            # 添加股吧话题精选（如果有）
            topics = getattr(self, '_latest_global_hot_news', None)
            if topics:
                lines.append("\n---\n")
                lines.append("## 💬 股吧话题精选\n")
                idx = 1
                for t in topics:
                    title = t.get('title', '') or ''
                    if not title or '【有奖】' in title:
                        continue
                    raw_url = t.get('url', '') or ''
                    url = self._normalize_topic_url(raw_url, title)
                    heat = t.get('heat', 0)
                    safe_title = title.replace('[', '\\[').replace(']', '\\]')
                    lines.append(f'{idx}. [{safe_title}]({url}) - 热度: {heat}')
                    idx += 1

            # 添加板块分组股票表格
            lines.append("\n---\n")
            lines.append("## 📊 热点股票板块分布")
            lines.append('<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 14px;">')
            lines.append('<thead><tr><th>所属板块</th><th>股票列表</th></tr></thead>')
            lines.append('<tbody>')

            # 按板块分组所有股票，存储板块涨幅
            sector_stocks = {}
            sector_change_candidates = {}
            sector_name_by_code = {}
            stock_name_by_code = {}

            def _is_numeric_text(text) -> bool:
                try:
                    stripped = str(text).strip()
                except Exception:
                    return False
                if not stripped:
                    return False
                if stripped.startswith(('+', '-')):
                    stripped = stripped[1:]
                if stripped.count('.') > 1:
                    return False
                parts = stripped.split('.')
                if not all(p.isdigit() for p in parts if p != ''):
                    return False
                return any(p != '' for p in parts)

            def _pick_sector_change(candidates):
                if not candidates:
                    return None
                usable = []
                for c in candidates:
                    if c is None:
                        continue
                    if isinstance(c, bool):
                        continue
                    if isinstance(c, (int, float)):
                        usable.append(float(c))
                        continue
                    if isinstance(c, str):
                        s = c.strip()
                        if not s or _is_numeric_text(s) is False:
                            continue
                        try:
                            usable.append(float(s))
                        except Exception:
                            continue
                if not usable:
                    return None
                rounded = [round(v, 2) for v in usable]
                freq = {}
                for v in rounded:
                    freq[v] = freq.get(v, 0) + 1
                best = max(freq.items(), key=lambda x: (x[1], abs(x[0])))[0]
                return float(best)

            def _to_float_or_none(v):
                if v is None or isinstance(v, bool):
                    return None
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str):
                    s = v.strip().replace('%', '')
                    if not s:
                        return None
                    try:
                        return float(s)
                    except Exception:
                        return None
                return None

            def _is_valid_sector_name(name: str) -> bool:
                if name is None:
                    return False
                s = str(name).strip()
                if not s:
                    return False
                if s in ('未知', 'unknown', 'Unknown', 'N/A', 'None', 'nan'):
                    return False
                if _is_numeric_text(s):
                    return False
                return True

            def _load_sector_from_tushare(code: str):
                if not code:
                    return None
                if code in sector_name_by_code:
                    return sector_name_by_code.get(code)
                try:
                    from analysis.sector_api import _get_industry_from_tushare
                    info = _get_industry_from_tushare(code)
                    if info:
                        sec = str(info.get('sector_name') or '').strip()
                        nm = str(info.get('stock_name') or '').strip()
                        if _is_valid_sector_name(sec):
                            sector_name_by_code[code] = sec
                        if nm:
                            stock_name_by_code[code] = nm
                except Exception:
                    pass
                return sector_name_by_code.get(code)

            def _resolve_sector_and_change(stock: Dict):
                scoring_result = stock.get('scoring_result') or {}
                details = scoring_result.get('details') or {}
                sector = details.get('sector') or {}
                advanced = stock.get('advanced_analysis') or scoring_result.get('advanced_analysis') or {}
                dimensions = advanced.get('dimensions', {}) if isinstance(advanced, dict) else {}
                adv_sector = (dimensions.get('sector') or {}).get('details', {}) if isinstance(dimensions, dict) else {}
                adv_cn_sector = advanced.get('板块联动', {}) if isinstance(advanced, dict) else {}

                candidates = [
                    sector.get('sector_name'),
                    adv_sector.get('sector_name'),
                    adv_cn_sector.get('sector_name'),
                    adv_cn_sector.get('所属板块'),
                    stock.get('sector_name'),
                    stock.get('industry')
                ]
                sector_name = ''
                for cand in candidates:
                    if _is_valid_sector_name(cand):
                        sector_name = str(cand).strip()
                        break

                change_candidates = [
                    {
                        'change': sector.get('change_pct'),
                        'turnover': sector.get('turnover_rate'),
                        'score': scoring_result.get('scores', {}).get('sector'),
                        'overall': sector.get('overall'),
                        'data_source': sector.get('data_source'),
                        'leader_stock': sector.get('leader_stock')
                    },
                    {
                        'change': sector.get('sector_change'),
                        'turnover': sector.get('turnover_rate'),
                        'score': scoring_result.get('scores', {}).get('sector'),
                        'overall': sector.get('overall'),
                        'data_source': sector.get('data_source'),
                        'leader_stock': sector.get('leader_stock')
                    },
                    {
                        'change': adv_sector.get('change_pct'),
                        'turnover': adv_sector.get('turnover_rate'),
                        'overall': adv_sector.get('overall'),
                        'data_source': adv_sector.get('data_source'),
                        'leader_stock': adv_sector.get('leader_stock')
                    },
                    {
                        'change': adv_sector.get('sector_change'),
                        'turnover': adv_sector.get('turnover_rate'),
                        'overall': adv_sector.get('overall'),
                        'data_source': adv_sector.get('data_source'),
                        'leader_stock': adv_sector.get('leader_stock')
                    },
                    {
                        'change': adv_cn_sector.get('change_pct'),
                        'turnover': adv_cn_sector.get('turnover_rate'),
                        'overall': adv_cn_sector.get('overall'),
                        'data_source': adv_cn_sector.get('data_source'),
                        'leader_stock': adv_cn_sector.get('leader_stock')
                    },
                    {
                        'change': adv_cn_sector.get('板块涨跌'),
                        'turnover': adv_cn_sector.get('换手率'),
                        'overall': adv_cn_sector.get('板块情绪'),
                        'data_source': adv_cn_sector.get('data_source'),
                        'leader_stock': adv_cn_sector.get('龙头股')
                    }
                ]
                sector_chg = None
                for cand in change_candidates:
                    val = _get_displayable_sector_change(
                        cand.get('change'),
                        turnover_value=cand.get('turnover'),
                        score=cand.get('score'),
                        overall=cand.get('overall'),
                        data_source=cand.get('data_source'),
                        leader_stock=cand.get('leader_stock')
                    )
                    if val is not None:
                        sector_chg = val
                        break

                code = str(stock.get('stock_code') or stock.get('code') or '').strip()
                if not _is_valid_sector_name(sector_name):
                    cached_sector = _load_sector_from_tushare(code)
                    if _is_valid_sector_name(cached_sector):
                        sector_name = cached_sector

                if not _is_valid_sector_name(sector_name):
                    sector_name = '其他'

                return sector_name, sector_chg

            def _resolve_stock_name(stock: Dict):
                code = _normalize_stock_code(stock.get('stock_code') or stock.get('code') or '')
                resolved = self._resolve_stock_display_name_from_reports(
                    code=code,
                    name=stock.get('name'),
                    stock_name=stock.get('stock_name'),
                    default=code or '未知',
                )
                if resolved and resolved not in ('未知', code):
                    return resolved
                if code:
                    _load_sector_from_tushare(code)
                    cached_name = stock_name_by_code.get(code)
                    if not _is_missing_display_value(cached_name):
                        return str(cached_name).strip()
                return _pick_stock_display_name(None, None, code)

            for stock in analysis_results:
                sector_name, sector_chg = _resolve_sector_and_change(stock)

                if sector_name not in sector_stocks:
                    sector_stocks[sector_name] = []
                    sector_change_candidates[sector_name] = []
                sector_change_candidates[sector_name].append(sector_chg)
                sector_stocks[sector_name].append(stock)

            # 如果没有板块数据，提示用户
            if not sector_stocks:
                lines.append("| 暂无板块数据 | — |")
            else:
                # 按股票数量降序排序，相同数量的按涨幅降序排序
                sorted_sectors = sorted(
                    sector_stocks.items(),
                    key=lambda x: (-len(x[1]), _pick_sector_change(sector_change_candidates.get(x[0])) or 0),
                    reverse=False
                )

                # 输出每个板块
                for sector_name, stocks in sorted_sectors:
                    sector_chg = _pick_sector_change(sector_change_candidates.get(sector_name))
                    if sector_chg is not None:
                        sector_chg_str = f"{sector_chg:+.2f}%"
                        sector_header = f"{sector_name}({sector_chg_str})"
                    else:
                        sector_header = sector_name

                    stock_parts = []
                    for stock in stocks:
                        code = _normalize_stock_code(stock.get('stock_code') or stock.get('code') or '未知') or '未知'
                        name = _resolve_stock_name(stock)
                        price_changes = stock.get('scoring_result', {}).get('details', {}).get('price_changes', {})
                        change_pct = price_changes.get('change_1d') if price_changes else None
                        
                        if change_pct is not None:
                            change_str = f"{change_pct:+.2f}%"
                            stock_parts.append(f"**{name}({code})** {change_str}")
                        else:
                            stock_parts.append(f"**{name}({code})**")

                    stocks_str = " ".join(stock_parts)
                    lines.append(f'<tr><td style="font-weight: bold;">{sector_header}</td><td>{stocks_str}</td></tr>')

            lines.append('</tbody></table>')

            # 添加个股资金流向（流入前20 + 流出前20）
            try:
                top_list_data = self._fetch_top_list()
                if top_list_data:
                    lines.append("\n---\n")
                    td = top_list_data.get('trade_date', '')
                    date_display = f"{td[:4]}-{td[4:6]}-{td[6:]}" if len(td) == 8 else td
                    lines.append(f"## 💰 个股资金流向（{date_display}）")

                    def fmt_amount(val):
                        if abs(val) >= 10000:
                            return f"{val/10000:.2f}亿"
                        else:
                            return f"{val:.0f}万"

                    # 流入前20
                    inflow = top_list_data.get('inflow', [])
                    if inflow:
                        lines.append("### 🔴 主力净流入 TOP 20")
                        lines.append('<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 13px;">')
                        lines.append('<thead><tr><th>#</th><th>股票</th><th>资金流向明细</th></tr></thead>')
                        lines.append('<tbody>')
                        for idx, item in enumerate(inflow, 1):
                            code = item.get('code', '')
                            name = item.get('name', '')
                            close = item.get('close', 0)
                            pct = item.get('pct_change', 0)
                            net = item.get('net_amount', 0)
                            net_rate = item.get('net_amount_rate', 0)
                            elg = item.get('buy_elg_amount', 0)
                            lg = item.get('buy_lg_amount', 0)
                            pct_str = f"{pct:+.2f}%" if pct >= 0 else f"{pct:.2f}%"
                            net_str = f"{net/10000:.2f}亿" if abs(net) >= 10000 else f"{net:.0f}万"
                            elg_str = f"{elg/10000:.2f}亿" if abs(elg) >= 10000 else f"{elg:.0f}万"
                            lg_str = f"{lg/10000:.2f}亿" if abs(lg) >= 10000 else f"{lg:.0f}万"
                            lines.append(f'<tr><td style="text-align: center;">{idx}</td><td><strong>{name}</strong>({code})</td><td>最新价: {close:.2f} | 涨跌幅: {pct_str} | 主力净流入: {net_str} | 净占比: {net_rate:+.1f}% | 超大单净流入: {elg_str} | 大单净流入: {lg_str}</td></tr>')
                        lines.append('</tbody></table>')
                        lines.append("")

                    # 流出前20
                    outflow = top_list_data.get('outflow', [])
                    if outflow:
                        lines.append("### 🟢 主力净流出 TOP 20")
                        lines.append('<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%; font-size: 13px;">')
                        lines.append('<thead><tr><th>#</th><th>股票</th><th>资金流向明细</th></tr></thead>')
                        lines.append('<tbody>')
                        for idx, item in enumerate(outflow, 1):
                            code = item.get('code', '')
                            name = item.get('name', '')
                            close = item.get('close', 0)
                            pct = item.get('pct_change', 0)
                            net = item.get('net_amount', 0)
                            net_rate = item.get('net_amount_rate', 0)
                            elg = item.get('buy_elg_amount', 0)
                            lg = item.get('buy_lg_amount', 0)
                            pct_str = f"{pct:+.2f}%" if pct >= 0 else f"{pct:.2f}%"
                            net_str = f"{net/10000:.2f}亿" if abs(net) >= 10000 else f"{net:.0f}万"
                            elg_str = f"{elg/10000:.2f}亿" if abs(elg) >= 10000 else f"{elg:.0f}万"
                            lg_str = f"{lg/10000:.2f}亿" if abs(lg) >= 10000 else f"{lg:.0f}万"
                            lines.append(f'<tr><td style="text-align: center;">{idx}</td><td><strong>{name}</strong>({code})</td><td>最新价: {close:.2f} | 涨跌幅: {pct_str} | 主力净流出: {net_str} | 净占比: {net_rate:+.1f}% | 超大单净流入: {elg_str} | 大单净流入: {lg_str}</td></tr>')
                        lines.append('</tbody></table>')
                        lines.append("")
            except Exception as e:
                logger.warning(f"生成资金流向Markdown失败: {e}")

            # 添加LLM智能分析结果
            llm_stocks = [s for s in top_20[:20] if s.get('llm_analysis')]
            if llm_stocks:
                lines.append("\n---\n")
                lines.append("## 🤖 AI智能分析结果\n")
                for stock in llm_stocks:
                    llm_result = stock.get('llm_analysis', {})
                    stock_code = _normalize_stock_code(stock.get('stock_code') or stock.get('code') or '')
                    stock_name = self._resolve_stock_display_name_from_reports(
                        code=stock_code,
                        name=stock.get('name'),
                        stock_name=stock.get('stock_name'),
                        default=stock_code or '未知',
                    )
                    rating = stock.get('rating', 'C')

                    lines.append(f"### {stock_name}({stock_code}) - {rating}级\n")

                    # 处理多模型或单模型结果
                    results_to_show = []
                    # 检查是否为多模型结果（字典且key包含模型名称）
                    if isinstance(llm_result, dict) and len(llm_result) > 0:
                        # 判断是否为多模型格式（key包含"/"）或者包含已知模型名
                        def contains_model_name(k):
                            k_str = str(k)
                            # 如果包含"/"，则提取模型名部分
                            if '/' in k_str:
                                model_part = k_str.split('/')[-1].lower()
                            else:
                                model_part = k_str.lower()
                            return any(
                                model_part == n or model_part.startswith(n)
                                for n in ['qwen', 'deepseek', 'minimax', 'kimi', 'glm']
                            )

                        # 兼容：键名可能是 "DeepSeek-V4" 这类非纯模型名；
                        # 或键名不含厂商/分隔符，但值仍是标准LLM分析结构。
                        is_multi_model = (
                            any('/' in str(k) or contains_model_name(k) for k in llm_result.keys())
                            or any(
                                isinstance(v, dict) and any(
                                    kk in v for kk in ['operation_advice', 'risk_assessment', 'kline_prediction', 'strategy', 'summary']
                                )
                                for v in llm_result.values()
                            )
                        )
                        if is_multi_model:
                            for model_name, model_result in llm_result.items():
                                if isinstance(model_result, dict) and 'error' not in model_result:
                                    # 只提取模型名称部分（如 "Qwen" 而不是 "魔塔社区/Qwen"）
                                    display_name = model_name.split('/')[-1] if '/' in model_name else model_name
                                    results_to_show.append((display_name, model_result))
                    elif isinstance(llm_result, dict) and 'llm_model' in llm_result:
                        # 单模型旧格式
                        results_to_show.append((llm_result.get('llm_model', 'AI'), llm_result))

                    for model_name, result in results_to_show:
                        # 只显示模型名称，不显示厂商
                        model_display = model_name.split('/')[-1].upper() if model_name else 'AI'
                        lines.append(f"**[{model_display}] 分析:**\n")

                        # 操作建议
                        operation = result.get('operation_advice', {})
                        action = operation.get('action', '-')
                        position = operation.get('position_control', '-')
                        target = operation.get('target_price', '-')
                        stop_loss = operation.get('stop_loss', '-')
                        confidence = operation.get('confidence', 0)
                        lines.append(f"- **操作建议**: {action} | 仓位: {position} | 目标价: {target} | 止损: {stop_loss} | 置信度: {confidence*100:.0f}%")

                        # 风险评估
                        risk = result.get('risk_assessment', {})
                        risk_level = risk.get('risk_level', '-')
                        risk_score = risk.get('overall_score', 0)
                        risk_points = risk.get('risk_points', [])
                        lines.append(f"- **风险评估**: {risk_level}风险 | 评分: {risk_score} | 风险点: {', '.join(risk_points[:3]) if risk_points else '无'}")

                        # 趋势预测
                        kline = result.get('kline_prediction', {})
                        trend = kline.get('trend', '-')
                        pred_conf = kline.get('confidence', 0)
                        support = kline.get('support_levels', [])
                        resistance = kline.get('resistance_levels', [])
                        lines.append(f"- **趋势预测**: {trend} | 置信度: {pred_conf*100:.0f}% | 支撑: {support[:2]} | 阻力: {resistance[:2]}")

                        # 策略
                        strategy = result.get('strategy', {})
                        short_term = strategy.get('short_term', '')
                        mid_term = strategy.get('mid_term', '')
                        if short_term:
                            lines.append(f"- **短线策略**: {short_term}")
                        if mid_term:
                            lines.append(f"- **中线策略**: {mid_term}")

                        # 总结
                        summary = result.get('summary', '')
                        if summary:
                            lines.append(f"- **综合建议**: {summary}")

                        lines.append("")

            lines.append("\n---\n")
            lines.append("*免责声明：本软件仅为数据工具，不构成投资建议，股市有风险，投资需谨慎。*")

            # ── 从完整Markdown生成网页版HTML（参考markdown内容重新排版）──
            try:
                html_body = _md_to_html_body(lines)
                html_page = self._wrap_html_page(html_body, report_title)
                with open(filepath, 'w', encoding='utf-8') as hf:
                    hf.write(html_page)
                logger.info(f"✓ HTML报表已生成(基于MD): {filepath}")
            except Exception as _he:
                logger.warning(f"从Markdown生成HTML失败: {_he}")

            with open(md_path, 'w', encoding='utf-8') as mf:
                mf.write('\n'.join(lines))
            self.latest_top_report_path = md_path
            logger.info(f"✓ TOP20统计Markdown已生成: {md_path}")

            # 落结构化信号 sidecar（供「风险·机遇」大屏个股风险层使用，markdown 拿不到这些数值）
            try:
                from analysis.opportunity_scorer import write_signals_sidecar
                _sig_rows = []
                for _st in top_20:
                    _sr = _st.get('scoring_result') or {}
                    _det = _sr.get('details') or {}
                    _scores = _sr.get('scores') or {}
                    _mom = _det.get('momentum') or {}
                    _quant = _det.get('quantitative') or {}
                    _tech = _det.get('technical') or {}
                    _pc = _det.get('price_changes') or {}
                    _chase = (((_sr.get('advanced_analysis') or {}).get('overall_score') or {})
                              .get('risk_metrics') or {}).get('chase_risk_score')
                    if not _chase:  # 0/None -> 回退动量明细（与评分逻辑一致）
                        _chase = _mom.get('chase_risk_score')
                    _sig_rows.append({
                        'code': _normalize_stock_code(_st.get('stock_code') or _st.get('code')),
                        'name': self._resolve_stock_display_name_from_reports(
                            code=_st.get('stock_code') or _st.get('code'),
                            name=_st.get('name'),
                            stock_name=_st.get('stock_name'),
                            default=_normalize_stock_code(_st.get('stock_code') or _st.get('code')),
                        ),
                        'total_score': _st.get('final_score'),
                        'rating': _resolve_tier_by_display_score(_st),
                        'scores': {'sector': _scores.get('sector')},
                        # v24: degraded(数据缺失降级) 透传, 供回测重建/统计剔除
                        'degraded': bool(_sr.get('degraded') or _quant.get('degraded')
                                         or _quant.get('error') == '无历史数据'),
                        'risk_signals': {
                            'chase': _chase,
                            'rsi': _tech.get('RSI'),
                            'day_change': _pc.get('change_1d'),
                            'change_3d': _pc.get('change_3d'),
                            'change_5d': _pc.get('change_5d'),
                            'sell_signals': _quant.get('sell_count'),
                            'quant_score': _scores.get('quantitative'),
                        },
                    })
                write_signals_sidecar(_sig_rows, md_path)
                logger.info(f"✓ 结构化信号 sidecar 已生成: {os.path.splitext(md_path)[0]}.signals.json")
            except Exception as _se:  # sidecar 不可阻塞报告生成
                logger.warning(f"signals sidecar 写入失败: {_se}")

            try:
                from scripts.generate_xueqiu_article import generate as _gen_xueqiu
                xueqiu_path = _gen_xueqiu(md_path)
                logger.info(f"✓ 雪球长文版已生成: {xueqiu_path}")
            except Exception as _xe:
                logger.warning(f"生成雪球长文失败: {_xe}")
        except Exception as e:
            logger.warning(f"生成TOP20 Markdown失败: {e}")
        logger.info(f"✓ 报表生成完成: {filepath}")
        return filepath

    def _fetch_top_list(self, trade_date: str = None) -> Optional[Dict]:
        """
        获取个股资金流向数据 (Tushare moneyflow_dc接口)
        返回流入前20和流出前20

        Args:
            trade_date: 交易日期，格式YYYYMMDD，默认获取最近一个有数据的交易日

        Returns:
            {'inflow': [...], 'outflow': [...], 'trade_date': '20260308'}，获取失败返回None
        """
        try:
            import tushare as ts
        except ImportError:
            logger.warning("Tushare未安装，无法获取资金流向数据")
            return None

        token = load_tushare_token()

        if not token:
            logger.debug("Tushare Token未配置，跳过资金流向数据获取")
            return None

        try:
            pro = ts.pro_api(token)

            if not hasattr(pro, 'moneyflow_dc'):
                logger.warning("Tushare接口不支持moneyflow_dc，需要5000积分")
                return None

            max_back_days = 14

            def resolve_latest_trade_date(base_dt: datetime) -> str:
                base_str = base_dt.strftime('%Y%m%d')
                try:
                    start_str = (base_dt - timedelta(days=30)).strftime('%Y%m%d')
                    cal_df = pro.trade_cal(exchange='SSE', start_date=start_str, end_date=base_str, fields='cal_date,is_open')
                    if cal_df is not None and not cal_df.empty and 'is_open' in cal_df.columns:
                        if 'cal_date' in cal_df.columns:
                            cal_df = cal_df.sort_values('cal_date')
                        open_dates = cal_df.loc[cal_df['is_open'] == 1, 'cal_date'].tolist()
                        if open_dates:
                            return open_dates[-1]
                except Exception as e:
                    logger.debug(f"trade_cal不可用，回退使用日期回溯: {e}")
                candidate = base_dt
                for _ in range(max_back_days):
                    if candidate.weekday() < 5:
                        return candidate.strftime('%Y%m%d')
                    candidate -= timedelta(days=1)
                return base_str

            if not trade_date:
                now = datetime.now()
                if now.hour >= 15:
                    base_dt = now
                else:
                    base_dt = now - timedelta(days=1)
                trade_date = resolve_latest_trade_date(base_dt)

            import pandas as pd

            df = None
            base_try_dt = datetime.strptime(trade_date, '%Y%m%d')
            for i in range(max_back_days):
                try_date = (base_try_dt - timedelta(days=i)).strftime('%Y%m%d')
                try:
                    df = pro.moneyflow_dc(trade_date=try_date)
                    if df is not None and not df.empty:
                        trade_date = try_date
                        break
                except Exception:
                    continue
            else:
                logger.debug(f"资金流向数据为空，回溯{max_back_days}天仍无数据")
                return None

            if df is None or df.empty:
                return None

            df['net_amount'] = pd.to_numeric(df['net_amount'], errors='coerce').fillna(0)
            df['pct_change'] = pd.to_numeric(df.get('pct_change'), errors='coerce').fillna(0)
            df['close'] = pd.to_numeric(df.get('close'), errors='coerce').fillna(0)
            df['net_amount_rate'] = pd.to_numeric(df.get('net_amount_rate'), errors='coerce').fillna(0)
            df['buy_elg_amount'] = pd.to_numeric(df.get('buy_elg_amount'), errors='coerce').fillna(0)
            df['buy_lg_amount'] = pd.to_numeric(df.get('buy_lg_amount'), errors='coerce').fillna(0)

            # 流入前20
            top_inflow = df.nlargest(20, 'net_amount')
            # 流出前20
            top_outflow = df.nsmallest(20, 'net_amount')

            def row_to_dict(row):
                ts_code = str(row.get('ts_code', ''))
                return {
                    'code': ts_code.split('.')[0] if ts_code else '',
                    'name': _pick_display_text(row.get('name'), default=''),
                    'close': float(row.get('close', 0)),
                    'pct_change': float(row.get('pct_change', 0)),
                    'net_amount': float(row['net_amount']),
                    'net_amount_rate': float(row.get('net_amount_rate', 0)),
                    'buy_elg_amount': float(row.get('buy_elg_amount', 0)),
                    'buy_lg_amount': float(row.get('buy_lg_amount', 0)),
                }

            inflow_list, removed_inflow = filter_st_stocks(
                [row_to_dict(row) for _, row in top_inflow.iterrows()],
                self._load_tushare_name_map()
            )
            outflow_list, removed_outflow = filter_st_stocks(
                [row_to_dict(row) for _, row in top_outflow.iterrows()],
                self._load_tushare_name_map()
            )
            removed_count = len(removed_inflow) + len(removed_outflow)
            if removed_count:
                logger.info(f"资金流向榜过滤ST/退市股票 {removed_count} 只")

            logger.info(f"✓ 获取资金流向数据成功，日期: {trade_date}，流入{len(inflow_list)}只/流出{len(outflow_list)}只")
            return {
                'inflow': inflow_list,
                'outflow': outflow_list,
                'trade_date': trade_date
            }

        except Exception as e:
            logger.warning(f"获取资金流向数据失败: {e}")
            return None

    def _generate_top_list_html(self, top_list_data: Dict) -> str:
        """
        生成个股资金流向HTML表格（流入前20 + 流出前20）

        Args:
            top_list_data: {'inflow': [...], 'outflow': [...], 'trade_date': '...'}

        Returns:
            HTML字符串，如果数据为空返回空字符串
        """
        if not top_list_data:
            return ''

        def fmt_amount(val):
            if abs(val) >= 10000:
                return f"{val/10000:.2f}亿"
            else:
                return f"{val:.0f}万"

        trade_date = top_list_data.get('trade_date', '')
        date_display = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}" if len(trade_date) == 8 else trade_date

        def build_table(stocks, title_icon, title_text):
            if not stocks:
                return ''
            rows = []
            for idx, item in enumerate(stocks, 1):
                code = item.get('code', '')
                name = item.get('name', '')
                close = item.get('close', 0)
                pct = item.get('pct_change', 0)
                net = item.get('net_amount', 0)
                net_rate = item.get('net_amount_rate', 0)
                elg = item.get('buy_elg_amount', 0)
                lg = item.get('buy_lg_amount', 0)

                pct_color = '#ef5350' if pct > 0 else '#66bb6a' if pct < 0 else '#b0bec5'
                net_color = '#ef5350' if net > 0 else '#66bb6a' if net < 0 else '#b0bec5'

                rows.append(f'''
                    <tr>
                        <td style="padding: 8px; text-align: center;">{idx}</td>
                        <td style="padding: 8px;">
                            <strong>{name}</strong><span style="color: #64748b; font-size: 12px;">({code})</span>
                        </td>
                        <td style="padding: 8px; text-align: left;">
                            <div>最新价: <span style="font-weight: bold;">{close:.2f}</span></div>
                            <div style="color: {pct_color}; font-weight: bold;">涨跌幅: {pct:+.2f}%</div>
                            <div style="color: {net_color}; font-weight: bold;">主力净流入: {fmt_amount(net)}</div>
                            <div style="color: {net_color};">净占比: {net_rate:+.1f}%</div>
                            <div>超大单净流入: {fmt_amount(elg)}</div>
                            <div>大单净流入: {fmt_amount(lg)}</div>
                        </td>
                    </tr>
                ''')

            return f'''
                <div style="margin-bottom: 20px;">
                    <h4 style="margin: 10px 0; color: #334155;">{title_icon} {title_text}</h4>
                    <table class="top10-table" style="width: 100%;">
                        <thead>
                            <tr>
                                <th style="width: 50px;">#</th>
                                <th style="width: 120px;">股票</th>
                                <th>资金流向明细</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join(rows)}
                        </tbody>
                    </table>
                </div>
            '''

        inflow_html = build_table(top_list_data.get('inflow', []), '🔴', '主力净流入 TOP 20')
        outflow_html = build_table(top_list_data.get('outflow', []), '🟢', '主力净流出 TOP 20')

        full_html = f'''
        <div class="section">
            <div class="section-title">💰 个股资金流向（{date_display}）</div>
            {inflow_html}
            {outflow_html}
        </div>
        '''
        return full_html

    def _calculate_stage_statistics(self, analysis_results: List[Dict]) -> Dict:
        """
        计算各阶段统计数据

        Returns:
            {
                'stage1': {'passed': 60, 'eliminated': 40},
                'stage2': {'passed': 40, 'eliminated': 20},
                ...
            }
        """
        stats = {
            'stage0': {'passed': len(analysis_results), 'eliminated': 0},  # 初始数量
            'stage1': {'passed': 0, 'eliminated': 0},
            'stage2': {'passed': 0, 'eliminated': 0},
            'stage3': {'passed': 0, 'eliminated': 0},
            'stage4': {'passed': 0, 'eliminated': 0}
        }

        for result in analysis_results:
            eliminated_at = result.get('eliminated_at_stage', -1)

            if eliminated_at in (0, -1, None):  # v8.0: 通过所有阶段（-1=无淘汰）
                for stage in range(1, 5):
                    stats[f'stage{stage}']['passed'] += 1
            else:
                # 仅统计至阶段4
                passed_before = min(max(eliminated_at - 1, 0), 4)
                for stage in range(1, passed_before + 1):
                    stats[f'stage{stage}']['passed'] += 1

                # 在阶段1-4被淘汰计入统计；阶段5淘汰忽略（事件面已移除）
                if 1 <= eliminated_at <= 4:
                    stats[f'stage{eliminated_at}']['eliminated'] += 1

        return stats

    def _generate_funnel_data(self, stage_stats: Dict, total: int) -> List[Dict]:
        """
        生成漏斗图数据

        Returns:
            [
                {'stage': '初始候选', 'count': 100, 'percentage': 100},
                {'stage': '量化筛选', 'count': 60, 'percentage': 60},
                ...
            ]
        """
        stage_names = {
            0: '初始候选',
            1: '量化筛选',
            2: '技术筛选',
            3: '情绪筛选',
            4: '基本面筛选'
        }

        funnel_data = []

        # 阶段0: 初始
        funnel_data.append({
            'stage': stage_names[0],
            'count': total,
            'percentage': 100
        })

        # 阶段1-4
        for i in range(1, 5):
            count = stage_stats[f'stage{i}']['passed']
            percentage = (count / total * 100) if total > 0 else 0

            funnel_data.append({
                'stage': stage_names[i],
                'count': count,
                'percentage': round(percentage, 1)
            })

        return funnel_data

    def _group_by_elimination_stage(self, analysis_results: List[Dict]) -> Dict:
        """
        按淘汰阶段分组

        Returns:
            {
                'passed': [...],  # 通过所有筛选的股票
                'stage1': [...],  # 在阶段1被淘汰
                'stage2': [...],
                ...
            }
        """
        grouped = {
            'passed': [],
            'stage1': [],
            'stage2': [],
            'stage3': [],
            'stage4': []
        }

        for result in analysis_results:
            if result.get('passed', False):
                grouped['passed'].append(result)
            else:
                stage = result.get('eliminated_at_stage', 0)
                if 1 <= stage <= 4:
                    grouped[f'stage{stage}'].append(result)

        # 排序：通过的按分数降序，淘汰的按分数降序
        for key in grouped:
            grouped[key] = sorted(grouped[key], key=lambda x: x.get('final_score', 0), reverse=True)

        return grouped

    def _wrap_html_page(self, body_content: str, title: str = "投资机会挖掘报告") -> str:
        """Wrap the markdown-converted HTML body in a full page with CSS styling."""
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text: #1e293b;
            --text-secondary: #475569;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --accent: #3b82f6;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-yellow: #f59e0b;
            --accent-purple: #8b5cf6;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.8;
            padding: 24px;
            max-width: 1200px;
            margin: 0 auto;
        }}

        .report-container {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 40px 48px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 4px 16px rgba(0,0,0,0.04);
        }}

        h2 {{
            font-size: 22px;
            color: var(--text);
            margin: 36px 0 16px 0;
            padding-bottom: 8px;
            border-bottom: 2px solid var(--border);
        }}

        h3 {{
            font-size: 18px;
            color: var(--text-secondary);
            margin: 24px 0 12px 0;
        }}

        hr {{
            border: none;
            border-top: 1px solid var(--border);
            margin: 28px 0;
        }}

        p {{
            margin: 8px 0;
            color: var(--text-secondary);
        }}

        blockquote {{
            border-left: 4px solid var(--accent);
            padding: 8px 16px;
            margin: 12px 0;
            background: #f1f5f9;
            border-radius: 0 6px 6px 0;
            color: var(--text-muted);
            font-size: 14px;
        }}

        ul, ol {{
            margin: 8px 0 8px 20px;
            color: var(--text-secondary);
        }}

        li {{
            margin: 4px 0;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 12px 0 20px 0;
            font-size: 14px;
        }}

        th {{
            background: #f1f5f9;
            padding: 10px 12px;
            text-align: left;
            font-weight: 600;
            color: var(--text);
            border-bottom: 2px solid var(--border);
            white-space: nowrap;
        }}

        td {{
            padding: 8px 12px;
            border-bottom: 1px solid var(--border);
            color: var(--text-secondary);
            vertical-align: top;
        }}

        tr:hover td {{
            background: #f8fafc;
        }}

        a {{
            color: var(--accent);
            text-decoration: none;
        }}
        a:hover {{ text-decoration: underline; }}

        strong {{ color: var(--text); }}

        /* Footer disclaimer */
        .report-container > p:last-child {{
            margin-top: 32px;
            padding-top: 16px;
            border-top: 1px solid var(--border);
            font-size: 13px;
            color: var(--text-muted);
            text-align: center;
        }}

        /* Responsive */
        @media (max-width: 768px) {{
            body {{ padding: 12px; }}
            .report-container {{ padding: 20px 16px; }}
            table {{ font-size: 12px; }}
            th, td {{ padding: 6px 8px; }}
        }}

        /* Print */
        @media print {{
            body {{ background: white; padding: 0; }}
            .report-container {{ box-shadow: none; border-radius: 0; }}
        }}
    </style>
</head>
<body>
    <div class="report-container">
        {body_content}
    </div>
</body>
</html>'''

    def _generate_html(self, report_title: str, total_count: int, passed_count: int,
                      stage_stats: Dict, funnel_data: List[Dict], top_20: List[Dict], quant_top_20: List[Dict],
                      grouped_stocks: Dict, global_hot_news: List[Dict], sector_hot_news: List[Dict], hot_news_title: str = None) -> str:
        """生成HTML内容"""

        # 构建热门新闻关联股票映射
        related_map = {}
        def _mk_key(item):
            item_title = (item.get('title') or '').strip()
            url = self._normalize_topic_url((item.get('url') or '').strip(), item_title)
            if url:
                return url
            return f"{(item.get('source') or '').strip()}|{(item.get('title') or '').strip()}"

        # 收集所有股票并去重
        all_stocks = []
        try:
            for k in ['passed', 'stage1', 'stage2', 'stage3', 'stage4', 'stage5']:
                all_stocks.extend(grouped_stocks.get(k, []))
            seen = set()
            deduped = []
            for s in all_stocks:
                code = s.get('stock_code') or s.get('code') or ''
                if code and code not in seen:
                    seen.add(code)
                    deduped.append(s)
            all_stocks = deduped
        except Exception:
            pass

        # 预建键（与展示数量一致，改为9条）
        for item in (global_hot_news or [])[:9]:
            related_map[_mk_key(item)] = []

        # 遍历股票提取关联热门新闻
        try:
            for s in all_stocks:
                scoring_result = s.get('scoring_result') or {}
                events = (scoring_result.get('details') or {}).get('events') or {}
                matches = events.get('hot_news_matches') or []
                for m in matches:
                    key = _mk_key(m)
                    if key in related_map:
                        related_map[key].append({
                            'name': s.get('name') or s.get('stock_name') or '未知',
                            'stock_code': s.get('stock_code') or s.get('code') or '',
                            'rating': s.get('rating') or scoring_result.get('rating') or 'C',
                            'final_score': s.get('final_score') or scoring_result.get('final_score') or 0
                        })
        except Exception:
            pass

        # 生成热门新闻HTML
        hot_news_html = ''
        # 热门话题/新闻展示数量改为9条
        for item in (global_hot_news or [])[:9]:
            key = _mk_key(item)
            stocks = related_map.get(key, [])[:8]
            title = (item.get('title') or '').replace('"', '&quot;')
            url = self._normalize_topic_url((item.get('url') or '').strip(), title)
            source = item.get('source') or ''
            publish_time = item.get('publish_time') or ''
            heat = item.get('heat') or ''
            rank = item.get('rank') or ''
            # 优先使用采集器解析到的关联股票（related_stocks）
            try:
                rel = item.get('related_stocks') or []
                if rel:
                    # 通过代码或名称映射到已评分股票，补充评级与分数用于标签渲染
                    idx = {}
                    name_idx = {}
                    for s in all_stocks:
                        code = s.get('stock_code') or s.get('code') or ''
                        if code:
                            idx[code] = s
                        nm0 = s.get('name') or s.get('stock_name') or ''
                        nm_key = (nm0 or '').replace(' ', '').lower()
                        if nm_key:
                            name_idx[nm_key] = s
                    rich = []
                    for r in rel:
                        code = r.get('stock_code') or ''
                        name = r.get('name') or ''
                        s = idx.get(code)
                        if (not s) and name:
                            s = name_idx.get((name or '').replace(' ', '').lower())
                        if s:
                            rich.append({
                                'name': s.get('name') or s.get('stock_name') or name or '未知',
                                'stock_code': s.get('stock_code') or s.get('code') or code,
                                'rating': s.get('rating') or (s.get('scoring_result') or {}).get('rating') or 'C',
                                'final_score': s.get('final_score') or (s.get('scoring_result') or {}).get('final_score') or 0
                            })
                        else:
                            # 若评分集中未出现该股，仍保留标签但不给分
                            rich.append({
                                'name': name or '未知',
                                'stock_code': code,
                                'rating': 'C',
                                'final_score': 0
                            })
                    rich = sorted(rich, key=lambda x: x.get('final_score', 0), reverse=True)
                    stocks = rich[:8]
            except Exception:
                pass
            if not stocks and title:
                # 回退：标题包含股票名称则展示相应股票标签
                try:
                    candidates = []
                    t = title
                    for s in all_stocks:
                        nm = s.get('name') or s.get('stock_name') or ''
                        if nm and (nm in t):
                            candidates.append({
                                'name': s.get('name') or s.get('stock_name') or '未知',
                                'stock_code': s.get('stock_code') or s.get('code') or '',
                                'rating': s.get('rating') or (s.get('scoring_result') or {}).get('rating') or 'C',
                                'final_score': s.get('final_score') or (s.get('scoring_result') or {}).get('final_score') or 0
                            })
                    if candidates:
                        candidates = sorted(candidates, key=lambda x: x.get('final_score', 0), reverse=True)
                        stocks = candidates[:5]
                except Exception:
                    pass
            tags_html = ''
            for st in stocks:
                rating_class = f"rating-{str(st.get('rating', 'C')).replace('+', '-plus')}"
                code_txt = st.get('stock_code', '')
                name_txt = st.get('name', '未知')
                display_txt = f"{name_txt}{f'({code_txt})' if code_txt else ''}"
                tags_html += f"<span class=\"stock-tag\"><span class=\"rating-badge {rating_class}\">{st.get('rating', 'C')}</span> {display_txt}</span>"
            # 新增：展示采集器识别的相关板块关键词
            sector_tags_html = ''
            # try:
            #     sectors = item.get('related_sectors') or []
            #     for sec in sectors[:4]:
            #         sector_tags_html += f"<span class=\"stock-tag muted\">{sec}</span>"
            # except Exception:
            #     pass
            meta_parts = []
            if source and ('股吧话题' not in source):
                meta_parts.append(f"<span class=\"source-badge\">{source}</span>")
            if publish_time:
                meta_parts.append(f"<span>时间: {publish_time}</span>")
            meta_parts.append(f"<span class=\"heat-badge\">热度 {heat}</span>")
            meta_parts.append(f"<span class=\"rank-badge small\">{rank if rank else '-'}</span>")
            meta_html = f"<div class=\"news-meta\">{''.join(meta_parts)}</div>"
            stock_tags_section = f"<div class=\"stock-tags\">{tags_html}{sector_tags_html}</div>" if (tags_html or sector_tags_html) else ""
            hot_news_html += (
                f"<div class=\"hot-news-item\">"
                f"<a href=\"{url}\" target=\"_blank\" class=\"news-title\">{title}</a>"
                f"{meta_html}"
                # f"{stock_tags_section}"
                f"</div>"
            )

        # 构建板块 -> 相关股票映射（用于板块新闻标签）
        sector_to_stocks = {}
        try:
            for s in all_stocks:
                scoring_result = s.get('scoring_result') or {}
                secd = (scoring_result.get('details') or {}).get('sector') or {}
                sec_name = (secd.get('sector_name') or '').strip()
                if not sec_name:
                    continue
                info = {
                    'name': s.get('name') or s.get('stock_name') or '未知',
                    'stock_code': s.get('stock_code') or s.get('code') or '',
                    'rating': s.get('rating') or scoring_result.get('rating') or 'C',
                    'final_score': s.get('final_score') or scoring_result.get('final_score') or 0
                }
                sector_to_stocks.setdefault(sec_name, []).append(info)

            # 各板块按分数排序
            for k in list(sector_to_stocks.keys()):
                sector_to_stocks[k] = sorted(sector_to_stocks[k], key=lambda x: x.get('final_score', 0), reverse=True)
        except Exception:
            pass

        # 生成板块新闻HTML（仅展示与板块内股票强相关的新闻）
        def _get_stocks_for_sector(name: str):
            n = (name or '').strip()
            if not n:
                return []
            # 1) 精确匹配
            exact = sector_to_stocks.get(n)
            if exact:
                return exact
            # 2) 子串模糊匹配（如“半导体及元件”匹配“半导体”）
            collected = []
            for k, v in sector_to_stocks.items():
                if n in k or k in n:
                    collected.extend(v)
            if collected:
                seen = set()
                dedup = []
                for s in collected:
                    code = s.get('stock_code', '')
                    if code and code not in seen:
                        seen.add(code)
                        dedup.append(s)
                return sorted(dedup, key=lambda x: x.get('final_score', 0), reverse=True)
            # 3) 同义词近似匹配
            syn = {
                '半导体': ['芯片', '集成电路', 'IC', '晶圆'],
                '光伏': ['太阳能', '硅料', '硅片', '电池片', '组件'],
                '锂电': ['动力电池', '电池', '电池产业链', '正极', '负极', '隔膜', '电解液'],
                '新能源': ['风电', '储能', '氢能'],
                '算力': ['数据中心', 'AI算力', 'GPU', '服务器'],
                '人工智能': ['AI', '大模型', 'AIGC'],
                '汽车': ['整车', '新能源车', '车企', '乘用车'],
                '券商': ['证券', '经纪'],
                '银行': ['商业银行'],
                '保险': ['寿险', '财险'],
                '地产': ['房地产', '房企']
            }
            candidates = []
            for k, vs in syn.items():
                if k in n or any(v in n for v in vs):
                    for sk, sv in sector_to_stocks.items():
                        if k in sk or any(v in sk for v in vs):
                            candidates.extend(sv)
            seen = set()
            dedup = []
            for s in candidates:
                code = s.get('stock_code', '')
                if code and code not in seen:
                    seen.add(code)
                    dedup.append(s)
            return sorted(dedup, key=lambda x: x.get('final_score', 0), reverse=True)

        sector_news_html = ''
        for item in (sector_hot_news or [])[:6]:
            sector_name = (item.get('sector_name') or '').strip()
            stocks = _get_stocks_for_sector(sector_name)[:8]
            if not stocks:
                # 若没有板块内高相关股票，跳过该新闻以避免空版块
                continue
            tags_html = ''
            for st in stocks:
                rating_class = f"rating-{str(st.get('rating', 'C')).replace('+', '-plus')}"
                tags_html += f"<span class=\"stock-tag\"><span class=\"rating-badge {rating_class}\">{st.get('rating', 'C')}</span> {st.get('name', '未知')}({st.get('stock_code', '')})</span>"

            title = (item.get('title') or '').replace('"', '&quot;')
            url = (item.get('url') or '').strip()
            source = item.get('source') or ''
            publish_time = item.get('publish_time') or ''
            heat = item.get('heat') or ''
            rank = item.get('rank') or ''

            # 板块徽章
            sector_badge = f"<span class=\"sector-badge\">{sector_name or '板块'}</span>"

            sector_news_html += (
                f"<div class=\"hot-news-item\">"
                f"<a href=\"{url}\" target=\"_blank\" class=\"news-title\">{title}</a>"
                f"<div class=\"news-meta\">{sector_badge}<span class=\"source-badge\">{source}</span><span>时间: {publish_time}</span><span class=\"heat-badge\">热度 {heat}</span><span class=\"rank-badge small\">{rank if rank else '-'}</span></div>"
                # f"<div class=\"stock-tags\">{tags_html}</div>"
                f"</div>"
            )

        # 若无板块新闻，则不渲染该版块
        sector_section_html = ''
        if sector_news_html.strip():
            sector_section_html = (
                '<div class="section">'
                '<div class="section-title">📈 热门板块相关新闻</div>'
                f'<div class="hot-news-list">{sector_news_html}</div>'
                '</div>'
            )

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report_title}</title>
    <style>
        :root {{
            --primary-bg: #1a1f2e;
            --secondary-bg: #252d42;
            --tertiary-bg: #2d3748;
            --accent-blue: #64b5f6;
            --accent-purple: #ba68c8;
            --accent-green: #66bb6a;
            --accent-red: #ef5350;
            --accent-yellow: #ffca28;
            --text-primary: #ffffff;
            --text-secondary: #e8eaf6;
            --text-muted: #b0bec5;
            --border-primary: #4a5568;
            --gradient-dark: linear-gradient(135deg, #252d42 0%, #2d3748 100%);
            /* 卡片主题（浅色背景） */
            --card-bg: #ffffff;
            --card-text-primary: #1f2937; /* 深色文本，提高可读性 */
            --card-text-secondary: #374151; /* 次级文本，降低灰度 */
            --card-text-muted: #4b5563; /* 辅助文本，避免过灰 */
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: var(--primary-bg);
            padding: 20px;
            color: var(--text-primary);
            line-height: 1.6;
            min-height: 100vh;
            overflow-x: hidden;
            position: relative;
        }}

        /* 动态背景与粒子效果，保持与批量分析风格一致 */
        body::before {{
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background:
                radial-gradient(circle at 20% 50%, rgba(91,155,213,0.08) 0%, transparent 50%),
                radial-gradient(circle at 80% 20%, rgba(159,122,234,0.08) 0%, transparent 50%),
                radial-gradient(circle at 40% 80%, rgba(72,187,120,0.08) 0%, transparent 50%);
            pointer-events: none;
            z-index: -1;
        }}

        body::after {{
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background-image:
                radial-gradient(1px 1px at 20px 30px, var(--accent-blue), transparent),
                radial-gradient(1px 1px at 40px 70px, var(--accent-purple), transparent),
                radial-gradient(1px 1px at 90px 40px, var(--accent-green), transparent),
                radial-gradient(1px 1px at 130px 80px, var(--accent-yellow), transparent);
            background-repeat: repeat;
            background-size: 200px 100px;
            animation: particleMove 20s linear infinite;
            opacity: 0.08;
            pointer-events: none;
            z-index: -1;
        }}

        @keyframes particleMove {{
            0% {{ transform: translate(0, 0); }}
            100% {{ transform: translate(-200px, -100px); }}
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .header {{
            background: var(--gradient-dark);
            border: 1px solid var(--border-primary);
            border-radius: 20px;
            padding: 40px;
            margin-bottom: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
            text-align: center;
            position: relative;
            overflow: hidden;
        }}

        .header::before {{
            content: '';
            position: absolute;
            top: 0; left: -100%;
            width: 100%; height: 100%;
            background: linear-gradient(90deg, transparent, rgba(0,212,255,0.1), transparent);
            animation: scanLine 3s linear infinite;
        }}

        @keyframes scanLine {{
            0% {{ left: -100%; }}
            100% {{ left: 100%; }}
        }}

        .header h1 {{
            font-size: 30px;
            color: var(--text-primary);
            margin-bottom: 8px;
            font-weight: 700;
        }}

        .header .subtitle {{
            font-size: 16px;
            color: var(--text-muted);
            margin-bottom: 20px;
        }}

        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .summary-card {{
            background: var(--secondary-bg);
            border: 1px solid var(--border-primary);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.25);
            transition: transform 0.3s ease;
        }}

        .summary-card:hover {{
            transform: translateY(-5px);
        }}

        .summary-card h3 {{
            font-size: 14px;
            color: var(--text-muted);
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}

        .summary-card .value {{
            font-size: 36px;
            font-weight: bold;
            color: var(--accent-blue);
        }}

        .summary-card .label {{
            font-size: 14px;
            color: var(--text-secondary);
            margin-top: 5px;
        }}

        .section {{
            background: white;
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.08);
        }}

        .section-title {{
            font-size: 24px;
            color: var(--text-primary);
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 3px solid var(--accent-blue);
            font-weight: 600;
        }}

        /* 热门新闻版块样式 */
        .hot-news-list {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
            gap: 10px;
        }}
        .hot-news-item {{
            background: var(--card-bg);
            border: 1px solid #eee;
            border-radius: 10px;
            padding: 10px;
        }}
        .news-title {{
            font-size: 16px;
            color: var(--card-text-primary);
            text-decoration: none;
            font-weight: 600;
        }}
        .news-title:hover {{ text-decoration: underline; }}
        .news-meta {{
            margin-top: 6px;
            font-size: 12px;
            color: var(--card-text-secondary);
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .sector-badge {{
            background: #e8f5e9;
            color: #1b5e20;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            border: 1px solid #c8e6c9;
        }}
        .source-badge {{
            background: #f1f5f9;
            color: #374151;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            border: 1px solid #e5e7eb;
        }}
        .heat-badge {{
            background: #fff7ed;
            color: #c2410c;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            border: 1px solid #fed7aa;
        }}
        .rank-badge.small {{
            width: 20px; height: 20px; line-height: 20px; font-size: 12px;
        }}
        .stock-tags {{
            margin-top: 8px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .stock-tag {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #f8fafc;
            border: 1px solid #e5e7eb;
            color: #374151;
            border-radius: 16px;
            padding: 4px 8px;
            font-size: 12px;
        }}
        .stock-tag.muted {{
            background: #f9fafb;
            color: #6b7280;
            border-style: dashed;
        }}

        /* 漏斗图样式（对齐股票分析报告的现代风格） */
        .funnel-container {{
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px 0;
        }}

        .funnel-stage {{
            position: relative;
            margin: 10px 0;
            text-align: center;
            transition: all 0.3s ease;
        }}

        .funnel-bar {{
            background: linear-gradient(90deg, #667eea, #764ba2);
            border-radius: 12px;
            padding: 18px 24px;
            color: white;
            font-weight: 600;
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.25);
            clip-path: polygon(0 0, 100% 0, 95% 100%, 5% 100%);
        }}

        .funnel-stage:hover .funnel-bar {{
            box-shadow: 0 6px 25px rgba(102, 126, 234, 0.5);
            transform: scale(1.02);
        }}

        .funnel-label {{
            font-size: 16px;
            margin-bottom: 5px;
        }}

        .funnel-count {{
            font-size: 24px;
            font-weight: bold;
            text-shadow: 0 1px 2px rgba(0,0,0,0.25);
        }}

        /* 漏斗阶段配色 */
        .funnel-bar.stage-0 {{ background: linear-gradient(90deg, #a18cd1, #fbc2eb); }}
        .funnel-bar.stage-1 {{ background: linear-gradient(90deg, #43e97b, #38f9d7); }}
        .funnel-bar.stage-2 {{ background: linear-gradient(90deg, #4facfe, #00f2fe); }}
        .funnel-bar.stage-3 {{ background: linear-gradient(90deg, #f6d365, #fda085); }}
        .funnel-bar.stage-4 {{ background: linear-gradient(90deg, #fa709a, #fee140); }}
        .funnel-bar.stage-5 {{ background: linear-gradient(90deg, #f093fb, #f5576c); }}

        /* TOP列表容器，默认显示约10行并允许滚动 */
        .top-table-container {{
            max-height: 540px;
            overflow-y: auto;
            border-radius: 12px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.25);
            border: 1px solid var(--border-primary);
            background: var(--secondary-bg);
        }}

        /* TOP 10 表格 */
        .top10-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}

        .top10-table th {{
            background: var(--tertiary-bg);
            color: var(--text-secondary);
            padding: 12px;
            text-align: left;
            font-weight: 600;
            font-size: 13px;
            border-bottom: 1px solid var(--border-primary);
            position: sticky;
            top: 0;
            z-index: 5;
        }}

        .top10-table td {{
            padding: 12px;
            border-bottom: 1px solid var(--border-primary);
            font-size: 13px;
            color: var(--text-primary);
        }}

        .top10-table tr {{ height: 48px; }}

        .top10-table tr:hover {{
            background-color: rgba(100, 181, 246, 0.08);
        }}

        .rank-badge {{
            display: inline-block;
            width: 30px;
            height: 30px;
            line-height: 30px;
            border-radius: 50%;
            text-align: center;
            font-weight: bold;
            color: white;
        }}

        .rank-1 {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }}
        .rank-2 {{ background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }}
        .rank-3 {{ background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%); }}
        .rank-other {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}

        .rating-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 12px;
        }}

        .rating-S {{ background: #ff6b6b; color: white; }}
        .rating-A-plus {{ background: #ee5a6f; color: white; }}
        .rating-A {{ background: #4ecdc4; color: white; }}
        .rating-B {{ background: #95e1d3; color: #333; }}
        .rating-C {{ background: #dddddd; color: #333; }}

        .score-bar {{
            width: 100%;
            height: 8px;
            background: #eee;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 5px;
        }}

        .score-fill {{
            height: 100%;
            background: #3b82f6;
            border-radius: 4px;
            transition: width 0.5s ease;
        }}

        /* 分组股票列表 */
        .group-section {{
            margin-bottom: 30px;
        }}

        .group-header {{
            background: #f0f3f8;
            color: #222;
            padding: 15px 20px;
            border-radius: 10px;
            margin-bottom: 15px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            user-select: none;
            transition: all 0.3s ease;
            border: 1px solid #e9edf3;
        }}

        .group-header:hover {{
            transform: translateX(3px);
            box-shadow: none;
            border-color: #d9dfeb;
        }}

        .group-header .count {{
            float: right;
            background: rgba(255, 255, 255, 0.2);
            padding: 2px 12px;
            border-radius: 15px;
            font-size: 14px;
        }}

        .stock-list {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}

        .stock-card {{
            background: var(--card-bg);
            border: 1px solid #eee;
            border-radius: 10px;
            padding: 15px;
            transition: all 0.3s ease;
        }}

        .stock-card:hover {{
            border-color: #667eea;
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.15);
            transform: translateY(-3px);
        }}

        .stock-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}

        .stock-name {{
            font-size: 16px;
            font-weight: 600;
            color: var(--card-text-primary);
        }}

        .stock-code {{
            font-size: 12px;
            color: var(--card-text-muted);
            margin-left: 8px;
        }}

        .filter-brief {{
            font-size: 12px;
            color: var(--card-text-secondary);
            margin-top: 4px;
        }}

        .filter-history {{
            margin-top: 10px;
        }}

        /* 每个阶段的维度元信息（合并到阶段卡片，替代顶部摘要） */
        .stage-meta {{
            font-size: 12px;
            color: var(--card-text-secondary);
            margin-top: 4px;
        }}

        .filter-stage {{
            padding: 8px 10px;
            margin: 5px 0;
            border-radius: 5px;
            font-size: 13px;
            background: #f8f9ff;
            border-left: 3px solid #667eea;
        }}

        .filter-stage.passed {{
            border-left-color: #4ecdc4;
        }}

        .filter-stage.failed {{
            border-left-color: #ff6b6b;
        }}

        .stage-name {{
             color: #333;
            font-weight: 600;
            margin-bottom: 3px;
        }}

        .stage-reason {{
            font-size: 12px;
            color: var(--card-text-secondary);
            line-height: 1.5;
        }}

        /* AI分析卡片样式 */
        .ai-analysis-card {{
            margin-top: 12px;
            padding: 12px;
            background: linear-gradient(135deg, #f8faff 0%, #f0f7ff 100%);
            border: 1px solid #e0e8f0;
            border-radius: 8px;
        }}
        .ai-card-title {{
            font-size: 13px;
            font-weight: 600;
            color: #4a5568;
            margin-bottom: 8px;
        }}
        .ai-model-section {{
            margin-bottom: 8px;
            padding: 8px;
            background: white;
            border-radius: 6px;
            border: 1px solid #e5e7eb;
        }}
        .ai-model-badge {{
            display: inline-block;
            padding: 2px 8px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 11px;
            font-weight: 600;
            border-radius: 12px;
            margin-bottom: 6px;
        }}
        .ai-metrics-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 4px;
        }}
        .ai-action {{
            display: inline-block;
            padding: 2px 10px;
            font-size: 12px;
            font-weight: 600;
            border-radius: 4px;
        }}
        .ai-action.action-buy {{ background: #dcfce7; color: #166534; }}
        .ai-action.action-sell {{ background: #fee2e2; color: #991b1b; }}
        .ai-action.action-hold {{ background: #fef3c7; color: #92400e; }}
        .ai-metric {{
            font-size: 11px;
            color: #4b5563;
            background: #f3f4f6;
            padding: 2px 6px;
            border-radius: 4px;
        }}
        .ai-risk {{
            display: inline-block;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 500;
            border-radius: 4px;
        }}
        .ai-risk.risk-low {{ background: #dcfce7; color: #166534; }}
        .ai-risk.risk-medium {{ background: #fef3c7; color: #92400e; }}
        .ai-risk.risk-high {{ background: #fee2e2; color: #991b1b; }}
        .ai-strategy {{
            font-size: 11px;
            color: #4b5563;
            margin-top: 4px;
            padding: 4px 6px;
            background: #f9fafb;
            border-radius: 4px;
        }}
        .ai-summary {{
            font-size: 12px;
            color: #374151;
            margin-top: 6px;
            padding: 6px 8px;
            background: #fffbeb;
            border-left: 3px solid #f59e0b;
            border-radius: 4px;
        }}
        /* TOP表格中的AI简短分析样式 */
        .ai-brief {{
            margin-top: 6px;
            padding: 4px 8px;
            background: linear-gradient(135deg, #f0f7ff 0%, #e8f4f8 100%);
            border: 1px solid #d0e8f0;
            border-radius: 6px;
            font-size: 11px;
            color: #374151;
        }}
        .ai-tag {{
            display: inline-block;
            padding: 1px 6px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 10px;
            font-weight: 600;
            border-radius: 8px;
            margin-right: 6px;
        }}

        .footer {{
            background: var(--card-bg);
            border-radius: 15px;
            padding: 20px;
            text-align: center;
            color: var(--card-text-muted);
            font-size: 14px;
            margin-top: 30px;
        }}

        @media (max-width: 768px) {{
            .summary-cards {{
                grid-template-columns: 1fr;
            }}

            .stock-list {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
  
        <!-- 已移除筛选漏斗以节省空间并聚焦核心内容 -->

        <!-- 热门新闻/话题精选（动态标题） -->
        <div class="section">
            <div class="section-title">{hot_news_title or '🔥 全市场最热新闻精选'}</div>
            <div class="hot-news-list">
                {hot_news_html}
            </div>
        </div>

        {sector_section_html}

        <!-- 个股资金流向 -->
'''
        # 获取资金流向数据
        top_list_data = self._fetch_top_list()
        if top_list_data:
            html += self._generate_top_list_html(top_list_data)
        else:
            logger.warning("资金流向数据获取失败或为空")
            html += '''
            <div style="text-align: center; color: #6b7280; padding: 20px;">
                暂无可用资金流向数据<br>
                <small>可能原因：Tushare Token未配置、积分不足(需5000)、昨日为非交易日</small>
            </div>
'''

        html += '''

        <!-- TOP 推荐（默认展示10个，支持滚动到末尾） -->
        <div class="section">
            <div class="section-title">⭐ TOP 投资机会</div>
            <div class="top-table-container">
            <table class="top10-table">
                <thead>
                    <tr>
                        <th>排名</th>
                        <th>股票</th>
                        <th>评级</th>
                        <th>综合得分</th>
                        <th>描述</th>
                        <th>建议</th>
                    </tr>
                </thead>
                <tbody>
'''

        for i, stock in enumerate(top_20, 1):
            rank_class = f"rank-{i}" if i <= 3 else "rank-other"
            rating = stock.get('rating', 'C')
            rating_class = f"rating-{rating.replace('+', '-plus')}"
            score = stock.get('final_score', 0)
            stock_code = _normalize_stock_code(stock.get('stock_code') or stock.get('code') or '')
            stock_name = self._resolve_stock_display_name_from_reports(
                code=stock_code,
                name=stock.get('name'),
                stock_name=stock.get('stock_name'),
                default=stock_code or '未知',
            )

            # 为TOP表格生成简短分析
            analysis_brief = self._build_short_analysis(stock)

            # 生成AI简短分析（如果有LLM分析结果）
            ai_brief = self._build_ai_brief_for_table(stock)

            html += f'''
                    <tr>
                        <td><span class="rank-badge {rank_class}">{i}</span></td>
                        <td>
                            <strong>{stock_name}</strong>
                            <span class="stock-code">({stock_code})</span>
                            <div class="filter-brief">筛选结果: {'全部通过' if stock.get('eliminated_at_stage', -1) in (0, -1, None) else f"阶段{stock.get('eliminated_at_stage')}淘汰"}</div>
                        </td>
                        <td><span class="rating-badge {rating_class}">{rating}</span></td>
                        <td>
                            {score:.2f} 分
                            <div class="score-bar">
                                <div class="score-fill" style="width: {score}%;"></div>
                            </div>
                        </td>
                        <td>{analysis_brief}{ai_brief}</td>
                        <td>{self._get_recommendation_text(rating)}</td>
                    </tr>
'''

        html += '''
                </tbody>
            </table>
            </div>
        </div>
'''

        # 已移除单独的LLM智能分析版块，AI分析结果已整合到每只股票卡片中

        html += '''
        <!-- 所有股票分组 -->
        <div class="section">
            <div class="section-title">📋 完整筛选结果</div>
'''

        # 通过筛选的股票
        html += self._generate_group_html("通过所有筛选", grouped_stocks['passed'], is_passed=True)

        # 各阶段淘汰的股票
        stage_names = {
            'stage1': '阶段1: 量化模型筛选 - 淘汰',
            'stage2': '阶段2: 技术面筛选 - 淘汰',
            'stage3': '阶段3: 情绪面筛选 - 淘汰',
            'stage4': '阶段4: 基本面筛选 - 淘汰'
        }

        for stage_key, stage_name in stage_names.items():
            html += self._generate_group_html(stage_name, grouped_stocks[stage_key], is_passed=False)

        html += '''
        </div>

        <!-- 页脚 -->
        <div class="footer">
            <p>📈 基于深度学习的金融预测系统</p>
            <p>本软件仅为数据工具，不构成投资建议，股市有风险，投资需谨慎。</p>
        </div>
    </div>

    <script>
        // 点击分组标题展开/收起
        document.querySelectorAll('.group-header').forEach(header => {
            header.addEventListener('click', function() {
                const content = this.nextElementSibling;
                if (content.style.display === 'none') {
                    content.style.display = 'grid';
                } else {
                    content.style.display = 'none';
                }
            });
        });

        // 页面加载动画
        window.addEventListener('load', function() {
            const scoreFills = document.querySelectorAll('.score-fill');
            scoreFills.forEach((fill, index) => {
                setTimeout(() => {
                    fill.style.width = fill.style.width;
                }, index * 50);
            });
        });
    </script>
</body>
</html>
'''

        return html

    def _build_full_indicator_summary(self, stock: Dict) -> str:
        try:
            scoring = stock.get('scoring_result') or {}
            scores = scoring.get('scores') or {}
            details = scoring.get('details') or {}

            code = stock.get('stock_code') or stock.get('code') or ''
            rating = stock.get('rating') or scoring.get('rating') or 'C'
            passed = stock.get('passed', False)
            eliminated = stock.get('eliminated_at_stage', 0)

            # 辅助格式化
            def _fmt(v, default='—'):
                if isinstance(v, float):
                    return f"{v:.2f}"
                return str(v) if v is not None and v != '' else default
            def _fmt_pct(v, digits=1):
                try:
                    return f"{float(v):+.{digits}f}%" if v is not None else '—'
                except: return '—'
            def _fmt_score(v):
                try:
                    return f"{float(v):.0f}" if isinstance(v, (int,float)) else '0'
                except: return '0'
            
            # 1. 板块
            sec = details.get('sector') or {}
            sector_name = sec.get('sector_name') or '未知'
            sec_score = scores.get('sector')
            sec_change_value = _get_displayable_sector_change(
                sec.get('change_pct'),
                turnover_value=sec.get('turnover_rate'),
                score=sec_score,
                overall=sec.get('overall'),
                data_source=sec.get('data_source'),
                leader_stock=sec.get('leader_stock')
            )
            sec_chg = _fmt_pct(sec_change_value)
            sec_turn = _fmt_pct(sec.get('turnover_rate'))
            sec_overall = sec.get('overall') or '中性'
            
            # 判断板块数据是否有效：至少要有有效板块名，且存在真实涨跌/换手/明确情绪信息之一
            is_valid_sector = True
            has_turnover = _to_float_safe(sec.get('turnover_rate')) not in (None, 0.0)
            has_overall = sec_overall not in ('', '未知', 'N/A', 'Unknown', '数据不足')
            if sector_name == '未知' or (sec_change_value is None and not has_turnover and not has_overall):
                is_valid_sector = False
                
            sec_str = f"{sector_name}({sec_chg}, {sec_overall}, {_fmt_score(sec_score)}分)"

            # 2. 量化
            qd = details.get('quantitative') or {}
            buy_count = qd.get('buy_count') or 0
            sell_count = qd.get('sell_count') or 0
            total_count = qd.get('total_count') or 0
            buy_ratio = qd.get('buy_ratio')
            buy_pct = f"{int(round(float(buy_ratio)*100))}%" if buy_ratio is not None else '—'
            quant_score = scores.get('quantitative')
            
            models = qd.get('top_buy_models') or []
            MODEL_DISPLAY_MAP = {
                'balance_dual_moving': '均衡双均线',
                'multi_breakthrough': '多重突破',
                'support_resistance': '支撑阻力',
                'trend_pullback': '趋势回踩',
                'ma_resonance': '均线共振',
                'super_reversal': '超级反转',
                'capital_trend': '资金趋势',
                'volume_breakthrough': '量能突破',
                'three_sisters': '三姐妹形态',
                'macd_axis_golden_cross': '轴心MACD金叉',
                'six_dimension_resonance': '六维共振',
                'statistical_quantitative': '统计量化',
                'super_profit_limit_up': '超额涨停',
                'turtle_trading_system': '海龟交易',
                'atr_momentum': 'ATR动量',
                'cta_trend_strategy': 'CTA趋势',
                'machine_learning_rf': '机器学习RF',
                'multi_factor_alpha': '多因子Alpha',
                'pairs_trading_arbitrage': '配对交易套利',
                'hft_microstructure': '高频微结构',
                'ichimoku_cloud': '一目均衡云',
                'bollinger_squeeze': '布林收敛',
                'rsi_divergence': 'RSI背离',
                'stochastic_momentum': '随机动量',
                'volume_price_trend': '量价趋势',
                'parabolic_sar': '抛物转向SAR',
                'chaikin_money_flow': '切金资金流',
                'elder_ray': 'Elder射线',
                'vwap_deviation': 'VWAP偏离',
                'fractal_adaptive_ma': '分形自适应均线'
            }
            model_names = '、'.join([MODEL_DISPLAY_MAP.get(m, m) for m in models[:3]]) if models else '无'
            quant_str = f"买{buy_count}/卖{sell_count}/总{total_count}({buy_pct})，{_fmt_score(quant_score)}分，模型[{model_names}]"
            # v24: degraded(数据缺失降级)标记 — 回测重建/统计据此剔除降级run
            _is_degraded = bool(qd.get('degraded')) or qd.get('error') == '无历史数据' or scoring.get('degraded')
            if _is_degraded:
                quant_str += "，⚠️数据降级"

            # 3. 技术
            tech = details.get('technical') or {}
            tech_score = scores.get('technical')
            rsi = _fmt(tech.get('RSI'), '—')
            macd = _fmt(tech.get('MACD'), '—')
            boll = _fmt(tech.get('Bollinger'), '—')
            tech_str = f"RSI:{rsi}，MACD:{macd}，布林:{boll}，{_fmt_score(tech_score)}分"

            # 4. 基本面
            fd = details.get('fundamental') or {}
            fund_score = scores.get('fundamental')
            pe = _fmt(fd.get('pe_ratio'), '—')
            rev = _fmt_pct(fd.get('revenue_yoy'))
            prof = _fmt_pct(fd.get('net_profit_yoy'))
            # fund_str = f"PE:{pe}，营收:{rev}，利润:{prof}，{_fmt_score(fund_score)}分"
            fund_str = f"营收:{rev}，利润:{prof}，{_fmt_score(fund_score)}分"

            # 5. 情绪 & 资金
            sd = details.get('sentiment') or {}
            sent_score = scores.get('sentiment')
            inv_sent = sd.get('comprehensive_sentiment') or '中性'
            
            cf = sd.get('capital_flow') or {}
            cf_trend = cf.get('trend') or '—'
            cf_str = cf.get('strength') or '—'
            cf_amt = _fmt_money(cf.get('main_inflow'))
            
            dt = sd.get('dragon_tiger') or {}
            dt_signal = dt.get('last_signal') or '—'
            dt_date = dt.get('last_date')
            dt_net = _fmt_money(dt.get('net_buy_amount'))

            cf_parts = []
            has_cf_trend = cf_trend not in ('—', '未知', None)
            has_cf_strength = cf_str not in ('—', '未知', None)
            has_cf_amt = cf_amt not in ('—', '+0.00')
            if has_cf_trend or has_cf_strength or has_cf_amt:
                amt_str = f", 净额{cf_amt}" if has_cf_amt else ""
                strength_str = cf_str if has_cf_strength else "—"
                cf_parts.append(f"资金:{cf_trend}({strength_str}{amt_str})")

            dt_parts = []
            valid_dt_date = bool(dt_date) and str(dt_date) != 'N/A'
            valid_dt_net = dt_net not in ('—', None)
            valid_dt_signal = dt_signal not in ('—', '中性', None)
            if valid_dt_date or valid_dt_net or valid_dt_signal:
                date_str = f"({dt_date})" if valid_dt_date else ""
                net_str = f"(净额{dt_net})" if valid_dt_net else ""
                signal_str = dt_signal if dt_signal else '—'
                dt_parts.append(f"龙虎榜:{signal_str}{net_str}{date_str}")

            sent_subparts = []
            if cf_parts:
                sent_subparts.append(cf_parts[0])
            if dt_parts:
                sent_subparts.append(dt_parts[0])
            if sent_subparts:
                sent_str = f"情绪:{inv_sent}，" + "，".join(sent_subparts) + f"，{_fmt_score(sent_score)}分"
            else:
                sent_str = f"情绪:{inv_sent}，{_fmt_score(sent_score)}分"

            # 6. 事件
            ed = details.get('events') or {}
            ev_score = scores.get('events')
            pos = ed.get('positive_events') or 0
            neg = ed.get('negative_events') or 0
            ev_rating = ed.get('rating') or '中性'
            events_str = f"评级:{ev_rating}，利好{pos}/利空{neg}，{_fmt_score(ev_score)}分"

            suggestion = self._get_recommendation_text(rating)
            filter_res = '' if eliminated in (0, -1, None) else f'阶段{eliminated}淘汰'

            # 获取涨幅数据
            price_changes = stock.get('scoring_result', {}).get('details', {}).get('price_changes', {})
            change_1d = price_changes.get('change_1d') if price_changes else None
            change_3d = price_changes.get('change_3d') if price_changes else None
            change_5d = price_changes.get('change_5d') if price_changes else None
            sector_chg = _get_displayable_sector_change(
                sec.get('change_pct'),
                turnover_value=sec.get('turnover_rate'),
                score=sec_score,
                overall=sec.get('overall'),
                data_source=sec.get('data_source'),
                leader_stock=sec.get('leader_stock')
            )

            change_1d_str = f"{change_1d:+.2f}%" if change_1d is not None else "—"
            change_3d_str = f"{change_3d:+.2f}%" if change_3d is not None else "—"
            change_5d_str = f"{change_5d:+.2f}%" if change_5d is not None else "—"
            sector_chg_str = f"{sector_chg:+.2f}%" if sector_chg is not None else "—"

            overview = f"【概览】评级{rating}，建议：{suggestion}<br>【涨幅】当日:{change_1d_str}，3日:{change_3d_str}，5日:{change_5d_str}"
            if filter_res:
                overview = f"【概览】评级{rating}，{filter_res}，建议：{suggestion}<br>【涨幅】当日:{change_1d_str}，3日:{change_3d_str}，5日:{change_5d_str}"

            parts = [overview]

            # v24: 板块分始终写入 (即使板块明细无效也保留评分) —
            # 回测重建依赖 detail 单元格里的 "【板块】...N分" 提取 sector_score
            if is_valid_sector:
                parts.append(f"【板块】{sec_str}")
            else:
                parts.append(f"【板块】未知(—, —, {_fmt_score(sec_score)}分)")

            # v24: 追高风险始终写入 (此前藏在 score_adjustments 里, v21 后缺失) —
            # 回测重建依赖 "追高风险...N分" 提取 chase_risk
            _mom = details.get('momentum') or {}
            _chase_val = (((scoring.get('advanced_analysis') or {}).get('overall_score') or {})
                          .get('risk_metrics') or {}).get('chase_risk_score')
            if not _chase_val:  # 0/None -> 回退动量明细（与评分逻辑一致）
                _chase_val = _mom.get('chase_risk_score')
            if isinstance(_chase_val, (int, float)):
                parts.append(f"【风险】追高风险{max(0, min(100, float(_chase_val))):.0f}分")

            parts.extend([
                f"【量化】{quant_str}",
                f"【技术】{tech_str}",
                f"【基本面】{fund_str}",
                f"【情绪资金】{sent_str}",
                f"【消息】{events_str}"
            ])

            score_adjustments = scoring.get('score_adjustments') or []
            if score_adjustments:
                wanted_keywords = (
                    '量化评分过低', '追高风险惩罚', 'RSI超买惩罚', 'RSI严重超买惩罚',
                    '连板涨停惩罚', '短期急涨惩罚', '短期暴涨惩罚', '惩罚触及上限',
                    '牛股动量识别', '板块死区惩罚',
                    f'[{RULESET_VERSION}]',  # v24: 共享规则命中明细统一带版本前缀
                )
                selected_adjustments = []
                for item in score_adjustments:
                    txt = str(item).strip()
                    if not txt:
                        continue
                    if any(k in txt for k in wanted_keywords):
                        selected_adjustments.append(txt)
                if selected_adjustments:
                    parts.append(f"【关键加减分】{'；'.join(selected_adjustments[:10])}")

            # 新增：入选原因与最新动态
            reason = _generate_selection_reason(stock)
            # 添加数据来源标签
            _stock_source = stock.get('source', '')
            _source_detail = stock.get('source_detail', '')
            _source_tag = ''
            if _stock_source == 'oversold_rebound':
                _source_tag = f'[超跌反弹] {_source_detail}；' if _source_detail else '[超跌反弹] '
            elif _stock_source in ('capital_flow_in', 'capital_flow_out', 'dragon_tiger'):
                _source_tag = f'[资金流向] {_source_detail}；' if _source_detail else '[资金流向] '
            parts.append(f"【入选原因】{_source_tag}{reason if reason else '无'}")
            
            latest_news = stock.get('latest_news')
            if latest_news:
                stock_code = stock.get('code', '')
                def _valid_title(t: str) -> bool:
                    if not t:
                        return False
                    ts = t.strip()
                    if len(ts) < 8:
                        return False
                    bad_keywords = ['上交所', '深交所', '证券交易所']
                    if any(bk in ts for bk in bad_keywords) and len(ts) < 20:
                        return False
                    # 过滤无关实体代码 (港股gs/指数zssh,zssz/基金of,zo/债券so)
                    import re
                    brackets = re.findall(r'[\[\(]([a-zA-Z0-9]+)[\]\)]', ts)
                    for b_content in brackets:
                        if not any(c.isdigit() for c in b_content):
                            continue
                        clean = b_content.lower()
                        for prefix in ['zssh', 'zssz', 'gs10', 'gs', 'zo9', 'zo', 'of', 'so', 'sz', 'sh']:
                            if clean.startswith(prefix):
                                clean = clean[len(prefix):]
                                break
                        if clean.isdigit() and clean != str(stock_code) and len(clean) >= 5:
                            return False
                        if b_content.lower() != str(stock_code) and len(b_content) >= 5:
                            if re.match(r'^(gs\d*|zs|zssh|zssz|zo\d*|of|so|sz|sh)\d+', b_content.lower()):
                                return False
                    return True

                titles = []
                for n in latest_news:
                    t = n.get('title', '')
                    if _valid_title(t):
                        titles.append(t)
                    if len(titles) >= 2:
                        break

                if titles:
                    news_str = "; ".join(titles)
                    parts.append(f"【最新动态】{news_str}")

            return '<br>'.join(parts)
        except Exception as e:
            total = stock.get('final_score') or (scoring.get('total_score') if 'scoring_result' in stock else 0)
            return f"综合{float(total or 0):.2f}分；数据解析错误: {str(e)}"

    def _build_advanced_analysis_summary(self, stock: Dict) -> str:
        """生成高级分析摘要（用于Markdown表格）"""
        try:
            parts = []
            scoring_result = stock.get('scoring_result') or {}
            details = scoring_result.get('details') or {}
            advanced = stock.get('advanced_analysis') or scoring_result.get('advanced_analysis') or {}

            def _num(val, default=None):
                if val is None:
                    return default
                if isinstance(val, bool):
                    return default
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, str):
                    s = val.strip()
                    if not s:
                        return default
                    s = s.replace(',', '')
                    if s.endswith('%'):
                        s = s[:-1].strip()
                    if s.startswith('+'):
                        s = s[1:].strip()
                    try:
                        return float(s)
                    except Exception:
                        return default
                if isinstance(val, dict):
                    for k in ('final_score', 'score', 'value', 'pct', 'percent', 'ratio', 'index'):
                        if k in val:
                            v2 = _num(val.get(k), default=None)
                            if v2 is not None:
                                return v2
                    return default
                if isinstance(val, (list, tuple)) and val:
                    return _num(val[0], default=default)
                return default
            
            # 1. 追高风险 (来自 details.momentum)
            momentum = details.get('momentum') or {}
            chase_risk = momentum.get('chase_risk_level', '')
            chase_score = momentum.get('chase_risk_score', 0)
            if chase_risk:
                risk_emoji = {'low': '🟢', 'low_medium': '🟡', 'medium': '🟠', 'high': '🔴'}.get(chase_risk, '⚪')
                risk_cn = {'low': '低', 'low_medium': '中低', 'medium': '中等', 'high': '偏高'}.get(chase_risk, chase_risk)
                safe_score = max(0, min(100, float(chase_score or 0)))
                parts.append(f"追高风险: {risk_emoji} {risk_cn}({safe_score:.0f}分)")

            # 2. 量价形态 (来自 details.volume_health)
            volume_health = details.get('volume_health') or {}
            patterns = volume_health.get('patterns') or {}
            if patterns:
                p_list = []
                for p_type, p_data in patterns.items():
                    if isinstance(p_data, dict) and p_data.get('detected'):
                        days = p_data.get('consecutive_days', 0)
                        p_name = {'vol_up_price_up': '放量上涨', 'vol_down_price_down': '缩量下跌', 
                                 'vol_up_price_down': '放量下跌', 'vol_down_price_up': '缩量上涨'}.get(p_type, p_type)
                        p_list.append(f"{p_name}({days}天)")
                if p_list:
                    parts.append(f"量价: {', '.join(p_list)}")

            # 3. 高级分析维度 (来自 advanced_analysis)
            if advanced:
                # 兼容两种结构：直接中文Key(旧) 或 English Key(新)
                
                # 3.1 综合评分
                adv_score = 0
                if 'overall_score' in advanced:
                    if isinstance(advanced.get('overall_score'), dict):
                        adv_score = advanced['overall_score'].get('final_score', 0)
                    else:
                        adv_score = advanced.get('overall_score', 0)
                else:
                    adv_score = advanced.get('综合评分', 0)
                
                adv_score_num = _num(adv_score, default=0.0)
                parts.append(f"高级评分: {adv_score_num:.1f}分")
                
                dimensions = advanced.get('dimensions', {})
                
                # 3.2 筹码 (Chip)
                chip = dimensions.get('chip', {}).get('details', {}) or advanced.get('筹码分析', {})
                if chip:
                    conc = chip.get('concentration_90') or chip.get('90%筹码集中度', 0)
                    control = chip.get('main_force_control') or chip.get('主力控盘度', 0)
                    lock_raw = chip.get('lock_pattern') or chip.get('锁仓形态')
                    lock_str = ''
                    if isinstance(lock_raw, dict):
                         if lock_raw.get('detected'):
                             lock_str = f"🔒 {lock_raw.get('type', '锁仓')}"
                    elif isinstance(lock_raw, str):
                        lock_str = lock_raw
                    
                    chip_parts = []
                    conc_num = _num(conc, default=None)
                    control_num = _num(control, default=None)
                    if conc_num not in (None, 0.0):
                        chip_parts.append(f"集中度{conc_num:.1f}%")
                    if control_num not in (None, 0.0):
                        chip_parts.append(f"控盘评分{control_num:.1f}/100")
                    if lock_str and lock_str != '无': chip_parts.append(lock_str)
                    
                    if chip_parts:
                        parts.append(f"筹码: {', '.join(chip_parts)}")
                
                # 3.3 板块 (Sector)
                sector = dimensions.get('sector', {}).get('details', {}) or advanced.get('板块联动', {})
                if sector:
                    s_name = sector.get('sector_name') or sector.get('所属板块', '')
                    s_rank = sector.get('sector_rank') or sector.get('板块排名', 0)
                    s_rot = sector.get('rotation_phase') or sector.get('轮动阶段', '')
                    
                    sec_parts = []
                    if s_name and str(s_name).strip() not in ('未知', 'Unknown', 'unknown'):
                        if s_rank:
                            sec_parts.append(f"{s_name}(排名{s_rank})")
                        else:
                            sec_parts.append(f"{s_name}")
                    if s_rot and s_rot != 'unknown': sec_parts.append(s_rot)
                    
                    if sec_parts:
                        parts.append(f"板块: {', '.join(sec_parts)}")

                # 3.4 资金 (Capital)
                capital = dimensions.get('capital_flow', {}).get('details', {}) or advanced.get('资金流向', {})
                if capital:
                    cont_dict = capital.get('continuity', {})
                    inflow_cont = cont_dict.get('consecutive_inflow_days', 0) if isinstance(cont_dict, dict) else capital.get('主力连续流入天数', capital.get('主力连续性', 0))
                    outflow_cont = cont_dict.get('consecutive_outflow_days', 0) if isinstance(cont_dict, dict) else capital.get('主力连续流出天数', 0)
                    cont_trend = cont_dict.get('trend', '') if isinstance(cont_dict, dict) else capital.get('trend', '')
                    retail = capital.get('retail_ratio') or capital.get('散户占比', 0)

                    def _infer_main_force_direction() -> str:
                        trend_val = ''
                        if isinstance(cont_trend, str):
                            trend_val = cont_trend.strip().lower()
                        elif cont_trend is not None:
                            trend_val = str(cont_trend).strip().lower()

                        if trend_val:
                            if any(k in trend_val for k in ['inflow', 'in_flow', 'net_in', 'in', 'buy', 'long', 'positive', '流入', '净流入', '买入']):
                                return '买入'
                            if any(k in trend_val for k in ['outflow', 'out_flow', 'net_out', 'out', 'sell', 'short', 'negative', '流出', '净流出', '卖出']):
                                return '卖出'

                        for k in ['main_net_inflow', 'main_force_net_inflow', 'net_inflow', '主力净流入', '主力资金净流入']:
                            if k in capital:
                                try:
                                    v = float(capital.get(k) or 0)
                                    if v > 0:
                                        return '买入'
                                    if v < 0:
                                        return '卖出'
                                except Exception:
                                    pass

                        if isinstance(cont_dict, dict):
                            inflow_days = cont_dict.get('consecutive_inflow_days', 0) or cont_dict.get('inflow_days', 0) or 0
                            outflow_days = cont_dict.get('consecutive_outflow_days', 0) or cont_dict.get('outflow_days', 0) or 0
                            try:
                                inflow_days = int(inflow_days)
                            except Exception:
                                inflow_days = 0
                            try:
                                outflow_days = int(outflow_days)
                            except Exception:
                                outflow_days = 0
                            if inflow_days > 0 and outflow_days <= 0:
                                return '买入'
                            if outflow_days > 0 and inflow_days <= 0:
                                return '卖出'
                        return ''
                    
                    cap_parts = []
                    inflow_days = int(_num(inflow_cont, default=0) or 0)
                    outflow_days = int(_num(outflow_cont, default=0) or 0)
                    main_cont = inflow_days if inflow_days > 0 else outflow_days
                    if main_cont > 0:
                        direction = _infer_main_force_direction()
                        if direction == '买入':
                            cap_parts.append(f"主力连续净流入{main_cont}天")
                        elif direction == '卖出':
                            cap_parts.append(f"主力连续净流出{main_cont}天")
                        elif inflow_days > 0 and outflow_days <= 0:
                            cap_parts.append(f"主力连续净流入{inflow_days}天")
                        elif outflow_days > 0 and inflow_days <= 0:
                            cap_parts.append(f"主力连续净流出{outflow_days}天")
                        else:
                            cap_parts.append(f"主力连续{main_cont}天")
                    retail_num = _num(retail, default=None)
                    if retail_num is not None and retail_num > 0 and abs(retail_num - 50.0) > 0.1:
                        ds = capital.get('data_source', '') or (dimensions.get('capital_flow', {}).get('details', {}).get('data_source', ''))
                        retail_tags = []
                        if retail_num > 70:
                            retail_tags.append('偏高')
                        elif retail_num < 30:
                            retail_tags.append('偏低')
                        if ds and ds != 'synthetic':
                            retail_tags.append(ds)
                        retail_tag = f"({'/'.join(retail_tags)})" if retail_tags else ""
                        cap_parts.append(f"散户成交额占比{retail_num:.1f}%{retail_tag}")
                    
                    if cap_parts:
                        parts.append(f"资金: {', '.join(cap_parts)}")

                # 3.5 情绪 (Sentiment)
                sent_dim = dimensions.get('sentiment_cycle', {})
                sent_details = sent_dim.get('details', {})
                # 旧版可能直接在 sent_dim 或 advanced.get('情绪周期')
                
                phase_raw = sent_details.get('market_cycle') or sent_details.get('cycle_phase') or ''
                if not phase_raw:
                    try:
                        phase_raw = (advanced.get('情绪周期', {}) or {}).get('市场周期', '')
                    except Exception:
                        phase_raw = ''

                phase_cn_map = {
                    'bottom': '底部',
                    'rising': '上升期',
                    'top': '顶部',
                    'falling': '下降期',
                    'consolidation': '震荡',
                    'unknown': '',
                }
                phase_txt = phase_cn_map.get(str(phase_raw).strip().lower(), str(phase_raw).strip() if phase_raw else '')

                fg_raw = sent_details.get('fear_greed_index') or (advanced.get('情绪周期', {}) or {}).get('恐惧贪婪指数', None)
                fg_num = _num(fg_raw, default=None)

                emotion_txt = ''
                if isinstance(fg_raw, dict):
                    try:
                        emotion_txt = str(fg_raw.get('emotion') or '').strip()
                    except Exception:
                        emotion_txt = ''
                
                show_sentiment = False
                if phase_txt and phase_txt not in ('震荡', '-'):
                    show_sentiment = True
                if emotion_txt and emotion_txt not in ('中性', '-'):
                    show_sentiment = True
                if fg_num is not None and abs(fg_num - 50.0) >= 5:
                    show_sentiment = True

                if show_sentiment:
                    fg_txt = f"{fg_num:.0f}" if fg_num is not None else "-"
                    head = " / ".join([t for t in [phase_txt, emotion_txt] if t]) or '中性'
                    parts.append(f"情绪: {head}, 恐贪{fg_txt}")

                # 3.6 分时 (Intraday)
                intra = dimensions.get('intraday', {}).get('details', {}) or advanced.get('分时特征', {})
                if intra:
                    manip = intra.get('manipulation', {})
                    manip_type = manip.get('type') if isinstance(manip, dict) else intra.get('操盘痕迹', '')
                    if manip_type:
                        parts.append(f"分时: {manip_type}")

                # 3.7 K线形态 (Patterns)
                # pattern_detector returns {'patterns': {'detected_patterns': [...]}} usually
                pats_dim = dimensions.get('patterns', {})
                pats_list = pats_dim.get('details', {}).get('detected_patterns', []) or advanced.get('K线形态', {}).get('识别形态', [])
                if pats_list:
                    # pats_list 可能是 [{'name': '...'}, ...] 或 ['...', ...]
                    pat_names = []
                    for p in pats_list:
                        if isinstance(p, dict):
                            pat_names.append(p.get('name', ''))
                        elif isinstance(p, str):
                            pat_names.append(p)
                    if pat_names:
                        parts.append(f"形态: {', '.join(pat_names[:2])}")
                
            return ' '.join(parts) if parts else "—"
        except Exception as e:
            return f"解析错误: {str(e)}"

    def _generate_group_html(self, group_name: str, stocks: List[Dict], is_passed: bool) -> str:
        """生成分组HTML"""
        if not stocks:
            return ""

        status_icon = "✓" if is_passed else "✗"
        html = f'''
            <div class="group-section">
                <div class="group-header">
                    {status_icon} {group_name}
                    <span class="count">{len(stocks)} 只</span>
                </div>
                <div class="stock-list">
'''

        for stock in stocks:
            rating = stock.get('rating', 'C')
            rating_class = f"rating-{rating.replace('+', '-plus')}"
            score = stock.get('final_score', 0)
            stock_code = _normalize_stock_code(stock.get('stock_code') or stock.get('code') or '')
            stock_name = self._resolve_stock_display_name_from_reports(
                code=stock_code,
                name=stock.get('name'),
                stock_name=stock.get('stock_name'),
                default=stock_code or '未知',
            )
            scoring_result = stock.get('scoring_result', {})
            scores = (scoring_result.get('scores') or {})
            weights_used = (scoring_result.get('weights_used') or {})

            def wpct(key):
                w = weights_used.get(key)
                return f"{int(round(w*100))}%" if isinstance(w, (int, float)) else "-"

            # 安全格式化工具
            def _fmt_float(val, digits=1, default='未知', signed=False):
                try:
                    if val is None or (isinstance(val, str) and val.strip() == ''):
                        return default
                    v = float(val)
                    return f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
                except Exception:
                    return str(val) if val is not None else default

            def _fmt_pct(val, digits=2, default='未知', signed=True):
                s = _fmt_float(val, digits=digits, default=default, signed=signed)
                return s + '%' if s and s != default else default

            # 量化统计
            qd = (scoring_result.get('details', {}).get('quantitative') or {})
            buy = qd.get('buy_count', None)
            sell = qd.get('sell_count', None)
            total = qd.get('total_count', None)
            buy_ratio = qd.get('buy_ratio', None)
            buy_ratio_pct = None
            if isinstance(buy_ratio, (int, float)):
                try:
                    buy_ratio_pct = f"{int(round(buy_ratio*100))}%"
                except Exception:
                    buy_ratio_pct = None

            # 技术指标
            td = (scoring_result.get('details', {}).get('technical') or {})
            rsi = td.get('RSI', None)
            macd = td.get('MACD', None)
            boll = td.get('Bollinger', None)
            rsi_str = _fmt_float(rsi, 1, default='未知')
            macd_str = macd if macd else '未知'
            boll_str = boll if boll else '未知'

            # 股民情绪
            sd = (scoring_result.get('details', {}).get('sentiment') or {})
            inv_score = sd.get('comprehensive_score', None)
            inv_sent = sd.get('comprehensive_sentiment', None)
            inv_score_str = _fmt_float(inv_score, 1, default='未知')
            # 新增：资金流与龙虎榜
            cf = sd.get('capital_flow', {}) or {}
            cf_trend = cf.get('trend', None)
            cf_strength = cf.get('strength', None)
            cf_amt = cf.get('main_inflow', None)
            cf_amt_str = _fmt_money(cf_amt)

            dt = sd.get('dragon_tiger', {}) or {}
            dt_signal = dt.get('last_signal', None)
            dt_date = dt.get('last_date', None)

            # 板块情绪
            secd = (scoring_result.get('details', {}).get('sector') or {})
            sec_name = secd.get('sector_name', None)
            sec_chg = _get_displayable_sector_change(
                secd.get('change_pct'),
                turnover_value=secd.get('turnover_rate'),
                score=scores.get('sector'),
                overall=secd.get('overall'),
                data_source=secd.get('data_source'),
                leader_stock=secd.get('leader_stock')
            )
            sec_turn = secd.get('turnover_rate', None)
            sec_overall = secd.get('overall', None)
            sec_chg_str = _fmt_pct(sec_chg, 2, default='')
            sec_turn_str = _fmt_pct(sec_turn, 2, default='')

            # 基本面
            fd = (scoring_result.get('details', {}).get('fundamental') or {})
            pe = fd.get('pe_ratio', None)
            rev = fd.get('revenue_yoy', None)
            prof = fd.get('net_profit_yoy', None)
            pe_str = _fmt_float(pe, 1, default='未知')
            rev_str = _fmt_pct(rev, 1, default='未知')
            prof_str = _fmt_pct(prof, 1, default='未知')

            # 消息面
            ed = (scoring_result.get('details', {}).get('events') or {})
            ev_rating = ed.get('rating', None)
            ev_pos = ed.get('positive_events', None)
            ev_neg = ed.get('negative_events', None)

            html += f'''
                    <div class="stock-card">
                        <div class="stock-header">
                            <div>
                                <span class="stock-name">{stock_name}</span>
                                <span class="stock-code">{stock_code}</span>
                            </div>
                            <div>
                                <span class="rating-badge {rating_class}">{rating}</span>
                                <span style="margin-left: 8px; font-weight: 600; color: #667eea;">{score:.1f}分</span>
                            </div>
                        </div>
                        <!-- 维度分数与权重摘要 -->
                        <div class="filter-history">
'''

            # 显示筛选历程
            for stage in stock.get('filter_history', []):
                status_class = "passed" if stage['passed'] else "failed"
                status_icon = "✓" if stage['passed'] else "✗"
                # 从阶段名称解析阶段号（如“阶段1: ...”）
                stage_num = None
                try:
                    name_str = str(stage.get('stage_name', ''))
                    for ch in name_str:
                        if ch.isdigit():
                            stage_num = int(ch)
                            break
                except Exception:
                    stage_num = None

                name_str = str(stage.get('stage_name', ''))
                if stage_num == 5:
                    continue

                # 构造合并后的维度元信息
                meta = ''
                if stage_num == 1:
                    meta = f"维度得分 {scores.get('quantitative', 0):.1f}分 · 权重 {wpct('quantitative')} · 买 {'' if buy is None else buy}/{'' if total is None else total} · 卖 {'' if sell is None else sell}{'' if not buy_ratio_pct else f' · 买比例 {buy_ratio_pct}'}"
                elif stage_num == 2:
                    meta = f"维度得分 {scores.get('technical', 0):.1f}分 · 权重 {wpct('technical')} · RSI {rsi_str} · MACD {macd_str} · 布林 {boll_str}"
                elif stage_num == 3:
                    meta = (
                        f"股民 {scores.get('sentiment', 0):.1f}分 · 权重 {wpct('sentiment')} · 综情 {inv_score_str} · {inv_sent or '中性'}"
                        f" · 资金 {cf_trend or '未知'}({cf_strength or '未知'}) · 净额 {cf_amt_str}；"
                        f"板块 {scores.get('sector', 0):.1f}分 · 权重 {wpct('sector')} · {sec_name or '所属板块'} {sec_chg_str} · {sec_overall or '中性'}"
                        f" · 龙虎榜 {dt_signal or '中性'}(净额{_fmt_money(dt.get('net_buy_amount'))}){'' if not dt_date else f'({dt_date})'}"
                    )
                elif stage_num == 4:
                    meta = f"维度得分 {scores.get('fundamental', 0):.1f}分 · 权重 {wpct('fundamental')} · PE {pe_str} · 营收 {rev_str} · 利润 {prof_str}"
                elif stage_num == 5:
                    meta = f"维度得分 {scores.get('events', 0):.1f}分 · 权重 {wpct('events')} · 评级 {ev_rating or '中性'} · 利好 {'' if ev_pos is None else ev_pos} · 利空 {'' if ev_neg is None else ev_neg}"

                meta_html = f'<div class="stage-meta">{meta}</div>' if meta else ''

                html += f'''
                            <div class="filter-stage {status_class}">
                                <div class="stage-name">{status_icon} {stage['stage_name']}</div>
                                <div class="stage-reason">{stage['reason']}</div>
                                {meta_html}
                            </div>
'''

            # 新增：入选原因与最新动态
            selection_reason = _generate_selection_reason(stock)
            latest_news = stock.get('latest_news')
            news_html = ''
            
            if selection_reason or latest_news:
                news_html = '<div class="stock-news-section" style="margin-top: 12px; padding-top: 12px; border-top: 1px dashed #e2e8f0;">'
                
                if selection_reason:
                    news_html += f'<div class="selection-reason" style="margin-bottom: 8px;"><span style="font-weight: 600; color: #4a5568;">🔍 入选原因:</span> <span style="color: #2d3748;">{selection_reason}</span></div>'
                    
                if latest_news:
                    news_html += '<div class="latest-news"><div style="font-weight: 600; color: #4a5568; margin-bottom: 4px;">📰 最新动态:</div>'
                    for news in latest_news[:2]:
                        title = news.get('title', '未知标题')
                        url = news.get('url', '#')
                        date = news.get('publish_time') or news.get('date') or ''
                        if len(date) > 10: date = date[:10]
                        
                        news_html += f'<div style="font-size: 12px; margin-bottom: 4px;"><a href="{url}" target="_blank" style="color: #3182ce; text-decoration: none;">{title}</a> <span style="color: #a0aec0; margin-left: 4px;">{date}</span></div>'
                    news_html += '</div>'
                    
                news_html += '</div>'

            # 在卡片底部添加AI分析结果（如果有）
            ai_analysis_html = self._build_ai_analysis_for_card(stock)

            html += f'''
                        </div>
                        {news_html}
                        {ai_analysis_html}
                    </div>
'''

        html += '''
                </div>
            </div>
'''

        return html

    def _build_ai_brief_for_table(self, stock: Dict) -> str:
        """为TOP表格生成AI简短分析（一行展示）"""
        llm_result = stock.get('llm_analysis')
        if not llm_result:
            return ''

        try:
            # 收集所有有效的模型结果
            valid_results = []
            
            # 1. 尝试作为多模型结果处理：优先按固定顺序检查已知模型
            if isinstance(llm_result, dict):
                for known_model in ['qwen', 'deepseek']:
                    if known_model in llm_result:
                        mr = llm_result[known_model]
                        if isinstance(mr, dict) and 'error' not in mr:
                            valid_results.append((known_model, mr))

            # 2. 如果未找到多模型结果，尝试作为单模型结果处理
            if not valid_results and isinstance(llm_result, dict) and 'operation_advice' in llm_result:
                model_name = llm_result.get('llm_model', 'AI')
                valid_results.append((model_name, llm_result))

            if not valid_results:
                return ''

            html_output = []
            
            # 对每个有效结果生成简短分析 HTML
            for model_name, result in valid_results:
                # 提取关键信息
                operation = result.get('operation_advice', {})
                action = operation.get('action', '')
                position = operation.get('position_control', '')
                confidence = operation.get('confidence', 0)

                risk = result.get('risk_assessment', {})
                risk_level = risk.get('risk_level', '')

                kline = result.get('kline_prediction', {})
                trend = kline.get('trend', '')

                # 构建简短AI分析
                parts = []
                if action:
                    action_icon = '🟢' if action == '买入' else ('🔴' if action == '卖出' else '🟡')
                    parts.append(f"{action_icon}{action}")
                if position:
                    parts.append(f"仓位{position}")
                if trend:
                    parts.append(f"趋势{trend}")
                if risk_level:
                    parts.append(f"{risk_level}风险")
                if confidence:
                    parts.append(f"置信{confidence*100:.0f}%")

                if parts:
                    # 只显示模型名称，不显示厂商
                    model_tag = model_name.split('/')[-1].upper() if model_name else 'AI'
                    html_output.append(f'<div class="ai-brief"><span class="ai-tag">{model_tag}</span>{" · ".join(parts)}</div>')

            return "".join(html_output)

        except Exception as e:
            pass

        return ''

    def _build_ai_analysis_for_card(self, stock: Dict) -> str:
        """为股票卡片生成AI分析详情展示"""
        llm_result = stock.get('llm_analysis')
        if not llm_result:
            return ''

        try:
            # 处理多模型或单模型结果
            results_to_show = []
            # 判断是否为多模型格式
            def contains_model_name(k):
                k_str = str(k)
                if '/' in k_str:
                    model_part = k_str.split('/')[-1].lower()
                else:
                    model_part = k_str.lower()
                return any(
                    model_part == n or model_part.startswith(n)
                    for n in ['qwen', 'deepseek', 'minimax', 'kimi', 'glm']
                )
            is_multi_model = (
                isinstance(llm_result, dict)
                and (
                    any(contains_model_name(k) for k in llm_result.keys())
                    or any(
                        isinstance(v, dict) and any(
                            kk in v for kk in ['operation_advice', 'risk_assessment', 'kline_prediction', 'strategy', 'summary']
                        )
                        for v in llm_result.values()
                    )
                )
            )

            if is_multi_model:
                for model_name, model_result in llm_result.items():
                    if isinstance(model_result, dict) and 'error' not in model_result:
                        # 只提取模型名称部分
                        display_name = model_name.split('/')[-1] if '/' in str(model_name) else model_name
                        results_to_show.append((display_name, model_result))
            else:
                results_to_show.append((llm_result.get('llm_model', 'AI'), llm_result))

            if not results_to_show:
                return ''

            html_parts = ['<div class="ai-analysis-card">']
            html_parts.append('<div class="ai-card-title">🤖 AI智能分析</div>')

            for model_name, result in results_to_show:
                # 只显示模型名称，不显示厂商
                model_display = model_name.split('/')[-1].upper() if model_name else 'AI'

                # 操作建议
                operation = result.get('operation_advice', {})
                action = operation.get('action', '-')
                position = operation.get('position_control', '-')
                target = operation.get('target_price', '-')
                stop_loss = operation.get('stop_loss', '-')
                confidence = operation.get('confidence', 0)

                action_class = 'action-buy' if action == '买入' else ('action-sell' if action == '卖出' else 'action-hold')

                # 风险评估
                risk = result.get('risk_assessment', {})
                risk_level = risk.get('risk_level', '-')
                risk_points = risk.get('risk_points', [])
                risk_class = 'risk-low' if risk_level == '低' else ('risk-high' if risk_level == '高' else 'risk-medium')

                # K线预测
                kline = result.get('kline_prediction', {})
                trend = kline.get('trend', '-')
                pred_conf = kline.get('confidence', 0)
                support = kline.get('support_levels', [])
                resistance = kline.get('resistance_levels', [])

                # 策略
                strategy = result.get('strategy', {})
                short_term = strategy.get('short_term', '')

                # 总结
                summary = result.get('summary', '')

                html_parts.append(f'''
                <div class="ai-model-section">
                    <span class="ai-model-badge">{model_display}</span>
                    <div class="ai-metrics-row">
                        <span class="ai-action {action_class}">{action}</span>
                        <span class="ai-metric">仓位: {position}</span>
                        <span class="ai-metric">目标: {target}</span>
                        <span class="ai-metric">止损: {stop_loss}</span>
                        <span class="ai-metric">置信: {confidence*100:.0f}%</span>
                    </div>
                    <div class="ai-metrics-row">
                        <span class="ai-risk {risk_class}">{risk_level}风险</span>
                        <span class="ai-metric">趋势: {trend}</span>
                        <span class="ai-metric">支撑: {", ".join(str(x) for x in support[:2]) if support else "-"}</span>
                        <span class="ai-metric">阻力: {", ".join(str(x) for x in resistance[:2]) if resistance else "-"}</span>
                    </div>
                    {f'<div class="ai-strategy">短线: {short_term[:60]}{"..." if len(short_term) > 60 else ""}</div>' if short_term else ''}
                    {f'<div class="ai-summary">💡 {summary[:80]}{"..." if len(summary) > 80 else ""}</div>' if summary else ''}
                </div>
                ''')

            html_parts.append('</div>')
            return '\n'.join(html_parts)

        except Exception as e:
            return ''

    def _build_short_analysis(self, stock: Dict) -> str:
        """根据评分与细节生成简短分析文本（≤45字）。
        优先展示量化买入模型，其次技术面要点与板块/事件倾向。
        """
        try:
            scoring = stock.get('scoring_result') or {}
            scores = scoring.get('scores') or {}
            details = scoring.get('details') or {}

            phrases = []

            # 量化模型简述（阶段1）
            MODEL_DISPLAY_MAP = {
                'balance_dual_moving': '均衡双均线',
                'multi_breakthrough': '多重突破',
                'support_resistance': '支撑阻力',
                'trend_pullback': '趋势回踩',
                'ma_resonance': '均线共振',
                'super_reversal': '超级反转',
                'capital_trend': '资金趋势',
                'volume_breakthrough': '量能突破',
                'three_sisters': '三姐妹形态',
                'macd_axis_golden_cross': '轴心MACD金叉',
                'six_dimension_resonance': '六维共振',
                'statistical_quantitative': '统计量化',
                'super_profit_limit_up': '超额涨停',
                'turtle_trading_system': '海龟交易',
                'atr_momentum': 'ATR动量',
                'cta_trend_strategy': 'CTA趋势',
                'machine_learning_rf': '机器学习RF',
                'multi_factor_alpha': '多因子Alpha',
                'pairs_trading_arbitrage': '配对交易套利',
                'hft_microstructure': '高频微结构',
                'ichimoku_cloud': '一目均衡云',
                'bollinger_squeeze': '布林收敛',
                'rsi_divergence': 'RSI背离',
                'stochastic_momentum': '随机动量',
                'volume_price_trend': '量价趋势',
                'parabolic_sar': '抛物转向SAR',
                'chaikin_money_flow': '切金资金流',
                'elder_ray': 'Elder射线',
                'vwap_deviation': 'VWAP偏离',
                'fractal_adaptive_ma': '分形自适应均线'
            }

            try:
                for st in stock.get('filter_history', []) or []:
                    if str(st.get('stage_name', '')).startswith('阶段1'):
                        models = (st.get('details', {}) or {}).get('top_buy_models') or (st.get('details', {}) or {}).get('top_models') or []
                        if models:
                            phrases.append('量化: ' + '、'.join([MODEL_DISPLAY_MAP.get(m, m) for m in models[:2]]))
                        break
            except Exception:
                pass

            # 技术面要点
            tech = details.get('technical') or {}
            macd = tech.get('MACD')
            boll = tech.get('Bollinger')
            rsi = tech.get('RSI')
            tech_parts = []
            if isinstance(macd, str) and macd in {'金叉', '死叉'}:
                tech_parts.append(f'MACD{macd}')
            if isinstance(boll, str) and boll in {'下轨附近', '上轨附近', '中轨附近'}:
                tech_parts.append(f'布林{boll}')
            if isinstance(rsi, (int, float)):
                if rsi < 30:
                    tech_parts.append('RSI超卖')
                elif rsi > 70:
                    tech_parts.append('RSI超买')
                elif 40 <= rsi <= 60:
                    tech_parts.append('RSI中性偏多')
            if tech_parts:
                phrases.append('技术: ' + ' · '.join(tech_parts[:2]))

            # 板块与事件倾向
            sector_score = scores.get('sector')
            if isinstance(sector_score, (int, float)):
                if sector_score >= 70:
                    phrases.append('板块景气')
                elif sector_score <= 40:
                    phrases.append('板块偏弱')

            events = details.get('events') or {}
            ev_rating = str(events.get('rating', '')).strip()
            # if ev_rating:
            #     if '利好' in ev_rating:
            #         phrases.append('事件利好')
            #     elif '利空' in ev_rating:
            #         phrases.append('事件利空')
            #     else:
            #         phrases.append('事件中性')

            # 兜底：至少给出综合分与评级
            if not phrases:
                total = scoring.get('total_score', 0)
                rating = scoring.get('rating', 'C')
                phrases = [f'综合{float(total):.1f}分 · {rating}级']

            text = ' · '.join(phrases)
            return (text[:44] + '…') if len(text) > 45 else text
        except Exception:
            total = (stock.get('scoring_result') or {}).get('total_score', 0)
            rating = (stock.get('scoring_result') or {}).get('rating', 'C')
            return f'综合{float(total):.1f}分 · {rating}级'

    def _generate_llm_analysis_section(self, stocks: List[Dict]) -> str:
        """
        生成LLM智能分析版块HTML

        Args:
            stocks: 股票列表（包含llm_analysis字段的股票）

        Returns:
            LLM分析版块的HTML字符串
        """
        # 筛选有LLM分析结果的股票
        llm_stocks = [s for s in stocks if s.get('llm_analysis')]
        if not llm_stocks:
            return ''

        html = '''
        <!-- LLM智能分析 -->
        <div class="section">
            <div class="section-title">🤖 AI智能分析（大模型深度解读）</div>
            <div class="llm-analysis-container">
'''

        for stock in llm_stocks:
            llm_result = stock.get('llm_analysis', {})
            stock_code = _normalize_stock_code(stock.get('stock_code') or stock.get('code') or '')
            stock_name = self._resolve_stock_display_name_from_reports(
                code=stock_code,
                name=stock.get('name'),
                stock_name=stock.get('stock_name'),
                default=stock_code or '未知',
            )
            rating = stock.get('rating', 'C')
            rating_class = f"rating-{rating.replace('+', '-plus')}"

            # 支持多模型聚合结果
            def contains_model_name(k):
                k_str = str(k)
                if '/' in k_str:
                    model_part = k_str.split('/')[-1].lower()
                else:
                    model_part = k_str.lower()
                return any(
                    model_part == n or model_part.startswith(n)
                    for n in ['qwen', 'deepseek', 'minimax', 'kimi', 'glm']
                )
            is_multi_model = (
                isinstance(llm_result, dict)
                and (
                    any(contains_model_name(k) for k in llm_result.keys())
                    or any(
                        isinstance(v, dict) and any(
                            kk in v for kk in ['operation_advice', 'risk_assessment', 'kline_prediction', 'strategy', 'summary']
                        )
                        for v in llm_result.values()
                    )
                )
            )

            if is_multi_model:
                # 多模型结果
                for model_name, model_result in llm_result.items():
                    if isinstance(model_result, dict) and 'error' not in model_result:
                        # 只提取模型名称部分
                        display_name = model_name.split('/')[-1] if '/' in str(model_name) else model_name
                        html += self._render_single_llm_card(
                            stock_name, stock_code, rating, rating_class,
                            model_result, display_name
                        )
            else:
                # 单模型结果
                model_name = llm_result.get('llm_model', 'AI')
                html += self._render_single_llm_card(
                    stock_name, stock_code, rating, rating_class,
                    llm_result, model_name
                )

        html += '''
            </div>
        </div>
'''
        return html

    def _render_single_llm_card(self, stock_name: str, stock_code: str,
                                 rating: str, rating_class: str,
                                 result: Dict, model_name: str = None) -> str:
        """
        渲染单个LLM分析卡片

        Args:
            stock_name: 股票名称
            stock_code: 股票代码
            rating: 评级
            rating_class: 评级CSS类
            result: LLM分析结果
            model_name: 模型名称

        Returns:
            单个LLM卡片的HTML
        """
        model_badge = ''
        if model_name:
            # 只显示模型名称，不显示厂商
            model_display = model_name.split('/')[-1].upper() if model_name else 'AI'
            model_badge = f'<span class="llm-model-badge">{model_display}</span>'

        # 操作建议
        operation = result.get('operation_advice', {})
        action = operation.get('action', '未知')
        position = operation.get('position_control', '未知')
        target_price = operation.get('target_price', '未知')
        stop_loss = operation.get('stop_loss', '未知')
        confidence = operation.get('confidence', 0)

        action_class = 'action-buy' if action == '买入' else ('action-sell' if action == '卖出' else 'action-hold')

        # 风险评估
        risk = result.get('risk_assessment', {})
        risk_level = risk.get('risk_level', '未知')
        risk_score = risk.get('overall_score', 0)
        risk_points = risk.get('risk_points', [])
        risk_class = 'risk-low' if risk_level == '低' else ('risk-high' if risk_level == '高' else 'risk-medium')

        # K线预测
        kline_pred = result.get('kline_prediction', {})
        trend = kline_pred.get('trend', '未知')
        pred_confidence = kline_pred.get('confidence', 0)
        support_levels = kline_pred.get('support_levels', [])
        resistance_levels = kline_pred.get('resistance_levels', [])

        # 策略
        strategy = result.get('strategy', {})
        short_term = strategy.get('short_term', '')
        mid_term = strategy.get('mid_term', '')
        position_strategy = strategy.get('position_strategy', '')

        # 总结
        summary = result.get('summary', '')

        # 构建HTML
        html = f'''
                <div class="llm-card">
                    <div class="llm-card-header">
                        <div class="llm-stock-info">
                            <span class="stock-name">{stock_name}</span>
                            <span class="stock-code">({stock_code})</span>
                            <span class="rating-badge {rating_class}">{rating}</span>
                            {model_badge}
                        </div>
                        <div class="llm-action {action_class}">
                            {action}
                        </div>
                    </div>

                    <div class="llm-card-body">
                        <!-- 操作建议 -->
                        <div class="llm-section">
                            <div class="llm-section-title">📈 操作建议</div>
                            <div class="llm-metrics">
                                <div class="llm-metric">
                                    <span class="metric-label">仓位控制</span>
                                    <span class="metric-value">{position}</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">目标价</span>
                                    <span class="metric-value">{target_price}</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">止损价</span>
                                    <span class="metric-value">{stop_loss}</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">置信度</span>
                                    <span class="metric-value">{confidence*100:.0f}%</span>
                                </div>
                            </div>
                        </div>

                        <!-- 风险评估 -->
                        <div class="llm-section">
                            <div class="llm-section-title">⚠️ 风险评估</div>
                            <div class="llm-risk">
                                <span class="risk-badge {risk_class}">{risk_level}风险</span>
                                <span class="risk-score">评分: {risk_score}</span>
                            </div>
                            <div class="risk-points">
                                {' · '.join(risk_points[:3]) if risk_points else '暂无风险提示'}
                            </div>
                        </div>

                        <!-- 趋势预测 -->
                        <div class="llm-section">
                            <div class="llm-section-title">📉 趋势预测</div>
                            <div class="llm-metrics">
                                <div class="llm-metric">
                                    <span class="metric-label">趋势</span>
                                    <span class="metric-value">{trend}</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">置信度</span>
                                    <span class="metric-value">{pred_confidence*100:.0f}%</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">支撑位</span>
                                    <span class="metric-value">{', '.join(str(x) for x in support_levels[:2]) if support_levels else '-'}</span>
                                </div>
                                <div class="llm-metric">
                                    <span class="metric-label">阻力位</span>
                                    <span class="metric-value">{', '.join(str(x) for x in resistance_levels[:2]) if resistance_levels else '-'}</span>
                                </div>
                            </div>
                        </div>

                        <!-- 策略建议 -->
                        <div class="llm-section">
                            <div class="llm-section-title">🎯 策略建议</div>
                            <div class="strategy-item">
                                <span class="strategy-label">短线:</span>
                                <span class="strategy-text">{short_term if short_term else '暂无'}</span>
                            </div>
                            <div class="strategy-item">
                                <span class="strategy-label">中线:</span>
                                <span class="strategy-text">{mid_term if mid_term else '暂无'}</span>
                            </div>
                        </div>

                        <!-- 综合建议 -->
                        <div class="llm-summary">
                            <div class="llm-section-title">💡 综合建议</div>
                            <p>{summary if summary else '暂无综合建议'}</p>
                        </div>
                    </div>
                </div>
'''
        return html

    def _get_recommendation_text(self, rating: str) -> str:
        """获取评级对应的建议文本"""
        recommendations = {
            'S': '🌟 强烈推荐',
            'A+': '⭐ 推荐',
            'A': '✓ 可考虑',
            'B': '△ 谨慎',
            'C': '✗ 不建议'
        }
        return recommendations.get(rating, '未知')


def main():
    """测试报表生成器"""
    print("=" * 60)
    print("投资机会挖掘报表生成器 - 测试")
    print("=" * 60)

    # 创建模拟数据
    mock_results = []

    # 10只通过所有筛选的股票
    for i in range(10):
        mock_results.append({
            'stock_code': f"60000{i}",
            'name': f"测试股票{i+1}",
            'passed': True,
            'eliminated_at_stage': 0,
            'final_score': 90 - i * 2,
            'rating': 'S' if i < 2 else 'A+' if i < 5 else 'A',
            'filter_history': [
                {'stage': j, 'stage_name': f'阶段{j}', 'passed': True, 'reason': f'✓ 通过阶段{j}筛选'}
                for j in range(1, 5)
            ]
        })

    # 在各阶段被淘汰的股票（仅阶段1-4）
    for stage in range(1, 5):
        for i in range(18):
            stock_idx = len(mock_results)
            mock_results.append({
                'stock_code': f"00{stock_idx:04d}",
                'name': f"测试股票{stock_idx+1}",
                'passed': False,
                'eliminated_at_stage': stage,
                'final_score': 70 - stage * 5 - i,
                'rating': 'B' if stage <= 2 else 'C',
                'filter_history': [
                    {'stage': j, 'stage_name': f'阶段{j}', 'passed': j < stage,
                     'reason': f"✓ 通过阶段{j}筛选" if j < stage else f"✗ 在阶段{j}被淘汰"}
                    for j in range(1, stage + 1)
                ]
            })

    # 生成报表
    generator = OpportunityReportGenerator()
    report_path = generator.generate_report(mock_results, "投资机会挖掘报告 (测试)")

    print(f"\n✓ 测试报表生成成功: {report_path}")


if __name__ == "__main__":
    main()
