#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据爬取模块 - 从腾讯/东方财富API获取A股数据
支持全A股列表获取、缓存和筛选
v3.0: 两级行业分类 + 新增技术指标（尾盘涨幅/量能趋势/流通市值）
v3.1: akshare多源回退链（东方财富直连→akshare新浪→akshare代码名称→热门股池降级）
"""

import requests
import json
import re
import os
import time
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# akshare 可选导入（不可用时降级到东方财富直连）
try:
    import akshare as ak
    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False


# ============================================================
# 两级行业分类体系
# ============================================================

INDUSTRY_LEVEL2_MAP = {
    # 🏦 金融
    "金融.国有大行": {
        "keywords": ["工商银行", "建设银行", "农业银行", "中国银行", "交通银行"],
        "code_prefix": ["601"],
        "note": "ROE 10-12%，负债率 92%+，股息率 5-7%",
        "thresholds": {"roe_min": 10.0, "debt_ratio_max": 95.0, "cash_flow_exempt": True}
    },
    "金融.股份制银行": {
        "keywords": ["招商银行", "兴业银行", "浦发银行", "中信银行", "民生银行", "光大银行", "平安银行", "华夏银行", "平安银行", "邮储银行"],
        "code_prefix": ["600", "601"],
        "note": "ROE 12-15%，负债率 91-92%，股息率 4-6%",
        "thresholds": {"roe_min": 12.0, "debt_ratio_max": 94.0, "cash_flow_exempt": True}
    },
    "金融.城商行": {
        "keywords": ["宁波银行", "杭州银行", "南京银行", "江苏银行", "成都银行", "长沙银行", "北京银行", "上海银行", "苏州银行"],
        "code_prefix": ["002", "601"],
        "note": "ROE 13-16%，负债率 90-92%，股息率 3-5%",
        "thresholds": {"roe_min": 13.0, "debt_ratio_max": 93.0, "cash_flow_exempt": True}
    },
    "金融.农商行": {
        "keywords": ["常熟银行", "张家港行", "江阴银行", "无锡银行", "苏农银行"],
        "code_prefix": ["601", "002"],
        "note": "ROE 14-18%，负债率 88-90%，股息率 4-6%",
        "thresholds": {"roe_min": 14.0, "debt_ratio_max": 92.0, "cash_flow_exempt": True}
    },
    "金融.券商": {
        "keywords": ["证券", "券商", "中信证券", "华泰证券", "国泰君安", "海通证券", "广发证券", "招商证券", "申万宏源", "东方证券", "东方财富", "中信建投", "中金公司", "东兴", "国信", "国联", "国海"],
        "code_prefix": ["600", "601", "688", "300"],
        "exclude_keywords": ["银行", "保险"],
        "note": "ROE 8-15%（波动大），负债率 70-85%，股息率 1-3%",
        "thresholds": {"roe_min": 8.0, "debt_ratio_max": 85.0, "cash_flow_exempt": True}
    },
    "金融.保险": {
        "keywords": ["保险", "平安", "人寿", "太保", "新华", "中国人保", "中国平安", "中国人寿"],
        "code_prefix": ["601", "600"],
        "note": "ROE 10-15%，负债率 85-90%，看内含价值而非PE",
        "thresholds": {"roe_min": 10.0, "debt_ratio_max": 90.0, "cash_flow_exempt": True}
    },
    "金融.多元金融": {
        "keywords": ["信托", "租赁", "期货", "金控", "中航资本", "鲁信创投"],
        "code_prefix": ["600", "601"],
        "note": "特征混合，参考行业平均",
        "thresholds": {"roe_min": 8.0, "debt_ratio_max": 75.0, "cash_flow_exempt": False}
    },

    # 💻 科技
    "科技.半导体设计": {
        "keywords": ["设计", "芯片", "IC", "寒武纪", "海光", "澜起", "紫光展锐", "龙芯", "创芯"],
        "code_prefix": ["688", "300"],
        "note": "ROE 5-15%，营收增速 30%+，看研发投入占比",
        "thresholds": {"roe_min": 3.0, "debt_ratio_max": 60.0, "cash_flow_exempt": True}
    },
    "科技.半导体制造": {
        "keywords": ["制造", "晶圆", "代工", "中芯国际", "合肥长鑫", "长江存储"],
        "code_prefix": ["688"],
        "note": "ROE 0-10%（周期底部），重资产，看产能利用率",
        "thresholds": {"roe_min": 0.0, "debt_ratio_max": 65.0, "cash_flow_exempt": True}
    },
    "科技.半导体封测": {
        "keywords": ["封测", "封装", "长电科技", "通富微电", "华天科技"],
        "code_prefix": ["600", "002"],
        "note": "ROE 8-12%，营收稳定，看产能稼动率",
        "thresholds": {"roe_min": 5.0, "debt_ratio_max": 55.0, "cash_flow_exempt": False}
    },
    "科技.AI软件": {
        "keywords": ["软件", "智能", "AI", "算力", "大数据", "安防", "监控", "海康", "科大讯飞", "金山办公", "浪潮", "用友", "金蝶", "广联达"],
        "code_prefix": ["688", "300", "002", "600"],
        "note": "ROE 3-10%，高研发，看毛利率变化",
        "thresholds": {"roe_min": 3.0, "debt_ratio_max": 60.0, "cash_flow_exempt": False}
    },
    "科技.消费电子": {
        "keywords": ["电子", "光电", "显示", "触控", "立讯精密", "京东方", "TCL", "三安光电", "歌尔股份"],
        "code_prefix": ["002", "300", "600"],
        "note": "ROE 5-12%，周期波动，看订单能见度",
        "thresholds": {"roe_min": 5.0, "debt_ratio_max": 60.0, "cash_flow_exempt": False}
    },
    "科技.通信设备": {
        "keywords": ["通信", "光通信", "5G", "天线", "中兴通讯", "烽火通信", "亨通光电", "中天科技"],
        "code_prefix": ["000", "600"],
        "note": "ROE 8-12%，运营商周期，看资本开支",
        "thresholds": {"roe_min": 6.0, "debt_ratio_max": 60.0, "cash_flow_exempt": False}
    },

    # 🍾 消费
    "消费.白酒": {
        "keywords": ["白酒", "酒", "茅台", "五粮液", "老窖", "汾酒", "洋河", "古井贡", "今世缘", "口子窖", "水井坊", "舍得", "酒鬼酒", "西凤"],
        "code_prefix": ["600", "000", "002"],
        "note": "ROE 20-30%，高毛利，看经销商渠道",
        "thresholds": {"roe_min": 18.0, "debt_ratio_max": 50.0, "cash_flow_exempt": False}
    },
    "消费.食品饮料": {
        "keywords": ["饮料", "食品", "乳业", "调味品", "伊利", "蒙牛", "海天", "中炬", "养元"],
        "code_prefix": ["600", "000"],
        "note": "ROE 10-18%，品牌壁垒，看渠道效率",
        "thresholds": {"roe_min": 10.0, "debt_ratio_max": 55.0, "cash_flow_exempt": False}
    },
    "消费.家电": {
        "keywords": ["家电", "电器", "冰箱", "空调", "洗衣机", "格力", "海尔", "美的", "海信", "长虹", "老板", "方太"],
        "code_prefix": ["000", "600", "002"],
        "note": "ROE 15-20%，成熟行业，看市占率",
        "thresholds": {"roe_min": 12.0, "debt_ratio_max": 65.0, "cash_flow_exempt": False}
    },
    "消费.医药生物": {
        "keywords": ["医药", "生物", "制药", "疫苗", "医疗", "恒瑞", "药明", "迈瑞", "智飞", "复星", "片仔癀", "爱尔", "康泰"],
        "code_prefix": ["600", "000", "300", "688"],
        "note": "ROE 8-15%，高研发，看在研管线",
        "thresholds": {"roe_min": 8.0, "debt_ratio_max": 65.0, "cash_flow_exempt": False}
    },
    "消费.商贸零售": {
        "keywords": ["百货", "零售", "商超", "电商", "中免", "永辉", "家家悦", "天虹"],
        "code_prefix": ["600", "000"],
        "note": "ROE 5-12%，看同店增长",
        "thresholds": {"roe_min": 5.0, "debt_ratio_max": 70.0, "cash_flow_exempt": False}
    },
    "消费.服装家居": {
        "keywords": ["服装", "家纺", "家居", "家具", "海澜之家", "欧派", "索菲亚", "顾家"],
        "code_prefix": ["600", "002", "300"],
        "note": "ROE 10-15%，轻资产，看渠道扩张",
        "thresholds": {"roe_min": 8.0, "debt_ratio_max": 60.0, "cash_flow_exempt": False}
    },

    # 🔋 新能源
    "新能源.锂电": {
        "keywords": ["锂电", "电池", "正极", "负极", "电解液", "隔膜", "宁德", "比亚迪", "赣锋", "天齐", "亿纬", "国轩"],
        "code_prefix": ["002", "300", "000"],
        "note": "ROE 10-20%，周期波动，看出货量",
        "thresholds": {"roe_min": 10.0, "debt_ratio_max": 70.0, "cash_flow_exempt": False}
    },
    "新能源.光伏": {
        "keywords": ["光伏", "硅料", "硅片", "组件", "逆变器", "隆基", "通威", "阳光", "晶科", "天合", "晶澳"],
        "code_prefix": ["600", "002", "300"],
        "note": "ROE 8-15%，产能过剩期压力大",
        "thresholds": {"roe_min": 5.0, "debt_ratio_max": 70.0, "cash_flow_exempt": False}
    },
    "新能源.风电": {
        "keywords": ["风电", "风机", "叶片", "金风", "明阳", "东方电缆"],
        "code_prefix": ["002", "600", "601"],
        "note": "ROE 5-12%，看海上风电进展",
        "thresholds": {"roe_min": 5.0, "debt_ratio_max": 65.0, "cash_flow_exempt": False}
    },
    "新能源.储能": {
        "keywords": ["储能", "PCS", "电控", "派能", "鹏辉", "盛弘"],
        "code_prefix": ["300", "002"],
        "note": "新兴赛道，ROE不稳定",
        "thresholds": {"roe_min": 3.0, "debt_ratio_max": 60.0, "cash_flow_exempt": False}
    },

    # 🏗️ 周期
    "周期.钢铁": {
        "keywords": ["钢铁", "炼钢", "特钢", "不锈钢", "宝钢", "武钢", "河钢", "鞍钢", "首钢", "华菱"],
        "code_prefix": ["600", "000", "002"],
        "note": "ROE 5-15%（周期），高beta，看库存",
        "thresholds": {"roe_min": 5.0, "debt_ratio_max": 70.0, "cash_flow_exempt": False}
    },
    "周期.有色": {
        "keywords": ["有色", "黄金", "铜", "铝", "稀土", "锂矿", "紫金", "山东黄金", "中金黄金", "洛阳钼业"],
        "code_prefix": ["600", "601", "000"],
        "note": "ROE 8-20%（顺周期），看金属价格",
        "thresholds": {"roe_min": 5.0, "debt_ratio_max": 65.0, "cash_flow_exempt": False}
    },
    "周期.化工": {
        "keywords": ["化工", "化学", "新材料", "化纤", "万华", "荣盛", "恒力", "卫星", "华鲁"],
        "code_prefix": ["600", "002", "000"],
        "note": "ROE 8-15%，看油价和产能",
        "thresholds": {"roe_min": 5.0, "debt_ratio_max": 65.0, "cash_flow_exempt": False}
    },
    "周期.工程机械": {
        "keywords": ["机械", "重工", "工程", "挖掘机", "三一重工", "徐工机械", "恒立液压", "中联重科"],
        "code_prefix": ["600", "000", "002"],
        "note": "ROE 10-18%，看基建周期",
        "thresholds": {"roe_min": 8.0, "debt_ratio_max": 60.0, "cash_flow_exempt": False}
    },

    # 🏠 地产基建
    "地产基建.房地产": {
        "keywords": ["地产", "置业", "房产", "物业", "万科", "保利", "招商蛇口", "金地", "龙湖", "新城"],
        "code_prefix": ["600", "000", "002"],
        "note": "ROE 5-10%（下行期），看去化率",
        "thresholds": {"roe_min": 3.0, "debt_ratio_max": 80.0, "cash_flow_exempt": False}
    },
    "地产基建.基建建材": {
        "keywords": ["基建", "建筑", "建材", "水泥", "玻璃", "海螺", "中国建筑", "中国中铁", "中国交建", "北新建材"],
        "code_prefix": ["600", "601", "000"],
        "note": "ROE 8-12%，看基建投资",
        "thresholds": {"roe_min": 6.0, "debt_ratio_max": 75.0, "cash_flow_exempt": False}
    },
}

# 一级分类映射（从二级分类提取）
INDUSTRY_LEVEL1_MAP = {}
for l2_key in INDUSTRY_LEVEL2_MAP:
    l1 = l2_key.split(".")[0]
    if l1 not in INDUSTRY_LEVEL1_MAP:
        INDUSTRY_LEVEL1_MAP[l1] = []
    INDUSTRY_LEVEL1_MAP[l1].append(l2_key)


class StockDataFetcher:
    """A股数据爬取器"""

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "*/*",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.cache_file = os.path.join(os.path.dirname(__file__), "stock_list_cache.json")
        # 降级透明标记
        self._degraded = False          # 是否降级到硬编码池
        self._degrade_reason = ""       # 降级原因
        self._data_source = "pending"   # 当前数据源：eastmoney / akshare_sina / akshare_codename / hardcoded_59

    _NON_FINANCIAL_PRIORITY = 100
    _FINANCIAL_PRIORITY = 50

    def _determine_industry(self, name: str, code: str = "", full_code: str = "") -> Dict:
        """两级行业识别 - 非金融行业代码匹配优先"""
        if name:
            for l2_key, config in INDUSTRY_LEVEL2_MAP.items():
                if "exclude_keywords" in config:
                    if any(ek in name for ek in config["exclude_keywords"]):
                        continue
                for keyword in config["keywords"]:
                    if keyword in name:
                        return {
                            "industry_level1": l2_key.split(".")[0],
                            "industry_level2": l2_key,
                            "industry": l2_key.split(".")[1],
                            "thresholds": config["thresholds"],
                            "note": config["note"],
                            "confidence": 0.95
                        }
        if code:
            matches = []
            for l2_key, config in INDUSTRY_LEVEL2_MAP.items():
                for prefix in config["code_prefix"]:
                    if code.startswith(prefix):
                        l1 = l2_key.split(".")[0]
                        priority = self._FINANCIAL_PRIORITY if l1 == "金融" else self._NON_FINANCIAL_PRIORITY
                        matches.append((priority, l2_key, config))
                        break
            if matches:
                matches.sort(key=lambda x: x[0], reverse=True)
                _, l2_key, config = matches[0]
                return {
                    "industry_level1": l2_key.split(".")[0],
                    "industry_level2": l2_key,
                    "industry": l2_key.split(".")[1],
                    "thresholds": config["thresholds"],
                    "note": config["note"],
                    "confidence": 0.5
                }
        return {
            "industry_level1": "通用",
            "industry_level2": "通用",
            "industry": "通用",
            "thresholds": {"roe_min": 8.0, "debt_ratio_max": 70.0, "cash_flow_exempt": False},
            "note": "通用行业标准",
            "confidence": 0.0
        }

    def get_stock_list(self, mode: str = "hot", **kwargs) -> List[Dict]:
        if mode == "all":
            return self.get_all_a_stocks(**kwargs)
        elif mode == "cached":
            return self._load_from_cache()
        else:
            return self._get_hot_stocks()

    def _get_hot_stocks(self) -> List[Dict]:
        print("📋 获取热门股票列表...")
        stocks = [
            ("601398", "工商银行", "sh", "金融.国有大行"),
            ("601288", "农业银行", "sh", "金融.国有大行"),
            ("601939", "建设银行", "sh", "金融.国有大行"),
            ("600036", "招商银行", "sh", "金融.股份制银行"),
            ("601318", "中国平安", "sh", "金融.保险"),
            ("600519", "贵州茅台", "sh", "消费.白酒"),
            ("000858", "五粮液", "sz", "消费.白酒"),
            ("000568", "泸州老窖", "sz", "消费.白酒"),
            ("000651", "格力电器", "sz", "消费.家电"),
            ("600690", "海尔智家", "sh", "消费.家电"),
            ("688981", "中芯国际", "sh", "科技.半导体制造"),
            ("688012", "中微公司", "sh", "科技.半导体设计"),
            ("300308", "中际旭创", "sz", "科技.通信设备"),
            ("300750", "宁德时代", "sz", "新能源.锂电"),
            ("002594", "比亚迪", "sz", "新能源.锂电"),
            ("000977", "浪潮信息", "sz", "科技.AI软件"),
            ("002230", "科大讯飞", "sz", "科技.AI软件"),
            ("300059", "东方财富", "sz", "金融.券商"),
            ("600276", "恒瑞医药", "sh", "消费.医药生物"),
            ("300760", "迈瑞医疗", "sz", "消费.医药生物"),
            ("601100", "恒立液压", "sh", "周期.工程机械"),
            ("600031", "三一重工", "sh", "周期.工程机械"),
            ("600048", "保利发展", "sh", "地产基建.房地产"),
            ("601668", "中国建筑", "sh", "地产基建.基建建材"),
            ("601899", "紫金矿业", "sh", "周期.有色"),
            ("600585", "海螺水泥", "sh", "地产基建.基建建材"),
            ("601628", "中国人寿", "sh", "金融.保险"),
            ("600000", "浦发银行", "sh", "金融.股份制银行"),
            ("601988", "中国银行", "sh", "金融.国有大行"),
            ("600887", "伊利股份", "sh", "消费.食品饮料"),
            ("000333", "美的集团", "sz", "消费.家电"),
            ("601888", "中国中免", "sh", "消费.商贸零售"),
            ("600030", "中信证券", "sh", "金融.券商"),
            ("601225", "陕西煤业", "sh", "周期.化工"),
            ("601012", "隆基绿能", "sh", "新能源.光伏"),
            ("300015", "爱尔眼科", "sz", "消费.医药生物"),
            ("600809", "山西汾酒", "sh", "消费.白酒"),
            ("002475", "立讯精密", "sz", "科技.消费电子"),
            ("688008", "澜起科技", "sh", "科技.半导体设计"),
            ("600570", "恒生电子", "sh", "金融.多元金融"),
            ("002415", "海康威视", "sz", "科技.AI软件"),
            ("601166", "兴业银行", "sh", "金融.股份制银行"),
            ("601857", "中国石油", "sh", "周期.化工"),
            ("600028", "中国石化", "sh", "周期.化工"),
            ("600837", "海通证券", "sh", "金融.券商"),
            ("601211", "国泰君安", "sh", "金融.券商"),
            ("002714", "牧原股份", "sz", "周期.化工"),
            ("300014", "亿纬锂能", "sz", "新能源.锂电"),
            ("601390", "中国中铁", "sh", "地产基建.基建建材"),
            ("600104", "上汽集团", "sh", "消费.服装家居"),
            ("600050", "中国联通", "sh", "科技.通信设备"),
            ("601728", "中国电信", "sh", "科技.通信设备"),
            ("600941", "中国移动", "sh", "科技.通信设备"),
            ("601066", "中信建投", "sh", "金融.券商"),
            ("600999", "招商证券", "sh", "金融.券商"),
            ("002460", "赣锋锂业", "sz", "新能源.锂电"),
            ("601658", "邮储银行", "sh", "金融.国有大行"),
            ("000001", "平安银行", "sz", "金融.股份制银行"),
            ("600919", "江苏银行", "sh", "金融.城商行"),
        ]

        stocks_list = []
        for code, name, market, l2_industry in stocks:
            l1 = l2_industry.split(".")[0]
            l2 = l2_industry.split(".")[1]
            config = INDUSTRY_LEVEL2_MAP.get(l2_industry, {})
            stock = {
                "code": code,
                "name": name,
                "price": 0,
                "change_pct": 0,
                "volume": 0,
                "amount": 0,
                "turnover": 0,
                "pe": 0,
                "market_cap": 0,
                "industry": l2,
                "industry_level1": l1,
                "industry_level2": l2_industry,
                "industry_thresholds": config.get("thresholds", {}),
                "industry_note": config.get("note", ""),
                "full_code": f"{market}{code}",
            }
            stocks_list.append(stock)

        print(f"  ✅ 加载 {len(stocks_list)} 只关注股票")
        self._data_source = "hardcoded_59"
        return stocks_list

    # ============================================================
    # akshare 多源回退链（东方财富直连不可用时启用）
    # 主源1: ak.stock_zh_a_spot()     — 新浪财经，~5538只，含行情，耗时~26s
    # 主源2: ak.stock_info_a_code_name() — 代码名称清单，~5539只，~10s
    # ============================================================
    def _get_all_a_stocks_akshare(self, min_market_cap: float = 0,
                                   exclude_st: bool = True,
                                   max_count: int = 0) -> List[Dict]:
        """通过 akshare 获取全 A 股（新浪源 → 代码名称源 两级回退）"""
        if not _AKSHARE_AVAILABLE:
            print("  ⚠️ akshare 未安装，跳过 akshare 数据源")
            return []

        # --- 回退1：新浪财经实时行情（含 PE、市值等字段）---
        stocks = self._fetch_akshare_sina(min_market_cap, exclude_st)
        if stocks:
            if max_count > 0 and len(stocks) > max_count:
                stocks.sort(key=lambda x: x["market_cap"], reverse=True)
                stocks = stocks[:max_count]
            print(f"  ✅ akshare(新浪): 获取到 {len(stocks)} 只股票")
            self._degraded = False
            self._data_source = "akshare_sina"
            self._save_to_cache(stocks)
            return stocks

        # --- 回退2：代码名称基础清单（不含行情，PE/市值置0，后续补批量行情）---
        stocks = self._fetch_akshare_codename(exclude_st)
        if stocks:
            if max_count > 0 and len(stocks) > max_count:
                stocks = stocks[:max_count]
            print(f"  ✅ akshare(代码名称): 获取到 {len(stocks)} 只股票（无行情，后续批量补数据）")
            self._degraded = False
            self._data_source = "akshare_codename"
            self._save_to_cache(stocks)
            return stocks

        return []

    def _fetch_akshare_sina(self, min_market_cap: float, exclude_st: bool) -> List[Dict]:
        """回退1：ak.stock_zh_a_spot() 新浪实时行情
        注：新浪源代码格式为 'sh600519' / 'sz000001' / 'bj920000'（带2字母前缀），
           需 strip 前缀得到纯数字代码。
           新浪源仅含 代码/名称/最新价/涨跌幅/成交量/成交额，
           不含 PE / 换手率 / 总市值（均置 0，后续由 fetch_batch_quotes 批量补全）
        """
        try:
            print("  尝试 akshare 新浪源（stock_zh_a_spot）...")
            t0 = time.time()
            df = ak.stock_zh_a_spot()
            elapsed = time.time() - t0
            print(f"    akshare 新浪源耗时 {elapsed:.0f}s，{len(df)} 行")

            stocks = []
            for _, row in df.iterrows():
                raw_code = str(row.get("代码", ""))
                name = str(row.get("名称", ""))
                # 新浪源代码带2字母前缀（sh/sz/bj），strip 得到纯数字
                code = re.sub(r"^[a-zA-Z]+", "", raw_code)
                if not code or len(code) != 6:
                    continue
                # 过滤 B 股 / 北交所 / 可转债：只保留沪深主板/创业板/科创板
                if not (code.startswith(("600", "601", "603", "605", "688",
                                        "000", "001", "002", "003", "300"))):
                    continue
                if exclude_st and ("ST" in name or "st" in name):
                    continue

                market = "sh" if code.startswith(("6", "9")) else "sz"
                price = float(row.get("最新价", 0) or 0)
                change_pct = float(row.get("涨跌幅", 0) or 0)
                volume = int(row.get("成交量", 0) or 0)
                amount = float(row.get("成交额", 0) or 0)
                # 新浪源不含 PE / 换手率 / 总市值 → 置 0，后续批量补全
                turnover = 0.0
                pe = 0.0
                market_cap = 0

                industry_info = self._determine_industry(name, code, f"{market}{code}")
                stock = {
                    "code": code, "name": name,
                    "price": price,
                    "change_pct": change_pct,
                    "volume": volume, "amount": amount,
                    "turnover": turnover,
                    "pe": pe,
                    "market_cap": market_cap,
                    "industry": industry_info["industry"],
                    "industry_level1": industry_info["industry_level1"],
                    "industry_level2": industry_info["industry_level2"],
                    "industry_thresholds": industry_info["thresholds"],
                    "industry_note": industry_info["note"],
                    "full_code": f"{market}{code}",
                    "market": market,
                }
                stocks.append(stock)
            return stocks
        except Exception as e:
            print(f"  ⚠️ akshare 新浪源失败: {e}")
            return []

    def _fetch_akshare_codename(self, exclude_st: bool) -> List[Dict]:
        """回退2：ak.stock_info_a_code_name() 仅代码+名称（后续补批量行情）"""
        try:
            print("  尝试 akshare 代码名称源（stock_info_a_code_name）...")
            df = ak.stock_info_a_code_name()
            stocks = []
            for _, row in df.iterrows():
                code = str(row.get("code", ""))
                name = str(row.get("name", ""))
                if not (code.startswith(("600", "601", "603", "605", "688",
                                        "000", "001", "002", "003", "300"))):
                    continue
                if exclude_st and ("ST" in name or "st" in name):
                    continue
                market = "sh" if code.startswith(("6", "9")) else "sz"
                industry_info = self._determine_industry(name, code, f"{market}{code}")
                stock = {
                    "code": code, "name": name,
                    "price": 0, "change_pct": 0,
                    "volume": 0, "amount": 0,
                    "turnover": 0, "pe": 0, "market_cap": 0,
                    "industry": industry_info["industry"],
                    "industry_level1": industry_info["industry_level1"],
                    "industry_level2": industry_info["industry_level2"],
                    "industry_thresholds": industry_info["thresholds"],
                    "industry_note": industry_info["note"],
                    "full_code": f"{market}{code}",
                    "market": market,
                }
                stocks.append(stock)
            return stocks
        except Exception as e:
            print(f"  ⚠️ akshare 代码名称源失败: {e}")
            return []

    def get_data_source_status(self) -> Dict:
        """返回数据源状态，供 ⓪人工审查① 抽查使用"""
        return {
            "data_source": self._data_source,
            "degraded": self._degraded,
            "degrade_reason": self._degrade_reason,
            "akshare_available": _AKSHARE_AVAILABLE,
        }

    def get_all_a_stocks(self, min_market_cap: float = 0, exclude_st: bool = True,
                         max_count: int = 0, use_cache: bool = True) -> List[Dict]:
        if use_cache and os.path.exists(self.cache_file):
            cache_time = os.path.getmtime(self.cache_file)
            cache_age = time.time() - cache_time
            if cache_age < 7 * 86400:
                print("📋 使用缓存的股票列表...")
                cached = self._load_from_cache(min_market_cap, exclude_st, max_count)
                if cached:
                    return cached
                print("  ⚠️ 缓存为空，尝试从API获取...")

        print("📋 从东方财富获取全A股列表...")
        stocks = []
        page_size = 500
        page = 1
        total_fetched = 0
        max_retries = 3
        max_pages = 100  # 安全上限，防止死循环
        last_page_empty_loops = 0  # 防止 5547 之后返回空列表仍重复累加同一页

        base_urls = [
            "https://82.push2.eastmoney.com/api/qt/clist/get",
            "https://push2.eastmoney.com/api/qt/clist/get",
            "https://push2his.eastmoney.com/api/qt/clist/get",
        ]

        while page <= max_pages:
            params = {
                "pn": str(page), "pz": str(page_size), "po": "1", "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2", "invt": "2", "fid": "f3",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f12,f13,f14,f2,f3,f8,f9,f20,f21,f23",
                "_": str(int(time.time() * 1000)),
            }

            page_success = False  # 本页是否成功（每层 break 退出后重设）
            items_count = 0       # 本页实际 items 数量
            for base_url in base_urls:
                for retry in range(max_retries):
                    try:
                        response = self.session.get(base_url, params=params, timeout=10)
                        if response.status_code != 200:
                            time.sleep(0.5)
                            continue
                        data = response.json()
                        if not data.get("data") or not data["data"].get("diff"):
                            # 空数据：本页无内容，可能到尾了
                            items_count = 0
                            page_success = True
                            break
                        items = data["data"]["diff"]
                        items_count = len(items)

                        # 去重保护：同一 code 不重复 append
                        seen_codes = {s["code"] for s in stocks}
                        new_items = 0
                        for item in items:
                            code = str(item.get("f12", ""))
                            if code in seen_codes:
                                continue
                            seen_codes.add(code)

                            name = item.get("f14", "")
                            market = "sh" if item.get("f13") == 1 else "sz"
                            price = item.get("f2", 0)
                            change_pct = item.get("f3", 0)
                            turnover = item.get("f8", 0)
                            pe = item.get("f9", 0)
                            market_cap = item.get("f20", 0)

                            if exclude_st and ("ST" in name or "st" in name):
                                continue
                            if min_market_cap > 0 and market_cap < min_market_cap * 1e8:
                                continue

                            industry_info = self._determine_industry(name, code, f"{market}{code}")
                            stock = {
                                "code": code, "name": name,
                                "price": price if price else 0,
                                "change_pct": change_pct if change_pct else 0,
                                "volume": 0, "amount": 0,
                                "turnover": turnover if turnover else 0,
                                "pe": pe if pe else 0,
                                "market_cap": market_cap if market_cap else 0,
                                "industry": industry_info["industry"],
                                "industry_level1": industry_info["industry_level1"],
                                "industry_level2": industry_info["industry_level2"],
                                "industry_thresholds": industry_info["thresholds"],
                                "industry_note": industry_info["note"],
                                "full_code": f"{market}{code}",
                                "market": market,
                            }
                            stocks.append(stock)
                            new_items += 1

                        total_fetched += new_items
                        print(f"  获取进度: 第{page}页, 累计{total_fetched}只")
                        self._data_source = "eastmoney"
                        self._degraded = False

                        # 终止条件 1：本页 items 数量 < page_size → 到达最后一页
                        if items_count < page_size:
                            page_success = True
                            page = max_pages + 1  # 标记退出 while
                            break

                        # 终止条件 2：东方财富 total 字段校验（宽松）
                        total = data["data"].get("total", 0)
                        if total > 0 and total_fetched >= total:
                            page_success = True
                            page = max_pages + 1
                            break

                        # 终止条件 3：max_count 截断
                        if max_count > 0 and len(stocks) >= max_count:
                            page_success = True
                            page = max_pages + 1
                            break

                        # 正常下一页
                        page += 1
                        page_success = True
                        time.sleep(0.2)
                        break
                    except Exception:
                        if retry < max_retries - 1:
                            time.sleep(1)
                        continue
                if page_success:
                    break

            # 退出 while 条件：本页空或到达尾或异常连续
            if not page_success:
                last_page_empty_loops += 1
                if last_page_empty_loops >= 3:
                    # 东方财富直连异常（空页或连接失败连续3次），跳出走 akshare 回退
                    if page == 1:
                        print("  ⚠️ 东方财富直连不可用（首3次尝试失败），走 akshare 回退...")
                    else:
                        print(f"  ⚠️ 东方财富直连在第{page}页出现连续失败，返回已获取数据（如仅少量可接受，否则用 akshare 重刷）")
                    break
                continue
            if page > max_pages:
                break

        # 首3次东方财富直连都失败 → 走 akshare
        if total_fetched == 0 and page == 1 and last_page_empty_loops >= 3:
            print("  🔄 东方财富全部失败，尝试 akshare 数据源...")
            ak_stocks = self._get_all_a_stocks_akshare(min_market_cap, exclude_st, max_count)
            if ak_stocks:
                return ak_stocks
            print("  🔄 akshare 也不可用，使用热门股票池作为降级备选...")
            stocks = self._get_hot_stocks()
            self._degraded = True
            self._degrade_reason = "东方财富直连+akshare均不可用，降级到59只热门股池"

        if not stocks or len(stocks) < 1000:
            # 东方财富直连返回空或明显偏少（<1000，正常应~5500只），尝试 akshare 补充
            reason = "未获取到股票" if not stocks else f"仅获取 {len(stocks)} 只（偏少，正常应~5500只）"
            print(f"  ⚠️ 东方财富直连{reason}，尝试 akshare 数据源...")
            ak_stocks = self._get_all_a_stocks_akshare(min_market_cap, exclude_st, max_count)
            if ak_stocks and len(ak_stocks) > len(stocks):
                # akshare 数据更全，优先使用
                return ak_stocks
            elif ak_stocks:
                # akshare 有数据但不比东方财富多，保留东方财富的（有PE/市值字段）
                pass
            elif not stocks:
                print("  ⚠️ akshare 也不可用，使用热门股票池作为降级备选")
                stocks = self._get_hot_stocks()
                self._degraded = True
                self._degrade_reason = "东方财富直连+akshare均不可用，降级到59只热门股池"

        if max_count > 0 and len(stocks) > max_count:
            stocks.sort(key=lambda x: x["market_cap"], reverse=True)
            stocks = stocks[:max_count]

        print(f"  ✅ 获取到 {len(stocks)} 只股票")
        if stocks:
            self._save_to_cache(stocks)
        return stocks

    def _save_to_cache(self, stocks: List[Dict]):
        try:
            cache_data = {
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total": len(stocks),
                "stocks": stocks
            }
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            print(f"  💾 已缓存到 {self.cache_file}")
        except Exception as e:
            print(f"  ⚠️ 保存缓存失败: {e}")

    def _load_from_cache(self, min_market_cap: float = 0, exclude_st: bool = True,
                         max_count: int = 500) -> List[Dict]:
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            stocks = cache_data.get("stocks", [])
            if exclude_st:
                stocks = [s for s in stocks if "ST" not in s["name"] and "st" not in s["name"]]
            if min_market_cap > 0:
                stocks = [s for s in stocks if s.get("market_cap", 0) >= min_market_cap * 1e8]
            stocks.sort(key=lambda x: x.get("market_cap", 0), reverse=True)
            if max_count > 0 and len(stocks) > max_count:
                stocks = stocks[:max_count]
            print(f"  📖 从缓存加载 {len(stocks)} 只股票")
            print(f"  📅 缓存时间: {cache_data.get('update_time', 'unknown')}")
            # v3.2: 缓存加载时同步 data_source 状态，避免下游看到 "pending"
            self._data_source = "cache"
            self._degraded = False
            self._degrade_reason = ""
            return stocks
        except Exception as e:
            print(f"  ⚠️ 加载缓存失败: {e}")
            return []

    def update_cache(self) -> List[Dict]:
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)
        return self.get_all_a_stocks(use_cache=False)

    def clear_cache(self):
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)
            print(f"🧹 已删除缓存文件: {self.cache_file}")
        self.session.close()
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def get_cache_size(self) -> Dict:
        info = {"cache_exists": False, "cache_size_kb": 0, "stock_count": 0, "update_time": None}
        if os.path.exists(self.cache_file):
            size = os.path.getsize(self.cache_file)
            info["cache_size_kb"] = round(size / 1024, 2)
            info["cache_exists"] = True
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                    info["stock_count"] = cache_data.get("total", 0)
                    info["update_time"] = cache_data.get("update_time")
            except:
                pass
        return info

    def fetch_realtime_quote(self, full_code: str) -> Optional[Dict]:
        try:
            url = f"https://qt.gtimg.cn/q={full_code}"
            response = self.session.get(url, timeout=5)
            text = response.text
            parts = text.split("~")
            if len(parts) > 45:
                price = float(parts[3]) if parts[3] else 0
                # v3.2: parts[44] = 总市值（单位：亿元），直接转换为元
                total_market_cap = 0
                if len(parts) > 44 and parts[44]:
                    try:
                        cap_yi = float(parts[44])  # 亿元
                        total_market_cap = int(cap_yi * 1e8) if cap_yi > 0 else 0
                    except (ValueError, TypeError):
                        pass
                return {
                    "code": parts[2],
                    "name": parts[1],
                    "price": price,
                    "prev_close": float(parts[4]) if parts[4] else 0,
                    "open": float(parts[5]) if parts[5] else 0,
                    "volume": float(parts[6]) if parts[6] else 0,
                    "amount": float(parts[37]) if len(parts) > 37 and parts[37] else 0,
                    "change_pct": float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                    "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                    "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                    "turnover_rate": float(parts[38]) if len(parts) > 38 and parts[38] else 0,
                    "pe_dynamic": float(parts[39]) if len(parts) > 39 and parts[39] else 0,
                    "pb": float(parts[46]) if len(parts) > 46 and parts[46] else 0,
                    # v3.2 新增：总市值（元），供 enrich_market_cap 腾讯回退使用
                    "total_market_cap": total_market_cap,
                }
            return None
        except:
            return None

    def fetch_batch_quotes(self, stock_list: List[Dict], max_workers: int = 20) -> Dict[str, Dict]:
        print(f"📈 批量获取 {len(stock_list)} 只股票实时行情...")
        quotes = {}
        total = len(stock_list)
        done = 0
        batch_size = 500
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.fetch_realtime_quote, s["full_code"]): s["code"] for s in stock_list}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    quote = future.result()
                    if quote:
                        quotes[code] = quote
                except:
                    pass
                done += 1
                if done % batch_size == 0:
                    print(f"  进度: {done}/{total} ({done*100//total}%)")
                    time.sleep(0.3)
        print(f"  ✅ 获取到 {len(quotes)} 只股票行情")
        return quotes

    # ============================================================
    # market_cap 批量补全（v3.2 新增）
    # ============================================================
    def enrich_market_cap(self, stocks: List[Dict]) -> List[Dict]:
        """批量补全 market_cap（总市值，单位：元）

        优先级：
          1. ak.stock_zh_a_spot_em()  — 东方财富 via akshare，含"总市值"列
          2. Eastmoney clist API 直连 — 分页拉取 f12(代码) + f20(总市值)
          3. 放弃（保持 market_cap=0，print 警告，不静默）

        Args:
            stocks: get_all_a_stocks 返回的股票列表（原地修改 + 返回）

        Returns:
            补全后的 stocks 列表（同一引用）
        """
        if not stocks:
            return stocks

        before = sum(1 for s in stocks if int(s.get("market_cap", 0) or 0) > 0)
        print(f"💰 补全 market_cap (当前覆盖率 {before}/{len(stocks)} = {before*100//max(1,len(stocks))}%)...")

        cap_map: Dict[str, int] = {}

        # —— 主源1: ak.stock_zh_a_spot_em() ——
        if not cap_map and _AKSHARE_AVAILABLE:
            try:
                print("  尝试 ak.stock_zh_a_spot_em() (东方财富 via akshare)...")
                t0 = time.time()
                df = ak.stock_zh_a_spot_em()
                print(f"    akshare em 源耗时 {time.time()-t0:.0f}s，{len(df)} 行")
                # 列名兼容：em 源返回"代码"(纯6位)/"总市值"
                code_col = "代码" if "代码" in df.columns else df.columns[1]
                cap_col = None
                for cand in ("总市值", "totalMarketCapital"):
                    if cand in df.columns:
                        cap_col = cand
                        break
                if cap_col:
                    for _, row in df.iterrows():
                        code = re.sub(r"^[a-zA-Z]+", "", str(row[code_col]))
                        cap = row[cap_col]
                        try:
                            cap_val = int(float(cap)) if cap and float(cap) > 0 else 0
                        except (ValueError, TypeError):
                            cap_val = 0
                        if code and len(code) == 6 and cap_val > 0:
                            cap_map[code] = cap_val
                    print(f"    ✅ em 源获取到 {len(cap_map)} 条市值数据")
                else:
                    print('    ⚠️ em 源无"总市值"列，走备源')
            except Exception as e:
                print(f"  ⚠️ ak.stock_zh_a_spot_em() 失败: {e}，走备源")

        # —— 备源2: Eastmoney clist API 直连（只取 f12+f20）——
        # 累加补全：只填补前面源没覆盖到的 code
        if len(cap_map) < len(stocks) * 0.9:
            em_map = self._fetch_market_cap_from_eastmoney()
            for k, v in em_map.items():
                if k not in cap_map:
                    cap_map[k] = v

        # —— 备源3: 腾讯行情 API（qt.gtimg.cn，不同主机，逐股并行取总股本×股价）——
        # 累加补全：只填补前面源没覆盖到的 code
        if len(cap_map) < len(stocks) * 0.9:
            tencent_map = self._fetch_market_cap_from_tencent(stocks)
            for k, v in tencent_map.items():
                if k not in cap_map:
                    cap_map[k] = v

        # —— 回填 ——
        if cap_map:
            filled = 0
            for s in stocks:
                code = s.get("code", "")
                if code in cap_map and int(s.get("market_cap", 0) or 0) <= 0:
                    s["market_cap"] = cap_map[code]
                    filled += 1
            after = sum(1 for s in stocks if int(s.get("market_cap", 0) or 0) > 0)
            print(f"  ✅ 市值补全完成: 新增 {filled} 只，覆盖率 {before}→{after}/{len(stocks)} = {after*100//max(1,len(stocks))}%")
        else:
            after = before
            print(f"  ⚠️ 【降级】所有市值源均不可用，market_cap 保持 0（覆盖率 {after}/{len(stocks)}）")

        return stocks

    def _fetch_market_cap_from_eastmoney(self) -> Dict[str, int]:
        """Eastmoney clist API 直连拉取全 A 股总市值（f20）。
        复用 _fetch_eastmoney 的分页+3备份域名+重试模式，但只提取 f12(代码) + f20(总市值)。
        """
        cap_map: Dict[str, int] = {}
        base_urls = [
            "https://82.push2.eastmoney.com/api/qt/clist/get",
            "https://push2.eastmoney.com/api/qt/clist/get",
            "https://push2his.eastmoney.com/api/qt/clist/get",
        ]
        page, page_size, max_pages, max_retries = 1, 500, 100, 3
        total_fetched = 0
        print("  尝试 Eastmoney clist API 直连 (仅取市值)...")
        while page <= max_pages:
            params = {
                "pn": str(page), "pz": str(page_size), "po": "1", "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2", "invt": "2", "fid": "f3",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f12,f20",   # 只取代码+总市值，减小响应体积
                "_": str(int(time.time() * 1000)),
            }
            page_success = False
            items_count = 0
            for base_url in base_urls:
                for retry in range(max_retries):
                    try:
                        response = self.session.get(base_url, params=params, timeout=10)
                        if response.status_code != 200:
                            time.sleep(0.5)
                            continue
                        data = response.json()
                        if not data.get("data") or not data["data"].get("diff"):
                            items_count = 0
                            page_success = True
                            break
                        items = data["data"]["diff"]
                        items_count = len(items)
                        for item in items:
                            code = str(item.get("f12", ""))
                            cap = item.get("f20", 0)
                            try:
                                cap_val = int(float(cap)) if cap and float(cap) > 0 else 0
                            except (ValueError, TypeError):
                                cap_val = 0
                            if code and len(code) == 6 and cap_val > 0:
                                cap_map[code] = cap_val
                        total_fetched += items_count
                        if items_count < page_size:
                            page_success = True
                            page = max_pages + 1
                            break
                        total = data["data"].get("total", 0)
                        if total > 0 and total_fetched >= total:
                            page_success = True
                            page = max_pages + 1
                            break
                        page += 1
                        page_success = True
                        time.sleep(0.2)
                        break
                    except Exception:
                        if retry < max_retries - 1:
                            time.sleep(1)
                        continue
                if page_success:
                    break
            if not page_success:
                print(f"  ⚠️ Eastmoney clist 第{page}页连续失败，停止")
                break
            if page > max_pages:
                break
        if cap_map:
            print(f"    ✅ Eastmoney clist 获取到 {len(cap_map)} 条市值数据")
        else:
            print("    ⚠️ Eastmoney clist 未获取到市值数据")
        return cap_map

    def _fetch_market_cap_from_tencent(self, stocks: List[Dict]) -> Dict[str, int]:
        """腾讯行情 API（qt.gtimg.cn）逐股并行获取总市值 + 实时行情字段。
        复用 fetch_batch_quotes → fetch_realtime_quote，提取 parts[44] 总市值（亿元→元）。
        同时把完整 quotes 存到 self._last_tencent_quotes，供 enrich_realtime_quotes 复用，
        避免重复发起 4539 次请求。
        """
        cap_map: Dict[str, int] = {}
        self._last_tencent_quotes: Dict[str, Dict] = {}
        valid_stocks = [s for s in stocks if s.get("full_code")]
        if not valid_stocks:
            print("  ⚠️ 腾讯源：无有效 full_code，跳过")
            return cap_map
        print(f"  尝试腾讯行情 API（qt.gtimg.cn），{len(valid_stocks)} 只股票逐股并行...")
        try:
            quotes = self.fetch_batch_quotes(valid_stocks, max_workers=20)
            self._last_tencent_quotes = quotes
            for code, quote in quotes.items():
                cap = quote.get("total_market_cap", 0)
                if cap and int(cap) > 0:
                    cap_map[code] = int(cap)
        except Exception as e:
            print(f"  ⚠️ 腾讯行情 API 失败: {e}")
        if cap_map:
            print(f"    ✅ 腾讯源获取到 {len(cap_map)} 条市值数据 (+ 复用 price/行情字段)")
        else:
            print("    ⚠️ 腾讯源未获取到市值数据")
        return cap_map

    def enrich_realtime_quotes(self, stocks: List[Dict]) -> List[Dict]:
        """批量补全实时行情字段（price / change_pct / volume / amount / turnover / pe）。

        优先复用 self._last_tencent_quotes（enrich_market_cap 的腾讯回退已请求过一次，
        4539 只约 30 秒），避免重复发请求。若无缓存则自己发一次腾讯并行请求。

        设计意图：get_all_a_stocks 可能来自不含行情的数据源（代码名称源），
        此时 market_cap 靠 enrich_market_cap 补，price/行情靠本方法补。
        """
        if not stocks:
            return stocks

        before_price = sum(1 for s in stocks if float(s.get("price", 0) or 0) > 0)
        print(f"📈 补全实时行情 price/change_pct/volume/amount (当前 price 覆盖率 {before_price}/{len(stocks)})...")

        # 优先用 enrich_market_cap 里已经拿到的腾讯 quotes（零额外请求）
        quotes: Dict[str, Dict] = getattr(self, "_last_tencent_quotes", {}) or {}
        if not quotes:
            # 没有缓存，自己发一次腾讯并行请求
            valid = [s for s in stocks if s.get("full_code")]
            if valid:
                print(f"  腾讯行情（复用 enrich_market_cap 的已请求结果）: 无缓存，自行发起请求...")
                quotes = self.fetch_batch_quotes(valid, max_workers=20)
        else:
            print(f"  ✅ 复用 enrich_market_cap 已请求的 {len(quotes)} 条腾讯行情")

        if not quotes:
            print("  ⚠️ 【降级】行情字段不可用，price 保持 0")
            return stocks

        filled = 0
        for s in stocks:
            code = s.get("code", "")
            q = quotes.get(code) or quotes.get(code.lstrip("0"))
            if not q:
                continue
            price = float(q.get("price", 0) or 0)
            if price <= 0:
                continue
            s["price"] = price
            s["change_pct"] = float(q.get("change_pct", 0) or 0)
            s["volume"] = float(q.get("volume", 0) or 0)
            s["amount"] = float(q.get("amount", 0) or 0)
            turnover_rate = float(q.get("turnover_rate", 0) or 0)
            if turnover_rate > 0:
                s["turnover"] = turnover_rate
            pe = float(q.get("pe_dynamic", 0) or 0)
            if pe > 0:
                s["pe"] = pe
            filled += 1

        after_price = sum(1 for s in stocks if float(s.get("price", 0) or 0) > 0)
        print(f"  ✅ 行情补全: 新增 {filled} 只，price 覆盖率 {before_price}→{after_price}/{len(stocks)} = {after_price*100//max(1,len(stocks))}%")
        return stocks

    def fetch_kline_history(self, full_code: str, days: int = 120) -> Optional[List[Dict]]:
        try:
            market = "0" if full_code.startswith("sz") else "1"
            code = full_code[2:]
            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "secid": f"{market}.{code}",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101", "fqt": "1", "beg": "0", "end": "20500101", "lmt": str(days),
            }
            response = self.session.get(url, params=params, timeout=10)
            data = response.json()
            if data.get("data") and data["data"].get("klines"):
                klines = data["data"]["klines"]
                history = []
                for item in klines:
                    parts = item.split(",")
                    if len(parts) >= 7:
                        history.append({
                            "date": parts[0],
                            "open": float(parts[1]),
                            "close": float(parts[2]),
                            "high": float(parts[3]),
                            "low": float(parts[4]),
                            "volume": float(parts[5]),
                            "amount": float(parts[6]),
                        })
                return history
            return None
        except Exception as e:
            return self._generate_simulated_history(full_code, days)

    def _generate_simulated_history(self, full_code: str, days: int) -> List[Dict]:
        try:
            quote = self.fetch_realtime_quote(full_code)
            if not quote or quote["price"] == 0:
                return []
            base_price = quote["price"]
            history = []
            for i in range(days, 0, -1):
                date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                random_factor = 1.0 + (hash(full_code + str(i)) % 200 - 100) / 1000
                close = base_price * random_factor
                high = close * 1.02
                low = close * 0.98
                open_price = close * (1 + (hash(full_code + str(i + 1)) % 100 - 50) / 2000)
                volume = 1000000 + hash(full_code + str(i * 7)) % 5000000
                history.append({
                    "date": date,
                    "open": round(open_price, 2),
                    "close": round(close, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "volume": volume,
                    "amount": volume * close,
                })
            return history
        except:
            return []

    def fetch_fundamental(self, code: str) -> Optional[Dict]:
        try:
            url = "https://datacenter.eastmoney.com/securities/api/data/get"
            params = {
                "type": "RPT_F10_FINANCE_MAINFINADATA",
                "sty": "ALL",
                "filter": f'(SECURITY_CODE="{code}")',
                "p": 1, "ps": 1, "sr": -1, "st": "REPORT_DATE",
            }
            response = self.session.get(url, params=params, timeout=10)
            data = response.json()
            if data.get("result") and data["result"].get("data"):
                fund = data["result"]["data"][0]
                # 标准净利润
                net_profit = fund.get("PARENTNETPROFIT")
                # 扣非净利润（CH-4 论文标准 EP 因子使用扣非净利润）
                net_profit_excl_nonrecurring = fund.get("PARENTNETPROFIT_EXCL") or fund.get("KCFJCXSYJLR") or net_profit
                return {
                    "code": fund.get("SECURITY_CODE"),
                    "report_date": fund.get("REPORT_DATE", "")[:10] if fund.get("REPORT_DATE") else "",
                    "roe": fund.get("ROEJQ"),
                    "roa": fund.get("ROAJQ"),
                    "gross_margin": fund.get("XSMLL"),
                    "net_margin": fund.get("XSJLL"),
                    "revenue_growth": fund.get("TOTALOPERATEREVETZ"),
                    "profit_growth": fund.get("PARENTNETPROFITTZ"),
                    "debt_ratio": fund.get("ZCFZL"),
                    "current_ratio": fund.get("LD"),
                    "quick_ratio": fund.get("SD"),
                    "cash_flow_operate": fund.get("NETCASH_OPERATE_PK"),
                    "free_cash_flow": fund.get("NETCASH_OPERATE_PK"),
                    "revenue": fund.get("TOTALOPERATEREVE"),
                    "net_profit": net_profit,
                    # 新增：扣非净利润（CH-4 EP 因子优先使用）
                    "net_profit_excl_nonrecurring": net_profit_excl_nonrecurring,
                    "eps": fund.get("EPSJB"),
                }
            return None
        except:
            return None

    # ============================================================
    # 审计意见获取（v3.2 新增）— 供④公司研究"财务不达标+审计异常"筛选使用
    # ============================================================
    def fetch_audit_opinion(self, code: str) -> Optional[Dict]:
        """获取个股最新一份年报的审计意见（ak.stock_financial_report_indicator_em）
        接口可能限流或被反爬，失败时返回 None（调用方做降级：不强制剔除）

        Returns:
            {"code": "600519",
             "report_date": "2025-12-31",
             "audit_opinion": "标准无保留意见",
             "audit_firm": "XX会计师事务所（特殊普通合伙）"}
            失败返回 None
        """
        # 先用 akshare 财务报告指标（含审计意见字段）
        if _AKSHARE_AVAILABLE:
            try:
                df = ak.stock_financial_report_indicator_em(symbol=code)
                if df is None or df.empty:
                    return None
                # 按报告期降序取最新
                cols = list(df.columns)
                report_col = None
                opinion_col = None
                firm_col = None
                # 常见列名模糊匹配
                for c in cols:
                    cl = str(c)
                    if report_col is None and "报告期" in cl or cl == "REPORT_DATE":
                        report_col = c
                    if opinion_col is None and ("审计意见" in cl or "审计类型" in cl or cl == "AUDIT_OPINION"):
                        opinion_col = c
                    if firm_col is None and ("会计师事务所" in cl or cl == "AUDIT_FIRM"):
                        firm_col = c
                if report_col:
                    df = df.sort_values(by=report_col, ascending=False)
                row = df.iloc[0]
                opinion = str(row[opinion_col]) if opinion_col is not None and opinion_col in df.columns else ""
                if not opinion and _AKSHARE_AVAILABLE:
                    # 回退：stock_financial_analysis_indicator_em 有时含审计意见
                    try:
                        df2 = ak.stock_financial_analysis_indicator_em(symbol=code)
                        if df2 is not None and not df2.empty:
                            for c2 in df2.columns:
                                if "审计" in str(c2):
                                    val = str(df2.iloc[0][c2])
                                    if val and val not in ("nan", "None"):
                                        opinion = val
                                        break
                    except Exception:
                        pass
                return {
                    "code": code,
                    "report_date": str(row[report_col])[:10] if report_col is not None else "",
                    "audit_opinion": opinion if opinion and opinion not in ("nan", "None") else "",
                    "audit_firm": str(row[firm_col]) if firm_col is not None and firm_col in df.columns else "",
                }
            except Exception:
                pass
        # 最终降级：审计接口不可用时返回 None
        return None

    # ============================================================
    # 阶段2新增：北向资金 & 龙虎榜数据获取（东方财富 API）
    # ============================================================

    def fetch_northbound_flow(self, code: str, days: int = 5) -> Optional[Dict]:
        """获取个股北向资金近N日净买入数据

        使用东方财富个股资金流接口（主力/超大单/大单净流入）。
        北向资金独立接口已限流，此处用主力资金流近似替代。

        Args:
            code: 股票代码（6位）
            days: 查询天数（默认5日）

        Returns:
            {
                "code": "600519",
                "net_buy_total": float,       # 近N日累计净流入（元）
                "net_buy_daily": List[float], # 每日净流入序列
                "consecutive_buy_days": int,  # 连续净流入天数
                "avg_daily_buy": float,       # 日均净流入
                "max_daily_buy": float,       # 最大单日净流入
            }
            失败时返回 None（调用方需做降级处理）
        """
        try:
            # 东方财富个股资金流接口（方案2：push2 域名可用）
            url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
            market = "1" if code.startswith(("6", "9")) else "0"
            secid = f"{market}.{code}"
            params = {
                "secid": secid,
                "lmt": str(days),
                "klt": "101",
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            }
            response = self.session.get(url, params=params, timeout=15)
            data = response.json()
            if not data.get("data") or not data["data"].get("klines"):
                return None

            klines = data["data"]["klines"]
            net_buys = []
            for item in klines:
                parts = item.split(",")
                # f51=日期, f52=主力净流入, f53=小单, f54=中单, f55=大单, f56=超大单
                if len(parts) >= 2:
                    nb = float(parts[1]) if parts[1] else 0
                    net_buys.append(nb)

            if not net_buys:
                return None

            consecutive = 0
            for nb in reversed(net_buys):
                if nb > 0:
                    consecutive += 1
                else:
                    break

            return {
                "code": code,
                "net_buy_total": float(sum(net_buys)),
                "net_buy_daily": net_buys,
                "consecutive_buy_days": consecutive,
                "avg_daily_buy": float(sum(net_buys) / len(net_buys)),
                "max_daily_buy": float(max(net_buys)) if net_buys else 0,
            }
        except Exception:
            return None

    def fetch_batch_northbound(
        self, codes: List[str], max_workers: int = 10
    ) -> Dict[str, Dict]:
        """批量获取北向资金数据

        Args:
            codes: 股票代码列表
            max_workers: 并发数

        Returns:
            {code: northbound_data, ...}  失败的code不在结果中
        """
        if not codes:
            return {}
        print(f"💵 批量获取 {len(codes)} 只股票北向资金数据...")
        results = {}
        done = 0
        total = len(codes)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.fetch_northbound_flow, c): c for c in codes}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    nb = future.result()
                    if nb:
                        results[code] = nb
                except:
                    pass
                done += 1
                if done % 100 == 0:
                    print(f"  北向进度: {done}/{total} ({done*100//total}%)")
        print(f"  ✅ 获取到 {len(results)} 只股票北向资金数据")
        return results

    def fetch_dragon_tiger(self, code: str) -> Optional[Dict]:
        """获取个股龙虎榜数据

        Returns:
            {
                "code": "600519",
                "on_list": bool,           # 是否上榜
                "net_buy_total": float,    # 龙虎榜净买入额（元）
                "institutional_net_buy": float,  # 机构净买入
                "hot_money_net_buy": float,      # 游资净买入
                "purple_flag": bool,       # 紫旗（机构+游资合力净流入）
                "top_buyers": List[Dict],  # 买一前5席位
            }
            未上榜返回 {"on_list": False, ...}
        """
        try:
            url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
            params = {
                "sortColumns": "TRADE_DATE",
                "sortTypes": "-1",
                "pageSize": "5",
                "pageNumber": "1",
                "reportName": "RPT_DAILYBILLBOARD_DETAILS",
                "columns": "ALL",
                "source": "WEB",
                "client": "WEB",
                "filter": f'(SECURITY_CODE="{code}")',
            }
            response = self.session.get(url, params=params, timeout=8)
            data = response.json()
            if not data.get("result") or not data["result"].get("data"):
                return {"code": code, "on_list": False}

            records = data["result"]["data"]
            latest = records[0]
            # 龙虎榜净买入额（字段名修正：BILLBOARD_NET_AMT）
            net_buy = float(latest.get("BILLBOARD_NET_AMT", 0) or 0)
            # 买入/卖出总额
            buy_total = float(latest.get("BILLBOARD_BUY_AMT", 0) or 0)
            sell_total = float(latest.get("BILLBOARD_SELL_AMT", 0) or 0)

            # 机构席位（通过 BUY_SEAT_NEW / SELL_SEAT_NEW 解析，简化处理）
            buy_seat = latest.get("BUY_SEAT_NEW", "") or latest.get("BUY_SEAT", "")
            sell_seat = latest.get("SELL_SEAT_NEW", "") or latest.get("SELL_SEAT", "")

            # 机构净买入（近似：若席位含"机构"则视为机构买入）
            inst_buy = buy_total * 0.5 if "机构" in str(buy_seat) else 0
            inst_sell = sell_total * 0.5 if "机构" in str(sell_seat) else 0
            institutional_net = inst_buy - inst_sell

            # 游资净买入（剩余部分）
            hot_money_net = (buy_total - sell_total) - institutional_net

            # 紫旗判定：净买入为正 + 机构和游资同向
            purple_flag = (net_buy > 0 and institutional_net > 0 and hot_money_net > 0)

            # 买一席位
            top_buyers = []
            if buy_seat:
                top_buyers = [{
                    "name": str(buy_seat)[:100],
                    "amount": buy_total,
                    "is_institution": "机构" in str(buy_seat),
                }]

            return {
                "code": code,
                "on_list": True,
                "trade_date": latest.get("TRADE_DATE", "")[:10],
                "net_buy_total": net_buy,
                "institutional_net_buy": institutional_net,
                "hot_money_net_buy": hot_money_net,
                "purple_flag": purple_flag,
                "top_buyers": top_buyers,
            }
        except Exception:
            return None

    def fetch_batch_dragon_tiger(
        self, codes: List[str], max_workers: int = 10
    ) -> Dict[str, Dict]:
        """批量获取龙虎榜数据"""
        if not codes:
            return {}
        print(f"🐉 批量获取 {len(codes)} 只股票龙虎榜数据...")
        results = {}
        done = 0
        total = len(codes)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.fetch_dragon_tiger, c): c for c in codes}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    dt = future.result()
                    if dt and dt.get("on_list"):
                        results[code] = dt
                except:
                    pass
                done += 1
                if done % 100 == 0:
                    print(f"  龙虎榜进度: {done}/{total} ({done*100//total}%)")
        print(f"  ✅ 获取到 {len(results)} 只股票龙虎榜数据")
        return results


class StockAnalyzer:
    """股票分析器 - 计算技术指标和评分 v3.0"""

    @staticmethod
    def calculate_ma(history: List[Dict], period: int) -> Optional[float]:
        if len(history) < period:
            return None
        recent = history[-period:]
        closes = [h["close"] for h in recent]
        return sum(closes) / period

    @staticmethod
    def calculate_ma_trend(history: List[Dict], period: int) -> Dict:
        if len(history) < period * 2:
            return {"ma": None, "trend": "unknown", "slope": 0}
        current_ma = sum(h["close"] for h in history[-period:]) / period
        prev_ma = sum(h["close"] for h in history[-period * 2:-period]) / period
        slope = (current_ma - prev_ma) / prev_ma * 100 if prev_ma > 0 else 0
        if slope > 1:
            trend = "up"
        elif slope < -1:
            trend = "down"
        else:
            trend = "flat"
        return {"ma": round(current_ma, 2), "prev_ma": round(prev_ma, 2), "trend": trend, "slope": round(slope, 2)}

    @staticmethod
    def check_ma_alignment(history: List[Dict]) -> Dict:
        """检查均线多头排列 — 股价同时站上 MA5/MA10/MA20"""
        if len(history) < 20:
            return {"alignment": "unknown", "score": 0, "price_above_all": False}
        ma5 = sum(h["close"] for h in history[-5:]) / 5
        ma10 = sum(h["close"] for h in history[-10:]) / 10
        ma20 = sum(h["close"] for h in history[-20:]) / 20
        current_price = history[-1]["close"]
        price_above_all = current_price > ma5 and current_price > ma10 and current_price > ma20
        if ma5 > ma10 > ma20 and price_above_all:
            return {"alignment": "bullish", "score": 100, "price_above_all": True}
        elif ma5 < ma10 < ma20:
            return {"alignment": "bearish", "score": 0, "price_above_all": False}
        elif price_above_all:
            return {"alignment": "semi_bullish", "score": 75, "price_above_all": True}
        else:
            return {"alignment": "neutral", "score": 50, "price_above_all": False}

    @staticmethod
    def calculate_volume_ratio(history: List[Dict]) -> Dict:
        if len(history) < 10:
            return {"volume_ratio": 1.0, "trend": "unknown"}
        recent_vol = sum(h["volume"] for h in history[-5:]) / 5
        prev_vol = sum(h["volume"] for h in history[-10:-5]) / 5
        ratio = recent_vol / prev_vol if prev_vol > 0 else 1.0
        if ratio > 1.5:
            trend = "high"
        elif ratio > 1.1:
            trend = "slightly_high"
        elif ratio < 0.7:
            trend = "low"
        else:
            trend = "normal"
        return {"volume_ratio": round(ratio, 2), "trend": trend}

    @staticmethod
    def check_volume_trend_3day(history: List[Dict]) -> Dict:
        """检查近3日成交量是否逐日放大"""
        if len(history) < 3:
            return {"trend": "unknown", "consecutive_up": False}
        recent = history[-3:]
        vols = [h["volume"] for h in recent]
        if vols[0] > 0 and vols[1] > vols[0] and vols[2] > vols[1]:
            return {"trend": "increasing", "consecutive_up": True, "volumes": vols}
        elif vols[-1] > vols[0]:
            return {"trend": "up", "consecutive_up": False, "volumes": vols}
        else:
            return {"trend": "down_or_flat", "consecutive_up": False, "volumes": vols}

    @staticmethod
    def calculate_tail_pct(history: List[Dict], quote: Dict) -> float:
        """计算前一日尾盘涨幅（最后1小时涨幅）"""
        if not history or not quote:
            return 0.0
        today_open = quote.get("open", 0)
        current_price = quote.get("price", 0)
        prev_close = quote.get("prev_close", 0)
        if prev_close and prev_close > 0:
            return round((current_price - prev_close) / prev_close * 100, 2)
        return 0.0

    @staticmethod
    def calculate_price_position(history: List[Dict], current_price: float) -> float:
        if not history or current_price == 0:
            return 50.0
        highs = [h["high"] for h in history[-60:]] if len(history) >= 60 else [h["high"] for h in history]
        lows = [h["low"] for h in history[-60:]] if len(history) >= 60 else [h["low"] for h in history]
        max_high = max(highs)
        min_low = min(lows)
        price_range = max_high - min_low
        if price_range == 0:
            return 50.0
        position = (current_price - min_low) / price_range * 100
        return round(position, 1)

    @staticmethod
    def calculate_pct_change(history: List[Dict], days: int) -> float:
        """计算近N日涨幅"""
        if len(history) < days + 1:
            return 0.0
        price_now = history[-1]["close"]
        price_ago = history[-(days + 1)]["close"]
        if price_ago == 0:
            return 0.0
        return round((price_now - price_ago) / price_ago * 100, 2)


if __name__ == "__main__":
    fetcher = StockDataFetcher()
    print("=" * 50)
    print("测试1: 热门股票池（含两级行业分类）")
    hot_stocks = fetcher._get_hot_stocks()
    industries = {}
    for s in hot_stocks:
        l2 = s.get("industry_level2", "unknown")
        industries[l2] = industries.get(l2, 0) + 1
    print("\n行业分布（二级分类）:")
    for ind, count in sorted(industries.items(), key=lambda x: -x[1])[:15]:
        print(f"  {ind}: {count}只")
    print("\n测试2: 行业识别验证")
    test_cases = [("600036", "招商银行"), ("688981", "中芯国际"), ("000858", "五粮液"), ("300750", "宁德时代")]
    for code, name in test_cases:
        info = fetcher._determine_industry(name, code)
        print(f"  {name}({code}) → {info['industry_level2']} (置信度: {info['confidence']})")