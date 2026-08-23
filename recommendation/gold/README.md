# 人工標準答案(gold answers)— 第 3 人待交付

Precision@K 需要「每種妝容,哪些商品算正確推薦」的人工標準答案。

每個 styleId 一個檔:`recommendation/gold/<styleId>.json`,例如 `richGirl.json`。
格式:相關商品 id 陣列,id 用 `type:id`(和推薦回傳的 id 一致)。

```json
{
  "style": "richGirl",
  "relevant": ["lipsticks:2656", "eyeshadows:1201", "blushes:889"]
}
```

七個檔:`softBaddie.json`、`richGirl.json`、`hongKong.json`、`koreanClean.json`、
`yandere.json`、`japaneseClear.json`、`mensPlain.json`。

沒有 gold 檔的妝容,`evaluate_precision_at_k.py` 會 SKIP(不列入平均)。
標準答案請以**真實商品資料庫**的 id 標註,不可用 Ollama 虛構名稱。
