"""星轨图谱仓库 —— 物理AI/AI产业链 同心轨道图的持久化与增删。

完全数据驱动:轨道环(ring)/板块(board)/钉选股(stock)都存库,前端可任意增删。
板块码为真实东财 BK 码,运行时由服务层叠加实时涨跌与成分股(见
``webui/services/star_orbit_service.py``)。本模块只管结构化读写,不联网。

首次为空时由 :func:`seed_if_empty` 灌入「图中国际概念→A股板块」的种子映射
(种子是数据,可随时改/删);股票不灌种子,默认实时拉成分股。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from data_store.connection import get_conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---- 种子映射:两张产业链图落到 A股可取数板块(真实 BK 码) ----
# 仅 ring + board;成分股运行时实时拉取(不写死个股)。
SEED_RINGS: List[Dict[str, Any]] = [
    {
        "name": "AI大脑·算力底座",
        "subtitle": "世界模型 / 算力底座 — 芯片与封装",
        "color": "#5b8cff",
        "boards": [
            ("BK1127", "AI芯片", "concept"),
            ("BK1134", "算力概念", "concept"),
            ("BK1036", "半导体", "industry"),
            ("BK0952", "第三代半导体", "concept"),
            ("BK1326", "半导体设备", "industry"),
            ("BK1101", "先进封装", "concept"),
            ("BK1331", "数字芯片设计", "industry"),
        ],
    },
    {
        "name": "通信·连接",
        "subtitle": "神经网络 — 光/铜/卫星互联",
        "color": "#28c0c8",
        "boards": [
            ("BK1128", "CPO概念", "concept"),
            ("BK1136", "光通信模块", "concept"),
            ("BK1168", "铜缆高速连接", "concept"),
            ("BK0921", "卫星互联网", "concept"),
            ("BK0877", "PCB", "concept"),
        ],
    },
    {
        "name": "机器人本体·VLA",
        "subtitle": "Agent / 具身智能 — 本体与执行",
        "color": "#f2a13d",
        "boards": [
            ("BK1184", "人形机器人", "concept"),
            ("BK1408", "机器人", "industry"),
            ("BK1145", "机器人执行器", "concept"),
            ("BK1100", "减速器", "concept"),
            ("BK0969", "汽车芯片", "concept"),
        ],
    },
    {
        "name": "机器感知",
        "subtitle": "感知世界 — 激光雷达/传感",
        "color": "#a06bff",
        "boards": [
            ("BK1002", "激光雷达", "concept"),
        ],
    },
    {
        "name": "应用·大模型·云",
        "subtitle": "世界模型落地 — 大模型与云",
        "color": "#3ecf8e",
        "boards": [
            ("BK0579", "云计算", "concept"),
            ("BK1182", "智谱AI概念", "concept"),
        ],
    },
    {
        "name": "能源·电力·冷却",
        "subtitle": "算力的燃料 — 液冷/核能",
        "color": "#ff6b6b",
        "boards": [
            ("BK1138", "液冷概念", "concept"),
            ("BK1163", "可控核聚变", "concept"),
        ],
    },
    {
        "name": "无人机·低空AI",
        "subtitle": "最早商业闭环 — 无人机/低空",
        "color": "#e0c34a",
        "boards": [
            ("BK0704", "无人机", "concept"),
        ],
    },
]


# ---------------- 读 ----------------
def get_map() -> Dict[str, Any]:
    """读全图结构(不含实时):rings -> boards -> pinned stocks。"""
    conn = get_conn()
    rings = [dict(r) for r in conn.execute(
        "SELECT * FROM star_orbit_ring ORDER BY sort_order, id"
    ).fetchall()]
    boards = [dict(b) for b in conn.execute(
        "SELECT * FROM star_orbit_board ORDER BY ring_id, sort_order, id"
    ).fetchall()]
    stocks = [dict(s) for s in conn.execute(
        "SELECT * FROM star_orbit_stock ORDER BY board_id, sort_order, id"
    ).fetchall()]

    by_board: Dict[int, List[Dict[str, Any]]] = {}
    for s in stocks:
        by_board.setdefault(s["board_id"], []).append(s)
    by_ring: Dict[int, List[Dict[str, Any]]] = {}
    for b in boards:
        b["stocks"] = by_board.get(b["id"], [])
        by_ring.setdefault(b["ring_id"], []).append(b)
    for r in rings:
        r["boards"] = by_ring.get(r["id"], [])
    return {"rings": rings}


def get_board(board_id: int) -> Optional[Dict[str, Any]]:
    row = get_conn().execute(
        "SELECT * FROM star_orbit_board WHERE id=?", (int(board_id),)
    ).fetchone()
    return dict(row) if row else None


# ---------------- 写:环 ----------------
def add_ring(name: str, subtitle: str = "", color: str = "", sort_order: Optional[int] = None) -> int:
    conn = get_conn()
    if sort_order is None:
        row = conn.execute("SELECT COALESCE(MAX(sort_order), -1)+1 FROM star_orbit_ring").fetchone()
        sort_order = int(row[0])
    cur = conn.execute(
        "INSERT INTO star_orbit_ring(name, subtitle, color, sort_order, created_at) VALUES(?,?,?,?,?)",
        (str(name).strip(), str(subtitle or "").strip(), str(color or "").strip(), int(sort_order), _now()),
    )
    return int(cur.lastrowid)


def update_ring(ring_id: int, **fields: Any) -> None:
    allowed = {"name", "subtitle", "color", "sort_order"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not sets:
        return
    cols = ", ".join(f"{k}=?" for k in sets)
    get_conn().execute(
        f"UPDATE star_orbit_ring SET {cols} WHERE id=?", (*sets.values(), int(ring_id))
    )


def delete_ring(ring_id: int) -> None:
    get_conn().execute("DELETE FROM star_orbit_ring WHERE id=?", (int(ring_id),))


# ---------------- 写:板块 ----------------
def add_board(ring_id: int, board_code: str, board_name: str,
              board_type: str = "concept", note: str = "",
              sort_order: Optional[int] = None) -> int:
    conn = get_conn()
    code = str(board_code or "").strip().upper()
    if not code:
        raise ValueError("board_code 不能为空")
    if sort_order is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1)+1 FROM star_orbit_board WHERE ring_id=?", (int(ring_id),)
        ).fetchone()
        sort_order = int(row[0])
    cur = conn.execute(
        """INSERT INTO star_orbit_board(ring_id, board_code, board_name, board_type, note, sort_order, created_at)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(ring_id, board_code) DO UPDATE SET
             board_name=excluded.board_name, board_type=excluded.board_type, note=excluded.note""",
        (int(ring_id), code, str(board_name or code).strip(), str(board_type or "concept").strip(),
         str(note or "").strip(), int(sort_order), _now()),
    )
    if cur.lastrowid:
        return int(cur.lastrowid)
    row = conn.execute(
        "SELECT id FROM star_orbit_board WHERE ring_id=? AND board_code=?", (int(ring_id), code)
    ).fetchone()
    return int(row[0])


def delete_board(board_id: int) -> None:
    get_conn().execute("DELETE FROM star_orbit_board WHERE id=?", (int(board_id),))


def move_board(board_id: int, ring_id: int) -> None:
    """把板块挪到另一条轨道环。"""
    get_conn().execute(
        "UPDATE star_orbit_board SET ring_id=? WHERE id=?", (int(ring_id), int(board_id))
    )


# ---------------- 写:钉选股 ----------------
def add_stock(board_id: int, stock_code: str, stock_name: str = "",
              note: str = "", sort_order: Optional[int] = None) -> int:
    conn = get_conn()
    code = str(stock_code or "").strip()
    if not code:
        raise ValueError("stock_code 不能为空")
    if sort_order is None:
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1)+1 FROM star_orbit_stock WHERE board_id=?", (int(board_id),)
        ).fetchone()
        sort_order = int(row[0])
    cur = conn.execute(
        """INSERT INTO star_orbit_stock(board_id, stock_code, stock_name, note, sort_order, created_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(board_id, stock_code) DO UPDATE SET
             stock_name=excluded.stock_name, note=excluded.note""",
        (int(board_id), code, str(stock_name or "").strip(), str(note or "").strip(),
         int(sort_order), _now()),
    )
    if cur.lastrowid:
        return int(cur.lastrowid)
    row = conn.execute(
        "SELECT id FROM star_orbit_stock WHERE board_id=? AND stock_code=?", (int(board_id), code)
    ).fetchone()
    return int(row[0])


def delete_stock(stock_id: int) -> None:
    get_conn().execute("DELETE FROM star_orbit_stock WHERE id=?", (int(stock_id),))


# ---------------- 板块成分股「关联关系」缓存 ----------------
# 点击板块实时拉取的成分股会被东财限流;membership 本身低频不变,故按板块快照入库,
# 限流/降级时回退本表(见 webui/services/star_orbit_service.board_constituents)。
def save_board_members(board_code: str, members: List[Dict[str, Any]],
                       source: str = "eastmoney") -> int:
    """整板快照式保存板块成分(先清后插同一时间戳),返回写入条数。

    ``members`` 为 ``[{"code","name"}, ...]`` 顺序即排序;空列表不动旧缓存(避免一次
    限流把已有关联关系清空)。
    """
    code = str(board_code or "").strip().upper()
    rows = [m for m in (members or []) if str(m.get("code") or "").strip()]
    if not code or not rows:
        return 0
    conn = get_conn()
    ts = _now()
    src = str(source or "").strip() or "eastmoney"
    conn.execute("DELETE FROM star_orbit_board_member WHERE board_code=?", (code,))
    conn.executemany(
        """INSERT INTO star_orbit_board_member
             (board_code, stock_code, stock_name, sort_order, source, updated_at)
           VALUES(?,?,?,?,?,?)""",
        [(code, str(m["code"]).strip(), str(m.get("name") or "").strip(), i, src, ts)
         for i, m in enumerate(rows)],
    )
    return len(rows)


def get_board_members(board_code: str, limit: int = 500) -> Dict[str, Any]:
    """读板块成分缓存:``{"members":[{code,name}], "source", "updated_at", "count"}``。

    无缓存时 members 空、updated_at 为 None。
    """
    code = str(board_code or "").strip().upper()
    if not code:
        return {"members": [], "source": "", "updated_at": None, "count": 0}
    rows = [dict(r) for r in get_conn().execute(
        """SELECT stock_code, stock_name, source, updated_at
             FROM star_orbit_board_member WHERE board_code=?
            ORDER BY sort_order, id LIMIT ?""",
        (code, max(1, int(limit))),
    ).fetchall()]
    members = [{"code": r["stock_code"], "name": r["stock_name"] or ""} for r in rows]
    return {
        "members": members,
        "source": rows[0]["source"] if rows else "",
        "updated_at": rows[0]["updated_at"] if rows else None,
        "count": len(members),
    }


# ---------------- 种子 ----------------
def is_empty() -> bool:
    row = get_conn().execute("SELECT COUNT(*) FROM star_orbit_ring").fetchone()
    return int(row[0]) == 0


def seed_if_empty() -> bool:
    """首次为空时灌入种子映射(rings + boards)。返回是否实际灌入。"""
    if not is_empty():
        return False
    for ri, ring in enumerate(SEED_RINGS):
        rid = add_ring(ring["name"], ring.get("subtitle", ""), ring.get("color", ""), sort_order=ri)
        for bi, (code, name, btype) in enumerate(ring["boards"]):
            add_board(rid, code, name, btype, sort_order=bi)
    return True


def reset_to_seed() -> None:
    """清空并重灌种子(用于「恢复默认」)。"""
    conn = get_conn()
    conn.execute("DELETE FROM star_orbit_ring")  # 级联删 board/stock
    seed_if_empty()
