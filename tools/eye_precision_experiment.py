"""眼型精密特徵實驗:現有 3 特徵 vs 加入虹膜/上瞼曲率/頂點的加強特徵,並試與 CNN 融合。

回答:把眼型幾何做得更精密(refine_landmarks 虹膜 + lid_curve + 頂點位置),
macro F1 會不會比現在的純 CNN(holdout 0.737)或純幾何(0.51)好?

- 特徵全是比值/角度(尺度不變)。
- 訓練用 train split、評估用 holdout(與線上量測同一份切分),不洩漏。
- 錨點:CNN-alone 應重現 ~0.737、現有 3 特徵應重現 ~0.51,兩者對得上才代表新數字可信。
"""
import _bootstrap  # noqa: F401  # 讓 face/ shared/ 的模組 import 得到
import json
import sys
from pathlib import Path

import numpy as np
import cv2
import mediapipe as mp
import onnxruntime as ort
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, accuracy_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from face_roi import roi_to_tensor  # noqa: E402

CACHE = ROOT / "data" / "roi_cache_gcs"
MODELDIR = ROOT / "models" / "basic_features_roi"

# 沿用 Face_analyzer 的眼周索引 + 加虹膜(refine 才有):468 左中心/469-472 環,473 右中心/474-477 環
EYES = [
    dict(inner=133, outer=33, upper=(157, 158, 159, 160, 161), lower=(145, 144, 153, 163),
         iris_c=468, iris_r=(469, 470, 471, 472)),
    dict(inner=362, outer=263, upper=(385, 386, 387, 388, 398), lower=(374, 380, 381, 382),
         iris_c=473, iris_r=(474, 475, 476, 477)),
]


def align(pts):
    """用兩眼中心連線旋正,讓角度/縱向量測不受頭歪影響。"""
    lc = pts[[33, 133, 145, 159]].mean(0)
    rc = pts[[263, 362, 374, 386]].mean(0)
    ang = np.arctan2(rc[1] - lc[1], rc[0] - lc[0])
    c, s = np.cos(-ang), np.sin(-ang)
    R = np.array([[c, -s], [s, c]], np.float32)
    return (pts - pts.mean(0)) @ R.T


def eye_feats(P):
    face_w = np.linalg.norm(P[234] - P[454]) or 1.0
    out = []
    for e in EYES:
        inner, outer = P[e["inner"]], P[e["outer"]]
        up = P[list(e["upper"])]; lo = P[list(e["lower"])]
        ic = P[e["iris_c"]]; ir = P[list(e["iris_r"])]
        w = np.linalg.norm(outer - inner) or 1.0
        up_mid = up.mean(0); lo_mid = lo.mean(0)
        h = abs(up_mid[1] - lo_mid[1])
        ear = h / w
        angle = np.degrees(np.arctan2(inner[1] - outer[1], abs(inner[0] - outer[0]) + 1e-6))
        upper_curve = (up[:, 1].max() - up[:, 1].min()) / (h + 1e-6)
        lower_curve = (lo[:, 1].max() - lo[:, 1].min()) / (h + 1e-6)
        iris_d = 2 * np.mean(np.linalg.norm(ir - ic, axis=1)) or 1.0
        openness = h / iris_d                                    # 圓眼高、鳳眼/下垂低
        upper_cover = (ic[1] - up_mid[1]) / iris_d               # 上瞼離虹膜中心(開合)
        lower_show = (lo_mid[1] - ic[1]) / iris_d                # 下方鞏膜露出
        apex_x = (up[np.argmin(up[:, 1])][0] - inner[0]) / ((outer[0] - inner[0]) or 1.0)
        out.append([ear, w / face_w, angle, upper_curve, lower_curve,
                    openness, upper_cover, lower_show, abs(apex_x)])
    return np.mean(out, axis=0)


FEAT_NAMES = ["ear", "ratio_to_face", "canthal_tilt", "upper_curve", "lower_curve",
              "iris_openness", "upper_cover", "lower_show", "apex_x"]
BASE3 = [0, 1, 2]  # 對應現行的 ear / ratio_to_face / angle


def main():
    records = json.loads((CACHE / "index.json").read_text(encoding="utf-8"))["records"]
    rois = np.load(CACHE / "rois.npz", allow_pickle=True)
    split = json.loads((CACHE / "holdout_split_v1.json").read_text(encoding="utf-8"))
    name_split = {Path(s["relpath"]).name: s["split"] for s in split["samples"]}

    idx = [k for k, r in enumerate(records) if "eye_shape" in r["labels"]]
    print(f"眼型樣本 {len(idx)} 張,抽虹膜精密特徵(refine_landmarks)…", flush=True)

    fm = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1,
                                         refine_landmarks=True, min_detection_confidence=0.5)
    X, y, grp, keep = [], [], [], []
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
        P = align(P)
        try:
            X.append(eye_feats(P))
        except Exception:
            continue
        y.append(r["labels"]["eye_shape"])
        grp.append(name_split.get(Path(r["path"]).name, "unknown"))
        keep.append(k)
        if c % 300 == 0:
            print(f"  {c}/{len(idx)}", flush=True)
    fm.close()
    X = np.array(X); y = np.array(y); grp = np.array(grp)
    print(f"成功抽特徵 {len(X)} 張\n")

    tr = grp == "train"; ho = grp == "holdout"

    def evalset(Xtr, Xho):
        clf = RandomForestClassifier(n_estimators=300, random_state=42, class_weight="balanced")
        clf.fit(Xtr, y[tr])
        pred = clf.predict(Xho)
        return f1_score(y[ho], pred, average="macro"), accuracy_score(y[ho], pred)

    # CNN-alone(錨點)
    sess = ort.InferenceSession(str(MODELDIR / "eye_shape.onnx"), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name
    classes = json.loads((MODELDIR / "eye_shape_classes.json").read_text(encoding="utf-8"))
    classes = classes["classes"] if isinstance(classes, dict) else classes
    cnn_batch = np.concatenate([roi_to_tensor(rois["eye_shape"][k]) for k in keep], 0)
    cnn_logits = sess.run(None, {inp: cnn_batch})[0]
    cnn_prob = np.exp(cnn_logits - cnn_logits.max(1, keepdims=True))
    cnn_prob /= cnn_prob.sum(1, keepdims=True)
    cnn_pred = np.array([classes[i] for i in cnn_prob.argmax(1)])
    f_cnn = f1_score(y[ho], cnn_pred[ho], average="macro")
    a_cnn = accuracy_score(y[ho], cnn_pred[ho])

    f_base, a_base = evalset(X[tr][:, BASE3], X[ho][:, BASE3])
    f_rich, a_rich = evalset(X[tr], X[ho])
    # 融合:加強幾何 + CNN 機率
    Xf = np.concatenate([X, cnn_prob], axis=1)
    f_fus, a_fus = evalset(Xf[tr], Xf[ho])

    print("===== 眼型 holdout macro F1(越高越好)=====")
    print(f"  現有 3 幾何特徵      F1={f_base:.3f}  acc={a_base:.3f}  (錨點,應 ≈0.51)")
    print(f"  加強幾何(9 特徵)     F1={f_rich:.3f}  acc={a_rich:.3f}")
    print(f"  純 CNN               F1={f_cnn:.3f}  acc={a_cnn:.3f}  (錨點,應 ≈0.737)")
    print(f"  融合 加強幾何+CNN     F1={f_fus:.3f}  acc={a_fus:.3f}")
    print(f"\n  加強幾何 vs 現有幾何:{f_rich-f_base:+.3f}")
    print(f"  融合   vs 純 CNN   :{f_fus-f_cnn:+.3f}")

    clf = RandomForestClassifier(n_estimators=300, random_state=42, class_weight="balanced").fit(X[tr], y[tr])
    imp = sorted(zip(FEAT_NAMES, clf.feature_importances_), key=lambda t: -t[1])
    print("\n  加強幾何的特徵重要度:", "、".join(f"{n} {v:.2f}" for n, v in imp))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
