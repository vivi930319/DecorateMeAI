"""訓練機的睡眠抑制。

這台機器設定成插電 5 分鐘、電池 3 分鐘就睡，而一次訓練要跑一兩個小時。
Windows 的閒置計時器看的是使用者輸入，不是 CPU 忙不忙——所以按下送訓之後
走開，機器照睡，訓練停在半路，十五分鐘後收到「訓練機失聯」。

要測的重點不是「有沒有擋」，是**有沒有還原**：忘了還原的話，這支常駐程式
活著的期間電腦永遠睡不著，而那是一個沒有人會發現、只會覺得電池很快沒電的壞法。
"""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

spec = importlib.util.spec_from_file_location("training_worker", ROOT / "tools/training_worker.py")
tw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tw)


class KeepAwakeTest(unittest.TestCase):
    def _fake_kernel32(self):
        calls = []
        fake = mock.Mock()
        fake.SetThreadExecutionState.side_effect = lambda flags: (calls.append(flags), 1)[1]
        return fake, calls

    def test_blocks_sleep_then_restores(self):
        fake, calls = self._fake_kernel32()
        with mock.patch.object(tw.sys, "platform", "win32"), \
             mock.patch.object(tw.ctypes, "windll", mock.Mock(kernel32=fake)):
            with tw._keep_awake("TR-x"):
                self.assertEqual(calls, [tw.ES_CONTINUOUS | tw.ES_SYSTEM_REQUIRED])
        self.assertEqual(calls[-1], tw.ES_CONTINUOUS, "離開區塊要把睡眠設定還回去")

    def test_restores_even_when_training_blows_up(self):
        """訓練失敗是常態，不能因此讓電腦永遠睡不著。"""
        fake, calls = self._fake_kernel32()
        with mock.patch.object(tw.sys, "platform", "win32"), \
             mock.patch.object(tw.ctypes, "windll", mock.Mock(kernel32=fake)):
            with self.assertRaises(RuntimeError):
                with tw._keep_awake():
                    raise RuntimeError("訓練炸了")
        self.assertEqual(calls[-1], tw.ES_CONTINUOUS)

    def test_a_refused_request_does_not_stop_training(self):
        """擋不了睡眠只是可能被中斷，不訓練是一定沒結果。"""
        fake = mock.Mock()
        fake.SetThreadExecutionState.return_value = 0      # 0 = 失敗
        ran = []
        with mock.patch.object(tw.sys, "platform", "win32"), \
             mock.patch.object(tw.ctypes, "windll", mock.Mock(kernel32=fake)):
            with tw._keep_awake():
                ran.append(True)
        self.assertEqual(ran, [True])
        # 沒拿到就不要還原：還原一個沒設過的狀態會清掉別人設的。
        self.assertEqual(fake.SetThreadExecutionState.call_count, 1)

    def test_other_platforms_are_left_alone(self):
        ran = []
        with mock.patch.object(tw.sys, "platform", "linux"):
            with tw._keep_awake():
                ran.append(True)
        self.assertEqual(ran, [True])


if __name__ == "__main__":
    unittest.main()
