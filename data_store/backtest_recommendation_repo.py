"""回测推荐记录仓库 —— backtest_recommendation 表(SQLite-only)。

原 ``results/backtest/recommendations.csv`` 的持久层替代(2026-07-09「全部走
SQLite」约定)。写侧 = scripts/auto_backtest.py(每日推荐落库 + 前瞻收益回填),
读侧 = 报告生成器「历史回测表现」、评分健康度卡片、自动优化器。

DataFrame 端保留旧 CSV 列名(含 ``rank``);DB 端用 ``item_rank``(RANK 是
SQLite 关键字),``load_df``/``save_df`` 负责双向映射。存量 CSV 仅在表空时经
:func:`seed_from_legacy_csv_if_empty` 一次性导入(传输格式,内存解析)。
"""
from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Dict, Iterable, List, Optional

from data_store.connection import get_conn

# DataFrame 侧列序 = 旧 recommendations.csv 列序(下游 pandas 逻辑零改动)
DF_COLUMNS = (
    'report_date', 'rank', 'code', 'name', 'score', 'chase_risk',
    'buy_signals', 'sell_signals', 'rsi', 'day_change', 'change_3d',
    'change_5d', 'sector_score', 'quant_score', 'tech_score',
    'momentum_pattern', 'buy_price',
    'return_1d', 'return_3d', 'return_5d', 'return_10d',
)

# DB 侧列(rank → item_rank)
_DB_COLUMNS = tuple('item_rank' if c == 'rank' else c for c in DF_COLUMNS)


def _norm_date(value: Any) -> str:
    text = str(value or '').strip()
    return text[:10]


def _norm_code(value: Any) -> str:
    text = str(value or '').strip().split('.')[0]
    digits = ''.join(ch for ch in text if ch.isdigit())
    return digits.zfill(6) if digits else ''


def _clean(value: Any) -> Any:
    """NaN/NaT → None,其余原样(sqlite 不认 float('nan'))。"""
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    try:  # pandas NaT / pd.NA 等
        import pandas as pd
        if pd.isna(value):
            return None
    except (TypeError, ValueError, ImportError):
        pass
    return value


def _to_db_row(record: Dict[str, Any]) -> Optional[tuple]:
    code = _norm_code(record.get('code'))
    date = _norm_date(record.get('report_date'))
    if not code or not date:
        return None
    values = []
    for col in DF_COLUMNS:
        if col == 'report_date':
            values.append(date)
        elif col == 'code':
            values.append(code)
        else:
            values.append(_clean(record.get(col)))
    values.append(_dt.datetime.now().isoformat(timespec='seconds'))  # updated_at
    return tuple(values)


def count() -> int:
    row = get_conn().execute("SELECT COUNT(*) FROM backtest_recommendation").fetchone()
    return int(row[0]) if row else 0


def replace_day(report_date: Any, records: Iterable[Dict[str, Any]]) -> int:
    """整日替换(与旧 save_recommendations「去除同日重复再追加」语义一致)。"""
    date = _norm_date(report_date)
    rows = [r for r in (_to_db_row(dict(rec, report_date=date)) for rec in records) if r]
    conn = get_conn()
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM backtest_recommendation WHERE report_date=?", (date,))
        _insert_rows(conn, rows, on_conflict='update')
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


def upsert_rows(records: Iterable[Dict[str, Any]], on_conflict: str = 'update') -> int:
    """按 (report_date, code) upsert。

    on_conflict='update' 覆盖旧行(收益回填);'ignore' 保留已存在行
    (历史报告回填脚本语义:实盘打分器写入的行优先)。
    """
    rows = [r for r in (_to_db_row(rec) for rec in records) if r]
    if not rows:
        return 0
    conn = get_conn()
    conn.execute("BEGIN")
    try:
        _insert_rows(conn, rows, on_conflict=on_conflict)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


def _insert_rows(conn, rows: List[tuple], on_conflict: str) -> None:
    if not rows:
        return
    cols = ",".join(_DB_COLUMNS) + ",updated_at"
    placeholders = ",".join("?" * (len(_DB_COLUMNS) + 1))
    if on_conflict == 'ignore':
        clause = "ON CONFLICT(report_date, code) DO NOTHING"
    else:
        updates = ",".join(
            f"{c}=excluded.{c}" for c in _DB_COLUMNS + ('updated_at',)
            if c not in ('report_date', 'code'))
        clause = f"ON CONFLICT(report_date, code) DO UPDATE SET {updates}"
    conn.executemany(
        f"INSERT INTO backtest_recommendation({cols}) VALUES({placeholders}) {clause}",
        rows,
    )


def load_df(start_date: Optional[str] = None, end_date: Optional[str] = None):
    """全量(或按日期区间)读为 DataFrame,列序/列名与旧 CSV 完全一致。"""
    import pandas as pd

    sql = f"SELECT {','.join(_DB_COLUMNS)} FROM backtest_recommendation"
    conds, params = [], []
    if start_date:
        conds.append("report_date >= ?")
        params.append(_norm_date(start_date))
    if end_date:
        conds.append("report_date <= ?")
        params.append(_norm_date(end_date))
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY report_date, item_rank, code"
    df = pd.read_sql_query(sql, get_conn(), params=params or None)
    df = df.rename(columns={'item_rank': 'rank'})
    return df[list(DF_COLUMNS)]


def save_df(df) -> int:
    """DataFrame 全量 upsert 写回(update_returns 等就地改列后调用)。"""
    if df is None or len(df) == 0:
        return 0
    return upsert_rows(df.to_dict(orient='records'), on_conflict='update')


def delete_by_name(name: str) -> int:
    cur = get_conn().execute(
        "DELETE FROM backtest_recommendation WHERE name=?", (str(name),))
    return int(cur.rowcount or 0)


def seed_from_legacy_csv_if_empty(csv_path: Optional[str] = None) -> int:
    """表空时从存量 recommendations.csv 一次性导入(幂等;表非空 = no-op)。

    默认候选:results_dir()/backtest/recommendations.csv(桌面/CLI 统一目录,
    最新),回退仓库 results/backtest/recommendations.csv(打包 App 无此路径,
    静默跳过)。导入后 CSV 保留原地不动,仅作历史存档。
    """
    if count() > 0:
        return 0

    candidates: List[str] = []
    if csv_path:
        candidates.append(str(csv_path))
    else:
        try:
            from webui.services.paths import results_dir
            candidates.append(os.path.join(str(results_dir()), 'backtest', 'recommendations.csv'))
        except Exception:  # noqa: BLE001 — 无 webui 上下文时跳过
            pass
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates.append(os.path.join(repo_root, 'results', 'backtest', 'recommendations.csv'))

    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            import pandas as pd
            df = pd.read_csv(path, encoding='utf-8-sig')
        except Exception:  # noqa: BLE001 — 损坏的存量文件不阻塞,试下一个候选
            continue
        if df.empty or 'report_date' not in df.columns or 'code' not in df.columns:
            continue
        return upsert_rows(df.to_dict(orient='records'), on_conflict='update')
    return 0
