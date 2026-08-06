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

# 真的 PNG。用截斷的假資料會被 data_url_to_bytes 的驗證擋掉，
# 那樣測到的是「驗證有效」而不是「同意閘門有效」。
_TINY_PNG_DATA_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAJElEQVQIHW3BAQEAAAABIP4fa5YDqshT5CnyFHmKPEWeIk+RZxykEskvcOowAAAAAElFTkSuQmCC"

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


class ContributionConsentTest(unittest.TestCase):
    """使用者貢獻的訓練樣本：沒有明確同意就不能存下任何東西。

    這條路徑會保存臉部裁切，所以「預設不存」必須是結構保證，不是靠後端自律。
    """

    def setUp(self):
        self.store = _FakeStore()
        self._real_store = ff.job_store
        ff.job_store = self.store
        self.calls = []
        self._real_contrib = ff.face_contributions.store
        ff.face_contributions.store = lambda *a, **k: self.calls.append((a, k)) or 1

    def tearDown(self):
        ff.job_store = self._real_store
        ff.face_contributions.store = self._real_contrib

    def _payload(self, **over):
        base = {
            "confirmed": False,
            "corrections": {"眼型": "圓眼"},
            "predicted": PREDICTED,
            "allowTrainingUse": True,
            "imageDataUrl": _TINY_PNG_DATA_URL,
        }
        base.update(over)
        return base

    def test_nothing_stored_without_consent(self):
        """沒勾同意 → 一張都不能存，即使照片就在請求裡。"""
        ff.save("basic", "job-a", self._payload(allowTrainingUse=False))
        self.assertEqual(self.calls, [], "未同意卻保存了臉部裁切")

    def test_nothing_stored_without_an_image(self):
        """同意了但沒帶照片 → 沒有東西可存，不該當成錯誤，也不該亂猜。"""
        ff.save("basic", "job-b", self._payload(imageDataUrl=None))
        self.assertEqual(self.calls, [])

    def test_nothing_stored_when_user_confirmed_the_model(self):
        """使用者按「判斷正確」→ 沒有修正，就沒有值得保存的樣本。"""
        ff.save("basic", "job-c", self._payload(confirmed=True, corrections={}))
        self.assertEqual(self.calls, [])

    def test_stored_only_with_explicit_consent_and_corrections(self):
        """三個條件齊備才會存，而且只帶被修正的部位。"""
        ff.save("basic", "job-d", self._payload())
        self.assertEqual(len(self.calls), 1)
        args, kwargs = self.calls[0]
        self.assertEqual(args[0], "job-d")
        self.assertEqual(args[2], {"眼型": "圓眼"}, "只該帶被修正的部位")

    def test_contribution_failure_never_breaks_the_feedback(self):
        """保存樣本失敗，使用者的修正仍要收下——那是加值功能，不是主流程。"""
        def explode(*a, **k):
            raise RuntimeError("gcs down")

        ff.face_contributions.store = explode
        ff.save("basic", "job-e", self._payload())
        self.assertIsNotNone(self.store.docs.get((ff.FEEDBACK_COL, "job-e")),
                             "貢獻失敗時，訓練修正仍要進 face_feedback")


class RoiSpecsVersionTest(unittest.TestCase):
    """裁切規格的版本指紋。

    貢獻樣本存的是**已裁切**的影像，原圖不留，所以規格一改就無法重裁。
    版本要跟樣本一起存，否則舊樣本會靜默混進新訓練集。
    """

    def test_version_changes_when_the_crop_changes(self):
        import face_roi

        before = face_roi.specs_version()
        original = face_roi.ROI_SPECS["eye_shape"]["margin"]
        try:
            face_roi.ROI_SPECS["eye_shape"]["margin"] = original + 0.05
            self.assertNotEqual(face_roi.specs_version(), before,
                                "改了裁切卻沿用同一個版本，舊樣本會被靜默混用")
        finally:
            face_roi.ROI_SPECS["eye_shape"]["margin"] = original
        self.assertEqual(face_roi.specs_version(), before, "改回來要復原，否則版本沒有意義")


class MemberDeletionRouteTest(unittest.TestCase):
    """會員刪除端點：本人或管理員才能刪，而且真的要刪得掉。

    存得下卻刪不掉的臉部資料，比一開始就不存更糟——所以這條路徑的權限與行為
    都要有測試守著。
    """

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        self.deleted = []
        self._real = ff.face_contributions.delete_for_owner
        ff.face_contributions.delete_for_owner = lambda owner: (self.deleted.append(owner) or 3)

        app = FastAPI()
        ff.register_route(app, mode="basic", jobs_collection="face_jobs_basic",
                          verify_job_token=lambda *a, **k: None)
        self.client = TestClient(app)

    def tearDown(self):
        ff.face_contributions.delete_for_owner = self._real

    def test_owner_can_delete_their_own(self):
        r = self.client.delete("/v1/face/users/actor_me", headers={"X-User-ID": "actor_me"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["contributions"], 3, "要回報刪了幾筆，呼叫端才知道有沒有生效")
        self.assertEqual(self.deleted, ["actor_me"])

    def test_stranger_cannot_delete_someone_else(self):
        r = self.client.delete("/v1/face/users/actor_victim",
                               headers={"X-User-ID": "actor_attacker"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.deleted, [], "被擋下時不能真的刪到任何東西")

    def test_missing_identity_is_refused(self):
        """沒帶身分不能通過——否則把標頭拿掉就繞過了。"""
        r = self.client.delete("/v1/face/users/actor_victim")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.deleted, [])

    def test_admin_may_delete_on_behalf(self):
        """會員刪除是由後台流程觸發的，管理員要能代為執行。"""
        r = self.client.delete("/v1/face/users/actor_someone",
                               headers={"X-Admin-Request": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.deleted, ["actor_someone"])


if __name__ == "__main__":
    unittest.main()
