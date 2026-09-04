#!/usr/bin/env node
// Regression checks for the long-running makeup render path.
// The render service returns an image URL, then the browser must be able to
// fetch that URL with the same Gateway identity used for polling the job.

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(process.argv[2] || '.');
const api = fs.readFileSync(path.join(root, 'js', 'api.js'), 'utf8');
const router = fs.readFileSync(path.join(root, 'js', 'router.js'), 'utf8');
const flow = fs.readFileSync(path.join(root, 'js', 'makeup-flow.js'), 'utf8');

let rateLimitMessage = '';
try {
    const context = {
        window: {},
        sessionStorage: { getItem: () => null },
        localStorage: { removeItem: () => {} },
        URL,
    };
    vm.runInNewContext(api.slice(0, api.indexOf('const ApiConfig')), context);
    rateLimitMessage = context.window.localizeUserError(
        'Render rate limit exceeded. Try again in 530 seconds.',
        'RATE_LIMITED',
        429,
        { retryAfterSeconds: 530 },
    );
} catch (_) {
    rateLimitMessage = '';
}

const checks = [
    [
        '本機跨埠 Gateway 仍視為受保護網址',
        api.includes('this.config?.services?.aiGateway?.baseUrl')
            && api.includes('url.origin !== gatewayOrigin')
            && api.includes("'/render-service/'")
    ],
    [
        '本機渲染圖片網址會回到 8015 Gateway',
        api.includes('_qualifyRenderMediaUrl(value)')
            && api.includes('gatewayUrl.origin === window.location.origin')
            && api.includes('return new URL(raw, gatewayUrl.origin).href')
    ],
    [
        '渲染回應正規化後仍保留妝後圖網址',
        api.includes('_normalizeRenderJob(payload)')
            && api.includes("'afterImageUrl', 'after_image_url'")
            && api.includes('submitted = this._normalizeRenderJob')
            && api.includes('job = this._normalizeRenderJob')
    ],
    [
        '渲染限流錯誤會顯示中文等待時間',
        api.includes('_renderApiError(payload, status = 0')
            && api.includes('localizeUserError(raw, code, status, details)')
            && api.includes('retryAfterSeconds: Number(retryMatch[1])')
            && api.includes('throw this._renderApiError(submitted, submitRes.status')
            && rateLimitMessage === '操作次數過多，請在 9 分鐘後再試。'
    ],
    [
        '渲染成功會寫入資料包並由成果頁使用',
        router.includes('afterImageUrl: result.afterImageUrl')
            && flow.includes('const after = render.afterImageUrl')
            && flow.includes('<img id="lookPortrait" src="${escapeHtml(after)}"')
    ],
    [
        'Ollama 渲染 prompt 與簽章不會被 Journey 流程清掉',
        // 比對「有沒有讀這個欄位」，不比對整行的排版——這條守的是
        // 「prompt 與簽章不能被寫成 null」，不是那一行怎麼換行。
        flow.includes('response?.renderPromptEn')
            && flow.includes('promptSignatureVersion: response?.promptSignatureVersion || null')
            && !flow.includes('renderPromptEn: null,\n                    ollamaRenderPromptEn: null')
    ],
    [
        '渲染請求會帶已簽的 Ollama prompt，避免重叫 Ollama',
        router.includes('const generativeText = pkg?.generativeText || {}')
            && router.includes('ollamaRenderPromptEn: signedPromptReady ? generativeText.ollamaRenderPromptEn : null')
            && router.includes('promptSignatureVersion: signedPromptReady ? generativeText.promptSignatureVersion : null')
    ],
    [
        '重新整理後會還原含妝後圖的分析草稿',
        router.includes('function restoreAnalysisDraft()')
            && router.includes('const raw = draft.analysis?.[mode]')
            && router.includes('restoreAnalysisDraft();')
    ]
];

let failed = 0;
for (const [label, ok] of checks) {
    if (ok) console.log(`PASS ${label}`);
    else {
        failed += 1;
        console.error(`FAIL ${label}`);
    }
}

console.log(`${checks.length - failed}/${checks.length} passed`);
process.exitCode = failed ? 1 : 0;
