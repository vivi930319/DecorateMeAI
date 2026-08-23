# 妝容字典商品推薦(第 3 人)— 骨架

由第 1 人搭好可跑的骨架;第 3 人接手填**兩個輸入**、校準關鍵字並跑準確率。

## 結構
```
recommendation/
  style_alias.py          styleId <-> 顯示名稱(七妝容)
  keyword_loader.py       載入 MAKEUP_KEYWORD_WHITELIST
  product_search.py       查啟用商品(GET /product-api/api/products)
  product_ranker.py       依關鍵字計分、去重、排序
  recommendation_service.py  完整流程 + 錯誤碼
  keywords.example.json   佔位白名單(可跑,非最終)
  gold/README.md          人工標準答案格式
tests/recommendation/
  test_style_alias.py / test_keyword_match.py / test_product_ranker.py
  test_recommendation_contract.py
  evaluate_precision_at_k.py   Precision@K + 錯誤率
```

## 第 3 人待交付的兩個輸入
1. `recommendation/keywords.json` — 正式關鍵字白名單(格式見 keywords.example.json)。
2. `recommendation/gold/<styleId>.json` — 七妝容人工標準答案(格式見 gold/README.md)。

## 跑法
```
python -m pytest tests/recommendation          # 單元測試(不打網路)
python tests/recommendation/evaluate_precision_at_k.py   # Precision@K(打真實商品 API)
```

## 目標(派工書)
Precision@5 ≥ 80%;重複率／停用商品率／幻覺商品率 皆 0%。商品 100% 來自資料庫。

## 已內建對齊實測的契約
- style 同時吃 styleId 與顯示名稱;未知妝容 → `UNKNOWN_MAKEUP_STYLE`(422)。
- 空結果 → `RECOMMENDATION_EMPTY` + 空陣列(不是 500、不回假商品)。
- 商品庫失效/逾時 → `PRODUCT_DB_UNAVAILABLE`(502)/`PRODUCT_DB_TIMEOUT`(504)。
- 錯誤回應只帶 error,不夾帶 products。
- 幻覺商品率 = 推薦 id 不在商品資料庫的比例(evaluate 會實際比對 catalog)。
