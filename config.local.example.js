// 複製這個檔案成 config.local.js。瀏覽器端只可保存公開、非敏感的 UI 開關；
// 上游網址與 API 金鑰全部設定在 Gateway／Secret Manager，不可放進此檔。
// `allowInsecureOtpBypass` 已於 2026-07-24 移除。它讓「驗證碼長度 ≥ 4」就通過，
// 但那從來不是防護——旗標是瀏覽器端的值，devtools 一行就能打開，而攻擊者也不必
// 經過這個前端。OTP 的閘門只能在會員資料庫端（追蹤編號 S7）。
window.DECORATE_ME_CONFIG = {};
