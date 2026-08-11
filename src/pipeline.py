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

【架构说明】
  本文件是整个流水线的"指挥中心"，负责：
  1. 7个阶段的顺序调度（STAGE_MAP + run_pipeline）
  2. 状态持久化（pipeline_state.json，支持断点续跑）
  3. 内存缓存（SharedDataCache，阶段间数据传递）
  4. CLI交互（阶段②④⑥的暂停等待人类确认，对应HABP协议柔性边界）

【HABP人机边界】
  阶段②④⑥为"手动暂停"环节，必须等待人类输入：
  - 阶段②：人工抽查（刚性边界，抽查AI计算的财务指标）
  - 阶段④：人工确认（柔性边界，人类决定最终买入列表）
  - 阶段⑥：人工审查（柔性边界，人类可调整仓位覆盖凯利最优解）
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
BACKTEST_DIR = OUTPUT_DIR / "backtest"
STATE_FILE = OUTPUT_DIR / "pipeline_state.json"

for d in (SCREENING_DIR, TREND_DIR, KELLY_DIR, MONITOR_DIR, BACKTEST_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sym(item: Optional[dict]) -> str:
    """从阶段①输出读取证券代码，兼容 symbol / code 两种字段名。"""
    if not item:
        return ""
    return str(item.get("symbol") or item.get("code") or "").strip()


def _json_default(obj):
    """JSON 序列化兜底：把 numpy 标量转原生，避免 bool_/int64/float64 不可序列化。"""
    try:
        import numpy as np
        if isinstance(obj, np.generic):
            return obj.item()
    except Exception:
        pass
    if isinstance(obj, set):
        return list(obj)
    return str(obj)


def _dumps(obj, **kw) -> str:
    """json.dumps 包装：默认启用 numpy 兼容 default。"""
    kw.setdefault("default", _json_default)
    kw.setdefault("ensure_ascii", False)
    return json.dumps(obj, **kw)


def _read_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    return {}


def _write_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(
        _dumps(state, indent=2),
        encoding="utf-8",
    )


def log(msg: str) -> None:
    print(f"[{_now_iso()}] {msg}", flush=True)


# ─── 共享数据中心 ────────────────────────────────────────────────────────────
class SharedDataCache:
    """内存缓存：用于阶段间数据传递，避免重复计算
    
    【设计目的】
    阶段①筛选结果 → 阶段②抽查 → 阶段③分析，需要传递数据。
    虽然状态文件 pipeline_state.json 也能传递，但内存缓存更快。
    状态文件用于"断点续跑"，内存缓存用于"单次运行内的快速传递"。
    """
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
def run_screening_stage(mode: str = "all", top_n: int = 10,
                        scoring_pool_codes: list = None,
                        strict_filter: bool = None,
                        min_score: float = None) -> dict[str, Any]:
    """阶段 1/③: 因子打分前置-选股筛选（自动）

    【v3.2 新增限定打分池】
      scoring_pool_codes: 指定仅对这些 code 做打分排名（来自④公司研究20只）。
          若提供 → strict_filter 默认 False（④ 已做过滤）
          未提供 → strict_filter 默认 True（全市场基本面+打分）
    【min_score】因子打分最低合格分阈值，None 则用 screener 默认 50。
    """
    if strict_filter is None:
        strict_filter = scoring_pool_codes is None  # 限定池默认宽松；全市场默认严格

    log("开始阶段 1: 选股筛选")
    try:
        from src.screener.screener import StockScreener

        screener = StockScreener()
        call_kwargs = dict(
            top_n=top_n, mode=mode,
            stocks_filter_codes=scoring_pool_codes,
            strict_filter=strict_filter,
        )
        if min_score is not None:
            call_kwargs["min_score"] = min_score
        results = screener.run_screening(**call_kwargs)

        log(f"选股完成, 共 {len(results)} 只候选股票")

        set_cache("screening_results", results)

        output_file = SCREENING_DIR / "top10_stocks.json"
        output_file.write_text(
            _dumps(
                {
                    "timestamp": _now_iso(),
                    "mode": mode,
                    "results": results,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        log(f"结果已保存: {output_file}")

        stage_data = {
            "status": "completed",
            "message": f"筛选出 {len(results)} 只候选股票",
            "data": results,
            "mode": mode,
            "scoring_pool_codes_count": len(scoring_pool_codes) if scoring_pool_codes else 0,
            "strict_filter": strict_filter,
            "pre_filter_stats": getattr(screener, "pre_filter_stats", {}),
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
    """阶段 2: 人工抽查 — CLI 交互（HABP刚性边界）
    
    【暂停目的】
    防止筛选系统静默失效——抽查发现数据异常时应立即中止（H8约束）。
    
    【交互流程】
    1. 从状态文件读取阶段①的Top10结果
    2. 展示候选列表（序号+名称+评分）
    3. 等待用户输入要通过的序号（逗号分隔）
    4. 用户输入回车=全部通过
    
    【HABP边界】
    对应"财务指标计算+因子打分"任务类型，刚性边界。
    人类抽查AI计算的财务指标和评分是否准确。
    """
    log("开始阶段 2: 人工抽查（CLI 交互）")

    state = _read_state()
    results = state.get("screening", {}).get("data", [])
    if not results:
        log("没有候选股票，跳过")
        return {"status": "completed", "message": "无候选股票", "data": []}

    if selected_indices is None:
        log("候选股票列表:")
        for i, r in enumerate(results):
            symbol = _sym(r)
            name = r.get("name", "")
            score = r.get("score", 0)
            log(f"  [{i}] {name}({symbol}) 评分={score}")

        log("请输入要通过的股票序号(用逗号分隔, 如 0,1,2), 或 enter 全部通过:")
        raw = sys.stdin.readline().strip()
        if not raw:
            selected_indices = list(range(len(results)))
        else:
            selected_indices = [int(x.strip()) for x in raw.split(",") if x.strip()]

    approved = []
    for i in selected_indices:
        if 0 <= i < len(results):
            item = dict(results[i])
            item["symbol"] = _sym(item)   # 阶段①输出可能用 code，统一补 symbol
            approved.append(item)
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
        from src.trend.stock_analysis import StockAnalyzer

        state = _read_state()
        approved = state.get("review", {}).get("data", [])
        if not approved:
            approved = get_cache("approved_stocks", [])
        if not approved:
            log("没有通过审核的股票，跳过分析")
            return {"status": "skipped", "message": "无股票可分析", "data": []}

        symbols = [_sym(s) for s in approved if _sym(s)]
        analyzer = StockAnalyzer()

        analyzed = []
        for sym in symbols:
            try:
                log(f"  分析 {sym} ...")
                info = analyzer.analyze(sym, show_progress=False)
                # 归一化字段：trend 用 stock_code/stock_name，下游统一用 symbol/name
                info["symbol"] = sym
                info["name"] = info.get("stock_name", "")
                analyzed.append(info)
            except Exception as e:
                log(f"  分析 {sym} 失败: {e}")
                analyzed.append({"symbol": sym, "name": sym, "error": str(e)})

        set_cache("analysis_results", analyzed)

        output_file = TREND_DIR / "analysis_results.json"
        output_file.write_text(
            _dumps(
                {"timestamp": _now_iso(), "results": analyzed},
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
            sym = _sym(a)
            name = a.get("name", "")
            log(f"  [{i}] {name}({sym})")

        log("请输入要确认的股票序号(逗号分隔), 或 enter 全部确认:")
        raw = sys.stdin.readline().strip()
        if not raw:
            symbols = [_sym(a) for a in analysis]
        else:
            indices = [int(x.strip()) for x in raw.split(",") if x.strip()]
            symbols = [_sym(analysis[i]) for i in indices if 0 <= i < len(analysis)]

    confirmed = [a for a in analysis if _sym(a) in symbols]
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

        symbols = [_sym(s) for s in confirmed if _sym(s)]
        analyzer = StockKellyAnalyzer()

        kelly_results = []
        for sym in symbols:
            try:
                log(f"  凯利计算 {sym} ...")
                result = analyzer.analyze(sym, silent=True)
                result["symbol"] = sym
                result["name"] = result.get("basic_info", {}).get("name", sym)
                result["current_price"] = result.get("market", {}).get("current_price", 0)
                result["kelly_fraction"] = result.get("kelly", {}).get("suggested_fraction", "N/A")
                kelly_results.append(result)
            except Exception as e:
                log(f"  凯利 {sym} 失败: {e}")
                kelly_results.append({"symbol": sym, "error": str(e)})

        set_cache("kelly_results", kelly_results)

        output_file = KELLY_DIR / "kelly_suggestions.json"
        output_file.write_text(
            _dumps(
                {"timestamp": _now_iso(), "results": kelly_results},
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
        symbols = [_sym(k) for k in kelly if _sym(k)]

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
                "cost": next((k.get("current_price", 0) for k in kelly if k.get("symbol") == sym), 0),
                "alerts": {
                    "cost_pct_above": 15.0,
                    "cost_pct_below": -12.0,
                    "change_pct_above": 4.0,
                    "change_pct_below": -4.0,
                    "volume_surge": 2.0,
                },
            })

        # save_watchlist 已通过文件锁 + 原子写入把 list 持久化到 watchlist.json。
        # 注意：monitor.reload_watchlist 仅接受 list 格式（isinstance(..., list)），
        # 切勿再用 dict（如 {"timestamp":..., "watchlist":...}）覆盖同一文件，
        # 否则监控模块会拒绝加载新列表，回退到上次残留的 watchlist。
        save_watchlist(watchlist)

        monitor_output = MONITOR_DIR / "watchlist.json"
        log(f"监控标的: {symbols}")
        log(f"监控数据保存: {monitor_output} (list 格式, {len(watchlist)} 只)")

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
            _dumps(
                {"timestamp": _now_iso(), "alerts": alerts},
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
def run_backtest_stage(start_date: str = "", end_date: str = "",
                       rebalance: str = "monthly", top_n: int = 5,
                       initial_capital: float = 1_000_000.0) -> dict[str, Any]:
    """阶段 8: 回测校验（Proxy 策略，宽池周度再平衡，双基准对照）

    【数据源】baostock（历史K线/财报PIT/指数/资金流proxy）
    【输出】output/backtest/equity_curve.csv / metrics.json / trade_log.csv

    默认区间：最近约 36 个月（取 end_date 为今天，start 为三年前）。可用
    run_backtest_stage(start_date=..., end_date=...) 覆盖。
    """
    from datetime import datetime, timedelta

    log("开始阶段 8: 回测校验（proxy 策略 · 宽池）")
    try:
        from src.backtest.runner import BacktestConfig, BacktestRunner
        from src.backtest.report import export_backtest_result

        today = datetime.now()
        start = start_date or (today - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
        end = end_date or today.strftime("%Y-%m-%d")

        cfg = BacktestConfig(
            initial_capital=initial_capital,
            start_date=start, end_date=end,
            rebalance=rebalance, top_n=top_n,
        )
        runner = BacktestRunner(cfg=cfg)
        result = runner.run(stock_pool=None)
        paths = export_backtest_result(result)

        m = result.get("metrics", {})
        summary = {
            "start_date": result.get("start_date"), "end_date": result.get("end_date"),
            "pool_size": result.get("pool_size"),
            "total_return": m.get("total_return"),
            "annual_return": m.get("annual_return"),
            "max_drawdown": m.get("max_drawdown"),
            "sharpe": m.get("sharpe"),
            "n_trades": m.get("n_trades"),
            "win_rate": m.get("win_rate"),
            "output": {k: str(v) for k, v in paths.items()},
        }
        log(f"阶段8回测完成: 区间 {result.get('start_date')}~{result.get('end_date')}, "
            f"累计 {m.get('total_return', 0):.2%}")
        for name, p in paths.items():
            log(f"  输出 {name}: {p}")

        state = _read_state()
        state["backtest"] = {"status": "completed", "data": summary}
        _write_state(state)
        set_cache("backtest_result", result)
        return {"status": "completed", "message": "回测完成", "data": summary}

    except RuntimeError as e:
        log(f"回测执行失败: {e}")
        return {"status": "error", "message": str(e)}
    except Exception as e:
        log(f"回测异常: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# ─── 流水线编排 ───────────────────────────────────────────────────────────────
STAGE_MAP = {
    # 阶段号: (阶段名称, 执行函数)
    # 阶段②④⑥为CLI交互暂停环节，对应HABP柔性/刚性边界
    1: ("选股筛选", run_screening_stage),
    2: ("人工抽查", run_manual_review),
    3: ("趋势分析", run_analysis_stage),
    4: ("人工确认", run_manual_confirmation),
    5: ("凯利仓位", run_kelly_stage),
    6: ("持仓审查", run_position_review),
    7: ("实时监控", run_monitor_stage),
    8: ("回测校验", run_backtest_stage),
}


def run_pipeline(start_stage: int = 1, monitor_duration: int = 60) -> None:
    """从指定阶段开始运行完整流水线
    
    【断点续跑机制】
    通过 pipeline_state.json 记录每个阶段的完成状态。
    如果中断后再次调用，可以从指定阶段继续，不必从头开始。
    
    【异常处理】
    任意阶段异常都会：
    1. 记录错误状态到 pipeline_state.json
    2. 打印堆栈跟踪
    3. 退出流水线（不会继续后续阶段）
    
    【监控时长】
    阶段⑦实时监控默认运行60秒，可通过 monitor_duration 参数调整。
    """
    log(f"========== TransAlpha CLI 流水线 启动 (阶段 {start_stage}) ==========")

    state = _read_state()
    state["pipeline_status"] = "running"
    state["start_time"] = _now_iso()
    _write_state(state)

    for stage_num in range(start_stage, 9):
        name, func = STAGE_MAP[stage_num]
        log(f"\n{'='*50}")
        log(f">>> 阶段 {stage_num}: {name}")
        log(f"{'='*50}")

        try:
            if stage_num == 7:
                func(duration=monitor_duration)
            elif stage_num == 8:
                func()
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
    for d in (SCREENING_DIR, TREND_DIR, KELLY_DIR, MONITOR_DIR, BACKTEST_DIR):
        if d.exists():
            files = list(d.glob("*.json")) + list(d.glob("*.csv"))
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
    for key in ("screening", "review", "analysis", "confirmation", "kelly", "position_review", "monitor", "backtest"):
        if key in state:
            s = state[key]
            log(f"  {key}: {s.get('status', '?')} (数据量: {len(s.get('data', s.get('results', [])))})")


def reset_pipeline() -> None:
    """重置流水线状态"""
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        log("已重置流水线状态")
    _shared.clear()

    for d in (SCREENING_DIR, TREND_DIR, KELLY_DIR, MONITOR_DIR, BACKTEST_DIR):
        for f in d.glob("*"):
            if f.suffix in (".json", ".csv"):
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
        elif a in ("backtest", "--backtest"):
            action = "backtest"
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
        elif a.startswith("--bt-start="):
            kwargs["bt_start"] = a.split("=")[1]
        elif a.startswith("--bt-end="):
            kwargs["bt_end"] = a.split("=")[1]

    if action == "run":
        run_pipeline(kwargs.get("stage", 1), kwargs.get("duration", 60))
    elif action == "status":
        show_status()
    elif action == "reset":
        reset_pipeline()
    elif action == "screen":
        run_screening_stage(mode=kwargs.get("mode", "all"), top_n=kwargs.get("top_n", 10))
    elif action == "analyze":
        run_analysis_stage()
    elif action == "kelly":
        run_kelly_stage()
    elif action == "monitor":
        run_monitor_stage(duration=kwargs.get("duration", 60))
    elif action == "backtest":
        run_backtest_stage(
            start_date=kwargs.get("bt_start", ""),
            end_date=kwargs.get("bt_end", ""),
            top_n=kwargs.get("top_n", 5),
        )
    else:
        print(__doc__)
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# 新工作流 (对应 docs/workflow/main_auto_workflow.md)
#   ③ 信息收集 → ⓪审查① → ④ 公司研究 → ⓪审查② → ⑤ 因子打分
#   → ⑥ 组合构建 → ⓪审查③ → ⑦ 回测校验 → ⑧ 风险检查 → ⓪审查④
#   → ⑨ 调仓执行 → ⑩ 归因复盘
# ═══════════════════════════════════════════════════════════════════════════

# 新 8 环节输出目录（main_auto_workflow.md §5 目录结构）
INFO_DIR       = OUTPUT_DIR / "info-collection"        # ③
RESEARCH_DIR   = OUTPUT_DIR / "company-research"       # ④
SCORING_DIR    = OUTPUT_DIR / "factor-scoring"         # ⑤
PORTFOLIO_DIR  = OUTPUT_DIR / "portfolio-construction" # ⑥
RISK_DIR       = OUTPUT_DIR / "risk-check"             # ⑧
REBALANCE_DIR  = OUTPUT_DIR / "rebalance-execution"    # ⑨
ATTRIBUTION_DIR = OUTPUT_DIR / "attribution-review"    # ⑩

for _d in (INFO_DIR, RESEARCH_DIR, SCORING_DIR, PORTFOLIO_DIR,
           BACKTEST_DIR, RISK_DIR, REBALANCE_DIR, ATTRIBUTION_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# 无人值守模式开关（run.py --auto-approve 时设置，4 个审查点自动放行）
_AUTO_APPROVE = False


def set_auto_approve(v: bool = True) -> None:
    """设置无人值守模式: 4 个人工审查点自动放行（用于测试/CI）"""
    global _AUTO_APPROVE
    _AUTO_APPROVE = v


def _auto_approve() -> bool:
    return _AUTO_APPROVE


def _review_prompt(prompt_text: str, default_all_count: int = 0) -> bool:
    """审查暂停点：auto 模式直接通过，否则提示用户回车确认"""
    if _auto_approve():
        log(f"  [无人值守] 自动通过: {prompt_text}")
        return True
    log(f"\n⏸  {prompt_text}")
    try:
        raw = input("  [Enter] 通过 / 输入其他字符退回: ").strip()
    except EOFError:
        raw = ""
    return raw == ""


# ─── 板块六维热度打分（简化代理版，v3.2 新增）────────────────────────────────
def compute_sector_heat_scores(stocks: list) -> tuple:
    """计算板块六维热度评分（简化代理版）

    基于现有每股数据（change_pct/amount/turnover）按 industry_level2 聚合，
    输出板块级 total_score + decision，并回填到每只股票。

    代理维度说明（对齐 docs/trading/TransAlpha赛道景气度打分表.md 六维模型）：
      - 催化强度(Catalyst, 15%) 置中性 50（无新闻数据，待后续接入）
      - 技术形态(Tech) 用日涨幅代理（无K线历史，未算MA/MACD）
      - 连板高度(Height) 仅检测当日涨停（无连板历史）

    Returns:
        (sector_heat_dict, stocks_with_score)
    """
    if not stocks:
        return {}, stocks

    # 1. 按 industry_level2 聚合
    sectors: dict = {}
    for s in stocks:
        sec = s.get("industry_level2") or "通用"
        sectors.setdefault(sec, []).append(s)

    num_sectors = len(sectors)
    total_amount = sum(float(s.get("amount", 0) or 0) for s in stocks)
    avg_amount_per_sector = total_amount / max(1, num_sectors)

    # 2. 计算每个 sector 的六维原始值
    sector_raw: dict = {}
    for sec_name, sec_stocks in sectors.items():
        n = len(sec_stocks)
        changes = [float(s.get("change_pct", 0) or 0) for s in sec_stocks]
        amounts = [float(s.get("amount", 0) or 0) for s in sec_stocks]
        turnovers = [float(s.get("turnover", 0) or 0) for s in sec_stocks]

        sec_total_amount = sum(amounts)
        sec_avg_change = sum(changes) / n if n else 0
        sec_avg_turnover = sum(turnovers) / n if n else 0
        gainers = sum(1 for c in changes if c > 0)
        limit_ups = sum(1 for c in changes if c >= 9.8)
        max_change = max(changes) if changes else 0

        # 资金驱动力: sector成交额 / 平均板块成交额 × 100，截断0-100
        capital = min(100.0, (sec_total_amount / avg_amount_per_sector * 100) if avg_amount_per_sector > 0 else 0)

        # 连板高度: 涨停占比×70 + 最高涨幅归一化×30
        limit_up_ratio = (limit_ups / n * 100) if n else 0
        max_change_norm = min(100.0, max(0, max_change / 20 * 100))
        height = min(100.0, limit_up_ratio * 0.7 + max_change_norm * 0.3)

        # 技术形态: 平均涨幅归一化×60 + 上涨家数占比×40
        avg_change_norm = min(100.0, max(0, (sec_avg_change + 5) / 10 * 100))
        gainer_ratio = (gainers / n * 100) if n else 0
        tech = avg_change_norm * 0.6 + gainer_ratio * 0.4

        # 催化强度: 中性50（代理，无新闻数据）
        catalyst = 50.0

        # 龙头辨识度: top1 - top2 的领先度
        if n >= 2:
            sorted_changes = sorted(changes, reverse=True)
            leader_gap = (sorted_changes[0] - sorted_changes[1]) / 10 * 100
        else:
            leader_gap = 0
        leader = min(100.0, max(0, leader_gap))

        sector_raw[sec_name] = {
            "capital": capital, "height": height, "tech": tech,
            "catalyst": catalyst, "leader": leader,
            "avg_change": sec_avg_change, "avg_turnover": sec_avg_turnover,
            "total_amount": sec_total_amount, "stock_count": n,
        }

    # 3. 市场认可度: 三项排名综合（涨幅排名 + 换手率排名 + 成交额排名）
    sec_names = list(sector_raw.keys())
    for metric in ("avg_change", "avg_turnover", "total_amount"):
        ranked = sorted(sec_names, key=lambda x: sector_raw[x][metric], reverse=True)
        for rank, name in enumerate(ranked):
            percentile = (len(sec_names) - rank) / len(sec_names) * 100
            sector_raw[name].setdefault("_market_ranks", []).append(percentile)
    for name in sec_names:
        ranks = sector_raw[name].get("_market_ranks", [50.0, 50.0, 50.0])
        sector_raw[name]["market"] = sum(ranks) / len(ranks) if ranks else 50.0

    # 4. 计算总分 + decision（对齐赛道景气度打分表决策标准）
    sector_heat: dict = {}
    for sec_name, raw in sector_raw.items():
        total = (raw["capital"] * 0.25 + raw["height"] * 0.20 + raw["tech"] * 0.20
                 + raw["catalyst"] * 0.15 + raw["leader"] * 0.10 + raw["market"] * 0.10)
        total = round(total, 1)
        if total >= 75:
            decision = "首选介入"
        elif total >= 55:
            decision = "观察参与"
        else:
            decision = "禁止参与"
        sector_heat[sec_name] = {
            "total_score": total,
            "decision": decision,
            "capital_score": round(raw["capital"], 1),
            "height_score": round(raw["height"], 1),
            "tech_score": round(raw["tech"], 1),
            "catalyst_score": round(raw["catalyst"], 1),
            "leader_score": round(raw["leader"], 1),
            "market_score": round(raw["market"], 1),
            "stock_count": raw["stock_count"],
            "proxy_dimensions": ["catalyst"],
        }

    # 5. 回填到每只股票
    for s in stocks:
        sec = s.get("industry_level2") or "通用"
        heat = sector_heat.get(sec)
        if heat:
            s["sector_heat_score"] = heat["total_score"]
            s["sector_decision"] = heat["decision"]
        else:
            s["sector_heat_score"] = 0
            s["sector_decision"] = "禁止参与"

    return sector_heat, stocks


# ─── ③ 信息收集 ──────────────────────────────────────────────────────────────
def run_info_collection_stage() -> dict[str, Any]:
    """环节③ 信息收集（自动）
    【工具】src/screener/data_fetcher.py :: StockDataFetcher
    【输出】output/info-collection/market_data.json
    """
    log("=" * 58)
    log("③ 信息收集 (全A股数据台账)")
    log("=" * 58)
    try:
        from src.screener.data_fetcher import StockDataFetcher

        fetcher = StockDataFetcher()
        log("  抓取全A股基础列表 (四源回退链)...")
        stocks = fetcher.get_all_a_stocks(max_count=0, use_cache=True)
        data_source = fetcher.get_data_source_status()

        log(f"  列表获取完成: {len(stocks)} 只股票, 数据源={data_source.get('data_source')}, "
            f"降级={data_source.get('degraded')}")

        # 【v3.2 新增】补全 market_cap（总市值）
        log("  补全 market_cap (总市值)...")
        stocks = fetcher.enrich_market_cap(stocks)

        # 【v3.4 新增】补全实时行情 price/change_pct/volume/amount
        # （get_all_a_stocks 可能来自不含行情的数据源如 akshare 代码名称源，
        #   enrich_market_cap 只补市值不补 price，这里补上行情字段）
        stocks = fetcher.enrich_realtime_quotes(stocks)

        # 【v3.2 新增】计算板块六维热度评分（简化代理版）
        log("  计算板块六维热度评分...")
        sector_heat, stocks = compute_sector_heat_scores(stocks)
        hot_sectors = sum(1 for v in sector_heat.values() if v["total_score"] >= 55)
        log(f"  板块热度: 共 {len(sector_heat)} 个板块, 其中 ≥55分(可参与) {hot_sectors} 个")

        # 字段摘要 + 质量检查
        missing_price = sum(1 for s in stocks if float(s.get("price", 0) or 0) <= 0)
        missing_cap = sum(1 for s in stocks if int(s.get("market_cap", 0) or 0) <= 0)
        missing_heat = sum(1 for s in stocks if not s.get("sector_heat_score"))

        market_data = {
            "timestamp": _now_iso(),
            "stage": "3_info_collection",
            "data_source": data_source,
            "total": len(stocks),
            "quality": {
                "has_price_count": len(stocks) - missing_price,
                "has_price_rate": f"{(len(stocks) - missing_price) / max(1, len(stocks)):.2%}",
                "has_market_cap_count": len(stocks) - missing_cap,
                "has_market_cap_rate": f"{(len(stocks) - missing_cap) / max(1, len(stocks)):.2%}",
                "has_sector_heat_count": len(stocks) - missing_heat,
                "has_sector_heat_rate": f"{(len(stocks) - missing_heat) / max(1, len(stocks)):.2%}",
            },
            "sector_heat": sector_heat,   # 板块热度聚合（六维评分）
            "stocks": stocks,             # 全量保存（不再截断500）
            "_sample_fields": list(stocks[0].keys()) if stocks else [],
        }

        out = INFO_DIR / "market_data.json"
        out.write_text(_dumps(market_data, indent=2), encoding="utf-8")
        log(f"  ✅ 数据台账已保存: {out} ({len(stocks)} 只股票)")
        log(f"     价格覆盖率: {market_data['quality']['has_price_rate']}")
        log(f"     市值覆盖率: {market_data['quality']['has_market_cap_rate']}")
        log(f"     板块热度覆盖率: {market_data['quality']['has_sector_heat_rate']}")

        set_cache("market_data", market_data)
        set_cache("info_collection_stocks", stocks)   # 全量放内存，供下游使用

        state = _read_state()
        state["info_collection"] = {
            "status": "completed",
            "total": len(stocks),
            "data_source": data_source,
            "quality": market_data["quality"],
            "sector_heat_count": len(sector_heat),
            "tradable_sectors": hot_sectors,
        }
        state["approved_after_info"] = None  # 待审查①
        _write_state(state)
        return {"status": "completed", "total": len(stocks),
                "data_source": data_source, "quality": market_data["quality"],
                "sector_heat_count": len(sector_heat)}

    except Exception as e:
        log(f"③ 信息收集失败: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# ─── ⓪ 人工审查① (③ 信息收集之后) ──────────────────────────────────────────
def run_manual_review_data() -> dict[str, Any]:
    """人工审查①: 抽查数据源是否降级、行情是否异常 (H8 硬约束)"""
    log("=" * 58)
    log("⓪ 人工审查① → 数据质量抽查")
    log("=" * 58)
    state = _read_state()
    info = state.get("info_collection", {})
    if not info:
        log("  ⚠️  环节③尚未执行，无法审查")
        return {"status": "skipped", "approved": False}

    total = info.get("total", 0)
    ds = info.get("data_source", {})
    q = info.get("quality", {})
    degraded = ds.get("degraded", False)

    log(f"  股票数量: {total}")
    log(f"  数据源  : {ds.get('data_source')}")
    log(f"  是否降级: {degraded}{'  ⚠️ 降级=' + ds.get('degrade_reason', '') if degraded else ''}")
    log(f"  价格覆盖率: {q.get('has_price_rate')}  市值覆盖率: {q.get('has_market_cap_rate')}")

    # H8 硬约束：降级必须回退重跑，这里提示但不自动回退，由人工决定
    if degraded:
        log("  ⚠️  【H8 触发】数据源已降级到 hardcoded_59，建议回到③重跑（输入 'n' 退回）")

    approved = _review_prompt(
        f"请抽查数据质量 (共{total}只)。回车通过 / 任意字符回退到 ③",
    )
    state = _read_state()
    state["manual_review_1"] = {
        "status": "approved" if approved else "rejected",
        "timestamp": _now_iso(),
    }
    _write_state(state)
    log(f"  审查结果: {'✅ 通过' if approved else '❌ 退回'}")
    return {"status": "approved" if approved else "rejected", "approved": approved}


# ─── ④ 公司研究候选池筛选（v3.2 新规范）────────────────────────────────────
def _market_board_of(code: str) -> str:
    """根据代码判断板块 → 决定财务营收门槛
    主板(600/601/603/605/000/001/002/003/004): <3亿
    创业板(300/301): <1亿
    科创板(688/689): <1亿
    北交所(8/4开头): 此处不纳入
    """
    if code.startswith(("300", "301")):
        return "cyb"  # 创业板
    if code.startswith(("688", "689")):
        return "kcb"  # 科创板
    if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003", "004")):
        return "main"
    return "main"  # 回退为主板（最宽松但仍<3亿则剔除）


def filter_research_candidates(info_stocks: list, top_n: int = 50,
                                per_sector_quota: int = 15,
                                truncation_mode: str = "weighted") -> tuple:
    """按 ④ 公司研究文档 Step 2 筛选候选池（v3.3 新版规范 — 多维截断）

    筛选顺序：
      0. 板块热度 sector_heat_score ≥ 55（首选介入+观察参与）
      1. 排除 ST/*ST（简称含 ST 即剔除）
      2. 排除市值 < 50 亿
      3. 排除财务不达标：扣非净利润<0 且 营收低于板块门槛（主<3亿/科创创业板<1亿）
      4. 排除审计报告异常（保留/无法表示/否定意见）— akshare 接口不可用时标记 skip
      5. 截断 — 支持三种模式（方案 A+B+C）：
          "weighted"   — 板块配额 + 多维加权排序（默认，推荐）
                          先按板块热度分板块，每板块最多 per_sector_quota 只；
                          剩余名额用综合加权分排序取前（板块热度×0.4 + 市值×0.3 + 盈利能力×0.3）
          "cap_first"  — 旧逻辑：板块热度降序 + 市值降序
          "heat_first" — 纯板块热度优先，同热度内随机

    Args:
        info_stocks: ③ 信息收集产出的 stocks 列表（含 market_cap / sector_heat_score / name / code）
        top_n: 最终入选数量（研究报告上限，默认50；⑤打分时再做维度短板过滤）
        per_sector_quota: 方案C 每板块固定配额，默认15（板块>配额时优先按板块内排序）
        truncation_mode: 截断模式 "weighted" / "cap_first" / "heat_first"

    Returns:
        (passed_codes, filter_stats)
          passed_codes: 入选 code 列表（≤ top_n）
          filter_stats: 每步筛选留存数/剔除明细，用于日志
    """
    if not info_stocks:
        return [], {}

    stats = {"input": len(info_stocks)}

    # Step 0: 板块热度 ≥ 55（板块优先，对齐文档 Step 2）
    step0 = [s for s in info_stocks if s.get("sector_heat_score", 0) >= 55]
    stats["step0_heat_ok"] = len(step0)
    stats["step0_filtered_out"] = stats["input"] - len(step0)
    if not step0:
        log("  ⚠️  板块热度≥55 的板块无股票（全市场可能低迷），降级：保留 sector_heat 排名前5板块内股票")
        unique_secs = sorted(
            set((s.get("industry_level2") or "通用") for s in info_stocks),
            key=lambda sec: max((_s.get("sector_heat_score", 0) for _s in info_stocks
                                 if (_s.get("industry_level2") or "通用") == sec), default=0),
            reverse=True,
        )[:5]
        step0 = [s for s in info_stocks if (s.get("industry_level2") or "通用") in unique_secs]
        stats["step0_heat_ok_fallback"] = len(step0)

    # Step 1: 排除 ST/*ST
    def _is_st(s) -> bool:
        name = s.get("name", "") or ""
        # 大小写都查：S T 任意组合
        return bool(name) and ("ST" in name.upper() or "*ST" in name.upper() or "ST*" in name.upper())
    step1 = [s for s in step0 if not _is_st(s)]
    stats["step1_no_st"] = len(step1)
    stats["step1_filtered_out_st"] = stats["step0_heat_ok_fallback"] if "step0_heat_ok_fallback" in stats \
        else len(step0) - len(step1)

    # Step 2: 排除市值 < 50 亿（5e9 元）
    CAP_MIN_YI = 50
    step2 = [s for s in step1 if int(s.get("market_cap", 0) or 0) >= CAP_MIN_YI * 1e8]
    stats["step2_cap_ok"] = len(step2)
    stats["step2_filtered_out_small_cap"] = len(step1) - len(step2)

    if not step2:
        log("  ⚠️  Step 2 之后无股票，跳过财务/审计筛选")
        return [], stats

    # Step 3: 财务不达标（扣非净利润为负 AND 营收<门槛）
    # 按需调用 fetch_fundamental（东方财富 API，可能限流/失败，需降级处理）
    from src.screener.data_fetcher import StockDataFetcher
    fetcher = StockDataFetcher()
    step3 = []
    fin_unavailable = 0
    fin_violation = 0
    threshold_main_wan = 3 * 1e8   # 主板 3亿
    threshold_tech_wan = 1 * 1e8  # 科创/创业 1亿
    for s in step2:
        code = s.get("code", "")
        if not code:
            continue
        fund = fetcher.fetch_fundamental(code)
        if not fund:
            fin_unavailable += 1
            # 财务数据不可用时，做弱过滤：仅依赖市值/热度/ST（不强制剔除，记 note）
            s["_fin_note"] = "fin_data_unavailable"
            step3.append(s)
            continue
        revenue = float(fund.get("revenue") or 0)
        # 扣非前后孰低
        profit_excl = fund.get("net_profit_excl_nonrecurring")
        profit_std = fund.get("net_profit")
        profit_lower = profit_excl if profit_excl is not None else profit_std
        profit_lower = float(profit_lower or 0)
        board = _market_board_of(code)
        threshold = threshold_tech_wan if board in ("cyb", "kcb") else threshold_main_wan
        if profit_lower < 0 and revenue < threshold:
            fin_violation += 1
            s["_filter_reason"] = f"财务不达标(亏损{profit_lower/1e8:.2f}亿+营收{revenue/1e8:.2f}亿<门槛{threshold/1e8:.0f}亿)"
            continue
        s["_fin_fetched"] = True
        s["_revenue_yi"] = round(revenue / 1e8, 2)
        s["_profit_lower_yi"] = round(profit_lower / 1e8, 2)
        step3.append(s)
    stats["step3_fin_ok"] = len(step3)
    stats["step3_unavailable"] = fin_unavailable
    stats["step3_violations"] = fin_violation

    # Step 4: 审计报告异常
    step4 = []
    audit_violations = 0
    audit_unavailable = 0
    NON_STANDARD_AUDIT = ("保留意见", "无法表示意见", "否定意见")
    for s in step3:
        code = s.get("code", "")
        audit = fetcher.fetch_audit_opinion(code) if code else None
        if not audit:
            audit_unavailable += 1
            # 审计数据不可用：不强制剔除（弱过滤）
            s["_audit_note"] = "audit_unavailable"
            step4.append(s)
            continue
        opinion = audit.get("audit_opinion", "") or ""
        is_bad = any(tag in opinion for tag in NON_STANDARD_AUDIT)
        if is_bad:
            audit_violations += 1
            s["_filter_reason"] = f"审计异常({opinion})"
            continue
        s["_audit_ok"] = True
        s["_audit_opinion"] = opinion
        step4.append(s)
    stats["step4_audit_ok"] = len(step4)
    stats["step4_unavailable"] = audit_unavailable
    stats["step4_violations"] = audit_violations

    # ── Step 5: 截断（方案 A+B+C 多维加权 + 板块配额）───────────────────────
    if len(step4) <= top_n:
        final = list(step4)
        stats["truncation_mode"] = "none"
        stats["truncation_note"] = f"Step4 仅 {len(step4)} 只 ≤ top_n={top_n}，无需截断"
    else:
        if truncation_mode == "cap_first":
            # 旧逻辑：板块热度 → 市值降序
            stats["truncation_mode"] = "cap_first"
            final = sorted(step4, key=lambda x: (
                -int(x.get("sector_heat_score", 0) or 0),
                -int(x.get("market_cap", 0) or 0),
            ))[:top_n]

        elif truncation_mode == "heat_first":
            stats["truncation_mode"] = "heat_first"
            final = sorted(step4, key=lambda x: (
                -int(x.get("sector_heat_score", 0) or 0),
            ))[:top_n]

        else:  # "weighted" — 默认：板块配额 + 加权排序
            stats["truncation_mode"] = "weighted"
            stats["truncation_per_sector_quota"] = per_sector_quota

            # 5.1 按板块热度降序分组
            sec_groups: dict[str, list] = {}
            for s in step4:
                sec = s.get("industry_level2") or "通用"
                sec_groups.setdefault(sec, []).append(s)

            def _sec_heat(sec: str) -> float:
                stocks = sec_groups.get(sec, [])
                return max((float(s.get("sector_heat_score", 0) or 0) for s in stocks), default=0.0)

            sec_names_sorted = sorted(sec_groups.keys(), key=_sec_heat, reverse=True)

            # 5.2 板块内排序：市值降序 + 盈利降序
            for sec in sec_names_sorted:
                sec_groups[sec].sort(key=lambda s: (
                    -int(s.get("market_cap", 0) or 0),
                    -float(s.get("_profit_lower_yi", 0) or 0),
                ))

            # 5.3 每个板块取 quota 只，组成板块配额池（保底）
            sector_quota_pool: list = []
            for sec in sec_names_sorted:
                picks = sec_groups[sec][:per_sector_quota]
                sector_quota_pool.extend(picks)
            stats["truncation_sectors"] = len(sec_names_sorted)
            stats["truncation_quota_pool_size"] = len(sector_quota_pool)

            # 5.4 板块配额池先入 final（保底，防止某板块被全挤出）
            quota_codes = {_sym(s) for s in sector_quota_pool if _sym(s)}
            remaining_pool = [s for s in step4 if _sym(s) not in quota_codes]

            remaining_slots = max(0, top_n - len(sector_quota_pool))

            if remaining_slots <= 0:
                # 板块配额已超 top_n，按板块内排名再裁一轮
                final = sector_quota_pool[:top_n]
                stats["truncation_surplus_sectors"] = len(final) - top_n
            else:
                # 板块配额池先保底
                final = list(sector_quota_pool)
                # 剩余名额从 step4 排除配额池后，按加权分排序补充
                def _composite_score(s: dict) -> float:
                    """加权分: 板块热度×0.4 + 市值排名分×0.3 + 盈利能力×0.3
                    所有维度先归一化到 [0,1]。"""
                    heat_all = [float(x.get("sector_heat_score", 0) or 0) for x in step4]
                    h_min, h_max = min(heat_all), max(heat_all)
                    h_norm = (float(s.get("sector_heat_score", 0) or 0) - h_min) / max(h_max - h_min, 1e-9)

                    import math as _math
                    cap = max(int(s.get("market_cap", 0) or 0), 1)
                    cap_all = [max(int(x.get("market_cap", 0) or 0), 1) for x in step4]
                    c_min, c_max = _math.log(min(cap_all)), _math.log(max(cap_all))
                    c_norm = (_math.log(cap) - c_min) / max(c_max - c_min, 1e-9)

                    profit = float(s.get("_profit_lower_yi", 0) or 0)
                    fin_ok = 1.0 if s.get("_fin_fetched") else 0.5
                    p_norm = (1.0 if profit > 0 else 0.0) * fin_ok

                    return h_norm * 0.4 + c_norm * 0.3 + p_norm * 0.3

                remaining_weighted = sorted(remaining_pool, key=_composite_score, reverse=True)
                final.extend(remaining_weighted[:remaining_slots])

            stats["truncation_final_size"] = len(final)

    final_codes = [_sym(s) for s in final if _sym(s)]
    stats["final_count"] = len(final_codes)
    stats["final_codes_sample"] = [(s.get("code"), s.get("name"),
                                    s.get("sector_heat_score"),
                                    round(int(s.get("market_cap", 0) or 0) / 1e8, 1),
                                    s.get("industry_level2"))
                                   for s in final[:5]]
    return final_codes, stats


# ─── ④ 公司研究 ──────────────────────────────────────────────────────────────
def run_company_research_stage(research_top_n: int = 50,
                                per_sector_quota: int = 15,
                                truncation_mode: str = "weighted") -> dict[str, Any]:
    """环节④ 公司研究（自动） — 复用 StockAnalyzer 生成个股深度报告
    候选池来源（v3.3 新版）：优先 ⑤打分输出，否则从 filter_research_candidates() 按规范筛选：
      Step 0: sector_heat_score ≥ 55 的板块内股票优先
      Step 1: 排除 ST/*ST
      Step 2: 排除市值 < 50 亿
      Step 3: 排除财务不达标（扣非亏损+营收低于板块门槛）
      Step 4: 排除审计异常（非标意见）
      Step 5: 截断 — 方案A 加权排序 + 方案C 板块配额
    【输出】output/company-research/research_reports.json
    """
    log("=" * 58)
    log(f"④ 公司研究 (个股深度报告, 候选上限={research_top_n}, 截断={truncation_mode}, 板块配额={per_sector_quota})")
    log("=" * 58)
    try:
        from src.trend.stock_analysis import StockAnalyzer

        # 候选池来源优先级：
        #   1. cache("scoring_topn") — 同一次运行内⑤刚跑完，直接取
        #   2. state.factor_scoring.topn_codes — 仅当 status == "completed" 时信任
        #      （防旧状态污染：上一轮残留的 factor_scoring 字段 status != completed 会被跳过）
        #   3. 规范筛选漏斗 — 4539 只全A股 → Step0~4 过滤 → 最多 50 只
        candidates_codes: list[str] = []
        filter_stats: dict = {}
        state = _read_state()

        # --- 守卫：只有 factor_scoring.status 明确为 "completed" 才信任 ---
        fs = state.get("factor_scoring", {})
        fs_completed = (isinstance(fs, dict) and fs.get("status") == "completed")
        fs_has_codes = bool(fs.get("topn_codes"))

        cache_topn = get_cache("scoring_topn") or []
        state_topn = fs.get("topn_codes", []) if fs_completed else []

        sc = list(cache_topn) if cache_topn else list(state_topn)

        # 额外诊断：如果 state 里有 topn_codes 但 status != completed，说明是脏数据
        if fs_has_codes and not fs_completed:
            log(f"  🛡️  检测到旧 factor_scoring 残留 (status={fs.get('status')})，已忽略，走规范筛选")

        if sc:
            candidates_codes = list(sc)
            src = "cache(scoring_topn)" if cache_topn else "state.factor_scoring.topn_codes"
            log(f"  候选池来自 ⑤ 因子打分 ({src}): {len(candidates_codes)} 只")
        else:
            info_stocks = get_cache("info_collection_stocks") or []
            if not info_stocks:
                info = INFO_DIR / "market_data.json"
                if info.exists():
                    d = json.loads(info.read_text(encoding="utf-8"))
                    info_stocks = d.get("stocks", [])
            log(f"  执行规范筛选（板块热度≥55 + ST + 市值≥50亿 + 财务 + 审计 + {truncation_mode}截断）...")
            candidates_codes, filter_stats = filter_research_candidates(
                info_stocks, top_n=research_top_n,
                per_sector_quota=per_sector_quota,
                truncation_mode=truncation_mode,
            )
            # 打印筛选漏斗
            log(f"  筛选漏斗:")
            for k, v in filter_stats.items():
                if isinstance(v, list) and k == "final_codes_sample":
                    log(f"    {k}:")
                    for rec in v:
                        log(f"      {rec}")
                else:
                    log(f"    {k}: {v}")

        if not candidates_codes:
            log("  ⚠️  没有候选股可研究，跳过")
            return {"status": "skipped", "count": 0}

        # 构建 code → 筛选元信息 映射（把 _revenue_yi _audit_opinion 等挂到最终报告里）
        info_stocks_for_lookup = get_cache("info_collection_stocks") or []
        info_by_code = {s.get("code"): s for s in info_stocks_for_lookup if s.get("code")}
        screening_by_code = {}
        if info_by_code:
            for code in candidates_codes:
                s = info_by_code.get(code)
                if not s:
                    continue
                screening_by_code[code] = {
                    "sector_heat_score": s.get("sector_heat_score"),
                    "sector_decision": s.get("sector_decision"),
                    "industry_level2": s.get("industry_level2"),
                    "market_cap_yi": round(int(s.get("market_cap", 0) or 0) / 1e8, 2),
                    "revenue_yi": s.get("_revenue_yi"),
                    "profit_lower_yi": s.get("_profit_lower_yi"),
                    "st_name_check": "pass",
                    "audit_opinion": s.get("_audit_opinion"),
                    "audit_status": "pass" if s.get("_audit_ok") else ("unavailable" if s.get("_audit_note") else "fail"),
                    "fin_status": "fetched" if s.get("_fin_fetched") else ("unavailable" if s.get("_fin_note") else "unknown"),
                }

        analyzer = StockAnalyzer()
        reports = []
        log(f"  将对 {len(candidates_codes)} 只候选股进行深度研究 (StockAnalyzer.analyze)...")
        for i, code in enumerate(candidates_codes):
            try:
                log(f"    [{i+1}/{len(candidates_codes)}] {code}")
                rep = analyzer.analyze(code, show_progress=False)
                rep["symbol"] = code
                rep["name"] = rep.get("stock_name") or rep.get("name") or code
                # v3.2 附加：筛选摘要（供 ⓪人工审查②复核）
                if code in screening_by_code:
                    rep["screening_summary"] = screening_by_code[code]
                reports.append(rep)
            except Exception as e:
                log(f"    ⚠️  {code} 研究失败: {e}")
                rep = {"symbol": code, "name": code, "error": str(e)}
                if code in screening_by_code:
                    rep["screening_summary"] = screening_by_code[code]
                reports.append(rep)

        out = RESEARCH_DIR / "research_reports.json"
        payload = {
            "timestamp": _now_iso(),
            "stage": "4_company_research",
            "count": len(reports),
            "filter_stats": filter_stats,   # v3.2 筛选漏斗（Step0~4 各步数量）
            "filter_rule_version": "v3.2",  # 板块热度≥55 + ST + 市值≥50亿 + 财务 + 审计
            "reports": reports,
        }
        out.write_text(_dumps(payload, indent=2), encoding="utf-8")
        log(f"  ✅ 研究报告已保存: {out} (共{len(reports)}份)")

        set_cache("research_reports", reports)

        state = _read_state()
        state["company_research"] = {
            "status": "completed",
            "count": len(reports),
            "codes": [r["symbol"] for r in reports],
            "filter_stats": filter_stats,
            "filter_rule_version": "v3.2",
        }
        _write_state(state)
        return {"status": "completed", "count": len(reports), "filter_stats": filter_stats}

    except Exception as e:
        log(f"④ 公司研究失败: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# ─── ⓪ 人工审查② (④ 之后) ─────────────────────────────────────────────────
def run_manual_review_research() -> dict[str, Any]:
    """人工审查②: 确认候选池（哪些股票进入 ⑤ 打分环节）"""
    log("=" * 58)
    log("⓪ 人工审查② → 候选池确认")
    log("=" * 58)
    reports = get_cache("research_reports") or []
    if not reports:
        info = RESEARCH_DIR / "research_reports.json"
        if info.exists():
            reports = json.loads(info.read_text(encoding="utf-8")).get("reports", [])
    if not reports:
        log("  ⚠️  ④ 无研究报告，跳过")
        return {"status": "skipped", "approved": True, "codes": []}

    log(f"  候选池 {len(reports)} 只：")
    for i, r in enumerate(reports[:10]):
        log(f"    [{i}] {r.get('name','')}({r.get('symbol','')}) "
            f"error={'有' if r.get('error') else '无'}")
    if len(reports) > 10:
        log(f"    ... (剩余 {len(reports) - 10} 只)")

    approved = _review_prompt(
        "确认以上候选池进入 ⑤ 因子打分环节",
    )
    state = _read_state()
    state["manual_review_2"] = {
        "status": "approved" if approved else "rejected",
        "timestamp": _now_iso(),
        "codes": [r.get("symbol", "") for r in reports],
    }
    _write_state(state)
    log(f"  审查结果: {'✅ 通过' if approved else '❌ 退回'}")
    return {"status": "approved" if approved else "rejected", "approved": approved,
            "codes": [r.get("symbol", "") for r in reports]}


# ─── ⑤ 因子打分辅助：板块配额分配 Top10 ──────────────────────────────────────
_last_top10_allocation_info: dict = {}   # 模块级，给 run_factor_scoring_stage 写 JSON 时引用


def _load_market_data_for_sector_heat() -> dict:
    """读 market_data.json，返回 {code: (industry_level2, sector_heat_score)}"""
    md_path = INFO_DIR / "market_data.json"
    if not md_path.exists():
        return {}
    try:
        data = json.loads(md_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    stocks = data.get("stocks", data) if isinstance(data, dict) else data
    out = {}
    for s in stocks:
        code = str(s.get("code", ""))
        sec = s.get("industry_level2") or s.get("industry") or "未知"
        heat = float(s.get("sector_heat_score", 0) or 0)
        out[code] = (sec, heat)
    return out


def _allocate_top10_by_sector(all_scored: list) -> list:
    """按「热度排名板块 → 配额」分配 Top10

    规则：
      热度第1板块 → 4 只（按分数降序）
      热度第2板块 → 3 只
      热度第3板块 → 2 只
      剩余名额 1 只 → 全池最高分黑马（可以是已入选板块的，也可以是其他板块的）

    如某板块不足配额数 → 剩余名额滚到后面的配额池（按热度降序）。
    如板块数不足 3 → 配额自动按剩余板块数重新切分（4/3/2 的权重比例）。

    Args:
        all_scored: screener 已排好序的全池结果（带 total_score / code）
    Returns:
        top10_results: 入选的 10 只（已按分数降序）
    """
    global _last_top10_allocation_info
    _last_top10_allocation_info = {}

    # 1. 给每个 result 附上 (sector, heat)
    md_map = _load_market_data_for_sector_heat()
    enriched = []
    for r in all_scored:
        code = str(r.get("code", _sym(r) or ""))
        sec, heat = md_map.get(code, ("未知", 0.0))
        enriched.append({**r, "_sector": sec, "_heat": heat})

    # 2. 按板块热度分组
    from collections import OrderedDict
    sec_heat_map: dict[str, float] = {}
    sec_stocks: dict[str, list] = {}
    for r in enriched:
        sec = r["_sector"]
        heat = r["_heat"]
        # 板块热度 = 板块内股票的最大热度
        sec_heat_map[sec] = max(sec_heat_map.get(sec, 0.0), heat)
        sec_stocks.setdefault(sec, []).append(r)

    # 板块内按分数降序
    for sec in sec_stocks:
        sec_stocks[sec].sort(key=lambda x: x.get("total_score", 0), reverse=True)

    # 板块按热度降序
    secs_sorted = sorted(sec_heat_map.keys(), key=lambda s: sec_heat_map[s], reverse=True)

    # 3. 分配配额（热度1→4, 2→3, 3→2，共 9；最后 1 个黑马）
    quota_template = [4, 3, 2]
    total_quota = 9
    if len(secs_sorted) < 3:
        # 板块不够，按比例重分配（4:3:2 的权重 → 等比缩放）
        weights = [4, 3, 2][:len(secs_sorted)]
        total_w = sum(weights)
        quotas = [max(1, round(w * total_quota / total_w)) for w in weights]
        # 修正偏差
        while sum(quotas) != total_quota:
            quotas[0] += 1 if sum(quotas) < total_quota else -1
    else:
        quotas = quota_template

    selected: list = []
    selected_codes: set = set()
    allocation_trace: list = []

    for i, sec in enumerate(secs_sorted[:len(quotas)]):
        q = quotas[i]
        candidates = sec_stocks.get(sec, [])
        picks = [s for s in candidates if s.get("code") not in selected_codes][:q]
        for s in picks:
            selected_codes.add(s.get("code"))
        allocation_trace.append({
            "rank": i + 1,
            "sector": sec,
            "heat": sec_heat_map[sec],
            "quota": q,
            "actual": len(picks),
            "codes": [s.get("code") for s in picks],
        })
        selected.extend(picks)

    # 配额没填满的名额 → 依次往热度降序的板块候选池里挑（已入选的跳过）
    if len(selected) < total_quota:
        for sec in secs_sorted:
            for s in sec_stocks.get(sec, []):
                if len(selected) >= total_quota:
                    break
                if s.get("code") not in selected_codes:
                    selected_codes.add(s.get("code"))
                    selected.append(s)
            if len(selected) >= total_quota:
                break

    # 4. 黑马名额（第 10 个）：全池最高分且不在已入选里的
    wildcard = None
    for s in sorted(enriched, key=lambda x: x.get("total_score", 0), reverse=True):
        if s.get("code") not in selected_codes:
            wildcard = s
            break
    if wildcard:
        selected.append(wildcard)
        allocation_trace.append({
            "rank": 10,
            "sector": wildcard["_sector"],
            "heat": wildcard["_heat"],
            "quota": "wildcard",
            "actual": 1,
            "codes": [wildcard.get("code")],
            "note": "全池最高分黑马",
        })

    # 5. 最终按分数降序
    selected.sort(key=lambda x: x.get("total_score", 0), reverse=True)

    # 写日志
    log("  📋 Top10 板块配额分配：")
    for t in allocation_trace:
        codes_str = ", ".join(t["codes"][:5]) + (" ..." if len(t["codes"]) > 5 else "")
        log(f"    热度{t['rank']} ({t['sector']} 热度{t['heat']}): 配额{t['quota']} → {t['actual']} 只 [{codes_str}]")

    _last_top10_allocation_info = {
        "allocation_rule": "热度1st→4 + 热度2nd→3 + 热度3rd→2 + 黑马→1",
        "allocation_trace": allocation_trace,
        "sectors_sorted_by_heat": [(s, sec_heat_map[s]) for s in secs_sorted],
    }
    return selected


# ─── ⑤ 因子打分 ──────────────────────────────────────────────────────────────
def run_factor_scoring_stage(top_n: int = 10, mode: str = "all",
                              scoring_pool_codes: list = None) -> dict[str, Any]:
    """环节⑤ 因子打分（自动） — 复用 StockScreener.run_screening
    【评分体系 v6.0】基本面40 + 趋势动量20 + 量价筹码15 + 资金面行为25 = 100
    【v3.2 打分范围】优先使用④公司研究筛选出的 50 只（scoring_pool_codes），
        仅对它们做打分排名，而不是全市场重新跑。
    【v3.2 短板否决】打分后做「维度短板一票否决」：任一维度 < 该维度满分的 30% 即剔除。
    【输出】output/factor-scoring/top10_stocks.json
    """
    log("=" * 58)
    log(f"⑤ 因子打分 (基本面40+趋势20+量价筹码15+资金面25, Top{top_n})")
    log("=" * 58)

    # 【v3.2】打分范围：优先 scoring_pool_codes → ④研究报告 codes → 否则全市场
    resolved_codes: list = list(scoring_pool_codes) if scoring_pool_codes else []
    source_note = ""
    if scoring_pool_codes:
        source_note = f"（来源: 显式传参, {len(resolved_codes)} 只）"

    if not resolved_codes:
        state = _read_state()
        # 1. 从 cache 拿④ research_reports
        research = get_cache("research_reports") or []
        # 2. cache 没有则读 output 文件
        if not research:
            reports_path = RESEARCH_DIR / "research_reports.json"
            if reports_path.exists():
                try:
                    payload = json.loads(reports_path.read_text(encoding="utf-8"))
                    research = payload.get("reports", [])
                except Exception:
                    research = []
        if research:
            resolved_codes = [r.get("symbol") or r.get("code") for r in research
                              if (r.get("symbol") or r.get("code")) and not r.get("error")]
            source_note = f"（来源: ④公司研究输出, {len(resolved_codes)} 只）"
        # 3. 还没有，从 state.company_research.codes 兜底
        if not resolved_codes:
            state_codes = state.get("company_research", {}).get("codes", [])
            if state_codes:
                resolved_codes = [c for c in state_codes if c]
                source_note = f"（来源: state.company_research.codes, {len(resolved_codes)} 只）"

    # 打分层级规则：
    #   有 resolved_codes（④已筛 50 只候选池）→ 全池打分 + 板块配额分配 Top10
    #   无 resolved_codes（全市场回退）→ 直接 Top10
    pool_mode = bool(resolved_codes)
    strict_filter = False if pool_mode else None

    if pool_mode:
        log(f"  限定打分池模式：仅对 {len(resolved_codes)} 只股票评分排名 {source_note}")
        log(f"  📐 Top10 分配规则：热度1st→4 + 热度2nd→3 + 热度3rd→2 + 全池最高分黑马→1")
    else:
        log("  ⚠️  未找到④公司研究候选池，回退到全市场打分模式（旧行为）")

    # 1) 先让 screener 打满整个池（min_score=0 避免误淘汰，top_n=池规模全保留）
    pool_size = len(resolved_codes) if pool_mode else top_n
    stage = run_screening_stage(mode=mode, top_n=pool_size,
                                 scoring_pool_codes=resolved_codes or None,
                                 strict_filter=strict_filter,
                                 min_score=0 if pool_mode else None)
    if stage.get("status") != "completed":
        return stage

    all_results = stage.get("data", [])
    # 限定池校验：返回结果必须是候选池的子集
    if pool_mode:
        code_set = set(str(c) for c in resolved_codes)
        all_results = [r for r in all_results
                       if str(_sym(r) or "") in code_set or str(r.get("code") or "") in code_set]
        log(f"  📊 全池打分完成: {len(all_results)}/{pool_size} 只有效分")

    # 2) 分配 Top10
    if pool_mode and len(all_results) >= 10:
        results = _allocate_top10_by_sector(all_results)
    else:
        all_results.sort(key=lambda r: r.get("total_score", 0), reverse=True)
        results = all_results[:top_n]
        if pool_mode:
            log(f"  ⚠️  有效分 < 10，直接按分数取前 {len(results)}")

    # 3) 保存 + 状态
    src = SCREENING_DIR / "top10_stocks.json"
    dst = SCORING_DIR / "top10_stocks.json"
    if src.exists():
        try:
            raw = json.loads(src.read_text(encoding="utf-8"))
        except Exception:
            raw = {"timestamp": _now_iso(), "results": all_results}
        raw["scoring_pool"] = {
            "source": "④ 公司研究" if pool_mode else "全市场回退",
            "codes": resolved_codes if pool_mode else [],
            "strict_filter": stage.get("strict_filter"),
            "pre_filter_stats": stage.get("pre_filter_stats", {}),
        }
        # 保存全池打分 + 最终入选（带配额说明）
        raw["all_scored_results"] = all_results
        raw["results"] = results
        if pool_mode:
            raw["top10_allocation"] = _last_top10_allocation_info  # 由 _allocate_top10_by_sector 写入
        dst.write_text(_dumps(raw, indent=2), encoding="utf-8")
        log(f"  ✅ 打分榜单已保存: {dst}")

    set_cache("scoring_topn", [_sym(r) for r in results])

    state_write = _read_state()
    state_write["factor_scoring"] = {
        "status": "completed",
        "count": len(results),
        "topn_codes": [_sym(r) for r in results],
        "scoring_pool_source": "④公司研究" if pool_mode else "全市场回退",
        "scoring_pool_codes": resolved_codes if pool_mode else [],
        "strict_filter": stage.get("strict_filter"),
        "pre_filter_stats": stage.get("pre_filter_stats", {}),
    }
    _write_state(state_write)
    return {"status": "completed", "count": len(results), "results": results,
            "scoring_pool_source": state_write["factor_scoring"]["scoring_pool_source"],
            "scoring_pool_codes": state_write["factor_scoring"]["scoring_pool_codes"]}


# ─── ⑥ 组合构建 ──────────────────────────────────────────────────────────────
def run_portfolio_stage() -> dict[str, Any]:
    """环节⑥ 组合构建（自动） — 基于 ⑤ 因子打分 Top10 做凯利仓位
    【硬约束】H6 半凯利 kelly_scaling=0.5, 单票 10%, 组合 80%
    【输出】output/portfolio-construction/portfolio.json
    """
    log("=" * 58)
    log("⑥ 组合构建 (半凯利 kelly_scaling=0.5, 单票≤10%, 组合≤80%)")
    log("=" * 58)

    # 从 ⑤ 因子打分拿 Top10（新流水线主路径），兜底老 confirmation（旧流水线回退）
    state = _read_state()
    topn_codes = (state.get("factor_scoring", {}) or {}).get("topn_codes") or []
    if not topn_codes:
        confirmed = state.get("confirmation", {}).get("data", [])
        topn_codes = [_sym(s) for s in confirmed if _sym(s)]
    if not topn_codes:
        log("  ⚠️  无候选股（⑤因子打分或旧确认均不可用），跳过凯利")
        return {"status": "skipped", "count": 0}

    log(f"  📥 从 ⑤ 因子打分拿 {len(topn_codes)} 只 Top 候选，计算凯利仓位")

    # 直接跑凯利分析（不复用 run_kelly_stage 的旧 confirmation 依赖）
    try:
        from src.kelly.stock_kelly_analyzer import StockKellyAnalyzer
        analyzer = StockKellyAnalyzer()
    except Exception as e:
        log(f"  ❌ StockKellyAnalyzer 加载失败: {e}")
        return {"status": "error", "count": 0}

    SINGLE_MAX = 0.10      # H9 单票上限
    PORTFOLIO_MAX = 0.80   # H9 组合上限

    positions = []
    truncated_count = 0
    for sym in topn_codes:
        try:
            result = analyzer.analyze(sym, silent=True)
            result["symbol"] = sym
            result["name"] = result.get("basic_info", {}).get("name", sym)
            result["current_price"] = result.get("market", {}).get("current_price", 0)

            kelly_info = result.get("kelly", {})
            raw_suggested = float(kelly_info.get("suggested_fraction", 0) or 0)
            truncated = min(raw_suggested, SINGLE_MAX)
            was_truncated = raw_suggested > SINGLE_MAX
            if was_truncated:
                truncated_count += 1
                kelly_info["suggested_fraction_original"] = raw_suggested
                kelly_info["suggested_fraction"] = truncated
                kelly_info["truncated_to_single_max"] = True
                kelly_info["truncation_reason"] = f"raw={raw_suggested:.4f} > single_max={SINGLE_MAX}"
                # 同步修正 suggested_amount
                capital = 1_000_000
                if raw_suggested > 0:
                    kelly_info["suggested_amount"] = round(truncated * capital, 2)
                log(f"  ✅ {sym} {result.get('name','')}  凯利={raw_suggested:.2%}  ⚠️ 截断→{truncated:.2%} (单票≤10%)")
            else:
                log(f"  ✅ {sym} {result.get('name','')}  凯利仓位={truncated:.2%}")

            result["kelly_fraction"] = truncated
            positions.append(result)
        except Exception as e:
            log(f"  ⚠️  {sym} 凯利失败: {e}")

    # 二次校验：如果截断后总仓位仍 > PORTFOLIO_MAX，按比例等比缩放到 80%
    total_after_cap = sum(float(p.get("kelly", {}).get("suggested_fraction", 0) or 0) for p in positions)
    if total_after_cap > PORTFOLIO_MAX and positions:
        scale = PORTFOLIO_MAX / total_after_cap
        log(f"  ⚠️  截断单票后总仓位={total_after_cap:.1%} > 80%，按比例缩放 {scale:.2f}x")
        for p in positions:
            kelly_info = p.get("kelly", {})
            orig = float(kelly_info.get("suggested_fraction", 0) or 0)
            scaled = round(orig * scale, 4)
            kelly_info["suggested_fraction_original_before_portfolio_cap"] = orig
            kelly_info["suggested_fraction"] = scaled
            p["kelly_fraction"] = scaled
        total_after_portfolio_cap = sum(float(p.get("kelly", {}).get("suggested_fraction", 0) or 0) for p in positions)
        log(f"  ✅ 按比例缩放后总仓位={total_after_portfolio_cap:.1%} ≤ 80%")

    total_final = sum(float(p.get("kelly", {}).get("suggested_fraction", 0) or 0) for p in positions)
    if truncated_count > 0:
        log(f"  📐 单票截断 {truncated_count} 只，最终总仓位 {total_final:.1%}")
    else:
        log(f"  📐 全部满足单票≤10%，最终总仓位 {total_final:.1%}")

    # 保存 portfolio.json
    kelly_files = list(KELLY_DIR.glob("*.json"))
    portfolio_payload = {
        "timestamp": _now_iso(),
        "stage": "6_portfolio_construction",
        "source": "⑤ 因子打分 Top10",
        "kelly_scaling": 0.5,
        "single_max_fraction": SINGLE_MAX,
        "portfolio_max_total_pct": PORTFOLIO_MAX,
        "topn_codes": topn_codes,
        "positions": positions,
        "_h9_applied": True,
        "_h9_truncated_count": truncated_count,
        "_legacy_outputs": [str(f.relative_to(PROJECT_ROOT)) for f in kelly_files],
    }
    dst = PORTFOLIO_DIR / "portfolio.json"
    dst.write_text(_dumps(portfolio_payload, indent=2), encoding="utf-8")
    log(f"  ✅ 持仓方案已保存: {dst} ({len(positions)} 个标的)")

    state["portfolio_construction"] = {
        "status": "completed",
        "count": len(positions),
        "topn_codes": topn_codes,
    }
    _write_state(state)
    return {"status": "completed", "count": len(positions), "positions": positions}


# ─── ⓪ 人工审查③ (⑥ 之后) ─────────────────────────────────────────────────
def run_manual_review_portfolio() -> dict[str, Any]:
    """人工审查③: 持仓方案+凯利仓位（H9 用户改仓位后要重新校验风控红线）"""
    log("=" * 58)
    log("⓪ 人工审查③ → 组合审查 (凯利仓位)")
    log("=" * 58)
    portfolio_file = PORTFOLIO_DIR / "portfolio.json"
    if not portfolio_file.exists():
        log("  ⚠️  ⑥ 未生成组合，跳过")
        return {"status": "skipped", "approved": True}

    d = json.loads(portfolio_file.read_text(encoding="utf-8"))
    positions = d.get("positions", [])
    total = sum(float(p.get("fraction", p.get("pct", 0)) or 0) for p in positions)
    log(f"  总仓位: {total:.2%}  | 标的数: {len(positions)}")
    for i, p in enumerate(positions[:10]):
        frac = float(p.get("fraction", p.get("pct", 0)) or 0)
        log(f"    [{i}] {p.get('name','')}({p.get('symbol', p.get('code',''))})  "
            f"仓位={frac:.2%}")

    # H9 校验：单票 ≤10%，总 ≤80%
    max_single = max(
        (float(p.get("fraction", p.get("pct", 0)) or 0) for p in positions), default=0
    )
    h9_ok = max_single <= 0.10 and total <= 0.80
    if not h9_ok:
        log(f"  ⚠️  【H9 触发】单票最高={max_single:.2%}(>10% 或 总仓位={total:.2%}>80%), "
            f"不通过，请回到 ⑥ 调整")
        approved = False
    else:
        approved = _review_prompt(
            "请审查以上凯利仓位方案（不突破信仰手册红线）",
        )

    state = _read_state()
    state["manual_review_3"] = {
        "status": "approved" if approved else "rejected",
        "timestamp": _now_iso(),
        "total_pct": total,
        "h9_ok": h9_ok,
    }
    _write_state(state)
    log(f"  审查结果: {'✅ 通过' if approved else '❌ 退回'}")
    return {"status": "approved" if approved else "rejected", "approved": approved}


# ─── ⑦ 回测校验 ──────────────────────────────────────────────────────────────
# 复用旧 run_backtest_stage，输出目录一致 output/backtest/
def run_backtest_stage_new(start_date: str = "", end_date: str = "",
                           rebalance: str = "monthly", top_n: int = 5,
                           initial_capital: float = 1_000_000.0) -> dict[str, Any]:
    """环节⑦ 回测校验（自动） — 复用 BacktestRunner
    【输出】output/backtest/ 下 equity_curve.csv / metrics.json / trade_log.csv
    """
    log("=" * 58)
    log("⑦ 回测校验 (宽池 Proxy 策略)")
    log("=" * 58)
    return run_backtest_stage(
        start_date=start_date, end_date=end_date,
        rebalance=rebalance, top_n=top_n, initial_capital=initial_capital,
    )


# ─── ⑧ 风险检查 ──────────────────────────────────────────────────────────────
def run_risk_check_stage() -> dict[str, Any]:
    """环节⑧ 风险检查（自动） — 基于⑦回测结果 + ⑥组合持仓，对照信仰手册红线
    【待建】src/risk/checker.py，当前临时用回测 metrics + H11~H13 规则生成报告
    【输出】output/risk-check/risk_report.json
    """
    log("=" * 58)
    log("⑧ 风险检查 (对照信仰手册 1.2 节风险红线)")
    log("=" * 58)

    bt_metrics_path = BACKTEST_DIR / "metrics.json"
    portfolio_path = PORTFOLIO_DIR / "portfolio.json"

    bt_metrics = {}
    if bt_metrics_path.exists():
        bt_metrics = json.loads(bt_metrics_path.read_text(encoding="utf-8"))

    positions = []
    total_pct = 0.0
    if portfolio_path.exists():
        pd = json.loads(portfolio_path.read_text(encoding="utf-8"))
        positions = pd.get("positions", [])
        total_pct = sum(float(p.get("fraction", p.get("pct", 0)) or 0) for p in positions)

    mdd = float(bt_metrics.get("max_drawdown", 0) or 0)
    total_ret = float(bt_metrics.get("total_return", 0) or 0)
    sharpe = float(bt_metrics.get("sharpe", 0) or 0)
    win_rate = float(bt_metrics.get("win_rate", 0) or 0)
    n_trades = int(bt_metrics.get("n_trades", 0) or 0)

    checks = [
        # (ID, 检查项, 是否通过, 说明)
        ("H6",  "凯利仓位使用半凯利 (kelly_scaling=0.5)", True,
         "默认值"),
        ("H9a", f"单票最大仓位 ≤ 10%",
         all(float(p.get("fraction", p.get("pct", 0)) or 0) <= 0.10 for p in positions) or not positions,
         f"实际 {max((float(p.get('fraction', p.get('pct', 0)) or 0) for p in positions), default=0):.2%}"),
        ("H9b", f"组合总仓位 ≤ 80%", total_pct <= 0.80, f"实际 {total_pct:.2%}"),
        ("H11", "最大持仓天数 ≤ 3 交易日 (T+3 强平规则)", True,
         "由 monitor.py run_once 强平执行"),
        ("H12", "日最大亏损容忍 2% 暂停当日交易", True,
         "运行时风控"),
        ("H13a", f"组合预警线: 回撤达 3% 减半", mdd < 0.03,
         f"实际最大回撤 {mdd:.2%}{'  ⚠️ 已触发预警' if mdd >= 0.03 else ''}"),
        ("H13b", f"组合熔断线: 回撤达 5% 停止买入", mdd < 0.05,
         f"实际最大回撤 {mdd:.2%}{'  ⚠️ 已触发熔断' if mdd >= 0.05 else ''}"),
    ]
    failed = [c for c in checks if not c[2]]

    risk_report = {
        "timestamp": _now_iso(),
        "stage": "8_risk_check",
        "backtest_summary": {
            "total_return": total_ret,
            "max_drawdown": mdd,
            "sharpe": sharpe,
            "win_rate": win_rate,
            "n_trades": n_trades,
        },
        "portfolio_summary": {
            "position_count": len(positions),
            "total_pct": total_pct,
        },
        "checks": [
            {"id": c[0], "name": c[1], "passed": c[2], "detail": c[3]} for c in checks
        ],
        "all_passed": len(failed) == 0,
        "failed_count": len(failed),
        "failed_ids": [c[0] for c in failed],
    }
    out = RISK_DIR / "risk_report.json"
    out.write_text(_dumps(risk_report, indent=2), encoding="utf-8")

    log(f"  共 {len(checks)} 项检查, 通过 {len(checks) - len(failed)}, 失败 {len(failed)}")
    for c in checks:
        tag = "✅" if c[2] else "❌"
        log(f"    {tag} [{c[0]}] {c[1]} — {c[3]}")
    log(f"  ✅ 风控报告已保存: {out}")

    state = _read_state()
    state["risk_check"] = {
        "status": "completed" if len(failed) == 0 else "warning",
        "all_passed": len(failed) == 0,
        "failed_count": len(failed),
    }
    _write_state(state)
    return risk_report


# ─── ⓪ 人工审查④ (⑧ 之后) ─────────────────────────────────────────────────
def run_manual_review_risk() -> dict[str, Any]:
    """人工审查④: 风控放行/退回（H10 风控红线不得临时豁免）"""
    log("=" * 58)
    log("⓪ 人工审查④ → 风控放行")
    log("=" * 58)
    risk_path = RISK_DIR / "risk_report.json"
    if not risk_path.exists():
        log("  ⚠️  ⑧ 未生成风控报告，跳过")
        return {"status": "skipped", "approved": True}

    rr = json.loads(risk_path.read_text(encoding="utf-8"))
    all_ok = rr.get("all_passed", False)
    failed = rr.get("failed_ids", [])

    log(f"  检查结果: {'✅ 全部通过' if all_ok else '⚠️  有 ' + str(len(failed)) + ' 项未通过: ' + str(failed)}")

    # H10 硬约束: 风控红线不得临时豁免
    # 若 H13/H9/H6 红线类失败，直接自动退回，不询问用户
    red_line_fail = [x for x in failed if x in ("H9a", "H9b", "H6", "H13b")]
    if red_line_fail:
        log(f"  ❌ 【H10 触发】红线 {red_line_fail} 失败，风控一票否决 — 强制退回 ⑥ 组合构建")
        approved = False
    else:
        approved = _review_prompt(
            "请审查风控报告并决定: [Enter] 放行进入 ⑨ 调仓执行 / 其他字符 退回 ⑥ 组合构建",
        )

    state = _read_state()
    state["manual_review_4"] = {
        "status": "approved" if approved else "rejected",
        "timestamp": _now_iso(),
        "red_line_fail": red_line_fail,
    }
    _write_state(state)
    log(f"  审查结果: {'✅ 放行' if approved else '❌ 退回'}")
    return {"status": "approved" if approved else "rejected", "approved": approved}


# ─── ⑨ 调仓执行 ──────────────────────────────────────────────────────────────
def run_rebalance_stage(duration: int = 10) -> dict[str, Any]:
    """环节⑨ 调仓执行（自动） — 复用 StockAlert.run_once (smart_mode=True)
    【输出】output/rebalance-execution/orders.json, alerts.json
    """
    log("=" * 58)
    log(f"⑨ 调仓执行 (StockAlert smart_mode=True, 监控 {duration}s)")
    log("=" * 58)
    # 复用旧 run_monitor_stage，但输出搬到新目录
    stage = run_monitor_stage(duration=duration)

    # 旧 monitor 输出文件可能在 MONITOR_DIR，把它们 copy 到 REBALANCE_DIR
    orders_out = REBALANCE_DIR / "orders.json"
    alerts_out = REBALANCE_DIR / "alerts.json"
    if not orders_out.exists():
        sample_orders = {
            "timestamp": _now_iso(),
            "stage": "9_rebalance_execution",
            "monitor_status": stage.get("status"),
            "monitor_message": stage.get("message"),
            "orders": [],   # 短线组合通常 T+1 卖出，当日无成交
        }
        orders_out.write_text(_dumps(sample_orders, indent=2), encoding="utf-8")
    if not alerts_out.exists():
        alerts_out.write_text(_dumps({
            "timestamp": _now_iso(),
            "alerts": [],
        }, indent=2), encoding="utf-8")

    log(f"  ✅ 调仓输出: {orders_out}  {alerts_out}")

    state = _read_state()
    state["rebalance_execution"] = {"status": "completed"}
    _write_state(state)
    return stage


# ─── ⑩ 归因复盘 ──────────────────────────────────────────────────────────────
def run_attribution_stage() -> dict[str, Any]:
    """环节⑩ 归因复盘（自动） — 聚合 ⑦⑧⑨ 的输出生成复盘日志
    【待建】src/attribution/review.py，当前根据回测 metrics + 风险检查报告合成
    【输出】output/attribution-review/review_log.md
    """
    log("=" * 58)
    log("⑩ 归因复盘 (资金曲线 + 风险检查 → 复盘日志)")
    log("=" * 58)

    bt_metrics = {}
    if (BACKTEST_DIR / "metrics.json").exists():
        bt_metrics = json.loads((BACKTEST_DIR / "metrics.json").read_text(encoding="utf-8"))
    risk_r = {}
    if (RISK_DIR / "risk_report.json").exists():
        risk_r = json.loads((RISK_DIR / "risk_report.json").read_text(encoding="utf-8"))
    portfolio = {}
    if (PORTFOLIO_DIR / "portfolio.json").exists():
        portfolio = json.loads((PORTFOLIO_DIR / "portfolio.json").read_text(encoding="utf-8"))

    total_ret = float(bt_metrics.get("total_return", 0) or 0)
    annual_ret = float(bt_metrics.get("annual_return", 0) or 0)
    mdd = float(bt_metrics.get("max_drawdown", 0) or 0)
    sharpe = float(bt_metrics.get("sharpe", 0) or 0)
    win_rate = float(bt_metrics.get("win_rate", 0) or 0)
    n_trades = int(bt_metrics.get("n_trades", 0) or 0)
    checks = risk_r.get("checks", [])
    failed = [c["id"] for c in checks if not c["passed"]]

    lines = []
    lines.append("# TransAlpha 归因复盘日志\n")
    lines.append(f"生成时间: {_now_iso()}\n")

    lines.append("## 1. 绩效概览\n")
    lines.append(f"- 累计收益率: **{total_ret:.2%}**")
    lines.append(f"- 年化收益率: {annual_ret:.2%}")
    lines.append(f"- 最大回撤: {mdd:.2%}")
    lines.append(f"- 夏普比率: {sharpe:.2f}")
    lines.append(f"- 胜率: {win_rate:.2%} ({n_trades} 笔交易)\n")

    lines.append("## 2. 风控执行\n")
    if failed:
        lines.append(f"- 未通过规则: **{failed}**\n")
    else:
        lines.append("- 所有风控检查 ✅ 通过\n")
    for c in checks:
        tag = "✅" if c["passed"] else "❌"
        lines.append(f"- {tag} [{c['id']}] {c['name']} — {c['detail']}")
    lines.append("")

    lines.append("## 3. 方法论改进建议 (自动生成, 仅供参考)\n")
    suggestions = []
    if sharpe < 1.0:
        suggestions.append("- [夏普<1] 建议降低仓位或增加行业分散度，降低波动")
    if mdd > 0.05:
        suggestions.append("- [回撤>5%] 建议强化 H13 熔断：实际应考虑 4% 提前止损")
    if win_rate and win_rate < 0.45:
        suggestions.append("- [胜率<45%] 建议收紧 ⑤ 因子打分阈值，提高入场质量")
    if total_ret < 0:
        suggestions.append("- [负收益] 建议回到 ② 赛道景气度打分表 重选景气赛道")
    if not suggestions:
        suggestions.append("- 本轮表现良好，维持现有策略参数不变")
    for s in suggestions:
        lines.append(s)
    lines.append("")

    lines.append("## 4. 下轮闭环回流 (→ 投资信仰手册 + 赛道景气度表)\n")
    lines.append("- 以上建议写入 TransAlpha小组投资信仰手册.md 对应章节")
    lines.append("- 赛道建议回流至 TransAlpha赛道景气度打分表.md\n")

    out = ATTRIBUTION_DIR / "review_log.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    log(f"  ✅ 复盘日志已保存: {out}")

    state = _read_state()
    state["attribution_review"] = {"status": "completed"}
    _write_state(state)
    return {"status": "completed", "review_log": str(out)}


# ─── 新流水线编排 (12 步: 8 自动 + 4 暂停) ──────────────────────────────────
NEW_STAGE_MAP = {
    # 步骤号: (步骤名, 执行函数, 自动/暂停)
    1:  ("③ 信息收集",                   run_info_collection_stage, "auto"),
    2:  ("⓪ 人工审查① (数据质量)",        run_manual_review_data,   "pause"),
    3:  ("④ 公司研究",                   run_company_research_stage, "auto"),
    4:  ("⓪ 人工审查② (候选池)",          run_manual_review_research, "pause"),
    5:  ("⑤ 因子打分",                   run_factor_scoring_stage, "auto"),
    6:  ("⑥ 组合构建",                   run_portfolio_stage,      "auto"),
    7:  ("⓪ 人工审查③ (凯利仓位)",        run_manual_review_portfolio, "pause"),
    8:  ("⑦ 回测校验",                   run_backtest_stage_new,   "auto"),
    9:  ("⑧ 风险检查",                   run_risk_check_stage,     "auto"),
    10: ("⓪ 人工审查④ (风控放行)",        run_manual_review_risk,   "pause"),
    11: ("⑨ 调仓执行",                   run_rebalance_stage,      "auto"),
    12: ("⑩ 归因复盘",                   run_attribution_stage,    "auto"),
}


def run_pipeline_new(start_stage: int = 1, monitor_duration: int = 10,
                     top_n: int = 10, research_top_n: int = 50,
                     per_sector_quota: int = 15,
                     truncation_mode: str = "weighted") -> None:
    """按 main_auto_workflow.md 顺序执行 12 步 (8 自动环节 + 4 人工暂停点)

    Args:
        start_stage: 1~12, 对应 NEW_STAGE_MAP 的 12 步
        monitor_duration: ⑨ 调仓执行监控秒数 (默认 10s, 短测试)
        top_n: ⑤ 因子打分 Top N
        research_top_n: ④ 公司研究候选上限 (默认 50, 可根据市场热度调大到 100)
        per_sector_quota: 方案C 每板块固定配额 (默认 15)
        truncation_mode: 方案A 截断模式 (weighted / cap_first / heat_first)
    """
    log(f"\n{'=' * 60}")
    log(f"🚀 TransAlpha 工作流 (main_auto_workflow.md) 启动 (第 {start_stage} 步起)")
    log(f"{'=' * 60}")

    state = _read_state()
    state["pipeline_status"] = "running"
    state["start_time"] = _now_iso()
    state["workflow_version"] = "new_12_steps"
    _write_state(state)

    for step_num in range(start_stage, 13):
        name, func, kind = NEW_STAGE_MAP[step_num]
        log(f"\n{'─' * 58}")
        log(f"▶ [{step_num}/12] {name}  ({kind})")
        log(f"{'─' * 58}")

        try:
            if step_num == 3:    # ④ 公司研究
                result = func(research_top_n=research_top_n,
                              per_sector_quota=per_sector_quota,
                              truncation_mode=truncation_mode)
            elif step_num == 5:    # ⑤ 因子打分
                result = func(top_n=top_n)
            elif step_num == 8:  # ⑦ 回测校验
                result = func(top_n=max(5, top_n // 2))
            elif step_num == 11:  # ⑨ 调仓执行
                result = func(duration=monitor_duration)
            else:
                result = func()
        except Exception as e:
            log(f"!!! 步骤 {step_num} 抛出异常: {e}")
            traceback.print_exc()
            state = _read_state()
            state["pipeline_status"] = f"error_at_step_{step_num}"
            state["error_message"] = str(e)
            _write_state(state)
            return

        # 审查点不通过 → 回退（暂停型任务 approved=False）
        if kind == "pause" and not result.get("approved", True):
            log(f"  ⏪ 人工审查退回：流水线在步骤 {step_num} 暂停。请修复后重新从 step=1 或 {step_num-1} 运行")
            state = _read_state()
            state["pipeline_status"] = f"paused_at_review_{step_num}"
            _write_state(state)
            return

    log(f"\n{'=' * 60}")
    log("🎉 工作流全部 12 步完成 (8 环节自动 + 4 审查通过)")
    log(f"{'=' * 60}")

    state = _read_state()
    state["pipeline_status"] = "completed"
    state["end_time"] = _now_iso()
    _write_state(state)

    # 打印 8 个输出目录总览
    print("\n📁 8 个输出文件总览:")
    dirs = [
        ("③ info-collection",      INFO_DIR),
        ("④ company-research",     RESEARCH_DIR),
        ("⑤ factor-scoring",       SCORING_DIR),
        ("⑥ portfolio-construction", PORTFOLIO_DIR),
        ("⑦ backtest",             BACKTEST_DIR),
        ("⑧ risk-check",           RISK_DIR),
        ("⑨ rebalance-execution",  REBALANCE_DIR),
        ("⑩ attribution-review",   ATTRIBUTION_DIR),
    ]
    for label, d in dirs:
        files = list(d.glob("*"))
        if files:
            print(f"  output/{label.split()[-1]}/")
            for f in files:
                size = f.stat().st_size if f.exists() else 0
                print(f"    - {f.name:30s}  ({size/1024:5.1f} KB)")

    print("\n💡 提示: 可随时使用以下命令检查/重置工作流:")
    print("   python run.py --status    # 查看当前状态")
    print("   python run.py --reset     # 清空输出，重新开始")
    print("   python run.py --collect   # 单独重跑环节③")


# ═══════════════════════════════════════════════════════════════════════════
# 新旧编排兼容：重写 run_pipeline / show_status / reset_pipeline
#   指向 NEW_STAGE_MAP (不影响旧的 STAGE_MAP，供旧命令行继续使用)
# ═══════════════════════════════════════════════════════════════════════════

_OLD_RUN_PIPELINE = run_pipeline
_OLD_SHOW_STATUS  = show_status
_OLD_RESET        = reset_pipeline


def run_pipeline(start_stage: int = 1, monitor_duration: int = 10, **_) -> None:  # type: ignore[no-redef]
    """默认使用新 12 步编排 (main_auto_workflow.md)。"""
    # 将旧 STAGE_MAP 的阶段号 1~8 映射到新 12 步中对应的自动环节位置：
    #   旧 1 screening ~ 新 5 (⑤打分)
    #   旧 2 review    ~ 新 2 (审查①)
    #   旧 3 analysis  ~ 新 3 (④研究)
    #   旧 4 confirm   ~ 新 4 (审查②)
    #   旧 5 kelly     ~ 新 6 (⑥构建)
    #   旧 6 position  ~ 新 7 (审查③)
    #   旧 7 monitor   ~ 新 11 (⑨执行)
    #   旧 8 backtest  ~ 新 8 (⑦回测)
    # 如果 start_stage 在 {1,2,3,4,5,6,7,8} 范围：认为是旧阶段号，走旧编排(向后兼容)
    if start_stage <= 8 and len(sys.argv) > 1 and any(
        x in sys.argv for x in ("-m", "src.pipeline")  # python -m src.pipeline 调用
    ):
        return _OLD_RUN_PIPELINE(start_stage=start_stage, monitor_duration=monitor_duration)

    # 否则走新编排 (12 步)
    top_n = _.get("top_n", 10)
    run_pipeline_new(
        start_stage=start_stage, monitor_duration=monitor_duration,
        top_n=top_n,
        research_top_n=_.get("research_top_n", 50),
        per_sector_quota=_.get("per_sector_quota", 15),
        truncation_mode=_.get("truncation_mode", "weighted"),
    )


def show_status() -> None:  # type: ignore[no-redef]
    """扩展: 展示新 12 步状态"""
    _OLD_SHOW_STATUS()
    state = _read_state()
    print("\n【新工作流 main_auto_workflow.md 12 步状态】")
    for step_num, (name, _, kind) in NEW_STAGE_MAP.items():
        key = {
            1: "info_collection", 2: "manual_review_1",
            3: "company_research", 4: "manual_review_2",
            5: "factor_scoring",  6: "portfolio_construction",
            7: "manual_review_3", 8: "backtest", 9: "risk_check",
            10: "manual_review_4", 11: "rebalance_execution",
            12: "attribution_review",
        }[step_num]
        if key in state:
            st = state[key].get("status", "?")
        else:
            st = "not_run"
        t = "⏸" if kind == "pause" else "▶"
        print(f"  {t} [{step_num:2d}] {name:24s} → {st}")


def reset_pipeline() -> None:  # type: ignore[no-redef]
    """扩展: 同时清空新 8 个输出目录"""
    _OLD_RESET()
    for d in (INFO_DIR, RESEARCH_DIR, SCORING_DIR, PORTFOLIO_DIR,
              RISK_DIR, REBALANCE_DIR, ATTRIBUTION_DIR):
        for f in d.glob("*"):
            if f.suffix in (".json", ".csv", ".md"):
                f.unlink()
    log("已清空新 8 环节输出目录 (info-collection ... attribution-review)")


if __name__ == "__main__":
    main()
