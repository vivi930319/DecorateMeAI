"""人工校對表的欄位名稱，一份定義給所有讀寫校對表的工具共用。

為什麼需要這一份
----------------
唇型在系統裡有兩個名字：服務端的 `PART_TO_FIELD` 用「嘴型」（那是使用者在分析頁
看到的字），而所有既有的校對表用「唇型」。兩邊各自寫死的結果是靜默的漏讀——
`score_against_manual.py` 只收表頭裡找得到的欄位，遇到「人工_唇型」的表就整欄跳過，
畫面上不會有任何錯誤，只是唇型永遠不列入準確率。

所以校對表的欄位名獨立定義在這裡。要改欄位名就改這一份，不要在各個工具裡各寫一次。
"""
from __future__ import annotations

from basic_roi_shadow import PART_TO_FIELD

# 部位代號 -> 校對表裡的欄位名。
# 除了唇型之外都跟服務端一致；唇型沿用既有校對表的「唇型」，
# 因為已經產出的表與 score_review / apply_review 都是那個名字。
SHEET_FIELD: dict[str, str] = {**PART_TO_FIELD, "lip_shape": "唇型"}

# 反查。匯入時要把表格欄位換回部位代號。
FIELD_TO_PART: dict[str, str] = {v: k for k, v in SHEET_FIELD.items()}

# 校對表欄位名 -> 服務端欄位名（`face_feedback` 的 corrections 用的是這一組）。
# 兩者只有唇型不同，但那一個不同就足以讓整欄消失。
SHEET_TO_SERVICE: dict[str, str] = {
    SHEET_FIELD[part]: PART_TO_FIELD[part] for part in SHEET_FIELD if part in PART_TO_FIELD
}
