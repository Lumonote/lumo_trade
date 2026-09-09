# -*- coding: utf-8 -*-
"""「入选后表现标记」并排展示的前端文案守卫(2026-08-17)。

顶层那份是该股**上一次**入选的口径(不是当天,见
``StockAnalysisSuite._collect_outcome_markers``),文案必须跟着说"上次入选",
否则用户看到两个同类块会以为在比同一天。

这个 bundle 是压缩产物、没有未压缩源,历史上出过「重新生成 bundle 把手工追加的块
清掉」的事故,故用断言把文案钉住。
"""
from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "webui" / "static" / "lumo_desktop_app.js"


def test_diff_label_says_previous_selection_not_selection_day():
    source = APP_JS.read_text(encoding="utf-8")
    assert "较上次入选新增：" in source
    assert "较入选当天新增：" not in source  # 旧文案(两侧同日)不该再出现


def test_stored_block_label_distinguishes_previous_from_today_only():
    """有 ``current`` 对照时标"上次入选";当天入选且无更早记录时只标日期。"""
    source = APP_JS.read_text(encoding="utf-8")
    assert 'e.current?"上次入选 "+t(e.as_of||"")+" 口径"' in source
    assert '入选口径' in source
