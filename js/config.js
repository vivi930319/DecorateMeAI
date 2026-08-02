// 部署時可覆蓋這些公開設定，不必修改主要程式。
window.DECORATE_ME_CONFIG = window.DECORATE_ME_CONFIG || {};

// 這裡只能放公開開關，禁止放 API 金鑰、權杖或密碼。
// 管理展示功能可手動關閉，也會在設定時間後自動失效。
window.DECORATE_ME_FEATURES = Object.assign({
    adminDemoEnabled: true,
    adminDemoExpiresAt: '2026-12-31T23:59:59+08:00'
}, window.DECORATE_ME_FEATURES || {});
