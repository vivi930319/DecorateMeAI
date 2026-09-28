// 妝容建議頁的「分享到 IG／Threads」。
//
// 分享的是**圖片本身**，不是網址：妝後圖要登入並驗證身分才看得到，別人點網址只會看到登入頁。
// 所以在前端把妝前／妝後重新畫成一張分享圖，兩種格式：
//   · IG 限時動態 9:16（1080×1920，預設）——上下各留 250px 給 IG 的介面，不放重要內容。
//   · 貼文 4:5（1080×1350）——IG 貼文與 Threads 都用這個比例。
// 再交給：
//   · 手機：系統分享面板（navigator.share 帶檔案）。選 Instagram 之後 IG 會讓你選「限時動態／貼文」；
//     Threads 也在同一個面板裡。
//   · 電腦：下載圖片＋複製文案，另給一顆直接開 Threads 發文的按鈕（Threads 的網址只能帶文字）。
// 網頁**不能**直接打開 IG 的限時動態編輯畫面：IG 的 instagram-stories:// 只開放給手機 App
// （要 Facebook App ID），網頁叫不到。這是平台限制，不是沒做。
//
// 妝後圖來自 GCS 簽名網址，能畫進 canvas 靠的是 decorate-me-renders 的 CORS 設定（2026-09-28 加）。
// 妝前是使用者的素顏照，預設放進分享圖（使用者確認過），但一定讓他能取消。
(function (window, document) {
    'use strict';

    const FORMATS = {
        story: { w: 1080, h: 1920, label: 'IG 限時動態', ratio: '9:16' },
        post: { w: 1080, h: 1350, label: 'IG 貼文／Threads', ratio: '4:5' },
    };
    // 「港風」→「港風妝」；英文名（Soft Baddie）不加「妝」，讀起來才自然
    const lookName = n => (/[A-Za-z]\s*$/.test(n) || /妝$/.test(n) ? n : `${n}妝`);
    const SITE = 'decorate-me.web.app';
    const THREADS_INTENT = 'https://www.threads.net/intent/post?text=';

    function loadImage(src) {
        return new Promise((resolve, reject) => {
            if (!src) { reject(new Error('沒有圖片')); return; }
            const im = new Image();
            if (!/^data:|^blob:/.test(src)) im.crossOrigin = 'anonymous';
            im.onload = () => resolve(im);
            im.onerror = () => reject(new Error('圖片讀取失敗'));
            im.src = src;
        });
    }
    function roundRect(ctx, x, y, w, h, r) {
        ctx.beginPath();
        ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
    }
    // 以 cover 方式把圖放進框，靠上對齊（臉在上半部）
    function drawCover(ctx, im, x, y, w, h, radius) {
        const s = Math.max(w / im.naturalWidth, h / im.naturalHeight);
        const dw = im.naturalWidth * s, dh = im.naturalHeight * s;
        ctx.save();
        roundRect(ctx, x, y, w, h, radius); ctx.clip();
        ctx.drawImage(im, x + (w - dw) / 2, y, dw, dh);
        ctx.restore();
    }
    function pill(ctx, text, cx, cy, bg, fg, font) {
        ctx.font = font; const tw = ctx.measureText(text).width, pw = tw + 44, ph = 52;
        ctx.fillStyle = bg; roundRect(ctx, cx - pw / 2, cy - ph / 2, pw, ph, ph / 2); ctx.fill();
        ctx.fillStyle = fg; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, cx, cy + 1);
    }

    async function composeCard({ before, after, styleName, withBefore, format = 'story' }) {
        const F = FORMATS[format] || FORMATS.story;
        const W = F.w, H = F.h, story = format === 'story';
        const canvas = document.createElement('canvas');
        canvas.width = W; canvas.height = H;
        const ctx = canvas.getContext('2d');
        const serif = '"Noto Serif TC", "Playfair Display", serif', sans = '"Noto Sans TC", "Jost", sans-serif';
        if (document.fonts && document.fonts.ready) { try { await document.fonts.ready; } catch (_) {} }

        // 背景：品牌的奶茶玫瑰色
        const bg = ctx.createLinearGradient(0, 0, W, H);
        bg.addColorStop(0, '#F7ECE8'); bg.addColorStop(1, '#EBD3CC');
        ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);

        // 版面：限時動態上下各留 250px 給 IG 的頭像列與回覆框
        const headY = story ? 260 : 58;
        const top = story ? 420 : 196;
        const photoH = story ? 1140 : 920;
        const nameY = top + photoH + (story ? 120 : 104);

        // 頂部：LOGO＋品牌名
        try {
            const logo = await loadImage('assets/brand/decorate-me-logo.png');
            ctx.drawImage(logo, 72, headY, 96, 96);
        } catch (_) {}
        ctx.fillStyle = '#4A3438'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
        ctx.font = `500 44px ${serif}`; ctx.fillText('妝識你的美', 188, headY + 52);
        ctx.fillStyle = '#A4675A'; ctx.font = `500 20px ${sans}`;
        ctx.fillText('D E C O R A T E   M E', 190, headY + 86);

        // 照片區
        const afterIm = await loadImage(after);
        if (withBefore && before) {
            let beforeIm = null;
            try { beforeIm = await loadImage(before); } catch (_) {}
            if (beforeIm) {
                const gap = 24, pw = (W - 72 * 2 - gap) / 2;
                drawCover(ctx, beforeIm, 72, top, pw, photoH, 28);
                drawCover(ctx, afterIm, 72 + pw + gap, top, pw, photoH, 28);
                pill(ctx, '妝前', 72 + pw / 2, top + photoH - 52, 'rgba(255,255,255,.88)', '#4A3438', `500 26px ${sans}`);
                pill(ctx, '妝後', 72 + pw + gap + pw / 2, top + photoH - 52, '#A4675A', '#FFFFFF', `500 26px ${sans}`);
            } else {
                drawCover(ctx, afterIm, 72, top, W - 144, photoH, 28);
            }
        } else {
            drawCover(ctx, afterIm, 72, top, W - 144, photoH, 28);
            pill(ctx, '妝後', W / 2, top + photoH - 52, '#A4675A', '#FFFFFF', `500 26px ${sans}`);
        }

        // 妝容名稱與網址
        ctx.textAlign = 'center'; ctx.fillStyle = '#4A3438';
        ctx.font = `500 ${story ? 64 : 56}px ${serif}`; ctx.fillText(lookName(styleName), W / 2, nameY);
        ctx.fillStyle = '#A4675A'; ctx.font = `400 ${story ? 28 : 26}px ${sans}`;
        ctx.fillText(`✦ 用臉部分析試妝 · ${SITE}`, W / 2, nameY + (story ? 56 : 48));

        return new Promise((resolve, reject) => canvas.toBlob(b => (b ? resolve(b) : reject(new Error('無法產生圖片'))), 'image/jpeg', 0.92));
    }

    const defaultCaption = styleName => `我在 Decorate Me 試了${lookName(styleName)} ✦ ${SITE}`;

    function open({ before, after, styleName }) {
        document.getElementById('lookShareModal')?.remove();
        const modal = document.createElement('div');
        modal.id = 'lookShareModal';
        modal.className = 'makeup-style-modal open';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-labelledby', 'lookShareTitle');
        const canNativeShare = !!(navigator.share && navigator.canShare);
        let format = 'story';
        modal.innerHTML = `<div class="makeup-style-dialog look-share-dialog">
            <div class="makeup-style-head">
                <div><span class="eyebrow">Share</span><h2 id="lookShareTitle">分享到 IG／Threads</h2>
                <p>分享的是這張圖片本身；別人不需要登入就看得到。</p></div>
                <button class="makeup-style-close" type="button" aria-label="關閉">×</button>
            </div>
            <div class="look-share-formats" role="radiogroup" aria-label="分享格式">
                ${Object.entries(FORMATS).map(([k, f]) => `<button type="button" class="chip${k === format ? ' active' : ''}" role="radio"
                    aria-checked="${k === format}" data-format="${k}">${f.label} <small>${f.ratio}</small></button>`).join('')}
            </div>
            <div class="look-share-body">
                <div class="look-share-preview" data-preview><div class="look-share-loading">正在產生分享圖…</div></div>
                <div class="look-share-side">
                    ${before ? `<label class="look-share-opt"><input type="checkbox" data-with-before checked>
                        <span>放入妝前照片<small>妝前是你的素顏照，取消勾選就只分享妝後。</small></span></label>` : ''}
                    <label class="look-share-caption"><span>文案</span>
                        <textarea rows="3" data-caption>${escapeHtml(defaultCaption(styleName))}</textarea></label>
                    <div class="look-share-actions">
                        ${canNativeShare ? '<button type="button" class="btn-gold" data-native></button>' : ''}
                        <button type="button" class="${canNativeShare ? 'btn-outline' : 'btn-gold'}" data-download>下載圖片</button>
                        <button type="button" class="btn-outline" data-copy>複製文案</button>
                        <a class="btn-outline" data-threads target="_blank" rel="noopener">開啟 Threads 發文</a>
                    </div>
                    <p class="look-share-note" data-note></p>
                </div>
            </div>
        </div>`;
        document.body.appendChild(modal);

        const close = () => modal.remove();
        modal.querySelector('.makeup-style-close').onclick = close;
        modal.onclick = e => { if (e.target === modal) close(); };
        const preview = modal.querySelector('[data-preview]');
        const captionEl = modal.querySelector('[data-caption]');
        const withBeforeEl = modal.querySelector('[data-with-before]');
        const threadsEl = modal.querySelector('[data-threads]');
        const nativeBtn = modal.querySelector('[data-native]');
        const noteEl = modal.querySelector('[data-note]');
        const setThreads = () => { threadsEl.href = THREADS_INTENT + encodeURIComponent(captionEl.value); };
        setThreads();
        captionEl.addEventListener('input', setThreads);

        // 依格式換說明：限時動態要講「選 Instagram → 限時動態」，而且文案要自己貼（IG 不吃分享過來的文字）
        const syncCopy = () => {
            preview.classList.toggle('is-story', format === 'story');
            if (nativeBtn) nativeBtn.textContent = format === 'story' ? '分享到 IG 限時動態…' : '分享到 IG 貼文／Threads…';
            noteEl.textContent = format === 'story'
                ? (canNativeShare
                    ? '按「分享到 IG 限時動態…」→ 選 Instagram →「限時動態」。IG 不會帶入文字，想加文案請先按「複製文案」再到限時動態貼上。'
                    : 'Instagram 不能從網頁直接開啟限時動態：請下載圖片，到 IG 限時動態從相簿選這張。')
                : (canNativeShare
                    ? '按「分享到 IG 貼文／Threads…」後選 Instagram 或 Threads，圖片會一起帶過去。'
                    : 'Instagram 不能從網頁直接發文：請先下載圖片再到 IG 上傳。Threads 的發文連結只能帶文字，圖片要自己加。');
        };

        let blob = null, url = '', token = 0;
        const build = async () => {
            const my = ++token;
            preview.innerHTML = '<div class="look-share-loading">正在產生分享圖…</div>';
            modal.querySelectorAll('[data-native],[data-download]').forEach(b => { b.disabled = true; });
            try {
                const b = await composeCard({ before, after, styleName, format, withBefore: withBeforeEl ? withBeforeEl.checked : false });
                if (my !== token) return;
                blob = b;
                if (url) URL.revokeObjectURL(url);
                url = URL.createObjectURL(b);
                preview.innerHTML = `<img src="${url}" alt="分享圖預覽">`;
                modal.querySelectorAll('[data-native],[data-download]').forEach(x => { x.disabled = false; });
            } catch (err) {
                if (my !== token) return;
                preview.innerHTML = `<div class="look-share-loading">分享圖產生失敗：${escapeHtml(err.message || '')}。可以改用截圖分享。</div>`;
            }
        };
        modal.querySelectorAll('[data-format]').forEach(btn => btn.onclick = () => {
            format = btn.dataset.format;
            modal.querySelectorAll('[data-format]').forEach(b => { b.classList.toggle('active', b === btn); b.setAttribute('aria-checked', String(b === btn)); });
            syncCopy(); build();
        });
        if (withBeforeEl) withBeforeEl.addEventListener('change', build);
        syncCopy();
        build();

        const fileName = () => `decorate-me-${styleName}-${format === 'story' ? 'story' : 'post'}.jpg`;
        if (nativeBtn) nativeBtn.onclick = async () => {
            if (!blob) return;
            const file = new File([blob], fileName(), { type: 'image/jpeg' });
            // 限時動態不帶文字：有些系統會把文字當成主要內容，IG 就改開成訊息而不是限動
            const data = format === 'story'
                ? { files: [file] }
                : { files: [file], text: captionEl.value, title: 'Decorate Me' };
            try {
                if (navigator.canShare(data)) await navigator.share(data);
                else await navigator.share({ text: captionEl.value, url: `https://${SITE}` });
            } catch (err) {
                // 使用者自己取消分享面板不算錯誤
                if (err && err.name !== 'AbortError') showToast('這台裝置無法直接分享，請改用下載圖片');
            }
        };
        modal.querySelector('[data-download]').onclick = () => {
            if (!url) return;
            const a = document.createElement('a');
            a.href = url; a.download = fileName();
            document.body.appendChild(a); a.click(); a.remove();
        };
        modal.querySelector('[data-copy]').onclick = async () => {
            try { await navigator.clipboard.writeText(captionEl.value); showToast('已複製文案'); }
            catch (_) { captionEl.select(); showToast('請長按文案手動複製'); }
        };
    }

    window.LookShare = { open, composeCard, defaultCaption, FORMATS };
})(window, document);
