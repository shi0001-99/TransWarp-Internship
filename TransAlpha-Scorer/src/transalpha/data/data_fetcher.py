import os

os.environ["NO_PROXY"] = "eastmoney.com,push2.eastmoney.com,search-codetable.eastmoney.com,baostock.com,127.0.0.1,localhost"
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""

import efinance as ef
import baostock as bs
import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import RLock
from typing import Dict, Optional
from datetime import datetime, timedelta
from ..logger import get_logger

session = requests.Session()
session.trust_env = False

ef.session = session

logger = get_logger(__name__)


class DataFetcher:
    def __init__(self):
        self._bs_logged_in = False
        self._bs_lock = RLock()
        self._cached_base_info = {}
        self._cached_industry_pe_pb = {}

    def _bs_login(self):
        with self._bs_lock:
            if not self._bs_logged_in:
                lg = bs.login()
                if lg.error_code != "0":
                    raise ConnectionError(f"baostock login failed: {lg.error_msg}")
                self._bs_logged_in = True

    def _bs_query(self, query_func, *args, **kwargs):
        with self._bs_lock:
            self._bs_login()
            rs = query_func(*args, **kwargs)
            rows = []
            while (rs.error_code == "0") and rs.next():
                rows.append(rs.get_row_data())
            return rows

    @staticmethod
    def _normalize_code(stock_code: str) -> str:
        return stock_code.replace(".SZ", "").replace(".SH", "").replace(".BJ", "").strip()

    @staticmethod
    def _to_bs_code(code: str) -> str:
        c = DataFetcher._normalize_code(code)
        return f"sh.{c}" if c.startswith("6") or c.startswith("9") else f"sz.{c}"

    @staticmethod
    def _current_year() -> int:
        return datetime.now().year

    def _get_years(self, n: int = 5):
        y = self._current_year()
        return [(y - i, 4) for i in range(n)]

    def fetch_stock_basic_info(self, stock_code: str) -> Dict:
        code = self._normalize_code(stock_code)
        if code in self._cached_base_info:
            return self._cached_base_info[code]
        try:
            df = ef.stock.get_base_info([code])
            if df is None or df.empty:
                return self._empty_basic_info(stock_code)
            row = df.iloc[0]
            info = {
                "stock_code": stock_code,
                "stock_name": str(row.get("股票名称", "")),
                "industry": str(row.get("所处行业", "")),
                "industry_code": str(row.get("板块编号", "")),
                "is_st": "ST" in str(row.get("股票名称", "")),
                "_pe": self._safe_float(row.get("市盈率(动)")),
                "_pb": self._safe_float(row.get("市净率")),
                "_roe": self._safe_float(row.get("ROE")),
                "_net_margin": self._safe_float(row.get("净利率")),
            }
            gm = self._safe_float(row.get("毛利率"))
            info["_gross_margin"] = gm if gm is not None and gm > 0 else None
            self._cached_base_info[code] = info
            return info
        except Exception as e:
            logger.warning("fetch_stock_basic_info(%s) failed: %s", stock_code, e)
            return self._empty_basic_info(stock_code)

    def _empty_basic_info(self, stock_code: str) -> Dict:
        return {"stock_code": stock_code, "stock_name": "", "industry": "", "industry_code": "", "is_st": False}

    def fetch_financial_data(self, stock_code: str) -> Dict:
        code = self._normalize_code(stock_code)
        result = {
            "pe_ttm": None, "pb": None, "ps": None, "roe_ttm": None,
            "roe_history": [], "gross_margin": None, "gross_margin_history": [],
            "net_margin": None, "net_margin_history": [], "debt_ratio": None,
            "operating_cash_flow": None, "operating_cash_flow_history": [],
            "revenue_history": [], "net_profit_history": [], "consecutive_loss_years": 0,
        }
        info = self.fetch_stock_basic_info(stock_code)
        result["pe_ttm"] = info.get("_pe")
        result["pb"] = info.get("_pb")
        result["roe_ttm"] = info.get("_roe")
        result["gross_margin"] = info.get("_gross_margin")
        result["net_margin"] = info.get("_net_margin")

        self._load_baostock_financials(code, result)
        self._load_historical_financials(code, result)
        return result

    def _load_baostock_financials(self, code: str, result: Dict):
        try:
            bs_code = self._to_bs_code(code)
            y = self._current_year()
            rows = self._bs_query(bs.query_balance_data, code=bs_code, year=y, quarter=4)
            for row in rows:
                if len(row) >= 9:
                    result["debt_ratio"] = self._safe_float(row[8])
                    break
            rows2 = self._bs_query(bs.query_cash_flow_data, code=bs_code, year=y, quarter=4)
            for row in rows2:
                if len(row) >= 9:
                    result["operating_cash_flow"] = self._safe_float(row[7])
                    break
        except Exception as e:
            logger.warning("_load_baostock_financials(%s) failed: %s", code, e)

    def _load_historical_financials(self, code: str, result: Dict):
        try:
            bs_code = self._to_bs_code(code)
            roe_hist, revenue_hist, net_profit_hist, cf_hist = [], [], [], []
            years = self._get_years(5)
            for year, quarter in years:
                profit_rows = self._bs_query(bs.query_profit_data, code=bs_code, year=year, quarter=quarter)
                for row in profit_rows:
                    if len(row) >= 7:
                        revenue_hist.append(self._safe_float(row[3]))
                        net_profit_hist.append(self._safe_float(row[6]))
                oper_rows = self._bs_query(bs.query_operation_data, code=bs_code, year=year, quarter=quarter)
                for row in oper_rows:
                    if len(row) >= 9:
                        roe_hist.append(self._safe_float(row[8]))
                cf_rows = self._bs_query(bs.query_cash_flow_data, code=bs_code, year=year, quarter=quarter)
                for row in cf_rows:
                    if len(row) >= 9:
                        cf_hist.append(self._safe_float(row[7]))
            result["roe_history"] = [v for v in roe_hist if v is not None]
            result["revenue_history"] = [v for v in revenue_hist if v is not None]
            result["net_profit_history"] = [v for v in net_profit_hist if v is not None]
            result["operating_cash_flow_history"] = [v for v in cf_hist if v is not None]
            consecutive = 0
            for v in net_profit_hist:
                if v is not None and v < 0:
                    consecutive += 1
                else:
                    break
            result["consecutive_loss_years"] = consecutive
        except Exception as e:
            logger.warning("_load_historical_financials(%s) failed: %s", code, e)

    def fetch_market_data(self, stock_code: str) -> Dict:
        code = self._normalize_code(stock_code)
        result = {"five_day_return": None, "twenty_day_return": None, "sixty_day_return": None,
                  "three_day_return": None, "turnover_rate": None, "fund_inflow_days": None, "main_fund_flow": None}
        bs_code = self._to_bs_code(code)
        today_s = datetime.now().strftime("%Y-%m-%d")
        start_3m = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        try:
            klines = self._bs_query(bs.query_history_k_data_plus, bs_code, "date,close,turn,pctChg",
                                    start_date=start_3m, end_date=today_s, frequency="d", adjustflag="2")
            closes, turns, pct_chgs = [], [], []
            for row in klines:
                if len(row) >= 4:
                    if row[1]:
                        closes.append(float(row[1]))
                    if row[2]:
                        turns.append(float(row[2]))
                    if row[3]:
                        pct_chgs.append(float(row[3]))
            if len(closes) >= 60:
                result["sixty_day_return"] = round((closes[-1] / closes[-60] - 1) * 100, 2)
            if len(closes) >= 20:
                result["twenty_day_return"] = round((closes[-1] / closes[-20] - 1) * 100, 2)
            if len(closes) >= 3:
                result["three_day_return"] = round((closes[-1] / closes[-3] - 1) * 100, 2)
            if len(closes) >= 5:
                result["five_day_return"] = round((closes[-1] / closes[-5] - 1) * 100, 2)
            if turns:
                result["turnover_rate"] = round(turns[-1], 2)
            if pct_chgs:
                result["fund_inflow_days"] = sum(1 for c in pct_chgs[-5:] if c > 0)
        except Exception as e:
            logger.warning("fetch_market_data K-line(%s) failed: %s", stock_code, e)
        try:
            snap = ef.stock.get_latest_quote(code)
            if snap is not None and not snap.empty:
                row = snap.iloc[0]
                chg_pct = self._safe_float(row.get("涨跌幅"))
                if chg_pct is not None:
                    result["main_fund_flow"] = chg_pct
        except Exception as e:
            logger.warning("fetch_market_data latest_quote(%s) failed: %s", stock_code, e)
        return result

    def fetch_industry_data(self, industry_code: str, stock_code: str = "", industry_name: str = "") -> Dict:
        result = {"pe_percentiles": [], "pb_percentiles": [], "industry_stocks": [],
                  "pe_percentile": None, "pb_percentile": None}
        lookup_key = industry_code or industry_name.replace(" ", "")
        if not lookup_key:
            return result
        if lookup_key in self._cached_industry_pe_pb:
            cached = self._cached_industry_pe_pb[lookup_key]
            return self._calc_percentiles(cached, stock_code, result)
        try:
            members = ef.stock.get_members(industry_code)
            if (members is None or members.empty) and industry_name:
                members = ef.stock.get_members(industry_name.replace(" ", ""))
            if members is None or members.empty:
                members = ef.stock.get_members(industry_name)
            if members is None or members.empty:
                self._fetch_industry_from_eastmoney(industry_name, result)
                return result
            codes = list(members.iloc[:, 2].astype(str))
            chunks = [codes[i:i + 50] for i in range(0, len(codes), 50)]
            pe_list, pb_list = [], []
            for chunk in chunks:
                try:
                    info_df = ef.stock.get_base_info(chunk)
                    if info_df is not None and not info_df.empty:
                        for _, r in info_df.iterrows():
                            pe = self._safe_float(r.get("市盈率(动)"))
                            pb = self._safe_float(r.get("市净率"))
                            if pe is not None and pe > 0:
                                pe_list.append(pe)
                            if pb is not None and pb > 0:
                                pb_list.append(pb)
                except Exception as e:
                    logger.warning("fetch_industry_data chunk failed: %s", e)
            cached = {"pe_list": pe_list, "pb_list": pb_list}
            self._cached_industry_pe_pb[lookup_key] = cached
            return self._calc_percentiles(cached, stock_code, result)
        except Exception as e:
            logger.warning("fetch_industry_data(%s) failed: %s", lookup_key, e)
            self._fetch_industry_from_eastmoney(industry_name, result)
        return result

    def _fetch_industry_from_eastmoney(self, industry_name: str, result: Dict):
        try:
            url = f"http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=200&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:90+t:2,m:90+t:23&fields=f12,f20,f25&secid=&_={int(datetime.now().timestamp() * 1000)}"
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("data", {}).get("diff"):
                    items = data["data"]["diff"]
                    pe_list = []
                    for item in items[:50]:
                        pe = self._safe_float(item.get("f20"))
                        if pe is not None and pe > 0:
                            pe_list.append(pe)
                    if pe_list:
                        result["pe_percentiles"] = pe_list
                        target_pe = self._safe_float(self._cached_base_info.get("", {}).get("_pe"))
                        if target_pe:
                            pct = sum(1 for v in pe_list if v <= target_pe) / len(pe_list) * 100
                            result["pe_percentile"] = round(pct, 1)
        except Exception as e:
            logger.warning("_fetch_industry_from_eastmoney(%s) failed: %s", industry_name, e)

    def _calc_percentiles(self, cached: Dict, stock_code: str, result: Dict) -> Dict:
        target_pe = self._safe_float(self._cached_base_info.get(self._normalize_code(stock_code), {}).get("_pe"))
        target_pb = self._safe_float(self._cached_base_info.get(self._normalize_code(stock_code), {}).get("_pb"))
        if target_pe is not None and cached.get("pe_list"):
            pct = sum(1 for v in cached["pe_list"] if v is not None and v <= target_pe) / len(cached["pe_list"]) * 100
            result["pe_percentile"] = round(pct, 1)
        if target_pb is not None and cached.get("pb_list"):
            pct = sum(1 for v in cached["pb_list"] if v is not None and v <= target_pb) / len(cached["pb_list"]) * 100
            result["pb_percentile"] = round(pct, 1)
        return result

    def fetch_macro_data(self) -> Dict:
        result = {"gdp_growth": None, "pmi": None, "m2_growth": None, "policy_score": None}
        try:
            rows = self._bs_query(bs.query_money_supply_data_year)
            if rows:
                latest = rows[-1]
                if len(latest) >= 3 and latest[2]:
                    result["m2_growth"] = round(float(latest[2]), 2)
        except Exception as e:
            logger.warning("fetch_macro_data baostock M2 failed: %s", e)
        try:
            sh_data = ef.stock.get_latest_quote("000001")
            if sh_data is not None and not sh_data.empty:
                row = sh_data.iloc[0]
                sh_change = self._safe_float(row.get("涨跌幅"))
                if sh_change is not None:
                    result["policy_score"] = 7 if sh_change > 1 else (6 if sh_change >= 0 else 5)
        except Exception as e:
            logger.warning("fetch_macro_data sh000001 failed: %s", e)
        if result["policy_score"] is None:
            result["policy_score"] = 5
        return result

    def fetch_fund_flow_data(self, stock_code: str) -> Dict:
        code = self._normalize_code(stock_code)
        result = {"northbound_flow": None, "margin_balance": None, "main_fund_flow": None, "stock_fund_flow": None}
        try:
            snap = ef.stock.get_latest_quote(code)
            if snap is not None and not snap.empty:
                row = snap.iloc[0]
                result["stock_fund_flow"] = self._safe_float(row.get("主力净流入"))
                result["main_fund_flow"] = self._safe_float(row.get("涨跌幅"))
        except Exception as e:
            logger.warning("fetch_fund_flow_data latest_quote(%s) failed: %s", stock_code, e)
        try:
            today_bill = ef.stock.get_today_bill()
            if today_bill is not None and not today_bill.empty:
                for _, row in today_bill.iterrows():
                    name = str(row.get("名称", ""))
                    if "北向资金" in name or "沪股通" in name or "深股通" in name:
                        result["northbound_flow"] = self._safe_float(row.get("净流入"))
                        break
        except Exception as e:
            logger.warning("fetch_fund_flow_data today_bill failed: %s", e)
        try:
            margin_url = "https://push2.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f57,f58,f116,f117,f118,f119,f120,f121,f122,f123,f124,f125"
            resp = session.get(margin_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("data"):
                    result["margin_balance"] = self._safe_float(data["data"].get("f117"))
        except Exception as e:
            logger.warning("fetch_fund_flow_data margin failed: %s", e)
        return result

    def fetch_event_data(self, stock_code: str) -> Dict:
        code = self._normalize_code(stock_code)
        result = {"earnings_surprise": None, "recent_events": [], "event_score": None}
        try:
            news_url = f"http://search-codetable.eastmoney.com/api/suggest/get?input={code}&type=14&token=D43BF722C8E33BDC906FB84D85EBEF13&count=10"
            resp = session.get(news_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("result", {}).get("items"):
                    items = data["result"]["items"]
                    for item in items[:5]:
                        if isinstance(item, dict):
                            title = item.get("Title", "")
                            if title:
                                result["recent_events"].append(title)
        except Exception as e:
            logger.warning("fetch_event_data(%s) failed: %s", stock_code, e)
        if result["recent_events"]:
            events_str = " ".join(result["recent_events"])
            if any(keyword in events_str for keyword in ["重大利好", "涨停", "增持", "回购", "业绩预增"]):
                result["event_score"] = 7
            elif any(keyword in events_str for keyword in ["重大利空", "跌停", "减持", "业绩预减", "问询"]):
                result["event_score"] = 3
            else:
                result["event_score"] = 5
        else:
            result["event_score"] = 5
        return result

    def get_stock_score_data(self, stock_code: str) -> Dict:
        basic_info = self.fetch_stock_basic_info(stock_code)
        financial_data = self.fetch_financial_data(stock_code)
        market_data = self.fetch_market_data(stock_code)
        macro_data = self.fetch_macro_data()
        fund_flow_data = self.fetch_fund_flow_data(stock_code)
        event_data = self.fetch_event_data(stock_code)
        industry_data = self.fetch_industry_data(basic_info.get("industry_code", ""), stock_code,
                                                 basic_info.get("industry", ""))
        return {"basic_info": basic_info, "financial": financial_data, "market": market_data,
                "industry": industry_data, "macro": macro_data, "fund_flow": fund_flow_data, "event": event_data}

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
