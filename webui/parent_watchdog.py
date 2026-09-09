"""后端「父进程守望」:桌面外壳一消失,后端立刻自杀。

Tauri 外壳用 `process_group(0)` 拉起后端(独立进程组)。好处是外壳吃到
Ctrl-C / 前台信号时不会误杀后端、清理时能整组 kill;代价是外壳**非正常
死亡**(强制退出、崩溃、被 SIGKILL、退出事件没来得及跑完)时操作系统不会
连坐——后端会继续活着占住 127.0.0.1:7070,用户看到的就是「App 退了但没退
干净」,下次启动还得靠 `cleanup_stale_backend` 收尸。

外壳 spawn 后端时会带上 `KRONOS_PARENT_PID`;本模块起一个守护线程盯着它,
父进程一没了就 `os._exit()`。这条路不依赖外壳跑完任何退出事件,是「后端一定
跟着 App 走」的兜底保证。

没有 `KRONOS_PARENT_PID`(命令行直跑 / 开发直跑 / 测试)时不启动,避免误杀。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable, Mapping

ENV_PARENT_PID = "KRONOS_PARENT_PID"
ENV_DISABLE = "KRONOS_DISABLE_PARENT_WATCHDOG"
ENV_INTERVAL = "KRONOS_PARENT_WATCHDOG_INTERVAL"

DEFAULT_INTERVAL = 2.0
THREAD_NAME = "lumo-parent-watchdog"

_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def parse_pid(raw: object) -> int | None:
    """把环境变量里的 PID 解析成正整数,非法/缺失一律 None(即不启动守望)。"""
    try:
        pid = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    # 0 = 当前进程组、1 = init/launchd,都不是合法的「外壳父进程」。
    return pid if pid > 1 else None


def parse_interval(raw: object, default: float = DEFAULT_INTERVAL) -> float:
    try:
        interval = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    # 太小会空转烧 CPU,太大会让端口迟迟不释放。
    return min(max(interval, 0.05), 30.0)


def _posix_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # 进程在,只是不归我们管(换用户跑的情况)。
        return True
    except OSError:
        return True
    return True


def _windows_process_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def process_alive(pid: int) -> bool:
    if os.name == "nt":
        try:
            return _windows_process_alive(pid)
        except Exception:
            # ctypes 不可用时宁可判定「还活着」,绝不误杀后端。
            return True
    return _posix_process_alive(pid)


def parent_gone(
    parent_pid: int,
    initial_ppid: int | None = None,
    *,
    getppid: Callable[[], int] = os.getppid,
    alive: Callable[[int], bool] = process_alive,
) -> bool:
    """父进程是否已经消失。

    两条判据:
    1. 我们本来就是外壳的直接子进程(onedir 打包、开发直跑)——父进程一死我们
       立刻被 launchd/init 收养,`getppid()` 当场变值。这条最快,而且不受 PID
       复用影响。
    2. 兜底按 PID 探活。onefile 打包时 bootloader 会 fork 一层,`getppid()`
       指向 bootloader 而不是外壳,判据 1 不成立(initial_ppid != parent_pid),
       此时只看这条。
    """
    if initial_ppid is not None and initial_ppid == parent_pid and getppid() != initial_ppid:
        return True
    return not alive(parent_pid)


def _default_on_gone(parent_pid: int) -> None:
    print(
        f"[parent-watchdog] 桌面外壳进程 {parent_pid} 已退出,后端随之关闭",
        file=sys.stderr,
        flush=True,
    )
    # 必须 os._exit:本函数跑在守护线程里,sys.exit 只会结束这个线程;而 Robyn
    # 的 Rust 运行时占着主线程、连 SIGTERM 都不理会,没有别的干净退出通道。
    os._exit(0)


def watch(
    parent_pid: int,
    initial_ppid: int | None,
    interval: float,
    on_gone: Callable[[int], None],
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_rounds: int | None = None,
) -> bool:
    """轮询直到父进程消失,返回是否触发过 on_gone(`max_rounds` 仅供测试收敛)。"""
    rounds = 0
    while max_rounds is None or rounds < max_rounds:
        if parent_gone(parent_pid, initial_ppid):
            on_gone(parent_pid)
            return True
        rounds += 1
        sleep(interval)
    return False


def start_parent_watchdog(
    env: Mapping[str, str] | None = None,
    on_gone: Callable[[int], None] | None = None,
) -> threading.Thread | None:
    """按环境变量启动守望线程;不该启动时返回 None。"""
    env = os.environ if env is None else env

    if _truthy(env.get(ENV_DISABLE)):
        return None

    parent_pid = parse_pid(env.get(ENV_PARENT_PID))
    if parent_pid is None or parent_pid == os.getpid():
        return None

    interval = parse_interval(env.get(ENV_INTERVAL))
    initial_ppid = os.getppid()
    callback = on_gone or _default_on_gone

    thread = threading.Thread(
        target=watch,
        args=(parent_pid, initial_ppid, interval, callback),
        name=THREAD_NAME,
        daemon=True,
    )
    thread.start()
    # 打一行日志,好在 backend.stderr.log 里确认打包版本确实带上了守望。
    print(
        f"[parent-watchdog] 已盯住桌面外壳进程 {parent_pid}(每 {interval}s 探活一次)",
        file=sys.stderr,
        flush=True,
    )
    return thread
