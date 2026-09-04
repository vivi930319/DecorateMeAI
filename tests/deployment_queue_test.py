"""部署請求的佇列保護。

換模型那條路徑一路被補過（stale 回收、claim、狀態機），部署這條卻是後來才加上去
而且從來沒有測試。它有兩個獨立的壞法，而且會互相放大：

  1. stale 回收原本只掃換模型那個集合。一筆卡在 claimed 的部署沒有任何回收路徑，
     而 Gateway 又會擋掉「還有一筆沒做完」的新請求——後台那顆部署按鈕就永遠
     按不下去，沒有錯誤訊息，只有一句「已經有一筆部署還沒完成」。

  2. process_deployment 讀到 queued 就直接寫 claimed，不看它現在是不是還在 queued。
     兩個 worker 會同時去跑 deploy_*.ps1，互相覆蓋 Cloud Run revision。

這一支就守這兩件事。
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))


def _load_worker():
    spec = importlib.util.spec_from_file_location(
        "promotion_worker", ROOT / "tools" / "promotion_worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pw = _load_worker()


class _Firestore:
    """把 worker 用到的那三支 Firestore helper 換成記憶體版。"""

    def __init__(self, docs=None):
        # {(collection, doc_id): dict}
        self.docs = dict(docs or {})
        self.patches = []

    def rows(self, collection, status):
        return [dict(doc) for (col, _id), doc in self.docs.items()
                if col == collection and doc.get("status") == status]

    def install(self, module):
        def run_query(project, body):
            query = body["structuredQuery"]
            collection = query["from"][0]["collectionId"]
            status = query["where"]["fieldFilter"]["value"]["stringValue"]
            return self.rows(collection, status)

        def patch_document(project, collection, doc_id, updates):
            self.patches.append((collection, doc_id, dict(updates)))
            self.docs.setdefault((collection, doc_id), {}).update(updates)

        def get_document(project, collection, doc_id):
            doc = self.docs.get((collection, doc_id))
            return dict(doc) if doc is not None else None

        module._run_query = run_query
        module.patch_document = patch_document
        module.get_document = get_document


_OLD = "2020-01-01T00:00:00+00:00"      # 遠早於 STALE_MINUTES


def _recent():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class RequeueStaleTest(unittest.TestCase):
    def setUp(self):
        self._saved = (pw._run_query, pw.patch_document, pw.get_document)

    def tearDown(self):
        pw._run_query, pw.patch_document, pw.get_document = self._saved

    def test_a_stuck_deployment_is_requeued(self):
        """卡住的部署要被排回佇列。

        這是這支測試存在的主要理由：不回收它，後台的部署按鈕就永遠是壞的。
        """
        store = _Firestore({
            (pw.DEPLOYMENTS_COLLECTION, "DP-1"): {
                "deploymentId": "DP-1", "status": "claimed",
                "claimedAt": _OLD, "stage": "gateway"},
        })
        store.install(pw)

        self.assertEqual(pw.requeue_stale("proj"), 1)

        doc = store.docs[(pw.DEPLOYMENTS_COLLECTION, "DP-1")]
        self.assertEqual(doc["status"], "queued")
        # stage 沒清掉的話，後台會顯示一筆 queued 卻同時說它正在部署 gateway。
        self.assertIsNone(doc["stage"])
        self.assertIsNone(doc["error"])

    def test_a_deployment_that_only_just_started_is_left_alone(self):
        """還在合理時間內的不要碰——它可能真的正在 build。"""
        store = _Firestore({
            (pw.DEPLOYMENTS_COLLECTION, "DP-2"): {
                "deploymentId": "DP-2", "status": "running", "claimedAt": _recent()},
        })
        store.install(pw)

        self.assertEqual(pw.requeue_stale("proj"), 0)
        self.assertEqual(store.docs[(pw.DEPLOYMENTS_COLLECTION, "DP-2")]["status"], "running")

    def test_both_collections_are_swept(self):
        """換模型與部署要一起回收，不能只救其中一種。"""
        store = _Firestore({
            (pw.PROMOTIONS_COLLECTION, "PM-1"): {
                "promotionId": "PM-1", "status": "running", "claimedAt": _OLD},
            (pw.DEPLOYMENTS_COLLECTION, "DP-1"): {
                "deploymentId": "DP-1", "status": "claimed", "claimedAt": _OLD},
        })
        store.install(pw)

        self.assertEqual(pw.requeue_stale("proj"), 2)
        self.assertEqual(store.docs[(pw.PROMOTIONS_COLLECTION, "PM-1")]["status"], "queued")
        self.assertEqual(store.docs[(pw.DEPLOYMENTS_COLLECTION, "DP-1")]["status"], "queued")


class LedgerMustProveTheWorkHappenedTest(unittest.TestCase):
    """子程序結束碼 0 不等於模型換好了。

    原本是 `entry = _last_ledger_entry(run_id) or {}`——對不上就當成空 dict，
    然後 version、backup、results 全填 None，status 照樣寫 deployed。後台會顯示
    一筆「已上線、版本空白」的紀錄，而沒有人能從那筆看出換了什麼、要怎麼還原。
    """

    def test_a_missing_ledger_is_a_problem(self):
        problem = pw._ledger_problem(None, "TR-abc")
        self.assertTrue(problem)
        self.assertIn("TR-abc", problem)

    def test_an_incomplete_ledger_names_what_is_missing(self):
        problem = pw._ledger_problem(
            {"runId": "TR-abc", "version": "20260904_eye_lip"}, "TR-abc")
        self.assertTrue(problem)
        self.assertIn("backup", problem)
        self.assertIn("parts", problem)

    def test_an_empty_version_is_not_acceptable(self):
        """version 是空字串時最危險：dict 有那個 key，粗看像完整的。"""
        self.assertTrue(pw._ledger_problem(
            {"runId": "TR-abc", "version": "", "backup": "b", "parts": [{"part": "眼型"}]},
            "TR-abc"))

    def test_a_complete_ledger_passes(self):
        self.assertEqual(pw._ledger_problem(
            {"runId": "TR-abc", "version": "20260904_eye_lip", "backup": "models/x",
             "parts": [{"part": "眼型", "liveMacro": 0.68, "newMacro": 0.74}]},
            "TR-abc"), "")


class StaleSweepRunsRepeatedlyTest(unittest.TestCase):
    """回收要每一輪都掃，不能只在啟動時掃一次。

    只在啟動掃的話幾乎保證掃不到：worker 死掉之後看門狗大約五分鐘就把它拉回來，
    那時卡住那筆的 claimedAt 還很新、不到 STALE_MINUTES，於是被跳過；之後 worker
    一直活著，再也不掃第二次。那筆就永遠停在 running，後台的部署按鈕永遠回
    DEPLOY_ALREADY_QUEUED——正是這個函式當初要消滅的症狀。
    """

    def test_the_sweep_is_inside_the_polling_loop(self):
        """驗的是呼叫點的位置，因為錯的就是位置本身。"""
        source = (ROOT / "tools" / "promotion_worker.py").read_text(encoding="utf-8")
        body = source.split("def main()")[1]
        loop_at = body.index("while True:")
        sweeps = [i for i in range(len(body)) if body.startswith("requeue_stale(", i)]
        self.assertTrue(sweeps, "找不到 requeue_stale 的呼叫")
        self.assertTrue(any(i > loop_at for i in sweeps),
                        "requeue_stale 只在進迴圈前呼叫，之後永遠不會再掃")

    def test_the_sweep_interval_is_far_longer_than_the_poll_interval(self):
        """每輪都掃會讓每 20 秒多兩次 Firestore 查詢，而卡住的工作要等 30 分鐘才算數。"""
        self.assertGreaterEqual(pw.STALE_SWEEP_SECONDS, 60)
        self.assertLess(pw.STALE_SWEEP_SECONDS, pw.STALE_MINUTES * 60)


class ClaimDeploymentTest(unittest.TestCase):
    def setUp(self):
        self._saved = (pw._run_query, pw.patch_document, pw.get_document, pw.subprocess)

    def tearDown(self):
        pw._run_query, pw.patch_document, pw.get_document, pw.subprocess = self._saved

    def _no_scripts_run(self):
        class _Blocked:
            @staticmethod
            def run(*a, **k):
                raise AssertionError("不該執行任何部署腳本")
        pw.subprocess = _Blocked

    def test_a_deployment_already_taken_is_not_run_again(self):
        """別的 worker 已經收走了就不要再跑一次。

        沒有這道檢查，兩個 worker 會同時 build 並部署同一組服務，
        互相覆蓋 Cloud Run revision，而且沒有人分得出線上是哪一次的產物。
        """
        store = _Firestore({
            (pw.DEPLOYMENTS_COLLECTION, "DP-9"): {
                "deploymentId": "DP-9", "services": ["gateway"], "status": "claimed"},
        })
        store.install(pw)
        self._no_scripts_run()

        # 這一份是 worker 從查詢拿到的舊快照，上面還寫著 queued——
        # 真實情境正是如此：查到的時候還在排隊，輪到它時已經被收走了。
        stale_row = {"deploymentId": "DP-9", "services": ["gateway"], "status": "queued"}
        self.assertFalse(pw.process_deployment(stale_row, "proj", False, "worker-b"))

        # 狀態不能被改動——尤其不能被覆寫成這個 worker 的 claim。
        self.assertEqual(store.docs[(pw.DEPLOYMENTS_COLLECTION, "DP-9")]["status"], "claimed")

    def test_claiming_records_which_worker_took_it(self):
        """收下來時要留下是誰收的，否則兩台機器打架時查不出來。"""
        store = _Firestore({
            (pw.DEPLOYMENTS_COLLECTION, "DP-10"): {
                "deploymentId": "DP-10", "services": ["gateway"], "status": "queued"},
        })
        store.install(pw)

        row = pw._claim_in("proj", pw.DEPLOYMENTS_COLLECTION, "DP-10", "worker-a")

        self.assertIsNotNone(row)
        doc = store.docs[(pw.DEPLOYMENTS_COLLECTION, "DP-10")]
        self.assertEqual(doc["status"], "claimed")
        self.assertEqual(doc["workerId"], "worker-a")

        # 收第二次要落空。
        self.assertIsNone(pw._claim_in("proj", pw.DEPLOYMENTS_COLLECTION, "DP-10", "worker-b"))


if __name__ == "__main__":
    unittest.main()
