#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票量化选股系统 - Flask Web应用
"""

import json
import os
import sys
import threading
import time
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from screener import StockScreener


app = Flask(__name__, template_folder="templates", static_folder="static")

# 全局选股器实例
screener = StockScreener()
scheduler = BackgroundScheduler()

# 运行状态
is_screening = False
screening_status = {
    "running": False,
    "progress": 0,
    "message": "",
    "last_update": None,
    "total_stocks": 0,
    "qualified_stocks": 0,
}


def run_screening_async():
    """异步运行选股"""
    global is_screening, screening_status
    
    if is_screening:
        return
    
    is_screening = True
    screening_status["running"] = True
    screening_status["message"] = "正在获取股票列表..."
    
    try:
        # 运行选股
        results = screener.run_screening(top_n=10)
        
        screening_status["message"] = f"筛选完成！共选出 {len(results)} 只股票"
        screening_status["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
    except Exception as e:
        screening_status["message"] = f"筛选失败: {str(e)}"
    
    finally:
        is_screening = False
        screening_status["running"] = False


# ==================== 路由 ====================

@app.route("/")
def index():
    """主页"""
    return render_template("index.html")


@app.route("/api/screen", methods=["POST"])
def api_screen():
    """触发选股"""
    global is_screening
    
    if is_screening:
        return jsonify({
            "success": False,
            "message": "正在筛选中，请稍候..."
        })
    
    # 异步运行
    thread = threading.Thread(target=run_screening_async)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        "success": True,
        "message": "选股任务已启动"
    })


@app.route("/api/status")
def api_status():
    """获取选股状态"""
    return jsonify({
        "success": True,
        "data": screening_status
    })


@app.route("/api/results")
def api_results():
    """获取选股结果"""
    summary = screener.get_results_summary()
    return jsonify({
        "success": True,
        "data": summary
    })


@app.route("/api/stock_detail/<code>")
def api_stock_detail(code):
    """获取单只股票详情"""
    for r in screener.results:
        if r["code"] == code:
            return jsonify({
                "success": True,
                "data": r
            })
    
    return jsonify({
        "success": False,
        "message": "未找到该股票"
    })


@app.route("/api/scheduler/status")
def api_scheduler_status():
    """获取定时任务状态"""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    
    return jsonify({
        "success": True,
        "running": scheduler.running,
        "jobs": jobs
    })


@app.route("/api/scheduler/start", methods=["POST"])
def api_scheduler_start():
    """启动定时任务（每个交易日自动运行）"""
    if not scheduler.running:
        # 添加定时任务：每个交易日 9:35 运行（开盘后）
        scheduler.add_job(
            run_screening_async,
            'cron',
            day_of_week='mon-fri',
            hour=9,
            minute=35,
            id='daily_screening',
            replace_existing=True,
        )
        scheduler.start()
        
        return jsonify({
            "success": True,
            "message": "定时任务已启动，将在每个交易日 9:35 自动运行"
        })
    
    return jsonify({
        "success": True,
        "message": "定时任务已在运行"
    })


@app.route("/api/scheduler/stop", methods=["POST"])
def api_scheduler_stop():
    """停止定时任务"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        return jsonify({
            "success": True,
            "message": "定时任务已停止"
        })
    
    return jsonify({
        "success": True,
        "message": "定时任务未运行"
    })


@app.route("/api/export")
def api_export():
    """导出结果为JSON"""
    summary = screener.get_results_summary()
    
    # 添加详细数据
    data = {
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_update": summary["last_update"],
        "results": []
    }
    
    for r in screener.results:
        data["results"].append({
            "code": r["code"],
            "name": r["name"],
            "price": r["price"],
            "change_pct": r.get("change_pct", 0),
            "total_score": r["total_score"],
            "grade": r["grade"],
            "advice": r["advice"],
            "industry": r.get("industry", ""),
            "pe": r.get("pe", 0),
            "pb": r.get("pb", 0),
            "turnover_rate": r.get("turnover_rate", 0),
            "price_position": r.get("price_position", 0),
            "ma_alignment": r.get("ma_alignment", {}),
            "score_details": r.get("score_details", []),
        })
    
    return jsonify({
        "success": True,
        "data": data
    })


# ==================== 主入口 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 股票量化选股系统 v1.0")
    print("📊 基于基本面+技术面多维度评分")
    print("💻 访问: http://127.0.0.1:5000")
    print("=" * 60)
    
    # 创建必要目录
    os.makedirs("templates", exist_ok=True)
    os.makedirs("static", exist_ok=True)
    
    app.run(host="0.0.0.0", port=5000, debug=True)