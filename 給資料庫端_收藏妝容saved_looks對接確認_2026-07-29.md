# 給資料庫端 — 收藏妝容 `saved_looks` 對接確認

**日期：** 2026-07-29
**提出方：** DECORATE ME 前端 + AI Gateway
**對象：** 會員資料庫維運者
**現象：** 後台顯示的收藏筆數與資料庫實際列數**不一致**。

---

## 0. 我們需要你回答的三件事

其餘都是背景說明。真正卡住的是這三個：

| # | 問題 | 為什麼問 |
| --- | --- | --- |
| **Q1** | `GET /api/members/{email}/saved-looks` 回應的 **JSON 外殼**是什麼？<br>`{"looks":[…]}`？`{"items":[…]}`？還是裸陣列 `[…]`？ | 我們只認得其中一種，認錯就顯示 0 筆 |
| **Q2** | `POST .../saved-looks` 成功時，**新建立的 id 放在哪一層**？<br>`{"id":123,…}`？還是 `{"look":{"id":123}}`？ | 拿不到 id，使用者之後刪除就刪不掉你們那一列 |
| **Q3** | `GET` 有沒有**分頁或預設筆數上限**？有沒有依 `status` 之類的欄位過濾？ | 若有，後台看到的本來就會比實際列數少 |

---

## 1. 先排除一件事：後台沒有別的資料來源

後台的收藏清單**只呼叫這一支**：

```
GET /api/members/{email}/saved-looks
```

沒有本機快取、沒有第二條路（`js/router.js` 的 `loadAllSavedLooks`）。
所以「後台顯示的筆數」＝「這支端點回給我們、而且我們解析得出來的筆數」。

兩邊對不上，只可能出在①回應格式我們讀不到、②你們有過濾或分頁、③殘留列（見 §3）。

---

## 2. Q1 —— 回應外殼（目前最可能的原因）

我們原本的程式碼是這樣：

```js
return { ok: true, looks: Array.isArray(data.looks) ? data.looks : [] };
```

**只認 `data.looks`。** 但同一個檔案裡其他清單端點都同時認 `items`：

| 端點 | 我們接受的外殼 |
| --- | --- |
| 商品清單 | `items` → `products` |
| 稽核紀錄 | `items` → `logs` |
| 會員清單 | `items` |
| **收藏妝容** | **只有 `looks`** ← 唯一的例外 |

**如果你們回的是 `{"items":[…]}` 或裸陣列，我們就會顯示 0 筆，而且完全沒有錯誤訊息。**

### 我們已經先改了（2026-07-29 上線）

現在四種外殼都收：`looks` / `items` / `savedLooks` / `saved_looks` / 裸陣列。
認不得的形狀會在瀏覽器 Console 印出實際的 keys，不再靜靜當成「這個人沒有收藏」。

**但還是請回答 Q1**，我們要把契約寫死，不想長期靠猜。

---

## 3. Q2 —— POST 的 id 放在哪一層（這個會讓你們累積殘留列）

我們現在這樣讀：

```js
const look = await res.json();
// 之後用 r.look.id 當作這筆收藏在你們那邊的主鍵
```

也就是**預期 `id` 在回應的最外層**：

```json
{ "id": 123, "style": "港風", "afterImageUrl": "...", "createdAt": "..." }
```

### 如果 id 不在最外層，會發生什麼

1. 我們拿不到 id，本機那筆收藏就沒有 `remoteId`
2. 使用者之後在前台按刪除時，我們**只刪本機**，因為沒有 id 可以告訴你們刪哪一列
3. **你們的 `saved_looks` 會留下一列使用者以為已經刪掉的資料**

這會直接造成筆數對不上，而且是往「資料庫比使用者預期的多」的方向。
如果你們現在去看，有一批很舊、使用者早就刪掉的收藏還在，大概就是這個原因。

---

## 4. 我們送給你們的完整內容（確認用）

### 4.1 新增

```http
POST /api/members/{email}/saved-looks
Content-Type: application/json
Cookie: __session=…            ← 經 AI Gateway 帶入的會員 session
```

```json
{
  "style": "港風",
  "afterImageUrl": "https://decorate-me.web.app/media/render/3f2a91c8d5e74b06a1cc82e4f7b03d19",
  "beforeImageUrl": "",
  "analysisSummary": {
    "faceShape": "鵝蛋臉", "browShape": "一字眉", "eyeShape": "鳳眼",
    "noseShape": "標準鼻", "lipShape": "薄唇", "skinSeason": "夏"
  }
}
```

**就這四個欄位，沒有任何圖片二進位資料、沒有 base64。**

### 4.2 `beforeImageUrl` 幾乎都是空字串 —— 這是設計，不是壞掉

妝後圖由渲染服務產生，一定有網址。
妝前圖是**使用者自己上傳的照片**，系統裡沒有任何管道能讓它變成網址 ——
Gateway 只有 `GET /media/render` 與 `/media/legacy`，**沒有上傳端點**。

所以它在前端永遠是 `data:image/…;base64,…`（常常 90 萬字元），
而 `before_image_url` 是 `String(500)`。我們刻意不送。

> 這裡出過一次事故（我方 S57）：先前連妝前圖一起做網址檢查，
> 結果**每一筆收藏都在送出前被自己擋掉**，畫面一切正常、資料庫一筆都沒進。

**請確認你們的欄位允許空字串**（非 NOT NULL、沒有 URL 格式驗證）。
先前 `INVALID_AFTER_IMAGE_URL` 那類驗證曾經擋掉整筆寫入。

---

## 5. 順帶說明：為什麼那些網址你們打不開

`after_image_url` 存的是**一段網址**，不是圖：

```
https://decorate-me.web.app/media/render/<32 位十六進位>
```

它由 **AI Gateway** 提供，不是靜態檔案。打進來時會驗會員 session、
檢查擁有者，通過才 302 轉到一個 **10 分鐘有效**的 GCS 私有網址。

| 你怎麼打 | 結果 |
| --- | --- |
| 瀏覽器直接貼（沒登入） | **401** |
| curl / Postman（沒 session） | **401** |
| 已登入的前端 `<img src>` | ✅ 正常 |

**看到 401 不代表資料有問題** —— 圖是私有的，那是使用者的臉。
請區分：

- **401** = 沒登入，資料好好的
- **404** = 圖真的過期了（render job 1 小時、GCS 物件 30 天；收藏時會呼叫 `/retain` 保住）

---

## 6. 你們可以自己跑的驗證

```sql
-- ① 某個會員的實際列數
SELECT COUNT(*) FROM saved_looks WHERE member_email = '<某個會員>';

-- ② 前 20 列長什麼樣
SELECT id, member_email, style, after_image_url, before_image_url, created_at
FROM saved_looks WHERE member_email = '<某個會員>'
ORDER BY created_at DESC LIMIT 20;

-- ③ before_image_url 是空字串的比例（預期接近 100%）
SELECT COUNT(*) FILTER (WHERE COALESCE(before_image_url,'') = '') AS 空的,
       COUNT(*) AS 總數
FROM saved_looks;
```

把 ① 的數字告訴我們，我們對照後台顯示的筆數，就能確定是往多還是往少的方向差。

**測試圖片時請不要複製 `__session` cookie 到任何地方** —— 那是 HttpOnly 的會員憑證。
用瀏覽器登入後在同一個分頁貼上網址即可。

---

## 7. 端點一覽

| 方法 | 路徑 | 用途 |
| --- | --- | --- |
| GET | `/api/members/{email}/saved-looks` | 列出收藏（前台與後台都用這支）|
| POST | `/api/members/{email}/saved-looks` | 新增收藏 |
| DELETE | `/api/members/{email}/saved-looks/{id}` | 刪除收藏（`{id}` 來自 POST 的回應）|

全部經由 AI Gateway 轉送並帶會員 session，我們不會從瀏覽器直接打你們的服務。
