from webui.services.analysis_jobs import AnalysisJobRequestParser, normalize_stock_codes, safe_int


def test_normalize_stock_codes_deduplicates_common_formats():
    assert normalize_stock_codes("SH600000, 000001.SZ sz000001 invalid") == ["600000", "000001"]


def test_safe_int_bounds_values():
    assert safe_int("99", 10, minimum=1, maximum=20) == 20
    assert safe_int("bad", 10, minimum=1, maximum=20) == 10


def test_opportunity_params_validate_source_and_defaults():
    parser = AnalysisJobRequestParser()

    params, error = parser.opportunity_params({"source": "heat", "stock_codes": "600000"})
    invalid, invalid_error = parser.opportunity_params({"source": "bad"})

    assert error is None
    assert params == {
        "limit": 100,
        "workers": 10,
        "source": "heat",
        "stock_codes": ["600000"],
    }
    assert invalid is None
    assert "Unsupported source" in invalid_error


def test_opportunity_params_empty_payload_uses_cli_defaults():
    parser = AnalysisJobRequestParser()

    params, error = parser.opportunity_params({})

    assert error is None
    assert params == {
        "limit": 100,
        "workers": 10,
        "source": "multi",
        "stock_codes": [],
    }


def test_batch_params_validate_codes_and_filter_types():
    parser = AnalysisJobRequestParser()

    params, error = parser.batch_params(
        {
            "stock_codes": "600000 000001",
            "data_types": "sentiment unknown",
            "max_concurrent": "99",
            "skip_scoring": True,
        }
    )
    invalid, invalid_error = parser.batch_params({"stock_codes": "bad"})

    assert error is None
    assert params["stock_codes"] == ["600000", "000001"]
    assert params["data_types"] == ["sentiment"]
    assert params["max_concurrent"] == 20
    assert params["skip_scoring"] is True
    assert invalid is None
    assert "6-digit" in invalid_error
