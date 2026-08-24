"""訓練眼型「精密幾何 + eye CNN 機率」的線性融合頭,匯出成可部署的 coef/intercept。

照鼻型 DINOv2 融合頭的部署慣例:存 coef/intercept + 特徵順序,不存 joblib
(避免 sklearn 版本綁定)。輸入契約 = [eye_features(9, 原始值), cnn_prob(n_classes)]。

輸出:models/basic_features_roi/eye_shape_fusion_head.npz
      keys: coef, intercept, geom_features, classes
驗證:重載 head 用「原始輸入」在 holdout 上算 macro F1,並與 sklearn 原預測比對一致。
"""
import _bootstrap  # noqa: F401  # 讓 face/ shared/ 的模組 import 得到
import json
import sys
from pathlib import Path

import numpy as np
import cv2
import mediapipe as mp
import onnxruntime as ort
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import f1_score, accuracy_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from face_roi import roi_to_tensor  # noqa: E402
from eye_features import eye_features_from_points, EYE_FUSION_FEATURES  # noqa: E402

CACHE = ROOT / "data" / "roi_cache_gcs"
MODELDIR = ROOT / "models" / "basic_features_roi"
OUT = MODELDIR / "eye_shape_fusion_head.npz"


def main():
    records = json.loads((CACHE / "index.json").read_text(encoding="utf-8"))["records"]
    rois = np.load(CACHE / "rois.npz", allow_pickle=True)
    split = json.loads((CACHE / "holdout_split_v1.json").read_text(encoding="utf-8"))
    name_split = {Path(s["relpath"]).name: s["split"] for s in split["samples"]}

    sess = ort.InferenceSession(str(MODELDIR / "eye_shape.onnx"), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name
    classes = json.loads((MODELDIR / "eye_shape_classes.json").read_text(encoding="utf-8"))
    classes = classes["classes"] if isinstance(classes, dict) else classes

    idx = [k for k, r in enumerate(records) if "eye_shape" in r["labels"]]
    print(f"眼型 {len(idx)} 張,抽精密幾何(refine)+ CNN 機率…", flush=True)
    fm = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1,
                                         refine_landmarks=True, min_detection_confidence=0.5)
    geo, cnnp, y, grp = [], [], [], []
    for c, k in enumerate(idx, 1):
        r = records[k]
        img = cv2.imdecode(np.fromfile(r["path"], np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        h0, w0 = img.shape[:2]
        res = fm.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        if not res.multi_face_landmarks:
            continue
        P = np.array([[lm.x * w0, lm.y * h0] for lm in res.multi_face_landmarks[0].landmark], np.float32)
        try:
            feats = eye_features_from_points(P)
        except Exception:
            continue
        logits = sess.run(None, {inp: roi_to_tensor(rois["eye_shape"][k])})[0][0]
        p = np.exp(logits - logits.max()); p = p / p.sum()
        geo.append([feats[n] for n in EYE_FUSION_FEATURES])
        cnnp.append(p)
        y.append(r["labels"]["eye_shape"])
        grp.append(name_split.get(Path(r["path"]).name, "unknown"))
        if c % 300 == 0:
            print(f"  {c}/{len(idx)}", flush=True)
    fm.close()

    geo = np.array(geo, np.float64); cnnp = np.array(cnnp, np.float64)
    y = np.array(y); grp = np.array(grp)
    tr, ho = grp == "train", grp == "holdout"
    print(f"成功 {len(geo)} 張(train {tr.sum()} / holdout {ho.sum()})\n")

    # 幾何標準化(只 fit train),CNN 機率保持原值(已是 0~1)
    scaler = StandardScaler().fit(geo[tr])
    Xtr = np.concatenate([scaler.transform(geo[tr]), cnnp[tr]], axis=1)
    clf = LogisticRegression(max_iter=5000, class_weight="balanced", C=1.0)
    clf.fit(Xtr, y[tr])

    # 把 scaler 摺進「幾何欄位」的權重,讓線上推論可餵原始幾何值(CNN 欄位不動)
    ng = geo.shape[1]
    coef = clf.coef_.copy().astype(np.float64)          # (n_classes, ng+n_cnn)
    intercept = clf.intercept_.copy().astype(np.float64)
    mean, scale = scaler.mean_, scaler.scale_
    intercept = intercept - (coef[:, :ng] * (mean / scale)).sum(axis=1)
    coef[:, :ng] = coef[:, :ng] / scale
    # sklearn 的 classes_ 順序才是 coef 的列順序
    head_classes = list(clf.classes_)

    # 驗證:用摺好的權重 + 原始輸入,結果要跟 sklearn 一致
    Xho_raw = np.concatenate([geo[ho], cnnp[ho]], axis=1)
    scores = Xho_raw @ coef.T + intercept
    pred_raw = np.array([head_classes[i] for i in scores.argmax(1)])
    pred_sk = clf.predict(np.concatenate([scaler.transform(geo[ho]), cnnp[ho]], axis=1))
    assert (pred_raw == pred_sk).all(), "摺權重後預測與 sklearn 不一致!"

    cnn_pred = np.array([classes[i] for i in cnnp.argmax(1)])
    f_cnn = f1_score(y[ho], cnn_pred[ho], average="macro")
    f_fus = f1_score(y[ho], pred_raw, average="macro")
    a_fus = accuracy_score(y[ho], pred_raw)

    np.savez(OUT, coef=coef.astype(np.float32), intercept=intercept.astype(np.float32),
             geom_features=np.array(EYE_FUSION_FEATURES), classes=np.array(head_classes),
             cnn_classes=np.array(classes))
    print("===== 線性融合頭(可部署)holdout =====")
    print(f"  純 CNN            macroF1={f_cnn:.3f}")
    print(f"  線性融合(幾何+CNN) macroF1={f_fus:.3f}  acc={a_fus:.3f}")
    print(f"  融合 vs 純 CNN    {f_fus-f_cnn:+.3f}  ({'贏' if f_fus>f_cnn else '沒贏'})")
    print(f"\n已存 {OUT.relative_to(ROOT)}  coef shape={coef.shape}  classes={head_classes}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
