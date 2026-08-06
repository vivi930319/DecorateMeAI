"""五官修正回饋的測試。

這個模組產出兩種資料，用途完全不同，混在一起會兩邊都壞掉：

  face_feedback     訓練資料，只收模型答錯的那些
  face_eval_events  評分紀錄，答對答錯都收，用來算線上信任分數

先前這裡沒有任何測試，而它同時是重訓的輸入與線上準確率的分母。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import face_feedback as ff

PREDICTED = {
    "臉型": "圓形臉", "眉型": "一字眉", "眼型": "鳳眼",
    "鼻型": "寬鼻", "嘴型": "薄唇",
}


class _FakeStore:
    def __init__(self):
        self.docs = {}

    def create(self, col, doc_id, data):
        self.docs[(col, doc_id)] = data

    def delete(self, col, doc_id):
        self.docs.pop((col, doc_id), None)


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        self.store = _FakeStore()
        self._real = ff.job_store
        ff.job_store = self.store

    def tearDown(self):
        ff.job_store = self._real

    def eval_doc(self, job_id):
        return self.store.docs.get((ff.EVAL_COL, job_id))

    def training_doc(self, job_id):
        return self.store.docs.get((ff.FEEDBACK_COL, job_id))

    def test_confirmation_is_counted_but_not_added_to_training_data(self):
        """使用者按「判斷正確」時，分母要 +1，訓練資料不能收。

        分母是線上信任分數的關鍵。先前只刪不記，於是看得到 30 筆錯誤，
        卻不知道那是 30/100 還是 30/1000。
        """
        ff.save("basic", "job-ok", {"confirmed": True, "corrections": {}, "predicted": PREDICTED})
        doc = self.eval_doc("job-ok")
        self.assertIsNotNone(doc, "答對也必須留下計數，否則算不出分母")
        self.assertEqual(len(doc["agreed"]), 5)
        self.assertEqual(doc["corrected"], [])
        self.assertIsNone(self.training_doc("job-ok"),
                          "答對的不該進訓練集，否則重訓會被『模型答對了』淹沒")

    def test_corrections_land_in_both_collections(self):
        """使用者改了部位：訓練集要收修正內容，評分紀錄要記哪些被改。"""
        ff.save("basic", "job-fix", {
            "confirmed": False,
            "corrections": {"眼型": "圓眼", "嘴型": "厚唇"},
            "predicted": PREDICTED,
        })
        ev = self.eval_doc("job-fix")
        self.assertEqual(sorted(ev["corrected"]), ["嘴型", "眼型"])
        self.assertEqual(sorted(ev["agreed"]), ["眉型", "臉型", "鼻型"])
        # 模型當時說什麼要留著，否則算不出「哪兩類分不開」
        self.assertEqual(ev["predicted"]["眼型"], "鳳眼")
        self.assertIsNotNone(self.training_doc("job-fix"))

    def test_resubmitting_the_same_job_overwrites_instead_of_double_counting(self):
        """同一次分析重送不能讓分母變兩倍。

        前端寫著「已送出，可再修改」，使用者改完又改回去是正常操作。
        文件 id 用 job_id 就是為了這件事。
        """
        ff.save("basic", "job-x", {"confirmed": False,
                                   "corrections": {"眼型": "圓眼"}, "predicted": PREDICTED})
        ff.save("basic", "job-x", {"confirmed": True, "corrections": {}, "predicted": PREDICTED})
        self.assertEqual(len([k for k in self.store.docs if k[0] == ff.EVAL_COL]), 1)
        self.assertEqual(self.eval_doc("job-x")["corrected"], [],
                         "改回正確之後，評分紀錄要反映最後一次的答案")

    def test_correcting_back_to_correct_clears_the_training_record(self):
        """改錯又改回來時，那筆錯誤標註必須從訓練集消失，不能無聲留著。"""
        ff.save("basic", "job-y", {"confirmed": False,
                                   "corrections": {"眼型": "圓眼"}, "predicted": PREDICTED})
        self.assertIsNotNone(self.training_doc("job-y"))
        ff.save("basic", "job-y", {"confirmed": True, "corrections": {}, "predicted": PREDICTED})
        self.assertIsNone(self.training_doc("job-y"),
                          "留著的話，使用者以為改回來了，訓練集裡卻還是錯的")

    def test_eval_record_carries_no_identity(self):
        """評分紀錄只記結果，不記身分——它會被拿去做統計，不該含個資。"""
        ff.save("basic", "job-z", {"confirmed": True, "corrections": {},
                                   "predicted": PREDICTED, "packageId": "AN-secret"})
        doc = self.eval_doc("job-z")
        flat = str(doc)
        for leaked in ("AN-secret", "ownerId", "email"):
            self.assertNotIn(leaked, flat, f"評分紀錄不該含 {leaked}")

    def test_missing_predicted_records_nothing(self):
        """沒有 predicted 就算不出對錯，不要記一筆空的把分母灌大。"""
        ff.save("basic", "job-empty", {"confirmed": True, "corrections": {}, "predicted": {}})
        self.assertIsNone(self.eval_doc("job-empty"))

    def test_eval_write_failure_does_not_break_the_feedback(self):
        """統計寫不進去，不能讓使用者的回饋一起失敗——那是量測，不是功能。"""
        class Exploding(_FakeStore):
            def create(self, col, doc_id, data):
                if col == ff.EVAL_COL:
                    raise RuntimeError("firestore down")
                super().create(col, doc_id, data)

        ff.job_store = Exploding()
        ff.save("basic", "job-boom", {"confirmed": False,
                                      "corrections": {"眼型": "圓眼"}, "predicted": PREDICTED})
        self.assertIsNotNone(ff.job_store.docs.get((ff.FEEDBACK_COL, "job-boom")),
                             "評分紀錄失敗時，訓練資料仍要收下")


if __name__ == "__main__":
    unittest.main()
