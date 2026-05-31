from pathlib import Path
from types import SimpleNamespace

from webui.services import model_runtime
from webui.services.model_runtime import ModelRuntimeContext, load_model_payload, run_prediction_payload


def _context(**overrides):
    defaults = {
        "model_available": lambda: False,
        "get_predictor": lambda: None,
        "set_loaded_model": lambda tokenizer, model, predictor: None,
        "available_models": {
            "kronos-small": {
                "name": "Kronos-small",
                "params": "24.7M",
                "context_length": 512,
                "description": "Small model",
            }
        },
        "user_root": Path("/tmp/kronos-test"),
        "kronos_cls": None,
        "tokenizer_cls": None,
        "predictor_cls": None,
        "pandas": None,
        "load_data_file": lambda _path: (None, "not called"),
        "create_prediction_chart": lambda *_args, **_kwargs: "{}",
        "save_prediction_results": lambda *_args, **_kwargs: None,
    }
    defaults.update(overrides)
    return ModelRuntimeContext(**defaults)


def test_load_model_short_circuits_when_model_library_disabled():
    result, status = load_model_payload({}, _context(model_available=lambda: False))

    assert status == 400
    assert result == {"error": "Kronos model library not available"}


def test_prediction_validates_file_path_before_loading_data():
    calls = []

    result, status = run_prediction_payload(
        {},
        _context(load_data_file=lambda path: calls.append(path)),
    )

    assert status == 400
    assert result == {"error": "File path cannot be empty"}
    assert calls == []


def test_prediction_short_circuits_when_predictor_not_loaded():
    class FakeFrame:
        columns = ["timestamps", "open", "high", "low", "close"]

        def __len__(self):
            return 10

    result, status = run_prediction_payload(
        {"file_path": "sample.csv", "lookback": 5},
        _context(
            model_available=lambda: True,
            get_predictor=lambda: None,
            load_data_file=lambda _path: (FakeFrame(), None),
        ),
    )

    assert status == 400
    assert result == {"error": "Kronos model not loaded, please load model first"}


def test_load_model_rejects_unsupported_model_before_importing_modelscope():
    result, status = load_model_payload(
        {"model_key": "unknown"},
        _context(
            model_available=lambda: True,
            kronos_cls=SimpleNamespace(),
            tokenizer_cls=SimpleNamespace(),
            predictor_cls=SimpleNamespace(),
        ),
    )

    assert status == 400
    assert result == {"error": "Unsupported model: unknown"}


def test_resolve_device_auto_uses_supported_device_name():
    assert model_runtime._resolve_device("auto") in {"cpu", "mps", "cuda:0"}


def test_model_cache_name_uses_repository_leaf():
    assert model_runtime._model_cache_name("northwind9898/Kronos-Tokenizer-2k") == "Kronos-Tokenizer-2k"


def test_loaded_model_info_uses_predictor_device_without_model_parameters():
    predictor = SimpleNamespace(model=SimpleNamespace(), device="cpu")

    assert model_runtime.loaded_model_info(predictor) == {"name": "SimpleNamespace", "device": "cpu"}
