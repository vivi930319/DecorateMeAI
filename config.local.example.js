// 複製這個檔案成 config.local.js 後填入實際值。config.local.js 不進版控（含 API 金鑰）。
// Cloudflare Tunnel 網址組員每次重啟就會換，換了就改這裡、存檔、重新整理網頁即可。
window.DECORATE_ME_CONFIG = {
    faceBasicUrl:      'https://face-basic-<專案編號>.asia-east1.run.app',
    faceProUrl:        'https://face-pro-<專案編號>.asia-east1.run.app',
    faceApiKey:        '<face 服務的 X-API-Key，需與 Cloud Run 環境變數 FACE_API_KEY 一致>',
    memberDatabaseUrl: 'https://<會員資料庫的-cloudflare-tunnel>.trycloudflare.com',
    productUrl:        'https://<商品服務的-cloudflare-tunnel>.trycloudflare.com',
    renderUrl:         'https://replicate-render-<專案編號>.asia-east1.run.app',
    renderApiKey:      '<render 服務的 X-API-Key，需與 Cloud Run 環境變數 RENDER_API_KEY 一致>',
    textSuggestionUrl: 'https://<Ollama建議服務的-cloudflare-tunnel>.trycloudflare.com',
    textSuggestionApiKey: '<Ollama 建議服務的 X-API-Key>',
    // 只在純本機 demo、且你明確接受假 OTP 風險時才設 true；預設應維持 false/省略。
    allowInsecureOtpBypass: false
};
