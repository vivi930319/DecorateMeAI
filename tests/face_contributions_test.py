"""使用者貢獻樣本的讀取與刪除。

這個模組動的是**真的臉部影像**，而且刪除不可逆。要守的是兩件事：

  1. 只碰到指定 job 的檔案。比對錯了就是刪掉別人的臉。
  2. 刪不掉的時候要讓呼叫端知道。覆核流程會據此決定要不要把 contributed
     標成 False——「說已經刪了、其實還在」是最糟的狀態，因為之後沒有人會再去查。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "face"))
sys.path.insert(0, str(ROOT / "shared"))

import face_contributions as fc


class _Blob:
    def __init__(self, name):
        self.name = name
        self.deleted = False

    def delete(self):
        self.deleted = True


class _Client:
    def __init__(self, names):
        self.blobs = [_Blob(n) for n in names]

    def list_blobs(self, bucket, prefix=""):
        return [b for b in self.blobs if b.name.startswith(prefix)]


# 真實的路徑長相：user_contributed/<ROI版本>/<部位>/<類別>/<job_id>.png
NAMES = [
    "user_contributed/v3/face_shape/圓形臉/JOB-1.png",
    "user_contributed/v3/eye_shape/鳳眼/JOB-1.png",
    "user_contributed/v3/lip_shape/薄唇/JOB-1.png",
    # 後綴相同但不是同一個 job——這是最危險的那一類
    "user_contributed/v3/face_shape/圓形臉/JOB-11.png",
    "user_contributed/v3/face_shape/方形臉/OTHER-JOB-1.png",
    "user_contributed/v3/nose_shape/寬鼻/JOB-2.png",
]


class DeleteForJobTest(unittest.TestCase):
    def _run(self, job_id, names=NAMES):
        client = _Client(names)
        with mock.patch.object(fc, "_client", return_value=client):
            removed = fc.delete_for_job(job_id)
        return removed, [b.name for b in client.blobs if b.deleted]

    def test_deletes_only_this_jobs_files(self):
        removed, deleted = self._run("JOB-1")
        self.assertEqual(removed, 3)
        self.assertEqual(sorted(deleted), sorted([
            "user_contributed/v3/eye_shape/鳳眼/JOB-1.png",
            "user_contributed/v3/face_shape/圓形臉/JOB-1.png",
            "user_contributed/v3/lip_shape/薄唇/JOB-1.png",
        ]))

    def test_a_longer_id_is_not_the_same_job(self):
        """JOB-11 不是 JOB-1。少了分隔線就會把它一起刪掉。"""
        _, deleted = self._run("JOB-1")
        self.assertNotIn("user_contributed/v3/face_shape/圓形臉/JOB-11.png", deleted)

    def test_a_suffix_match_is_not_the_same_job(self):
        """OTHER-JOB-1.png 的結尾是 JOB-1.png，但它是別人的影像。"""
        _, deleted = self._run("JOB-1")
        self.assertNotIn("user_contributed/v3/face_shape/方形臉/OTHER-JOB-1.png", deleted)

    def test_an_id_that_is_a_bare_digit_does_not_match_everything(self):
        """job_id='1' 是最極端的情況：沒有分隔線的話它會命中每一個 ...1.png。"""
        removed, deleted = self._run("1", [
            "user_contributed/v3/face_shape/圓形臉/1.png",
            "user_contributed/v3/eye_shape/鳳眼/21.png",
            "user_contributed/v3/lip_shape/薄唇/JOB-1.png",
        ])
        self.assertEqual(removed, 1)
        self.assertEqual(deleted, ["user_contributed/v3/face_shape/圓形臉/1.png"])

    def test_empty_id_deletes_nothing(self):
        """空字串接上分隔線會變成 '/.png'，但更該做的是提早退出。"""
        removed, deleted = self._run("")
        self.assertEqual((removed, deleted), (0, []))

    def test_nothing_to_delete_is_not_an_error(self):
        removed, deleted = self._run("JOB-NOPE")
        self.assertEqual((removed, deleted), (0, []))

    def test_a_failed_delete_is_raised_not_swallowed(self):
        """吞掉例外的話，覆核流程會把 contributed 標成 False——
        畫面說影像已刪除，GCS 上其實還在，而且沒有人會再去查。"""
        client = _Client(NAMES)
        for b in client.blobs:
            b.delete = mock.Mock(side_effect=RuntimeError("GCS 拒絕"))
        with mock.patch.object(fc, "_client", return_value=client):
            with self.assertRaises(RuntimeError):
                fc.delete_for_job("JOB-1")

    def test_no_credentials_deletes_nothing_quietly(self):
        """拿不到 client 時回 0，不是往下走然後 AttributeError。"""
        with mock.patch.object(fc, "_client", return_value=None):
            self.assertEqual(fc.delete_for_job("JOB-1"), 0)


class LoadForJobTest(unittest.TestCase):
    def test_load_uses_the_same_separator_rule_as_delete(self):
        """讀取與刪除必須用同一條比對規則。

        兩邊不一致的症狀很難查：後台顯示得出影像，按下排除卻刪不到那幾張
        （或反過來），而畫面上兩個動作看起來都成功了。
        """
        import inspect
        load_src = inspect.getsource(fc.load_for_job)
        delete_src = inspect.getsource(fc.delete_for_job)
        self.assertIn('f"/{job_id}.png"', load_src)
        self.assertIn('f"/{job_id}.png"', delete_src)


if __name__ == "__main__":
    unittest.main()
