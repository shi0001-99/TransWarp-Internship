# -*- coding: utf-8 -*-
"""回测结果导出：将 result 落盘为三个交付文件。

输出目录: output/backtest/
  - equity_curve.csv   资金曲线（date/equity/equity_norm/ret + 双基准列）
  - metrics.json       全套绩效指标（numpy 值转原生类型后序列化）
  - trade_log.csv      交易记录（每笔买/卖）
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "backtest"


def _default_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def _json_safe(obj: Any) -> Any:
    """把 numpy 标量 / NaN / inf 转成可 JSON 序列化的原生类型。"""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 6)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def export_backtest_result(result: dict[str, Any],
                           output_dir: Optional[Path] = None) -> dict[str, Path]:
    """把回测 result 写出到 {output_dir}/backtest。

    Returns: {equity_curve: Path, metrics: Path, trade_log: Path}
    """
    out = output_dir or _default_output_dir()
    out.mkdir(parents=True, exist_ok=True)

    curve_df = result.get("curve")
    trades = result.get("trades", [])
    metrics = result.get("metrics", {})

    # 1. equity_curve.csv
    eq_path = out / "equity_curve.csv"
    if curve_df is not None and len(curve_df):
        curve_df.to_csv(eq_path, index=False, encoding="utf-8-sig")

    # 2. metrics.json
    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start_date": result.get("start_date"),
        "end_date": result.get("end_date"),
        "pool_size": result.get("pool_size"),
        "cfg": {
            "initial_capital": getattr(result.get("cfg"), "initial_capital", None),
            "rebalance": getattr(result.get("cfg"), "rebalance", None),
            "top_n": getattr(result.get("cfg"), "top_n", None),
            "max_single_fund": getattr(result.get("cfg"), "max_single_fund", None),
            "stop_loss_ma20": getattr(result.get("cfg"), "stop_loss_ma20", None),
        },
        "warnings": result.get("warnings", []),
    }
    metrics_safe = {"metrics": _json_safe(metrics), "meta": _json_safe(meta)}
    metrics_path = out / "metrics.json"
    metrics_path.write_text(
        json.dumps(metrics_safe, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3. trade_log.csv
    trade_path = out / "trade_log.csv"
    if trades:
        import pandas as pd
        tdf = pd.DataFrame([t.__dict__ for t in trades])
        tdf.to_csv(trade_path, index=False, encoding="utf-8-sig")
    else:
        import pandas as pd
        pd.DataFrame(columns=["date", "code", "side", "price", "shares",
                              "amount", "fee", "pnl"]).to_csv(
            trade_path, index=False, encoding="utf-8-sig")

    return {"equity_curve": eq_path, "metrics": metrics_path, "trade_log": trade_path}