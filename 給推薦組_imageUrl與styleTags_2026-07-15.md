# 給推薦組：imageUrl 空白問題 + styleTags 串接建議

> 日期：2026-07-15
> 來源：前端／臉部分析端實測 `/recommend-products`（新 analysisPackage 格式已成功串接，感謝！）

## 1.（要修）推薦回應的 imageUrl 全部是空字串

新格式串接已經通了，推薦清單、分數、matchReason 都正常回來。唯一的問題：**每一件推薦商品的 `imageUrl` 都是 `""`**，前端商品卡只能顯示佔位圖。

但同一個服務的 `GET /api/products` 裡，同一件商品其實有完整的圖片網址（`image_src` 欄位），例如：

```
推薦回應：  "name": "Za 超磁久無瑕美肌粉底液 - PO20", "imageUrl": ""
商品清單：  "name": "Za 超磁久無瑕美肌粉底液 - PO20", "image_src": "https://www.za-cosmetics.tw/Uploads/ProductList/..."
```

我們用 12 件推薦商品實測，每一件都能在 `/api/products` 用 `sale_page_id` 或名稱對到，而且都有 `image_src`。所以資料是有的，只是推薦端點組回應時沒把圖片欄位帶出來。

**請求修改**：`/recommend-products` 回應的每件商品，把 `imageUrl` 填入你們資料庫的 `image_src` 值即可。

（前端目前已臨時用 `/api/products` 自行比對補圖，畫面不會開天窗，但正規解法還是推薦端點直接回圖，未來單獨呼叫推薦時才不用多拉一次全商品清單。）

另外順便回報：回應中的 `productUrl` 目前放的是 `sale_page_id` slug（如 `za-za-foundation-po20`），不是可點的完整網址。若這是刻意設計就維持，前端已相容；若原意是放商品頁連結，可以一併補完整 URL。

## 2.（需求）Ollama 文字建議提及的品項，要納入推薦依據

前端從 2026-07-15 起，已在請求的 `analysisPackage.generativeText.suggestion` 帶上 Ollama 產生的完整中文妝容建議文字（六段：整體方向／底妝／眉眼妝／唇妝／避免事項／總結）。

需求：**推薦演算法要把這份文字中提到的品項方向、色系、質地納入計分**，讓推薦出來的商品跟使用者讀到的文字建議互相呼應，而不是兩套各講各的。例如文字建議寫「霧面淺棕眼影」「裸豆沙色唇膏」，眼影就應優先推霧面淺棕色系、唇彩優先推裸豆沙色系。

你們目前每次回應都帶：

```
"fallbackReason": "generativeText.styleTags missing; used style default tags for 'natural'"
```

代表 styleScore 已支援 `generativeText.styleTags` 排序，只是上游沒給、每次都退回風格預設標籤。所以這條的實作路徑（擇一或並行）：

- **推薦端解析 suggestion**（建議優先，不依賴其他組）：從中文建議文字抽關鍵詞——色系（淺棕、豆沙、玫瑰…）、質地（霧面、珠光、水潤…）、品項（眼影、唇膏、腮紅…）——轉成內部 styleTags/preferredColors 參與 styleScore 計分。
- **上游補結構化欄位**：由 Ollama 端產生建議時一併輸出 `styleTags` / `preferredColors` / `avoidTags`（規格書 6.1 格式），前端原樣轉送。這條需要 Ollama 組配合，我們可以去談。

補充：Ollama 的 prompt 明確禁止編造特定品牌與色號，所以文字裡只會有「品項＋色系＋質地」的方向描述，不會出現真實商品名——把方向對應到實體商品，本來就是推薦端的職責。

## 3.（需求）「綜合推薦度」的依據要詳細說明

目前回應的 `matchReason` 資訊量太低，實測 12 件裡看到的是：

```
"matchReason": "綜合推薦度 5%"
"matchReason": "顏色相近"
"matchReason": "眉型與理想眉型吻合：完美搭配"
```

「綜合推薦度 5%」使用者看不懂 5% 是怎麼來的，也不知道為什麼 5% 還被推薦；「顏色相近」沒說跟什麼相近、多近。

需求：**每件商品的 `matchReason` 要能向使用者解釋這個分數的組成**，寫出人話版的依據。你們的 `scoreBreakdown` 四個分數（colorScore／styleScore／featureScore／availabilityScore）其實都算出來了，把它翻譯成文字即可，例如規格書 6.1 的範例格式：

```
"matchReason": "色調接近你的唇色（ΔE 3.2），且符合韓系清透妝的低飽和玫瑰色方向。"
```

建議至少涵蓋：
- 顏色分數的來源（跟使用者的膚色 LAB 還是唇色 LAB 比、色差多少或「非常接近／接近」的分級）。
- 風格分數對到哪些標籤（例如「符合 natural 的霧面、低飽和方向」）。
- 五官分數對應什麼（例如「圓形臉適合斜向修容」）。

另外請一併說明（或在 API 文件補上）：`score` 的計算公式與權重是否照規格書建議的 `color*0.40 + style*0.35 + feature*0.15 + availability*0.10`？我們實測分數與這組權重接近但不完全吻合，前端要對使用者解釋「綜合推薦指數」時需要正確版本。

## 4.（說明，不用改）各大類至少一件——你們已做到

實測回應 12 件涵蓋全部 7 大類（base/lip/eye/blush/contour/highlight/brow，前 7 件剛好每類一件）。之前線上只看到 4 件是前端顯示上限的問題，前端已於 2026-07-15 改為每個大類各顯示分數最高的一件，此項你們不用動——但請維持「回應必定涵蓋 7 大類」這個行為，前端顯示依賴它。

## 優先順序建議

1. 第 1 節 imageUrl（小改，馬上讓畫面完整）
2. 第 3 節 matchReason 詳細化（展示時要對外解釋推薦依據）
3. 第 2 節 suggestion 納入計分（需要新開發，可排後續）

## 附：目前實測正常的部分（不用動）

- `POST /recommend-products` 新 analysisPackage 格式：200，12 件推薦，含 `score`、`scoreBreakdown`（color/style/feature/availability 四分數）、`matchReason`。
- 錯誤格式回 `400 INVALID_ANALYSIS_PACKAGE`，與規格書一致。
- 中文欄位值（臉型「鵝蛋臉」等）正常處理。
