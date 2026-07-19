// Public service locations only. Keep API keys and other credentials out of this file.
window.DECORATE_ME_CONFIG = Object.assign(window.DECORATE_ME_CONFIG || {}, {
    memberDatabaseUrl: 'https://yen-minute-from-ict.trycloudflare.com',
    productUrl: 'https://yen-minute-from-ict.trycloudflare.com'
    // aiGatewayUrl 刻意留空：firebase.json 的 rewrites 已把 /auth、/face-basic、/face-pro 等
    // 路徑導到 ai-gateway，走同源即可，不需要也不應該寫死 Gateway 網址。
});
