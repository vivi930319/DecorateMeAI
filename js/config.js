// 部署時可覆蓋這些公開設定，不必修改主要程式。
window.DECORATE_ME_CONFIG = window.DECORATE_ME_CONFIG || {};

// 這裡只能放公開開關，禁止放 API 金鑰、權杖或密碼。
// 目前沒有任何功能開關——專題展示區塊已於 2026-08-23 移除，
// 它的 adminDemoEnabled / adminDemoExpiresAt 也一併清掉了。
window.DECORATE_ME_FEATURES = Object.assign({}, window.DECORATE_ME_FEATURES || {});
