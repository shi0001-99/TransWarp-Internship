#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金面 & 行为学打分模块
基于量价分析、行为金融学和筹码结构的资金面评估

核心数据源（均为已有数据，无需新增API）：
- K线历史: open, close, high, low, volume, amount (120日)
- 实时行情: price, volume, turnover_rate, change_pct

可选增强数据源（有则加分，无则降级）：
- 北向资金: 东方财富/akshare API
- 龙虎榜: 东方财富 API

评分维度（满分20分）：
1. 主力吸筹信号 (6分): 缩量回踩均线支撑 + 放量突破 + 封板质量
2. 资金合力检测 (5分): 量价配合度（放量上涨 vs 放量滞涨）
3. 筹码健康度 (5分): 低换手横盘（锁仓）vs 高换手滞涨（出货）vs 一家独大
4. 行为学锚定信号 (4分): 52周高低点位置 + 异动成交量
"""

import numpy as np
from typing import Dict, List, Optional, Tuple


class CapitalFlowAnalyzer:
    """资金面 & 行为学打分分析器"""

    def __init__(self):
        pass

    def score(
        self,
        code: str,
        name: str,
        history: List[Dict],
        quote: Dict,
        northbound_data: Optional[Dict] = None,
        dragon_tiger_data: Optional[Dict] = None,
    ) -> Dict:
        """计算资金面 & 行为学综合打分

        Args:
            code: 股票代码
            name: 股票名称
            history: K线历史数据 (120日)
            quote: 实时行情
            northbound_data: 可选，北向资金数据（阶段2增强）
            dragon_tiger_data: 可选，龙虎榜数据（阶段2增强）

        Returns:
            {
                "score": float,       # 综合得分 (0-20)
                "max": int,           # 满分 (20)
                "items": List[Dict],  # 各维度小分
                "signals": List[str], # 信号描述（买入/卖出信号）
                "position_advice": str, # 仓位建议
                "data_quality": Dict, # 数据质量说明
            }
        """
        if not history or len(history) < 20:
            return self._fallback_result("历史数据不足(<20日)")

        # 计算技术指标
        indicators = self._calc_indicators(history, quote)

        # 四个维度评分（基础满分20）
        accumulation_score, accum_items = self._score_accumulation_signals(
            indicators, history
        )
        momentum_score, mom_items = self._score_capital_synergy(indicators, history)
        chip_score, chip_items = self._score_chip_health(indicators, history)
        behavior_score, beh_items = self._score_behavioral_anchors(indicators, history)

        base_total = accumulation_score + momentum_score + chip_score + behavior_score

        # 阶段2增强：北向资金 & 龙虎榜加分项（可选，各最高+2分）
        nb_bonus, nb_items, nb_signals = self._score_northbound_bonus(northbound_data)
        dt_bonus, dt_items, dt_signals = self._score_dragon_tiger_bonus(dragon_tiger_data)

        # 最终总分（截断在20分，加分项只提升不降低基础分）
        total = min(base_total + nb_bonus + dt_bonus, 20.0)

        # 生成信号描述
        signals = self._generate_signals(
            indicators, accumulation_score, momentum_score, chip_score, behavior_score
        )
        signals.extend(nb_signals)
        signals.extend(dt_signals)

        # 仓位建议（结合新数据）
        position_advice = self._generate_position_advice(
            total, accumulation_score, chip_score, indicators,
            northbound_data=northbound_data, dragon_tiger_data=dragon_tiger_data
        )

        items = accum_items + mom_items + chip_items + beh_items + nb_items + dt_items

        # 数据质量说明
        data_sources = ["K线历史(东方财富)", "实时行情(腾讯)"]
        if northbound_data:
            data_sources.append("北向资金(东方财富)")
        if dragon_tiger_data:
            data_sources.append("龙虎榜(东方财富)")

        return {
            "score": round(total, 1),
            "max": 20,
            "items": items,
            "signals": signals,
            "position_advice": position_advice,
            "data_quality": {
                "source": " + ".join(data_sources),
                "history_days": len(history),
                "has_northbound": northbound_data is not None,
                "has_dragon_tiger": dragon_tiger_data is not None,
                "note": "基础四维度20分 + 可选加分项" if (northbound_data or dragon_tiger_data) else "基于量价分析推断",
            },
        }

    # ================================================================
    # 技术指标计算
    # ================================================================

    @staticmethod
    def _calc_indicators(history: List[Dict], quote: Dict) -> Dict:
        """计算所有技术指标（从已有K线数据推导）"""
        closes = np.array([h["close"] for h in history], dtype=np.float64)
        highs = np.array([h["high"] for h in history], dtype=np.float64)
        lows = np.array([h["low"] for h in history], dtype=np.float64)
        volumes = np.array([h["volume"] for h in history], dtype=np.float64)

        n = len(closes)

        # 均线
        ma5 = np.mean(closes[-5:]) if n >= 5 else closes[-1]
        ma10 = np.mean(closes[-10:]) if n >= 10 else closes[-1]
        ma20 = np.mean(closes[-20:]) if n >= 20 else closes[-1]
        ma60 = np.mean(closes[-60:]) if n >= 60 else closes[-1]

        # 当前价格
        current_price = quote.get("price", closes[-1]) or closes[-1]

        # 成交量指标
        vol_5 = np.mean(volumes[-5:]) if n >= 5 else volumes[-1]
        vol_10 = np.mean(volumes[-10:]) if n >= 10 else volumes[-1]
        vol_20 = np.mean(volumes[-20:]) if n >= 20 else volumes[-1]
        vol_60 = np.mean(volumes[-60:]) if n >= 60 else volumes[-1]

        # 换手率
        turnover = quote.get("turnover_rate", 0) or 0

        # 涨跌幅
        change_pct = quote.get("change_pct", 0) or 0

        # 近期涨跌幅
        ret_5 = (closes[-1] / closes[-5] - 1) * 100 if n >= 5 else 0
        ret_10 = (closes[-1] / closes[-10] - 1) * 100 if n >= 10 else 0
        ret_20 = (closes[-1] / closes[-20] - 1) * 100 if n >= 20 else 0

        # 52周高低点
        high_52w = np.max(highs[-60:]) if n >= 60 else np.max(highs)
        low_52w = np.min(lows[-60:]) if n >= 60 else np.min(lows)
        price_position = (
            (current_price - low_52w) / (high_52w - low_52w) * 100
            if high_52w > low_52w
            else 50
        )

        # 量比
        volume_ratio = volumes[-1] / vol_20 if vol_20 > 0 else 1.0

        # 波动率
        returns = np.diff(closes[-20:]) / closes[-20:-1]
        volatility = np.std(returns) * np.sqrt(252) if len(returns) > 1 else 0

        # 连板数（连续涨停天数）
        consecutive_limit_up = 0
        for i in range(min(n, 10)):
            idx = -(i + 1)
            if idx >= -n:
                daily_ret = (closes[idx] / closes[idx - 1] - 1) * 100 if abs(idx) < n else 0
                if daily_ret >= 9.5:
                    consecutive_limit_up += 1
                else:
                    break

        # 缺口检测
        gap_up = False
        gap_down = False
        if n >= 2:
            today_open = history[-1]["open"]
            prev_high = history[-2]["high"]
            prev_low = history[-2]["low"]
            if today_open > prev_high:
                gap_up = True
            if today_open < prev_low:
                gap_down = True

        # 均线排列
        ma_alignment = "neutral"
        if current_price > ma5 > ma10 > ma20:
            ma_alignment = "bullish"
        elif current_price < ma5 < ma10 < ma20:
            ma_alignment = "bearish"

        # 回撤幅度（从近期高点）
        recent_high = np.max(highs[-20:]) if n >= 20 else np.max(highs)
        drawdown = (recent_high - current_price) / recent_high * 100 if recent_high > 0 else 0

        # 振幅
        amplitude = (highs[-1] - lows[-1]) / lows[-1] * 100 if lows[-1] > 0 else 0

        return {
            "current_price": float(current_price),
            "ma5": float(ma5),
            "ma10": float(ma10),
            "ma20": float(ma20),
            "ma60": float(ma60),
            "vol_5": float(vol_5),
            "vol_10": float(vol_10),
            "vol_20": float(vol_20),
            "vol_60": float(vol_60),
            "turnover": float(turnover),
            "change_pct": float(change_pct),
            "ret_5": float(ret_5),
            "ret_10": float(ret_10),
            "ret_20": float(ret_20),
            "high_52w": float(high_52w),
            "low_52w": float(low_52w),
            "price_position": float(price_position),
            "volume_ratio": float(volume_ratio),
            "volatility": float(volatility),
            "consecutive_limit_up": consecutive_limit_up,
            "gap_up": gap_up,
            "gap_down": gap_down,
            "ma_alignment": ma_alignment,
            "drawdown": float(drawdown),
            "amplitude": float(amplitude),
        }

    # ================================================================
    # 维度1：主力吸筹信号 (6分)
    # ================================================================

    def _score_accumulation_signals(
        self, indicators: Dict, history: List[Dict]
    ) -> Tuple[float, List[Dict]]:
        """主力吸筹信号：缩量回踩均线支撑 + 放量突破 + 封板质量"""
        score = 0.0
        items = []

        # 1.1 回踩均线支撑 (2分)
        retrace_score = 0.0
        price = indicators["current_price"]
        ma20 = indicators["ma20"]
        ma60 = indicators["ma60"]
        turnover = indicators["turnover"]

        # 回踩MA20（智能交易蓝线）
        if price >= ma20 * 0.98 and price <= ma20 * 1.02:
            if turnover > 0 and turnover < 3.0:
                retrace_score = 2.0  # 缩量回踩
            else:
                retrace_score = 1.0
        elif price >= ma60 * 0.98 and price <= ma60 * 1.02:
            retrace_score = 1.5  # 回踩MA60
        elif price > ma20:
            retrace_score = 1.0  # 站上MA20上方

        score += retrace_score
        items.append({
            "name": "回踩均线支撑",
            "score": round(retrace_score, 1),
            "max": 2,
            "value": f"价={price:.2f}/MA20={ma20:.2f}/换手={turnover:.1f}%"
        })

        # 1.2 放量突破 (2分)
        breakout_score = 0.0
        vol_ratio = indicators["volume_ratio"]
        ret_5 = indicators["ret_5"]
        ma_align = indicators["ma_alignment"]

        if vol_ratio >= 2.0 and ret_5 > 3:
            if ma_align == "bullish":
                breakout_score = 2.0  # 放量突破+均线多头
            else:
                breakout_score = 1.5
        elif vol_ratio >= 1.5 and ret_5 > 0:
            breakout_score = 1.0
        elif vol_ratio < 0.8 and ret_5 > 0:
            breakout_score = 0.5  # 缩量上涨（动力不足）

        score += breakout_score
        items.append({
            "name": "放量突破",
            "score": round(breakout_score, 1),
            "max": 2,
            "value": f"量比={vol_ratio:.2f}/5日涨幅={ret_5:.1f}%/{ma_align}"
        })

        # 1.3 封板质量 (2分)
        board_score = 0.0
        limit_up = indicators["consecutive_limit_up"]
        change_pct = indicators["change_pct"]
        amplitude = indicators["amplitude"]

        if limit_up >= 3:
            board_score = 2.0  # 3连板以上
        elif limit_up >= 2:
            board_score = 1.5
        elif limit_up >= 1:
            if change_pct >= 9.5 and amplitude < 5:
                board_score = 2.0  # 一字板/秒板
            else:
                board_score = 1.0
        elif change_pct > 5 and amplitude < 5:
            board_score = 0.5  # 强势上涨未涨停

        score += board_score
        items.append({
            "name": "封板质量",
            "score": round(board_score, 1),
            "max": 2,
            "value": f"连板={limit_up}/涨幅={change_pct:.1f}%/振幅={amplitude:.1f}%"
        })

        return min(score, 6.0), items

    # ================================================================
    # 维度2：资金合力检测 (5分)
    # ================================================================

    def _score_capital_synergy(
        self, indicators: Dict, history: List[Dict]
    ) -> Tuple[float, List[Dict]]:
        """资金合力检测：量价配合度（放量上涨=合力；放量滞涨=分歧）"""
        score = 0.0
        items = []

        # 2.1 量价配合度 (3分)
        synergy_score = 0.0
        vol_ratio = indicators["volume_ratio"]
        ret_10 = indicators["ret_10"]
        change_pct = indicators["change_pct"]
        turnover = indicators["turnover"]

        # 价涨量增（理想）
        if change_pct > 0 and vol_ratio >= 1.2:
            if ret_10 > 5:
                synergy_score = 3.0  # 中期趋势+放量配合
            else:
                synergy_score = 2.0
        # 价涨量缩（量价背离，动力不足）
        elif change_pct > 0 and vol_ratio < 0.8:
            synergy_score = 0.5  # 缩量上涨
        # 价跌量增（放量下跌，恐慌抛售）
        elif change_pct < -1 and vol_ratio >= 1.5:
            synergy_score = 0.0  # 放量滞涨/下跌
        # 横盘整理
        elif abs(change_pct) < 1 and vol_ratio >= 1.0:
            if turnover < 5:
                synergy_score = 1.5  # 温和放量整理
            else:
                synergy_score = 0.5  # 高换手整理
        else:
            synergy_score = 1.0

        score += synergy_score
        items.append({
            "name": "量价配合度",
            "score": round(synergy_score, 1),
            "max": 3,
            "value": f"量比={vol_ratio:.2f}/涨跌={change_pct:.1f}%/换手={turnover:.1f}%"
        })

        # 2.2 资金持续性 (2分)
        persistence_score = 0.0
        if len(history) >= 5:
            recent_vols = [h["volume"] for h in history[-5:]]
            recent_closes = [h["close"] for h in history[-5:]]
            vol_trend = np.mean(recent_vols[-3:]) / max(np.mean(recent_vols[:2]), 1)
            price_trend = np.mean(recent_closes[-3:]) / max(np.mean(recent_closes[:2]), 1)

            if vol_trend >= 1.2 and price_trend >= 1.02:
                persistence_score = 2.0  # 量价齐升
            elif vol_trend >= 1.0 and price_trend >= 1.0:
                persistence_score = 1.5  # 温和放量上涨
            elif vol_trend < 0.8 and price_trend >= 1.0:
                persistence_score = 0.5  # 缩量上涨
            elif vol_trend > 1.2 and price_trend < 0.98:
                persistence_score = 0.0  # 放量下跌
            else:
                persistence_score = 1.0

        score += persistence_score
        items.append({
            "name": "资金持续性",
            "score": round(persistence_score, 1),
            "max": 2,
            "value": f"3日量比={vol_trend:.2f}/3日价比={price_trend:.3f}" if len(history) >= 5 else "数据不足"
        })

        return min(score, 5.0), items

    # ================================================================
    # 维度3：筹码健康度 (5分)
    # ================================================================

    def _score_chip_health(
        self, indicators: Dict, history: List[Dict]
    ) -> Tuple[float, List[Dict]]:
        """筹码健康度：低换手横盘(锁仓) vs 高换手滞涨(出货) vs 一家独大"""
        score = 0.0
        items = []

        turnover = indicators["turnover"]
        volume_ratio = indicators["volume_ratio"]
        change_pct = indicators["change_pct"]
        drawdown = indicators["drawdown"]
        price = indicators["current_price"]
        ma20 = indicators["ma20"]

        # 3.1 锁仓检测 (2分)
        lock_score = 0.0
        if turnover > 0 and turnover < 3 and change_pct >= -1:
            if price > ma20:
                lock_score = 2.0  # 低换手站上MA20（锁仓拉升）
            else:
                lock_score = 1.5  # 低换手横盘
        elif turnover >= 3 and turnover <= 8 and change_pct > 2:
            lock_score = 1.0  # 适度换手上涨
        elif turnover > 15:
            lock_score = 0.0  # 超高换手（对倒出货风险）
        elif turnover == 0:
            lock_score = 0.5  # 停牌或无成交

        score += lock_score
        items.append({
            "name": "锁仓检测",
            "score": round(lock_score, 1),
            "max": 2,
            "value": f"换手={turnover:.1f}%/价={price:.2f}/MA20={ma20:.2f}"
        })

        # 3.2 出货检测 (2分)
        distribute_score = 0.0
        # 放量不涨（典型出货信号）
        if volume_ratio >= 2.0 and abs(change_pct) < 1:
            distribute_score = 0.0  # 放量不涨→出货
        # 放量下跌
        elif volume_ratio >= 1.5 and change_pct < -2:
            distribute_score = 0.0  # 放量下跌→恐慌
        # 缩量下跌
        elif volume_ratio < 0.8 and change_pct < -2 and drawdown < 5:
            distribute_score = 1.5  # 缩量回踩（洗盘非出货）
        # 正常调整
        elif volume_ratio < 1.0 and abs(change_pct) < 3:
            distribute_score = 2.0  # 量价正常
        else:
            distribute_score = 1.0

        score += distribute_score
        items.append({
            "name": "出货检测",
            "score": round(distribute_score, 1),
            "max": 2,
            "value": f"量比={volume_ratio:.2f}/涨跌={change_pct:.1f}%/回撤={drawdown:.1f}%"
        })

        # 3.3 一家独大检测 (1分)
        dominance_score = 0.0
        # 超高换手率 + 大额成交量 = 一家独大风险
        if turnover > 15 and volume_ratio > 2.0:
            dominance_score = 0.0  # 一家独大
        elif turnover > 10 and change_pct > 5:
            dominance_score = 0.5  # 高换手但上涨
        elif turnover > 10:
            dominance_score = 0.5
        elif turnover > 5:
            dominance_score = 1.0
        else:
            dominance_score = 1.0  # 低换手→无此风险

        score += dominance_score
        items.append({
            "name": "一家独大检测",
            "score": round(dominance_score, 1),
            "max": 1,
            "value": f"换手={turnover:.1f}%/量比={volume_ratio:.2f}"
        })

        return min(score, 5.0), items

    # ================================================================
    # 维度4：行为学锚定信号 (4分)
    # ================================================================

    def _score_behavioral_anchors(
        self, indicators: Dict, history: List[Dict]
    ) -> Tuple[float, List[Dict]]:
        """行为学锚定信号：52周位置 + 处置效应 + 锚定效应"""
        score = 0.0
        items = []

        price_position = indicators["price_position"]
        turnover = indicators["turnover"]
        change_pct = indicators["change_pct"]
        vol_ratio = indicators["volume_ratio"]
        price = indicators["current_price"]
        high_52w = indicators["high_52w"]
        low_52w = indicators["low_52w"]

        # 4.1 处置效应检测 (2分)
        # 盈利股高换手率→投资者卖出倾向强(处置效应)
        # 亏损股低换手率→投资者死扛(处置效应)
        disposition_score = 0.0
        if price_position > 70:
            # 盈利状态
            if turnover > 8 and change_pct < 0:
                disposition_score = 0.5  # 盈利+放量下跌→投资者获利了结
            elif turnover > 8 and change_pct > 0:
                disposition_score = 1.5  # 盈利+放量上涨→追涨
            else:
                disposition_score = 1.0
        elif price_position < 30:
            # 亏损状态
            if turnover < 3:
                disposition_score = 0.5  # 亏损+缩量→死扛
            elif turnover > 10 and change_pct < 0:
                disposition_score = 0.0  # 亏损+放量暴跌→恐慌出逃
            else:
                disposition_score = 1.0
        else:
            disposition_score = 2.0  # 中性状态

        score += disposition_score
        items.append({
            "name": "处置效应",
            "score": round(disposition_score, 1),
            "max": 2,
            "value": f"位置={price_position:.0f}%/换手={turnover:.1f}%/涨跌={change_pct:.1f}%"
        })

        # 4.2 锚定效应检测 (2分)
        # 价格接近52周高点→心理锚定卖出压力
        # 价格接近52周低点→心理锚定抄底意愿
        anchor_score = 0.0
        if price_position > 85:
            # 接近52周高点
            if vol_ratio < 1.0:
                anchor_score = 1.5  # 缩量创新高（健康）
            else:
                anchor_score = 1.0  # 放量创新高
        elif price_position > 70:
            # 高位区域
            if change_pct > 2 and vol_ratio > 1.0:
                anchor_score = 2.0  # 高位放量突破
            elif change_pct > 0:
                anchor_score = 1.5
            else:
                anchor_score = 1.0
        elif price_position < 20:
            # 接近52周低点
            if turnover < 3 and change_pct >= 0:
                anchor_score = 1.5  # 低位缩量企稳
            elif vol_ratio > 2 and change_pct > 0:
                anchor_score = 1.0  # 放量反弹
            else:
                anchor_score = 0.5  # 低位弱反弹
        elif price_position < 35:
            # 低位区域
            if change_pct > 2 and vol_ratio > 1.0:
                anchor_score = 1.5
            else:
                anchor_score = 1.0
        else:
            anchor_score = 2.0  # 中间区域

        score += anchor_score
        items.append({
            "name": "锚定效应",
            "score": round(anchor_score, 1),
            "max": 2,
            "value": f"52周位置={price_position:.0f}%/高={high_52w:.2f}/低={low_52w:.2f}"
        })

        return min(score, 4.0), items

    # ================================================================
    # 信号生成
    # ================================================================

    def _generate_signals(
        self, indicators: Dict,
        accum_score: float, mom_score: float,
        chip_score: float, beh_score: float
    ) -> List[str]:
        """生成资金面买卖信号"""
        signals = []

        # 买入信号
        if accum_score >= 5:
            signals.append("📈 主力吸筹信号强烈（回踩支撑+放量配合）")
        if chip_score >= 4 and indicators["turnover"] < 5:
            signals.append("🔒 筹码结构健康（低换手锁仓）")
        if indicators["consecutive_limit_up"] >= 2:
            signals.append("🚀 龙头连板（主升浪信号）")
        if indicators["gap_up"] and indicators["change_pct"] > 3:
            signals.append("⚡ 向上跳空缺口（突破信号）")
        if indicators["ma_alignment"] == "bullish" and accum_score >= 4:
            signals.append("📊 均线多头排列+资金配合")

        # 卖出/警示信号
        if indicators["volume_ratio"] >= 2.0 and abs(indicators["change_pct"]) < 1:
            signals.append("⚠️ 放量不涨（出货警示）")
        if indicators["volume_ratio"] >= 1.5 and indicators["change_pct"] < -2:
            signals.append("⛔ 放量下跌（恐慌抛售）")
        if indicators["turnover"] > 15 and accum_score < 3:
            signals.append("⚠️ 高换手+低吸筹得分（对倒出货风险）")
        if indicators["consecutive_limit_up"] == 0 and indicators["change_pct"] < -3:
            signals.append("📉 跌停/大跌（趋势破坏）")
        if indicators["price_position"] > 85 and indicators["volume_ratio"] > 2.0:
            signals.append("⚠️ 52周高位放量（获利了结压力）")

        return signals

    # ================================================================
    # 仓位建议
    # ================================================================

    def _generate_position_advice(
        self, total: float, accum_score: float, chip_score: float,
        indicators: Dict,
        northbound_data: Optional[Dict] = None,
        dragon_tiger_data: Optional[Dict] = None,
    ) -> str:
        """根据资金面得分给出仓位建议（阶段2增强：结合北向/龙虎榜数据）"""
        turnover = indicators["turnover"]
        price_pos = indicators["price_position"]

        # 阶段2增强：北向资金卖出信号 → 降级建议
        if northbound_data:
            nb_total = northbound_data.get("net_buy_total", 0)
            if nb_total < -1e8:  # 北向单日净卖≥1亿
                return "⛔ 北向资金净卖出（≥1亿），建议回避"

        # 阶段2增强：龙虎榜一家独大 → 轻仓
        if dragon_tiger_data:
            dt_net = dragon_tiger_data.get("net_buy_total", 0)
            if dt_net < 0:
                return "⛔ 龙虎榜净流出，抛压明显"

        # 一家独大→轻仓
        if turnover > 15 and total < 12:
            return "🔔 轻仓试错（高换手一家独大，游资打板成功率低）"

        # 阶段2增强：北向+龙虎榜双合力 → 提升建议
        if northbound_data and dragon_tiger_data:
            nb_consec = northbound_data.get("consecutive_buy_days", 0)
            dt_purple = dragon_tiger_data.get("purple_flag", False)
            if nb_consec >= 3 and dt_purple:
                return "✅ 强烈建仓（北向连续净买入+龙虎榜紫旗双合力）"

        # 资金合力强→重仓
        if accum_score >= 5 and chip_score >= 4:
            nb_hint = ""
            if northbound_data and northbound_data.get("consecutive_buy_days", 0) >= 3:
                nb_hint = "，北向连续买入"
            return f"✅ 可积极建仓（资金合力强，筹码结构健康{nb_hint}）"

        # 中性
        if total >= 12:
            return "⚠️ 适量配置（资金面中性偏积极）"

        # 偏弱
        if total >= 8:
            return "🔍 轻仓观察（资金面偏弱，等待确认）"

        # 回避
        return "⛔ 暂不参与（资金面信号弱或风险高）"

    # ================================================================
    # 阶段2增强：北向资金 & 龙虎榜加分项
    # ================================================================

    def _score_northbound_bonus(
        self, northbound_data: Optional[Dict]
    ) -> Tuple[float, List[Dict], List[str]]:
        """北向资金加分项（最高+2分）

        评分逻辑：
        - 连续3日净买入≥5000万 → +2分
        - 连续3日净买入但<5000万 → +1分
        - 连续2日净买入 → +0.5分
        - 净卖出 → 0分（不额外扣分，避免双重惩罚）
        - 无数据 → 0分
        """
        if not northbound_data:
            return 0.0, [], []

        items = []
        signals = []
        bonus = 0.0

        consec_days = northbound_data.get("consecutive_buy_days", 0)
        net_total = northbound_data.get("net_buy_total", 0)
        avg_daily = northbound_data.get("avg_daily_buy", 0)

        # 用户需求：连续3日净买入≥5000万 → 强信号
        if consec_days >= 3 and net_total >= 5e7:
            bonus = 2.0
            signals.append(f"💵 北向资金连续{consec_days}日净买入（累计{net_total/1e4:.0f}万）")
        elif consec_days >= 3:
            bonus = 1.0
            signals.append(f"💵 北向资金连续{consec_days}日净买入（金额较小）")
        elif consec_days >= 2:
            bonus = 0.5
            signals.append(f"💵 北向资金连续{consec_days}日净买入")
        elif net_total < -1e8:
            # 北向单日净卖≥1亿 → 卖出信号
            signals.append(f"⛔ 北向资金净卖出（{net_total/1e4:.0f}万）")

        items.append({
            "name": "北向资金(加分)",
            "score": round(bonus, 1),
            "max": 2,
            "value": f"连续{consec_days}日/累计{net_total/1e4:.0f}万/日均{avg_daily/1e4:.0f}万"
        })

        return bonus, items, signals

    def _score_dragon_tiger_bonus(
        self, dragon_tiger_data: Optional[Dict]
    ) -> Tuple[float, List[Dict], List[str]]:
        """龙虎榜加分项（最高+2分）

        评分逻辑：
        - 紫旗（机构+游资合力净流入） → +2分
        - 上榜但非紫旗，净买入为正 → +1分
        - 上榜但净卖出 → 0分
        - 未上榜/无数据 → 0分
        """
        if not dragon_tiger_data or not dragon_tiger_data.get("on_list"):
            return 0.0, [], []

        items = []
        signals = []
        bonus = 0.0

        purple_flag = dragon_tiger_data.get("purple_flag", False)
        net_buy = dragon_tiger_data.get("net_buy_total", 0)
        inst_net = dragon_tiger_data.get("institutional_net_buy", 0)
        hm_net = dragon_tiger_data.get("hot_money_net_buy", 0)

        if purple_flag:
            bonus = 2.0
            signals.append(f"🐉 龙虎榜紫旗（机构+游资合力净流入，净买{net_buy/1e4:.0f}万）")
        elif net_buy > 0:
            bonus = 1.0
            signals.append(f"🐉 龙虎榜上榜净买入（{net_buy/1e4:.0f}万）")
        elif net_buy < 0:
            signals.append(f"⚠️ 龙虎榜净流出（{net_buy/1e4:.0f}万，抛压明显）")

        items.append({
            "name": "龙虎榜(加分)",
            "score": round(bonus, 1),
            "max": 2,
            "value": f"紫旗={purple_flag}/净买{net_buy/1e4:.0f}万/机构{inst_net/1e4:.0f}万/游资{hm_net/1e4:.0f}万"
        })

        return bonus, items, signals

    # ================================================================
    # 回退逻辑
    # ================================================================

    @staticmethod
    def _fallback_result(reason: str) -> Dict:
        return {
            "score": 10.0,
            "max": 20,
            "items": [
                {"name": "资金面(降级)", "score": 10.0, "max": 20, "value": reason}
            ],
            "signals": [],
            "position_advice": "⚪ 资金面数据不足，建议保守仓位",
            "data_quality": {
                "source": "降级模式",
                "note": reason,
            },
        }
