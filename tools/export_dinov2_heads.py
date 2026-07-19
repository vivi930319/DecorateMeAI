"""把 DINOv2 的線性分類器權重抽出成 npz，讓服務端不必依賴 scikit-learn 版本。

joblib/pickle 會綁定 sklearn 版本：訓練用 1.9.0、部署映像是 1.7.2，載入時 sklearn 會發出
InconsistentVersionWarning，實測 LogisticRegression.predict_proba 直接拋
AttributeError: no attribute 'multi_class'，而且官方明言可能產生「invalid results」。

LinearSVC 與 LogisticRegression 都是線性模型，推論只是 X @ coef.T + intercept，
抽出權重後用 numpy 計算即可，順便免去 pickle 的安全性疑慮。
"""
import json
import pathlib

import joblib
import numpy as np

SRC = pathlib.Path("models/final_features_20260719")
DST = pathlib.Path("models/basic_features_roi")

HEADS = {
    "face_shape": ("face_shape_dinov2_linear_svc.joblib", "linear_svc"),
    "eye_shape": ("eye_shape_dinov2_logistic_regression.joblib", "logistic_regression"),
    "nose_shape": ("nose_shape_dinov2_linear_svc.joblib", "linear_svc"),
}


def main() -> None:
    emb = np.load("data/roi_cache/dinov2_embeddings.npz")["embeddings"][:400]

    for part, (filename, kind) in HEADS.items():
        clf = joblib.load(SRC / filename)
        coef = np.asarray(clf.coef_, dtype=np.float32)
        intercept = np.asarray(clf.intercept_, dtype=np.float32)

        out = DST / f"{part}_dinov2_head.npz"
        np.savez(out, coef=coef, intercept=intercept, kind=np.array(kind))

        # 驗證：numpy 的結果必須與 sklearn 完全一致，否則抽權重的方式有誤
        scores = emb @ coef.T + intercept
        mine = scores.argmax(1) if scores.shape[1] > 1 else (scores[:, 0] > 0).astype(int)
        ref = clf.predict(emb)
        agree = int((mine == ref).sum())
        status = "一致" if agree == len(ref) else f"不一致（{agree}/{len(ref)}）"
        print(f"{part:11s} {kind:20s} coef={coef.shape} -> {out.name}  {status}")


if __name__ == "__main__":
    main()
