"""股票分析服务器守护脚本 - 监控并自动重启服务器"""
import subprocess
import time
import sys
import os
import requests

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_SCRIPT = os.path.join(PROJECT_DIR, 'app.py')
HEALTH_URL = 'http://127.0.0.1:5000/api/health'
CHECK_INTERVAL = 30  # 每30秒检查一次
MAX_RESTART_ATTEMPTS = 5  # 最大重启次数


def check_server():
    """检查服务器健康状态"""
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        return r.status_code == 200
    except:
        return False


def get_server_pid():
    """获取当前服务器进程PID"""
    try:
        result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if ':5000' in line and 'LISTENING' in line:
                parts = line.strip().split()
                if parts:
                    return parts[-1]
    except:
        pass
    return None


def kill_server():
    """停止服务器"""
    pid = get_server_pid()
    if pid:
        try:
            subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True, timeout=5)
            time.sleep(2)
            print(f"  [守护] 已终止旧服务器进程 PID: {pid}")
        except Exception as e:
            print(f"  [守护] 终止进程失败: {e}")


def start_server():
    """启动服务器"""
    try:
        process = subprocess.Popen(
            [sys.executable, SERVER_SCRIPT],
            cwd=PROJECT_DIR,
            shell=False,
            creationflags=0x00000008 if sys.platform == 'win32' else 0
        )
        print(f"  [守护] 服务器已启动 PID: {process.pid}")
        return process
    except Exception as e:
        print(f"  [守护] 启动服务器失败: {e}")
        return None


def main():
    print("=" * 50)
    print("  股票凯利分析器 - 服务器守护进程")
    print("=" * 50)
    print()
    print(f"[配置] 检查间隔: {CHECK_INTERVAL}秒")
    print(f"[配置] 健康检查URL: {HEALTH_URL}")
    print()
    
    restart_count = 0
    server_process = None
    
    # 初始启动
    if not check_server():
        print("[守护] 服务器未运行，正在启动...")
        kill_server()
        server_process = start_server()
        time.sleep(3)
    
    print("[守护] 开始监控...")
    print()
    
    try:
        while True:
            time.sleep(CHECK_INTERVAL)
            
            if not check_server():
                print(f"[{time.strftime('%H:%M:%S')}] 检测到服务器无响应！")
                restart_count += 1
                
                if restart_count > MAX_RESTART_ATTEMPTS:
                    print(f"[守护] 已重启{restart_count}次，可能存在严重问题")
                    print("[守护] 等待60秒后重试...")
                    time.sleep(60)
                    restart_count = 0
                
                kill_server()
                server_process = start_server()
                
                if server_process:
                    # 等待启动
                    for i in range(10):
                        time.sleep(1)
                        if check_server():
                            print(f"[守护] 服务器恢复正常！")
                            restart_count = 0
                            break
                    else:
                        print("[守护] 服务器启动超时")
            else:
                if restart_count > 0:
                    print(f"[{time.strftime('%H:%M:%S')}] 服务器运行正常 (已恢复)")
                    restart_count = 0
    
    except KeyboardInterrupt:
        print("\n[守护] 正在退出...")
        if server_process:
            server_process.terminate()
        print("[守护] 已停止")


if __name__ == '__main__':
    main()