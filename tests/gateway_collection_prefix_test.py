"""staging 的 Gateway 用 GATEWAY_COLLECTION_PREFIX 把後台下單的集合跟正式環境分開。

守住兩件事：
1. 沒設前綴時集合名跟以前一模一樣——正式環境不能因為這個變數而改讀別的集合。
2. 設了前綴時，訓練、換上線、部署這幾個集合加上前綴，但 face_feedback 與
   render_jobs 不加：它們由正式的臉部分析與渲染服務寫入，加了就讀不到。

用子行程載入，避免在同一個行程裡 reload ai_gateway 汙染其他測試的模組狀態。
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_PROBE = (
    "import json, ai_gateway as g;"
    "print(json.dumps([g.FACE_FEEDBACK_COL, g.FACE_TRAINING_RUNS_COL,"
    " g.FACE_TRAINING_WORKERS_COL, g.FACE_MODEL_PROMOTIONS_COL,"
    " g.FACE_DEPLOYMENTS_COL, g.FACE_MODEL_METRICS_COL, g.RENDER_JOBS_COL]))"
)


def _collections(prefix):
    env = dict(os.environ)
    env["GATEWAY_SESSION_SECRET"] = "test-session-secret-that-is-at-least-32-bytes"
    env["GATEWAY_FACE_API_KEY"] = "face-client-key"
    env["GATEWAY_RENDER_API_KEY"] = "render-client-key"
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "gateway"), str(ROOT / "shared")])
    env.pop("GATEWAY_COLLECTION_PREFIX", None)
    if prefix is not None:
        env["GATEWAY_COLLECTION_PREFIX"] = prefix
    out = subprocess.run([sys.executable, "-c", _PROBE], env=env, cwd=ROOT,
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


class CollectionPrefixTest(unittest.TestCase):
    def test_no_prefix_keeps_production_names(self):
        self.assertEqual(_collections(None), [
            "face_feedback", "face_training_runs", "face_training_workers",
            "face_model_promotions", "face_service_deployments", "face_model_metrics",
            "render_jobs",
        ])

    def test_staging_prefix_isolates_admin_orders_only(self):
        self.assertEqual(_collections("staging_"), [
            "face_feedback", "staging_face_training_runs", "staging_face_training_workers",
            "staging_face_model_promotions", "staging_face_service_deployments",
            "staging_face_model_metrics", "render_jobs",
        ])


if __name__ == "__main__":
    unittest.main()
