"""妝容字典驅動的商品推薦(第 3 人)。

模組:
    style_alias           styleId <-> 顯示名稱
    keyword_loader        載入 MAKEUP_KEYWORD_WHITELIST
    product_search        查啟用商品(經 Gateway 商品 API)
    product_ranker        依關鍵字計分、去重、排序
    recommendation_service  串起完整流程

第 3 人待交付的兩個輸入:
    recommendation/keywords.json        正式關鍵字白名單(附 keywords.example.json 佔位)
    recommendation/gold/<styleId>.json  七種妝容的人工標準答案(給 Precision@K)
"""
from . import (  # noqa: F401
    keyword_loader,
    product_ranker,
    product_search,
    recommendation_service,
    style_alias,
)
