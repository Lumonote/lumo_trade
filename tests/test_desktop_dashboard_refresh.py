from pathlib import Path
import re


APP_JS = Path(__file__).resolve().parents[1] / "webui" / "static" / "kronos_desktop_app.js"


def test_dashboard_refresh_requests_fresh_market_data():
    source = APP_JS.read_text(encoding="utf-8")

    assert re.search(r"async\s+function\s+loadDashboard\s*\(\s*forceRefresh\s*=\s*false\s*\)", source)
    assert re.search(
        r'fetchJson\s*\(\s*"/api/stock-dashboard"\s*\+\s*\(\s*forceRefresh\s*\?\s*"\?refresh=1"\s*:\s*""\s*\)\s*\)',
        source,
    )
    assert re.search(r"renderDashboardPage\s*\(\s*await\s+loadDashboard\s*\(\s*true\s*\)\s*\)", source)
