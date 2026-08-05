# Decorate Me 專案修改紀錄

最後更新：2026-07-08

## 本輪已完成

- 前端 `web_frontend/js/router.js`
  - 登入後不再用白名單 email 或前端 fallback 覆寫 `role` / `level`
  - `doRegisterAction()` 在 `register` 或 `sendOTP` 任一步失敗時，直接顯示錯誤並中止，不再錯誤進入 OTP 畫面
  - 個人頁不再用前端 demo 付款或本機升級申請來開通 PRO / VIP；頁面改成只顯示後端回傳結果
  - 渲染次數提示改為「由後端判定」，不再用前端 localStorage 次數當真實權限依據

- 前端 `web_frontend/js/api.js`
  - `AdminStore.isAdminProfile()` 現在只信任後端回傳的 `role === 'admin'` 或 `level === '管理員'`
  - `AdminStore` 不再從 localStorage 發放 `allowedPages` / `vipRequested` / render 次數
  - `canUseProAnalysis()`、`canAccess()`、`canRender()` 改為讀取後端回傳的 `role` / `level` / `status` / `allowedPages`
  - `Api.renderMakeup()` 送出渲染請求時會附帶目前登入會員的 `X-User-Email` / `X-User-Role` 作為後端紀錄輔助資訊
  - `ProSubscription.purchase()` demo 開通已停用，避免前端自行升級會員等級
  - `fetchAdminMembers()` 已切回正式 `credentials:'include'` 模式；後台會員清單現在依賴 admin session cookie，不再走公開讀取模式

- 後端 `replicate_render_api.py`
  - `/render` 既有 `X-API-Key` 之外，再加伺服器端限流
  - 預設使用固定時間窗限制：
    - `RENDER_RATE_LIMIT_WINDOW_SECONDS=3600`
    - `RENDER_RATE_LIMIT_MAX_REQUESTS=10`
  - 超量時回 `429 RATE_LIMITED`
  - `/health` 新增 rate limit 設定資訊

- 文件 / contract
  - `MEMBER_DATABASE_INTEGRATION_SPEC.md` 已補 members 權限欄位 contract、`GET /api/members` / `PATCH /api/members/{email}` 回應格式、CORS / session 要求、admin 驗收清單
  - `00_資料庫整合_請先讀我_READ_FIRST.md` 已同步更新優先順序與待決策項目（`vipRequested`、`renderQuota`、停權規則）

## 仍待後端/產品決策

- 若要做真正的「會員綁定配額」，需要會員資料庫或 render service 能驗證不可偽造的會員身分；目前這輪先落地 IP 為主的 server-side 限流
- 若後端之後提供 `renderQuota`、`vipRequested`、更完整 `allowedPages`，前端目前已可直接顯示，不需要再回頭做 localStorage fallback
- 前端 `fetchAdminMembers()` 已改成 `credentials:'include'`；若後端仍讀不到 cookie，需優先檢查 members API 的 CORS 與 session 設定
- `GET /api/members` 後端需確認：
  - 只有 admin session 可讀
  - `Access-Control-Allow-Credentials: true`
  - `Access-Control-Allow-Origin` 不能是 `*`，必須是前端實際網域
  - session cookie 需可跨站送出（通常 `SameSite=None; Secure`）

## 版本控制說明

- 後端工作區：`PythonProject12` 是 Git repo
- 前端工作區：`C:\Users\isach\OneDrive\桌面\web_frontend` 是獨立 Git repo，不是後端 repo 的子目錄
