// 瀏覽器只認得 Firebase Hosting 的同源 Gateway 路徑。
// 會員、商品、爬蟲與模型服務的實際上游網址只設定在 ai-gateway Cloud Run，
// 不再發布到前端，也不保留 Quick Tunnel fallback。
window.DECORATE_ME_CONFIG = Object.assign(window.DECORATE_ME_CONFIG || {}, {
    aiGatewayUrl: ''
});
