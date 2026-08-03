"""股票分析服务器启动脚本"""
import subprocess
import time
import sys
import os

def check_server():
    """检查服务器是否在运行"""
    try:
        import requests
        r = requests.get('http://127.0.0.1:5000/api/health', timeout=2)
        return r.status_code == 200
    except:
        return False

def kill_port_5000():
    """释放5000端口"""
    try:
        import subprocess
        result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if ':5000' in line and 'LISTENING' in line:
                parts = line.strip().split()
                if parts:
                    pid = parts[-1]
                    print(f"  终止占用端口的进程 PID: {pid}")
                    subprocess.run(['taskkill', '/F', '/PID', pid], 
                                 capture_output=True, timeout=5)
        time.sleep(1)
    except Exception as e:
        print(f"  清理端口失败: {e}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description='启动股票分析服务器')
    parser.add_argument('--no-pause', action='store_true', help='不等待按键')
    args = parser.parse_args()
    
    print("=" * 50)
    print("  股票凯利分析器 - 服务器启动")
    print("=" * 50)
    print()
    
    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)
    
    # 检查服务器状态
    if check_server():
        print("[提示] 服务器已在运行")
        print("[访问] http://127.0.0.1:5000")
        if not args.no_pause:
            print()
            input("按回车键退出...")
        return
    
    # 释放端口
    print("[检查] 正在释放端口...")
    kill_port_5000()
    
    # 启动服务器
    print("[启动] 正在启动服务器...")
    try:
        # 使用subprocess启动后台进程
        startupinfo = None
        if sys.platform == 'win32':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # 隐藏窗口
        
        process = subprocess.Popen(
            [sys.executable, 'app.py'],
            cwd=project_dir,
            shell=False,
            creationflags=0x00000008 if sys.platform == 'win32' else 0  # CREATE_NO_WINDOW
        )
        
        # 等待启动
        for i in range(10):
            time.sleep(1)
            if check_server():
                print(f"[成功] 服务器已启动！(PID: {process.pid})")
                print(f"[访问] http://127.0.0.1:5000")
                break
        else:
            print("[警告] 服务器启动超时")
            print(f"[提示] 可手动运行: python app.py")
    except Exception as e:
        print(f"[失败] 启动异常: {e}")
    
    print()
    if not args.no_pause:
        input("按回车键退出...")

if __name__ == '__main__':
    main()