#!/usr/bin/env python3
"""基于 opportunity_top10_*.md 生成雪球长文格式文章.

读取 results/ 下最新的(或指定的) opportunity_top10_*.md 报告,
解析其中 HTML 表格与文本,转写为适合雪球编辑器的 markdown 长文,
并对股票代码自动套用 $股票名(SH/SZxxxxxx)$ cashtag.

用法:
    python scripts/generate_xueqiu_article.py                       # 自动选最新
    python scripts/generate_xueqiu_article.py <md_path>             # 指定文件
    python scripts/generate_xueqiu_article.py <md_path> -o out.md   # 指定输出
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")

SH_PREFIXES = ("60", "68", "11", "13", "50", "51", "58", "90")
SZ_PREFIXES = ("00", "30", "15", "16", "18", "20")


def _exchange_prefix(code: str) -> str:
    code = (code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        return ""
    if code.startswith(SH_PREFIXES):
        return "SH"
    if code.startswith(SZ_PREFIXES):
        return "SZ"
    return "SZ" if code.startswith("0") or code.startswith("3") else "SH"


def cashtag(code: str, name: str) -> str:
    """生成雪球股票链接: [股票名](https://xueqiu.com/S/SH600519).

    使用 markdown 链接而不是 `$..$` cashtag,避免预览器把 `$` 解析为 KaTeX 数学公式。
    粘贴到雪球后渲染为可点击链接,跳转到雪球个股页(失去自动 cashtag 卡片,但预览零报错)。
    """
    name = (name or "").strip().replace(" ", "")
    code = (code or "").strip()
    prefix = _exchange_prefix(code)
    if not prefix or not name:
        return f"{name}({code})" if name else code
    return f"[{name}](https://xueqiu.com/S/{prefix}{code})"


def _read_md(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _find_latest_report() -> Optional[str]:
    pattern = os.path.join(RESULTS_DIR, "opportunity_top10_*.md")
    files = [
        f for f in glob.glob(pattern)
        if not any(tag in os.path.basename(f) for tag in ("wechat", "xueqiu", "alignment"))
    ]
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def _split_sections(md: str) -> Dict[str, str]:
    """以二级标题切分,返回 {section_title: body}."""
    sections: Dict[str, str] = {}
    parts = re.split(r"(?m)^##\s+", md)
    if parts and not parts[0].strip().startswith("##"):
        sections["__head__"] = parts[0]
    for part in parts[1:]:
        line, _, body = part.partition("\n")
        sections[line.strip()] = body
    return sections


def _parse_table(html: str) -> Tuple[List[str], List[List[str]]]:
    """提取 <table> 的表头和数据行(纯文本)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return [], []
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        rows.append([td.get_text(" ", strip=True) for td in tds])
    return headers, rows


def _md_table(headers: List[str], rows: List[List[str]]) -> str:
    if not headers:
        return ""
    line_h = "| " + " | ".join(headers) + " |"
    line_sep = "|" + "|".join(["---"] * len(headers)) + "|"
    lines = [line_h, line_sep]
    for r in rows:
        cells = list(r) + [""] * (len(headers) - len(r))
        lines.append("| " + " | ".join(c.replace("|", "丨") for c in cells) + " |")
    return "\n".join(lines)


def _extract_quote(block: str) -> str:
    for line in block.splitlines():
        s = line.strip()
        if s.startswith(">"):
            return s.lstrip(">").strip()
    return ""


def _format_recap(body: str) -> str:
    """昨日复盘段(bullet 列表)."""
    summary = _extract_quote(body)
    headers, rows = _parse_table(body)
    if not rows:
        return ""
    out = ["## 一、昨日成绩单"]
    if summary:
        out.append(f"> {summary}")
        out.append("")
    for r in rows:
        if len(r) < 8:
            continue
        rank, code, name, score, buy_p, last_p, hold_n, chg = r[:8]
        tag = cashtag(code, name)
        out.append(
            f"- **{rank}** {tag} | 原评分 {score} | 买入 {buy_p} → 最新 {last_p} | 持有 {hold_n}日 | **{chg}**"
        )
    return "\n".join(out)


def _parse_detail_segments(text: str) -> Dict[str, str]:
    """把【概览】xxx；【涨幅】xxx 切成 {key: value}."""
    segs: Dict[str, str] = {}
    for m in re.finditer(r"【([^】]+)】([^；]+)", text):
        segs[m.group(1).strip()] = m.group(2).strip().rstrip("；")
    return segs


def _format_top10(body: str) -> str:
    """TOP10 详细解读."""
    headers, rows = _parse_table(body)
    if not rows:
        return ""
    out = ["## 二、TOP10 精选解读", ""]
    for r in rows[:10]:
        if len(r) < 5:
            continue
        rank, code, name, score, analysis = r[:5]
        segs = _parse_detail_segments(analysis)
        tag = cashtag(code, name)
        overview = segs.get("概览", "")
        tier = ""
        suggest = ""
        m_tier = re.search(r"评级([SAB][+\-]?)", overview)
        if m_tier:
            tier = m_tier.group(1)
        m_sug = re.search(r"建议[:：]([^,，；]+)", overview)
        if m_sug:
            suggest = m_sug.group(1).strip()

        out.append(f"### #{rank} {tag} | {score}分 {tier}级")
        if suggest:
            out.append(f"> 建议：{suggest}")
            out.append("")

        bullets: List[List[str]] = []

        def add(label: str, key: str) -> None:
            v = segs.get(key)
            if v:
                bullets.append([label, v])

        add("涨幅", "涨幅")
        add("板块", "板块")
        add("量化", "量化")
        add("技术", "技术")
        add("基本面", "基本面")
        add("情绪资金", "情绪资金")
        add("消息", "消息")
        add("亮点加分", "关键加减分")
        add("入选理由", "入选原因")
        add("最新动态", "最新动态")
        add("高级", "高级")
        repeat = segs.get("历史重复入选")
        if repeat:
            bullets.insert(0, ["历史复现", repeat])

        for label, val in bullets:
            out.append(f"- **{label}**：{val}")
        out.append("")
    return "\n".join(out)


def _format_confidence(body: str) -> str:
    """置信度分布 + 历史回测表现 (bullet 列表)."""
    out = ["## 三、置信度分布 & 历史回测"]
    tables = re.findall(r"<table[\s\S]*?</table>", body)
    sub_titles = ["当日推荐置信度分布", "历史回测表现（评分区间）", "历史收益分档分布"]
    for idx, tb in enumerate(tables[:3]):
        headers, rows = _parse_table(tb)
        if not rows:
            continue
        out.append("")
        out.append(f"### {sub_titles[idx] if idx < len(sub_titles) else '统计'}")
        out.append("")
        for r in rows:
            if not r:
                continue
            cells = [c for c in r if c is not None]
            label = cells[0] if cells else ""
            rest_pairs = []
            for h, v in zip(headers[1:], cells[1:]):
                rest_pairs.append(f"{h} {v}")
            out.append(f"- **{label}** | " + " | ".join(rest_pairs))

    for line in body.splitlines():
        s = line.strip()
        if s.startswith("**核心统计") or s.startswith("**全样本") or s.startswith("**统计窗口"):
            out.append("")
            out.append("> " + s)
        elif s.startswith("> **备注"):
            out.append("")
            out.append(s)
    return "\n".join(out)


_SECTOR_TOKEN_RE = re.compile(r"\*\*([^*()]+)\(((?:\d{6}|[A-Z0-9]+))\)\*\*\s*([+\-]?\d+\.\d+%)?")


def _convert_sector_text(raw: str) -> str:
    def repl(m: re.Match) -> str:
        name, code, pct = m.group(1), m.group(2), m.group(3) or ""
        tag = cashtag(code, name)
        return (f"{tag} {pct} " if pct else f"{tag} ").rstrip() + " "

    return _SECTOR_TOKEN_RE.sub(repl, raw).rstrip()


def _format_sectors(body: str) -> str:
    headers, rows = _parse_table(body)
    if not rows:
        return ""
    out = ["## 四、热点板块分布", ""]
    for r in rows:
        if len(r) < 2:
            continue
        sector, stocks = r[0], r[1]
        sector_clean = sector.strip()
        out.append(f"**{sector_clean}**")
        out.append("")
        out.append(_convert_sector_text(stocks))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


_FUND_BOLD_RE = re.compile(r"<strong>([^<]+)</strong>\((\d{6})\)")


def _format_fund_flow(body: str) -> str:
    out = ["## 五、主力资金流向 TOP10"]
    tables = re.findall(r"<table[\s\S]*?</table>", body)
    sub_titles = ["🔴 主力净流入 TOP10", "🟢 主力净流出 TOP10"]
    for idx, tb in enumerate(tables[:2]):
        headers, rows = _parse_table(tb)
        if not rows:
            continue
        out.append("")
        out.append(f"### {sub_titles[idx] if idx < len(sub_titles) else '资金流向'}")
        out.append("")
        for r in rows[:10]:
            if len(r) < 3:
                continue
            seq, stock_cell, detail = r[0], r[1], r[2]
            m = re.match(r"([^\(]+)\((\d{6})\)", stock_cell)
            tag = cashtag(m.group(2), m.group(1)) if m else stock_cell
            out.append(f"- **#{seq}** {tag} — {detail}")
    return "\n".join(out)


def _format_market_quote(*blocks: str) -> str:
    for block in blocks:
        if not block:
            continue
        for ln in block.splitlines():
            s = ln.strip()
            if s.startswith("> **市场环境"):
                return s
    return ""


def build_xueqiu_article(md_path: str) -> str:
    raw = _read_md(md_path)
    sections = _split_sections(raw)
    head = sections.get("__head__", "")

    date_match = re.search(r"opportunity_top10_(\d{8})_", os.path.basename(md_path))
    if date_match:
        d = date_match.group(1)
        date_label = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    else:
        date_label = datetime.now().strftime("%Y-%m-%d")

    recap_body = None
    top_body = None
    confidence_body = None
    sectors_body = None
    fund_body = None
    for title, body in sections.items():
        if "昨日选股复盘" in title:
            recap_body = body
        elif "综合排名" in title:
            top_body = body
        elif "置信度分级" in title or "历史回测" in title:
            confidence_body = body
        elif "热点股票板块分布" in title:
            sectors_body = body
        elif "个股资金流向" in title:
            fund_body = body

    market_line = _format_market_quote(head, recap_body or "", top_body or "")

    lines: List[str] = []
    lines.append(f"# 📊 {date_label} 量化投资机会挖掘｜S/A 级精选")
    lines.append("")
    if market_line:
        lines.append(market_line)
        lines.append("")
    lines.append("> 本文由 Kronos 多因子量化引擎(v5.6 / v20参数)自动生成,基于 30 个量化模型 + 技术面 / 基本面 / 情绪 / 资金 / 消息 多维打分,仅供参考,不构成投资建议。")
    lines.append("")
    lines.append("---")
    lines.append("")

    if recap_body:
        text = _format_recap(recap_body)
        if text:
            lines.append(text)
            lines.append("")
            lines.append("---")
            lines.append("")

    if top_body:
        text = _format_top10(top_body)
        if text:
            lines.append(text)
            lines.append("---")
            lines.append("")

    if confidence_body:
        text = _format_confidence(confidence_body)
        if text:
            lines.append(text)
            lines.append("")
            lines.append("---")
            lines.append("")

    if sectors_body:
        text = _format_sectors(sectors_body)
        if text:
            lines.append(text)
            lines.append("---")
            lines.append("")

    if fund_body:
        text = _format_fund_flow(fund_body)
        if text:
            lines.append(text)
            lines.append("")
            lines.append("---")
            lines.append("")

    lines.append("## 风险提示")
    lines.append("")
    lines.append("以上分析仅供参考,不构成投资建议。市场有风险,入市需谨慎。")
    lines.append("")
    lines.append("> 关注作者,获取每日量化选股报告与算法迭代日志。")
    return "\n".join(lines)


def generate(input_md: Optional[str] = None, output_md: Optional[str] = None) -> str:
    src = input_md or _find_latest_report()
    if not src or not os.path.exists(src):
        raise FileNotFoundError(f"找不到 opportunity_top10 报告: {src}")

    content = build_xueqiu_article(src)

    if not output_md:
        base = os.path.basename(src)
        m = re.match(r"opportunity_top10_(\d{8}_\d{6})\.md", base)
        stamp = m.group(1) if m else datetime.now().strftime("%Y%m%d_%H%M%S")
        output_md = os.path.join(RESULTS_DIR, f"opportunity_top10_xueqiu_{stamp}.md")

    os.makedirs(os.path.dirname(output_md), exist_ok=True)
    with open(output_md, "w", encoding="utf-8") as f:
        f.write(content)
    return output_md


def main() -> int:
    parser = argparse.ArgumentParser(description="把 opportunity_top10_*.md 转写为雪球长文格式")
    parser.add_argument("input", nargs="?", help="源 markdown 路径,缺省自动选取最新")
    parser.add_argument("-o", "--output", help="输出雪球版 markdown 路径")
    args = parser.parse_args()
    out = generate(args.input, args.output)
    print(f"✓ 雪球长文已生成: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
