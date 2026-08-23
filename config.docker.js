// 容器版的本機設定。Dockerfile 會把這份 COPY 成容器內的 config.local.js。
//
// 為什麼只設 localGatewayPort 一個值：
// js/api.js:19 的 _defaultGatewayUrl() 決定 gateway 位址的順序是
//   1. RuntimeApiConfig.aiGatewayUrl（非空才採用）
//   2. hostname 是 localhost/127.0.0.1 → http://localhost:{localGatewayPort || 8015}
//   3. 其餘 → ''（同源）
//
// 而 js/service-endpoints.js 會在這份檔案之後用 Object.assign 把 aiGatewayUrl 覆寫成
// 空字串，所以在這裡設 aiGatewayUrl 是沒有用的——會被蓋掉，然後落到第 2 條。
// 既然一定會走第 2 條，就把埠指向 nginx 自己（8080），讓 gateway 路徑變成同源請求，
// 由 nginx.conf 的 proxy_pass 接手。這樣不必動 js/api.js 一行程式碼。
window.DECORATE_ME_CONFIG = Object.assign(window.DECORATE_ME_CONFIG || {}, {
    localGatewayPort: 8080,

    // 以下三個是「不經過 gateway」的直連服務。前端某些路徑會直接讀它們，
    // 留空代表該功能在容器內不可用（不會是錯誤，只是不啟用）。
    // 要用的話從組員拿到當次的 Cloudflare Tunnel 網址填進來。
    memberDatabaseUrl: '',
    productUrl: '',

    // OTP 驗證碼的本機繞道。永遠保持 false：這個旗標若在任何非本機環境為 true，
    // 等於註冊流程不必驗證信箱。
    allowInsecureOtpBypass: false
});
