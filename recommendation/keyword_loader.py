"""載入 MAKEUP_KEYWORD_WHITELIST:每種妝容、每個分類的檢索關鍵字。

派工書 §執行流程 step 3:讀取 eyeshadows、blushes、lipsticks 的關鍵字。
不硬編碼商品,只用關鍵字動態查詢現有商品資料庫。

檔案格式(JSON,鍵一律用**顯示名稱**):
{
  "千金": {
    "eyeshadows": ["奶茶", "大地色", "燕麥"],
    "blushes":    ["裸粉", "杏色"],
    "lipsticks":  ["奶茶玫瑰", "豆沙"]
  },
  ...
}

⚠️ 第 3 人待交付:`recommendation/keywords.json` 是**真正的白名單**。
本 repo 只附 `keywords.example.json` 佔位,讓骨架能跑;數值不是最終答案。
"""
from __future__ import annotations

import json
from pathlib import Path

from .style_alias import DISPLAY_NAMES, normalize_style

# 這一版只用這三個分類(派工書:不使用膚質與場合)。
CATEGORIES = ("eyeshadows", "blushes", "lipsticks")

_DEFAULT_PATH = Path(__file__).with_name("keywords.json")
_EXAMPLE_PATH = Path(__file__).with_name("keywords.example.json")


class KeywordWhitelistError(RuntimeError):
    """白名單缺失或格式錯誤。"""


def load_keywords(path: str | Path | None = None) -> dict[str, dict[str, list[str]]]:
    """載入白名單。未指定路徑時:先找正式的 keywords.json,沒有就退回 example 佔位並警告。"""
    if path is not None:
        p = Path(path)
    elif _DEFAULT_PATH.is_file():
        p = _DEFAULT_PATH
    elif _EXAMPLE_PATH.is_file():
        import warnings
        warnings.warn("使用 keywords.example.json 佔位白名單;第 3 人請交付正式的 keywords.json",
                      stacklevel=2)
        p = _EXAMPLE_PATH
    else:
        raise KeywordWhitelistError(f"找不到白名單:{_DEFAULT_PATH} 或 {_EXAMPLE_PATH}")

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise KeywordWhitelistError(f"白名單讀取失敗 {p}:{exc}") from exc

    if not isinstance(data, dict):
        raise KeywordWhitelistError("白名單最外層必須是物件(妝容顯示名稱 -> 分類 -> 關鍵字)")
    # 正規化鍵成顯示名稱,並檢查分類。
    normalized: dict[str, dict[str, list[str]]] = {}
    for style_key, cats in data.items():
        if str(style_key).startswith("_"):
            continue  # 底線開頭的鍵(如 _note)是註解,不是妝容
        try:
            name = normalize_style(style_key)
        except Exception:
            raise KeywordWhitelistError(f"白名單有不認識的妝容鍵:{style_key}")
        if not isinstance(cats, dict):
            raise KeywordWhitelistError(f"{style_key} 的值必須是分類 -> 關鍵字")
        normalized[name] = {
            c: [str(k) for k in (cats.get(c) or [])] for c in CATEGORIES
        }
    return normalized


def keywords_for(whitelist: dict, style_name: str, category: str) -> list[str]:
    """取某妝容某分類的關鍵字;缺就回空清單(呼叫端自行決定是否算分類不完整)。"""
    return list((whitelist.get(style_name) or {}).get(category) or [])


def assert_complete(whitelist: dict) -> list[str]:
    """回傳「缺關鍵字」的 (妝容, 分類) 清單,供分類完整率統計。空清單代表完整。"""
    missing = []
    for name in DISPLAY_NAMES:
        for cat in CATEGORIES:
            if not keywords_for(whitelist, name, cat):
                missing.append(f"{name}/{cat}")
    return missing
