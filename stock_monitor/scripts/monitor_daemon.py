#!/usr/bin/env python3
"""
Stock Monitor Daemon - 后台常驻进程
跨平台 (Windows/Linux/Mac)，支持日志轮转、PID锁、优雅退出

用法:
    python monitor_daemon.py              # 前台运行
    python monitor_daemon.py --background  # 后台运行 (Windows: pythonw)
    python monitor_daemon.py --stop        # 停止进程
    python monitor_daemon.py --status      # 查看状态
"""

import sys
import os
import time
import signal
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from monitor import StockAlert, WATCHLIST, PID_FILE, LOG_DIR, LOG_FILE, ALERT_LOG_FILE

class MonitorDaemon:
    def __init__(self):
        self.monitor = StockAlert(log_to_file=True, log_to_console=True)
        self.running = True
        self.last_run_time = 0
        self._setup_signals()

    def _setup_signals(self):
        """跨平台信号处理"""
        if sys.platform == 'win32':
            self._setup_windows_signals()
        else:
            signal.signal(signal.SIGTERM, self._handle_shutdown)
            signal.signal(signal.SIGINT, self._handle_shutdown)

    def _setup_windows_signals(self):
        """Windows 控制台信号处理"""
        for sig_name in ['SIGINT', 'SIGBREAK']:
            if hasattr(signal, sig_name):
                sig = getattr(signal, sig_name)
                try:
                    signal.signal(sig, self._handle_shutdown)
                except (OSError, ValueError):
                    pass

    def _handle_shutdown(self, signum=None, frame=None):
        self.monitor.logger.info(f"收到退出信号，正在停止...")
        self.running = False

    def _get_sleep_interval(self):
        schedule = self.monitor.should_run_now()
        if not schedule.get("run"):
            now = datetime.now()
            hour = now.hour
            if 0 <= hour < 9:
                return 1800
            return 300
        return schedule.get("interval", 300)

    def run(self):
        self.monitor.logger.info("=" * 60)
        self.monitor.logger.info("股票监控后台进程启动")
        self.monitor.logger.info(f"PID: {os.getpid()}")
        self.monitor.logger.info(f"监控标的: {len(WATCHLIST)} 只")
        self.monitor.logger.info(f"日志文件: {LOG_FILE}")
        self.monitor.logger.info(f"预警日志: {ALERT_LOG_FILE}")
        self.monitor.logger.info("=" * 60)

        while self.running:
            try:
                schedule = self.monitor.should_run_now()

                if schedule.get("run"):
                    mode = schedule.get("mode", "normal")
                    stocks_count = len(schedule.get("stocks", []))
                    self.monitor.logger.info(f"[{mode}] 扫描 {stocks_count} 只标的...")

                    alerts = self.monitor.run_once(smart_mode=False)

                    if alerts:
                        self.monitor.logger.info(f"触发 {len(alerts)} 条预警")
                        for alert in alerts:
                            print(alert)
                    else:
                        self.monitor.logger.info("扫描完成，无预警触发")

                    self.last_run_time = time.time()

                sleep_interval = self._get_sleep_interval()

                slept = 0
                while slept < sleep_interval and self.running:
                    time.sleep(1)
                    slept += 1

            except Exception as e:
                self.monitor.logger.error(f"运行出错: {e}", exc_info=True)
                time.sleep(60)

        self.monitor.logger.info("股票监控后台进程已停止")


def stop_daemon():
    if not PID_FILE.exists():
        print("监控进程未运行")
        return

    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        PID_FILE.unlink(missing_ok=True)
        print("PID文件损坏，已清理")
        return

    if sys.platform == 'win32':
        result = subprocess.run(
            ['taskkill', '/PID', str(pid), '/F'],
            capture_output=True, text=True
        )
        if 'SUCCESS' in result.stdout or '成功' in result.stdout:
            print(f"已停止进程 PID: {pid}")
        else:
            print(f"停止失败: {result.stdout.strip() or result.stderr.strip()}")
    else:
        try:
            os.kill(pid, 15)
            print(f"已停止进程 PID: {pid}")
        except ProcessLookupError:
            print(f"进程 {pid} 不存在")

    PID_FILE.unlink(missing_ok=True)


def check_status():
    if not PID_FILE.exists():
        print("监控进程未运行")
        return

    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        print("监控进程未运行 (PID文件损坏)")
        return

    if sys.platform == 'win32':
        result = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}'],
            capture_output=True, text=True
        )
        if str(pid) in result.stdout:
            print(f"监控进程运行中 (PID: {pid})")
            print(f"日志文件: {LOG_FILE}")
            print(f"预警日志: {ALERT_LOG_FILE}")
        else:
            print("监控进程未运行 (PID文件过期)")
            PID_FILE.unlink(missing_ok=True)
    else:
        try:
            os.kill(pid, 0)
            print(f"监控进程运行中 (PID: {pid})")
        except ProcessLookupError:
            print("监控进程未运行")
            PID_FILE.unlink(missing_ok=True)


def show_logs(alert_only=False):
    log_path = ALERT_LOG_FILE if alert_only else LOG_FILE
    label = "预警记录" if alert_only else "运行日志"

    if not log_path.exists():
        print(f"暂无{label}")
        return

    with open(log_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    print(f"=== 最近 {label} ({len(lines)} 条) ===\n")
    print(''.join(lines[-50:]))


def main():
    parser = argparse.ArgumentParser(description='股票监控后台进程')
    parser.add_argument('--stop', '-s', action='store_true', help='停止后台进程')
    parser.add_argument('--status', help='查看进程状态', action='store_true')
    parser.add_argument('--logs', '-l', action='store_true', help='查看最近日志')
    parser.add_argument('--alerts', '-a', action='store_true', help='查看最近预警')
    parser.add_argument('--background', '-b', action='store_true', help='后台运行')
    args = parser.parse_args()

    if args.status:
        check_status()
        return

    if args.stop:
        stop_daemon()
        return

    if args.logs:
        show_logs(alert_only=False)
        return

    if args.alerts:
        show_logs(alert_only=True)
        return

    my_pid = os.getpid()

    if PID_FILE.exists():
        try:
            existing_pid = int(PID_FILE.read_text().strip())
            if existing_pid != my_pid:
                check_status()
                print("\n如需重启，请先使用 --stop 停止旧进程")
                return
            PID_FILE.unlink(missing_ok=True)
        except (ValueError, OSError):
            PID_FILE.unlink(missing_ok=True)

    PID_FILE.write_text(str(my_pid))

    try:
        daemon = MonitorDaemon()
        daemon.run()
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
