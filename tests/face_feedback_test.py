"""五官修正回饋的測試。

這個模組產出兩種資料，用途完全不同，混在一起會兩邊都壞掉：

  face_feedback     訓練資料，只收模型答錯的那些
  face_eval_events  評分紀錄，答對答錯都收，用來算線上信任分數

先前這裡沒有任何測試，而它同時是重訓的輸入與線上準確率的分母。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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

    def test_owner_comes_from_the_job_not_the_request(self):
        """ownerId 必須來自 job 文件，不能來自客戶端送的 payload。

        第一版寫成 payload.get("ownerId")，而 FeedbackIn 根本沒有那個欄位，
        所以每一筆都是空的——物件存進了 GCS 卻沒有擁有者，delete_for_owner
        永遠找不到它們。存得下、刪不掉，比一開始就不存更糟。

        而且就算補了那個欄位也不能用：payload 是客戶端送的，
        讓它自稱擁有者等於誰都能把樣本掛到別人名下。
        """
        ff.save("basic", "job-f", self._payload(ownerId="actor_client_claims"),
                owner_id="actor_from_job")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1]["owner_id"], "actor_from_job",
                         "採用了客戶端宣稱的身分，而不是 job 上記錄的")

    def test_missing_owner_is_still_recorded_as_such(self):
        """沒有 ownerId（訪客）時仍要能看出來，不要靜默存成空字串就算了。"""
        ff.save("basic", "job-g", self._payload(), owner_id=None)
        self.assertIsNone(self.calls[0][1]["owner_id"])

    def test_contribution_failure_never_breaks_the_feedback(self):
        """保存樣本失敗，使用者的修正仍要收下——那是加值功能，不是主流程。"""
        def explode(*a, **k):
            raise RuntimeError("gcs down")

        ff.face_contributions.store = explode
        ff.save("basic", "job-e", self._payload())
        self.assertIsNotNone(self.store.docs.get((ff.FEEDBACK_COL, "job-e")),
                             "貢獻失敗時，訓練修正仍要進 face_feedback")


class ProNoseSideFieldTest(unittest.TestCase):
    """PRO 側臉鼻型是獨立欄位、獨立分類法，不能跟 BASIC 的正面鼻型混用。

    兩顆模型的類別完全不重疊（正面：寬鼻／標準鼻；側臉：塌鼻／直挺鼻／翹鼻／
    蒜頭鼻／駝峰鼻）。混用不會壞在畫面上，會壞在重訓時——BASIC 的訓練集裡
    混進五個它不認識的類別，而那正是 validate() 存在的理由。
    """

    def setUp(self):
        ff._allowed_cache = None      # 分類表有快取，測試之間要清掉

    def tearDown(self):
        ff._allowed_cache = None

    def _pro_available(self) -> bool:
        return bool(ff.allowed_classes().get(ff.PRO_NOSE_FIELD))

    def test_pro_classes_are_loaded_from_the_pro_model_dir(self):
        if not self._pro_available():
            self.skipTest("這個環境沒有 PRO 模型目錄（BASIC 服務屬正常）")
        classes = ff.allowed_classes()[ff.PRO_NOSE_FIELD]
        self.assertIn("駝峰鼻", classes)
        self.assertNotIn("寬鼻", classes, "側臉分類表混進了正面鼻型的類別")

    def test_front_and_side_taxonomies_do_not_leak_into_each_other(self):
        if not self._pro_available():
            self.skipTest("這個環境沒有 PRO 模型目錄")
        ff.validate({ff.PRO_NOSE_FIELD: "駝峰鼻"})        # 合法
        with self.assertRaises(ff.FeedbackRejected):
            ff.validate({ff.PRO_NOSE_FIELD: "寬鼻"})      # 正面的類別不能進側臉欄位
        with self.assertRaises(ff.FeedbackRejected):
            ff.validate({"鼻型": "駝峰鼻"})                # 側臉的類別也不能進正面欄位

    def test_field_budget_leaves_room_for_the_pro_field(self):
        """上限要含 PRO 那一欄，否則五個部位加側臉鼻型會被當成超量而整包退回。"""
        self.assertEqual(ff._MAX_FIELDS, 6)


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


class ReviewRouteTest(unittest.TestCase):
    """覆核端點：管理員把一筆修正標成採用或退回。

    這條路徑決定**哪些使用者修正會變成訓練標籤**。放行未經查核的資料，
    後果不是「多一筆沒用的紀錄」，而是分數變差之後查不回原因——所以這裡
    要守住三件事：只有管理員能寫、decision 只能是那兩個、不存在的 id 要說不存在。
    """

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        self.store = _FakeStore()
        # 這個假 store 要多兩個方法：覆核會先 get 再 patch。
        self.store.get = lambda col, doc_id: self.store.docs.get((col, doc_id))
        self.patched = {}

        def _patch(col, doc_id, updates):
            self.patched[(col, doc_id)] = updates
            self.store.docs.setdefault((col, doc_id), {}).update(updates)

        self.store.patch = _patch
        self._real = ff.job_store
        ff.job_store = self.store
        self.store.docs[(ff.FEEDBACK_COL, "JOB-1")] = {
            "jobId": "JOB-1", "corrections": {"眉型": "一字眉"},
        }

        app = FastAPI()
        ff.register_route(app, mode="basic", jobs_collection="face_jobs_basic",
                          verify_job_token=lambda *a, **k: None)
        self.client = TestClient(app)

    def tearDown(self):
        ff.job_store = self._real

    def _patch_review(self, feedback_id, body, admin=True):
        headers = {"X-Admin-Request": "1"} if admin else {}
        return self.client.patch(f"/v1/face/feedback/{feedback_id}/review",
                                 json=body, headers=headers)

    def test_admin_can_accept(self):
        r = self._patch_review("FB-JOB-1", {"decision": "accepted"})
        self.assertEqual(r.status_code, 200)
        saved = self.store.docs[(ff.FEEDBACK_COL, "JOB-1")]
        self.assertEqual(saved["reviewStatus"], "accepted")
        self.assertTrue(saved["reviewedAt"])

    def test_feedback_id_prefix_is_optional(self):
        # 文件 id 是 jobId，但清單回的是 FB-<jobId>。兩種都要收，
        # 否則前端得記住這個細節，而它遲早會記錯。
        self.assertEqual(self._patch_review("JOB-1", {"decision": "rejected"}).status_code, 200)
        self.assertEqual(self.store.docs[(ff.FEEDBACK_COL, "JOB-1")]["reviewStatus"], "rejected")

    def test_non_admin_is_refused(self):
        r = self._patch_review("FB-JOB-1", {"decision": "accepted"}, admin=False)
        self.assertEqual(r.status_code, 403)
        # 被擋下時什麼都不能寫進去。
        self.assertNotIn("reviewStatus", self.store.docs[(ff.FEEDBACK_COL, "JOB-1")])

    def test_unknown_decision_is_refused(self):
        for bad in ("approved", "ACCEPTED", "", "pending", None):
            with self.subTest(decision=bad):
                r = self._patch_review("FB-JOB-1", {"decision": bad})
                self.assertEqual(r.status_code, 422)
        # pending 也不行：那是「還沒有人看」的意思，不是一個可以主動下的判斷。
        self.assertNotIn("reviewStatus", self.store.docs[(ff.FEEDBACK_COL, "JOB-1")])

    def test_missing_document_is_not_created(self):
        r = self._patch_review("FB-JOB-NOPE", {"decision": "accepted"})
        self.assertEqual(r.status_code, 404)
        # patch 若沒有先確認存在，這裡會憑空生出一筆只有覆核狀態、
        # 沒有任何修正內容的文件——之後匯入時就會看到一筆空標籤。
        self.assertNotIn((ff.FEEDBACK_COL, "JOB-NOPE"), self.store.docs)

    def test_note_is_capped(self):
        r = self._patch_review("FB-JOB-1", {"decision": "accepted", "note": "字" * 900})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.store.docs[(ff.FEEDBACK_COL, "JOB-1")]["reviewNote"]), 500)


class ContributedFlagTest(unittest.TestCase):
    """文件上的 contributed 要如實反映「GCS 上到底有沒有影像」。

    覆核的人靠這個欄位決定要不要點開來看。標成有、實際沒有，等於叫人去找一張
    不存在的圖；標成沒有、實際有，那張圖就永遠不會被人看到也不會進訓練集。
    """

    def setUp(self):
        self.store = _FakeStore()
        self._real_store = ff.job_store
        ff.job_store = self.store
        self._real_get = ff.job_store.get if hasattr(ff.job_store, "get") else None
        self._real_store_fn = ff.face_contributions.store
        self.calls = []
        ff.face_contributions.store = lambda *a, **k: self.calls.append(k)

    def tearDown(self):
        ff.job_store = self._real_store
        ff.face_contributions.store = self._real_store_fn

    def _save(self, **payload):
        ff.save("basic", "JOB-C", {
            "predicted": PREDICTED,
            "corrections": {"眉型": "彎月眉"},
            **payload,
        })
        return self.store.docs.get((ff.FEEDBACK_COL, "JOB-C"))

    def test_true_when_an_image_was_stored(self):
        doc = self._save(allowTrainingUse=True, imageDataUrl=_TINY_PNG_DATA_URL)
        self.assertTrue(doc["contributed"])

    def test_false_without_consent(self):
        doc = self._save(allowTrainingUse=False, imageDataUrl=_TINY_PNG_DATA_URL)
        self.assertFalse(doc["contributed"])
        self.assertEqual(self.calls, [])

    def test_false_without_an_image(self):
        doc = self._save(allowTrainingUse=True)
        self.assertFalse(doc["contributed"])

    def test_false_when_the_upload_failed(self):
        # 存不進 GCS 時使用者的修正還是要收下（那是刻意的），但這個欄位不能說謊。
        def _boom(*a, **k):
            raise RuntimeError("GCS 掛了")
        ff.face_contributions.store = _boom
        doc = self._save(allowTrainingUse=True, imageDataUrl=_TINY_PNG_DATA_URL)
        self.assertIsNotNone(doc, "上傳失敗不該讓整筆回饋消失")
        self.assertFalse(doc["contributed"])


class ImageOnlyDependsOnModulesInTheFaceImageTest(unittest.TestCase):
    """貢獻路徑只能用 face 映像裡有的模組。

    第一版從 replicate_render import data_url_to_bytes。本機測全過——磁碟上檔案都在——
    但那是渲染服務的模組，Dockerfile 沒有 COPY 它，部署後直接 ModuleNotFoundError，
    而且失敗被吞掉，只有翻 Cloud Run 日誌才看得出來。

    這個測試讀 Dockerfile 的 COPY 清單，確保貢獻路徑不會再依賴映像外的東西。
    """

    def _copied_modules(self):
        text = Path(__file__).resolve().parents[1].joinpath("face/Dockerfile").read_text(encoding="utf-8")
        names = set()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("COPY ") and line.endswith(" ."):
                target = line[5:-2].strip()
                if target.endswith(".py"):
                    # 2026-08-23 起原始碼分在 face/ gateway/ render/ shared/ 等資料夾，
                    # 但 Dockerfile 是 `COPY face/x.py .`——**扁平**複製到容器的 /app。
                    # 所以容器裡的模組名是不含資料夾的檔名，比對要用 basename。
                    # 這也是 import 寫法不必跟著改的原因。
                    names.add(target.rsplit("/", 1)[-1][:-3])
        return names

    def test_face_contributions_imports_are_available_in_the_image(self):
        import ast

        source = Path(__file__).resolve().parents[1].joinpath("face/face_contributions.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])

        stdlib = {
            "base64", "binascii", "io", "json", "logging", "os", "datetime",
        }
        third_party = {"cv2": "opencv", "numpy": "numpy", "google": "google-cloud"}
        local = imported - stdlib - set(third_party)
        copied = self._copied_modules()
        missing = {m for m in local if m not in copied}
        self.assertEqual(missing, set(),
                         f"這些模組 face 映像裡沒有，部署後會 ModuleNotFoundError：{missing}")

    def test_google_cloud_subpackages_are_in_requirements(self):
        """`from google.cloud import X` 的 X 要真的裝在 face 映像裡。

        google.cloud 是命名空間套件——firestore 有裝不代表 storage 也有。
        第一版就是這樣：import google.cloud.storage 在本機成功（venv 裝了兩個），
        映像裡只有 firestore，於是 ImportError，而且一樣被吞掉。
        """
        import re

        source = Path(__file__).resolve().parents[1].joinpath("face/face_contributions.py").read_text(encoding="utf-8")
        used = set(re.findall(r"from google\.cloud import (\w+)", source))
        reqs = Path(__file__).resolve().parents[1].joinpath("face/requirements.txt").read_text(encoding="utf-8").lower()
        missing = {name for name in used if f"google-cloud-{name}" not in reqs}
        self.assertEqual(missing, set(),
                         f"requirements.txt 缺 google-cloud-{{{'、'.join(sorted(missing))}}}，"
                         f"face 映像會 ImportError")

    def test_data_url_parser_lives_here_not_in_the_render_service(self):
        """明確擋掉退回去 import replicate_render 的改法。"""
        source = Path(__file__).resolve().parents[1].joinpath("face/face_feedback.py").read_text(encoding="utf-8")
        self.assertNotIn("from replicate_render import", source,
                         "replicate_render 不在 face 映像裡，改用 face_contributions 那支")


if __name__ == "__main__":
    unittest.main()
