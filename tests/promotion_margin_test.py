"""換上線的判定要看得出「這個差距是不是抽樣造成的」。

先前的規則是：任一部位的 macro 比線上低，整批擋下。問題是那個數字沒有誤差範圍。
保留集雖然固定（613 張、197 個身分），但每個部位只用得到有該標註的那些——實測是
76～169 張。在這個規模下單次量測的 95% 誤差就有 ±7～9 個百分點，兩次相比更大，
所以「批次比線上低 2.6」根本分不出是退步還是換一批資料的抖動。

2026-09-04 實際被擋掉的那一批就是這樣：臉型 +0.0、鼻型 -2.6、唇型 +0.0，
誤差各是 ±12.1／±10.1／±11.0——三個都在誤差內，卻整批被拒絕。

這一支守住三件事：誤差算得對、算不出誤差時保守擋下、以及換上線成功要把
「線上現在實際是什麼分數」寫回去（否則後台的比較基準會一直停在過期的歷史批次）。
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

from training_run_store import macro_std_error, read_model_metrics  # noqa: E402


def _load_promote_model():
    spec = importlib.util.spec_from_file_location("promote_model", ROOT / "tools" / "promote_model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metrics(macro, recalls, counts, val_count):
    """造一份 identity.best：confusion_matrix 只需要列和正確，對角線放不放不影響列和。"""
    matrix = [[n] for n in counts]
    return {
        "identity": {
            "val_count": val_count,
            "best": {
                "macro_accuracy": macro,
                "per_class_recall": recalls,
                "confusion_matrix": matrix,
                "val_count": val_count,
            },
        }
    }


class TestMacroStdError:
    def test_matches_the_formula(self):
        # 兩類、各 50 張、recall 0.9 與 0.8：
        # Var = (1/4)·[0.9·0.1/50 + 0.8·0.2/50]，SE = sqrt(Var)
        best = _metrics(0.85, [0.9, 0.8], [50, 50], 100)["identity"]["best"]
        expected = math.sqrt((0.9 * 0.1 / 50 + 0.8 * 0.2 / 50)) / 2
        assert macro_std_error(best) == pytest.approx(expected)

    def test_small_class_dominates(self):
        """類別小，誤差就大。這正是鼻型 n=76 卻有 ±6.8 的原因。"""
        big = macro_std_error(_metrics(0.85, [0.9, 0.8], [500, 500], 1000)["identity"]["best"])
        small = macro_std_error(_metrics(0.85, [0.9, 0.8], [20, 20], 40)["identity"]["best"])
        assert small > big * 3

    @pytest.mark.parametrize("best", [
        {},
        {"macro_accuracy": 0.9},                                   # 沒有 per_class_recall
        {"per_class_recall": [0.9, 0.8]},                          # 沒有 confusion_matrix
        {"per_class_recall": [0.9], "confusion_matrix": [[0]]},     # 該類別一張都沒有
        {"per_class_recall": [0.9, 0.8], "confusion_matrix": [[10]]},  # 長度對不上
    ])
    def test_returns_none_rather_than_zero(self, best):
        """算不出來要回 None。回 0 會被讀成「毫無誤差」，比不知道更糟。"""
        assert macro_std_error(best) is None


class TestDiffMargin:
    def test_margin_covers_the_batch_that_was_wrongly_blocked(self, tmp_path):
        pm = _load_promote_model()
        live = tmp_path / "live.json"
        new = tmp_path / "new.json"
        # 鼻型：2 類、線上 76 張、批次 72 張，實測 90.3% → 87.7%
        live.write_text(json.dumps(_metrics(0.903, [0.95, 0.86], [40, 36], 76)), encoding="utf-8")
        new.write_text(json.dumps(_metrics(0.877, [0.93, 0.82], [38, 34], 72)), encoding="utf-8")
        margin, n_live, n_new = pm._diff_margin(live, new)
        assert (n_live, n_new) == (76, 72)
        # 2.6 個百分點的差距必須落在誤差裡，否則這次改動沒有意義。
        assert margin > 2.6

    def test_no_margin_when_the_file_cannot_say(self, tmp_path):
        pm = _load_promote_model()
        live = tmp_path / "live.json"
        new = tmp_path / "new.json"
        live.write_text(json.dumps({"identity": {"best": {"macro_accuracy": 0.9}}}), encoding="utf-8")
        new.write_text(json.dumps({"identity": {"best": {"macro_accuracy": 0.8}}}), encoding="utf-8")
        margin, _, _ = pm._diff_margin(live, new)
        # 算不出誤差時要回 None，讓呼叫端退回「保守擋下」，而不是拿一個假的 0 放行。
        assert margin is None

    def test_missing_file_is_not_an_error(self, tmp_path):
        pm = _load_promote_model()
        margin, n_live, n_new = pm._diff_margin(tmp_path / "nope.json", tmp_path / "nope2.json")
        assert margin is None and n_live is None and n_new is None


class TestLiveMetricsPublishing:
    def test_read_model_metrics_carries_n_and_error(self, tmp_path):
        """後台要能說「誤差 ±X、n=Y」，這兩個欄位就是它的來源。"""
        (tmp_path / "nose_shape_classes.json").write_text(
            json.dumps({"architecture": "convnext_tiny", "classes": ["a", "b"]}), encoding="utf-8")
        (tmp_path / "nose_shape_metrics.json").write_text(
            json.dumps(_metrics(0.903, [0.95, 0.86], [40, 36], 76)), encoding="utf-8")
        part = read_model_metrics(tmp_path)["parts"]["nose_shape"]
        assert part["macroAccuracy"] == pytest.approx(0.903)
        assert part["valCount"] == 76
        assert part["macroStdErr"] is not None and part["macroStdErr"] > 0

    def test_publish_writes_the_current_document(self, tmp_path, monkeypatch):
        """換上線成功要更新比較基準，否則後台會一直拿過期的歷史批次去比。"""
        import training_run_store as store

        written = {}

        def fake_patch(project, collection, doc_id, payload):
            written.update({"project": project, "collection": collection,
                            "doc_id": doc_id, "payload": payload})

        monkeypatch.setattr(store, "patch_document", fake_patch)
        (tmp_path / "eye_shape_classes.json").write_text(
            json.dumps({"classes": ["a", "b"]}), encoding="utf-8")
        (tmp_path / "eye_shape_metrics.json").write_text(
            json.dumps(_metrics(0.688, [0.7, 0.68], [90, 79], 169)), encoding="utf-8")

        store.publish_live_model_metrics("decorate-me", tmp_path)

        assert written["collection"] == "face_model_metrics"
        assert written["doc_id"] == "current"
        assert written["payload"]["source"] == "promotion"
        assert written["payload"]["parts"]["eye_shape"]["valCount"] == 169

    def _publish(self, tmp_path, monkeypatch, **kwargs):
        import training_run_store as store

        written = {}
        monkeypatch.setattr(store, "patch_document",
                            lambda project, collection, doc_id, payload: written.update(payload))
        (tmp_path / "eye_shape_classes.json").write_text(
            json.dumps({"classes": ["a", "b"]}), encoding="utf-8")
        (tmp_path / "eye_shape_metrics.json").write_text(
            json.dumps(_metrics(0.688, [0.7, 0.68], [90, 79], 169)), encoding="utf-8")
        store.publish_live_model_metrics("decorate-me", tmp_path, **kwargs)
        return written

    def test_publish_records_where_the_numbers_came_from(self, tmp_path, monkeypatch):
        """光有分數證明不了它是線上的。

        原本只寫分數，後台於是有正確的數字卻講不出「這是哪一版換上去的」，只能在
        標題掛一句「不代表已上線」自保——而那句話會讓看的人以為數字不可信，實際上
        它就是線上的。少的不是資料，是出處。
        """
        written = self._publish(tmp_path, monkeypatch, version="20260909_brow",
                                promotion_id="PM-7c3eed1295cb2b81", run_id="TR-b673609456f9cb05")
        assert written["version"] == "20260909_brow"
        assert written["promotionId"] == "PM-7c3eed1295cb2b81"
        assert written["runId"] == "TR-b673609456f9cb05"

    def test_publish_never_blanks_an_existing_version(self, tmp_path, monkeypatch):
        """沒帶版本時要**不寫這個欄位**，不是寫成 None。

        patch_document 是合併寫入，塞 None 會把上一次的正確版本蓋掉。畫面於是從
        「不知道版本」變成「明確顯示沒有版本」——後者看起來像是查證過的結論。
        """
        written = self._publish(tmp_path, monkeypatch)
        assert "version" not in written
        assert "promotionId" not in written
        assert "runId" not in written
        assert written["source"] == "promotion"
