# -*- coding: utf-8 -*-
"""A股交易成本（移植 QuantBacktest.engine.costs 公式）。

规则:
  - 印花税：仅卖出，单向 0.05%（2023-08 起）
  - 佣金：双向 0.025%，每笔最低 5 元
  - 过户费：双向 0.001%（沪深统一简化）
  - 滑点：按成交金额比例（默认 0.1%）
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostConfig:
    stamp_tax: float = 0.0005          # 印花税（卖出）
    stamp_tax_side: str = "sell"       # 印花税方向
    commission_rate: float = 0.00025   # 佣金（双向）
    commission_min: float = 5.0        # 每笔最低佣金
    transfer_fee: float = 0.00001      # 过户费（双向）
    slippage: float = 0.001            # 滑点

    @classmethod
    def from_dict(cls, d: dict) -> "CostConfig":
        return cls(
            stamp_tax=d.get("stamp_tax", 0.0005),
            stamp_tax_side=d.get("stamp_tax_side", "sell"),
            commission_rate=d.get("commission_rate", 0.00025),
            commission_min=d.get("commission_min", 5.0),
            transfer_fee=d.get("transfer_fee", 0.00001),
            slippage=d.get("slippage", 0.001),
        )


def compute_trade_cost(amount: float, side: str, cfg: CostConfig) -> float:
    """单笔交易总成本（元）。"""
    if amount <= 0:
        return 0.0
    commission = max(amount * cfg.commission_rate, cfg.commission_min)
    stamp = amount * cfg.stamp_tax if (side == cfg.stamp_tax_side or cfg.stamp_tax_side == "both") else 0.0
    transfer = amount * cfg.transfer_fee
    slip = amount * cfg.slippage
    return commission + stamp + transfer + slip


def applied_price(price: float, side: str, slippage: float) -> float:
    """考虑滑点后的成交价：买入上浮，卖出下浮。"""
    if side == "buy":
        return price * (1 + slippage)
    elif side == "sell":
        return price * (1 - slippage)
    return price