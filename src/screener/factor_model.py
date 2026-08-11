#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CH-4 因子模型 - Liu, Stambaugh, Yuan (2019) - Size and Value in China
严格实现论文中CH-4四因子模型：RMRF + SMB(剔除壳价值) + VMG(EP) + PMG(异常换手率)

四因子定义：
- RMRF: 市场因子（A股市值加权收益 - 无风险利率）
- SMB:  规模因子（剔除最小30%壳公司后，小盘-大盘）
- VMG:  价值因子 Value-Minus-Growth（EP横截面分位，规模中性化）
- PMG:  情绪因子 Pessimistic-Minus-Optimistic（异常换手率横截面分位）
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


class CH4FactorModel:
    """CH-4 四因子模型（Liu, Stambaugh, Yuan 2019）

    论文关键步骤：
    1. 剔除市值最小30%（壳价值过滤）
    2. 按Size分2组，按EP/换手率分3组 (2x3)
    3. 因子规模中性化：VMG = mean(S/H, B/H) - mean(S/L, B/L)
    4. 横截面z-score标准化
    """

    SHELL_PERCENTILE = 0.30
    FACTOR_BREAKPOINTS = (0.30, 0.70)

    def __init__(self, fetcher=None):
        self.fetcher = fetcher
        self.universe_cache = None
        self.last_rebalance = None

    def build_universe_snapshot(
        self, stocks: List[Dict], quotes: Dict
    ) -> pd.DataFrame:
        """构建全市场快照（CH-4因子计算基准池）

        Args:
            stocks: 股票列表，含 market_cap, total_shares
            quotes: 实时行情，含 pe_dynamic, price, turnover_rate

        Returns:
            DataFrame with columns: code, market_cap, log_market_cap, ep, pe,
                                   price, turnover_rate
        """
        rows = []
        for stock in stocks:
            code = stock["code"]
            quote = quotes.get(code, {}) or {}
            market_cap = stock.get("market_cap", 0)
            pe = quote.get("pe_dynamic", 0) or 0

            # 阶段2增强：EP 优先使用扣非净利润计算（论文严格定义）
            # EP = 扣非净利润 / (上月末收盘价 × 总股本)
            # 若扣非净利润不可用，回退到 1/PE
            ep = self._calc_ep_strict(stock, quote, pe)

            price = quote.get("price", 0) or 0
            turnover_rate = quote.get("turnover_rate", 0) or 0

            rows.append(
                {
                    "code": code,
                    "market_cap": float(market_cap),
                    "log_market_cap": (
                        float(np.log(market_cap)) if market_cap > 0 else 0.0
                    ),
                    "ep": float(ep),
                    "pe": float(pe),
                    "price": float(price),
                    "turnover_rate": float(turnover_rate),
                }
            )

        df = pd.DataFrame(rows)
        df = df[df["market_cap"] > 0].copy()
        df.reset_index(drop=True, inplace=True)
        return df

    @staticmethod
    def _calc_ep_strict(stock: Dict, quote: Dict, pe: float) -> float:
        """阶段2增强：严格按论文定义计算 EP

        论文公式：EP = 扣非净利润 / (上月末收盘价 × 总股本)

        数据优先级：
        1. 扣非净利润 + 总股本 + 上月末收盘价（最严格）
        2. 1 / PE（回退，与阶段1保持兼容）

        Returns:
            EP值（>0 表示盈利，≤0 表示亏损或数据不足）
        """
        # 方案1：使用扣非净利润（严格论文定义）
        net_profit_excl = stock.get("net_profit_excl_nonrecurring")
        total_shares = stock.get("total_shares", 0)
        last_month_close = stock.get("last_month_close", 0)

        if (net_profit_excl and net_profit_excl > 0
                and total_shares and total_shares > 0
                and last_month_close and last_month_close > 0):
            ep_strict = float(net_profit_excl) / (float(last_month_close) * float(total_shares))
            if ep_strict > 0:
                return ep_strict

        # 方案2：回退到 1/PE
        return (1.0 / pe) if pe and pe > 0 else 0.0

    def filter_shell_stocks(self, universe: pd.DataFrame) -> pd.DataFrame:
        """CH-4核心预处理：剔除最小30%壳公司

        论文依据：A股IPO限制导致小盘股含"壳价值溢价"，
        若不剔除会污染规模因子和整体定价。
        """
        if len(universe) < 30:
            return universe.copy()

        cap_threshold = float(universe["market_cap"].quantile(self.SHELL_PERCENTILE))
        filtered = universe[universe["market_cap"] > cap_threshold].copy()
        filtered.reset_index(drop=True, inplace=True)

        removed_cnt = len(universe) - len(filtered)
        print(
            f"  [CH-4] 壳价值过滤：剔除最小{self.SHELL_PERCENTILE*100:.0f}% "
            f"(市值<{cap_threshold/1e8:.1f}亿)，"
            f"剔除 {removed_cnt} 只，剩余 {len(filtered)} 只"
        )
        return filtered

    def compute_factor_exposure(
        self,
        stock: Dict,
        quote: Dict,
        history: List[Dict],
        fund: Optional[Dict],
        universe_data: pd.DataFrame,
    ) -> Dict:
        """计算单只股票的CH-4四因子暴露

        Returns:
            {market_beta, size_score, value_score, sentiment_score,
             composite_score, raw_factors, interpretation}
        """
        code = stock["code"]
        pe = (quote.get("pe_dynamic", 0) or 0)
        market_cap = stock.get("market_cap", 0)

        if universe_data is None or len(universe_data) < 30:
            return self._fallback_exposure(pe, market_cap)

        # ========== 因子1: Size（市值log，取反后小盘得分高） ==========
        log_cap = float(np.log(market_cap)) if market_cap > 0 else 0.0
        size_z = self._cross_section_zscore(log_cap, universe_data["log_market_cap"])
        size_score = -size_z  # SMB = 小盘-大盘，所以取反

        # ========== 因子2: Value（EP横截面分位z-score，严格论文定义） ==========
        ep = self._calc_ep_strict(stock, quote, pe)
        valid_ep_mask = universe_data["ep"] > 0
        if valid_ep_mask.sum() > 30 and ep > 0:
            value_z = self._cross_section_zscore(ep, universe_data.loc[valid_ep_mask, "ep"])
        elif ep > 0:
            value_z = self._cross_section_zscore(ep, universe_data["ep"])
        else:
            value_z = -2.0
        value_score = value_z

        # ========== 因子3: Sentiment（异常换手率，低换手得分高） ==========
        abnormal_turnover = self._calc_abnormal_turnover(history, quote)
        turn_z = self._cross_section_zscore(
            abnormal_turnover, universe_data["turnover_rate"]
        )
        sentiment_score = -turn_z  # PMG = 低换手-高换手

        # ========== 因子4: Market Beta（简化估计） ==========
        market_beta = self._estimate_market_beta(history)

        # ========== 综合得分（等权因子z-score） ==========
        composite_score = (
            0.25 * market_beta
            + 0.25 * size_score
            + 0.30 * value_score  # EP在A股解释力最强
            + 0.20 * sentiment_score
        )

        # ========== 人类可读解读 ==========
        interpretation = {
            "size": self._interpret_size(size_score, market_cap),
            "value": self._interpret_value(value_score, ep),
            "sentiment": self._interpret_sentiment(sentiment_score, abnormal_turnover),
        }

        return {
            "market_beta": round(float(market_beta), 3),
            "size_score": round(float(size_score), 3),
            "value_score": round(float(value_score), 3),
            "sentiment_score": round(float(sentiment_score), 3),
            "composite_score": round(float(composite_score), 3),
            "raw_factors": {
                "log_market_cap": round(log_cap, 3),
                "ep": round(ep, 4),
                "abnormal_turnover": round(abnormal_turnover, 3),
            },
            "interpretation": interpretation,
        }

    def get_ep_percentile(self, ep: float, universe_data: pd.DataFrame) -> float:
        """获取EP在全市场横截面的分位数（用于打分输出）"""
        if universe_data is None or len(universe_data) < 30 or ep <= 0:
            return 0.0
        valid_ep = universe_data[universe_data["ep"] > 0]["ep"]
        if len(valid_ep) < 10:
            return 0.0
        return float((valid_ep < ep).mean())

    # ---------- 内部辅助函数 ----------

    def _fallback_exposure(self, pe: float, market_cap: float) -> Dict:
        """快照不可用时的回退因子暴露（保守中性）"""
        log_cap = float(np.log(market_cap)) if market_cap > 0 else 0.0
        ep = (1.0 / pe) if pe and pe > 0 else 0.0
        return {
            "market_beta": 1.0,
            "size_score": 0.0,
            "value_score": 0.0,
            "sentiment_score": 0.0,
            "composite_score": 0.0,
            "raw_factors": {
                "log_market_cap": round(log_cap, 3),
                "ep": round(ep, 4),
                "abnormal_turnover": 1.0,
            },
            "interpretation": {
                "size": "数据不足（快照未构建）",
                "value": "数据不足（快照未构建）",
                "sentiment": "数据不足（快照未构建）",
            },
        }

    @staticmethod
    def _cross_section_zscore(value: float, series: pd.Series) -> float:
        """横截面z-score标准化（CH-4论文标准预处理）"""
        series = pd.to_numeric(series, errors="coerce").dropna()
        if len(series) < 10:
            return 0.0
        std = float(series.std())
        if std == 0 or np.isnan(std):
            return 0.0
        return float((value - float(series.mean())) / std)

    @staticmethod
    def _calc_abnormal_turnover(
        history: List[Dict], quote: Optional[Dict]
    ) -> float:
        """计算异常换手率 = 当日换手率 / 过去60日均值换手率"""
        today_turnover = 0.0
        if quote and isinstance(quote, dict):
            today_turnover = float(quote.get("turnover_rate", 0) or 0)

        if not history or not isinstance(history, list):
            return today_turnover if today_turnover > 0 else 1.0

        hist_window = history[-60:] if len(history) > 60 else history
        hist_turnovers = [
            float(h.get("turnover_rate", 0) or 0)
            for h in hist_window
            if isinstance(h, dict)
        ]
        if len(hist_turnovers) == 0:
            return today_turnover if today_turnover > 0 else 1.0

        avg_60 = sum(hist_turnovers) / len(hist_turnovers)
        if avg_60 <= 0:
            return today_turnover if today_turnover > 0 else 1.0

        return float(today_turnover / avg_60)

    @staticmethod
    def _estimate_market_beta(history: List[Dict]) -> float:
        """估计市场Beta（简化版：仅基于波动率估计β≈1，待后续接入市场收益序列）"""
        if not history or len(history) < 30:
            return 1.0
        rets = [
            float(h.get("pct_chg", 0) or 0)
            for h in history[-60:]
            if isinstance(h, dict)
        ]
        if len(rets) < 20:
            return 1.0
        vol = float(np.std(rets))
        # A股个股日波动率通常在2%-3%左右，β=个股相对市场波动比
        # 简化：以2.0%作为市场波动代理，vol/2%
        if vol <= 0:
            return 1.0
        beta = vol / 2.0
        return float(max(0.3, min(2.5, beta)))

    # ---------- 解读函数 ----------

    @staticmethod
    def _interpret_size(size_score: float, market_cap: float) -> str:
        cap_yi = market_cap / 1e8 if market_cap else 0
        if size_score >= 0.5:
            return f"小盘股溢价（{cap_yi:.0f}亿，规模暴露正向）"
        elif size_score <= -0.5:
            return f"大盘股稳健（{cap_yi:.0f}亿，规模暴露负向）"
        else:
            return f"中盘股中性（{cap_yi:.0f}亿）"

    @staticmethod
    def _interpret_value(value_score: float, ep: float) -> str:
        if value_score >= 0.5 and ep > 0:
            return f"高EP价值股（EP={ep:.4f}，价值暴露正向）"
        elif value_score <= -0.5:
            return f"低EP成长股（EP={ep:.4f}，价值暴露负向）"
        else:
            return f"EP中性（EP={ep:.4f}）"

    @staticmethod
    def _interpret_sentiment(sentiment_score: float, abnormal_turnover: float) -> str:
        if sentiment_score >= 0.5:
            return f"低换手理性期（异常换手={abnormal_turnover:.2f}，情绪暴露正向）"
        elif sentiment_score <= -0.5:
            return f"高换手过热期（异常换手={abnormal_turnover:.2f}，情绪暴露负向）"
        else:
            return f"换手中性（异常换手={abnormal_turnover:.2f}）"
