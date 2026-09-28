// 新手實作導覽（2026-09-28 使用者要求：「真的帶新手做一遍，不是跳視窗而已」）。
//
// 做法：照真實流程一步一步走——切到真的頁面、把畫面上**真正要按的那個元素**框出來（聚光燈），
// 旁邊一張說明小卡；使用者自己按下去、上傳照片、等分析完成……系統偵測到那一步完成了才進下一步。
// 純說明的步驟才有「下一步」按鈕。
//
//   · 聚光燈是一個 pointer-events:none 的框（外面一圈半透明陰影），**不擋任何點擊**——
//     使用者照樣可以操作頁面與視窗，導覽只是指路。
//   · 層級高於所有視窗（視窗是 360），所以選妝容那幾個視窗裡的按鈕也框得到。
//   · 找不到目標（版面不同、手機選單收著）時不卡住：小卡改成置中，並給「下一步／帶我過去」。
//   · 進度存在這台裝置：重新整理或中途離開，下次進來從同一步繼續。
(function (window, document) {
    'use strict';

    const PROGRESS_KEY = 'beautyGuidedTour';
    const $ = sel => { try { return document.querySelector(sel); } catch (_) { return null; } };
    // 「看得到」＝有大小、在畫面範圍內、自己與祖先都沒被藏起來。
    // 手機選單收起時，抽屜裡的連結有大小但在畫面外（或祖先是 visibility:hidden）——
    // 只看自己的樣式會把它當成看得到，聚光燈就框到畫面外去了。
    const visible = el => {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return false;
        if (r.right <= 0 || r.left >= window.innerWidth || r.bottom <= 0) return false;
        if (typeof el.checkVisibility === 'function'
            && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
        const cs = getComputedStyle(el);
        return cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) > 0.05;
    };
    const firstVisible = (...sels) => { for (const s of sels) { const el = $(s); if (visible(el)) return el; } return null; };
    const narrow = () => !!(window.matchMedia && window.matchMedia('(max-width: 900px)').matches);
    const page = () => (typeof Router !== 'undefined' ? Router.currentPage : '');
    const journeyStarted = () => (typeof hasStartedJourney === 'function' ? hasStartedJourney() : false);
    const anyStyleModal = () => $('#makeupPlanModal') || $('#makeupStyleModal.open') || $('#bagStyleModal');

    // 導覽列的目標：桌機直接框選單項目；手機先框「≡」請他打開選單，打開後再框選單裡的項目
    function navTarget(pageId) {
        const link = $(`.topbar-nav a[data-page="${pageId}"]`);
        if (visible(link)) return link;
        const tab = $(`.tabbar a[data-page="${pageId}"]`);
        if (visible(tab)) return tab;
        return firstVisible('.topbar-menu-toggle');
    }
    const navHint = pageId => {
        const link = $(`.topbar-nav a[data-page="${pageId}"]`);
        return visible(link) ? '' : '（先按右上角的 ≡ 打開選單，再點選單裡的項目）';
    };

    // ── 步驟 ─────────────────────────────────────────────────────
    // target：回傳要框的元素（null＝置中顯示）；done：偵測到完成就自動進下一步；
    // manual：純說明步驟，顯示「下一步」；go：找不到目標時「帶我過去」要做的事。
    const STEPS = [
        { id: 'intro', title: '一起走一遍', manual: true,
          text: '我們會實際帶你做一次：拍照分析 → 選妝容 → 產生建議與妝後照 → 看上妝示範。分析和產生妝後照各要等一下，全程約 3～5 分鐘。途中隨時可以按「略過導覽」。' },
        { id: 'goAnalysis', title: '① 打開「臉部分析」',
          text: () => `按框起來的地方，進入臉部分析。${navHint('analysis')}`,
          target: () => navTarget('analysis'),
          done: () => page() === 'analysis',
          go: () => Router.go('analysis') },
        { id: 'upload', title: '② 上傳一張正面照',
          text: '點這裡選一張正面、光線均勻、沒有遮住臉的照片（也可以用下面的「開啟鏡頭」直接拍）。',
          target: () => firstVisible('#uploadBox', '#frontSlot', '.upload-box'),
          done: () => { const p = $('#preview'); return !!(p && p.getAttribute('src') && p.style.display !== 'none'); },
          ensurePage: 'analysis' },
        { id: 'analyze', title: '③ 開始分析',
          text: '照片放好了，按「開始分析」。',
          target: () => firstVisible('#analyzeBtn'),
          done: () => journeyStarted() || /分析中|上傳|處理|排隊/.test($('#loadingStatus')?.textContent || ''),
          ensurePage: 'analysis' },
        { id: 'waitAnalysis', title: '分析中…',
          text: '系統正在分析你的臉型、五官與膚色，大約 20～60 秒。完成後會自動進到下一步，這段時間可以先看看分析進度。',
          target: () => firstVisible('#analysisSteps', '#loadingStatus'),
          done: () => journeyStarted() && visible($('#goStyleBtn')) },
        { id: 'goStyle', title: '④ 選擇妝容風格',
          text: '分析完成了！上面是你的臉部特徵。按「選擇風格 →」開始挑妝容。',
          target: () => firstVisible('#goStyleBtn'),
          done: () => !!anyStyleModal() },
        { id: 'pickPlan', title: '⑤ 選一種規劃方式',
          text: () => ($('#makeupPlanModal')
              ? '兩種方式：從七種妝容挑一款，或「用我的化妝包」依你已有的化妝品推薦。第一次建議先選「依想嘗試的風格」，選好按「下一步」。'
              : '挑一款想試的妝容（卡片上的星星是新手難易度，星越少越好上手），選好按「產生妝容建議 →」。'),
          target: () => firstVisible('#makeupPlanModal .makeup-style-grid', '#makeupStyleModal.open .makeup-style-grid', '#bagStyleModal .makeup-style-grid'),
          done: () => !!$('#journeyModal') },
        { id: 'waitAdvice', title: '⑥ 產生妝容建議',
          text: '系統正在依你的臉部分析寫專屬的妝容建議，大約 10～30 秒。',
          target: () => firstVisible('#journeyModal .makeup-style-dialog'),
          done: () => visible($('#journeyModal [data-render]')) || page() === 'suggestion' },
        { id: 'render', title: '⑦ 產生妝後照',
          text: '建議好了！按「開始妝容渲染 →」，系統會把這個妝畫在你的照片上（約 1～2 分鐘，請保持頁面開啟）。',
          target: () => firstVisible('#journeyModal [data-render]'),
          done: () => page() === 'suggestion' && !!$('.look-pin') },
        { id: 'pins', title: '⑧ 看每個部位怎麼畫',
          text: '這是你的妝後照。點照片兩側的部位標籤（例如「眼妝」），會直接在照片上示範這個部位怎麼畫，旁邊有你的專屬做法。可以先點一個試試。',
          target: () => firstVisible('.look-pin-lane.right-lane', '.look-pin'),
          done: () => !!$('.look-pin.is-demo'), manual: true },
        { id: 'tutorAll', title: '⑨ 完整上妝示範',
          text: '想從頭看一遍？按「▶ 上妝示範」，會依照上妝順序一步步示範。',
          target: () => firstVisible('[data-tutor-all]'), manual: true },
        { id: 'products', title: '⑩ 推薦商品、收藏與分享',
          text: '「查看推薦商品」依你的臉部分析推薦商品；也可以收藏這次的妝容，或分享到 IG 限時動態／Threads。',
          target: () => firstVisible('.lookbook-actions'), manual: true },
        { id: 'bag', title: '⑪ 我的化妝包（之後可以做）',
          text: () => `「我的化妝包」在「會員中心」裡：把手邊已經有的化妝品登記進去，下次選妝容時就能「用我的化妝包」，只補你缺的。${navHint('profile')}`,
          target: () => navTarget('profile'), manual: true, last: true },
    ];

    let idx = -1, timer = 0, root = null, hole = null, card = null, lastEl = null, missingSince = 0, onKey = null;

    const save = () => { try { localStorage.setItem(PROGRESS_KEY, JSON.stringify({ step: STEPS[idx]?.id || null, at: Date.now() })); } catch (_) {} };
    const clearProgress = done => { try { localStorage.setItem(PROGRESS_KEY, JSON.stringify({ step: null, done: !!done, at: Date.now() })); } catch (_) {} };
    const progress = () => { try { return JSON.parse(localStorage.getItem(PROGRESS_KEY) || 'null'); } catch (_) { return null; } };

    function mount() {
        if (root) return;
        root = document.createElement('div');
        root.className = 'gt-root';
        root.innerHTML = '<div class="gt-hole" aria-hidden="true"></div><div class="gt-card" role="dialog" aria-live="polite" aria-label="新手導覽"></div>';
        document.body.appendChild(root);
        hole = root.querySelector('.gt-hole');
        card = root.querySelector('.gt-card');
        onKey = e => { if (e.key === 'Escape') stop(false); };
        document.addEventListener('keydown', onKey);
    }
    function stop(done) {
        clearInterval(timer); timer = 0;
        if (root) root.remove();
        root = hole = card = lastEl = null;
        if (onKey) document.removeEventListener('keydown', onKey);
        clearProgress(done);
        if (typeof HelpCenter !== 'undefined' && HelpCenter.markTourSeen) HelpCenter.markTourSeen();
    }

    function place(el) {
        const pad = 8, vw = window.innerWidth, vh = window.innerHeight;
        if (!el) {
            hole.classList.add('is-off');
            card.classList.add('is-center');
            card.style.left = ''; card.style.top = '';
            return;
        }
        const r = el.getBoundingClientRect();
        hole.classList.remove('is-off');
        Object.assign(hole.style, { left: `${r.left - pad}px`, top: `${r.top - pad}px`, width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px` });
        card.classList.remove('is-center');
        // 小卡放在目標下方；下方放不下就放上方；左右夾在視窗內
        const cw = Math.min(340, vw - 24), ch = card.offsetHeight || 180;
        let top = r.bottom + pad + 12;
        if (top + ch > vh - 12) top = r.top - pad - 12 - ch;
        if (top < 12) top = Math.min(vh - ch - 12, Math.max(12, r.bottom + pad + 12));
        const left = Math.max(12, Math.min(vw - cw - 12, r.left + r.width / 2 - cw / 2));
        card.style.width = `${cw}px`; card.style.left = `${left}px`; card.style.top = `${top}px`;
    }

    function drawCard(st, found) {
        const text = typeof st.text === 'function' ? st.text() : st.text;
        const showNext = st.manual || (!found && Date.now() - missingSince > 2500);
        card.innerHTML = `
            <div class="gt-step">新手導覽 · ${idx + 1} / ${STEPS.length}</div>
            <b class="gt-title">${escapeHtml(st.title)}</b>
            <p class="gt-text">${escapeHtml(text)}</p>
            <div class="gt-actions">
                <button type="button" class="gt-skip" data-gt-skip>略過導覽</button>
                ${!found && st.go ? '<button type="button" class="btn-outline gt-btn" data-gt-go>帶我過去</button>' : ''}
                ${showNext ? `<button type="button" class="btn-gold gt-btn" data-gt-next>${st.last ? '完成' : (idx === 0 ? '開始' : '下一步')}</button>` : '<span class="gt-wait">完成這一步後會自動繼續</span>'}
            </div>`;
        card.querySelector('[data-gt-skip]').onclick = () => stop(false);
        card.querySelector('[data-gt-next]')?.addEventListener('click', () => (st.last ? stop(true) : goto(idx + 1)));
        card.querySelector('[data-gt-go]')?.addEventListener('click', () => { try { st.go(); } catch (_) {} });
    }

    function tick() {
        const st = STEPS[idx];
        if (!st || !root) return;
        if (st.ensurePage && page() !== st.ensurePage && typeof Router !== 'undefined') Router.go(st.ensurePage);
        if (st.done && st.done()) { goto(idx + 1); return; }
        const el = st.target ? st.target() : null;
        if (el) missingSince = 0; else if (!missingSince) missingSince = Date.now();
        // 目標換了才重畫卡片內容（避免每 400ms 重建按鈕，使用者按不到）
        const key = `${idx}|${el ? 'y' : 'n'}|${Date.now() - missingSince > 2500 ? 'late' : ''}|${typeof st.text === 'function' ? st.text() : ''}`;
        if (card.dataset.key !== key) { card.dataset.key = key; drawCard(st, !!el); }
        if (el && el !== lastEl) {
            const r = el.getBoundingClientRect();
            if (r.top < 70 || r.bottom > window.innerHeight - 40) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
        lastEl = el;
        place(el);
    }

    function goto(i) {
        if (i >= STEPS.length) { stop(true); return; }
        idx = i; missingSince = 0; lastEl = null;
        if (card) card.dataset.key = '';
        save();
        tick();
    }

    function start(fromStepId) {
        mount();
        const i = fromStepId ? Math.max(0, STEPS.findIndex(s => s.id === fromStepId)) : 0;
        clearInterval(timer);
        timer = setInterval(tick, 400);
        window.addEventListener('resize', tick);
        window.addEventListener('scroll', () => { if (root && lastEl) place(lastEl); }, { passive: true });
        goto(i);
    }
    // 上次做到一半（重新整理、中途離開）：從同一步繼續
    function resumeIfUnfinished() {
        const p = progress();
        if (p && p.step && !root) { start(p.step); return true; }
        return false;
    }

    window.GuidedTour = { start, stop, resumeIfUnfinished, STEPS, isRunning: () => !!root };
})(window, document);
