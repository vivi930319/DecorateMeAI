// Copy to config.local.js for local development only.
// This file is downloaded by the browser: never put secrets in it.
window.DECORATE_ME_CONFIG = {
    // Leave empty to use Firebase Hosting rewrites. For local Gateway testing,
    // use http://127.0.0.1:8015.
    gatewayUrl: '',
    // Product image/data URL is public routing information, not a secret.
    productUrl: '',
    crawlerUrl: '',
    allowInsecureOtpBypass: false,
    adminDemoEnabled: true,
    adminDemoExpiresAt: '2026-12-31T23:59:59+08:00'
};
