// 瀏覽器只呼叫 Firebase Hosting 的同源 Gateway。
// 真實服務網址保留在 Cloud Run，避免暴露在前端。
window.DECORATE_ME_CONFIG = Object.assign(window.DECORATE_ME_CONFIG || {}, {
    aiGatewayUrl: ''
});
