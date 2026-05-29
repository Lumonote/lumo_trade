"""量化席位注册表（JSON 热加载）。"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Tuple


class QuantSeatRegistry:
    """从 config/quant_seats.json 加载 high/medium 置信度席位清单。

    构造或调用 reload() 时读 JSON；classify(name) 返回 (is_quant, confidence)。
    """

    def __init__(self, config_path: Path):
        self._path = Path(config_path)
        self._lock = Lock()
        self._high: set[str] = set()
        self._medium: set[str] = set()
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._high, self._medium = set(), set()
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._high = set(data.get("high_confidence", []))
            self._medium = set(data.get("medium_confidence", []))

    def classify(self, inst_name: str) -> Tuple[bool, str | None]:
        if inst_name in self._high:
            return True, "high"
        if inst_name in self._medium:
            return True, "medium"
        return False, None
