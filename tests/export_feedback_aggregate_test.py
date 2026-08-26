"""去識別化彙總的產出邏輯。

這支腳本產的檔案**會離開這棟樓**——交給演算法端，之後可能被轉寄、被存進別的地方。
所以要守的不只是「數字算對」，更是「該沒有的東西真的沒有」：
身分、影像、job id、逐筆時間戳。

其中逐筆時間戳最容易被當成無害：一個罕見的類別配對加上一個確切日期，
配合其他資訊就有機會指回某一個人的某一次使用。所以日期只給整份的頭尾。
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import export_feedback_aggregate as ex


def ev(job_id, predicted, agreed, corrected, created="2026-08-10T03:00:00Z", version=None):
    """組一份 Firestore REST 格式的評估事件。"""
    fields = {
        "jobId": {"stringValue": job_id},
        "createdAt": {"timestampValue": created},
        "predicted": {"mapValue": {"fields": {k: {"stringValue": v}
                                              for k, v in predicted.items()}}},
        "agreed": {"arrayValue": {"values": [{"stringValue": x} for x in agreed]}},
        "corrected": {"arrayValue": {"values": [{"stringValue": x} for x in corrected]}},
    }
    if version:
        fields["modelVersion"] = {"stringValue": version}
    return {"name": "projects/x/databases/(default)/documents/face_eval_events/" + job_id,
            "fields": fields}


def fb(job_id, corrections):
    return {job_id: {"fields": {
        "corrections": {"mapValue": {"fields": {k: {"stringValue": v}
                                                for k, v in corrections.items()}}}}}}


FIVE = {"臉型": "圓形臉", "眉型": "一字眉", "眼型": "鳳眼", "鼻型": "寬鼻", "嘴型": "薄唇"}


class SuppressionTest(unittest.TestCase):
    def test_rare_combinations_are_merged_not_listed(self):
        """只出現一兩次的組合最容易被認出來，對看分布也沒有統計意義。"""
        events = [ev("JOB-%d" % i, FIVE, list(FIVE), []) for i in range(5)]
        events.append(ev("JOB-rare", {"臉型": "心形臉"}, ["臉型"], []))
        payload = ex.build_payload(events, {}, min_count=3)
        notes = [r.get("note", "") for r in payload["rows"]]
        self.assertTrue(any("其他" in x for x in notes), "罕見組合應該被併成一列")
        self.assertNotIn("心形臉", [r["predicted"] for r in payload["rows"]])

    def test_min_count_one_lists_everything(self):
        events = [ev("JOB-1", {"臉型": "心形臉"}, ["臉型"], [])]
        payload = ex.build_payload(events, {}, min_count=1)
        self.assertIn("心形臉", [r["predicted"] for r in payload["rows"]])
        self.assertEqual(payload["suppressedCells"], 0)

    def test_suppressed_rows_still_count_towards_the_total(self):
        """被抑制的筆數要留在總數裡，否則總和對不上，讀的人會以為資料少了。"""
        events = [ev("JOB-%d" % i, FIVE, list(FIVE), []) for i in range(4)]
        events.append(ev("JOB-rare", {"臉型": "心形臉"}, ["臉型"], []))
        payload = ex.build_payload(events, {}, min_count=3)
        self.assertEqual(sum(r["count"] for r in payload["rows"]),
                         payload["partRecordCount"])


class DeIdentificationTest(unittest.TestCase):
    def _payload(self):
        events = [ev("JOB-%d" % i, FIVE, list(FIVE), [],
                     created="2026-08-%02dT03:00:00Z" % (10 + i)) for i in range(4)]
        return ex.build_payload(events, {}, min_count=1)

    def test_only_the_overall_date_range_is_kept(self):
        self.assertEqual(self._payload()["dateRange"],
                         {"from": "2026-08-10", "to": "2026-08-13"})

    def test_no_per_record_timestamps_anywhere(self):
        """逐筆日期配上罕見組合，就有機會回推到某一個人的某一次使用。"""
        text = json.dumps(self._payload(), ensure_ascii=False)
        self.assertNotIn("T03:00:00", text)
        self.assertEqual(text.count("2026-08-11"), 0, "中間的日期不該出現")

    def test_no_job_ids(self):
        self.assertNotIn("JOB-", json.dumps(self._payload(), ensure_ascii=False))

    def test_the_leak_scan_actually_catches_a_leak(self):
        """這條比「乾淨的資料掃過是乾淨的」重要得多。

        只驗證乾淨資料通過，等於沒有驗證掃描器——它永遠回傳空 list 也會過。
        所以刻意種一個進去，確認它抓得到。
        """
        payload = self._payload()
        self.assertEqual(ex.find_leaks(payload), [])
        payload["rows"][0]["ownerId"] = "u-12345"
        self.assertIn("ownerId", ex.find_leaks(payload))

    def test_the_leak_scan_catches_an_embedded_image(self):
        payload = self._payload()
        payload["rows"][0]["sample"] = "data:image/png;base64,iVBORw0KGgo"
        self.assertIn("base64", ex.find_leaks(payload))


class ConsistencyTest(unittest.TestCase):
    def test_five_parts_per_event_adds_up(self):
        events = [ev("JOB-%d" % i, FIVE, list(FIVE), []) for i in range(10)]
        p = ex.build_payload(events, {}, min_count=1)
        self.assertEqual((p["eventCount"], p["partRecordCount"]), (10, 50))
        self.assertTrue(all(p["consistencyChecks"].values()))

    def test_a_sixth_part_is_named_not_hidden(self):
        """演算法端驗收時發現 649 對不上 645，靠彙總本身查不出差在哪。
        多出來的那幾筆要有名有姓，才不用回頭問來源端。"""
        six = dict(FIVE)
        six["側臉鼻型"] = "標準"
        events = [ev("JOB-1", six, list(six), [])]
        events += [ev("JOB-%d" % i, FIVE, list(FIVE), []) for i in range(2, 5)]
        p = ex.build_payload(events, {}, min_count=1)
        self.assertIn("側臉鼻型", p["extraParts"])
        self.assertEqual(p["extraParts"]["側臉鼻型"]["total"], 1)
        self.assertEqual(p["partRecordCount"], 4 * 5 + 1)
        self.assertTrue(p["consistencyChecks"]["basicPartsEqualEventsTimesFive"])
        self.assertTrue(p["consistencyChecks"]["partRecordCountEqualsBasicPlusExtra"])

    def test_corrected_values_come_from_the_feedback_doc(self):
        events = [ev("JOB-1", {"眉型": "一字眉"}, [], ["眉型"])]
        p = ex.build_payload(events, fb("JOB-1", {"眉型": "彎月眉"}), min_count=1)
        row = next(r for r in p["rows"] if r["part"] == "眉型")
        self.assertEqual((row["predicted"], row["corrected"], row["agreed"]),
                         ("一字眉", "彎月眉", False))

    def test_a_missing_feedback_doc_leaves_the_value_null_not_guessed(self):
        """對不到就少一個欄位，不要猜——猜出來的標籤會被當成使用者說的。"""
        events = [ev("JOB-1", {"眉型": "一字眉"}, [], ["眉型"])]
        p = ex.build_payload(events, {}, min_count=1)
        self.assertIsNone(next(r for r in p["rows"] if r["part"] == "眉型")["corrected"])

    def test_a_part_neither_agreed_nor_corrected_is_not_counted(self):
        """沒有被判過的部位不算進分母，否則同意率會被稀釋。"""
        events = [ev("JOB-1", FIVE, ["臉型"], ["眉型"])]
        p = ex.build_payload(events, fb("JOB-1", {"眉型": "彎月眉"}), min_count=1)
        self.assertEqual(p["partRecordCount"], 2)

    def test_versions_are_counted_separately(self):
        events = [ev("JOB-1", {"臉型": "圓形臉"}, ["臉型"], [], version="v2"),
                  ev("JOB-2", {"臉型": "圓形臉"}, ["臉型"], [])]
        p = ex.build_payload(events, {}, min_count=1)
        self.assertEqual(dict(p["modelVersions"]), {"v2": 1, "unknown": 1})

    def test_no_events_does_not_crash(self):
        p = ex.build_payload([], {}, min_count=3)
        self.assertIsNone(p["dateRange"])
        self.assertEqual((p["rows"], p["eventCount"]), ([], 0))


class UsageBoundaryTest(unittest.TestCase):
    def test_the_file_carries_its_own_limits(self):
        """檔案會傳得比對話遠。用途界線寫在裡面，才不會脫離脈絡被當成別的東西用。"""
        p = ex.build_payload([], {}, min_count=3)
        self.assertIn("ColorScore", " ".join(p["usage"]["notOk"]))
        self.assertIn("推薦金標", " ".join(p["usage"]["notOk"]))
        self.assertIn("不是隨機抽樣", p["usage"]["bias"])
        self.assertEqual(p["excluded"], ["身分", "影像", "job id", "逐筆時間戳"])


class MainSmokeTest(unittest.TestCase):
    """main() 也要跑到。

    2026-08-26 把運算抽成 build_payload 之後，main 仍然對 payload["modelVersions"]
    呼叫 .most_common()——但那已經是普通 dict 了，一跑就 AttributeError。
    上面那些測試全都是綠的，因為它們測的是被抽出來的函式，不是呼叫它的地方。
    抽出函式之後，最容易壞的正好是留在原地的那一半。
    """

    def test_main_writes_a_file_and_prints_without_blowing_up(self):
        import tempfile
        from unittest import mock

        events = [ev("JOB-%d" % i, FIVE, list(FIVE), [], version="v2") for i in range(4)]
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "agg.json")
            argv = ["export_feedback_aggregate.py", "--out", out, "--min-count", "1"]
            with mock.patch.object(ex.sys, "argv", argv),                  mock.patch.object(ex, "_gcloud", return_value="fake-token"),                  mock.patch.object(ex, "_fetch",
                                   side_effect=lambda proj, tok, col: events if col == ex.EVAL_COL else []):
                code = ex.main()
            self.assertEqual(code, 0, "夾帶檢查應該通過，離開碼要是 0")
            written = json.loads(Path(out).read_text(encoding="utf-8"))
        self.assertEqual(written["eventCount"], 4)
        self.assertEqual(written["modelVersions"], {"v2": 4})

    def test_main_exits_non_zero_when_something_leaked(self):
        """夾帶檢查抓到東西時不能安靜地寫出檔案就結束——
        離開碼要是非 0，這樣包在腳本裡跑的人才會知道。"""
        import tempfile
        from unittest import mock

        events = [ev("JOB-1", {"臉型": "圓形臉"}, ["臉型"], [])]
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "agg.json")
            argv = ["export_feedback_aggregate.py", "--out", out]
            with mock.patch.object(ex.sys, "argv", argv),                  mock.patch.object(ex, "_gcloud", return_value="fake-token"),                  mock.patch.object(ex, "_fetch",
                                   side_effect=lambda proj, tok, col: events if col == ex.EVAL_COL else []),                  mock.patch.object(ex, "find_leaks", return_value=["ownerId"]):
                self.assertEqual(ex.main(), 1)


if __name__ == "__main__":
    unittest.main()
