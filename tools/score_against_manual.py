"""拿人工校對表當答案，量**目前這一版模型**的準確率。

為什麼不能直接讀校對表裡的「模型_」欄
--------------------------------------
那些欄位是**產生表格當下**的預測。模型換過之後它們就過期了——2026-08-25 就發生：
表格裡的眉型是 3 類版（一字眉／彎月眉／落尾眉），而線上已經換成 4 類的
`20260824_brow4`。拿過期的預測去算準確率，量到的是一個已經不存在的模型。

所以這支腳本重跑推論：讀 `models/basic_features_roi/` 底下**現在**的 ONNX，
對同一批照片跑一次，再跟人工答案比。那個目錄就是部署時打包進映像的內容
（見 tools/face_models_manifest.json），所以本機跑等於線上跑。

「不確定」怎麼處理
------------------
不算進分母。那代表人也看不出來，把它算成模型錯會低估、算成對會高估——
兩種都是拿無法判定的樣本充數。單獨回報數量。

用法
----
    python tools/score_against_manual.py \
        --xlsx 亞洲人臉一萬筆人工校對/亞洲人臉200筆_ConvNeXt_人工校對.xlsx
"""

from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import mediapipe_ascii  # noqa: F401
import mediapipe as mp
import numpy as np

import basic_roi_shadow
# 同 build_review_sheet：校對表的欄位名跟服務端不完全一樣。
# 先前這裡用服務端的名字，於是「人工_唇型」那一欄從來沒被讀到——
# 沒有錯誤訊息，唇型就是靜靜地不列入準確率。
from review_sheet_schema import SHEET_FIELD as PART_TO_FIELD

MAX_IMAGE_SIZE = 1024


def load_manual(xlsx: Path) -> tuple[list[dict], dict]:
    """讀校對表。回傳每一列的人工答案與表格內記載的舊預測（供對照）。"""
    import openpyxl
    wb = openpyxl.load_workbook(xlsx)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    hdr = {h: i for i, h in enumerate(rows[0])}
    fields = [f for f in PART_TO_FIELD.values() if f"人工_{f}" in hdr]

    out, img_dir = [], None
    for r in rows[1:]:
        # 圖片路徑藏在 HYPERLINK 公式裡；只取一次目錄就夠
        if img_dir is None:
            m = re.search(r'"([^"]+)"', str(r[hdr.get("看圖", 0)]) or "")
            if m:
                img_dir = Path(m.group(1)).parent
        manual = {f: r[hdr[f"人工_{f}"]] for f in fields if r[hdr[f"人工_{f}"]]}
        if not manual:
            continue
        out.append({
            "file": r[hdr["檔名"]],
            "manual": manual,
            "sheet_pred": {f: r[hdr[f"模型_{f}"]] for f in fields if f"模型_{f}" in hdr},
        })
    return out, {"fields": fields, "img_dir": img_dir}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--images", default=None, help="照片目錄（預設從表格的 HYPERLINK 推）")
    args = ap.parse_args()

    rows, meta = load_manual(Path(args.xlsx))
    img_dir = Path(args.images) if args.images else meta["img_dir"]
    fields = meta["fields"]
    print(f"  校對表 {Path(args.xlsx).name}｜有人工答案的 {len(rows)} 張")
    print(f"  照片目錄 {img_dir}")

    state = basic_roi_shadow.model_status()
    print(f"  模型：{state.get('architecture')}｜就緒 {state.get('ready')}")
    for part in PART_TO_FIELD:
        p = Path(basic_roi_shadow.MODEL_DIR) / f"{part}_classes.json"
        if p.is_file():
            print(f"    {part:12} {json.loads(p.read_text(encoding='utf-8'))['classes']}")

    mesh = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1,
                                           refine_landmarks=False, min_detection_confidence=0.5)
    hit = defaultdict(int); tot = defaultdict(int); unc = defaultdict(int)
    sheet_hit = defaultdict(int); sheet_tot = defaultdict(int)
    confusion = defaultdict(Counter)
    failed = 0
    for i, row in enumerate(rows, 1):
        path = img_dir / str(row["file"])
        frame = (cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
                 if path.is_file() else None)
        if frame is None:
            failed += 1
            continue
        h0, w0 = frame.shape[:2]
        s = MAX_IMAGE_SIZE / max(h0, w0)
        if s < 1:
            frame = cv2.resize(frame, (int(w0 * s), int(h0 * s)), interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
        res = mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not res.multi_face_landmarks:
            failed += 1
            continue
        pts = np.array([[int(lm.x * w), int(lm.y * h)]
                        for lm in res.multi_face_landmarks[0].landmark], dtype=np.int32)
        pred = basic_roi_shadow.predict(frame, pts) or {}

        for f in fields:
            ans = row["manual"].get(f)
            if not ans:
                continue
            if ans == "不確定":
                unc[f] += 1
                continue
            # 有些部位回的是物件而不是字串（眼型的融合結果帶 confidence，
            # 見 basic_roi_shadow._eye_fusion_predict）。統一取 label。
            now = pred.get(f)
            if isinstance(now, dict):
                now = now.get("label") or now.get("value")
            if now:
                tot[f] += 1
                hit[f] += (now == ans)
                if now != ans:
                    confusion[f][(now, ans)] += 1
            old = row["sheet_pred"].get(f)
            if old:
                sheet_tot[f] += 1
                sheet_hit[f] += (old == ans)
        if i % 20 == 0:
            print(f"    {i}/{len(rows)}", flush=True)
    mesh.close()

    print(f"\n  {'部位':6}{'現在的模型':>12}{'表格裡的舊預測':>16}{'不確定':>8}")
    for f in fields:
        now = f"{hit[f]}/{tot[f]} = {hit[f]/tot[f]:.1%}" if tot[f] else "—"
        old = f"{sheet_hit[f]}/{sheet_tot[f]} = {sheet_hit[f]/sheet_tot[f]:.1%}" if sheet_tot[f] else "—"
        print(f"  {f:6}{now:>12}{old:>16}{unc[f]:>8}")
    T, H = sum(tot.values()), sum(hit.values())
    ST, SH = sum(sheet_tot.values()), sum(sheet_hit.values())
    print(f"  {'合計':6}{f'{H}/{T} = {H/T:.1%}' if T else '—':>12}"
          f"{f'{SH}/{ST} = {SH/ST:.1%}' if ST else '—':>16}{sum(unc.values()):>8}")
    if failed:
        print(f"\n  {failed} 張讀不到或偵測不到人臉，未計入")

    print(f"\n  現在的模型最常錯在哪（模型說 → 你說）：")
    for f in fields:
        if confusion[f]:
            top = "、".join(f"{a}→{b} {n}次" for (a, b), n in confusion[f].most_common(3))
            print(f"    {f:6} {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
