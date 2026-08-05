# 前端串接 API 規格與新手教學

這份文件是給第一次接觸 API 的前端新手使用。目標是讓你知道：

- API 是什麼
- 前端要怎麼呼叫 API
- Request 和 Response 怎麼看
- 登入 token 怎麼帶
- 常見錯誤怎麼處理
- 實際程式碼怎麼寫

---

## 1. API 是什麼？

API 可以想成是「前端跟後端溝通的窗口」。

前端負責畫面，例如：

- 登入頁
- 商品列表
- 會員資料頁
- 表單送出

後端負責資料，例如：

- 檢查帳號密碼
- 從資料庫拿商品
- 儲存表單
- 回傳會員資料

前端要資料時，就會呼叫 API。

---

## 2. 基本 API 網址

假設後端 API 網址是：

```txt
https://api.example.com
```

這個叫做 `Base URL`。

之後所有 API 都會接在這個網址後面。

例如：

```txt
https://api.example.com/auth/login
https://api.example.com/users/me
https://api.example.com/products
```

---

## 3. HTTP Method 是什麼？

前端呼叫 API 時，通常會使用不同的 HTTP Method。

| Method | 用途 |
| --- | --- |
| GET | 取得資料 |
| POST | 新增資料、登入、送出表單 |
| PUT | 更新整筆資料 |
| PATCH | 更新部分資料 |
| DELETE | 刪除資料 |

範例：

```txt
GET /products
```

意思是：取得商品列表。

```txt
POST /auth/login
```

意思是：送出登入資料。

---

## 4. 通用規則

### 4.1 Request 格式

前端送資料給後端時，通常使用 JSON。

Header 要帶：

```txt
Content-Type: application/json
```

如果需要登入驗證，還要帶：

```txt
Authorization: Bearer <token>
```

範例：

```txt
Authorization: Bearer abc123xyz
```

---

### 4.2 Response 格式

建議後端統一回傳格式。

成功：

```json
{
  "success": true,
  "data": {},
  "message": "成功"
}
```

失敗：

```json
{
  "success": false,
  "message": "錯誤訊息"
}
```

---

## 5. 登入 API

### 5.1 登入

#### API

```txt
POST /auth/login
```

#### 用途

使用者輸入帳號密碼後，前端呼叫這支 API 進行登入。

#### Request Body

```json
{
  "email": "test@example.com",
  "password": "12345678"
}
```

#### 欄位說明

| 欄位 | 型別 | 必填 | 說明 |
| --- | --- | --- | --- |
| email | string | 是 | 使用者 Email |
| password | string | 是 | 使用者密碼 |

#### 成功 Response

```json
{
  "success": true,
  "message": "登入成功",
  "data": {
    "token": "abc123xyz",
    "user": {
      "id": 1,
      "name": "王小明",
      "email": "test@example.com"
    }
  }
}
```

#### 失敗 Response

```json
{
  "success": false,
  "message": "帳號或密碼錯誤"
}
```

#### 前端要做什麼？

登入成功後：

1. 把 `token` 存起來
2. 之後需要登入的 API 都要帶 token
3. 跳轉到首頁或會員頁

範例：

```js
localStorage.setItem("token", result.data.token);
```

---

## 6. 取得目前登入使用者資料

### 6.1 取得個人資料

#### API

```txt
GET /users/me
```

#### 用途

取得目前登入者的個人資料。

#### Header

```txt
Authorization: Bearer <token>
```

#### 成功 Response

```json
{
  "success": true,
  "data": {
    "id": 1,
    "name": "王小明",
    "email": "test@example.com",
    "phone": "0912345678"
  }
}
```

#### 失敗 Response

```json
{
  "success": false,
  "message": "尚未登入"
}
```

#### 前端要做什麼？

如果成功，就把資料顯示在畫面上。

如果失敗，通常代表 token 過期或沒有登入，要導回登入頁。

---

## 7. 商品列表 API

### 7.1 取得商品列表

#### API

```txt
GET /products
```

#### 用途

取得商品列表。

#### Query Parameters

範例：

```txt
GET /products?page=1&limit=10&keyword=鞋子
```

#### 參數說明

| 參數 | 型別 | 必填 | 說明 |
| --- | --- | --- | --- |
| page | number | 否 | 第幾頁，預設 1 |
| limit | number | 否 | 一頁幾筆，預設 10 |
| keyword | string | 否 | 搜尋關鍵字 |

#### 成功 Response

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": 1,
        "name": "白色運動鞋",
        "price": 1200,
        "imageUrl": "https://example.com/shoe.jpg"
      }
    ],
    "pagination": {
      "page": 1,
      "limit": 10,
      "total": 25
    }
  }
}
```

---

## 8. 新增商品 API

### 8.1 新增商品

#### API

```txt
POST /products
```

#### Header

```txt
Authorization: Bearer <token>
Content-Type: application/json
```

#### Request Body

```json
{
  "name": "黑色外套",
  "price": 2500,
  "imageUrl": "https://example.com/coat.jpg"
}
```

#### 欄位說明

| 欄位 | 型別 | 必填 | 說明 |
| --- | --- | --- | --- |
| name | string | 是 | 商品名稱 |
| price | number | 是 | 商品價格 |
| imageUrl | string | 否 | 商品圖片網址 |

#### 成功 Response

```json
{
  "success": true,
  "message": "新增成功",
  "data": {
    "id": 2,
    "name": "黑色外套",
    "price": 2500,
    "imageUrl": "https://example.com/coat.jpg"
  }
}
```

---

## 9. 前端實際串接範例

### 9.1 使用 fetch 登入

```js
async function login(email, password) {
  const response = await fetch("https://api.example.com/auth/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      email: email,
      password: password
    })
  });

  const result = await response.json();

  if (result.success) {
    localStorage.setItem("token", result.data.token);
    alert("登入成功");
  } else {
    alert(result.message);
  }
}
```

---

### 9.2 呼叫需要登入的 API

```js
async function getMyProfile() {
  const token = localStorage.getItem("token");

  const response = await fetch("https://api.example.com/users/me", {
    method: "GET",
    headers: {
      "Authorization": `Bearer ${token}`
    }
  });

  const result = await response.json();

  if (result.success) {
    console.log(result.data);
  } else {
    alert(result.message);
  }
}
```

---

## 10. 建議前端統一封裝 API

可以建立一個 `api.js`，讓所有 API 呼叫都走同一個函式。

```js
const BASE_URL = "https://api.example.com";

export async function apiRequest(path, options = {}) {
  const token = localStorage.getItem("token");

  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers
    }
  });

  const result = await response.json();

  if (!response.ok) {
    throw new Error(result.message || "API 發生錯誤");
  }

  return result;
}
```

使用方式：

```js
const result = await apiRequest("/products", {
  method: "GET"
});
```

登入：

```js
const result = await apiRequest("/auth/login", {
  method: "POST",
  body: JSON.stringify({
    email: "test@example.com",
    password: "12345678"
  })
});
```

---

## 11. 常見錯誤碼

| 狀態碼 | 意思 | 前端處理方式 |
| --- | --- | --- |
| 200 | 成功 | 正常顯示資料 |
| 201 | 新增成功 | 顯示成功訊息 |
| 400 | 前端送的資料錯誤 | 顯示錯誤訊息 |
| 401 | 未登入或 token 錯誤 | 清除 token，導回登入頁 |
| 403 | 沒有權限 | 顯示無權限 |
| 404 | 找不到資料 | 顯示查無資料 |
| 500 | 後端錯誤 | 顯示系統錯誤，請稍後再試 |

---

## 12. 前端接 API 的基本流程

以登入為例：

1. 使用者輸入 email 和 password
2. 前端按下登入按鈕
3. 前端呼叫 `POST /auth/login`
4. 後端檢查帳密
5. 後端回傳 token
6. 前端儲存 token
7. 前端跳轉頁面

---

## 13. 第一次接 API 最常犯的錯

### 13.1 忘記 JSON.stringify

錯誤寫法：

```js
body: {
  email: "test@example.com",
  password: "12345678"
}
```

正確寫法：

```js
body: JSON.stringify({
  email: "test@example.com",
  password: "12345678"
})
```

---

### 13.2 忘記帶 Content-Type

如果送 JSON 給後端，通常要帶：

```js
headers: {
  "Content-Type": "application/json"
}
```

---

### 13.3 忘記帶 token

需要登入的 API 通常要帶：

```js
headers: {
  "Authorization": `Bearer ${token}`
}
```

---

### 13.4 沒有處理錯誤

不要只寫成功情境，也要處理失敗。

```js
if (result.success) {
  console.log("成功", result.data);
} else {
  alert(result.message);
}
```

---

## 14. 給新手的練習順序

建議先練習這四支 API：

```txt
POST /auth/login
GET /users/me
GET /products
POST /products
```

會接完這四支，就已經理解前端串 API 的核心流程了。

---

## 15. 新手檢查清單

串 API 前，請先確認：

- API 網址是否正確
- Method 是否正確
- Request Body 欄位名稱是否正確
- Request Body 型別是否正確
- 是否有加 `Content-Type: application/json`
- 需要登入的 API 是否有帶 `Authorization`
- 是否有處理成功狀態
- 是否有處理失敗狀態
- 是否有處理 `401` token 過期

---

## 16. 簡短總結

前端串 API 可以記成四件事：

1. 確認 API 網址
2. 確認 Method
3. 準備 Request
4. 處理 Response

只要這四件事做對，大部分 API 都能順利串起來。
