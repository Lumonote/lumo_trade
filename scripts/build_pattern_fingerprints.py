"""Build pattern fingerprints for the full A-share market.

Fetches last 30 trading days of daily OHLCV from Tushare bulk data by default
with a Sina Finance fallback, computes normalized curves and slopes, and stores
results in SQLite.

Usage:
    python scripts/build_pattern_fingerprints.py
    python scripts/build_pattern_fingerprints.py --limit 50   # 调试
    python scripts/build_pattern_fingerprints.py --source sina
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from analysis.pattern_matcher import (  # noqa: E402
    TARGET_LENGTH,
    linear_slope,
    normalize_curve,
)
from analysis.pattern_store import Fingerprint, PatternStore  # noqa: E402

DB_PATH = ROOT_DIR / "data" / "pattern_fingerprints.db"

SINA_STOCK_COUNT_URL = (
    "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeStockCount"
)
SINA_STOCK_LIST_URL = (
    "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)
SINA_KLINE_URL = (
    "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData"
)
EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 10
DEFAULT_WORKERS = 4
WINDOW = 30  # 取最近 30 个交易日


def parse_market_from_symbol(symbol: str) -> str:
    """Sina symbol 形如 'sh600977' / 'sz000001' / 'bj920000'。"""
    prefix = str(symbol or "").strip().lower()[:2]
    if prefix == "sh":
        return "SH"
    if prefix == "sz":
        return "SZ"
    if prefix == "bj":
        return "BJ"
    return "SZ"


def parse_market_from_secid(secid: str) -> str:
    """Eastmoney secid 形如 '1.600977' / '0.000001'。"""
    market_code, _, stock_code = str(secid or "").strip().partition(".")
    if market_code == "1":
        return "SH"
    if stock_code.startswith(("43", "83", "87", "92")):
        return "BJ"
    return "SZ"


def sina_symbol_from_code(stock_code: str) -> str:
    """将 6 位 A 股代码转换为 Sina symbol。"""
    code = str(stock_code or "").strip().zfill(6)
    if code.startswith(("60", "68", "90")):
        return f"sh{code}"
    if code.startswith(("43", "83", "87", "92")):
        return f"bj{code}"
    return f"sz{code}"


def parse_market_from_ts_code(ts_code: str, stock_code: str = "") -> str:
    """Tushare ts_code 形如 '600977.SH' / '000001.SZ' / '920000.BJ'。"""
    suffix = str(ts_code or "").rsplit(".", 1)[-1].upper()
    if suffix in {"SH", "SZ", "BJ"}:
        return suffix
    return parse_market_from_symbol(sina_symbol_from_code(stock_code))


def build_fingerprint_for_stock(
    stock_code: str,
    stock_name: str,
    market: str,
    industry: str,
    klines_raw: List[Any],
    snapshot_date: datetime.date,
) -> Optional[Fingerprint]:
    """从原始日 K 数据构建指纹。"""
    if not klines_raw or len(klines_raw) < 10:
        return None
    closes: List[float] = []
    for item in klines_raw[-WINDOW:]:
        try:
            if isinstance(item, dict):
                close = float(item.get("close") or 0)
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                # Tencent-style fallback shape: [date, open, close, high, low, volume]
                close = float(item[2])
            else:
                parts = str(item).split(",")
                if len(parts) < 3:
                    continue
                close = float(parts[2])
            if close <= 0:
                continue
            closes.append(close)
        except (TypeError, ValueError):
            continue
    if len(closes) < 10:
        return None

    norm = normalize_curve(closes, target_length=TARGET_LENGTH)
    if norm is None:
        return None
    slope = linear_slope(norm)
    last_pct = 0.0
    if len(closes) >= 2 and closes[-2] > 0:
        last_pct = (closes[-1] / closes[-2] - 1) * 100

    return Fingerprint(
        stock_code=stock_code,
        stock_name=stock_name,
        market=market,
        industry=industry,
        normalized_curve=norm,
        mean_slope=slope,
        latest_close=closes[-1],
        latest_change_pct=last_pct,
        snapshot_date=snapshot_date,
    )


def _http_get_json(
    url: str,
    params: dict,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 3,
) -> Any:
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://finance.sina.com.cn/",
        },
    )
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="ignore"))
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                delay = 0.3 * (attempt + 1)
                if isinstance(exc, urllib.error.HTTPError) and exc.code == 456:
                    delay = 2.0 * (attempt + 1)
                time.sleep(delay)
    raise last_error or RuntimeError("http request failed")


def _load_tushare_token() -> str:
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if token:
        return token

    config_dir = os.environ.get("KRONOS_CONFIG_DIR")
    cfg_path = Path(config_dir) / "tushare_config.json" if config_dir else ROOT_DIR / "config" / "tushare_config.json"
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
        token = str((cfg.get("tushare") or {}).get("token") or cfg.get("token") or "")
        token = token.strip()
        if token == "your_tushare_token_here":
            return ""
        return token
    except Exception:
        return ""


def _latest_tushare_trade_dates(pro, snapshot_date: datetime.date, count: int) -> List[str]:
    start_date = (snapshot_date - datetime.timedelta(days=max(90, count * 4))).strftime("%Y%m%d")
    end_date = snapshot_date.strftime("%Y%m%d")
    trade_cal = pro.trade_cal(
        exchange="",
        start_date=start_date,
        end_date=end_date,
        is_open="1",
        fields="cal_date",
    )
    if trade_cal is None or trade_cal.empty:
        return []
    dates = sorted(str(value) for value in trade_cal["cal_date"].dropna().tolist())
    return dates[-count:]


def build_fingerprints_from_tushare(
    snapshot_date: datetime.date,
    limit: Optional[int] = None,
    progress_callback=None,
) -> Optional[Tuple[List[Fingerprint], int]]:
    """使用 Tushare 批量日线构建指纹；无 token 时返回 None。"""
    token = _load_tushare_token()
    if not token:
        return None

    import tushare as ts

    pro = ts.pro_api(token)
    stock_basic = pro.stock_basic(
        exchange="",
        list_status="L",
        fields="ts_code,symbol,name,market,industry",
    )
    if stock_basic is None or stock_basic.empty:
        raise RuntimeError("Tushare stock_basic returned no stocks")

    stock_basic = stock_basic.sort_values("symbol").reset_index(drop=True)
    if limit:
        stock_basic = stock_basic.head(limit)

    stocks = []
    ts_codes = set()
    for row in stock_basic.to_dict("records"):
        ts_code = str(row.get("ts_code") or "").strip().upper()
        code = str(row.get("symbol") or "").strip().zfill(6)
        if not ts_code or not code.isdigit():
            continue
        ts_codes.add(ts_code)
        stocks.append({
            "ts_code": ts_code,
            "stock_code": code,
            "stock_name": str(row.get("name") or "").strip(),
            "market": parse_market_from_ts_code(ts_code, code),
            "industry": str(row.get("industry") or "").strip(),
        })

    total = len(stocks)
    if not total:
        raise RuntimeError("Tushare stock_basic returned no usable A-share stocks")
    if progress_callback:
        progress_callback(f"开始抓取 {total} 只股票的 30 日 K 线（Tushare）")

    trade_dates = _latest_tushare_trade_dates(pro, snapshot_date, WINDOW + 5)
    if len(trade_dates) < 10:
        raise RuntimeError("Tushare trade calendar returned too few open dates")

    records_by_code = {stock["ts_code"]: [] for stock in stocks}
    for idx, trade_date in enumerate(trade_dates, start=1):
        daily = pro.daily(
            trade_date=trade_date,
            fields="ts_code,trade_date,open,high,low,close,pct_chg",
        )
        if daily is None or daily.empty:
            continue
        for row in daily.to_dict("records"):
            ts_code = str(row.get("ts_code") or "").strip().upper()
            if ts_code not in ts_codes:
                continue
            records_by_code[ts_code].append({
                "trade_date": str(row.get("trade_date") or ""),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "pct_chg": row.get("pct_chg"),
            })
        if progress_callback and idx % 10 == 0:
            progress_callback(f"Tushare 日线进度 {idx}/{len(trade_dates)}")
        time.sleep(0.12)

    fingerprints: List[Fingerprint] = []
    for stock in stocks:
        records = sorted(
            records_by_code.get(stock["ts_code"], []),
            key=lambda item: item.get("trade_date") or "",
        )
        fp = build_fingerprint_for_stock(
            stock_code=stock["stock_code"],
            stock_name=stock["stock_name"],
            market=stock["market"],
            industry=stock["industry"],
            klines_raw=records,
            snapshot_date=snapshot_date,
        )
        if fp is not None:
            fingerprints.append(fp)

    return fingerprints, total


def fetch_recent_klines(symbol: str, limit: int = 30) -> Tuple[str, List[dict]]:
    """拉取该 symbol 最近 limit 个日 K。返回 (股票名, 原始 K 线数组)。"""
    params = {
        "symbol": symbol,
        "scale": "240",
        "ma": "no",
        "datalen": str(limit + 5),  # 多取几个防止节假日
    }
    payload = _http_get_json(SINA_KLINE_URL, params)
    if isinstance(payload, dict):
        data = payload.get("data") or {}
        if isinstance(data, dict):
            name = str(data.get("name") or "")
            klines = data.get("klines") or []
            return name, list(klines) if isinstance(klines, list) else []
    if not isinstance(payload, list):
        return "", []
    klines = [item for item in payload if isinstance(item, dict)]
    return "", klines


def list_all_stocks(limit: Optional[int] = None) -> List[dict]:
    """获取沪深京全 A 股代码列表。

    返回 [{stock_code, symbol, stock_name, industry, market}, ...]
    """
    page_size = 80
    page = 1
    out: List[dict] = []
    seen = set()

    try:
        count_payload = _http_get_json(SINA_STOCK_COUNT_URL, {"node": "hs_a"})
        max_pages = max(1, (int(count_payload) + page_size - 1) // page_size + 1)
    except Exception:
        max_pages = 100

    while True:
        params = {
            "page": str(page),
            "num": str(page_size),
            "sort": "symbol",
            "asc": "1",
            "node": "hs_a",
            "symbol": "",
            "_s_r_a": "init",
        }
        rows = _http_get_json(SINA_STOCK_LIST_URL, params)
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("code") or "").strip().zfill(6)
            symbol = str(row.get("symbol") or "").strip().lower()
            name = str(row.get("name") or "").strip()
            if not code.isdigit() or len(code) != 6:
                continue
            if symbol[:2] not in {"sh", "sz", "bj"}:
                symbol = sina_symbol_from_code(code)
            if code in seen:
                continue
            seen.add(code)
            out.append({
                "stock_code": code,
                "symbol": symbol,
                "stock_name": name,
                "industry": "",
                "market": parse_market_from_symbol(symbol),
            })
            if limit and len(out) >= limit:
                return out
        if len(rows) < page_size:
            break
        page += 1
        time.sleep(0.1)
        if page > max_pages:
            break
    return out


def list_all_secids(limit: Optional[int] = None) -> List[dict]:
    """获取 Eastmoney secid 格式的 A 股列表，保留旧调用方兼容性。"""
    params = {
        "pn": "1",
        "pz": str(limit or 10000),
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81",
        "fields": "f12,f13,f14,f100",
    }
    payload = _http_get_json(EASTMONEY_CLIST_URL, params)
    rows = ((payload or {}).get("data") or {}).get("diff") if isinstance(payload, dict) else []

    stocks: List[dict] = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("f12") or "").strip().zfill(6)
        if not code.isdigit() or len(code) != 6 or code in seen:
            continue
        seen.add(code)
        market_id = str(row.get("f13") if row.get("f13") is not None else "")
        if market_id not in {"0", "1"}:
            market_id = "1" if code.startswith(("60", "68", "90")) else "0"
        secid = f"{market_id}.{code}"
        market = parse_market_from_secid(secid)
        symbol = f"{market.lower()}{code}" if market in {"SH", "SZ", "BJ"} else sina_symbol_from_code(code)
        stocks.append({
            "stock_code": code,
            "secid": secid,
            "symbol": symbol,
            "stock_name": str(row.get("f14") or "").strip(),
            "industry": str(row.get("f100") or "").strip(),
            "market": market,
        })
        if limit and len(stocks) >= limit:
            break
    return stocks


def _process_one(stock: dict, snapshot_date: datetime.date) -> Optional[Fingerprint]:
    """单股拉取并构建指纹。失败返回 None。"""
    try:
        name, klines = fetch_recent_klines(stock["symbol"], limit=WINDOW)
    except Exception as exc:
        print(f"[warn] {stock['stock_code']}: kline fetch failed: {exc}")
        return None
    final_name = name or stock["stock_name"]
    return build_fingerprint_for_stock(
        stock_code=stock["stock_code"],
        stock_name=final_name,
        market=stock["market"],
        industry=stock["industry"],
        klines_raw=klines,
        snapshot_date=snapshot_date,
    )


def build_all(
    store: PatternStore,
    limit: Optional[int] = None,
    max_workers: int = DEFAULT_WORKERS,
    snapshot_date: Optional[datetime.date] = None,
    data_source: str = "auto",
    progress_callback=None,
) -> dict:
    snapshot_date = snapshot_date or datetime.date.today()
    store.init_schema()
    if limit is None and store.successful_snapshot_exists(snapshot_date):
        if progress_callback:
            progress_callback(f"{snapshot_date.isoformat()} 指纹库已是最新，跳过全量重建")
        status = store.current_status()
        return {
            "snapshot_id": None,
            "snapshot_date": snapshot_date.isoformat(),
            "total": int(status.get("total_stocks") or 0),
            "succeeded": 0,
            "failed": 0,
            "elapsed_seconds": 0,
            "status": "skipped",
            "source": "cache",
            "skipped": True,
        }
    snapshot_id = store.start_snapshot(snapshot_date)
    started_at = time.time()
    data_source = (data_source or "auto").lower()
    if data_source not in {"auto", "tushare", "sina"}:
        raise ValueError("data_source must be one of: auto, tushare, sina")

    if data_source in {"auto", "tushare"}:
        try:
            result = build_fingerprints_from_tushare(
                snapshot_date=snapshot_date,
                limit=limit,
                progress_callback=progress_callback,
            )
        except Exception as exc:
            if data_source == "tushare":
                store.finish_snapshot(
                    snapshot_id, status="failed", total=0, succeeded=0,
                    failed=0, error_log=f"tushare: {exc}",
                )
                raise
            result = None
            if progress_callback:
                progress_callback(f"Tushare 不可用，切换 Sina：{exc}")

        if result is not None:
            fingerprints, total = result
            if fingerprints:
                store.upsert_fingerprints(fingerprints)
            succeeded = len(fingerprints)
            failed = max(0, total - succeeded)
            elapsed = time.time() - started_at
            fail_rate = failed / total if total else 1.0
            status = "failed" if fail_rate > 0.30 else "success"
            store.finish_snapshot(
                snapshot_id,
                status=status,
                total=total,
                succeeded=succeeded,
                failed=failed,
                error_log=None,
            )
            return {
                "snapshot_id": snapshot_id,
                "snapshot_date": snapshot_date.isoformat(),
                "total": total,
                "succeeded": succeeded,
                "failed": failed,
                "elapsed_seconds": round(elapsed, 1),
                "status": status,
                "source": "tushare",
            }

    try:
        stocks = list_all_stocks(limit=limit)
    except Exception as exc:
        store.finish_snapshot(
            snapshot_id, status="failed", total=0, succeeded=0,
            failed=0, error_log=f"list_all_stocks: {exc}",
        )
        raise

    total = len(stocks)
    if progress_callback:
        progress_callback(f"开始抓取 {total} 只股票的 30 日 K 线（Sina）")

    succeeded = 0
    failed = 0
    errors: List[str] = []
    buffer: List[Fingerprint] = []
    BATCH = 200

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_process_one, stock, snapshot_date): stock
            for stock in stocks
        }
        for idx, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            stock = futures[future]
            try:
                fp = future.result()
            except Exception as exc:
                fp = None
                errors.append(f"{stock['stock_code']}: {exc}")
            if fp is None:
                failed += 1
            else:
                buffer.append(fp)
                succeeded += 1
            if len(buffer) >= BATCH:
                store.upsert_fingerprints(buffer)
                buffer.clear()
            if progress_callback and idx % 200 == 0:
                progress_callback(
                    f"进度 {idx}/{total}  成功 {succeeded}  失败 {failed}"
                )
    if buffer:
        store.upsert_fingerprints(buffer)

    elapsed = time.time() - started_at
    fail_rate = failed / total if total else 1.0
    status = "failed" if fail_rate > 0.30 else "success"
    store.finish_snapshot(
        snapshot_id,
        status=status,
        total=total,
        succeeded=succeeded,
        failed=failed,
        error_log=("; ".join(errors[:30]) if errors else None),
    )
    return {
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date.isoformat(),
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "elapsed_seconds": round(elapsed, 1),
        "status": status,
        "source": "sina",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="构建全市场形态指纹库")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 只（调试用）")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--db", type=str, default=str(DB_PATH))
    parser.add_argument(
        "--source",
        choices=["auto", "tushare", "sina"],
        default="auto",
        help="数据源：auto 优先 Tushare，失败后使用 Sina；不使用东方财富",
    )
    args = parser.parse_args()
    store = PatternStore(Path(args.db))

    def log(msg: str) -> None:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

    result = build_all(
        store,
        limit=args.limit,
        max_workers=args.workers,
        data_source=args.source,
        progress_callback=log,
    )
    log(f"完成: {result}")


if __name__ == "__main__":
    main()
