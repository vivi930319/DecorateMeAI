// 使用導覽＋意見回饋（2026-09-28）。
//
// 右下角一顆「?」按鈕，展開兩個選項：使用導覽、意見回饋。
//   · 使用導覽：第一次進入系統時自動出現一次（每個帳號各記一次，訪客共用一次），
//     之後隨時可以從這顆按鈕重看。用卡片一步步說明，不用聚光燈指向導覽列——
//     手機上導覽列收在抽屜裡，指不到。
//   · 意見回饋：登入的會員才能送（要能回頭找到人、也擋濫發）；
//     送不出去時存在這台裝置，下次打開自動重送（見 api.js 的 UserFeedbackApi）。
(function (window, document) {
    'use strict';

    const TOUR_KEY = 'beautyTourSeen';
    const STEPS = [
        { img: 'assets/brand/decorate-me-logo.png', title: '歡迎來到妝識你的美',
          body: '用一張正面照分析你的臉型、五官與膚色，再依你的條件推薦妝容、示範怎麼畫、推薦適合的商品。花 30 秒看看怎麼用。' },
        { img: 'assets/feature/nav-face.webp', title: '① 臉部分析',
          body: '從「臉部分析」上傳一張正面、光線均勻、沒有遮擋的照片。系統會分析臉型、眉眼鼻唇與膚色季型，這是後面所有推薦的依據。' },
        { img: '港風.webp', title: '② 選擇妝容',
          body: '分析完成後有兩種規劃方式：從七種妝容挑一款（卡片上的星星是新手難易度），或「用我的化妝包」——依你已經有的化妝品推薦能畫的妝。' },
        { img: 'assets/makeup-bag.webp', title: '③ 我的化妝包',
          body: '在「我的化妝包」登記手邊的彩妝。登記後，推薦會優先用你已經有的，只補你缺的部位；商品旁的「化妝包內容」標記代表你已經有了。' },
        { img: '日雜.webp', title: '④ 妝容建議與上妝示範',
          body: '產生妝容建議與妝後照後，點照片兩側的部位標籤，會在妝後照上一步步示範怎麼畫；也可以播放完整的上妝示範，或分享到 IG／Threads。' },
        { img: '千金.webp', title: '⑤ 商品推薦與收藏',
          body: '「查看推薦商品」會依你的臉部分析推薦商品。喜歡的妝容記得收藏，之後在「收藏」頁隨時再看。有任何想法，歡迎從右下角的「?」告訴我們。' },
    ];

    const email = () => String((typeof Auth !== 'undefined' && Auth.getProfile && Auth.getProfile()?.email) || 'guest').trim().toLowerCase();
    const seenMap = () => { try { return JSON.parse(localStorage.getItem(TOUR_KEY) || '{}'); } catch (_) { return {}; } };
    const markSeen = () => { try { const m = seenMap(); m[email()] = new Date().toISOString(); localStorage.setItem(TOUR_KEY, JSON.stringify(m)); } catch (_) {} };
    const isAdminPage = () => typeof Router !== 'undefined' && Router.currentPage === 'admin';

    function modalShell(id, labelId, inner) {
        document.getElementById(id)?.remove();
        const modal = document.createElement('div');
        modal.id = id;
        modal.className = 'makeup-style-modal open help-modal';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-labelledby', labelId);
        modal.innerHTML = inner;
        document.body.appendChild(modal);
        return modal;
    }

    // ── 使用導覽 ──────────────────────────────────────────────
    function startTour() {
        let i = 0;
        const modal = modalShell('onboardingTour', 'tourTitle', '<div class="makeup-style-dialog tour-dialog"></div>');
        const dialog = modal.querySelector('.tour-dialog');
        const close = () => { markSeen(); modal.remove(); };
        const draw = () => {
            const st = STEPS[i], last = i === STEPS.length - 1;
            dialog.innerHTML = `
                <button class="makeup-style-close" type="button" aria-label="關閉導覽">×</button>
                <div class="tour-art"><img src="${escapeHtml(st.img)}" alt=""></div>
                <div class="tour-copy">
                    <span class="eyebrow">Guide · ${i + 1} / ${STEPS.length}</span>
                    <h2 id="tourTitle">${escapeHtml(st.title)}</h2>
                    <p>${escapeHtml(st.body)}</p>
                </div>
                <div class="tour-dots" aria-hidden="true">${STEPS.map((_, k) => `<i class="${k === i ? 'on' : ''}"></i>`).join('')}</div>
                <div class="makeup-style-actions tour-actions">
                    ${i === 0 ? '<button class="btn-outline" type="button" data-skip>略過</button>' : '<button class="btn-outline" type="button" data-prev>上一步</button>'}
                    ${last ? '<button class="btn-gold" type="button" data-go>開始臉部分析 →</button>' : '<button class="btn-gold" type="button" data-next>下一步</button>'}
                </div>`;
            dialog.querySelector('.makeup-style-close').onclick = close;
            dialog.querySelector('[data-skip]')?.addEventListener('click', close);
            dialog.querySelector('[data-prev]')?.addEventListener('click', () => { i -= 1; draw(); });
            dialog.querySelector('[data-next]')?.addEventListener('click', () => { i += 1; draw(); });
            dialog.querySelector('[data-go]')?.addEventListener('click', () => { close(); if (typeof Router !== 'undefined') Router.go('analysis'); });
        };
        draw();
    }
    // 第一次進入系統時自動出現一次；後台不出現
    function maybeStartTour() {
        if (isAdminPage() || seenMap()[email()]) return;
        setTimeout(() => { if (!document.getElementById('onboardingTour')) startTour(); }, 700);
    }

    // ── 意見回饋 ──────────────────────────────────────────────
    function openFeedback() {
        const isGuest = typeof window.isGuest === 'function' ? window.isGuest() : !Auth.getProfile()?.email;
        const cats = (typeof UserFeedbackApi !== 'undefined' ? UserFeedbackApi.CATEGORIES : ['功能建議', '問題回報', '其他']);
        const modal = modalShell('feedbackBox', 'feedbackTitle', `<div class="makeup-style-dialog feedback-dialog">
            <div class="makeup-style-head">
                <div><span class="eyebrow">Feedback</span><h2 id="feedbackTitle">意見回饋</h2>
                <p>哪裡好用、哪裡卡住、想要什麼功能，都歡迎告訴我們。</p></div>
                <button class="makeup-style-close" type="button" aria-label="關閉">×</button>
            </div>
            ${isGuest ? `<div class="mp-hint">登入後才能送出回饋——我們需要能回頭找到你，也避免被濫發。</div>
                <div class="makeup-style-actions"><button class="btn-gold" type="button" data-login>登入／註冊</button></div>` : `
            <div class="fb-form">
                <div class="fb-row"><span class="fb-label">類型</span>
                    <div class="fb-cats" role="radiogroup">${cats.map((c, k) => `<button type="button" class="chip${k === 0 ? ' active' : ''}" role="radio" aria-checked="${k === 0}" data-cat="${escapeHtml(c)}">${escapeHtml(c)}</button>`).join('')}</div></div>
                <div class="fb-row"><span class="fb-label">整體滿意度（可不填）</span>
                    <div class="fb-stars" role="radiogroup" aria-label="滿意度">${[1, 2, 3, 4, 5].map(n => `<button type="button" data-star="${n}" aria-label="${n} 顆星">☆</button>`).join('')}</div></div>
                <label class="fb-row"><span class="fb-label">內容</span>
                    <textarea rows="5" maxlength="1000" data-msg placeholder="例如：上妝示範的眼影位置跑到眉毛上了、希望可以比較兩種妝容…"></textarea>
                    <small class="fb-count" data-count>0 / 1000</small></label>
                <label class="fb-check"><input type="checkbox" data-page-info checked><span>附上目前所在的頁面（幫我們找到問題）</span></label>
                <p class="fb-status" data-status role="status"></p>
            </div>
            <div class="makeup-style-actions">
                <button class="btn-outline" type="button" data-cancel>取消</button>
                <button class="btn-gold" type="button" data-send disabled>送出回饋</button>
            </div>`}
        </div>`);
        const close = () => modal.remove();
        modal.querySelector('.makeup-style-close').onclick = close;
        if (isGuest) {
            modal.querySelector('[data-login]').onclick = () => { close(); if (typeof promptGuestAuth === 'function') promptGuestAuth('送出意見回饋'); };
            return;
        }
        let cat = cats[0], rating = null;
        modal.querySelector('[data-cancel]').onclick = close;
        modal.querySelectorAll('[data-cat]').forEach(b => b.onclick = () => {
            cat = b.dataset.cat;
            modal.querySelectorAll('[data-cat]').forEach(x => { x.classList.toggle('active', x === b); x.setAttribute('aria-checked', String(x === b)); });
        });
        const stars = modal.querySelectorAll('[data-star]');
        stars.forEach(b => b.onclick = () => {
            const n = Number(b.dataset.star);
            rating = rating === n ? null : n;   // 再點一次同一顆＝取消
            stars.forEach(x => { x.textContent = rating && Number(x.dataset.star) <= rating ? '★' : '☆'; });
        });
        const msg = modal.querySelector('[data-msg]'), send = modal.querySelector('[data-send]'), count = modal.querySelector('[data-count]');
        const status = modal.querySelector('[data-status]');
        msg.addEventListener('input', () => {
            const n = msg.value.trim().length;
            count.textContent = `${msg.value.length} / 1000`;
            send.disabled = n < 5;
        });
        send.onclick = async () => {
            const text = msg.value.trim();
            if (text.length < 5) return;
            send.disabled = true; status.textContent = '送出中…';
            const payload = {
                category: cat,
                rating,
                message: text,
                page: modal.querySelector('[data-page-info]').checked && typeof Router !== 'undefined' ? (Router.currentPage || null) : null,
                styleId: typeof Router !== 'undefined' ? (Router.selectedStyleId || null) : null,
                appVersion: (document.querySelector('script[src*="js/router.js"]')?.getAttribute('src') || '').split('v=')[1] || null,
                userAgent: navigator.userAgent.slice(0, 200),
                createdAt: new Date().toISOString(),
            };
            const res = await UserFeedbackApi.submit(payload);
            if (res.ok) { close(); showToast('謝謝你的回饋，我們收到了'); return; }
            status.textContent = res.error || '送出失敗，請稍後再試。';
            status.classList.add('is-error');
            if (res.queued) { send.textContent = '已存在這台裝置'; setTimeout(close, 2200); }
            else send.disabled = false;
        };
        // 上次沒送出去的，趁這次打開再送一次
        UserFeedbackApi.flushOutbox().then(n => { if (n) showToast(`之前沒送出的 ${n} 則回饋已補送`); }).catch(() => {});
    }

    // ── 右下角的「?」 ───────────────────────────────────────────
    function mountButton() {
        if (document.getElementById('helpFab')) return;
        const wrap = document.createElement('div');
        wrap.id = 'helpFab';
        wrap.className = 'help-fab';
        wrap.innerHTML = `<div class="help-fab-menu" hidden>
                <button type="button" data-help-tour>使用導覽</button>
                <button type="button" data-help-feedback>意見回饋</button>
            </div>
            <button type="button" class="help-fab-btn" aria-label="說明與意見回饋" aria-expanded="false">?</button>`;
        document.body.appendChild(wrap);
        const menu = wrap.querySelector('.help-fab-menu'), btn = wrap.querySelector('.help-fab-btn');
        const toggle = (open) => { menu.hidden = !open; btn.setAttribute('aria-expanded', String(open)); };
        btn.onclick = () => toggle(menu.hidden);
        wrap.querySelector('[data-help-tour]').onclick = () => { toggle(false); startTour(); };
        wrap.querySelector('[data-help-feedback]').onclick = () => { toggle(false); openFeedback(); };
        document.addEventListener('click', e => { if (!wrap.contains(e.target)) toggle(false); });
        // 換頁（含進後台、登出回登入畫面）時重新判斷要不要顯示
        window.addEventListener('hashchange', () => setTimeout(syncVisibility, 0));
    }
    // 後台與登入畫面不顯示；進入系統（showApp）後才出現
    function syncVisibility() {
        const fab = document.getElementById('helpFab');
        const app = document.getElementById('app');
        const appShown = !app || app.style.display !== 'none';
        if (fab) fab.hidden = isAdminPage() || !appShown;
    }

    window.HelpCenter = { startTour, maybeStartTour, openFeedback, mountButton, syncVisibility, STEPS };
})(window, document);
