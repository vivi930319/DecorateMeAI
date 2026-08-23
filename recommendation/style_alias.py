"""妝容映射:styleId 與顯示名稱互轉。字典放後端,不傳入前端 bundle。

演算法同時接受 styleId(richGirl)與顯示名稱(千金)。所有下游(keyword_loader、
gold 標準答案)都以**顯示名稱**為鍵,因此對外一律先 normalize 成顯示名稱。
"""
from __future__ import annotations

# 來源:派工書 §妝容映射。七種妝容。
STYLE_ALIAS: dict[str, str] = {
    "softBaddie": "Soft Baddie",
    "richGirl": "千金",
    "hongKong": "港風",
    "koreanClean": "韓系亞裔",
    "yandere": "病嬌",
    "japaneseClear": "日雜清透",
    "mensPlain": "男士白開水",
}

# 顯示名稱 -> styleId,供反查。
NAME_TO_ID: dict[str, str] = {name: sid for sid, name in STYLE_ALIAS.items()}

# 全部合法顯示名稱。
DISPLAY_NAMES = frozenset(STYLE_ALIAS.values())


class UnknownMakeupStyle(ValueError):
    """妝容不存在。對應錯誤碼 UNKNOWN_MAKEUP_STYLE(HTTP 422)。"""


def normalize_style(value: str) -> str:
    """把 styleId 或顯示名稱正規化成**顯示名稱**;認不得就丟 UnknownMakeupStyle。

    大小寫敏感的部分只在 styleId 上寬鬆處理(richgirl == richGirl),
    顯示名稱是中文/固定字串,原樣比對。
    """
    if not isinstance(value, str) or not value.strip():
        raise UnknownMakeupStyle("style 不可為空")
    v = value.strip()
    if v in DISPLAY_NAMES:
        return v
    if v in STYLE_ALIAS:
        return STYLE_ALIAS[v]
    # styleId 大小寫不敏感的最後嘗試
    lower = {sid.lower(): name for sid, name in STYLE_ALIAS.items()}
    if v.lower() in lower:
        return lower[v.lower()]
    raise UnknownMakeupStyle(f"不支援的妝容:{value}")


def style_id_of(display_name: str) -> str:
    """顯示名稱 -> styleId。"""
    return NAME_TO_ID.get(display_name, "")
