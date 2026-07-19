// Override these values in the deployed frontend without changing application code.
window.DECORATE_ME_CONFIG = window.DECORATE_ME_CONFIG || {};

// Public runtime switches only. Never place API keys, tokens, or passwords here.
// 專題展示面板：專題結束後把 adminDemoEnabled 改成 false，或讓 adminDemoExpiresAt 到期即可自動關閉。
window.DECORATE_ME_FEATURES = Object.assign({
    adminDemoEnabled: true,
    adminDemoExpiresAt: '2026-12-31T23:59:59+08:00'
}, window.DECORATE_ME_FEATURES || {});
