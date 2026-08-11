#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全A股扫描数据源验证脚本
检查 4 个优化点是否生效：
  1. akshare 新浪源（stock_zh_a_spot）→ ~5538只
  2. akshare 代码名称源（stock_info_a_code_name）→ ~5539只
  3. data_fetcher.get_all_a_stocks(max_count=0) → 走四源回退链
  4. data_source_status 返回值非 hardcoded_59
  5. screener 配置 max_count=0 + pipeline 默认 mode=all
"""
import sys
import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

RESULT = {"passed": 0, "failed": 0, "details": []}

def report(ok, msg):
    if ok:
        RESULT["passed"] += 1
        RESULT["details"].append(("✅ PASS", msg))
        print(f"  ✅ PASS  {msg}")
    else:
        RESULT["failed"] += 1
        RESULT["details"].append(("❌ FAIL", msg))
        print(f"  ❌ FAIL  {msg}")

print("=" * 70)
print("🔍 全A股扫描数据源验证")
print("=" * 70)

# ============================================================
# 1. 检查 akshare 可用性
# ============================================================
print("\n[1/7] akshare 可用性")
print("-" * 50)
try:
    import akshare as ak
    report(True, f"akshare 已安装 (v{ak.__version__})")
except Exception as e:
    report(False, f"akshare 未安装: {e}")
    sys.exit(1)

# ============================================================
# 2. akshare 新浪源（stock_zh_a_spot）
# ============================================================
print("\n[2/7] akshare 新浪源 stock_zh_a_spot() （含行情，耗时较长~26s）")
print("-" * 50)
SINA_COUNT = 0
try:
    import time
    t0 = time.time()
    df = ak.stock_zh_a_spot()
    elapsed = time.time() - t0
    SINA_COUNT = len(df)
    print(f"    耗时 {elapsed:.0f}s，获取 {SINA_COUNT} 行")
    # 新浪源代码带2字母前缀（sh/sz/bj），strip 后过滤标准 A 股
    import re as _re
    pure_codes = df["代码"].astype(str).str.replace(r"^[a-zA-Z]+", "", regex=True)
    std_mask = pure_codes.str.startswith(
        ("600","601","603","605","688","000","001","002","003","300"))
    std_count = int(std_mask.sum())
    if std_count >= 4000:
        report(True, f"新浪源 {std_count} 只标准A股（≥ 4000 ✔️）")
    else:
        report(False, f"新浪源仅 {std_count} 只标准A股（< 4000）")
    # 新浪源字段（akshare v1.18）：代码/名称/最新价/涨跌额/涨跌幅/成交量/成交额
    # — 不包含 PE / 换手率 / 总市值（置 0，由后续 fetch_batch_quotes 补全）
    has_fields = all(f in df.columns for f in ["代码","名称","最新价","涨跌幅","成交量","成交额"])
    report(has_fields, "新浪源关键字段齐全（代码/名称/最新价/涨跌幅/成交量/成交额）")
except Exception as e:
    report(False, f"新浪源异常: {e}")

# ============================================================
# 3. akshare 代码名称源（stock_info_a_code_name）
# ============================================================
print("\n[3/7] akshare 代码名称源 stock_info_a_code_name() （仅代码名称）")
print("-" * 50)
CODE_COUNT = 0
try:
    df = ak.stock_info_a_code_name()
    CODE_COUNT = len(df)
    std_codes = df[df["code"].astype(str).str.startswith(
        ("600","601","603","605","688","000","001","002","003","300"))]
    std_count = len(std_codes)
    if std_count >= 4000:
        report(True, f"代码名称源 {std_count} 只标准A股（≥ 4000 ✔️）")
    else:
        report(False, f"代码名称源仅 {std_count} 只标准A股（< 4000）")
except Exception as e:
    report(False, f"代码名称源异常: {e}")

# ============================================================
# 4. data_fetcher.get_data_source_status() / akshare 回退链方法存在
# ============================================================
print("\n[4/7] data_fetcher 降级透明标记与 akshare 方法")
print("-" * 50)
try:
    from src.screener.data_fetcher import StockDataFetcher, _AKSHARE_AVAILABLE
    fetcher = StockDataFetcher()
    report(_AKSHARE_AVAILABLE, "data_fetcher._AKSHARE_AVAILABLE = True")
    report(hasattr(fetcher, "_get_all_a_stocks_akshare"),
           "存在 _get_all_a_stocks_akshare() akshare 回退方法")
    report(hasattr(fetcher, "_fetch_akshare_sina"),
           "存在 _fetch_akshare_sina() 新浪行情方法")
    report(hasattr(fetcher, "_fetch_akshare_codename"),
           "存在 _fetch_akshare_codename() 代码名称方法")
    report(hasattr(fetcher, "get_data_source_status"),
           "存在 get_data_source_status() 降级透明状态方法")
    # 调用状态检查
    status = fetcher.get_data_source_status()
    report(isinstance(status, dict) and "degraded" in status and "data_source" in status,
           f"get_data_source_status 返回结构正确：{json.dumps(status, ensure_ascii=False)}")
except Exception as e:
    report(False, f"data_fetcher 检查异常: {e}")

# ============================================================
# 5. screener 默认 max_count = 0
# ============================================================
print("\n[5/7] screener.config 默认值 max_count=0 全A股")
print("-" * 50)
try:
    from src.screener.screener import StockScreener
    s = StockScreener()
    mc = s.config.get("max_count")
    md = s.config.get("mode")
    report(mc == 0, f"screener.config['max_count'] = {mc} (期望值 0 = 不限量)")
    report(md == "all", f"screener.config['mode'] = '{md}' (期望值 'all')")
except Exception as e:
    report(False, f"screener 检查异常: {e}")

# ============================================================
# 6. pipeline 默认 mode = "all"
# ============================================================
print("\n[6/7] pipeline 默认 run_screening_stage(mode='all')")
print("-" * 50)
try:
    import inspect
    from src.pipeline import run_screening_stage
    sig = inspect.signature(run_screening_stage)
    mode_param = sig.parameters.get("mode")
    default = mode_param.default if mode_param else None
    report(default == "all",
           f"run_screening_stage 默认参数 mode='{default}' (期望值 'all'，原 'hot')")
except Exception as e:
    report(False, f"pipeline 参数签名检查异常: {e}")

# ============================================================
# 7. 端到端：调用 data_fetcher.get_all_a_stocks(max_count=0, use_cache=False)
#    → 走四源回退链，并验证 degraded=False + data_source≠hardcoded_59
# ============================================================
print("\n[7/7] 端到端：data_fetcher.get_all_a_stocks(max_count=0) 全量扫描")
print("-" * 50)
try:
    # 先清缓存，强制走 API
    cache_file = os.path.join(PROJECT_ROOT, "src", "screener", "stock_list_cache.json")
    if os.path.exists(cache_file):
        print(f"  清理旧缓存: {cache_file}")
        os.remove(cache_file)

    stocks = fetcher.get_all_a_stocks(max_count=0, use_cache=False, exclude_st=True)
    count = len(stocks)
    status = fetcher.get_data_source_status()
    print(f"  结果: {count} 只股票，数据源={status.get('data_source')}，"
          f"降级={status.get('degraded')}")

    # 核心断言 1：不是 59 只硬编码
    report(count != 59, f"返回 {count} 只 ≠ 59 硬编码 ✔️（若 ==59 表示仍静默降级）")

    # 核心断言 2：数据源不是 hardcoded_59
    ds = status.get("data_source")
    report(ds != "hardcoded_59",
           f"data_source = '{ds}' (≠ hardcoded_59 ✔️，注意: 走缓存时仍可能='pending' 也是合法非降级态)")

    # 核心断言 3：degraded = False
    report(not status.get("degraded", True),
           f"degraded = {status.get('degraded')} (应为 False ✔️)")

    # 核心断言 4：数量 ≥ 4000 只标准 A 股
    report(count >= 4000, f"{count} 只标准A股（≥ 4000 ✔️）")

    # 抽样检查
    if stocks:
        sample = stocks[0]
        has_keys = all(k in sample for k in ["code","name","industry_level2","full_code"])
        report(has_keys, f"首条样本字段完整：{json.dumps({k:sample[k] for k in ['code','name','industry_level2','pe','price']}, ensure_ascii=False)}")
except Exception as e:
    report(False, f"端到端扫描异常: {e}")
    import traceback
    traceback.print_exc()

# ============================================================
# 汇总
# ============================================================
total = RESULT["passed"] + RESULT["failed"]
rate = (RESULT["passed"] / total * 100) if total > 0 else 0
print("\n" + "=" * 70)
print(f"📊 汇总：通过 {RESULT['passed']}/{total}（{rate:.0f}%），失败 {RESULT['failed']}")
print("=" * 70)

for status, msg in RESULT["details"]:
    if status.startswith("❌"):
        print(f"  {status}  {msg}")

if RESULT["failed"] == 0:
    print("\n✅ 全A股扫描数据源优化已全部生效！")
    sys.exit(0)
else:
    print(f"\n❌ 有 {RESULT['failed']} 项未通过，请修复后重试")
    sys.exit(1)
