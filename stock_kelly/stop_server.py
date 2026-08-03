"""股票分析服务器停止脚本"""
import subprocess
import time
import sys
import os

def main():
    print("=" * 50)
    print("  股票凯利分析器 - 停止服务器")
    print("=" * 50)
    print()
    
    # 查找并终止占用5000端口的进程
    print("[查找] 正在查找占用5000端口的进程...")
    try:
        result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
        pids_found = []
        
        for line in result.stdout.split('\n'):
            if ':5000' in line and 'LISTENING' in line:
                parts = line.strip().split()
                if parts:
                    pid = parts[-1]
                    pids_found.append(pid)
        
        if pids_found:
            for pid in pids_found:
                print(f"[发现] 找到进程 PID: {pid}")
                subprocess.run(['taskkill', '/F', '/PID', pid], 
                            capture_output=True, timeout=5)
                print(f"[停止] 进程 {pid} 已终止")
        else:
            print("[提示] 未找到占用5000端口的进程")
    
    except Exception as e:
        print(f"[错误] {e}")
    
    print()
    print("[完成] 服务器停止操作完成")
    time.sleep(1)

if __name__ == '__main__':
    main()