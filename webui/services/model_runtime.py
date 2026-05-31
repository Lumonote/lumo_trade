"""Framework-neutral Kronos model loading and prediction helpers."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class ModelRuntimeContext:
    model_available: Callable[[], bool]
    get_predictor: Callable[[], Any]
    set_loaded_model: Callable[[Any, Any, Any], None]
    available_models: dict[str, dict[str, Any]]
    user_root: Path
    kronos_cls: Any
    tokenizer_cls: Any
    predictor_cls: Any
    pandas: Any
    load_data_file: Callable[[str], tuple[Any, str | None]]
    create_prediction_chart: Callable[..., str]
    save_prediction_results: Callable[..., str | None]


def _model_cache_name(model_id: str) -> str:
    return str(model_id or "").rsplit("/", 1)[-1]


def _resolve_device(requested_device: Any) -> str:
    device = str(requested_device or "cpu").strip().lower()
    if device != "auto":
        return device

    try:
        import torch

        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda:0"
    except Exception:
        pass
    return "cpu"


def loaded_model_info(predictor: Any) -> dict[str, str]:
    model = getattr(predictor, "model", None)
    name = model.__class__.__name__ if model is not None else predictor.__class__.__name__
    device = str(getattr(predictor, "device", "") or "")
    if not device and model is not None:
        try:
            parameters = model.parameters()
            device = str(next(parameters).device)
        except Exception:
            device = "unknown"
    return {"name": name, "device": device or "unknown"}


def _load_modelscope_artifact(
    *,
    model_id: str,
    cache_dir: Path,
    expected_dir: Path,
    loader_cls: Any,
    label: str,
) -> Any:
    from modelscope import snapshot_download

    if expected_dir.exists() and (expected_dir / "config.json").exists():
        print(f"Found local {label}, loading...")
        return loader_cls.from_pretrained(str(expected_dir))

    print(f"Downloading {label}...")
    downloaded_path = Path(snapshot_download(model_id, cache_dir=str(cache_dir)))
    if downloaded_path.resolve() != expected_dir.resolve():
        if not expected_dir.exists():
            shutil.move(str(downloaded_path), str(expected_dir))
            return loader_cls.from_pretrained(str(expected_dir))
        return loader_cls.from_pretrained(str(downloaded_path))
    return loader_cls.from_pretrained(str(downloaded_path))


def run_prediction_payload(data: dict[str, Any], context: ModelRuntimeContext) -> tuple[dict[str, Any], int]:
    try:
        pd = context.pandas
        predictor = context.get_predictor()
        file_path = data.get("file_path")
        lookback = int(data.get("lookback", 400))
        pred_len = int(data.get("pred_len", 120))
        temperature = float(data.get("temperature", 0.6))
        top_p = float(data.get("top_p", 0.9))
        sample_count = int(data.get("sample_count", 10))

        if not file_path:
            return {"error": "File path cannot be empty"}, 400

        df, error = context.load_data_file(file_path)
        if error:
            return {"error": error}, 400
        if len(df) < lookback:
            return {"error": f"Insufficient data length, need at least {lookback} rows"}, 400
        if not context.model_available() or predictor is None:
            return {"error": "Kronos model not loaded, please load model first"}, 400

        required_cols = ["open", "high", "low", "close"]
        if "volume" in df.columns:
            required_cols.append("volume")

        start_date = data.get("start_date")
        if start_date:
            start_dt = pd.to_datetime(start_date)
            time_range_df = df[df["timestamps"] >= start_dt]
            if len(time_range_df) < lookback + pred_len:
                return {
                    "error": (
                        f"Insufficient data from start time {start_dt.strftime('%Y-%m-%d %H:%M')}, "
                        f"need at least {lookback + pred_len} data points, currently only "
                        f"{len(time_range_df)} available"
                    )
                }, 400

            x_df = time_range_df.iloc[:lookback][required_cols]
            x_timestamp = time_range_df.iloc[:lookback]["timestamps"]
            y_timestamp = time_range_df.iloc[lookback:lookback + pred_len]["timestamps"]
            start_timestamp = time_range_df["timestamps"].iloc[0]
            end_timestamp = time_range_df["timestamps"].iloc[lookback + pred_len - 1]
            time_span = end_timestamp - start_timestamp
            prediction_type = (
                "Kronos model prediction (within selected window: first "
                f"{lookback} data points for prediction, last {pred_len} data points "
                f"for comparison, time span: {time_span})"
            )
        else:
            x_df = df.iloc[:lookback][required_cols]
            x_timestamp = df.iloc[:lookback]["timestamps"]
            y_timestamp = df.iloc[lookback:lookback + pred_len]["timestamps"]
            prediction_type = "Kronos model prediction (latest data)"

        if isinstance(x_timestamp, pd.DatetimeIndex):
            x_timestamp = pd.Series(x_timestamp, name="timestamps")
        if isinstance(y_timestamp, pd.DatetimeIndex):
            y_timestamp = pd.Series(y_timestamp, name="timestamps")

        try:
            pred_df = predictor.predict(
                df=x_df,
                x_timestamp=x_timestamp,
                y_timestamp=y_timestamp,
                pred_len=pred_len,
                T=temperature,
                top_p=top_p,
                sample_count=sample_count,
            )
        except Exception as exc:
            return {"error": f"Kronos model prediction failed: {exc}"}, 500

        actual_data = []
        actual_df = None
        if start_date:
            start_dt = pd.to_datetime(start_date)
            time_range_df = df[df["timestamps"] >= start_dt]
            if len(time_range_df) >= lookback + pred_len:
                actual_df = time_range_df.iloc[lookback:lookback + pred_len]
        elif len(df) >= lookback + pred_len:
            actual_df = df.iloc[lookback:lookback + pred_len]

        if actual_df is not None:
            for _index, row in actual_df.iterrows():
                actual_data.append(
                    {
                        "timestamp": row["timestamps"].isoformat(),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row["volume"]) if "volume" in row else 0,
                        "amount": float(row["amount"]) if "amount" in row else 0,
                    }
                )

        if start_date:
            start_dt = pd.to_datetime(start_date)
            mask = df["timestamps"] >= start_dt
            historical_start_idx = df[mask].index[0] if len(df[mask]) > 0 else 0
        else:
            historical_start_idx = 0

        chart_json = context.create_prediction_chart(
            df,
            pred_df,
            lookback,
            pred_len,
            actual_df,
            historical_start_idx,
        )

        if "timestamps" in df.columns:
            if start_date:
                start_dt = pd.to_datetime(start_date)
                time_range_df = df[df["timestamps"] >= start_dt]
                if len(time_range_df) >= lookback:
                    last_timestamp = time_range_df["timestamps"].iloc[lookback - 1]
                    time_diff = df["timestamps"].iloc[1] - df["timestamps"].iloc[0]
                    future_timestamps = pd.date_range(
                        start=last_timestamp + time_diff,
                        periods=pred_len,
                        freq=time_diff,
                    )
                else:
                    future_timestamps = []
            else:
                last_timestamp = df["timestamps"].iloc[-1]
                time_diff = df["timestamps"].iloc[1] - df["timestamps"].iloc[0]
                future_timestamps = pd.date_range(
                    start=last_timestamp + time_diff,
                    periods=pred_len,
                    freq=time_diff,
                )
        else:
            future_timestamps = range(len(df), len(df) + pred_len)

        prediction_results = []
        for index, (_row_index, row) in enumerate(pred_df.iterrows()):
            prediction_results.append(
                {
                    "timestamp": future_timestamps[index].isoformat()
                    if index < len(future_timestamps)
                    else f"T{index}",
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]) if "volume" in row else 0,
                    "amount": float(row["amount"]) if "amount" in row else 0,
                }
            )

        try:
            context.save_prediction_results(
                file_path=file_path,
                prediction_type=prediction_type,
                prediction_results=prediction_results,
                actual_data=actual_data,
                input_data=x_df,
                prediction_params={
                    "lookback": lookback,
                    "pred_len": pred_len,
                    "temperature": temperature,
                    "top_p": top_p,
                    "sample_count": sample_count,
                    "start_date": start_date if start_date else "latest",
                },
            )
        except Exception as exc:
            print(f"Failed to save prediction results: {exc}")

        return {
            "success": True,
            "prediction_type": prediction_type,
            "chart": chart_json,
            "prediction_results": prediction_results,
            "actual_data": actual_data,
            "has_comparison": len(actual_data) > 0,
            "message": f"Prediction completed, generated {pred_len} prediction points"
            + (f", including {len(actual_data)} actual data points for comparison" if actual_data else ""),
        }, 200
    except Exception as exc:
        return {"error": f"Prediction failed: {exc}"}, 500


def load_model_payload(data: dict[str, Any], context: ModelRuntimeContext) -> tuple[dict[str, Any], int]:
    try:
        if not context.model_available():
            return {"error": "Kronos model library not available"}, 400

        model_key = data.get("model_key", "kronos-small")
        device = _resolve_device(data.get("device", "cpu"))
        if model_key not in context.available_models:
            return {"error": f"Unsupported model: {model_key}"}, 400

        model_config = context.available_models[model_key]
        model_dir = context.user_root / "models"
        model_dir.mkdir(exist_ok=True)
        model_model_id = model_config.get("model_id") or f"northwind9898/{model_config['name']}"
        tokenizer_model_id = model_config.get("tokenizer_id") or "northwind9898/Kronos-Tokenizer-base"
        tokenizer_dir = model_dir / _model_cache_name(tokenizer_model_id)
        model_dir_path = model_dir / _model_cache_name(model_model_id)

        tokenizer = _load_modelscope_artifact(
            model_id=tokenizer_model_id,
            cache_dir=model_dir,
            expected_dir=tokenizer_dir,
            loader_cls=context.tokenizer_cls,
            label="tokenizer",
        )
        model = _load_modelscope_artifact(
            model_id=model_model_id,
            cache_dir=model_dir,
            expected_dir=model_dir_path,
            loader_cls=context.kronos_cls,
            label="model",
        )

        predictor = context.predictor_cls(
            model,
            tokenizer,
            device=device,
            max_context=model_config["context_length"],
        )
        context.set_loaded_model(tokenizer, model, predictor)

        return {
            "success": True,
            "message": f"Model loaded successfully: {model_config['name']} ({model_config['params']}) on {device}",
            "model_info": {
                "name": model_config["name"],
                "params": model_config["params"],
                "context_length": model_config["context_length"],
                "description": model_config["description"],
            },
        }, 200
    except Exception as exc:
        return {"error": f"Model loading failed: {exc}"}, 500
