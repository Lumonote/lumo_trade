import os
import sys
from pathlib import Path
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from analysis.technical_analysis import QuantitativeModels  # noqa: E402


def pick_data_file() -> Path:
    """Pick a usable CSV in `data/` that looks like 5-minute K-line."""
    data_dir = Path(os.environ.get("KRONOS_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
    if not data_dir.exists():
        raise FileNotFoundError(f"数据目录不存在: {data_dir}")

    candidates = list(data_dir.glob("*.csv"))
    if not candidates:
        raise FileNotFoundError("未找到CSV数据文件，请将5分钟K线CSV放入data目录")

    # Prefer files containing `_5min_`
    min5 = [p for p in candidates if "_5min_" in p.name]
    return (min5[0] if min5 else candidates[0]).resolve()


def load_df(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    # Normalize timestamp column name
    if 'timestamps' not in df.columns and 'timestamp' in df.columns:
        df = df.rename(columns={'timestamp': 'timestamps'})
    required = ['timestamps', 'open', 'high', 'low', 'close', 'volume', 'amount']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"数据文件缺少必要列: {missing}; 文件: {csv_path}")
    df['timestamps'] = pd.to_datetime(df['timestamps'])
    df = df.sort_values('timestamps').reset_index(drop=True)
    return df


def validate_models(df: pd.DataFrame, optimized: bool = False) -> int:
    qm = QuantitativeModels(df.copy())
    if optimized:
        qm.use_optimized_calculation = True
        qm.run_all_models_optimized()
    else:
        qm.run_all_models()

    errors = []

    # Expected keys used by报告生成
    expected_perf_keys = {'胜率', '适用人群', '中文名称', '核心策略'}

    # Validate signals
    for model_key, signals in qm.signals.items():
        # 1) Length check
        if len(signals) != len(qm.df):
            errors.append(f"[长度不一致] {model_key}: signals={len(signals)} df={len(qm.df)}")
            continue

        # 2) Value domain check
        bad_vals = [s for s in signals if s not in (-1, 0, 1)]
        if bad_vals:
            errors.append(f"[非法取值] {model_key}: 包含非{-1,0,1}值样本数={len(bad_vals)}")

        # 3) NaN check
        if any(pd.isna(s) for s in signals):
            errors.append(f"[出现NaN] {model_key}: 信号列表中存在NaN")

        # 4) 型别一致性
        if not all(isinstance(s, (int,)) for s in signals):
            errors.append(f"[类型不一致] {model_key}: 信号应为int(-1/0/1)")

    # Validate performance dict keys
    for model_key, perf in qm.models_performance.items():
        missing_keys = expected_perf_keys - set(perf.keys())
        if missing_keys:
            errors.append(f"[性能字段缺失] {model_key}: 缺少{sorted(missing_keys)}")

    # Summary
    if errors:
        print("❌ 校验发现问题:")
        for e in errors:
            print(" - ", e)
        print(f"\n共发现 {len(errors)} 项问题，建议修复后重跑校验。")
        return 1
    else:
        tag = "优化版" if optimized else "常规模型"
        print(f"✅ {tag}全部30个模型校验通过：长度一致，取值合法，无NaN，性能字段完整。")
        return 0


def main():
    try:
        csv_path = pick_data_file()
        print(f"📁 使用数据文件: {csv_path}")
        df = load_df(csv_path)
        print(f"📊 数据记录数: {len(df)} 条，时间范围: {df['timestamps'].min()} ~ {df['timestamps'].max()}")
        # 先跑常规模型
        rc1 = validate_models(df, optimized=False)
        # 再跑优化版模型
        rc2 = validate_models(df, optimized=True)
        rc = 1 if (rc1 != 0 or rc2 != 0) else 0
        sys.exit(rc)
    except Exception as e:
        print(f"❌ 校验执行失败: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()