from webui.services.kline_service import StockKlineService


class StubKlineService(StockKlineService):
    def __init__(self, records=None, error=None):
        super().__init__("unused")
        self.records = records if records is not None else []
        self.error = error

    def load_local_kline(self, stock_code, period, limit):
        return [], None

    def fetch_sina_kline(self, stock_code, period, limit):
        if self.error:
            raise self.error
        return self.records, ""


def test_sina_symbol_and_scale_mapping():
    assert StockKlineService.sina_symbol_for_code("600000") == "sh600000"
    assert StockKlineService.sina_symbol_for_code("000001") == "sz000001"
    assert StockKlineService.sina_symbol_for_code("830000") == "bj830000"
    assert StockKlineService.period_to_sina_scale("1h") == "60"
    assert StockKlineService.period_to_sina_scale("daily") == "240"


def test_parse_sina_klines_calculates_pct_change():
    records = StockKlineService.parse_sina_klines(
        [
            {"day": "2026-05-19", "open": "10", "close": "10", "high": "11", "low": "9"},
            {"day": "2026-05-20", "open": "10", "close": "11", "high": "11", "low": "10"},
        ]
    )

    assert records[0]["pct_chg"] == 0.0
    assert records[1]["pct_chg"] == 10.0


def test_get_payload_validates_code_without_network():
    service = StubKlineService()

    payload, error = service.get_payload("bad")

    assert payload is None
    assert error == "Invalid stock code"


def test_get_payload_handles_sina_success_and_failure():
    service = StubKlineService(records=[{"date": "2026-05-20", "open": 1, "close": 1}])
    fail_service = StubKlineService(error=RuntimeError("offline"))

    payload, error = service.get_payload("600000", limit="999")
    failed, failed_error = fail_service.get_payload("600000")

    assert error is None
    assert payload["source"] == "sina"
    assert payload["available"] is True
    assert failed_error is None
    assert failed["available"] is False
    assert failed["detail"] == "offline"
