"""檢查分類表在所有地方是否一致。改過類別之後**一定要跑這支**。

## 為什麼需要它

同一個事實目前抄在五個地方：

    prepare_roi_cache.CANONICAL_LABELS      訓練側的唯一事實來源
    models/basic_features_roi/*_classes.json  模型實際輸出的類別（隨重訓更新）
    analysis_package.*_SHAPE_CODES          中文 → 代碼
    Ollama_suggestion.MAP_* / *_LOGIC       代碼 → 中文、中文 → 描述詞
    replicate_render.FACE_TERM_EN           中文 → 英文 prompt

**任何一份沒跟上都不會報錯**，只會安靜地劣化：

  - 2026-07-24 眼型合併，Ollama 的 MAP_EYE 沒跟上 → 鳳眼被顯示成已淘汰的「丹鳳眼」，
    使用者在回饋面板上看到的選項裡根本沒有那個名字。撐了六天沒人發現。
  - 2026-07-30 桃杏眼上線，MAP_EYE 沒有 peach_almond → `_map_or_raw` 查不到是
    **原樣回傳**，於是英文 enum 被寫進要餵給中文語言模型的 prompt：
    「眼型：peach_almond（）」。
  - MAP_NOSE 把 standard 顯示成「直鼻」，而分類表裡只有「標準鼻」——
    使用者想修正也選不到自己看到的那個名字。

三次都是同一種病：**查不到就跳過或原樣輸出，沒有任何一層會吵。**

## 這支怎麼判

以 `prepare_roi_cache.CANONICAL_LABELS` 為基準（訓練側決定分類表），檢查四件事：

  1. 每個現行類別，在每一張下游表都查得到
  2. 每一張表都**不含**已淘汰或不存在的類別
  3. 已淘汰的名稱能被 `analysis_package.canonical_label` 正規化成現行名稱
  4. 模型實際輸出的類別（*_classes.json）與分類表一致

有任何一項不符就 exit code 1，讓它在 CI 或部署前大聲失敗。

    .\.venv\Scripts\python.exe -X utf8 tools/check_label_tables.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analysis_package as ap  # noqa: E402
from prepare_roi_cache import CANONICAL_LABELS  # noqa: E402

MODEL_DIR = Path("models/basic_features_roi")

# 部位 -> (代碼表, 顯示表, 描述表)
PART_TO_FIELD = {
    "face_shape": "臉型", "brow_shape": "眉型", "eye_shape": "眼型",
    "nose_shape": "鼻型", "lip_shape": "嘴型",
}
UNKNOWN = {"未知", "未知臉型", "未知眉型", "未知眼型", "未知鼻型", "未知唇型"}
# 膚色分級與四季型也放在 FACE_TERM_EN 裡，不是五官類別
NON_PART_TERMS = {"白皙", "自然", "健康", "小麥", "春", "夏", "秋", "冬"}

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


def main() -> int:
    from Ollama_suggestion import (
        MAP_FACE, MAP_BROW, MAP_EYE, MAP_NOSE, MAP_LIP,
        FACE_LOGIC, EYEBROW_LOGIC, EYE_LOGIC, NOSE_LOGIC, LIP_LOGIC,
    )
    from replicate_render import FACE_TERM_EN

    codes = {
        "face_shape": ap.FACE_SHAPE_CODES, "brow_shape": ap.BROW_SHAPE_CODES,
        "eye_shape": ap.EYE_SHAPE_CODES, "nose_shape": ap.NOSE_SHAPE_CODES,
        "lip_shape": ap.LIP_SHAPE_CODES,
    }
    maps = {"face_shape": MAP_FACE, "brow_shape": MAP_BROW, "eye_shape": MAP_EYE,
            "nose_shape": MAP_NOSE, "lip_shape": MAP_LIP}
    logics = {"face_shape": FACE_LOGIC, "brow_shape": EYEBROW_LOGIC, "eye_shape": EYE_LOGIC,
              "nose_shape": NOSE_LOGIC, "lip_shape": LIP_LOGIC}

    all_canon = {x for v in CANONICAL_LABELS.values() for x in v}

    print("=== 1. 現行類別在每張表都查得到 ===")
    for part, canon in CANONICAL_LABELS.items():
        miss = {
            "代碼(analysis_package)": [x for x in canon if x not in codes[part]],
            "顯示(Ollama MAP)": [x for x in canon if x not in maps[part].values()],
            "描述(Ollama LOGIC)": [x for x in canon if x not in logics[part]],
            "渲染(replicate FACE_TERM_EN)": [x for x in canon if x not in FACE_TERM_EN],
        }
        bad = {k: v for k, v in miss.items() if v}
        check(not bad, f"{part} 缺: {bad}")
        print(f"  {part:12s} {'[OK]' if not bad else bad}")

    print("\n=== 2. 每張表都不含已淘汰／不存在的類別 ===")
    tables = [(f"analysis_package.{part}", set(codes[part]), part) for part in CANONICAL_LABELS]
    tables += [(f"Ollama.MAP[{part}](值)", set(maps[part].values()), part) for part in CANONICAL_LABELS]
    tables += [(f"Ollama.LOGIC[{part}]", set(logics[part]), part) for part in CANONICAL_LABELS]
    for name, keys, part in tables:
        stray = sorted(keys - set(CANONICAL_LABELS[part]) - UNKNOWN)
        check(not stray, f"{name} 含非現行類別 {stray}")
        if stray:
            print(f"  {name:36s} *** {stray}")
    stray_render = sorted(k for k in FACE_TERM_EN if k not in all_canon and k not in NON_PART_TERMS)
    check(not stray_render, f"replicate_render.FACE_TERM_EN 含非現行類別 {stray_render}")
    print(f"  replicate_render.FACE_TERM_EN        {'[OK]' if not stray_render else stray_render}")
    if not failures:
        print("  （其餘皆乾淨）")

    print("\n=== 3. 已淘汰名稱能正規化成現行 ===")
    for old, new in ap.LABEL_ALIASES.items():
        got = ap.canonical_label(old)
        ok = got == new and new in all_canon
        check(ok, f"別名 {old} -> {got} 不是現行類別")
        print(f"  {old:5s} -> {got:5s} {'[OK]' if ok else '***'}")

    print("\n=== 4. 模型輸出的類別與分類表一致 ===")
    for part, canon in CANONICAL_LABELS.items():
        for suffix in ("_classes.json", "_dinov2_classes.json"):
            p = MODEL_DIR / f"{part}{suffix}"
            if not p.is_file():
                continue
            got = set(json.loads(p.read_text(encoding="utf-8"))["classes"])
            ok = got == set(canon)
            check(ok, f"{p.name} 的類別 {sorted(got)} 與分類表 {sorted(canon)} 不符")
            print(f"  {p.name:34s} {'[OK]' if ok else '*** ' + str(sorted(got))}")

    print()
    if failures:
        print(f"*** 未通過（{len(failures)} 項）：")
        for f in failures:
            print("   ", f)
        return 1
    print("全部一致：分類表、代碼表、顯示表、描述表、渲染表、模型類別檔。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
