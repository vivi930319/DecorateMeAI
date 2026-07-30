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

def discover_heads() -> dict[str, tuple[str, str]]:
    """從 model_selection.json 讀「哪個部位用哪個分類器」，不要在這裡再抄一份。

    先前這裡是硬編清單。2026-07-31 眼型由 logistic_regression 改成 linear_svc 時，
    train_final_selected_models 改了、這裡沒改，於是它繼續去載那個**已經不會再產生**
    的舊 joblib——匯出「成功」，但線上拿到的是上一版的頭。
    同一個事實抄兩份，就會有一份先過期（見發展歷程規格書 §7.8 的通則）。
    """
    sel = json.loads((SRC / "model_selection.json").read_text(encoding="utf-8"))["models"]
    heads: dict[str, tuple[str, str]] = {}
    for part, spec in sel.items():
        if "+" not in spec:            # mobilenet 之類的不是線性頭，跳過
            continue
        kind = spec.split("+", 1)[1]   # dinov2_vits14+linear_svc -> linear_svc
        heads[part] = (f"{part}_dinov2_{kind}.joblib", kind)
    return heads


def main() -> None:
    emb = np.load("data/roi_cache/dinov2_embeddings.npz")["embeddings"][:400]

    for part, (filename, kind) in discover_heads().items():
        clf = joblib.load(SRC / filename)
        coef = np.asarray(clf.coef_, dtype=np.float32)
        intercept = np.asarray(clf.intercept_, dtype=np.float32)

        out = DST / f"{part}_dinov2_head.npz"
        np.savez(out, coef=coef, intercept=intercept, kind=np.array(kind))

        # 類別檔要跟著 head 一起更新，否則兩者會不同步。
        # 2026-07-30 就踩到：head 已重訓成 5 類（桃杏眼），旁邊的 *_dinov2_classes.json
        # 還停在 8 類（含丹鳳眼、瞇縫眼）。basic_roi_shadow 的 _retired_labels 守衛會
        # 因此拒絕載入整個 head——功能沒壞，但重訓等於白做，而且從外面看不出原因。
        src_classes = SRC / f"{part}_classes.json"
        if src_classes.is_file():
            classes = json.loads(src_classes.read_text(encoding="utf-8"))["classes"]
            (DST / f"{part}_dinov2_classes.json").write_text(
                json.dumps({"classes": classes, "architecture": "dinov2_vits14"},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
            print(f"{part:11s} 類別檔同步為 {len(classes)} 類")

        # 驗證：numpy 的結果必須與 sklearn 完全一致，否則抽權重的方式有誤
        scores = emb @ coef.T + intercept
        mine = scores.argmax(1) if scores.shape[1] > 1 else (scores[:, 0] > 0).astype(int)
        ref = clf.predict(emb)
        agree = int((mine == ref).sum())
        status = "一致" if agree == len(ref) else f"不一致（{agree}/{len(ref)}）"
        print(f"{part:11s} {kind:20s} coef={coef.shape} -> {out.name}  {status}")


if __name__ == "__main__":
    main()
