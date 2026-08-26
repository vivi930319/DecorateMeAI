"""修正快取：同一張臉再上傳時，套用使用者上次的更正。

這裡有兩個地方壞掉是沉默的，而且後果會一路流下去：

  1. 舊標籤沒有正規化。分類表合併過（M型唇→花瓣唇、杏仁眼／桃花眼→桃杏眼），
     使用者當初送出的是舊名稱。不換的話，一個**已經不存在的類別**會被寫進結果，
     再流到建議 prompt 與渲染 prompt——那些對照表只認得現行類別，
     查不到就整句略過，不報錯。症狀是「某些人的建議少了一段」，沒有人會聯想到這裡。

  2. 修正被收回時留下空紀錄。下次讀到會以為「這張臉被確認過是對的」，
     但使用者其實只是把答案改了回去。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "face"))
sys.path.insert(0, str(ROOT / "shared"))

import face_corrections as fx


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.result = {"臉型": "圓形臉", "眉型": "一字眉", "眼型": "鳳眼",
                       "鼻型": "寬鼻", "嘴型": "薄唇", "膚色": "春"}

    def _apply(self, doc):
        with mock.patch.object(fx.job_store, "get", return_value=doc), \
             mock.patch.object(fx, "ENABLED", True):
            return fx.apply(dict(self.result), "hash123", owner_id="u1")

    def test_raw_output_is_always_kept(self):
        """回饋面板要有一份可信的 predicted，不必去分辨這次有沒有被快取動過。"""
        out = self._apply(None)
        self.assertEqual(out[fx.RAW_KEY]["眼型"], "鳳眼")

    def test_a_correction_replaces_the_model_answer(self):
        out = self._apply({"corrections": {"眼型": "桃杏眼"}})
        self.assertEqual(out["眼型"], "桃杏眼")
        # 原始輸出仍然留著，不是被覆蓋掉
        self.assertEqual(out[fx.RAW_KEY]["眼型"], "鳳眼")

    def test_an_obsolete_label_is_normalised_not_stored_as_is(self):
        """這是最重要的一條：舊類別寫進結果就會一路流到 prompt 而且不報錯。"""
        out = self._apply({"corrections": {"眼型": "杏仁眼"}})
        self.assertEqual(out["眼型"], fx.canonical_label("杏仁眼"))
        self.assertNotEqual(out["眼型"], "杏仁眼",
                            "舊名稱應該被換成現行分類表的名稱")

    def test_an_unknown_field_is_ignored(self):
        """快取裡混進不是五官的欄位時，不要讓它污染結果。"""
        out = self._apply({"corrections": {"身高": "170"}})
        self.assertNotIn("身高", out)

    def test_an_empty_value_does_not_erase_the_model_answer(self):
        out = self._apply({"corrections": {"眼型": ""}})
        self.assertEqual(out["眼型"], "鳳眼")

    def test_a_read_failure_falls_back_to_the_model_output(self):
        """快取讀不到不該讓整次分析失敗——模型本來就答得出來。"""
        with mock.patch.object(fx.job_store, "get", side_effect=RuntimeError("Firestore 掛了")), \
             mock.patch.object(fx, "ENABLED", True):
            out = fx.apply(dict(self.result), "hash123", owner_id="u1")
        self.assertEqual(out["眼型"], "鳳眼")
        self.assertIn(fx.RAW_KEY, out)

    def test_disabled_cache_still_records_the_raw_output(self):
        with mock.patch.object(fx, "ENABLED", False):
            out = fx.apply(dict(self.result), "hash123", owner_id="u1")
        self.assertIn(fx.RAW_KEY, out)

    def test_a_non_dict_result_is_returned_untouched(self):
        self.assertEqual(fx.apply("不是 dict", "h"), "不是 dict")


class RememberTest(unittest.TestCase):
    def test_a_withdrawn_correction_deletes_the_record(self):
        """留著一筆空的修正，下次讀到會以為「這張臉被確認過是對的」。"""
        with mock.patch.object(fx, "ENABLED", True), \
             mock.patch.object(fx.job_store, "delete") as deleted, \
             mock.patch.object(fx.job_store, "create") as created:
            fx.remember("hash123", {}, owner_id="u1")
        deleted.assert_called_once()
        created.assert_not_called()

    def test_only_empty_values_also_counts_as_withdrawn(self):
        with mock.patch.object(fx, "ENABLED", True), \
             mock.patch.object(fx.job_store, "delete") as deleted, \
             mock.patch.object(fx.job_store, "create") as created:
            fx.remember("hash123", {"眼型": "", "嘴型": None}, owner_id="u1")
        deleted.assert_called_once()
        created.assert_not_called()

    def test_non_feature_fields_are_not_stored(self):
        stored = {}
        with mock.patch.object(fx, "ENABLED", True), \
             mock.patch.object(fx.job_store, "create",
                               side_effect=lambda col, key, doc: stored.update(doc)):
            fx.remember("hash123", {"眼型": "桃杏眼", "身高": "170"}, owner_id="u1")
        self.assertEqual(stored["corrections"], {"眼型": "桃杏眼"})

    def test_a_write_failure_does_not_raise(self):
        """快取寫不進去不該讓回饋整支失敗——face_feedback 那一筆才是要留的訓練資料。"""
        with mock.patch.object(fx, "ENABLED", True), \
             mock.patch.object(fx.job_store, "create", side_effect=RuntimeError("寫不進去")):
            fx.remember("hash123", {"眼型": "桃杏眼"}, owner_id="u1")   # 不應拋出


class ImageHashTest(unittest.TestCase):
    def test_the_same_bytes_give_the_same_hash(self):
        self.assertEqual(fx.image_hash(b"abc"), fx.image_hash(b"abc"))

    def test_different_bytes_give_different_hashes(self):
        self.assertNotEqual(fx.image_hash(b"abc"), fx.image_hash(b"abd"))

    def test_the_cache_key_separates_owners(self):
        """兩個人上傳同一張圖，不該共用彼此的修正。"""
        a = fx._cache_key("samehash", "user-a")
        b = fx._cache_key("samehash", "user-b")
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
