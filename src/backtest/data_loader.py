# -*- coding: utf-8 -*-
"""历史数据加载器（baostock 主源，聚焦历史可得的 proxy 数据）

提供四类历史数据能力，支撑强对齐的代理策略回测：
  ① 历史K线（前复权）—— 技术面因子 / 停牌 / 涨跌停
  ② 财报 + 真实公告日 pubDate —— 基本面因子（天然 PIT 对齐）
  ③ 指数历史 —— 中证500 / 沪深300 基准、宏观 proxy
  ④ 资金流 —— 东财主源 + 成交额/换手兜底（限流时降级）

设计借鉴 QuantBacktest.data 的模块化 + 多源容灾，但数据全部自 baostock 拉取，
项目自治（不依赖兄弟项目）。
"""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd

try:
    import baostock as bs
    _BS_AVAILABLE = True
except Exception:  # pragma: no cover
    _BS_AVAILABLE = False


def get_prefix(code: str) -> str:
    """6/5/9 开头=沪(sh)，0/3 开头=深(sz)。"""
    code = str(code)
    if code.startswith(("6", "5", "9")):
        return "sh"
    return "sz"


def to_bs_code(code: str) -> str:
    return f"{get_prefix(code)}.{str(code)}"


def _fmt(s: str) -> str:
    return str(s).strip() if s is not None else ""


class DataLoader:
    """baostock 历史数据加载器。"""

    def __init__(self, retries: int = 3, pause: float = 0.3):
        self.retries = retries
        self.pause = pause
        self._logged_in = False

    # ─── 生命周期 ───────────────────────────────────────────────
    def _ensure_login(self) -> None:
        if self._logged_in:
            return
        if not _BS_AVAILABLE:
            raise RuntimeError("baostock 未安装，无法加载历史数据")
        for i in range(self.retries):
            lg = bs.login()
            if lg.error_code == "0":
                self._logged_in = True
                return
            if i == self.retries - 1:
                break
            time.sleep(self.pause)
        raise RuntimeError(f"baostock 登录失败: {getattr(lg, 'error_msg', 'unknown')}")

    def logout(self) -> None:
        if self._logged_in:
            bs.logout()
            self._logged_in = False

    def _query(self, fn, *args, **kwargs) -> pd.DataFrame:
        self._ensure_login()
        rows = []
        fields = []
        for _ in range(self.retries):
            try:
                rs = fn(*args, **kwargs)
                if rs.error_code == "0":
                    fields = list(rs.fields or [])
                    while rs.next():
                        rows.append(rs.get_row_data())
                    break
            except Exception:
                pass
            time.sleep(self.pause)
        if not rows:
            return pd.DataFrame(columns=fields)
        return pd.DataFrame(rows, columns=fields)

    # ─── ① 历史K线（前复权）───────────────────────────────────
    def kline(self, code: str, start: str, end: str) -> pd.DataFrame:
        """拉取前复权日K线。

        Returns: [date, open, high, low, close, volume, amount, turn, pctChg, tradestatus, isST]
        """
        df = self._query(
            bs.query_history_k_data_plus,
            to_bs_code(code),
            "date,open,high,low,close,volume,amount,turn,pctChg,tradestatus,isST",
            start_date=start, end_date=end, frequency="d",
            adjustflag="2",  # 2=前复权
        )
        if not len(df):
            return df
        for col in ("open", "high", "low", "close", "volume", "amount", "turn", "pctChg"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in ("tradestatus", "isST"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        df["date"] = pd.to_datetime(df["date"])
        return df

    # ─── ② 财报（含公告日 pubDate）────────────────────────────
    def financial(self, code: str, year: int, quarter: int) -> pd.DataFrame:
        """取某季度财报，自带 pubDate（实际公告日）→ 天然 PIT。

        Returns: 单行 [code, pubDate, statDate, roe, net_margin, gross_margin,
                       ocf, debt_ratio, revenue, net_profit]
        """
        profit = self._query(bs.query_profit_data, code=to_bs_code(code), year=year, quarter=quarter)
        balance = self._query(bs.query_balance_data, code=to_bs_code(code), year=year, quarter=quarter)
        cash = self._query(bs.query_cash_flow_data, code=to_bs_code(code), year=year, quarter=quarter)

        anchor = profit if len(profit) else (balance if len(balance) else pd.DataFrame())
        if not len(anchor):
            return pd.DataFrame()
        pub = anchor.iloc[0].get("pubDate", "")
        stat = anchor.iloc[0].get("statDate", "")
        row = {"code": code, "pubDate": pub, "statDate": stat}

        if len(profit):
            p0 = profit.iloc[0]
            row["roe"] = self._n(p0, "roeAvg")
            row["net_margin"] = self._n(p0, "npMargin")
            row["gross_margin"] = self._n(p0, "gpMargin")
            row["profit_growth"] = self._n(p0, "dtProfit")  # 归母净利同比（若有）
            row["revenue"] = self._n(p0, "MBRevenue")
            row["net_profit"] = self._n(p0, "netProfit")
        if len(balance):
            b0 = balance.iloc[0]
            ta = self._n(b0, "totalAssets")
            liab = self._n(b0, "totalLiab")
            row["debt_ratio"] = (liab / ta) if ta else None
            row["bps"] = self._n(b0, "bsp")  # 每股净资产
        if len(cash):
            c0 = cash.iloc[0]
            row["ocf"] = self._n(c0, "netOperatingCashFlow")
        return pd.DataFrame([row])

    # ─── ③ 指数历史 ──────────────────────────────────────────
    def index_kline(self, bs_index: str, start: str, end: str) -> pd.DataFrame:
        """拉指数日K。bs_index 如 sh.000905(中证500)、sh.000300(沪深300)。"""
        df = self._query(bs.query_history_k_data_plus,
                         bs_index, "date,close",
                         start_date=start, end_date=end, frequency="d")
        if len(df):
            df["value"] = pd.to_numeric(df["close"], errors="coerce")
            df["date"] = pd.to_datetime(df["date"])
        return df

    # ─── ④ 成分股（宽池，默认中证500）────────────────────────
    def csi500_components(self, date: str) -> pd.DataFrame:
        """中证500 成分股列表（含调整日）。"""
        df = self._query(bs.query_zz500_stocks, date=date)
        if not len(df):
            return df
        # 列可能为 updateDate/code/code_name
        code_col = "code" if "code" in df.columns else ("code_name" if "code_name" in df.columns else df.columns[0])
        df["code"] = df[code_col]
        return df

    @staticmethod
    def _n(row: pd.Series, key: str) -> Optional[float]:
        v = row.get(key)
        try:
            f = float(_fmt(v))
            return f if f == f else None  # 排除 NaN
        except (TypeError, ValueError):
            return None


# 模块级便捷函数
_loader: Optional[DataLoader] = None


def get_loader() -> DataLoader:
    global _loader
    if _loader is None:
        _loader = DataLoader()
    return _loader