#!/usr/bin/env python3
"""
跨进程文件锁 (Windows / Linux / Mac 通用)

用法:
    from db_lock import file_lock

    with file_lock(lock_path):
        # 临界区 - 同一时间只有一个进程能进入
        do_critical_work()

实现:
    - Windows: msvcrt.locking (LK_LOCK)
    - Unix:    fcntl.flock (LOCK_EX)
"""

import os
import time
from contextlib import contextmanager


class _FileLock:
    """跨平台文件锁，支持 with 语句"""

    def __init__(self, lock_path, timeout=10):
        self.lock_path = str(lock_path)
        self.timeout = timeout
        self._fh = None

    def __enter__(self):
        self._fh = open(self.lock_path, 'a+')
        self._acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._release()
        if self._fh:
            self._fh.close()
        return False

    def _acquire(self):
        import sys
        start = time.time()
        while True:
            try:
                if sys.platform == 'win32':
                    import msvcrt
                    # LK_NBLCK = 1 (非阻塞), LK_LOCK = 2 (阻塞)
                    try:
                        msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                        return
                    except OSError:
                        pass
                else:
                    import fcntl
                    try:
                        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        return
                    except (OSError, IOError):
                        pass
            except Exception:
                pass

            if time.time() - start > self.timeout:
                raise TimeoutError(f"获取文件锁超时: {self.lock_path}")
            time.sleep(0.1)

    def _release(self):
        import sys
        try:
            if sys.platform == 'win32':
                import msvcrt
                try:
                    # 释放前先定位到文件头
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                except (OSError, IOError):
                    pass
        except Exception:
            pass


@contextmanager
def file_lock(lock_path, timeout=10):
    """跨进程文件锁上下文管理器

    Args:
        lock_path: 锁文件路径 (任意路径都可以，文件不存在会自动创建)
        timeout: 获取锁超时时间 (秒)

    Example:
        with file_lock('/tmp/myapp.lock'):
            # 临界区
            pass
    """
    lock = _FileLock(lock_path, timeout)
    lock.__enter__()
    try:
        yield lock
    finally:
        lock.__exit__(None, None, None)


def atomic_write_json(path, data, ensure_ascii=False, indent=2):
    """原子写入 JSON 文件

    先写入临时文件，再通过 os.replace 原子替换原文件，
    确保其他进程永远不会读到半写状态的数据。

    Args:
        path: 目标文件路径
        data: 要写入的数据 (会被 json.dump)
        ensure_ascii: json 参数
        indent: json 参数
    """
    import json
    from pathlib import Path

    path = Path(path)
    tmp_path = path.with_suffix(path.suffix + '.tmp')

    # 写入临时文件
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
        f.flush()
        os.fsync(f.fileno())  # 强制刷盘，防止系统崩溃丢数据

    # 原子替换 (Windows/Linux 都支持)
    os.replace(str(tmp_path), str(path))


def safe_read_json(path, default=None):
    """安全读取 JSON 文件

    如果文件不存在、损坏、或正在被写入，返回 default 值。
    不会抛出异常。

    Args:
        path: 文件路径
        default: 读取失败时返回的默认值
    """
    import json
    from pathlib import Path

    path = Path(path)
    if not path.exists():
        return default

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError, OSError):
        return default
