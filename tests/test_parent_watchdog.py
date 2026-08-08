"""`webui.parent_watchdog` 单测:外壳一死后端必须自了,但绝不能误杀。"""

from __future__ import annotations

import os

import pytest

from webui import parent_watchdog as pw


class TestParsers:
    @pytest.mark.parametrize("raw", ["4242", " 4242 ", 4242])
    def test_parse_pid_accepts_positive(self, raw):
        assert pw.parse_pid(raw) == 4242

    @pytest.mark.parametrize("raw", [None, "", "abc", "0", "1", "-5"])
    def test_parse_pid_rejects_invalid_and_reserved(self, raw):
        # 0(当前进程组)/1(init) 不是合法外壳 PID,解析失败一律不启动守望。
        assert pw.parse_pid(raw) is None

    def test_parse_interval_defaults_and_clamps(self):
        assert pw.parse_interval(None) == pw.DEFAULT_INTERVAL
        assert pw.parse_interval("abc") == pw.DEFAULT_INTERVAL
        assert pw.parse_interval("0.5") == 0.5
        assert pw.parse_interval("0") == 0.05
        assert pw.parse_interval("9999") == 30.0


class TestParentGone:
    def test_alive_parent_is_not_gone(self):
        assert pw.parent_gone(100, 100, getppid=lambda: 100, alive=lambda _pid: True) is False

    def test_reparented_direct_child_detected_immediately(self):
        # 我们本是外壳直接子进程,父进程一死就被 launchd/init 收养 → getppid 变 1。
        # 这条判据不看 PID 探活,所以即使 PID 被复用也能立刻发现。
        assert pw.parent_gone(100, 100, getppid=lambda: 1, alive=lambda _pid: True) is True

    def test_forked_bootloader_falls_back_to_pid_probe(self):
        # onefile 打包时 bootloader 多一层 fork,getppid != KRONOS_PARENT_PID,
        # 判据 1 天然不成立,不能因此误判「父进程没了」。
        assert pw.parent_gone(100, 55, getppid=lambda: 55, alive=lambda _pid: True) is False
        assert pw.parent_gone(100, 55, getppid=lambda: 55, alive=lambda _pid: False) is True

    def test_dead_pid_detected_without_reparent_signal(self):
        assert pw.parent_gone(100, 100, getppid=lambda: 100, alive=lambda _pid: False) is True

    def test_real_self_pid_is_alive(self):
        assert pw.process_alive(os.getpid()) is True


class TestWatchLoop:
    def test_fires_once_parent_disappears(self, monkeypatch):
        states = iter([False, False, True])
        monkeypatch.setattr(pw, "parent_gone", lambda *_a, **_k: next(states))
        fired: list[int] = []
        slept: list[float] = []

        triggered = pw.watch(777, None, 0.25, fired.append, sleep=slept.append, max_rounds=10)

        assert triggered is True
        assert fired == [777]
        assert slept == [0.25, 0.25]  # 触发那一轮不再 sleep

    def test_gives_up_after_max_rounds_without_firing(self, monkeypatch):
        monkeypatch.setattr(pw, "parent_gone", lambda *_a, **_k: False)
        fired: list[int] = []

        triggered = pw.watch(777, None, 0.01, fired.append, sleep=lambda _s: None, max_rounds=3)

        assert triggered is False
        assert fired == []


class TestStart:
    def test_not_started_without_parent_pid(self):
        assert pw.start_parent_watchdog(env={}) is None

    def test_not_started_when_disabled(self):
        env = {pw.ENV_PARENT_PID: "4242", pw.ENV_DISABLE: "1"}
        assert pw.start_parent_watchdog(env=env) is None

    def test_not_started_when_parent_is_self(self):
        # 命令行直跑时若环境里残留了自己的 PID,起来就会立刻自杀。
        env = {pw.ENV_PARENT_PID: str(os.getpid())}
        assert pw.start_parent_watchdog(env=env) is None

    def test_started_and_fires_when_parent_missing(self):
        # 一个必定不存在的 PID:守望线程应当立刻判定父进程已消失并回调。
        import threading

        fired = threading.Event()
        env = {pw.ENV_PARENT_PID: "2147483646", pw.ENV_INTERVAL: "0.01"}

        thread = pw.start_parent_watchdog(env=env, on_gone=lambda _pid: fired.set())

        assert thread is not None
        assert thread.daemon is True
        assert fired.wait(timeout=5.0) is True
        thread.join(timeout=5.0)
        assert thread.is_alive() is False
