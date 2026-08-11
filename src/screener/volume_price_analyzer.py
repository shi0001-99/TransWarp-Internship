#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流派2：量价、筹码与支撑阻力 —— 打分模块

核心思想：价格是表象，筹码成本是本质。筹码密集峰是天然支撑/阻力。
数据来源：从已有K线历史(OHLCV)自行计算筹码分布，不依赖第三方付费API。
         akshare的stock_cyq_em接口在东方财富反爬机制下不稳定，
         因此采用纯计算方案，基于换手率衰减模型重建筹码结构。

评分维度（满分15分）：
1. 筹码集中度 (5分): CR10指标 + 单峰/双峰形态识别
2. 量价配合度 (5分): 放量突破/缩量回踩/放量滞涨检测
3. 支撑阻力位 (5分): 筹码密集峰位置 + 缺口支撑/阻力

买点逻辑：
- 低位单峰密集（筹码>30%集中，CR10<15%）+ 放量突破上沿
- 双峰中下峰不破，缩量回踩止跌
- V形反转前密集峰未被消耗

卖点逻辑：
- 高位单峰密集+底部筹码消失（主力派发）
- 筹码发散+放量滞涨
- 上峰不移下跌不止
"""

import numpy as np
from typing import Dict, List, Optional, Tuple


class VolumePriceAnalyzer:
    """量价筹码打分分析器"""

    DECAY_HALF_LIFE = 60
    PRICE_BINS = 80
    CR10_THRESHOLD = 0.15
    CONCENTRATION_THRESHOLD = 0.25

    def __init__(self):
        pass

    def score(
        self,
        code: str,
        name: str,
        history: List[Dict],
        quote: Dict,
    ) -> Dict:
        """计算量价筹码综合打分（满分15分）"""
        if not history or len(history) < 30:
            return self._fallback_result("历史数据不足(<30日)")

        chip_dist = self._calc_chip_distribution(history)
        chip_metrics = self._analyze_chip_structure(chip_dist, history)
        vol_price = self._analyze_volume_price(history, quote)
        support_resistance = self._analyze_support_resistance(chip_dist, history, quote)

        conc_score, conc_items = self._score_concentration(chip_metrics)
        vp_score, vp_items = self._score_volume_price(vol_price)
        sr_score, sr_items = self._score_support_resistance(support_resistance, quote)

        total = conc_score + vp_score + sr_score

        buy_signals = self._detect_buy_signals(chip_metrics, vol_price, support_resistance, quote)
        sell_signals = self._detect_sell_signals(chip_metrics, vol_price, support_resistance, quote)

        signals = buy_signals + sell_signals
        items = conc_items + vp_items + sr_items

        data_sources = ["K线历史(东方财富)"]
        if quote.get("price"):
            data_sources.append("实时行情(腾讯)")

        return {
            "score": round(total, 1),
            "max": 15,
            "items": items,
            "signals": signals,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "data_quality": {
                "source": " + ".join(data_sources),
                "history_days": len(history),
                "chip_peaks_found": len(chip_metrics.get("peaks", [])),
                "note": "筹码分布基于换手率衰减模型自行计算",
            },
        }

    # ================================================================
    # 筹码分布计算
    # ================================================================

    def _calc_chip_distribution(self, history: List[Dict]) -> Dict:
        """从K线历史重建筹码分布（换手率衰减模型）

        核心算法：
        1. 将价格区间划分为N个bin
        2. 对每根K线，将成交量均匀分布到 [low, high] 区间
        3. 对历史成交量施加指数衰减：weight = exp(-ln(2) * age / half_life)
        4. 同时结合换手率做加权：换手率越高，筹码换手越充分
        5. 汇总每个价格bin的累积筹码量
        """
        if not history:
            return {"price_levels": np.array([]), "chip_volume": np.array([]), "total_chips": 0.0}

        highs = np.array([h["high"] for h in history], dtype=np.float64)
        lows = np.array([h["low"] for h in history], dtype=np.float64)
        volumes = np.array([h["volume"] for h in history], dtype=np.float64)
        closes = np.array([h["close"] for h in history], dtype=np.float64)

        price_min = float(np.min(lows))
        price_max = float(np.max(highs))

        if price_max <= price_min:
            return {"price_levels": np.array([]), "chip_volume": np.array([]), "total_chips": 0.0}

        n_bins = self.PRICE_BINS
        price_levels = np.linspace(price_min, price_max, n_bins)
        bin_size = (price_max - price_min) / (n_bins - 1)

        chip_volume = np.zeros(n_bins, dtype=np.float64)
        n_days = len(history)

        for i in range(n_days):
            low = lows[i]
            high = highs[i]
            vol = volumes[i]
            age = n_days - 1 - i
            weight = np.exp(-np.log(2) * age / self.DECAY_HALF_LIFE)

            if high <= low or vol <= 0:
                continue

            low_idx = max(0, int((low - price_min) / bin_size))
            high_idx = min(n_bins - 1, int((high - price_min) / bin_size))

            if high_idx <= low_idx:
                chip_volume[low_idx] += vol * weight
            else:
                range_len = high_idx - low_idx + 1
                per_bin_vol = vol * weight / range_len
                for idx in range(low_idx, high_idx + 1):
                    chip_volume[idx] += per_bin_vol

        total_chips = float(np.sum(chip_volume))

        return {
            "price_levels": price_levels,
            "chip_volume": chip_volume,
            "total_chips": total_chips,
            "closes": closes,
        }

    def _analyze_chip_structure(self, chip_dist: Dict, history: List[Dict]) -> Dict:
        """分析筹码结构：集中度、峰谷识别、单峰/双峰判定"""
        price_levels = chip_dist.get("price_levels", np.array([]))
        chip_volume = chip_dist.get("chip_volume", np.array([]))
        total = chip_dist.get("total_chips", 0.0)

        if len(price_levels) == 0 or total <= 0:
            return self._empty_chip_metrics()

        chip_density = chip_volume / total

        cr10 = self._calc_cr10_robust(price_levels, chip_volume, total)

        peaks = self._find_peaks_robust(price_levels, chip_volume, total)

        is_single_peak = len(peaks) >= 1 and peaks[0]["concentration"] >= self.CONCENTRATION_THRESHOLD
        is_double_peak = len(peaks) >= 2 and peaks[1]["concentration"] >= 0.08

        if len(history) > 0:
            current_price = history[-1].get("close", 0)
        else:
            current_price = price_levels[-1]

        peak_positions = self._classify_peak_positions(peaks, price_levels, current_price)

        bottom_ratio, top_ratio = self._calc_chip_distribution_ratio(
            price_levels, chip_volume, total, current_price
        )

        chip_divergence = cr10 < 0.12

        price_vs_peak = self._classify_price_vs_peak(peaks, current_price)

        return {
            "cr10": cr10,
            "peaks": peaks,
            "is_single_peak": is_single_peak,
            "is_double_peak": is_double_peak,
            "peak_positions": peak_positions,
            "bottom_chips_ratio": bottom_ratio,
            "top_chips_ratio": top_ratio,
            "chip_divergence": chip_divergence,
            "price_vs_peak": price_vs_peak,
            "current_price": current_price,
        }

    def _calc_cr10_robust(self, price_levels: np.ndarray, chip_volume: np.ndarray,
                           total: float) -> float:
        """鲁棒CR10计算：找到10%价格区间内最大集中度"""
        if len(price_levels) < 5 or total <= 0:
            return 0.0

        price_min = price_levels[0]
        price_max = price_levels[-1]
        price_range = price_max - price_min

        if price_range <= 0:
            return 1.0

        window_size = price_range * 0.10

        best_concentration = 0.0
        n = len(price_levels)

        for i in range(n):
            center_price = price_levels[i]
            left_bound = center_price - window_size / 2
            right_bound = center_price + window_size / 2

            mask = (price_levels >= left_bound) & (price_levels <= right_bound)
            concentration = float(np.sum(chip_volume[mask])) / total

            if concentration > best_concentration:
                best_concentration = concentration

        return best_concentration

    def _find_peaks_robust(self, price_levels: np.ndarray, chip_volume: np.ndarray,
                            total: float) -> List[Dict]:
        """鲁棒峰检测：基于密度重心的峰识别

        算法：
        1. 找到筹码量最大的价格点（主峰）
        2. 计算主峰的集中度（主峰附近15%价格区间的筹码占比）
        3. 依次扣除已识别峰的筹码，寻找次峰
        4. 当次峰集中度<15%时停止
        """
        if len(chip_volume) < 5 or total <= 0:
            return []

        remaining = chip_volume.copy()
        peaks = []
        n = len(price_levels)
        price_range = price_levels[-1] - price_levels[0]
        peak_window = price_range * 0.08

        for _ in range(3):
            if np.sum(remaining) <= 0:
                break

            peak_idx = int(np.argmax(remaining))
            peak_val = remaining[peak_idx]

            if peak_val < total * 0.03:
                break

            peak_price = price_levels[peak_idx]

            left_bound = peak_idx
            while left_bound > 0 and abs(price_levels[left_bound] - peak_price) < peak_window:
                left_bound -= 1
            left_bound = max(0, left_bound + 1)

            right_bound = peak_idx
            while right_bound < n - 1 and abs(price_levels[right_bound] - peak_price) < peak_window:
                right_bound += 1
            right_bound = min(n - 1, right_bound - 1)

            peak_concentration = float(np.sum(chip_volume[left_bound:right_bound + 1])) / total
            peak_width = float(price_levels[right_bound] - price_levels[left_bound])

            peaks.append({
                "price": float(peak_price),
                "density": float(peak_val / total),
                "width": peak_width,
                "concentration": peak_concentration,
                "left_bound": float(price_levels[left_bound]),
                "right_bound": float(price_levels[right_bound]),
            })

            remaining[left_bound:right_bound + 1] = 0

        peaks.sort(key=lambda x: x["concentration"], reverse=True)
        return peaks[:3]

    def _classify_peak_positions(self, peaks: List[Dict], price_levels: np.ndarray,
                                 current_price: float) -> str:
        """分类峰位位置：低位/中位/高位"""
        if not peaks or len(price_levels) == 0:
            return "unknown"

        price_min = price_levels[0]
        price_max = price_levels[-1]
        price_range = price_max - price_min

        if price_range <= 0:
            return "unknown"

        strongest_peak = peaks[0]["price"]
        position_pct = (strongest_peak - price_min) / price_range

        if position_pct < 0.33:
            return "low"
        elif position_pct < 0.66:
            return "mid"
        else:
            return "high"

    def _calc_chip_distribution_ratio(self, price_levels: np.ndarray, chip_volume: np.ndarray,
                                       total: float, current_price: float) -> Tuple[float, float]:
        """计算底部/顶部筹码占比"""
        if total <= 0 or len(price_levels) == 0:
            return 0.0, 0.0

        bottom_mask = price_levels <= current_price
        top_mask = price_levels > current_price

        bottom_ratio = float(np.sum(chip_volume[bottom_mask])) / total
        top_ratio = float(np.sum(chip_volume[top_mask])) / total

        return bottom_ratio, top_ratio

    def _classify_price_vs_peak(self, peaks: List[Dict], current_price: float) -> str:
        """分类当前价与峰位的关系"""
        if not peaks:
            return "unknown"

        strongest = peaks[0]
        peak_price = strongest["price"]
        peak_width = strongest.get("width", peak_price * 0.1) or peak_price * 0.05

        if abs(current_price - peak_price) < peak_width * 0.3:
            return "at_peak"
        elif current_price > peak_price + peak_width * 0.5:
            return "above_peak"
        elif current_price < peak_price - peak_width * 0.5:
            return "below_peak"
        else:
            return "near_peak"

    def _empty_chip_metrics(self) -> Dict:
        return {
            "cr10": 0.0,
            "peaks": [],
            "is_single_peak": False,
            "is_double_peak": False,
            "peak_positions": "unknown",
            "bottom_chips_ratio": 0.0,
            "top_chips_ratio": 0.0,
            "chip_divergence": False,
            "price_vs_peak": "unknown",
            "current_price": 0.0,
        }

    # ================================================================
    # 量价配合度分析
    # ================================================================

    def _analyze_volume_price(self, history: List[Dict], quote: Dict) -> Dict:
        """分析量价配合度"""
        if len(history) < 10:
            return self._empty_vol_price()

        closes = np.array([h["close"] for h in history[-20:]], dtype=np.float64)
        volumes = np.array([h["volume"] for h in history[-20:]], dtype=np.float64)
        highs = np.array([h["high"] for h in history[-20:]], dtype=np.float64)
        lows = np.array([h["low"] for h in history[-20:]], dtype=np.float64)

        current_price = quote.get("price", closes[-1]) or closes[-1]
        current_volume = quote.get("volume", volumes[-1]) or volumes[-1]

        vol_5 = np.mean(volumes[-5:])
        vol_20 = np.mean(volumes)

        volume_ratio = current_volume / vol_20 if vol_20 > 0 else 1.0

        price_change_5d = (closes[-1] / closes[-5] - 1) * 100 if len(closes) >= 5 else 0
        volume_change_5d = (volumes[-1] / vol_5 - 1) * 100 if vol_5 > 0 else 0

        ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else closes[-1]
        ma20 = np.mean(closes[-20:])

        breakout = False
        if current_volume > vol_20 * 1.3 and current_price > ma20 * 1.01:
            recent_high = np.max(highs[-20:])
            if current_price >= recent_high * 0.97:
                breakout = True
        elif current_volume > vol_5 * 1.2 and current_price > ma5:
            recent_high = np.max(highs[-5:])
            if current_price >= recent_high * 0.98:
                breakout = True

        shrink_pullback = False
        if len(closes) >= 5:
            if (abs(current_price - ma20) / ma20 < 0.03 and
                    current_volume < vol_20 * 0.7 and
                    current_price >= ma20 * 0.95):
                shrink_pullback = True
            elif (abs(current_price - ma5) / ma5 < 0.02 and
                  current_volume < vol_5 * 0.7):
                shrink_pullback = True

        stagnation = False
        if current_volume > vol_20 * 1.15 and abs(price_change_5d) < 3.0:
            stagnation = True
        elif current_volume > vol_5 * 1.2 and abs(price_change_5d) < 2.0:
            stagnation = True

        divergence = False
        if len(closes) >= 20:
            price_high_20 = np.max(closes)
            vol_at_high = volumes[np.argmax(closes)]
            if (closes[-1] >= price_high_20 * 0.97 and
                    current_volume < vol_at_high * 0.6):
                divergence = True

        return {
            "volume_breakout": breakout,
            "shrink_pullback": shrink_pullback,
            "volume_stagnation": stagnation,
            "divergence": divergence,
            "volume_ratio": float(volume_ratio),
            "price_change_5d": float(price_change_5d),
            "volume_change_5d": float(volume_change_5d),
            "current_price": float(current_price),
            "ma5": float(ma5),
            "ma20": float(ma20),
            "vol_20": float(vol_20),
        }

    def _empty_vol_price(self) -> Dict:
        return {
            "volume_breakout": False,
            "shrink_pullback": False,
            "volume_stagnation": False,
            "divergence": False,
            "volume_ratio": 1.0,
            "price_change_5d": 0.0,
            "volume_change_5d": 0.0,
            "current_price": 0.0,
            "ma20": 0.0,
            "vol_20": 0.0,
        }

    # ================================================================
    # 支撑阻力分析
    # ================================================================

    def _analyze_support_resistance(self, chip_dist: Dict, history: List[Dict],
                                     quote: Dict) -> Dict:
        """分析支撑阻力位"""
        price_levels = chip_dist.get("price_levels", np.array([]))
        chip_volume = chip_dist.get("chip_volume", np.array([]))
        total = chip_dist.get("total_chips", 0.0)

        if len(price_levels) == 0 or total <= 0 or not history:
            return self._empty_support_resistance()

        current_price = quote.get("price", history[-1]["close"]) if quote else history[-1]["close"]

        chip_density = chip_volume / total

        peak_indices = []
        for i in range(2, len(chip_density) - 2):
            if (chip_density[i] > chip_density[i - 1] and
                    chip_density[i] > chip_density[i - 2] and
                    chip_density[i] > chip_density[i + 1] and
                    chip_density[i] > chip_density[i + 2] and
                    chip_density[i] > 0.015):
                peak_indices.append(i)

        supports = []
        resistances = []

        for idx in peak_indices:
            peak_price = price_levels[idx]
            peak_density = chip_density[idx]

            left_bound = idx
            while left_bound > 0 and chip_density[left_bound] > peak_density * 0.3:
                left_bound -= 1

            right_bound = idx
            while right_bound < len(chip_density) - 1 and chip_density[right_bound] > peak_density * 0.3:
                right_bound += 1

            support = float(price_levels[left_bound])
            resistance = float(price_levels[right_bound])

            if support < current_price:
                supports.append(support)
            if resistance > current_price:
                resistances.append(resistance)

        supports = sorted(set([round(s, 2) for s in supports]), reverse=True)[:3]
        resistances = sorted(set([round(r, 2) for r in resistances]))[:3]

        nearest_support = supports[0] if supports else current_price * 0.95
        nearest_resistance = resistances[0] if resistances else current_price * 1.05

        gap_up = False
        gap_down = False
        if len(history) >= 2:
            today_open = history[-1]["open"]
            prev_high = history[-2]["high"]
            prev_low = history[-2]["low"]
            if today_open > prev_high:
                gap_up = True
            if today_open < prev_low:
                gap_down = True

        if gap_up:
            supports.append(round(prev_high, 2))
        if gap_down:
            resistances.append(round(prev_low, 2))

        supports = sorted(set(supports), reverse=True)[:3]
        resistances = sorted(set(resistances))[:3]

        price_position = "mid"
        if nearest_support > 0 and nearest_resistance > 0:
            total_range = nearest_resistance - nearest_support
            if total_range > 0:
                rel_pos = (current_price - nearest_support) / total_range
                if rel_pos < 0.3:
                    price_position = "near_support"
                elif rel_pos > 0.7:
                    price_position = "near_resistance"

        return {
            "supports": supports,
            "resistances": resistances,
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
            "gap_support": gap_up,
            "gap_resistance": gap_down,
            "price_position": price_position,
        }

    def _empty_support_resistance(self) -> Dict:
        return {
            "supports": [],
            "resistances": [],
            "nearest_support": 0.0,
            "nearest_resistance": 0.0,
            "gap_support": False,
            "gap_resistance": False,
            "price_position": "unknown",
        }

    # ================================================================
    # 评分函数
    # ================================================================

    def _score_concentration(self, chip_metrics: Dict) -> Tuple[float, List[Dict]]:
        """筹码集中度评分 (5分)"""
        items = []
        score = 0.0

        cr10 = chip_metrics.get("cr10", 0.0)
        cr_score = 0.0
        if cr10 < 0.12:
            cr_score = 2.0
        elif cr10 < 0.18:
            cr_score = 1.5
        elif cr10 < 0.25:
            cr_score = 1.0
        elif cr10 < 0.35:
            cr_score = 0.5
        else:
            cr_score = 0.0
        score += cr_score
        items.append({
            "name": "CR10集中度",
            "score": round(cr_score, 1),
            "max": 2,
            "value": f"CR10={cr10*100:.1f}%"
        })

        peak_score = 0.0
        is_single = chip_metrics.get("is_single_peak", False)
        is_double = chip_metrics.get("is_double_peak", False)
        peak_pos = chip_metrics.get("peak_positions", "unknown")

        if is_single and peak_pos == "low":
            peak_score = 2.0
        elif is_double and peak_pos in ("low", "mid"):
            peak_score = 1.5
        elif is_single and peak_pos == "mid":
            peak_score = 1.0
        elif is_double:
            peak_score = 1.0
        elif is_single and peak_pos == "high":
            peak_score = 0.0
        else:
            peak_score = 0.5
        score += peak_score
        items.append({
            "name": "峰形识别",
            "score": round(peak_score, 1),
            "max": 2,
            "value": f"{'单峰' if is_single else '双峰' if is_double else '多峰'}/{peak_pos}"
        })

        bottom_ratio = chip_metrics.get("bottom_chips_ratio", 0.0)
        bottom_score = 0.0
        if bottom_ratio > 0.65:
            bottom_score = 1.0
        elif bottom_ratio > 0.5:
            bottom_score = 0.5
        score += bottom_score
        items.append({
            "name": "底部筹码占比",
            "score": round(bottom_score, 1),
            "max": 1,
            "value": f"底部占比={bottom_ratio*100:.1f}%"
        })

        return score, items

    def _score_volume_price(self, vol_price: Dict) -> Tuple[float, List[Dict]]:
        """量价配合度评分 (5分)"""
        items = []
        score = 2.5

        breakout = vol_price.get("volume_breakout", False)
        breakout_score = 0.0
        if breakout:
            breakout_score = 2.0
        score += breakout_score
        items.append({
            "name": "放量突破",
            "score": round(breakout_score, 1),
            "max": 2,
            "value": "是" if breakout else "否"
        })

        shrink = vol_price.get("shrink_pullback", False)
        shrink_score = 0.0
        if shrink:
            shrink_score = 1.0
        score += shrink_score
        items.append({
            "name": "缩量回踩",
            "score": round(shrink_score, 1),
            "max": 1,
            "value": "是" if shrink else "否"
        })

        stagnation = vol_price.get("volume_stagnation", False)
        stagnation_penalty = 0.0
        if stagnation:
            stagnation_penalty = -1.0
        score += stagnation_penalty
        items.append({
            "name": "放量滞涨",
            "score": round(stagnation_penalty, 1),
            "max": 1,
            "value": "⚠️放量不涨" if stagnation else "正常"
        })

        divergence = vol_price.get("divergence", False)
        div_penalty = 0.0
        if divergence:
            div_penalty = -1.0
        score += div_penalty
        items.append({
            "name": "量价背离",
            "score": round(div_penalty, 1),
            "max": 1,
            "value": "⚠️顶背离" if divergence else "无"
        })

        score = max(0.0, min(5.0, score))
        return score, items

    def _score_support_resistance(self, sr: Dict, quote: Dict) -> Tuple[float, List[Dict]]:
        """支撑阻力评分 (5分)"""
        items = []
        score = 0.0

        current_price = quote.get("price", 0) if quote else 0
        supports = sr.get("supports", [])
        resistances = sr.get("resistances", [])
        nearest_support = sr.get("nearest_support", 0)
        nearest_resistance = sr.get("nearest_resistance", 0)

        support_score = 0.0
        if current_price > 0 and nearest_support > 0 and current_price > nearest_support:
            dist_to_support = (current_price - nearest_support) / current_price
            if dist_to_support < 0.03:
                support_score = 2.0
            elif dist_to_support < 0.06:
                support_score = 1.5
            elif dist_to_support < 0.10:
                support_score = 1.0
            else:
                support_score = 0.5
        score += support_score
        dist_str = f"距支撑{dist_to_support*100:.1f}%" if current_price > 0 and nearest_support > 0 else "N/A"
        items.append({
            "name": "支撑位距离",
            "score": round(support_score, 1),
            "max": 2,
            "value": dist_str
        })

        resistance_score = 0.0
        if current_price > 0 and nearest_resistance > 0 and nearest_resistance > current_price:
            dist_to_resistance = (nearest_resistance - current_price) / current_price
            if dist_to_resistance > 0.05:
                resistance_score = 1.0
            elif dist_to_resistance > 0.02:
                resistance_score = 0.5
            else:
                resistance_score = 0.0
        score += resistance_score
        items.append({
            "name": "阻力位距离",
            "score": round(resistance_score, 1),
            "max": 1,
            "value": f"距阻力{dist_to_resistance*100:.1f}%" if current_price > 0 and nearest_resistance > 0 else "N/A"
        })

        gap_score = 0.0
        if sr.get("gap_support", False):
            gap_score = 1.0
        score += gap_score
        items.append({
            "name": "缺口支撑",
            "score": round(gap_score, 1),
            "max": 1,
            "value": "跳空高开" if sr.get("gap_support") else "无"
        })

        peak_support_score = 0.0
        if sr.get("price_position") in ("near_support", "mid"):
            peak_support_score = 1.0
        score += peak_support_score
        items.append({
            "name": "密集峰支撑",
            "score": round(peak_support_score, 1),
            "max": 1,
            "value": sr.get("price_position", "unknown")
        })

        return score, items

    # ================================================================
    # 买入/卖出信号检测
    # ================================================================

    def _detect_buy_signals(self, chip_metrics: Dict, vol_price: Dict,
                            sr: Dict, quote: Dict) -> List[str]:
        """检测买入信号"""
        signals = []
        current_price = quote.get("price", 0) if quote else 0

        is_single = chip_metrics.get("is_single_peak", False)
        peak_pos = chip_metrics.get("peak_positions", "")
        cr10 = chip_metrics.get("cr10", 0)
        is_double = chip_metrics.get("is_double_peak", False)
        bottom_ratio = chip_metrics.get("bottom_chips_ratio", 0)

        breakout = vol_price.get("volume_breakout", False)
        shrink = vol_price.get("shrink_pullback", False)

        # 信号1: 低位单峰密集+放量突破
        if is_single and peak_pos == "low" and cr10 < 0.15 and breakout:
            signals.append(f"🟢 低位单峰密集+放量突破：筹码高度集中(CR10={cr10*100:.1f}%)，放量突破MA20，典型买点")

        # 信号2: 双峰下峰不破+缩量回踩
        if is_double and peak_pos in ("low", "mid") and shrink and bottom_ratio > 0.5:
            signals.append(f"🟢 双峰下峰不破+缩量回踩：下方筹码占比{bottom_ratio*100:.0f}%，缩量回踩支撑位，主力未出货")

        # 信号3: V形反转+密集峰未消耗
        price_vs_peak = chip_metrics.get("price_vs_peak", "")
        if price_vs_peak in ("above_peak", "at_peak") and bottom_ratio > 0.55 and breakout:
            signals.append(f"🟢 V形反转确认：价格突破密集峰上沿，底部筹码仍占{bottom_ratio*100:.0f}%，主力锁仓")

        # 信号4: 支撑位附近缩量止跌
        if sr.get("price_position") == "near_support" and shrink:
            nearest_support = sr.get("nearest_support", 0)
            signals.append(f"🟢 支撑位缩量止跌：当前价{current_price:.2f}接近支撑{nearest_support:.2f}，缩量回踩不破")

        return signals

    def _detect_sell_signals(self, chip_metrics: Dict, vol_price: Dict,
                              sr: Dict, quote: Dict) -> List[str]:
        """检测卖出信号"""
        signals = []
        current_price = quote.get("price", 0) if quote else 0

        is_single = chip_metrics.get("is_single_peak", False)
        peak_pos = chip_metrics.get("peak_positions", "")
        bottom_ratio = chip_metrics.get("bottom_chips_ratio", 0)
        top_ratio = chip_metrics.get("top_chips_ratio", 0)
        chip_divergence = chip_metrics.get("chip_divergence", False)
        price_vs_peak = chip_metrics.get("price_vs_peak", "")

        stagnation = vol_price.get("volume_stagnation", False)
        divergence = vol_price.get("divergence", False)

        # 信号1: 高位单峰密集+底部筹码消失
        if is_single and peak_pos == "high" and bottom_ratio < 0.3:
            signals.append(f"🔴 高位单峰密集+底部筹码消失：高位密集且底部筹码仅{bottom_ratio*100:.0f}%，主力派发风险")

        # 信号2: 筹码发散+放量滞涨
        if chip_divergence and stagnation:
            signals.append("🔴 筹码发散+放量滞涨：CR10低集中度，放量不涨，典型出货信号")

        # 信号3: 上峰不移下跌不止
        if price_vs_peak == "below_peak" and top_ratio > 0.4:
            signals.append(f"🔴 上峰不移下跌不止：价格跌破密集峰下沿，上方套牢盘占比{top_ratio*100:.0f}%，抛压沉重")

        # 信号4: 量价顶背离
        if divergence:
            signals.append("🔴 量价顶背离：价格新高但成交量萎缩，上涨动能衰竭")

        # 信号5: 阻力位附近
        if sr.get("price_position") == "near_resistance":
            nearest_resistance = sr.get("nearest_resistance", 0)
            signals.append(f"🟡 接近阻力位：当前价{current_price:.2f}接近阻力{nearest_resistance:.2f}，注意回调风险")

        return signals

    # ================================================================
    # 工具函数
    # ================================================================

    def _fallback_result(self, reason: str) -> Dict:
        return {
            "score": 7.5,
            "max": 15,
            "items": [
                {"name": "数据质量", "score": 0, "max": 0, "value": reason}
            ],
            "signals": [],
            "buy_signals": [],
            "sell_signals": [],
            "data_quality": {
                "source": "降级模式",
                "history_days": 0,
                "note": reason,
            },
        }