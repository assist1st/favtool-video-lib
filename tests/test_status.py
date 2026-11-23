"""采集任务状态逻辑的单测：不碰浏览器，也不碰真实数据。

runner.py 在模块层 import playwright，而 CI 不装 playwright（平台适配器也不随
仓库分发），所以这里先塞一个假的 playwright.sync_api，import 才不会直接炸。
"""
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if "playwright" not in sys.modules:
    _pw = types.ModuleType("playwright")
    _sync = types.ModuleType("playwright.sync_api")
    _sync.sync_playwright = lambda: None
    _pw.sync_api = _sync
    sys.modules["playwright"] = _pw
    sys.modules["playwright.sync_api"] = _sync

from app import runner


def dead_pid():
    """一个确实已经退出的进程 pid。"""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class TestStatusFile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="favtool-status-"))
        self._saved = runner.STATUS_FILE
        runner.STATUS_FILE = self.tmp / "collect-status.json"

    def tearDown(self):
        runner.STATUS_FILE = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_file_is_idle(self):
        self.assertEqual(runner.read_status()["state"], "idle")

    def test_running_task_keeps_state_while_pid_alive(self):
        runner.Status().set(state="collecting", count=12, pid=os.getpid())
        st = runner.read_status()
        self.assertEqual(st["state"], "collecting")
        self.assertEqual(st["count"], 12)

    def test_dead_pid_is_treated_as_interrupted(self):
        # 采集进程没了，状态文件里的「进行中」只是残影，不能再当成它在跑
        runner.Status().set(state="collecting", count=12, pid=dead_pid())
        self.assertEqual(runner.read_status()["state"], "idle")

    def test_dead_pid_does_not_lock_the_button_forever(self):
        # 旧逻辑靠「超过 20 分钟」判残影：刚被杀掉的任务会把按钮锁死 20 分钟
        runner.Status().set(state="collecting", count=12, pid=dead_pid())
        self.assertEqual(runner.read_status()["state"], "idle")

    def test_long_task_is_not_killed_by_age(self):
        # 登录要等 15 分钟，再加上扫描，很容易超过 20 分钟：
        # 只要进程还活着，就不能按残影处理
        runner.Status().set(state="waiting_login", pid=os.getpid())
        self.assertEqual(runner.read_status()["state"], "waiting_login")

    def test_raw_status_keeps_the_original_record(self):
        runner.Status().set(state="collecting", count=12, pid=dead_pid())
        self.assertEqual(runner.raw_status()["state"], "collecting")

    def test_status_set_records_the_given_pid(self):
        runner.Status().set(state="starting", pid=4242)
        self.assertEqual(runner.raw_status()["pid"], 4242)


if __name__ == "__main__":
    unittest.main()
