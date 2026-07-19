// Public service locations only. Keep API keys and other credentials out of this file.
window.DECORATE_ME_CONFIG = Object.assign(window.DECORATE_ME_CONFIG || {}, {
    memberDatabaseUrl: 'https://yen-minute-from-ict.trycloudflare.com',
    productUrl: 'https://yen-minute-from-ict.trycloudflare.com',
    // 臉部分析／渲染改走 AI Gateway：長期金鑰留在 Gateway，瀏覽器只帶登入後的短期 session。
    aiGatewayUrl: 'https://ai-gateway-eu5pq7c53a-de.a.run.app'
});
