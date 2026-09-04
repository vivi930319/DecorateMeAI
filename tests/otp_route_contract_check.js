// OTP 路由契約：註冊重寄的錯誤要看得見，忘記密碼要經 Gateway 隔離。
//
// 這支橫跨兩個 repo。後端在同一個 GitHub repo 的另一個分支（Isa），本機是隔壁
// 目錄 PythonProject12，但 CI 只 checkout 前端這個分支——所以原本直接
// readFileSync 隔壁 repo 的那一行在 CI 一定 ENOENT，整份 workflow 掛掉。
//
// 缺席時跳過那兩條，但**要吵**。 靜默跳過就變成「有寫測試、但沒有在跑」，
// 而那正是這個 workflow 存在的理由；印一行說清楚少驗了什麼，看 log 的人才知道
// CI 的綠燈涵蓋到哪裡。前端自己的斷言在哪裡都照跑。
const fs = require('fs'), assert = require('assert/strict'), path = require('path');
const api = fs.readFileSync(path.join(__dirname, '../js/api.js'), 'utf8');
const router = fs.readFileSync(path.join(__dirname, '../js/router.js'), 'utf8');

assert(api.includes("forgotPasswordPath: '/auth/forgot-password'"));
assert(/sendForgotPasswordOTP[\s\S]*forgotPasswordPath/.test(api));
assert(/sendForgotOTP[\s\S]{0,300}sendForgotPasswordOTP/.test(router));
assert(/resendForgotOTP[\s\S]{0,220}sendForgotPasswordOTP/.test(router));
assert(!/resendOTP[\s\S]{0,180}catch \(_\) \{\}/.test(router));
assert(router.includes('目前沒有待驗證的註冊資料'));

const gatewayPath = path.join(__dirname, '../../PythonProject12/gateway/ai_gateway.py');
if (fs.existsSync(gatewayPath)) {
    const gateway = fs.readFileSync(gatewayPath, 'utf8');
    assert(gateway.includes('@app.post("/auth/forgot-password")'));
    assert(gateway.includes('proxy_public_member_request(request, "/api/forgot-password")'));
    console.log('PASS OTP routes: registration resend errors visible; forgot-password isolated through Gateway');
} else {
    console.log('PASS OTP routes: registration resend errors visible (frontend side only)');
    console.log('  SKIP Gateway 端兩條斷言：找不到 ../../PythonProject12/gateway/ai_gateway.py。');
    console.log('       後端在同一 repo 的 Isa 分支，CI 只 checkout 這一個分支，所以「前端打的');
    console.log('       路由後端真的有」只有在兩個 repo 並排的開發機上驗得到。');
}
