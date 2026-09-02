"""五官類別必須一路活到 Ollama 的 prompt 裡，中途不能被某一張表吃掉。

2026-08-24 模型加入第四類眉型「挑眉」時，`analysis_package.BROW_SHAPE_CODES` 有補上
`"挑眉": "arched"`，但建議端的 `MAP_BROW` / `EYEBROW_LOGIC` / `EYEBROW_METHOD` 三張表
都沒跟著加。後果不是報錯：`_map_or_raw` 查不到就把原值回傳，於是 prompt 寫成
「眉型：arched（）」——一個英文代碼配一對空括號，而眉毛做法退回通用文案。
`BROW_SHAPE_CODES` 的註解記著線上實測一萬張裡有 964 張（10%）判為挑眉。

這支測試把三層綁在一起：

    models/basic_features_roi/*_classes.json      模型實際會輸出的中文標籤
    face/analysis_package.py    *_SHAPE_CODES     中文標籤 → 英文 enum
    suggestion/Ollama_suggestion.py  MAP_* 等     英文 enum → 中文 → 描述與做法

任何一層加了類別而其他層沒跟上，這裡就會紅。`analysis_package_test.py` 只守第二層，
所以先前那次修補只修了一半而沒有人發現。

用正則讀原始碼而不 import：這樣不需要 suggestion 端的執行相依，CI 跑得起來。
"""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "basic_features_roi"
PACKAGE_SRC = (ROOT / "face" / "analysis_package.py").read_text(encoding="utf-8")
OLLAMA_SRC = (ROOT / "suggestion" / "Ollama_suggestion.py").read_text(encoding="utf-8")

# 部位、classes.json、資料包的代碼表、建議端的英文對照表、以中文標籤為 key 的描述表。
PARTS = [
    ("臉型", "face_shape_classes.json", "FACE_SHAPE_CODES", "MAP_FACE",
     ["FACE_LOGIC", "FACE_METHOD"]),
    ("眉型", "brow_shape_classes.json", "BROW_SHAPE_CODES", "MAP_BROW",
     ["EYEBROW_LOGIC", "EYEBROW_METHOD"]),
    ("眼型", "eye_shape_classes.json", "EYE_SHAPE_CODES", "MAP_EYE",
     ["EYE_LOGIC"]),
    ("鼻型", "nose_shape_classes.json", "NOSE_SHAPE_CODES", "MAP_NOSE",
     ["NOSE_LOGIC"]),
    ("唇型", "lip_shape_classes.json", "LIP_SHAPE_CODES", "MAP_LIP",
     ["LIP_LOGIC"]),
]


def _dict_literal(source: str, name: str) -> dict[str, str]:
    """讀出一個扁平字典字面值。這幾張表都是單層的，所以配到第一個 `}` 就結束。"""
    match = re.search(re.escape(name) + r"\s*=\s*\{(.*?)\}", source, re.S)
    assert match, f"找不到 {name}"
    return dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', match.group(1)))


def _classes(filename: str) -> list[str]:
    return json.loads((MODEL_DIR / filename).read_text(encoding="utf-8"))["classes"]


@pytest.mark.parametrize("part,classes_file,codes_name,map_name,logic_names", PARTS)
def test_every_model_class_reaches_the_prompt(part, classes_file, codes_name,
                                              map_name, logic_names):
    classes = _classes(classes_file)
    codes = _dict_literal(PACKAGE_SRC, codes_name)
    mapping = _dict_literal(OLLAMA_SRC, map_name)

    missing_code = [label for label in classes if label not in codes]
    assert not missing_code, (
        f"{part}：analysis_package.{codes_name} 缺 {missing_code}——"
        f"_code() 會回 unknown，模型答對了資料包卻把答案丟掉"
    )

    # 英文 enum 才是服務之間實際傳輸的值。MAP_* 查不到時 _map_or_raw 會原值回傳，
    # 於是那個英文代碼直接被寫進使用者看到的 prompt。
    missing_enum = [codes[label] for label in classes if codes[label] not in mapping]
    assert not missing_enum, (
        f"{part}：{map_name} 缺 {missing_enum}——prompt 會出現英文代碼而不是中文標籤"
    )

    wrong_round_trip = [
        (label, mapping[codes[label]]) for label in classes
        if mapping[codes[label]] != label
    ]
    assert not wrong_round_trip, (
        f"{part}：{map_name} 把類別對到了別的名字 {wrong_round_trip}"
    )

    for logic_name in logic_names:
        logic = _dict_literal(OLLAMA_SRC, logic_name)
        missing_logic = [label for label in classes if label not in logic]
        assert not missing_logic, (
            f"{part}：{logic_name} 缺 {missing_logic}——"
            f"查不到只會得到空字串，那句話少掉一半資訊而且不報錯"
        )


def test_arched_brow_specifically_survives():
    """挑眉是實際發生過的那一次，單獨立一條，紅的時候一眼看得出是哪個類別。"""
    assert _dict_literal(PACKAGE_SRC, "BROW_SHAPE_CODES").get("挑眉") == "arched"
    assert _dict_literal(OLLAMA_SRC, "MAP_BROW").get("arched") == "挑眉"
    assert _dict_literal(OLLAMA_SRC, "EYEBROW_LOGIC").get("挑眉")
    assert _dict_literal(OLLAMA_SRC, "EYEBROW_METHOD").get("挑眉")
