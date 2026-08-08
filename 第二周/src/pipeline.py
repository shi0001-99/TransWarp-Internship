"""
TransAlpha 量化投资流水线 - 纯 CLI 版本
7 阶段自动化选股工作流，无任何图形界面依赖。

工作流:
  1. 选股筛选 → output/screening/
  2. 人工抽查
  3. 趋势分析 → output/trend/
  4. 人工确认
  5. 凯利仓位 → output/kelly/
  6. 持仓审查
  7. 实时监控 → output/monitor/

用法:
  python -m src.pipeline run              # 运行完整流水线
  python -m src.pipeline run --stage 1    # 从第1阶段开始
  python -m src.pipeline status           # 查看当前状态
  python -m src.pipeline reset            # 重置流水线
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
SCREENING_DIR = OUTPUT_DIR / "screening"
TREND_DIR = OUTPUT_DIR / "trend"
KELLY_DIR = OUTPUT_DIR / "kelly"
MONITOR_DIR = OUTPUT_DIR / "monitor"
STATE_FILE = OUTPUT_DIR / "pipeline_state.json"

for d in (SCREENING_DIR, TREND_DIR, KELLY_DIR, MONITOR_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return {}


def _write_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def log(msg: str) -> None:
    print(f"[{_now_iso()}] {msg}", flush=True)


# ─── 共享数据中心 ────────────────────────────────────────────────────────────
class SharedDataCache:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default)

    def clear(self) -> None:
        self._cache.clear()


_shared = SharedDataCache()


def set_cache(key: str, value: Any) -> None:
    _shared.set(key, value)


def get_cache(key: str, default: Any = None) -> Any:
    return _shared.get(key, default)


# ─── 各阶段实现 ───────────────────────────────────────────────────────────────
def run_screening_stage(mode: str = "hot", top_n: int = 10) -> dict[str, Any]:
    """阶段 1: 选股筛选"""
    log("开始阶段 1: 选股筛选")
    try:
        from src.screener.screener import StockScreener

        screener = StockScreener()
        results = screener.run_screening(top_n=top_n, mode=mode)

        log(f"选股完成, 共 {len(results)} 只候选股票")

        set_cache("screening_results", results)

        output_file = SCREENING_DIR / "top10_stocks.json"
        output_file.write_text(
            json.dumps(
                {
                    "timestamp": _now_iso(),
                    "mode": mode,
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"结果已保存: {output_file}")

        stage_data = {
            "status": "completed",
            "message": f"筛选出 {len(results)} 只候选股票",
            "data": results,
        }
        state = _read_state()
        state["screening"] = stage_data
        _write_state(state)
        return stage_data

    except Exception as e:
        log(f"选股筛选失败: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e), "data": []}


def run_manual_review(selected_indices: Optional[list[int]] = None) -> dict[str, Any]:
    """阶段 2: 人工抽查 — CLI 交互"""
    log("开始阶段 2: 人工抽查（CLI 交互）")

    state = _read_state()
    results = state.get("screening", {}).get("data", [])
    if not results:
        log("没有候选股票，跳过")
        return {"status": "completed", "message": "无候选股票", "data": []}

    if selected_indices is None:
        log("候选股票列表:")
        for i, r in enumerate(results):
            symbol = r.get("symbol", "")
            name = r.get("name", "")
            score = r.get("score", 0)
            log(f"  [{i}] {name}({symbol}) 评分={score}")

        log("请输入要通过的股票序号(用逗号分隔, 如 0,1,2), 或 enter 全部通过:")
        raw = sys.stdin.readline().strip()
        if not raw:
            selected_indices = list(range(len(results)))
        else:
            selected_indices = [int(x.strip()) for x in raw.split(",") if x.strip()]

    approved = [results[i] for i in selected_indices if 0 <= i < len(results)]
    set_cache("approved_stocks", approved)

    log(f"人工抽查完成: {len(approved)}/{len(results)} 只通过")

    state["review"] = {
        "status": "completed",
        "approved_count": len(approved),
        "total_count": len(results),
        "data": approved,
    }
    _write_state(state)
    return {"status": "completed", "message": f"{len(approved)} 只通过", "data": approved}


def run_analysis_stage() -> dict[str, Any]:
    """阶段 3: 趋势分析"""
    log("开始阶段 3: 趋势分析")
    try:
        from src.screener.data_fetcher import StockAnalyzer

        state = _read_state()
        approved = state.get("review", {}).get("data", [])
        if not approved:
            approved = get_cache("approved_stocks", [])
        if not approved:
            log("没有通过审核的股票，跳过分析")
            return {"status": "skipped", "message": "无股票可分析", "data": []}

        symbols = [s.get("code", s.get("symbol", "")) for s in approved]
        analyzer = StockAnalyzer()

        analyzed = []
        for sym in symbols:
            try:
                log(f"  分析 {sym} ...")
                info = analyzer.get_stock_analysis(sym)
                analyzed.append(info)
            except Exception as e:
                log(f"  分析 {sym} 失败: {e}")
                analyzed.append({"symbol": sym, "error": str(e)})

        set_cache("analysis_results", analyzed)

        output_file = TREND_DIR / "analysis_results.json"
        output_file.write_text(
            json.dumps(
                {"timestamp": _now_iso(), "results": analyzed},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"分析结果已保存: {output_file}")

        state["analysis"] = {
            "status": "completed",
            "count": len(analyzed),
            "data": analyzed,
        }
        _write_state(state)
        return {"status": "completed", "message": f"分析 {len(analyzed)} 只", "data": analyzed}

    except Exception as e:
        log(f"趋势分析失败: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e), "data": []}


def run_manual_confirmation(symbols: Optional[list[str]] = None) -> dict[str, Any]:
    """阶段 4: 人工确认"""
    log("开始阶段 4: 人工确认（CLI 交互）")

    state = _read_state()
    analysis = state.get("analysis", {}).get("data", [])
    if not analysis:
        log("没有分析结果，跳过")
        return {"status": "completed", "message": "无分析结果", "data": []}

    if symbols is None:
        log("分析结果列表:")
        for i, a in enumerate(analysis):
            sym = a.get("symbol", "")
            name = a.get("name", "")
            log(f"  [{i}] {name}({sym})")

        log("请输入要确认的股票序号(逗号分隔), 或 enter 全部确认:")
        raw = sys.stdin.readline().strip()
        if not raw:
            symbols = [a.get("symbol", "") for a in analysis]
        else:
            indices = [int(x.strip()) for x in raw.split(",") if x.strip()]
            symbols = [analysis[i].get("symbol", "") for i in indices if 0 <= i < len(analysis)]

    confirmed = [a for a in analysis if a.get("symbol", "") in symbols]
    set_cache("confirmed_stocks", confirmed)

    log(f"人工确认完成: {len(confirmed)}/{len(analysis)} 只通过")

    state["confirmation"] = {
        "status": "completed",
        "count": len(confirmed),
        "symbols": symbols,
        "data": confirmed,
    }
    _write_state(state)
    return {"status": "completed", "message": f"{len(confirmed)} 只确认", "data": confirmed}


def run_kelly_stage() -> dict[str, Any]:
    """阶段 5: 凯利仓位"""
    log("开始阶段 5: 凯利仓位计算")
    try:
        from src.kelly.stock_kelly_analyzer import StockKellyAnalyzer

        state = _read_state()
        confirmed = state.get("confirmation", {}).get("data", [])
        if not confirmed:
            log("没有确认的股票，跳过凯利")
            return {"status": "skipped", "message": "无股票", "data": []}

        symbols = [s.get("symbol", "") for s in confirmed]
        analyzer = StockKellyAnalyzer()

        kelly_results = []
        for sym in symbols:
            try:
                log(f"  凯利计算 {sym} ...")
                result = analyzer.analyze_stock(sym)
                kelly_results.append(result)
            except Exception as e:
                log(f"  凯利 {sym} 失败: {e}")
                kelly_results.append({"symbol": sym, "error": str(e)})

        set_cache("kelly_results", kelly_results)

        output_file = KELLY_DIR / "kelly_suggestions.json"
        output_file.write_text(
            json.dumps(
                {"timestamp": _now_iso(), "results": kelly_results},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"凯利建议已保存: {output_file}")

        state["kelly"] = {
            "status": "completed",
            "count": len(kelly_results),
            "data": kelly_results,
        }
        _write_state(state)
        return {"status": "completed", "message": f"凯利 {len(kelly_results)} 只", "data": kelly_results}

    except Exception as e:
        log(f"凯利计算失败: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e), "data": []}


def run_position_review() -> dict[str, Any]:
    """阶段 6: 持仓审查"""
    log("开始阶段 6: 持仓审查")

    state = _read_state()
    kelly = state.get("kelly", {}).get("data", [])
    if not kelly:
        log("没有凯利结果，跳过")
        return {"status": "completed", "message": "无数据", "data": []}

    log("凯利建议汇总:")
    for k in kelly:
        sym = k.get("symbol", "")
        name = k.get("name", sym)
        fraction = k.get("kelly_fraction", "N/A")
        price = k.get("current_price", "N/A")
        log(f"  {name}({sym}): 凯利仓位={fraction}, 价格={price}")

    set_cache("position_review", kelly)

    state["position_review"] = {
        "status": "completed",
        "data": kelly,
    }
    _write_state(state)
    return {"status": "completed", "message": "持仓审查完成", "data": kelly}


def run_monitor_stage(duration: int = 60) -> dict[str, Any]:
    """阶段 7: 实时监控"""
    log(f"开始阶段 7: 实时监控 (时长 {duration}s)")
    try:
        from src.monitor.monitor import StockAlert, save_watchlist

        state = _read_state()
        kelly = state.get("kelly", {}).get("data", [])
        symbols = [k.get("symbol", "") for k in kelly if k.get("symbol")]

        if not symbols:
            log("没有监控标的，跳过")
            return {"status": "completed", "message": "无标的", "data": []}

        watchlist = []
        for sym in symbols:
            name = next((k.get("name", sym) for k in kelly if k.get("symbol") == sym), sym)
            market = "sh" if sym.startswith("6") else "sz"
            watchlist.append({
                "code": sym,
                "name": name,
                "market": market,
                "type": "individual",
                "cost": kelly[0].get("current_price", 0) if kelly else 0,
                "alerts": {
                    "cost_pct_above": 15.0,
                    "cost_pct_below": -12.0,
                    "change_pct_above": 4.0,
                    "change_pct_below": -4.0,
                    "volume_surge": 2.0,
                },
            })

        save_watchlist(watchlist)

        monitor_output = MONITOR_DIR / "watchlist.json"
        monitor_output.write_text(
            json.dumps(
                {"timestamp": _now_iso(), "watchlist": watchlist},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        log(f"监控标的: {symbols}")
        log(f"监控数据保存: {monitor_output}")

        alert_system = StockAlert(log_to_file=True, log_to_console=False)

        alerts = []
        start = time.time()
        while time.time() - start < duration:
            try:
                result = alert_system.run_once(smart_mode=True)
                if result:
                    if isinstance(result, list):
                        alerts.extend(result)
                    elif isinstance(result, dict):
                        alerts.append(result)
            except Exception as e:
                log(f"  轮询异常: {e}")
            time.sleep(min(5, duration - (time.time() - start)))

        alerts_file = MONITOR_DIR / "alerts.json"
        alerts_file.write_text(
            json.dumps(
                {"timestamp": _now_iso(), "alerts": alerts},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"监控告警已保存: {alerts_file}")

        state["monitor"] = {
            "status": "completed",
            "duration": duration,
            "alerts": len(alerts),
        }
        state["pipeline_status"] = "idle"
        _write_state(state)

        return {"status": "completed", "message": f"监控 {duration}s", "alerts": len(alerts)}

    except Exception as e:
        log(f"监控异常: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# ─── 流水线编排 ───────────────────────────────────────────────────────────────
STAGE_MAP = {
    1: ("选股筛选", run_screening_stage),
    2: ("人工抽查", run_manual_review),
    3: ("趋势分析", run_analysis_stage),
    4: ("人工确认", run_manual_confirmation),
    5: ("凯利仓位", run_kelly_stage),
    6: ("持仓审查", run_position_review),
    7: ("实时监控", run_monitor_stage),
}


def run_pipeline(start_stage: int = 1, monitor_duration: int = 60) -> None:
    """从指定阶段开始运行完整流水线"""
    log(f"========== TransAlpha CLI 流水线 启动 (阶段 {start_stage}) ==========")

    state = _read_state()
    state["pipeline_status"] = "running"
    state["start_time"] = _now_iso()
    _write_state(state)

    for stage_num in range(start_stage, 8):
        name, func = STAGE_MAP[stage_num]
        log(f"\n{'='*50}")
        log(f">>> 阶段 {stage_num}: {name}")
        log(f"{'='*50}")

        try:
            if stage_num == 7:
                func(duration=monitor_duration)
            else:
                func()
        except Exception as e:
            log(f"阶段 {stage_num} 异常: {e}")
            traceback.print_exc()
            state = _read_state()
            state["pipeline_status"] = f"error_at_stage_{stage_num}"
            state["error_message"] = str(e)
            _write_state(state)
            return

    log("\n========== 流水线全部完成 ==========")
    state = _read_state()
    state["pipeline_status"] = "completed"
    state["end_time"] = _now_iso()
    _write_state(state)

    print("\n📁 输出文件:")
    for d in (SCREENING_DIR, TREND_DIR, KELLY_DIR, MONITOR_DIR):
        if d.exists():
            files = list(d.glob("*.json"))
            if files:
                print(f"  {d.relative_to(PROJECT_ROOT)}/")
                for f in files:
                    print(f"    - {f.name}")


def show_status() -> None:
    """显示当前流水线状态"""
    state = _read_state()
    if not state:
        log("尚无流水线状态")
        return

    status = state.get("pipeline_status", "unknown")
    log(f"流水线状态: {status}")
    for key in ("screening", "review", "analysis", "confirmation", "kelly", "position_review", "monitor"):
        if key in state:
            s = state[key]
            log(f"  {key}: {s.get('status', '?')} (数据量: {len(s.get('data', s.get('results', [])))})")


def reset_pipeline() -> None:
    """重置流水线状态"""
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        log("已重置流水线状态")
    _shared.clear()

    for d in (SCREENING_DIR, TREND_DIR, KELLY_DIR, MONITOR_DIR):
        for f in d.glob("*.json"):
            f.unlink()
    log("已清空所有输出目录")


# ─── CLI 入口 ────────────────────────────────────────────────────────────────
def main() -> None:
    args = sys.argv[1:]

    action = "run"
    for a in args:
        if a in ("status", "--status"):
            action = "status"
        elif a in ("reset", "--reset"):
            action = "reset"
        elif a in ("screen", "--screen"):
            action = "screen"
        elif a in ("analyze", "--analyze"):
            action = "analyze"
        elif a in ("kelly", "--kelly"):
            action = "kelly"
        elif a in ("monitor", "--monitor"):
            action = "monitor"
        elif a in ("run", "--run"):
            action = "run"

    kwargs = {}
    for a in args:
        if a.startswith("--stage="):
            kwargs["stage"] = int(a.split("=")[1])
        elif a.startswith("--duration="):
            kwargs["duration"] = int(a.split("=")[1])
        elif a.startswith("--mode="):
            kwargs["mode"] = a.split("=")[1]
        elif a.startswith("--top="):
            kwargs["top_n"] = int(a.split("=")[1])

    if action == "run":
        run_pipeline(kwargs.get("stage", 1), kwargs.get("duration", 60))
    elif action == "status":
        show_status()
    elif action == "reset":
        reset_pipeline()
    elif action == "screen":
        run_screening_stage(mode=kwargs.get("mode", "hot"), top_n=kwargs.get("top_n", 10))
    elif action == "analyze":
        run_analysis_stage()
    elif action == "kelly":
        run_kelly_stage()
    elif action == "monitor":
        run_monitor_stage(duration=kwargs.get("duration", 60))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()