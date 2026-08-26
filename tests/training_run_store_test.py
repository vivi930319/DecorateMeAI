"""訓練批次狀態寫回的測試。

重點在 fail_run：它同時要做兩件事，而其中一件在 2026-08-26 之前根本不存在。

「訓練機失聯」告警盯的是心跳指標消失，所以它抓得到斷網與關機，卻**抓不到
「機器活著、訓練炸了」**——那時候心跳照跳。失敗因此只出現在後台畫面上，
要有人主動去看才會發現。這裡的測試就是釘住「失敗會推出告警指標」這件事，
否則哪天有人把那行拿掉，症狀是**沉默**，不會有任何測試變紅。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))

import training_run_store as store


class FailRunTest(unittest.TestCase):
    def test_records_the_reason_before_pushing_the_metric(self):
        calls = []
        with mock.patch.object(store, "patch_document",
                               side_effect=lambda *a, **k: calls.append(("patch", a[3]))), \
             mock.patch.object(store, "_push_failure_metric",
                               side_effect=lambda *a: calls.append(("metric", None))):
            store.fail_run("decorate-me", "TR-x", "顯示卡記憶體不足")

        self.assertEqual([c[0] for c in calls], ["patch", "metric"],
                         "記錄要先寫進去：推指標失敗不該讓後台要顯示的原因跟著消失")
        patch = calls[0][1]
        self.assertEqual(patch["status"], "failed")
        self.assertEqual(patch["error"], "顯示卡記憶體不足")

    def test_truncates_a_huge_error_so_the_write_still_fits(self):
        seen = {}
        with mock.patch.object(store, "patch_document",
                               side_effect=lambda *a, **k: seen.update(a[3])), \
             mock.patch.object(store, "_push_failure_metric"):
            store.fail_run("decorate-me", "TR-x", "x" * 5000)
        # Firestore 單一欄位有大小上限，而一段 PyTorch 的錯誤輕易就上千字。
        self.assertEqual(len(seen["error"]), 1500)

    def test_an_empty_reason_still_says_something_readable(self):
        seen = {}
        with mock.patch.object(store, "patch_document",
                               side_effect=lambda *a, **k: seen.update(a[3])), \
             mock.patch.object(store, "_push_failure_metric"):
            store.fail_run("decorate-me", "TR-x", "")
        # 後台會把這個欄位直接顯示給人看，空字串等於沒告訴任何人發生什麼事。
        self.assertTrue(seen["error"])

    def test_the_run_id_never_becomes_a_metric_label(self):
        """每個批次的 id 都不一樣，當標籤會讓時間序列無限增生。"""
        sent = {}
        with mock.patch.object(store, "_write_time_series",
                               side_effect=lambda p, t, l: sent.update({"type": t, "labels": l})):
            store._push_failure_metric("decorate-me", "TR-abcdef123456")
        self.assertEqual(sent["type"], store.FAILURE_METRIC)
        self.assertEqual(sent["labels"], {})

    def test_a_dead_network_does_not_take_the_failure_record_with_it(self):
        """推指標是盡力而為；它失敗不該蓋掉「這個批次失敗了」這個事實。

        真的斷網時推不上去，正好就是「訓練機失聯」那條告警負責的狀態。
        """
        seen = {}
        with mock.patch.object(store, "patch_document",
                               side_effect=lambda *a, **k: seen.update(a[3])), \
             mock.patch.object(store, "_open", side_effect=OSError("網路不通")):
            store.fail_run("decorate-me", "TR-x", "訓練炸了")
        self.assertEqual(seen["status"], "failed")


if __name__ == "__main__":
    unittest.main()
