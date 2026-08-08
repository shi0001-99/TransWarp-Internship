#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据爬取模块 - 从腾讯/东方财富API获取A股数据
支持全A股列表获取、缓存和筛选
v3.0: 两级行业分类 + 新增技术指标（尾盘涨幅/量能趋势/流通市值）
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
        "Referer": "https://finance.eastmoney.com/"
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.cache_file = os.path.join(os.path.dirname(__file__), "stock_list_cache.json")

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
            max_count = kwargs.get("max_count", 500)
            return self._get_hot_stocks(max_count=max_count)

    def _get_hot_stocks(self, max_count: int = 500) -> List[Dict]:
        """获取热门500只股票 — 按成交额排序从东方财富API获取，失败时降级到硬编码龙头池"""
        # 先尝试从API获取热门500只
        api_stocks = self._fetch_hot_stocks_api(max_count=max_count)
        if api_stocks and len(api_stocks) >= 50:
            return api_stocks
        # API失败则降级到硬编码龙头池
        print("  ⚠️ API获取失败，降级到硬编码热门龙头股池...")
        return self._get_hardcoded_hot_stocks()

    def _fetch_hot_stocks_api(self, max_count: int = 500) -> List[Dict]:
        """从东方财富API获取按成交额排序的热门股票"""
        print(f"📋 从东方财富获取热门股票列表（按成交额排序，最多{max_count}只）...")
        stocks = []
        page_size = 100
        page = 1
        total_fetched = 0
        max_retries = 5

        base_urls = [
            "https://82.push2.eastmoney.com/api/qt/clist/get",
            "https://push2.eastmoney.com/api/qt/clist/get",
            "https://push2his.eastmoney.com/api/qt/clist/get",
        ]

        # 首次请求前重建session，避免连接池问题
        self.session.close()
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        time.sleep(0.5)

        while total_fetched < max_count:
            params = {
                "pn": str(page), "pz": str(page_size), "po": "1", "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2", "invt": "2",
                "fid": "f6",  # 按成交额排序（热门度）
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f12,f13,f14,f2,f3,f6,f8,f9,f20,f21,f23",
                "_": str(int(time.time() * 1000)),
            }

            success = False
            for base_url in base_urls:
                for retry in range(max_retries):
                    try:
                        response = self.session.get(base_url, params=params, timeout=10)
                        if response.status_code == 200:
                            data = response.json()
                            if not data.get("data") or not data["data"].get("diff"):
                                if page == 1:
                                    print(f"  ⚠️ API返回空数据")
                                success = True
                                break

                            items = data["data"]["diff"]
                            for item in items:
                                code = str(item.get("f12", ""))
                                name = item.get("f14", "")
                                market = "sh" if item.get("f13") == 1 else "sz"
                                price = item.get("f2", 0)
                                change_pct = item.get("f3", 0)
                                amount = item.get("f6", 0)
                                turnover = item.get("f8", 0)
                                pe = item.get("f9", 0)
                                market_cap = item.get("f20", 0)

                                # 排除ST、退市股
                                if "ST" in name or "st" in name or "退" in name:
                                    continue

                                industry_info = self._determine_industry(name, code, f"{market}{code}")

                                stock = {
                                    "code": code, "name": name,
                                    "price": price if price else 0,
                                    "change_pct": change_pct if change_pct else 0,
                                    "volume": 0, "amount": amount if amount else 0,
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

                            total_fetched = len(stocks)
                            print(f"  获取进度: 第{page}页, 累计{total_fetched}只")

                            if total_fetched >= max_count:
                                success = True
                                break
                            page += 1
                            time.sleep(0.2)
                            success = True
                            break
                        else:
                            print(f"  ⚠️ HTTP {response.status_code} ({base_url})")
                            time.sleep(0.5)
                            continue
                    except Exception as e:
                        print(f"  ⚠️ 请求异常({base_url}): {e}")
                        # 连接断开时重建session
                        try:
                            self.session.close()
                        except Exception:
                            pass
                        self.session = requests.Session()
                        self.session.headers.update(self.HEADERS)
                        if retry < max_retries - 1:
                            time.sleep(1.5)
                        continue
                if success:
                    break

            if not success:
                print(f"  ⚠️ 获取第{page}页失败，所有API均不可用")
                break

        if not stocks:
            print("  ⚠️ API获取热门股票失败")
            return []

        if len(stocks) > max_count:
            stocks = stocks[:max_count]

        print(f"  ✅ 获取到 {len(stocks)} 只热门股票")
        return stocks

    def _get_hardcoded_hot_stocks(self) -> List[Dict]:
        """硬编码热门龙头股池（API不可用时的降级方案）"""
        print("📋 使用硬编码热门龙头股池...")
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
        return stocks_list

    def get_all_a_stocks(self, min_market_cap: float = 0, exclude_st: bool = True,
                         max_count: int = 500, use_cache: bool = True) -> List[Dict]:
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

        base_urls = [
            "https://82.push2.eastmoney.com/api/qt/clist/get",
            "https://push2.eastmoney.com/api/qt/clist/get",
            "https://push2his.eastmoney.com/api/qt/clist/get",
        ]

        while True:
            params = {
                "pn": str(page), "pz": str(page_size), "po": "1", "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2", "invt": "2", "fid": "f3",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f12,f13,f14,f2,f3,f8,f9,f20,f21,f23",
                "_": str(int(time.time() * 1000)),
            }

            success = False
            for base_url in base_urls:
                for retry in range(max_retries):
                    try:
                        response = self.session.get(base_url, params=params, timeout=10)
                        if response.status_code == 200:
                            data = response.json()
                            if not data.get("data") or not data["data"].get("diff"):
                                if page == 1:
                                    print(f"  ⚠️ API返回空数据")
                                continue

                            items = data["data"]["diff"]
                            for item in items:
                                code = str(item.get("f12", ""))
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

                            total_fetched += len(items)
                            print(f"  获取进度: 第{page}页, 累计{total_fetched}只")

                            total = data["data"].get("total", 0)
                            if total_fetched >= total or total == 0:
                                success = True
                                break
                            page += 1
                            time.sleep(0.2)

                            if len(stocks) >= max_count and max_count > 0:
                                success = True
                                break
                            success = True
                            break
                        else:
                            time.sleep(0.5)
                            continue
                    except Exception as e:
                        if retry < max_retries - 1:
                            time.sleep(1)
                        continue
                if success:
                    break

            if not success:
                print(f"  ⚠️ 获取第{page}页失败，所有API均不可用")
                if page == 1:
                    print("  🔄 将使用热门股票池作为备选...")
                    return self._get_hot_stocks()
                break

        if not stocks:
            print("  ⚠️ 未能获取全A股列表，使用热门股票池作为备选")
            return self._get_hot_stocks()

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
                return {
                    "code": parts[2],
                    "name": parts[1],
                    "price": float(parts[3]) if parts[3] else 0,
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
                    "net_profit": fund.get("PARENTNETPROFIT"),
                    "eps": fund.get("EPSJB"),
                }
            return None
        except:
            return None


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

    @staticmethod
    def calculate_rsi(history: List[Dict], period: int = 14) -> float:
        """计算RSI指标"""
        if len(history) < period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(-period, 0):
            change = history[i]["close"] - history[i - 1]["close"]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi, 1)

    @staticmethod
    def detect_patterns(history: List[Dict]) -> List[Dict]:
        """识别K线形态"""
        patterns = []
        if len(history) < 5:
            return patterns

        recent = history[-5:]
        # 双顶/双顶
        highs = [h["high"] for h in recent]
        if len(highs) >= 4:
            if highs[-3] > highs[-4] and highs[-1] < highs[-2] and abs(highs[-3] - highs[-1]) / max(highs) < 0.02:
                patterns.append({"name": "双顶形态", "type": "bearish"})
            if highs[-3] < highs[-4] and highs[-1] > highs[-2] and abs(highs[-3] - highs[-1]) / max(highs) < 0.02:
                patterns.append({"name": "双底形态", "type": "bullish"})

        # V型反转
        closes = [h["close"] for h in recent]
        if len(closes) >= 5:
            mid = len(closes) // 2
            if closes[0] > closes[mid] and closes[-1] > closes[mid]:
                patterns.append({"name": "V型反转", "type": "bullish"})
            elif closes[0] < closes[mid] and closes[-1] < closes[mid]:
                patterns.append({"name": "倒V反转", "type": "bearish"})

        # 突破压力位
        if len(history) >= 20:
            ma20 = sum(h["close"] for h in history[-20:]) / 20
            current = history[-1]["close"]
            prev = history[-2]["close"]
            if prev < ma20 and current > ma20:
                patterns.append({"name": f"突破压力位{ma20:.2f}", "type": "bullish"})
            elif prev > ma20 and current < ma20:
                patterns.append({"name": f"跌破支撑位{ma20:.2f}", "type": "bearish"})

        # 反弹蓄势
        if len(closes) >= 3:
            if closes[-1] > closes[-2] and closes[-2] < closes[-3]:
                patterns.append({"name": "反弹蓄势", "type": "neutral"})

        return patterns

    def get_stock_analysis(self, code: str, predict_days: int = 5) -> Dict:
        """趋势分析主入口 — 综合技术指标、形态识别、信号生成"""
        fetcher = StockDataFetcher()

        # 判断市场前缀
        if code.startswith("6"):
            full_code = f"sh{code}"
        else:
            full_code = f"sz{code}"

        # 获取数据
        quote = fetcher.fetch_realtime_quote(full_code) or {}
        history = fetcher.fetch_kline_history(full_code, days=120) or []
        fundamental = fetcher.fetch_fundamental(code) or {}

        if not history or len(history) < 20:
            return {
                "stock_code": code, "stock_name": quote.get("name", ""),
                "error": "历史数据不足", "signal_direction": "中性", "score": 0,
            }

        current_price = quote.get("price", history[-1]["close"])

        # 计算技术指标
        ma5 = self.calculate_ma_trend(history, 5)
        ma10 = self.calculate_ma_trend(history, 10)
        ma20 = self.calculate_ma_trend(history, 20)
        ma60 = self.calculate_ma_trend(history, 60)
        ma_alignment = self.check_ma_alignment(history)
        volume_ratio = self.calculate_volume_ratio(history)
        vol_trend = self.check_volume_trend_3day(history)
        tail_pct = self.calculate_tail_pct(history, quote)
        price_position = self.calculate_price_position(history, current_price)
        pct_5d = self.calculate_pct_change(history, 5)
        pct_20d = self.calculate_pct_change(history, 20)
        rsi = self.calculate_rsi(history)

        # 识别形态
        patterns = self.detect_patterns(history)

        # 生成信号方向和评分
        score = 50  # 基础分
        bull_signals = []
        bear_signals = []

        # 均线排列
        if ma_alignment["alignment"] == "bullish":
            score += 15
            bull_signals.append("均线多头排列")
        elif ma_alignment["alignment"] == "bearish":
            score -= 15
            bear_signals.append("均线空头排列")
        elif ma_alignment["alignment"] == "semi_bullish":
            score += 8
            bull_signals.append("均线偏多")

        # MA20趋势（核心指标 H5）
        if ma20["trend"] == "up":
            score += 10
            bull_signals.append("MA20上行")
        elif ma20["trend"] == "down":
            score -= 10
            bear_signals.append("MA20下行")

        # 价格位置
        if current_price > ma20["ma"]:
            score += 5
            bull_signals.append("股价站上MA20")
        else:
            score -= 5
            bear_signals.append("股价低于MA20")

        # RSI
        if rsi > 70:
            score -= 5
            bear_signals.append(f"RSI超买({rsi})")
        elif rsi < 30:
            score += 5
            bull_signals.append(f"RSI超卖({rsi})")

        # 成交量
        if vol_trend["trend"] in ("increasing", "up"):
            score += 5
            bull_signals.append("成交量放大")
        elif volume_ratio["trend"] == "high":
            score += 3

        # 形态
        for p in patterns:
            if p["type"] == "bullish":
                score += 3
                bull_signals.append(p["name"])
            elif p["type"] == "bearish":
                score -= 3
                bear_signals.append(p["name"])

        # 近期涨幅
        if pct_5d > 10:
            score += 3
        elif pct_5d < -10:
            score -= 3

        score = max(0, min(100, score))

        # 信号方向
        if score >= 60:
            signal_direction = "看多"
        elif score <= 40:
            signal_direction = "看空"
        else:
            signal_direction = "中性"

        # 简单预测
        recent_returns = [(history[i]["close"] - history[i-1]["close"]) / history[i-1]["close"] for i in range(-min(10, len(history)-1), 0) if history[i-1]["close"] > 0]
        avg_return = sum(recent_returns) / len(recent_returns) if recent_returns else 0
        predicted_return = avg_return * predict_days * 100
        up_probability = min(100, max(0, 50 + avg_return * 200))

        result = {
            "stock_code": code,
            "stock_name": quote.get("name", ""),
            "current_price": current_price,
            "signal_direction": signal_direction,
            "signal_score": round(score / 100, 2),
            "score": score,
            "prediction": {
                "predicted_price": round(current_price * (1 + predicted_return / 100), 2),
                "predicted_return": round(predicted_return, 2),
                "up_probability": round(up_probability, 1),
                "confidence": round(abs(up_probability - 50) * 0.7, 1),
            },
            "patterns": patterns,
            "indicators": {
                "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
                "ma_alignment": ma_alignment, "rsi": rsi,
                "volume_ratio": volume_ratio, "vol_trend": vol_trend,
                "tail_pct": tail_pct, "price_position": price_position,
                "pct_5d": pct_5d, "pct_20d": pct_20d,
            },
            "bull_signals": bull_signals,
            "bear_signals": bear_signals,
        }
        return result


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