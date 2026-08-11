#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选股引擎 v4.0 - 两轮预过滤 + 行业自适应阈值 + 多维度评分
- 第一轮：质量筛查（基本面一票否决）
- 第二轮：形态筛查（量价形态门槛）
- 行业自适应阈值：根据二级分类使用不同财务标准
- 新增技术指标：tail_pct（尾盘涨幅）/ vol_trend（量能趋势）/ circ_market_cap（流通市值）
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .data_fetcher import StockDataFetcher, StockAnalyzer, INDUSTRY_LEVEL2_MAP
from .capital_flow_analyzer import CapitalFlowAnalyzer
from .volume_price_analyzer import VolumePriceAnalyzer


class StockScreener:
    """股票选股引擎 v4.0"""
    
    def __init__(self):
        self.fetcher = StockDataFetcher()
        self.analyzer = StockAnalyzer()
        self.results = []
        self.last_update = None
        self.pre_filter_stats = {
            "quality_passed": 0,
            "pattern_passed": 0,
            "total_scanned": 0,
            "shell_filtered": 0,
            "universe_size": 0,
        }
        self.config = {
            "mode": "all",
            "min_market_cap": 50,
            "max_count": 0,    # 全A股扫描（不限量），原500是东方财富单源限制，现akshare回退链可覆盖~5500只
            "top_n": 10,
            "min_score": 50.0,
            "exclude_st": True,
            "circ_market_cap_range": (50, 500),
            "tail_pct_range": (3.0, 5.0),
            "turnover_rate_range": (3.0, 15.0),
            "enable_ch4_factor": True,
            "enable_capital_enhancement": True,
        }
        self.universe_snapshot = None
        self.factor_model = None
        self.northbound_data = {}
        self.dragon_tiger_data = {}
        self._volume_price_analyzer = VolumePriceAnalyzer()
        self._init_factor_model()

    def _init_factor_model(self):
        """初始化CH-4因子模型（Liu, Stambaugh, Yuan 2019）"""
        try:
            from .factor_model import CH4FactorModel
            self.factor_model = CH4FactorModel(self.fetcher)
            print("✅ CH-4 因子模型已加载（EP价值因子 + 壳价值过滤 + 异常换手率情绪因子）")
        except Exception as e:
            print(f"⚠️ CH-4 因子模型加载失败，将使用传统打分: {e}")
            self.factor_model = None
    
    def update_config(self, **kwargs):
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value

    def run_screening(self, top_n: int = None, min_score: float = None,
                      mode: str = None, stocks_filter_codes: list = None,
                      strict_filter: bool = True, **kwargs) -> List[Dict]:
        """v6.0 选股筛选 + 因子打分

        Args:
            top_n: 返回 Top N（默认配置）
            min_score: 最低合格分数
            mode: "all" / "hot"
            stocks_filter_codes: 【新增 v3.2 限定打分池】仅对指定 codes 做打分排名。
                若提供，则仅在 Step 3 调用 _process_stocks 前按 codes 过滤，
                CH-4 横截面/行情获取仍走全市场（因子计算需全市场排名）。
            strict_filter: 【新增 v3.2】True 执行 _pre_filter_quality 基本面一票否决；
                False 仅打分、不额外剔除（用于④已筛过的候选池，避免二次过滤把20只打空）。
            **kwargs: 透传给 self.config
        """
        top_n = top_n if top_n is not None else self.config["top_n"]
        min_score = min_score if min_score is not None else self.config["min_score"]
        mode = mode if mode is not None else self.config["mode"]

        self.config.update({k: v for k, v in kwargs.items() if k in self.config})

        filter_hint = (f"   限定打分池: {len(stocks_filter_codes)} 只 (strict_filter={strict_filter})"
                       if stocks_filter_codes else "   全市场打分 + 基本面筛选")
        ch4_status = "CH-4因子融合: 传统60% + 因子40%" if self.config.get("enable_ch4_factor") and self.factor_model else "传统打分模式"
        print("=" * 60)
        print("🚀 开始股票筛选 v6.0 (基本面筛选 + 四维度打分)")
        print(f"   模式: {mode}")
        print(f"   市值范围: {self.config['circ_market_cap_range'][0]}亿-{self.config['circ_market_cap_range'][1]}亿")
        print(f"   打分维度: 基本面(40) + 趋势动量(20) + 量价筹码(15) + 资金面行为(25) = 100分")
        print(f"   模型: {ch4_status}")
        print(f" {filter_hint}")
        print("=" * 60)

        # Step 1: 获取股票列表（CH-4 横截面需全市场，此处不做 codes 过滤）
        stocks = self.fetcher.get_stock_list(
            mode=mode,
            min_market_cap=self.config['min_market_cap'],
            exclude_st=self.config['exclude_st'],
            max_count=self.config['max_count'],
        )
        if not stocks:
            print("❌ 无法获取股票列表")
            return []

        self.pre_filter_stats["total_scanned"] = len(stocks)
        print(f"\n📋 Step 1: 获取到 {len(stocks)} 只股票")

        # Step 2: 批量获取实时行情
        print("📊 Step 2: 获取实时行情...")
        quotes = self.fetcher.fetch_batch_quotes(stocks)

        # Step 2.5: 构建CH-4全市场快照（用于横截面排序）
        if self.config.get("enable_ch4_factor") and self.factor_model:
            print("🌐 Step 2.5: 构建CH-4全市场快照（壳价值过滤 + EP/换手率横截面）...")
            self.universe_snapshot = self.factor_model.build_universe_snapshot(stocks, quotes)
            before_count = len(self.universe_snapshot)
            self.universe_snapshot = self.factor_model.filter_shell_stocks(self.universe_snapshot)
            after_count = len(self.universe_snapshot)
            self.pre_filter_stats["shell_filtered"] = before_count - after_count
            self.pre_filter_stats["universe_size"] = after_count
            print(f"  快照完成：{after_count} 只股票进入因子计算池")

        # Step 2.6: 阶段2增强 - 北向资金 & 龙虎榜数据
        self.northbound_data = {}
        self.dragon_tiger_data = {}
        if self.config.get("enable_capital_enhancement", True):
            # 【v3.2】限定打分池时，仅拉目标 codes 的资金数据（提速）
            if stocks_filter_codes:
                target_codes = [c for c in stocks_filter_codes if c]
                print(f"💵 Step 2.6: 限定池模式 → 获取 {len(target_codes)} 只的北向资金数据...")
                codes_north = target_codes
            else:
                print("💵 Step 2.6: 获取北向资金数据（阶段2增强）...")
                codes_north = [s["code"] for s in stocks[:200]]  # 限制前200只
            try:
                self.northbound_data = self.fetcher.fetch_batch_northbound(codes_north)
            except Exception as e:
                print(f"⚠️ 北向资金数据获取失败: {e}")
                self.northbound_data = {}
            try:
                print("🐉 Step 2.6: 获取龙虎榜数据...")
                self.dragon_tiger_data = self.fetcher.fetch_batch_dragon_tiger(codes_north)
            except Exception as e:
                print(f"⚠️ 龙虎榜数据获取失败: {e}")
                self.dragon_tiger_data = {}

        # Step 3: 基本面筛选 + 三维度打分
        # 【v3.2】限定打分池模式：先按 codes 过滤到目标子集，再打分
        process_stocks = stocks
        if stocks_filter_codes:
            code_set = set(str(c) for c in stocks_filter_codes if c)
            before_n = len(process_stocks)
            process_stocks = [s for s in process_stocks if str(s.get("code") or "") in code_set]
            print(f"🎯 限定打分池: {before_n} → {len(process_stocks)} 只（匹配 {len(code_set)} 个目标 codes）")
            self.pre_filter_stats["scoring_pool_target"] = len(code_set)
            self.pre_filter_stats["scoring_pool_matched"] = len(process_stocks)
            if len(process_stocks) < len(code_set):
                missing = code_set - set(str(s.get("code") or "") for s in process_stocks)
                print(f"  ⚠️ 以下 codes 未在市场池中找到（可能停牌/已退市）: {list(missing)[:5]}")
        print("🔍 Step 3: 基本面筛选 + 三维度打分...")
        analyzed_results = self._process_stocks(process_stocks, quotes, strict_mode=strict_filter)

        if not analyzed_results:
            print("⚠️ 无股票通过基本面筛选，返回空结果")
            self.results = []
            self.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return []

        # Step 4: 排序并选出Top N
        analyzed_results.sort(key=lambda x: x["total_score"], reverse=True)
        qualified = [r for r in analyzed_results if r["total_score"] >= min_score]
        top_stocks = qualified[:top_n]

        self.results = top_stocks
        self.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n🎉 筛选完成！")
        print(f"   有效分析: {len(analyzed_results)}")
        print(f"   合格股票: {len(qualified)} (≥{min_score}分)")
        print(f"   返回Top: {len(top_stocks)}")
        if self.pre_filter_stats.get("shell_filtered", 0) > 0:
            print(f"   壳股剔除: {self.pre_filter_stats['shell_filtered']} 只（市值<30%分位）")
        if self.pre_filter_stats.get("weak_dimension_total", 0) > 0:
            print(f"   维度短板剔除: {self.pre_filter_stats['weak_dimension_total']} 只 "
                  f"(明细={self.pre_filter_stats.get('weak_dimension_breakdown', {})})")

        return top_stocks

    def _pre_filter_quality(self, stock: Dict, quote: Dict, history: List[Dict]) -> Tuple[bool, List[str]]:
        """第一轮：质量筛查（基本面一票否决）
        
        【7条否决条件】（任一触发即淘汰）
        1. ST/*ST股票 → 名称含ST即淘汰
        2. 壳价值污染 → 全市场最小30%市值+低营收亏损（CH-4论文核心过滤）
        3. ROE过低 → < 行业roe_min（白酒18%, 半导体3%）
        4. ROE连续3年下滑 → ⚠️占位实现，永不触发
        5. 净利润增长率过低 → < -30%
        6. 自由现金流为负 → 非豁免行业才检查
        7. 资产负债率过高 → > 行业debt_ratio_max
        
        【H1硬约束】行业自适应阈值
        thresholds从stock["industry_thresholds"]读取，已根据行业预设。
        金融/半导体通常cash_flow_exempt=True（豁免现金流检查）。
        """
        reasons = []
        thresholds = stock.get("industry_thresholds", {})
        industry_level2 = stock.get("industry_level2", "通用")
        
        # 1. 排除 ST/*ST 股票
        name = stock.get("name", "")
        if "ST" in name or "st" in name or "*ST" in name:
            reasons.append("ST/*ST股票")
            return False, reasons
        
        # 2. CH-4壳价值过滤（Liu, Stambaugh, Yuan 2019）
        if self.universe_snapshot is not None and len(self.universe_snapshot) > 50:
            market_cap = stock.get("market_cap", 0)
            shell_threshold = float(self.universe_snapshot["market_cap"].quantile(0.30))
            if market_cap > 0 and market_cap < shell_threshold:
                fund_shell = self._get_fundamental_safe(stock["code"]) or {}
                revenue = fund_shell.get("revenue", 0) or 0
                net_profit = fund_shell.get("net_profit", 0) or 0
                if revenue < 5e8 and net_profit <= 0:
                    reasons.append(f"壳价值污染（市值<{shell_threshold/1e8:.1f}亿+低营收亏损）")
                    return False, reasons
        
        # 3. ROE 检查
        roe_min = thresholds.get("roe_min", 3.0)
        fund = self._get_fundamental_safe(stock["code"])
        if fund:
            roe = fund.get("roe")
            if roe is not None and roe < roe_min:
                reasons.append(f"ROE({roe:.1f}%) < {roe_min}%")
            
            # 4. 连续3年ROE下滑（简化版：检查趋势）
            roe_trend = self._check_roe_trend(stock["code"])
            if roe_trend == "declining":
                reasons.append("ROE连续3年下滑")
            
            # 5. 净利润增长率
            profit_growth = fund.get("profit_growth")
            if profit_growth is not None and profit_growth < -30:
                reasons.append(f"净利润增长率({profit_growth:.1f}%)过低")
            
            # 6. 自由现金流
            cash_flow_exempt = thresholds.get("cash_flow_exempt", False)
            free_cf = fund.get("free_cash_flow")
            if not cash_flow_exempt and free_cf is not None and free_cf < 0:
                reasons.append(f"自由现金流为负({free_cf/1e8:.2f}亿)")
            
            # 7. 资产负债率
            debt_max = thresholds.get("debt_ratio_max", 70.0)
            debt = fund.get("debt_ratio")
            if debt is not None and debt > debt_max:
                reasons.append(f"资产负债率({debt:.1f}%) > {debt_max}%")
        else:
            # 无法获取基本面数据时，仅做技术面筛选
            pass
        
        passed = len(reasons) == 0
        return passed, reasons

    # ── v3.2 维度短板一票否决 ────────────────────────────────────────────────
    # 四维权重：基本面40 + 趋势动量20 + 量价筹码15 + 资金面25 = 100
    # "明显劣势" 定义：低于该维度满分的 30%
    WEAK_DIM_THRESHOLDS = {
        "fundamental_score": (40, 0.30),   # < 12/40
        "trend_score":       (20, 0.30),   # <  6/20
        "volume_price_score":(15, 0.30),   # < 4.5/15
        "capital_score":     (25, 0.30),   # < 7.5/25
    }

    def _check_dimension_weakness(self, result: Dict) -> List[str]:
        """返回维度短板的原因列表；空列表表示全部合格。"""
        reasons = []
        for field, (max_score, min_ratio) in self.WEAK_DIM_THRESHOLDS.items():
            cutoff = round(max_score * min_ratio, 2)
            got = float(result.get(field) or 0)
            if got < cutoff:
                # 中文 category 映射
                zh = {
                    "fundamental_score": "基本面",
                    "trend_score": "趋势动量",
                    "volume_price_score": "量价筹码",
                    "capital_score": "资金面行为",
                }.get(field, field)
                reasons.append(f"{zh}得分 {got:.1f} < {cutoff:.1f}（满分{max_score}的{int(min_ratio*100)}%）")
        return reasons
    # ──────────────────────────────────────────────────────────────────────────

    def _process_stocks(self, stocks: List[Dict], quotes: Dict, strict_mode: bool = True) -> List[Dict]:
        """处理股票列表 - 仅基本面过滤 + 三维度打分

        v3.2 新增：
          - 打分后执行「维度短板一票否决」：任一维度得分低于满分的30%即剔除，避免
            某一面明显劣势的股票靠其他面高分稀释掉短板信号、挤进TopN。
        """
        quality_passed = []
        analyzed_results = []

        total = len(stocks)
        done = 0
        skip_reasons = {"no_quote": 0, "no_history": 0, "quality_fail": 0, "weak_dimension": 0}
        weak_dimension_breakdown = {k: 0 for k in self.WEAK_DIM_THRESHOLDS}

        for stock in stocks:
            code = stock["code"]
            quote = quotes.get(code)

            if not quote or quote["price"] == 0:
                skip_reasons["no_quote"] += 1
                done += 1
                continue

            try:
                history = self.fetcher.fetch_kline_history(stock["full_code"], days=120)

                if not history or len(history) < 30:
                    skip_reasons["no_history"] += 1
                    done += 1
                    continue

                # 基本面过滤
                if strict_mode:
                    quality_ok, quality_reasons = self._pre_filter_quality(stock, quote, history)
                    if not quality_ok:
                        skip_reasons["quality_fail"] += 1
                        done += 1
                        continue
                quality_passed.append(stock)

                # → 三维度打分
                result = self._analyze_stock(stock, quote, history)
                if not strict_mode:
                    _q_ok, _q_reasons = self._pre_filter_quality(stock, quote, history)
                    if not _q_ok:
                        result["quality_warnings"] = _q_reasons

                # v3.2 维度短板一票否决
                weak_reasons = self._check_dimension_weakness(result)
                if weak_reasons:
                    # 计入 breakdown（用字段 key）
                    for field in self.WEAK_DIM_THRESHOLDS:
                        cutoff = round(self.WEAK_DIM_THRESHOLDS[field][0] *
                                       self.WEAK_DIM_THRESHOLDS[field][1], 2)
                        if float(result.get(field) or 0) < cutoff:
                            weak_dimension_breakdown[field] += 1
                    result["weak_dimension_reasons"] = weak_reasons
                    skip_reasons["weak_dimension"] += 1
                    done += 1
                    continue

                analyzed_results.append(result)

            except Exception as e:
                print(f"    ⚠️ 分析 {code} 出错: {e}")

            done += 1
            if done % 100 == 0:
                print(f"  进度: {done}/{total} ({done*100//total}%) - 基本面通过: {len(quality_passed)}")
                time.sleep(0.2)

        self.pre_filter_stats["quality_passed"] = len(quality_passed)
        self.pre_filter_stats["pattern_passed_before_weak"] = (
            len(analyzed_results) + skip_reasons["weak_dimension"]
        )
        self.pre_filter_stats["pattern_passed"] = len(analyzed_results)
        self.pre_filter_stats["weak_dimension_total"] = skip_reasons["weak_dimension"]
        self.pre_filter_stats["weak_dimension_breakdown"] = weak_dimension_breakdown

        mode_name = "严格" if strict_mode else "宽松"
        print(f"\n📊 [{mode_name}模式] 筛选统计:")
        print(f"  扫描总数: {total}")
        print(f"  无行情/停牌: {skip_reasons['no_quote']}")
        print(f"  无历史数据: {skip_reasons['no_history']}")
        print(f"  基本面通过: {len(quality_passed)} ({len(quality_passed)*100/max(total,1):.1f}%)")
        print(f"  维度短板剔除: {skip_reasons['weak_dimension']} (明细: {weak_dimension_breakdown})")
        print(f"  进入排名: {len(analyzed_results)}")

        return analyzed_results

    def _analyze_stock(self, stock: Dict, quote: Dict, history: List[Dict]) -> Dict:
        """分析单只股票 - 三大维度评分体系"""
        code = stock["code"]
        name = stock["name"]
        price = quote["price"]
        industry_level1 = stock.get("industry_level1", "通用")
        industry_level2 = stock.get("industry_level2", "通用")
        thresholds = stock.get("industry_thresholds", {})
        
        result = {
            "code": code,
            "name": name,
            "price": price,
            "change_pct": quote.get("change_pct", 0),
            "turnover_rate": quote.get("turnover_rate", 0),
            "pe": quote.get("pe_dynamic", 0),
            "pb": quote.get("pb", 0),
            "market_cap": stock.get("market_cap", 0),
            "industry": stock.get("industry", ""),
            "industry_level1": industry_level1,
            "industry_level2": industry_level2,
            "industry_thresholds": thresholds,
            "industry_note": stock.get("industry_note", ""),
        }
        
        # 获取基本面数据
        fund = self._get_fundamental_safe(code)
        result["fundamental"] = fund or {}
        
        # 1. 均线分析
        ma5_trend = self.analyzer.calculate_ma_trend(history, 5)
        ma10_trend = self.analyzer.calculate_ma_trend(history, 10)
        ma20_trend = self.analyzer.calculate_ma_trend(history, 20)
        ma60_trend = self.analyzer.calculate_ma_trend(history, 60)
        
        result["ma5"] = ma5_trend
        result["ma10"] = ma10_trend
        result["ma20"] = ma20_trend
        result["ma60"] = ma60_trend
        
        # 均线排列
        alignment = self.analyzer.check_ma_alignment(history)
        result["ma_alignment"] = alignment
        
        # 2. 成交量分析
        volume_analysis = self.analyzer.calculate_volume_ratio(history)
        result["volume_analysis"] = volume_analysis
        
        # 3. 3日成交量趋势
        vol_trend_3d = self.analyzer.check_volume_trend_3day(history)
        result["vol_trend"] = vol_trend_3d
        
        # 4. 尾盘涨幅
        tail_pct = self.analyzer.calculate_tail_pct(history, quote)
        result["tail_pct"] = tail_pct
        
        # 5. 价格位置
        price_position = self.analyzer.calculate_price_position(history, price)
        result["price_position"] = price_position
        
        # 6. 近5日/20日涨幅
        result["pct_5d"] = self.analyzer.calculate_pct_change(history, 5)
        result["pct_20d"] = self.analyzer.calculate_pct_change(history, 20)
        
        # 7. 流通市值（亿）
        market_cap = stock.get("market_cap", 0)
        result["circ_market_cap"] = round(market_cap / 1e8, 2) if market_cap else 0
        
        # 8. 换手率量化
        turnover = quote.get("turnover_rate", 0)
        result["turnover_rate_quantified"] = self._quantify_turnover(turnover)
        
        # 9. 计算评分（四维度 + CH-4因子融合）
        fundamental_score = self._calc_fundamental_score(result, thresholds, industry_level2)
        trend_score = self._calc_trend_score(result, thresholds, industry_level2, history)

        # 量价筹码打分 - 流派2：量价、筹码与支撑阻力（15分）
        vp_result = self._volume_price_analyzer.score(
            code=stock["code"], name=stock["name"],
            history=history or [], quote=quote,
        )
        volume_price_score = vp_result["score"]

        # 资金面打分 - 基于量价分析的资金面&行为学打分（阶段2增强：北向+龙虎榜）
        self._capital_analyzer = CapitalFlowAnalyzer()
        code = stock["code"]
        nb_data = getattr(self, "northbound_data", {}).get(code)
        dt_data = getattr(self, "dragon_tiger_data", {}).get(code)
        cap_result = self._capital_analyzer.score(
            code=code, name=stock["name"],
            history=history or [], quote=quote,
            northbound_data=nb_data,
            dragon_tiger_data=dt_data,
        )
        capital_score = cap_result["score"]

        # 资金面行为评分从20分映射到25分：cap_result满分20 → 映射到25
        capital_score_scaled = capital_score * 1.25

        result["fundamental_score"] = round(fundamental_score, 1)
        result["trend_score"] = round(trend_score, 1)
        result["volume_price_score"] = round(volume_price_score, 1)
        result["capital_score"] = round(capital_score_scaled, 1)
        result["capital_flow_detail"] = cap_result
        result["volume_price_detail"] = vp_result
        
        # CH-4 因子暴露计算与融合
        if self.config.get("enable_ch4_factor") and self.factor_model and self.universe_snapshot is not None:
            fund = result.get("fundamental", {}) or {}
            ch4_exposure = self.factor_model.compute_factor_exposure(
                stock=stock, quote=quote, history=history,
                fund=fund, universe_data=self.universe_snapshot
            )
            result["ch4_factors"] = ch4_exposure
            
            traditional_total = fundamental_score + trend_score + volume_price_score + capital_score_scaled
            ch4_composite_scaled = max(0.0, min(100.0, 50.0 + ch4_exposure["composite_score"] * 20.0))
            total_score = 0.6 * traditional_total + 0.4 * ch4_composite_scaled
        else:
            total_score = fundamental_score + trend_score + volume_price_score + capital_score_scaled
        
        result["total_score"] = round(total_score, 1)
        
        # 10. 评级
        result["grade"] = self._get_grade(total_score)
        
        # 11. 建议
        result["advice"] = self._get_advice(result)
        
        # 12. 保存详细分数
        ch4_items = []
        if result.get("ch4_factors"):
            cf = result["ch4_factors"]
            ch4_items = [
                {"name": "市场β", "score": round(50 + cf["market_beta"] * 10, 1), "max": 100,
                 "value": f"β={cf['market_beta']:.2f}"},
                {"name": "规模因子", "score": round(50 + cf["size_score"] * 15, 1), "max": 100,
                 "value": cf["interpretation"]["size"]},
                {"name": "价值因子", "score": round(50 + cf["value_score"] * 15, 1), "max": 100,
                 "value": cf["interpretation"]["value"]},
                {"name": "情绪因子", "score": round(50 + cf["sentiment_score"] * 15, 1), "max": 100,
                 "value": cf["interpretation"]["sentiment"]},
            ]
        
        result["score_details"] = [
            {"category": "基本面", "score": result["fundamental_score"], "max": 40,
             "items": result.get("fundamental_items", [])},
            {"category": "趋势动量", "score": result["trend_score"], "max": 20,
             "items": result.get("trend_items", [])},
            {"category": "量价筹码", "score": result["volume_price_score"], "max": 15,
             "items": vp_result.get("items", [])},
            {"category": "资金面行为", "score": result["capital_score"], "max": 25,
             "items": cap_result.get("items", [])},
        ]
        if ch4_items:
            result["score_details"].append({
                "category": "CH-4因子", "score": round(total_score, 1), "max": 100,
                "items": ch4_items
            })
        
        return result

    def _calc_fundamental_score(self, result: Dict, thresholds: Dict, industry_level2: str) -> float:
        """计算基本面评分（满分40分）
        
        【5个子项】
        1. ROE（10分）：≥1.5倍行业下限→10分；≥下限→10分；≥0.7倍下限→6分；其他→3分
        2. 营收增速（10分）：≥30%→10；≥15%→8；≥5%→6；≥0→4；<0→2
        3. 自由现金流（8分）：豁免行业→6；>0→8；≤0→2
        4. 价值因子EP（7分）：CH-4横截面分位→高EP(70%)→7；中高EP(50%)→5.5；中低EP(30%)→4；低EP→2
        5. 股息率（5分）：≥2倍门槛→5；≥门槛→4；≥0.5倍门槛→3；其他→1.5
        
        【CH-4因子融合】
        EP横截面分位：全市场EP排名（排除最小30%壳股）
        - 与Liu-Stambaugh-Yuan(2019)论文一致：EP因子在中国市场subsumes B/P
        """
        items = []
        fund = result.get("fundamental", {})
        
        # 行业自适应阈值
        industry_roe_min = thresholds.get("roe_min", 3.0)
        debt_max = thresholds.get("debt_ratio_max", 70.0)
        cash_flow_exempt = thresholds.get("cash_flow_exempt", False)
        
        # 1. ROE评分 (10分)
        roe = fund.get("roe")
        roe_score = 5.0
        if roe is not None:
            if roe >= industry_roe_min * 1.5:
                roe_score = 10.0
            elif roe >= industry_roe_min:
                roe_score = 10.0 - max(0, (industry_roe_min - roe) * 0.5)
            elif roe >= industry_roe_min * 0.7:
                roe_score = 6.0
            else:
                roe_score = 3.0
        items.append({"name": "ROE", "score": round(roe_score, 1), "max": 10, "value": f"{roe:.1f}%" if roe else "N/A"})
        
        # 2. 营收增速评分 (10分)
        profit_growth = fund.get("profit_growth")
        growth_score = 5.0
        if profit_growth is not None:
            if profit_growth >= 30:
                growth_score = 10.0
            elif profit_growth >= 15:
                growth_score = 8.0
            elif profit_growth >= 5:
                growth_score = 6.0
            elif profit_growth >= 0:
                growth_score = 4.0
            else:
                growth_score = 2.0
        items.append({"name": "营收增速", "score": round(growth_score, 1), "max": 10, "value": f"{profit_growth:.1f}%" if profit_growth else "N/A"})
        
        # 3. 自由现金流评分 (8分)
        free_cf = fund.get("free_cash_flow")
        cf_score = 4.0
        if cash_flow_exempt:
            cf_score = 6.0  # 金融/半导体豁免
        elif free_cf is not None:
            if free_cf > 0:
                cf_score = 8.0
            else:
                cf_score = 2.0
        items.append({"name": "自由现金流", "score": round(cf_score, 1), "max": 8, "value": "为正" if (free_cf and free_cf > 0) else "为负"})
        
        # 4. 价值因子评分 (7分) - 严格遵循CH-4论文：EP横截面分位数
        # 论文依据：EP = Earnings/Price，在中国市场subsumes B/P
        pe = result.get("pe", 0)
        ep = (1.0 / pe) if pe and pe > 0 else 0.0
        val_score = 3.5
        ep_pct = 0.5
        
        if pe <= 0 or ep <= 0:
            val_score = 1.0
            ep_pct = 0.0
        elif self.universe_snapshot is not None and len(self.universe_snapshot) > 50 and self.factor_model:
            ep_pct = self.factor_model.get_ep_percentile(ep, self.universe_snapshot)
            if ep_pct >= 0.70:
                val_score = 7.0
            elif ep_pct >= 0.50:
                val_score = 5.5
            elif ep_pct >= 0.30:
                val_score = 4.0
            else:
                val_score = 2.0
        else:
            pe_ranges = {
                "金融.国有大行": (4, 6), "金融.股份制银行": (5, 7),
                "金融.券商": (15, 25), "金融.保险": (10, 20),
                "科技.半导体设计": (50, 100), "消费.白酒": (25, 35),
                "消费.家电": (10, 15), "周期.钢铁": (5, 15),
            }
            pe_low, pe_high = pe_ranges.get(industry_level2, (15, 25))
            ep_pct = 0.5
            if pe < pe_low:
                val_score = 7.0
            elif pe_low <= pe <= pe_high:
                val_score = 6.0
            elif pe <= pe_high * 1.5:
                val_score = 3.5
            else:
                val_score = 1.5
        
        items.append({
            "name": "价值因子EP", "score": round(val_score, 1), "max": 7,
            "value": f"PE:{pe:.1f}/EP:{ep:.4f}/分位:{ep_pct*100:.0f}%" if pe else "N/A"
        })
        
        # 5. 股息率评分 (5分)
        dividend_yield = fund.get("dividend_yield", 0)
        div_score = 2.5
        
        dividend_thresholds = {
            "金融.国有大行": 4.0, "金融.股份制银行": 4.0,
            "公用事业": 3.0, "消费.白酒": 2.0,
        }
        div_min = dividend_thresholds.get(industry_level2, 1.0)
        
        if dividend_yield >= div_min * 2:
            div_score = 5.0
        elif dividend_yield >= div_min:
            div_score = 4.0
        elif dividend_yield >= div_min * 0.5:
            div_score = 3.0
        else:
            div_score = 1.5
        
        items.append({"name": "股息率", "score": round(div_score, 1), "max": 5, "value": f"{dividend_yield:.2f}%"})
        
        # 保存明细
        result["fundamental_items"] = items
        total = sum(item["score"] for item in items)
        return total

    def _calc_trend_score(self, result: Dict, thresholds: Dict, industry_level2: str,
                               history: List[Dict] = None) -> float:
        """趋势动量得分（满分20分）- 均线多头排列(8) + 动量反转(6) + 波动率(3) + 行业热度(3)
        
        流派1：趋势与动量类技术分析
        - MA均线系统、MACD趋势、动量反转、波动率过滤
        
        【CH-4因子融合】
        换手率评分叠加异常换手率（PMG情绪因子）调整：
        - 异常换手率 = 当日换手 / 过去60日均换手
        - 论文依据：PMG = 低换手 - 高换手（情绪反转效应）
        """
        items = []
        
        # 1. 均线多头排列 (8分)
        alignment = result.get("ma_alignment", {})
        ma_score = 4.0
        if alignment.get("alignment") == "bullish":
            ma_score = 8.0
        elif alignment.get("alignment") == "semi_bullish":
            ma_score = 6.0
        elif alignment.get("alignment") == "neutral":
            ma_score = 4.0
        elif alignment.get("alignment") == "bearish":
            ma_score = 1.0
        items.append({"name": "均线多头排列", "score": round(ma_score, 1), "max": 8, "value": alignment.get("alignment", "unknown")})
        
        # 2. 趋势动量 (6分) - 基于5日/20日涨幅和动量反转
        pct_5d = result.get("pct_5d", 0)
        pct_20d = result.get("pct_20d", 0)
        momentum_score = 3.0
        
        if pct_5d > 5 and pct_20d > 10:
            momentum_score = 6.0
        elif pct_5d > 0 and pct_20d > 5:
            momentum_score = 5.0
        elif pct_5d > 0:
            momentum_score = 4.0
        elif pct_5d < -5 and pct_20d < -10:
            momentum_score = 1.5
        elif pct_5d < 0:
            momentum_score = 2.5
        
        # 动量反转加分：超跌反弹（5日跌>10%但20日跌<5%）
        if pct_5d < -10 and pct_20d > -5:
            momentum_score = min(6.0, momentum_score + 1.5)
            items.append({"name": "动量反转", "score": round(1.5, 1), "max": 2, "value": "超跌反弹信号"})
        
        items.append({"name": "趋势动量", "score": round(momentum_score, 1), "max": 6, "value": f"5日{pct_5d:.1f}%/20日{pct_20d:.1f}%"})
        
        # 3. 波动率ATR (3分) - 基于历史波动率
        volatility_score = 1.5
        if history and len(history) >= 20:
            closes = [h["close"] for h in history[-20:]]
            returns = [(closes[i] / closes[i-1] - 1) for i in range(1, len(closes))]
            vol = (sum((r - sum(returns)/len(returns))**2 for r in returns) / len(returns)) ** 0.5 * (252 ** 0.5)
            
            if vol < 0.15:
                volatility_score = 3.0
            elif vol < 0.25:
                volatility_score = 2.5
            elif vol < 0.35:
                volatility_score = 1.5
            else:
                volatility_score = 0.5
        items.append({"name": "波动率ATR", "score": round(volatility_score, 1), "max": 3, "value": f"年化波动{vol*100:.1f}%" if history else "N/A"})
        
        # 4. 行业热度 (3分) - 基于近5日涨幅
        industry_score = 1.5
        if pct_5d > 10:
            industry_score = 3.0
        elif pct_5d > 5:
            industry_score = 2.5
        elif pct_5d > 0:
            industry_score = 2.0
        elif pct_5d > -5:
            industry_score = 1.0
        else:
            industry_score = 0.5
        items.append({"name": "行业热度", "score": round(industry_score, 1), "max": 3, "value": f"5日涨{pct_5d:.1f}%"})
        
        # 保存明细
        result["trend_items"] = items
        total = sum(item["score"] for item in items)
        return total

    @staticmethod
    def _quantify_turnover(turnover: float) -> str:
        """量化换手率描述"""
        if turnover <= 0.5:
            return "低迷"
        elif turnover <= 3:
            return "适中"
        elif turnover <= 15:
            return "活跃"
        elif turnover <= 25:
            return "过热"
        else:
            return "异常"

    def _get_fundamental_safe(self, code: str) -> Optional[Dict]:
        """安全获取基本面数据"""
        try:
            return self.fetcher.fetch_fundamental(code)
        except Exception:
            return None

    def _check_roe_trend(self, code: str) -> str:
        """检查ROE趋势（简化版）"""
        fund = self._get_fundamental_safe(code)
        if not fund:
            return "unknown"
        roe = fund.get("roe")
        if roe is not None and roe > 3:
            return "stable"
        return "unknown"

    def _get_grade(self, score: float) -> str:
        if score >= 80:
            return "⭐⭐⭐⭐⭐ 优秀"
        elif score >= 70:
            return "⭐⭐⭐⭐ 良好"
        elif score >= 60:
            return "⭐⭐⭐ 中性"
        elif score >= 50:
            return "⭐⭐ 偏弱"
        else:
            return "⭐ 较差"
    
    def _get_advice(self, result: Dict) -> str:
        score = result["total_score"]
        alignment = result["ma_alignment"]["alignment"]
        industry_level2 = result.get("industry_level2", "通用")
        capital_detail = result.get("capital_flow_detail", {})
        capital_advice = capital_detail.get("position_advice", "")
        capital_signals = capital_detail.get("signals", [])
        vp_detail = result.get("volume_price_detail", {})
        vp_buy_signals = vp_detail.get("buy_signals", [])
        vp_sell_signals = vp_detail.get("sell_signals", [])

        # 资金面强信号 → 提升建议
        cap_score = result.get("capital_score", 10)
        capital_boost = ""
        if cap_score >= 20:
            capital_boost = "，资金面配合"
        elif cap_score < 12:
            capital_boost = "，资金面偏弱"

        # 量价筹码强信号
        vp_boost = ""
        if vp_buy_signals:
            vp_boost = "，量价买点确认"
        if vp_sell_signals:
            vp_boost += "，⚠️筹码卖出信号"

        if score >= 75 and alignment == "bullish":
            return f"✅ 积极建仓：{industry_level2}行业，四维度优秀，均线多头排列{capital_boost}{vp_boost}。{capital_advice}"
        elif score >= 65:
            return f"⚠️ 谨慎关注：{industry_level2}行业，基本面良好，趋势配合{capital_boost}{vp_boost}。{capital_advice}"
        elif score >= 55:
            return f"🔍 观察为主：{industry_level2}行业，基本面中性，等待更好时机{capital_boost}{vp_boost}"
        elif score >= 45:
            return f"⚠️ 谨慎：{industry_level2}行业，基本面偏弱，建议观望{capital_boost}{vp_boost}"
        else:
            return f"⛔ 回避：{industry_level2}行业，基本面较差，不建议参与{capital_boost}{vp_boost}"
    
    def get_results_summary(self) -> Dict:
        ch4_model_info = {}
        if self.config.get("enable_ch4_factor") and self.factor_model:
            ch4_model_info = {
                "model": "Liu-Stambaugh-Yuan CH-4 (2019)",
                "factors": ["RMRF", "SMB(剔除壳价值)", "VMG(EP)", "PMG(异常换手率)"],
                "shell_filter_percentile": self.factor_model.SHELL_PERCENTILE,
                "fusion_weight": {"traditional": 0.6, "ch4": 0.4},
                "universe_size": self.pre_filter_stats.get("universe_size", 0),
                "shell_filtered": self.pre_filter_stats.get("shell_filtered", 0),
            }
        
        return {
            "last_update": self.last_update,
            "total_results": len(self.results),
            "pre_filter_stats": self.pre_filter_stats,
            "ch4_model_info": ch4_model_info,
            "top_stocks": [
                {
                    "rank": i + 1,
                    "code": r["code"],
                    "name": r["name"],
                    "price": r["price"],
                    "total_score": r["total_score"],
                    "fundamental_score": r.get("fundamental_score", 0),
                    "trend_score": r.get("trend_score", 0),
                    "volume_price_score": r.get("volume_price_score", 0),
                    "capital_score": r.get("capital_score", 0),
                    "grade": r["grade"],
                    "advice": r["advice"],
                    "industry_level1": r.get("industry_level1", ""),
                    "industry_level2": r.get("industry_level2", ""),
                    "change_pct": r.get("change_pct", 0),
                    "pe": r.get("pe", 0),
                    "pb": r.get("pb", 0),
                    "tail_pct": r.get("tail_pct", 0),
                    "circ_market_cap": r.get("circ_market_cap", 0),
                    "ch4_factors": r.get("ch4_factors", {}),
                    "capital_flow_detail": r.get("capital_flow_detail", {}),
                    "score_details": r.get("score_details", []),
                }
                for i, r in enumerate(self.results)
            ]
        }
    
    def cleanup(self):
        self.fetcher.clear_cache()
        print("🧹 已清理缓存，内存已释放")
    
    def get_memory_status(self) -> Dict:
        import sys
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            return {
                "memory_usage_mb": round(memory_info.rss / 1024 / 1024, 2),
                "memory_percent": round(process.memory_percent(), 2),
                "stock_count": len(self.results),
                "cache_size": self.fetcher.get_cache_size(),
            }
        except ImportError:
            return {
                "memory_usage_mb": "psutil未安装",
                "stock_count": len(self.results),
                "cache_size": self.fetcher.get_cache_size(),
            }


if __name__ == "__main__":
    screener = StockScreener()
    results = screener.run_screening(top_n=10, mode="hot")
    
    print("\n" + "=" * 70)
    print("📋 Top 10 选股结果（CH-4因子融合评分）:")
    print("=" * 80)
    print(f"{'排名':<4} {'名称':<10} {'代码':<8} {'总分':<6} {'基本面':<8} {'技术面':<8} {'资金面':<8} {'EP分位':<8} {'行业':<16} {'评级':<10}")
    print("-" * 80)
    for i, r in enumerate(results, 1):
        total = r['total_score']
        fund = r.get('fundamental_score', 0)
        tech = r.get('technical_score', 0)
        cap = r.get('capital_score', 0)
        industry = r.get('industry_level2', '')[:8]
        grade = r['grade'][:6]
        ep_pct_str = ""
        if r.get('ch4_factors'):
            rv = r['ch4_factors'].get('raw_factors', {})
            ep_val = rv.get('ep', 0)
            if ep_val > 0:
                ep_pct_str = f"EP={ep_val:.3f}"
        print(f"{i:<4} {r['name']:<10} {r['code']:<8} {total:<6.1f} {fund:<8.1f} {tech:<8.1f} {cap:<8.1f} {ep_pct_str:<8} {industry:<16} {grade:<10}")
        
        # 打印小分明细
        if r.get('score_details'):
            print(f"     基本面: ", end="")
            for item in r['score_details'][0].get('items', []):
                print(f"{item['name']}:{item['score']:.0f}/{item['max']} ", end="")
            print()
            print(f"     技术面: ", end="")
            for item in r['score_details'][1].get('items', []):
                print(f"{item['name']}:{item['score']:.0f}/{item['max']} ", end="")
            print()
            # 打印资金面明细
            if len(r['score_details']) > 2:
                cap_detail = r['score_details'][2]
                print(f"     资金面: ", end="")
                for item in cap_detail.get('items', []):
                    print(f"{item['name']}:{item['score']:.0f}/{item['max']} ", end="")
                print()
            # 打印资金面信号
            cap_flow = r.get('capital_flow_detail', {})
            if cap_flow.get('signals'):
                print(f"     资金信号: ", end="")
                for sig in cap_flow['signals'][:3]:
                    print(f"{sig[:20]} ", end="")
                print()
            if cap_flow.get('position_advice'):
                print(f"     仓位建议: {cap_flow['position_advice']}")
            # 打印CH-4因子明细
            if len(r['score_details']) > 3:
                ch4_detail = r['score_details'][3]
                print(f"     CH-4因子: ", end="")
                for item in ch4_detail.get('items', []):
                    print(f"{item['name']}:{item['value']} ", end="")
                print()
    
    print("\n" + "=" * 80)
    print("💡 评分体系: 传统打分(60%) + CH-4因子(40%) = 综合评分")
    print("📖 因子模型: Liu, Stambaugh, Yuan (2019) - Size and Value in China")
    print("📖 详情文档: docs/stock-scoring_auto_workflow.md")