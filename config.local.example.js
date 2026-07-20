// 複製這個檔案成 config.local.js。瀏覽器端只可保存公開、非敏感的 UI 開關；
// 上游網址與 API 金鑰全部設定在 Gateway／Secret Manager，不可放進此檔。
window.DECORATE_ME_CONFIG = {
    allowInsecureOtpBypass: false
};
