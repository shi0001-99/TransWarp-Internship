#!/usr/bin/env python3
"""
Stock Monitor Web API Server
Flask-based REST API for the stock monitoring skill

Usage:
    python web_server.py [--port 8765]
    python web_server.py --host 0.0.0.0 --port 8765
"""

import sys
import os
import json
import time
import subprocess
import argparse
import threading
from datetime import datetime
from pathlib import Path

try:
    from flask import Flask, jsonify, request, send_from_directory
    from flask_cors import CORS
except ImportError:
    print("Missing dependencies. Run: pip install flask flask-cors")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from monitor import StockAlert, WATCHLIST as DEFAULT_WATCHLIST, PID_FILE, LOG_DIR, LOG_FILE, ALERT_LOG_FILE
from db_lock import file_lock, atomic_write_json, safe_read_json

app = Flask(__name__, static_folder='web_static', static_url_path='/static')
CORS(app)

# ============ Watchlist Persistence (并发安全) ============
# 多人同时编辑时，三层防护：
#   1. WATCHLIST_LOCK    - 进程内线程互斥 (Flask 多线程)
#   2. file_lock         - 跨进程互斥 (web_server vs daemon)
#   3. atomic_write_json - 原子写入，避免其他进程读到半写状态
WATCHLIST_FILE = LOG_DIR / 'watchlist.json'
WATCHLIST_LOCK_FILE = LOG_DIR / 'watchlist.lock'
WATCHLIST_LOCK = threading.RLock()  # 进程内可重入锁


def load_watchlist():
    """从文件加载最新 watchlist (线程安全 + 进程安全)

    每次调用都会从磁盘重新读取，确保多人编辑时看到最新数据。
    """
    with WATCHLIST_LOCK:
        with file_lock(WATCHLIST_LOCK_FILE):
            data = safe_read_json(WATCHLIST_FILE, default=None)
            if isinstance(data, list) and len(data) > 0:
                return data
            # 文件不存在或损坏，初始化默认值
            atomic_write_json(WATCHLIST_FILE, list(DEFAULT_WATCHLIST))
            return list(DEFAULT_WATCHLIST)


def save_watchlist(watchlist):
    """原子写入 watchlist (线程安全 + 进程安全)"""
    with WATCHLIST_LOCK:
        with file_lock(WATCHLIST_LOCK_FILE):
            WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(WATCHLIST_FILE, watchlist)


def reload_watchlist():
    """重新从文件加载 watchlist (用于读操作前确保数据最新)

    多人编辑场景：用户 A 修改后，用户 B 读操作前调用此函数，
    确保 B 看到的是 A 的最新修改，而不是内存中的旧数据。
    """
    global WATCHLIST
    WATCHLIST = load_watchlist()


# 初始化全局 WATCHLIST
WATCHLIST = load_watchlist()

MONITOR = None
MONITOR_LOCK = threading.Lock()
LAST_SCAN_RESULT = None
LAST_SCAN_TIME = None


def get_monitor():
    global MONITOR
    if MONITOR is None:
        MONITOR = StockAlert(log_to_file=True, log_to_console=False, watchlist=WATCHLIST)
    return MONITOR


def run_scan_async():
    global LAST_SCAN_RESULT, LAST_SCAN_TIME
    with MONITOR_LOCK:
        try:
            monitor = get_monitor()
            alerts = monitor.run_once(smart_mode=False)
            LAST_SCAN_RESULT = alerts
            LAST_SCAN_TIME = datetime.now().isoformat()
        except Exception as e:
            LAST_SCAN_RESULT = []
            LAST_SCAN_TIME = datetime.now().isoformat()


def get_daemon_status():
    if not PID_FILE.exists():
        return {"running": False, "pid": None}
    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return {"running": False, "pid": None}

    if sys.platform == 'win32':
        result = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}'],
            capture_output=True, text=True
        )
        if str(pid) in result.stdout:
            return {"running": True, "pid": pid}
        return {"running": False, "pid": pid}
    else:
        try:
            os.kill(pid, 0)
            return {"running": True, "pid": pid}
        except (ProcessLookupError, OSError):
            return {"running": False, "pid": pid}


def start_daemon_process():
    if PID_FILE.exists():
        status = get_daemon_status()
        if status["running"]:
            return {"success": False, "message": "Daemon already running"}

    script_path = str(Path(__file__).parent / "monitor_daemon.py")
    proc = subprocess.Popen(
        [sys.executable, script_path],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    )
    PID_FILE.write_text(str(proc.pid))
    return {"success": True, "pid": proc.pid}


def stop_daemon_process():
    status = get_daemon_status()
    if not status["running"]:
        return {"success": False, "message": "Daemon not running"}

    pid = status["pid"]
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True)
    else:
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass

    PID_FILE.unlink(missing_ok=True)
    return {"success": True, "message": f"Stopped PID {pid}"}


def get_recent_logs(alert_only=False, lines=100):
    log_path = ALERT_LOG_FILE if alert_only else LOG_FILE
    if not log_path.exists():
        return []

    with open(log_path, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()

    result = []
    for line in all_lines[-lines:]:
        line = line.strip()
        if not line:
            continue
        result.append(line)
    return result


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/api/status')
def api_status():
    status = get_daemon_status()
    return jsonify({
        "daemon": status,
        "lastScanTime": LAST_SCAN_TIME,
        "watchlistCount": len(WATCHLIST),
        "logFileSize": LOG_FILE.stat().st_size if LOG_FILE.exists() else 0,
        "alertFileSize": ALERT_LOG_FILE.stat().st_size if ALERT_LOG_FILE.exists() else 0,
    })


@app.route('/api/watchlist')
def api_watchlist():
    # 读操作前重新加载，确保多人编辑场景下看到最新配置
    reload_watchlist()
    monitor = get_monitor()
    data_map = {}

    try:
        raw_data = monitor.fetch_sina_realtime(WATCHLIST)
        for code, data in raw_data.items():
            stock = next((s for s in WATCHLIST if s['code'] == code), None)
            if not stock or data.get('price', 0) <= 0:
                continue

            price = data['price']
            prev_close = data.get('prev_close', price)
            change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
            cost = stock.get('cost', 0)
            cost_change = (price - cost) / cost * 100 if cost > 0 else 0

            alerts, level = monitor.check_alerts(stock, data)

            data_map[code] = {
                "code": code,
                "name": stock['name'],
                "type": stock['type'],
                "market": stock['market'],
                "price": price,
                "prevClose": prev_close,
                "changePct": round(change_pct, 2),
                "cost": cost,
                "costChange": round(cost_change, 2),
                "maxHigh": stock.get('max_high', cost),
                "level": level,
                "alerts": [{"type": t, "text": text} for t, text in alerts],
                "timestamp": data.get('time', datetime.now().strftime('%H:%M:%S')),
            }
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"stocks": list(data_map.values())})


@app.route('/api/scan', methods=['POST'])
def api_scan():
    t = threading.Thread(target=run_scan_async, daemon=True)
    t.start()
    return jsonify({"status": "scan_started"})


@app.route('/api/alerts')
def api_alerts():
    lines = request.args.get('lines', 100, type=int)
    alert_only = request.args.get('alert_only', 'true').lower() == 'true'
    logs = get_recent_logs(alert_only=False, lines=lines * 3)

    alerts = []
    for line in logs:
        if 'ALERT [' not in line:
            continue
        try:
            match_start = line.find('ALERT [')
            timestamp = line[:match_start].strip().replace('[INFO]', '').strip()

            bracket_end = line.find(']', match_start + 6)
            level = 'info'
            if bracket_end != -1:
                level_str = line[match_start + 6:bracket_end]
                if 'critical' in level_str:
                    level = 'critical'
                elif 'warning' in level_str:
                    level = 'warning'

            content_start = bracket_end + 2 if bracket_end != -1 else match_start + 20
            content = line[content_start:].strip()
            if content:
                alerts.append({"timestamp": timestamp, "content": content, "level": level})
        except Exception:
            pass

    if alert_only:
        alerts = alerts[-lines:]

    # 反转顺序，最新消息在最上面
    alerts = list(reversed(alerts))

    return jsonify({"alerts": alerts})


@app.route('/api/logs')
def api_logs():
    lines = request.args.get('lines', 100, type=int)
    logs = get_recent_logs(alert_only=False, lines=lines)

    entries = []
    for line in logs:
        try:
            parts = line.split('] ', 1)
            timestamp = parts[0].replace('[', '')
            level = 'INFO'
            if 'ALERT' in line:
                level = 'ALERT'
            content = parts[1] if len(parts) > 1 else line
            entries.append({"timestamp": timestamp, "level": level, "content": content})
        except Exception:
            entries.append({"timestamp": "", "level": "INFO", "content": line})

    return jsonify({"logs": entries})


@app.route('/api/daemon/start', methods=['POST'])
def api_daemon_start():
    result = start_daemon_process()
    return jsonify(result)


@app.route('/api/daemon/stop', methods=['POST'])
def api_daemon_stop():
    result = stop_daemon_process()
    return jsonify(result)


@app.route('/api/daemon/restart', methods=['POST'])
def api_daemon_restart():
    stop_daemon_process()
    time.sleep(1)
    result = start_daemon_process()
    return jsonify(result)


@app.route('/api/watchlist_config')
def api_watchlist_config():
    # 读操作前重新加载，确保看到其他用户的最新修改
    reload_watchlist()
    configs = []
    for stock in WATCHLIST:
        configs.append({
            "code": stock['code'],
            "name": stock['name'],
            "type": stock['type'],
            "market": stock['market'],
            "cost": stock.get('cost', 0),
            "maxHigh": stock.get('max_high', stock.get('cost', 0)),
            "alerts": stock.get('alerts', {}),
        })
    return jsonify({"watchlist": configs})


@app.route('/api/watchlist', methods=['POST'])
def api_watchlist_add():
    """Add a new stock to watchlist (并发安全)"""
    global WATCHLIST, MONITOR
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid data"}), 400

    required_fields = ['code', 'name', 'market', 'type']
    for field in required_fields:
        if not data.get(field):
            return jsonify({"error": f"Missing field: {field}"}), 400

    # 加锁：保证读-改-写的原子性，避免多人同时添加导致丢失
    with WATCHLIST_LOCK:
        reload_watchlist()  # 读取最新数据

        # Check for duplicate
        if any(s['code'] == data['code'] and s['market'] == data['market'] for s in WATCHLIST):
            return jsonify({"error": f"Stock {data['code']} already exists"}), 409

        new_stock = {
            "code": data['code'],
            "name": data['name'],
            "market": data['market'],
            "type": data['type'],
            "cost": data.get('cost', 0),
            "max_high": data.get('cost', 0),
            "alerts": data.get('alerts', {
                "cost_pct_above": 10.0,
                "cost_pct_below": -10.0,
                "change_pct_above": 3.0,
                "change_pct_below": -3.0,
                "volume_surge": 2.0
            })
        }

        WATCHLIST.append(new_stock)
        save_watchlist(WATCHLIST)
        MONITOR = None  # Reset monitor to reload watchlist
    return jsonify({"success": True, "stock": new_stock})


@app.route('/api/watchlist/<code>', methods=['PUT'])
def api_watchlist_update(code):
    """Update an existing stock (并发安全)"""
    global WATCHLIST, MONITOR
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid data"}), 400

    # 加锁：保证读-改-写的原子性
    with WATCHLIST_LOCK:
        reload_watchlist()  # 读取最新数据

        stock = next((s for s in WATCHLIST if s['code'] == code), None)
        if not stock:
            return jsonify({"error": f"Stock {code} not found"}), 404

        # Update fields
        for field in ['name', 'cost', 'market', 'type']:
            if field in data:
                stock[field] = data[field]

        # Reset max_high when cost changes (new cost basis = new tracking period)
        if 'cost' in data:
            stock['max_high'] = data['cost']

        if 'alerts' in data:
            stock['alerts'].update(data['alerts'])

        save_watchlist(WATCHLIST)
        MONITOR = None
    return jsonify({"success": True, "stock": stock})


@app.route('/api/watchlist/<code>', methods=['DELETE'])
def api_watchlist_delete(code):
    """Delete a stock from watchlist (并发安全)"""
    global WATCHLIST, MONITOR

    # 加锁：保证读-改-写的原子性
    with WATCHLIST_LOCK:
        reload_watchlist()  # 读取最新数据

        stock = next((s for s in WATCHLIST if s['code'] == code), None)
        if not stock:
            return jsonify({"error": f"Stock {code} not found"}), 404

        WATCHLIST = [s for s in WATCHLIST if s['code'] != code]
        save_watchlist(WATCHLIST)
        MONITOR = None
    return jsonify({"success": True, "message": f"Deleted {code}"})


@app.route('/api/stock/search')
def api_stock_search():
    """Search for stock code by name/code"""
    query = request.args.get('q', '').strip()
    if not query or len(query) < 1:
        return jsonify({"results": []})

    # 读取最新数据
    reload_watchlist()
    # Search from existing watchlist first
    results = []
    for s in WATCHLIST:
        if query.lower() in s['name'].lower() or query.lower() in s['code'].lower():
            results.append({
                "code": s['code'],
                "name": s['name'],
                "market": s['market'],
                "type": s['type']
            })

    # Also search via Sina API for real-time lookup
    if len(query) >= 2 and len(results) < 5:
        try:
            monitor = get_monitor()
            search_code = query
            if not query.startswith(('sh', 'sz')):
                # Try to guess market
                for prefix in ['sh', 'sz']:
                    try:
                        test_data = monitor.fetch_sina_realtime([{"code": query, "market": prefix, "name": query, "type": "individual"}])
                        if query in test_data and test_data[query].get('price', 0) > 0:
                            results.append({
                                "code": query,
                                "name": test_data[query].get('name', query),
                                "market": prefix,
                                "type": "individual"
                            })
                            break
                    except Exception:
                        pass
        except Exception:
            pass

    return jsonify({"results": results[:20]})


def main():
    parser = argparse.ArgumentParser(description='Stock Monitor Web API')
    parser.add_argument('--host', default='127.0.0.1', help='Host')
    parser.add_argument('--port', type=int, default=8765, help='Port')
    parser.add_argument('--debug', action='store_true', help='Debug mode')
    args = parser.parse_args()

    # Ensure web_static directory exists
    web_static = Path(__file__).parent / 'web_static'
    web_static.mkdir(exist_ok=True)

    print(f"Stock Monitor Web API starting...")
    print(f"  URL: http://{args.host}:{args.port}")
    print(f"  Static: {web_static}")
    print(f"  Logs: {LOG_DIR}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == '__main__':
    main()
