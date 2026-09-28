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

    // 化妝包外框（2026-09-28 使用者要求分享圖用化妝包的外框）：
    // 提把、拉鍊（愛心拉鍊頭）、菱格車線、圓弧包身，照片與文字都裝在包裡。
    function drawBagFrame(ctx, W, H, P) {
        const { x0, y0, x1, y1 } = P, w = x1 - x0, h = y1 - y0;
        // 包外的背景：比包身深一階
        const bg = ctx.createLinearGradient(0, 0, W, H);
        bg.addColorStop(0, '#E9CFC8'); bg.addColorStop(1, '#D9B3AA');
        ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
        // 提把
        ctx.save();
        ctx.lineWidth = 26; ctx.lineCap = 'round'; ctx.strokeStyle = '#B97A6C';
        const hr = P.handle || w * 0.17;
        ctx.beginPath(); ctx.arc(W / 2, y0 + 8, hr, Math.PI, 0); ctx.stroke();
        ctx.lineWidth = 8; ctx.strokeStyle = 'rgba(255,255,255,.45)';
        ctx.beginPath(); ctx.arc(W / 2, y0 + 8, hr - 6, Math.PI * 1.1, Math.PI * 1.45); ctx.stroke();
        ctx.restore();
        // 包身（上方圓角小、下方圓角大，像化妝包）
        const rt = 56, rb = 110;
        const body = () => {
            ctx.beginPath();
            ctx.moveTo(x0 + rt, y0); ctx.lineTo(x1 - rt, y0); ctx.quadraticCurveTo(x1, y0, x1, y0 + rt);
            ctx.lineTo(x1, y1 - rb); ctx.quadraticCurveTo(x1, y1, x1 - rb, y1);
            ctx.lineTo(x0 + rb, y1); ctx.quadraticCurveTo(x0, y1, x0, y1 - rb);
            ctx.lineTo(x0, y0 + rt); ctx.quadraticCurveTo(x0, y0, x0 + rt, y0); ctx.closePath();
        };
        ctx.save();
        ctx.shadowColor = 'rgba(90,40,40,.28)'; ctx.shadowBlur = 40; ctx.shadowOffsetY = 18;
        const fill = ctx.createLinearGradient(0, y0, 0, y1);
        fill.addColorStop(0, '#FBF1EE'); fill.addColorStop(1, '#F3DDD7');
        ctx.fillStyle = fill; body(); ctx.fill();
        ctx.restore();
        // 菱格車線（虛線）
        ctx.save(); body(); ctx.clip();
        ctx.strokeStyle = 'rgba(185,122,108,.22)'; ctx.lineWidth = 2; ctx.setLineDash([10, 9]);
        for (let d = -h; d < w + h; d += 64) {
            ctx.beginPath(); ctx.moveTo(x0 + d, y0); ctx.lineTo(x0 + d + h, y1); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(x0 + d, y1); ctx.lineTo(x0 + d + h, y0); ctx.stroke();
        }
        ctx.restore();
        // 包身描邊
        ctx.save(); ctx.lineWidth = 6; ctx.strokeStyle = '#B97A6C'; body(); ctx.stroke(); ctx.restore();
        // 拉鍊：一條鋸齒帶＋愛心拉鍊頭
        const zy = y0 + 44, zx0 = x0 + 44, zx1 = x1 - 44;
        ctx.save();
        ctx.fillStyle = '#E8C4B4'; roundRect(ctx, zx0, zy - 9, zx1 - zx0, 18, 9); ctx.fill();
        ctx.fillStyle = '#A4675A';
        for (let x = zx0 + 6; x < zx1 - 6; x += 12) ctx.fillRect(x, zy - 6, 5, 12);
        const px = zx1 - 30;
        ctx.fillStyle = '#A4675A'; roundRect(ctx, px - 14, zy - 12, 28, 46, 10); ctx.fill();
        ctx.fillStyle = '#F7E3DC'; ctx.font = '600 22px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText('♥', px, zy + 14);
        ctx.restore();
    }

    async function composeCard({ before, after, styleName, withBefore, format = 'story' }) {
        const F = FORMATS[format] || FORMATS.story;
        const W = F.w, H = F.h, story = format === 'story';
        const canvas = document.createElement('canvas');
        canvas.width = W; canvas.height = H;
        const ctx = canvas.getContext('2d');
        const serif = '"Noto Serif TC", "Playfair Display", serif', sans = '"Noto Sans TC", "Jost", sans-serif';
        if (document.fonts && document.fonts.ready) { try { await document.fonts.ready; } catch (_) {} }

        // 版面：限時動態上下各約 250px 留給 IG 的頭像列與回覆框（提把可以伸進去，內容不行）
        const P = story ? { x0: 50, y0: 330, x1: 1030, y1: 1690, handle: 166 } : { x0: 36, y0: 150, x1: 1044, y1: 1322, handle: 112 };
        drawBagFrame(ctx, W, H, P);
        const m = 52, cx0 = P.x0 + m, cx1 = P.x1 - m;
        const headY = P.y0 + 84;
        const top = headY + 130;
        const photoH = story ? 900 : 740;
        const nameY = top + photoH + (story ? 110 : 92);

        // 包裡頂部：LOGO＋品牌名
        try {
            const logo = await loadImage('assets/brand/decorate-me-logo.png');
            ctx.drawImage(logo, cx0, headY, 96, 96);
        } catch (_) {}
        ctx.fillStyle = '#4A3438'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
        ctx.font = `500 44px ${serif}`; ctx.fillText('妝識你的美', cx0 + 116, headY + 52);
        ctx.fillStyle = '#A4675A'; ctx.font = `500 20px ${sans}`;
        ctx.fillText('D E C O R A T E   M E', cx0 + 118, headY + 86);

        // 照片區
        const afterIm = await loadImage(after);
        const areaW = cx1 - cx0;
        if (withBefore && before) {
            let beforeIm = null;
            try { beforeIm = await loadImage(before); } catch (_) {}
            if (beforeIm) {
                const gap = 22, pw = (areaW - gap) / 2;
                drawCover(ctx, beforeIm, cx0, top, pw, photoH, 26);
                drawCover(ctx, afterIm, cx0 + pw + gap, top, pw, photoH, 26);
                pill(ctx, '妝前', cx0 + pw / 2, top + photoH - 50, 'rgba(255,255,255,.9)', '#4A3438', `500 26px ${sans}`);
                pill(ctx, '妝後', cx0 + pw + gap + pw / 2, top + photoH - 50, '#A4675A', '#FFFFFF', `500 26px ${sans}`);
            } else {
                drawCover(ctx, afterIm, cx0, top, areaW, photoH, 26);
            }
        } else {
            drawCover(ctx, afterIm, cx0, top, areaW, photoH, 26);
            pill(ctx, '妝後', W / 2, top + photoH - 50, '#A4675A', '#FFFFFF', `500 26px ${sans}`);
        }

        // 妝容名稱與網址（網址照印在圖上：沒加連結貼紙的人也找得到）
        ctx.textAlign = 'center'; ctx.fillStyle = '#4A3438';
        ctx.font = `500 ${story ? 64 : 54}px ${serif}`; ctx.fillText(lookName(styleName), W / 2, nameY);
        ctx.fillStyle = '#A4675A'; ctx.font = `400 ${story ? 28 : 25}px ${sans}`;
        ctx.fillText(`✦ 你也來試試 · ${SITE}`, W / 2, nameY + (story ? 54 : 44));

        return new Promise((resolve, reject) => canvas.toBlob(b => (b ? resolve(b) : reject(new Error('無法產生圖片'))), 'image/jpeg', 0.92));
    }

    // 分享連結（2026-09-28）：點進來的人會在登入頁看到「朋友試了○○妝」與「訪客直接試」，
    // 而且那款妝會預選好（見 router.js 的 shareLandingHtml）。src 分辨是從哪個平台點進來的。
    const shareUrl = (styleId, src) => {
        const q = new URLSearchParams({ ref: 'share', src });
        if (styleId) q.set('look', styleId);
        return `https://${SITE}/?${q}`;
    };
    const defaultCaption = (styleName, link = `https://${SITE}`) =>
        `我在 Decorate Me 試了${lookName(styleName)} ✦ 你也來試試 → ${link}`;

    function open({ before, after, styleName, styleId }) {
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
                        <textarea rows="3" data-caption>${escapeHtml(defaultCaption(styleName, shareUrl(styleId, 'share')))}</textarea></label>
                    <div class="look-share-link"><span>連結</span><code data-link></code></div>
                    <div class="look-share-actions">
                        ${canNativeShare ? '<button type="button" class="btn-gold" data-native></button>' : ''}
                        <button type="button" class="${canNativeShare ? 'btn-outline' : 'btn-gold'}" data-download>下載圖片</button>
                        <button type="button" class="btn-outline" data-copy-link>複製連結</button>
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
        // 任務點數「分享妝容到 IG／Threads」：每次按下分享就回報一次，發不發點、每天幾次由會員資料庫決定。
        // IG 不會告訴網頁使用者最後有沒有真的發文，所以能回報的只有「分享動作完成」。
        const reportShare = platform => {
            if (typeof ShareEvents === 'undefined') return;
            ShareEvents.record(platform, styleId).then(r => {
                if (r?.ok && Number(r.pointsAwarded) > 0) showToast(`分享任務完成，獲得 ${Number(r.pointsAwarded)} 點`);
            }).catch(() => {});
        };
        threadsEl.addEventListener('click', () => reportShare('threads'));
        const nativeBtn = modal.querySelector('[data-native]');
        const noteEl = modal.querySelector('[data-note]');
        const linkEl = modal.querySelector('[data-link]');
        const currentLink = () => shareUrl(styleId, format === 'story' ? 'ig-story' : 'ig-post');
        // Threads 發文連結：文案裡已經帶了網址，Threads 會自動把它變成可以點的連結
        const setThreads = () => {
            const text = captionEl.value.replace(/src=share/, 'src=threads');
            threadsEl.href = THREADS_INTENT + encodeURIComponent(text);
        };
        setThreads();
        captionEl.addEventListener('input', setThreads);

        // 依格式換說明：限時動態要講「選 Instagram → 限時動態」，而且文案要自己貼（IG 不吃分享過來的文字）
        const syncCopy = () => {
            preview.classList.toggle('is-story', format === 'story');
            if (nativeBtn) nativeBtn.textContent = format === 'story' ? '分享到 IG 限時動態…' : '分享到 IG 貼文／Threads…';
            linkEl.textContent = currentLink();
            // IG 限時動態的連結只能用「連結貼紙」加：網頁不能替使用者貼，所以一步步講清楚
            noteEl.textContent = format === 'story'
                ? `${canNativeShare ? '按「分享到 IG 限時動態…」→ 選 Instagram →「限時動態」。' : '先下載圖片，到 IG 限時動態從相簿選這張。'}`
                  + '要讓朋友點得進來：先按「複製連結」，在限時動態按上方的貼紙圖示 →「連結」→ 貼上。朋友點貼紙就會打開 Decorate Me，直接用訪客身分試同一款妝。'
                : (canNativeShare
                    ? '按「分享到 IG 貼文／Threads…」後選 Instagram 或 Threads，圖片和文案（含連結）會一起帶過去。IG 貼文的內文連結點不了，建議把連結放在個人簡介；Threads 的連結可以直接點。'
                    : '請下載圖片再到 IG 上傳；IG 貼文的內文連結點不了，建議放在個人簡介。Threads 可以按「開啟 Threads 發文」，文案與連結會帶過去，圖片要自己加。');
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
            // 限時動態要貼連結貼紙：分享前先把連結放進剪貼簿，到 IG 直接貼
            if (format === 'story') { try { await navigator.clipboard.writeText(currentLink()); showToast('連結已複製，到限時動態加「連結」貼紙貼上'); } catch (_) {} }
            try {
                if (navigator.canShare(data)) await navigator.share(data);
                else await navigator.share({ text: captionEl.value, url: currentLink() });
                // share() 成功只代表使用者選了一個 App，不代表真的發出去；取消會進 catch，不回報
                reportShare(format === 'story' ? 'ig_story' : 'ig_post');
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
            reportShare('download');
        };
        modal.querySelector('[data-copy-link]').onclick = async () => {
            try { await navigator.clipboard.writeText(currentLink()); showToast('已複製連結'); }
            catch (_) { showToast('請長按連結手動複製'); }
        };
        modal.querySelector('[data-copy]').onclick = async () => {
            try { await navigator.clipboard.writeText(captionEl.value); showToast('已複製文案'); }
            catch (_) { captionEl.select(); showToast('請長按文案手動複製'); }
        };
    }

    window.LookShare = { open, composeCard, defaultCaption, shareUrl, FORMATS };
})(window, document);
