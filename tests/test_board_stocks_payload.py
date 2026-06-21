import webui.core as core


def test_board_stocks_payload_normal(monkeypatch):
    rows = [{'code': '300196', 'name': '长海股份', 'price': 12.3, 'change_pct': 5.1,
             'main_net_inflow': 1.2e7, 'main_net_inflow_text': '1200万', 'industry': '玻璃玻纤'}]
    monkeypatch.setattr(core.MARKET_INTELLIGENCE_SERVICE, 'fetch_eastmoney_clist',
                        lambda **kw: rows)
    out = core.board_stocks_payload('BK0739', '玻璃玻纤')
    assert out['degraded'] is False and out['count'] == 1
    s = out['stocks'][0]
    assert s['code'] == '300196' and s['change_pct'] == 5.1
    assert s['main_net_inflow_text'] == '1200万'
    assert out['board'] == {'code': 'BK0739', 'name': '玻璃玻纤'}


def test_board_stocks_payload_non_bk_degrades_without_fetch(monkeypatch):
    called = {'n': 0}

    def _spy(**kw):
        called['n'] += 1
        return [{'code': 'x'}]

    monkeypatch.setattr(core.MARKET_INTELLIGENCE_SERVICE, 'fetch_eastmoney_clist', _spy)
    out = core.board_stocks_payload('884123.DC', '某板块')   # 非 BK(Tushare 兜底码)
    assert out['degraded'] is True and out['stocks'] == []
    assert called['n'] == 0                                  # BK 守卫:根本不发请求
    assert '非东财' in out['note']


def test_board_stocks_payload_fetch_error_degrades(monkeypatch):
    def _boom(**kw):
        raise RuntimeError('clist blocked')

    monkeypatch.setattr(core.MARKET_INTELLIGENCE_SERVICE, 'fetch_eastmoney_clist', _boom)
    out = core.board_stocks_payload('BK0739', '玻璃玻纤')
    assert out['degraded'] is True and out['stocks'] == []
    assert out['note']                                       # 有兜底文案,不抛错


def test_board_stocks_payload_empty_code_degrades(monkeypatch):
    out = core.board_stocks_payload('', '')
    assert out['degraded'] is True and out['count'] == 0


# ── _overlay_board_realtime:读时多源实时叠加(ulist→腾讯→Tushare)修复快照空字段 ──

def _patch_quote_overlay(monkeypatch, mapping):
    from webui.services import star_orbit_service
    monkeypatch.setattr(star_orbit_service, '_quote_overlay', lambda codes: mapping)


def test_overlay_fills_empty_fields_and_clears_placeholder_text(monkeypatch):
    _patch_quote_overlay(monkeypatch, {
        '688300': {'price': 270.47, 'change_pct': 14.98, 'main_net_inflow': 1.77e8},
    })
    rows = [{'code': '688300', 'name': '联瑞新材', 'change_pct': None,
             'price': None, 'main_net_inflow': 0, 'main_net_inflow_text': '—'}]
    out = core._overlay_board_realtime(rows, 'BK1152')
    assert out[0]['price'] == 270.47 and out[0]['change_pct'] == 14.98
    assert out[0]['main_net_inflow'] == 1.77e8
    # 占位符文案被清空 → 前端按数值统一格式化(否则 truthy 的 '—' 会盖掉数值)
    assert out[0]['main_net_inflow_text'] == ''


def test_overlay_preserves_existing_nonzero_snapshot_values(monkeypatch):
    _patch_quote_overlay(monkeypatch, {
        '688300': {'price': 270.47, 'change_pct': 14.98, 'main_net_inflow': 1.77e8},
    })
    rows = [{'code': '688300', 'name': '联瑞新材', 'change_pct': 9.9,
             'price': 250.0, 'main_net_inflow': 1.0e8, 'main_net_inflow_text': '1.00亿'}]
    out = core._overlay_board_realtime(rows, 'BK1152')
    # 快照已记录的非空历史值不被实时覆盖
    assert out[0]['change_pct'] == 9.9 and out[0]['price'] == 250.0
    assert out[0]['main_net_inflow'] == 1.0e8 and out[0]['main_net_inflow_text'] == '1.00亿'


def test_overlay_degrades_to_unchanged_rows_when_quotes_empty(monkeypatch):
    _patch_quote_overlay(monkeypatch, {})
    rows = [{'code': '688300', 'name': '联瑞新材', 'change_pct': None,
             'price': None, 'main_net_inflow': None, 'main_net_inflow_text': '—'}]
    out = core._overlay_board_realtime(rows, 'BK1152')
    assert out[0]['change_pct'] is None and out[0]['price'] is None
    assert out[0]['main_net_inflow_text'] == '—'  # 无数据 → 原样保留占位符


def test_overlay_empty_input_returns_empty(monkeypatch):
    assert core._overlay_board_realtime([], 'BK1152') == []
