import webui.core as core


def _patch_star_fallback(monkeypatch, payload, calls=None):
    """替换星轨成分股兜底链(东财双路由→Tushare dc_member→本地缓存),隔离网络/DB。"""
    from webui.services import star_orbit_service

    def _fb(code, name='', limit=30):
        if calls is not None:
            calls.append({'code': code, 'name': name, 'limit': limit})
        return payload

    monkeypatch.setattr(star_orbit_service, 'board_constituents', _fb)


def _star_payload(stocks, note='', source='', quoted=False):
    return {
        'board': {'code': 'BK0739', 'name': '玻璃玻纤'},
        'stocks': stocks, 'count': len(stocks), 'degraded': not stocks,
        'stale': not quoted, 'source': source, 'quoted': quoted, 'note': note,
    }


def test_board_stocks_payload_normal(monkeypatch):
    rows = [{'code': '300196', 'name': '长海股份', 'price': 12.3, 'change_pct': 5.1,
             'main_net_inflow': 1.2e7, 'main_net_inflow_text': '1200万', 'industry': '玻璃玻纤'}]
    monkeypatch.setattr(core.MARKET_INTELLIGENCE_SERVICE, 'fetch_eastmoney_clist',
                        lambda **kw: rows)
    calls = []
    _patch_star_fallback(monkeypatch, _star_payload([]), calls)
    out = core.board_stocks_payload('BK0739', '玻璃玻纤')
    assert out['degraded'] is False and out['count'] == 1
    s = out['stocks'][0]
    assert s['code'] == '300196' and s['change_pct'] == 5.1
    assert s['main_net_inflow_text'] == '1200万'
    assert out['board'] == {'code': 'BK0739', 'name': '玻璃玻纤'}
    assert calls == []                                       # 主路成功:不触发兜底


def test_board_stocks_payload_non_bk_degrades_without_fetch(monkeypatch):
    called = {'n': 0}

    def _spy(**kw):
        called['n'] += 1
        return [{'code': 'x'}]

    monkeypatch.setattr(core.MARKET_INTELLIGENCE_SERVICE, 'fetch_eastmoney_clist', _spy)
    calls = []
    _patch_star_fallback(monkeypatch, _star_payload([{'code': 'x', 'name': 'x'}]), calls)
    out = core.board_stocks_payload('884123.DC', '某板块')   # 非 BK(Tushare 兜底码)
    assert out['degraded'] is True and out['stocks'] == []
    assert called['n'] == 0                                  # BK 守卫:根本不发请求
    assert calls == []                                       # 兜底链同样被 BK 守卫拦住
    assert '非东财' in out['note']


def test_board_stocks_payload_fetch_error_falls_back_to_star_chain(monkeypatch):
    """东财主路挂(网络/限流)→ 星轨兜底(Tushare/缓存)命中 → 正常出成分股列表。"""
    def _boom(**kw):
        raise RuntimeError('clist blocked')

    monkeypatch.setattr(core.MARKET_INTELLIGENCE_SERVICE, 'fetch_eastmoney_clist', _boom)
    calls = []
    fb_stocks = [{'code': '301526', 'name': '国际复材', 'price': 9.9, 'change_pct': 3.2,
                  'main_net_inflow': 5.6e7, 'main_net_inflow_text': '5600万',
                  'abnormal': False, 'signal': '关注', 'signal_reason': 'x'}]
    _patch_star_fallback(
        monkeypatch,
        _star_payload(fb_stocks, note='东财成分股接口限流,已用 Tushare 关联成分 + 实时报价叠加。',
                      source='tushare', quoted=True),
        calls)
    out = core.board_stocks_payload('BK0739', '玻璃玻纤', limit=60)
    assert out['degraded'] is False and out['count'] == 1
    s = out['stocks'][0]
    assert s['code'] == '301526' and s['change_pct'] == 3.2
    assert s['main_net_inflow_text'] == '5600万'
    assert 'signal' not in s and 'abnormal' not in s         # 与主路同形的精简行
    assert 'Tushare' in out['note']                          # 来源说明透传
    assert out['source'] == 'tushare' and out['quoted'] is True and out['stale'] is False
    assert calls == [{'code': 'BK0739', 'name': '玻璃玻纤', 'limit': 60}]


def test_board_stocks_payload_empty_rows_also_fall_back(monkeypatch):
    """东财主路返回空列表(未抛错)同样走兜底。"""
    monkeypatch.setattr(core.MARKET_INTELLIGENCE_SERVICE, 'fetch_eastmoney_clist',
                        lambda **kw: [])
    calls = []
    _patch_star_fallback(
        monkeypatch,
        _star_payload([{'code': '600176', 'name': '中国巨石'}],
                      note='东财实时暂不可用(网络/限流),已用 Tushare 成分股(收盘数据,无实时价)兜底。',
                      source='tushare', quoted=False),
        calls)
    out = core.board_stocks_payload('BK0739', '玻璃玻纤')
    assert out['degraded'] is False and out['count'] == 1
    assert out['stocks'][0]['code'] == '600176'
    assert out['stocks'][0]['main_net_inflow_text'] == ''    # 无实时价 → 文案留空由前端占位
    assert out['stale'] is True and len(calls) == 1


def test_board_stocks_payload_fetch_error_degrades_when_fallback_empty(monkeypatch):
    def _boom(**kw):
        raise RuntimeError('clist blocked')

    monkeypatch.setattr(core.MARKET_INTELLIGENCE_SERVICE, 'fetch_eastmoney_clist', _boom)
    _patch_star_fallback(monkeypatch, _star_payload(
        [], note='东财成分股暂不可用(网络/限流)且无缓存,请稍后重试。'))
    out = core.board_stocks_payload('BK0739', '玻璃玻纤')
    assert out['degraded'] is True and out['stocks'] == []
    assert out['note']                                       # 有兜底文案,不抛错
    assert 'source' not in out                               # 空兜底不透传附加字段


def test_board_stocks_payload_fallback_exception_degrades(monkeypatch):
    """兜底链本身抛错也不冒泡,仍按降级返回。"""
    monkeypatch.setattr(core.MARKET_INTELLIGENCE_SERVICE, 'fetch_eastmoney_clist',
                        lambda **kw: [])
    from webui.services import star_orbit_service

    def _fb_boom(code, name='', limit=30):
        raise RuntimeError('star chain down')

    monkeypatch.setattr(star_orbit_service, 'board_constituents', _fb_boom)
    out = core.board_stocks_payload('BK0739', '玻璃玻纤')
    assert out['degraded'] is True and out['stocks'] == []
    assert out['note']


def test_board_stocks_payload_empty_code_degrades(monkeypatch):
    _patch_star_fallback(monkeypatch, _star_payload([{'code': 'x', 'name': 'x'}]))
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
