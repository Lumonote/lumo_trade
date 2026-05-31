"""persona 注册表：从 personas/*.yaml 加载 + 校验。"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Dict, List

import yaml

SCHOOLS: Dict[str, str] = {
    "A": "价值派", "B": "成长派", "C": "宏观派", "D": "技术派",
    "E": "中国价投", "F": "游资派", "G": "量化派",
}

_REQUIRED = ("id", "name", "school", "tier", "rule", "voice")
_PERSONAS_DIR = Path(__file__).resolve().parent / "personas"


@functools.lru_cache(maxsize=1)
def load_personas() -> List[Dict[str, Any]]:
    """加载并校验全部 persona。结果进程内缓存（YAML 静态）。"""
    personas: List[Dict[str, Any]] = []
    for path in sorted(_PERSONAS_DIR.glob("*.yaml")):
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        for entry in entries:
            missing = [k for k in _REQUIRED if k not in entry]
            if missing:
                raise ValueError(f"{path.name}: persona 缺字段 {missing}: {entry!r}")
            if entry["school"] not in SCHOOLS:
                raise ValueError(f"{path.name}: 未知流派 {entry['school']!r}")
            if entry["tier"] not in ("flagship", "stub"):
                raise ValueError(f"{path.name}: 未知 tier {entry['tier']!r}")
            personas.append(entry)
    return personas
