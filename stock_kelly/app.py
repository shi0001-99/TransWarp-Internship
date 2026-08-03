#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票凯利分析器 - Flask Web版后端服务
"""

import sys
import os
import time
import warnings
import logging
import threading
import traceback
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from typing import Dict, Optional

# 忽略警告
warnings.filterwarnings('ignore')

# 抑制 tqdm 进度条
os.environ['TQDM_DISABLE'] = '1'

# 设置日志
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'server.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 导入现有的分析模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stock_kelly_analyzer import (
    StockDataFetcher,
    StockScorer,
    KellyCalculator,
    StockKellyAnalyzer,
    SCORING_WEIGHTS,
    RATING_THRESHOLDS,
    KELLY_CONFIG,
    BLACKLIST_RULES
)

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
CORS(app)

# 全局缓存（5分钟有效）
_cache = {}
_cache_timestamps = {}
CACHE_DURATION = 300  # 5分钟
_cache_lock = threading.Lock()

# 服务器运行状态
_server_start_time = time.time()
_request_count = 0
_request_lock = threading.Lock()

# 并发请求守卫 - 防止多个分析请求同时进行导致baostock连接阻塞
_analysis_in_progress = False
_analysis_lock = threading.Lock()


def get_cached_data(key: str) -> Optional[Dict]:
    """获取缓存数据（线程安全）"""
    with _cache_lock:
        if key in _cache and key in _cache_timestamps:
            if time.time() - _cache_timestamps[key] < CACHE_DURATION:
                return _cache[key]
    return None


def set_cached_data(key: str, data: Dict):
    """设置缓存数据（线程安全）"""
    with _cache_lock:
        _cache[key] = data
        _cache_timestamps[key] = time.time()


def clear_all_cache():
    """清除所有缓存（线程安全）"""
    global _cache, _cache_timestamps
    with _cache_lock:
        _cache = {}
        _cache_timestamps = {}
    import stock_kelly_analyzer
    stock_kelly_analyzer._global_cache = {}
    stock_kelly_analyzer._global_cache_time = {}


def run_analysis_with_timeout(stock_code: str, total_capital: float, timeout: int = 90) -> Dict:
    """带超时的分析执行"""
    result_container = [None]
    exception_container = [None]
    
    def do_analysis():
        try:
            analyzer = StockKellyAnalyzer(
                total_capital=total_capital,
                kelly_scaling=KELLY_CONFIG['kelly_scaling']
            )
            result_container[0] = analyzer.analyze(stock_code, silent=True)
        except Exception as e:
            exception_container[0] = e
    
    thread = threading.Thread(target=do_analysis, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    
    if thread.is_alive():
        raise TimeoutError(f"分析超时（超过{timeout}秒），数据源可能响应慢，请稍后重试")
    
    if exception_container[0]:
        raise exception_container[0]
    
    if result_container[0] is None:
        raise RuntimeError("分析结果为空")
    
    return result_container[0]


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/analyze', methods=['POST'])
def analyze_stock():
    """分析股票 API（带超时保护和错误恢复）"""
    global _request_count, _analysis_in_progress
    data = request.get_json()
    stock_code = data.get('code', '').strip()
    total_capital = data.get('capital', 1000000)
    
    if not stock_code:
        return jsonify({
            'success': False,
            'error': '请输入股票代码'
        })
    
    try:
        total_capital = float(total_capital)
    except (ValueError, TypeError):
        total_capital = 1000000
    
    # 检查缓存
    cache_key = f"{stock_code}_{total_capital}"
    cached = get_cached_data(cache_key)
    if cached:
        logger.info(f"使用缓存数据: {stock_code}")
        return jsonify(cached)
    
    # 并发守卫 - 如果有分析正在进行，拒绝新请求
    with _analysis_lock:
        if _analysis_in_progress:
            logger.warning(f"服务器繁忙，拒绝请求: {stock_code}")
            return jsonify({
                'success': False,
                'error': '服务器繁忙，当前有其他分析正在处理，请稍后再试'
            }), 429
        _analysis_in_progress = True
    
    logger.info(f"开始分析: {stock_code}")
    start_time = time.time()
    
    with _request_lock:
        _request_count += 1
    
    try:
        # 使用带超时的分析执行
        raw_result = run_analysis_with_timeout(stock_code, total_capital, timeout=90)
        
        # 格式化返回结果
        response_data = format_result_for_web(raw_result, stock_code, total_capital)
        
        response = {
            'success': True,
            'data': response_data,
            'processing_time': round(time.time() - start_time, 2)
        }
        
        # 缓存结果
        set_cached_data(cache_key, response)
        
        logger.info(f"分析完成: {stock_code}, 耗时 {response['processing_time']}s")
        return jsonify(response)
        
    except TimeoutError as e:
        logger.warning(f"分析超时: {stock_code}, 错误: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })
    except Exception as e:
        logger.error(f"分析出错: {stock_code}, 错误: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': f'分析失败：{str(e)[:200]}。请稍后重试，或检查网络连接。'
        })
    finally:
        # 释放并发守卫
        with _analysis_lock:
            _analysis_in_progress = False


def format_result_for_web(raw_result: Dict, stock_code: str, total_capital: float) -> Dict:
    """将分析结果格式化为前端可用的格式"""
    basic_info = raw_result.get('basic_info', {})
    financial = raw_result.get('financial', {})
    market = raw_result.get('market', {})
    valuation = raw_result.get('valuation', {})
    ratings = raw_result.get('ratings', {})
    kelly = raw_result.get('kelly', {})
    blacklist = raw_result.get('blacklist', {})
    advice = raw_result.get('advice', '')
    value_score = raw_result.get('value_score', {})
    trend_score = raw_result.get('trend_score', {})
    fund_flow = raw_result.get('fund_flow', {})
    
    # 提取股票名称
    stock_name = basic_info.get('name', '未知')
    
    # 构建评分详情
    score_details = [
        {
            'dimension': '价值基本面',
            'score': ratings.get('value', 0),
            'max_score': 10,
            'weight': '25%',
            'color': '#3b82f6',
            'details': value_score.get('details', [])[:5]
        },
        {
            'dimension': '趋势动量',
            'score': ratings.get('trend', 0),
            'max_score': 10,
            'weight': '45%',
            'color': '#8b5cf6',
            'details': trend_score.get('details', [])[:5]
        },
        {
            'dimension': '宏观环境',
            'score': ratings.get('macro', 0),
            'max_score': 10,
            'weight': '5%',
            'color': '#10b981',
            'details': raw_result.get('macro_score', {}).get('details', [])[:5]
        },
        {
            'dimension': '资金流向',
            'score': ratings.get('fund_flow', 0),
            'max_score': 10,
            'weight': '15%',
            'color': '#f59e0b',
            'details': raw_result.get('fund_flow_score', {}).get('details', [])[:3]
        },
        {
            'dimension': '事件消息',
            'score': ratings.get('event', 0),
            'max_score': 10,
            'weight': '10%',
            'color': '#ef4444',
            'details': raw_result.get('event_score', {}).get('details', [])[:3]
        }
    ]
    
    # 风险提示
    risk_warnings = blacklist.get('warnings', [])
    
    # 格式化财务数据
    financial_display = {
        'roe': round(financial.get('roe', 0), 2),
        'gross_margin': round(financial.get('gross_margin', 0), 2),
        'net_margin': round(financial.get('net_margin', 0), 2),
        'debt_ratio': round(financial.get('debt_ratio', 0), 2),
        'revenue_growth': round(financial.get('revenue_growth', 0), 2),
        'profit_growth': round(financial.get('profit_growth', 0), 2),
    }
    
    # 格式化行情数据
    market_display = {
        'current_price': round(market.get('current_price', 0), 2),
        'change_pct': round(market.get('change_pct', 0), 2),
        'returns_5d': round(market.get('returns_5d', 0), 2),
        'returns_20d': round(market.get('returns_20d', 0), 2),
        'returns_60d': round(market.get('returns_60d', 0), 2),
        'turnover': round(market.get('turnover', 0), 2),
        'volatility': round(market.get('volatility', 0), 2),
        'volume': round(market.get('volume', 0), 0),
        'is_realtime': market.get('last_date', '') != __import__('datetime').datetime.now().strftime('%Y-%m-%d'),
    }
    
    # 格式化估值数据
    valuation_display = {
        'pe': round(valuation.get('pe', 0), 2),
        'pb': round(valuation.get('pb', 0), 2),
        'pe_percentile': round(valuation.get('pe_percentile', 0), 1),
        'pb_percentile': round(valuation.get('pb_percentile', 0), 1),
    }
    
    # 格式化凯利数据
    kelly_display = {}
    if kelly:
        kelly_display = {
            'win_probability': round(kelly.get('win_probability', 0) * 100, 1),
            'kelly_fraction': round(kelly.get('kelly_fraction', 0) * 100, 2),
            'suggested_fraction': round(kelly.get('suggested_fraction', 0) * 100, 2),
            'suggested_amount': round(kelly.get('suggested_amount', 0), 2),
            'suggested_shares': kelly.get('suggested_shares', 0),
            'edge': round(kelly.get('edge', 0), 4),
            'avg_win_pct': round(kelly.get('avg_win_pct', 0) * 100, 0),
            'avg_loss_pct': round(kelly.get('avg_loss_pct', 0) * 100, 0),
        }
    
    # 格式化资金流向
    fund_flow_display = {
        'net_inflow_5d': round(fund_flow.get('net_inflow_5d', 0) / 1e8, 2),  # 亿元
        'up_days_5d': fund_flow.get('up_days_5d', 0),
    }
    
    # 从market数据获取市值（如果basic_info中没有）
    total_market_cap = basic_info.get('total_market_cap', 0)
    if total_market_cap == 0 and market.get('total_market_cap', 0) > 0:
        total_market_cap = market.get('total_market_cap', 0)
    circulating_market_cap = basic_info.get('circulating_market_cap', 0)
    if circulating_market_cap == 0 and market.get('circulating_market_cap', 0) > 0:
        circulating_market_cap = market.get('circulating_market_cap', 0)
    
    # 格式化宏观环境数据
    macro_data = raw_result.get('macro_data', {})
    ip = macro_data.get('industry_performance', {})
    mi = macro_data.get('market_indices', {})
    macro_data_display = {
        'industry_performance': ip if ip and ip.get('change_5d') is not None else None,
        'market_indices': mi if mi else None,
    }
    
    # 格式化事件消息数据
    event_data = raw_result.get('event_data', {})
    event_data_display = {
        'total_news': event_data.get('total_news', 0),
        'positive_news': event_data.get('positive_news', 0),
        'negative_news': event_data.get('negative_news', 0),
        'neutral_news': event_data.get('neutral_news', 0),
        'sentiment_score': event_data.get('sentiment_score', 5.0),
        'has_significant_event': event_data.get('has_significant_event', False),
        'news_list': event_data.get('news_list', [])[:5],
    }
    
    return {
        'stock_name': stock_name,
        'stock_code': stock_code,
        'stock_info': {
            'name': stock_name,
            'code': basic_info.get('code', stock_code),
            'industry': basic_info.get('industry', '未知'),
            'total_market_cap': round(total_market_cap / 1e8, 2) if total_market_cap > 0 else 0,
            'circulating_market_cap': round(circulating_market_cap / 1e8, 2) if circulating_market_cap > 0 else 0,
            'listing_date': basic_info.get('listing_date', ''),
        },
        'market_data': market_display,
        'valuation_data': valuation_display,
        'financial_data': financial_display,
        'fund_flow_data': fund_flow_display,
        'macro_data': macro_data_display,
        'event_data': event_data_display,
        'total_score': round(ratings.get('total', 0), 2),
        'rating': ratings.get('rating', ''),
        'score_details': score_details,
        'kelly': kelly_display,
        'risk_warnings': risk_warnings,
        'advice': advice,
    }


@app.route('/api/health')
def health_check():
    """健康检查（包含服务器运行状态）"""
    uptime = round(time.time() - _server_start_time, 0)
    with _request_lock:
        count = _request_count
    return jsonify({
        'status': 'ok',
        'version': '1.0.0',
        'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        'uptime_seconds': uptime,
        'total_requests': count,
        'server_time': time.strftime('%Y-%m-%d %H:%M:%S')
    })


@app.route('/api/clear_cache', methods=['POST'])
def clear_cache_endpoint():
    """清除缓存"""
    clear_all_cache()
    return jsonify({'status': 'ok', 'message': '缓存已清除'})


@app.route('/api/status')
def server_status():
    """服务器详细状态"""
    uptime = round(time.time() - _server_start_time, 0)
    with _request_lock:
        count = _request_count
    with _cache_lock:
        cache_entries = len(_cache)
    return jsonify({
        'status': 'running',
        'uptime': f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m {int(uptime % 60)}s",
        'total_requests': count,
        'cache_entries': cache_entries,
        'server_start': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(_server_start_time))
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    debug = os.environ.get('DEBUG', 'false').lower() == 'true'
    
    # 确保模板目录存在
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    
    # 获取本机IP
    local_ip = '127.0.0.1'
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    
    logger.info("=" * 50)
    logger.info("🚀 股票凯利分析器 Web 服务启动中...")
    logger.info(f"📊 本地访问: http://127.0.0.1:{port}")
    logger.info(f"🌐 局域网访问: http://{local_ip}:{port}")
    logger.info(f"🔧 Debug模式: {'开启' if debug else '关闭'}")
    logger.info("=" * 50)
    
    print("\n" + "=" * 50)
    print("🚀 股票凯利分析器 Web 服务启动中...")
    print(f"📊 本地访问: http://127.0.0.1:{port}")
    print(f"🌐 局域网访问: http://{local_ip}:{port}")
    print(f"🔧 Debug模式: {'开启' if debug else '关闭'}")
    print("=" * 50 + "\n")
    
    # 使用更稳定的生产模式启动
    app.run(
        host=host,
        port=port,
        debug=debug,
        threaded=True,
        use_reloader=False,
        passthrough_errors=False,
    )