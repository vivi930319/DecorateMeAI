// 新手實作導覽（2026-09-28 使用者要求：「真的帶新手做一遍，不是跳視窗而已」）。
//
// 做法：照真實流程一步一步走——切到真的頁面、把畫面上**真正要按的那個元素**框出來（聚光燈），
// 旁邊一張說明小卡；使用者自己按下去、上傳照片、等分析完成……系統偵測到那一步完成了才進下一步。
// 純說明的步驟才有「下一步」按鈕。
//
// 每一步都要**真的做到**（2026-09-28 追加：「照片挑錯你就要帶使用者去重做」）：
//   · done 只認這一次導覽裡發生的結果——舊的分析、被退回的同一張照片都不算數
//   · problem 偵測這一步做壞了（照片不能分析、膚色不準、建議或妝後照沒產生成功），
//     小卡改成「哪裡出了問題＋為什麼＋帶我重做」，按下去會退回該重做的那一步
//   · 分析完、妝後照出來後各有一個確認步驟：照片選錯、結果不對，都能從這裡退回去
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
    const page = () => (typeof Router !== 'undefined' ? Router.currentPage : '');
    const pkg = () => (typeof Router !== 'undefined' ? Router.analysisPackage : null) || null;
    const anyStyleModal = () => $('#makeupPlanModal') || $('#makeupStyleModal.open') || $('#bagStyleModal');
    const textOf = sel => String($(sel)?.textContent || '').trim();

    // 目前選的那張正面照（BASIC 是 selectedFile，PRO 是 proFiles.front）
    const chosenFile = () => {
        if (typeof Router === 'undefined') return null;
        return Router.analyzeMode === 'pro' ? (Router.proFiles?.front || null) : (Router.selectedFile || null);
    };
    // 同一張照片重新選一次會是新的 File 物件，所以用「檔名＋大小＋修改時間」認照片
    const fileSig = f => (f ? `${f.name}|${f.size}|${f.lastModified}` : '');
    const previewShown = () => { const p = $('#preview'); return !!(p && p.getAttribute('src') && p.style.display !== 'none'); };

    // ── 這一次導覽的狀態（只在記憶體）───────────────────────────────
    // rejectedFile：使用者說「照片挑錯了」或分析退回的那張（fileSig）——再選到同一張不算完成上傳
    // dismissed：使用者看過並按了「重做」的那個問題，避免同一個舊錯誤一直把人拉回來
    // accepted：使用者看過警告仍選「先用這張繼續」
    // analyzeStepAt：進入「開始分析」的時間；完成時間早於它的分析是舊結果，不算
    let rejectedFile = null, dismissed = '', accepted = '', analyzeStepAt = 0;
    const clicked = { tutorAll: false, products: false };

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

    // ── 重做的動作 ───────────────────────────────────────────────────
    // 換照片：把目前那張記成「退回」，回到上傳那一步，並直接打開選照片的視窗。
    // 檔案選擇器必須在按鈕的點擊裡**同步**觸發，手機瀏覽器才肯開（非使用者手勢會被擋）。
    function redoPhoto() {
        rejectedFile = fileSig(chosenFile()) || 'restored';
        if (page() === 'analysis') $('#uploadBox')?.click();
        else if (typeof Router !== 'undefined') Router.go('analysis');
        goto(stepIndex('upload'));
    }
    // 回到選妝容：關掉流程視窗，重新打開規劃妝容
    function redoStyle() {
        const modal = $('#journeyModal');
        if (modal) modal.remove();
        if (typeof window.openMakeupStyleModal === 'function') {
            window.openMakeupStyleModal(typeof Router !== 'undefined' ? Router.selectedStyleId : undefined);
        }
        goto(stepIndex('pickPlan'));
    }

    // ── 問題偵測 ─────────────────────────────────────────────────────
    // 回傳 null 或 { key, title, text, actions: [{ label, primary, run }] }。
    // key 用來判斷「這個問題使用者已經處理過了」——同一個 key 不再顯示第二次。
    function analysisProblem() {
        const p = pkg();
        if (!p || p.status !== 'failed') return null;
        const err = p.async || {};
        const key = `analysis|${p.id}|${err.failedAt || err.error || ''}`;
        const msg = String(err.error || '').trim();
        const offline = /Failed to fetch|NetworkError|Load failed|連不上|無法連接|逾時|timeout|50[234]/i.test(msg);
        // 照片本身的問題：分析端明確說照片不能用，或訊息在講臉、角度、光線、遮擋
        const photo = err.errorCode === 'FACE_IMAGE_UNUSABLE'
            || (!offline && /臉|照片|角度|轉向|光線|太暗|過曝|模糊|遮|正面|側臉|人像/.test(msg));
        if (photo) {
            return {
                key, title: '這張照片沒辦法分析',
                text: `${msg ? `分析端的說明：「${msg}」。` : ''}請換一張：本人、正面直視鏡頭、整張臉入鏡、光線均勻，不要戴口罩或墨鏡，頭髮不要蓋住臉頰。`,
                actions: [{ label: '換一張照片', primary: true, run: redoPhoto }],
            };
        }
        return {
            key, title: '分析沒有完成',
            text: offline
                ? '分析服務暫時連不上，不是你的照片有問題。照片已經保留，等一下再按一次「開始分析」就好。'
                : `分析沒有完成${msg ? `（${msg}）` : ''}。照片已經保留，可以直接再分析一次；一直失敗的話，換一張照片試試。`,
            actions: [
                { label: '換一張照片', run: redoPhoto },
                { label: '再分析一次', primary: true, run: () => goto(stepIndex('analyze')) },
            ],
        };
    }
    function adviceProblem() {
        const note = textOf('#journeyModal .journey-wait-note');
        if (/目前沒有臉部分析結果/.test(note)) {
            return {
                key: `advice|noAnalysis|${pkg()?.id}`, title: '還沒有臉部分析結果',
                text: '妝容建議要依你的臉部分析來寫，但目前找不到分析結果。我們回去重新上傳照片分析一次。',
                actions: [{ label: '回去重新分析', primary: true, run: () => { $('#journeyModal')?.remove(); redoPhoto(); } }],
            };
        }
        if (!/目前無法完成建議/.test(note)) return null;
        return {
            key: `advice|${pkg()?.id}|${note}`, title: '妝容建議沒有產生成功',
            text: `${note.replace(/^目前無法完成建議：?/, '原因：')}。通常是服務忙碌，回上一步重新選一次妝容就會再產生一次。`,
            actions: [{ label: '回上一步重選', primary: true, run: redoStyle }],
        };
    }
    function renderProblem() {
        const msg = textOf('#journeyModal .render-estimate b');
        if (!/生成失敗/.test(msg)) return null;
        return {
            key: `render|${pkg()?.id}|${msg}`, title: '妝後照沒有產生成功',
            text: `${msg.replace(/^生成失敗：?/, '原因：')}。回上一步再按一次「開始妝容渲染」就會重試（每天有次數上限，別連按）。`,
            actions: [{
                label: '回上一步再試', primary: true,
                run: () => { $('#journeyModal [data-back]')?.click(); goto(stepIndex('render')); },
            }],
        };
    }
    // 分析成功但膚色不可信：不擋路，讓使用者自己決定重拍或先用
    function skinWarning() {
        const skin = pkg()?.faceAnalysis?.skinTone;
        const warnEl = $('#skinReliabilityWarn');
        const warnText = warnEl && warnEl.style.display !== 'none' ? textOf('#skinReliabilityWarn') : '';
        if (skin?.labReliable !== false && !warnText) return null;
        const key = `skin|${pkg()?.id}`;
        if (accepted === key) return null;
        return {
            key, title: '膚色可能量不準',
            text: `${warnText || '臉頰被頭髮或陰影遮住，膚色可能不準。'} 膚色會影響粉底色號和整體配色推薦，建議在均勻光線下、把頭髮撥到耳後重拍一張。`,
            actions: [
                { label: '先用這張繼續', run: () => { accepted = key; goto(stepIndex('checkResult')); } },
                { label: '重拍一張（建議）', primary: true, run: redoPhoto },
            ],
        };
    }

    // 這一次導覽中完成的分析（完成時間不早於進入「開始分析」那一刻）
    const freshAnalysisDone = () => {
        const p = pkg();
        if (!p || p.status !== 'completed') return false;
        const at = Date.parse(p.async?.completedAt || '') || 0;
        return at >= analyzeStepAt - 1000;
    };

    // ── 步驟 ─────────────────────────────────────────────────────
    // target：回傳要框的元素（null＝置中顯示）；done：偵測到完成就自動進下一步；
    // manual：純說明步驟，顯示「下一步」；go：找不到目標時「帶我過去」要做的事；
    // problem：這一步做壞了（回傳上面那種物件）；extra：一直顯示的次要按鈕。
    const STEPS = [
        { id: 'intro', title: '一起走一遍', manual: true,
          text: '我們會實際帶你做一次：拍照分析 → 選妝容 → 產生建議與妝後照 → 看上妝示範。每一步都會確認你有做到，做錯了會帶你回去重做。分析和產生妝後照各要等一下，全程約 3～5 分鐘。途中隨時可以按「略過導覽」。' },
        { id: 'goAnalysis', title: '① 打開「臉部分析」',
          text: () => `按框起來的地方，進入臉部分析。${navHint('analysis')}`,
          target: () => navTarget('analysis'),
          done: () => page() === 'analysis',
          go: () => Router.go('analysis') },
        { id: 'upload', title: '② 上傳一張正面照',
          text: () => `${rejectedFile ? '請換一張**不同**的照片。' : ''}點這裡選照片（也可以用下面的「開啟鏡頭」直接拍）。挑照片的重點：本人、正面直視、整張臉入鏡、光線均勻、素顏或淡妝；不要戴口罩或墨鏡，頭髮不要蓋住臉頰。`,
          target: () => firstVisible('#uploadBox', '#frontSlot', '.upload-box'),
          // 選到的必須是「新的」那張；被退回的同一張不算。重新整理後 File 物件會消失，
          // 此時只要畫面上有照片、而且這輪沒有退回過照片就算數。
          done: () => { const f = chosenFile(); return f ? fileSig(f) !== rejectedFile : (previewShown() && !rejectedFile); },
          ensurePage: 'analysis' },
        { id: 'analyze', title: '③ 確認照片，開始分析',
          text: '看一下預覽：是你本人、正面、整張臉都看得到嗎？沒問題就按「開始分析」；選錯了按「照片挑錯了」。',
          target: () => firstVisible('#analyzeBtn'),
          done: () => !!$('#loadingStatus.active') || freshAnalysisDone(),
          problem: analysisProblem,
          extra: [{ label: '照片挑錯了，換一張', run: () => redoPhoto() }],
          onEnter: () => { analyzeStepAt = Date.now(); },
          ensurePage: 'analysis' },
        { id: 'waitAnalysis', title: '分析中…',
          text: '系統正在分析你的臉型、五官與膚色，大約 20～60 秒。完成後會自動進到下一步。',
          target: () => firstVisible('#analysisSteps', '#loadingStatus'),
          done: () => freshAnalysisDone() && visible($('#goStyleBtn')),
          problem: analysisProblem },
        { id: 'checkResult', title: '④ 確認分析結果',
          text: '分析完成！看一下結果：臉型、眉眼、唇形大致對嗎？個別判斷不準的，可以在下方的分析結果回饋直接改。如果照片本身選錯了（不是本人、不是正面、戴了口罩），按「照片挑錯了」重新來。',
          target: () => firstVisible('.result-grid', '#goStyleBtn'),
          problem: skinWarning,
          extra: [{ label: '照片挑錯了，重新上傳', run: () => redoPhoto() }],
          manual: true, nextLabel: '結果沒問題' },
        { id: 'goStyle', title: '⑤ 選擇妝容風格',
          text: '按「選擇風格 →」開始挑妝容。',
          target: () => firstVisible('#goStyleBtn'),
          done: () => !!anyStyleModal() },
        { id: 'pickPlan', title: '⑥ 選一種規劃方式',
          text: () => ($('#makeupPlanModal')
              ? '兩種方式：從七種妝容挑一款，或「用我的化妝包」依你已有的化妝品推薦。第一次建議先選「依想嘗試的風格」，選好按「下一步」。'
              : '挑一款想試的妝容（卡片上的星星是新手難易度，星越少越好上手），選好按「產生妝容建議 →」。'),
          target: () => firstVisible('#makeupPlanModal .makeup-style-grid', '#makeupStyleModal.open .makeup-style-grid', '#bagStyleModal .makeup-style-grid'),
          done: () => !!$('#journeyModal'),
          go: () => window.openMakeupStyleModal?.(Router.selectedStyleId) },
        { id: 'waitAdvice', title: '⑦ 產生妝容建議',
          text: '系統正在依你的臉部分析寫專屬的妝容建議，大約 10～30 秒。',
          target: () => firstVisible('#journeyModal .makeup-style-dialog'),
          done: () => visible($('#journeyModal [data-render]')) || page() === 'suggestion',
          problem: adviceProblem },
        { id: 'render', title: '⑧ 產生妝後照',
          text: '建議好了！按「開始妝容渲染 →」，系統會把這個妝畫在你的照片上（約 1～2 分鐘，請保持頁面開啟）。',
          target: () => firstVisible('#journeyModal [data-render]', '#journeyModal .render-estimate'),
          done: () => page() === 'suggestion' && !!$('.look-pin'),
          problem: renderProblem },
        { id: 'checkLook', title: '⑨ 確認妝後照',
          text: '這是你的妝後照。看起來是你本人、妝感也是你想要的風格嗎？不像你或不是你要的感覺，可以換一款妝容重新產生（每天有次數上限）。',
          target: () => firstVisible('.look-portrait-frame'),
          extra: [{ label: '不太對，換個妝容重做', run: () => redoStyle() }],
          manual: true, nextLabel: '看起來不錯' },
        { id: 'pins', title: '⑩ 看每個部位怎麼畫',
          text: '點照片兩側的任一個部位標籤（例如「眼妝」），會直接在照片上示範這個部位怎麼畫，旁邊有你的專屬做法。點一個試試。',
          target: () => firstVisible('.look-pin-lane.right-lane', '.look-pin'),
          done: () => !!$('.look-pin.is-demo') },
        { id: 'tutorAll', title: '⑪ 完整上妝示範',
          text: '想從頭看一遍？按「▶ 上妝示範」，會依照上妝順序一步步示範。',
          target: () => firstVisible('[data-tutor-all]'),
          done: () => clicked.tutorAll },
        { id: 'products', title: '⑫ 推薦商品、收藏與分享',
          text: '最後，按「查看推薦商品」看依你的臉部分析推薦的商品。這一排也可以收藏這次的妝容，或分享到 IG 限時動態／Threads。',
          target: () => firstVisible('[data-products]', '.lookbook-actions'),
          done: () => clicked.products || page() === 'products' },
        { id: 'bag', title: '⑬ 我的化妝包（之後可以做）',
          text: () => `「我的化妝包」在「會員中心」裡：把手邊已經有的化妝品登記進去，下次選妝容時就能「用我的化妝包」，只補你缺的。${navHint('profile')}`,
          target: () => navTarget('profile'), manual: true, last: true },
    ];
    const stepIndex = id => Math.max(0, STEPS.findIndex(s => s.id === id));

    let idx = -1, timer = 0, root = null, hole = null, card = null, lastEl = null, missingSince = 0, onKey = null, onClick = null;

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
        // 「按過沒有」在畫面上不留痕跡（示範結束就收起、商品按鈕會換頁），所以直接聽點擊
        onClick = e => {
            const t = e.target;
            if (!t || !t.closest) return;
            if (t.closest('[data-tutor-all]')) clicked.tutorAll = true;
            if (t.closest('[data-products]')) clicked.products = true;
        };
        document.addEventListener('click', onClick, true);
    }
    function stop(done) {
        clearInterval(timer); timer = 0;
        if (root) root.remove();
        root = hole = card = lastEl = null;
        if (onKey) document.removeEventListener('keydown', onKey);
        if (onClick) document.removeEventListener('click', onClick, true);
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

    // 文字裡的 **粗體** 轉成 <b>（先跳脫，再轉）
    const rich = s => escapeHtml(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');

    function drawProblem(pb) {
        card.classList.add('is-problem');
        card.innerHTML = `
            <div class="gt-step">新手導覽 · ${idx + 1} / ${STEPS.length} · 需要重做</div>
            <b class="gt-title">⚠ ${escapeHtml(pb.title)}</b>
            <p class="gt-text">${rich(pb.text)}</p>
            <div class="gt-actions">
                <button type="button" class="gt-skip" data-gt-skip>略過導覽</button>
                ${pb.actions.map((a, i) => `<button type="button" class="${a.primary ? 'btn-gold' : 'btn-outline'} gt-btn" data-gt-act="${i}">${escapeHtml(a.label)}</button>`).join('')}
            </div>`;
        card.querySelector('[data-gt-skip]').onclick = () => stop(false);
        card.querySelectorAll('[data-gt-act]').forEach(btn => {
            btn.onclick = () => {
                dismissed = pb.key;          // 這個問題處理過了，舊狀態不再把人拉回來
                card.dataset.key = '';
                try { pb.actions[Number(btn.dataset.gtAct)].run(); } catch (_) {}
            };
        });
    }

    function drawCard(st, found) {
        card.classList.remove('is-problem');
        const text = typeof st.text === 'function' ? st.text() : st.text;
        const showNext = st.manual || (!found && Date.now() - missingSince > 2500);
        const extra = (st.extra || []).map((a, i) => `<button type="button" class="btn-outline gt-btn" data-gt-extra="${i}">${escapeHtml(a.label)}</button>`).join('');
        card.innerHTML = `
            <div class="gt-step">新手導覽 · ${idx + 1} / ${STEPS.length}</div>
            <b class="gt-title">${escapeHtml(st.title)}</b>
            <p class="gt-text">${rich(text)}</p>
            <div class="gt-actions">
                <button type="button" class="gt-skip" data-gt-skip>略過導覽</button>
                ${extra}
                ${!found && st.go ? '<button type="button" class="btn-outline gt-btn" data-gt-go>帶我過去</button>' : ''}
                ${showNext ? `<button type="button" class="btn-gold gt-btn" data-gt-next>${st.last ? '完成' : (idx === 0 ? '開始' : (st.nextLabel || '下一步'))}</button>` : '<span class="gt-wait">完成這一步後會自動繼續</span>'}
            </div>`;
        card.querySelector('[data-gt-skip]').onclick = () => stop(false);
        card.querySelector('[data-gt-next]')?.addEventListener('click', () => (st.last ? stop(true) : goto(idx + 1)));
        card.querySelector('[data-gt-go]')?.addEventListener('click', () => { try { st.go(); } catch (_) {} });
        card.querySelectorAll('[data-gt-extra]').forEach(btn => {
            btn.onclick = () => { try { st.extra[Number(btn.dataset.gtExtra)].run(); } catch (_) {} };
        });
    }

    function tick() {
        const st = STEPS[idx];
        if (!st || !root) return;
        if (st.ensurePage && page() !== st.ensurePage && typeof Router !== 'undefined') Router.go(st.ensurePage);
        // 先看有沒有做壞：做壞了就停在這一步，小卡換成「哪裡出錯＋帶我重做」
        let pb = null;
        try { pb = st.problem ? st.problem() : null; } catch (_) { pb = null; }
        if (pb && pb.key === dismissed) pb = null;
        if (!pb && st.done && st.done()) { goto(idx + 1); return; }
        // 有問題時聚光燈照樣框著目標（例如照片區），讓人知道問題出在哪
        const el = st.target ? st.target() : null;
        if (el) missingSince = 0; else if (!missingSince) missingSince = Date.now();
        // 內容換了才重畫卡片（避免每 400ms 重建按鈕，使用者按不到）
        const key = pb ? `${idx}|pb|${pb.key}`
            : `${idx}|${el ? 'y' : 'n'}|${Date.now() - missingSince > 2500 ? 'late' : ''}|${typeof st.text === 'function' ? st.text() : ''}`;
        if (card.dataset.key !== key) { card.dataset.key = key; if (pb) drawProblem(pb); else drawCard(st, !!el); }
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
        if (STEPS[idx].id === 'tutorAll') clicked.tutorAll = false;
        if (STEPS[idx].id === 'products') clicked.products = false;
        try { STEPS[idx].onEnter?.(); } catch (_) {}
        if (card) card.dataset.key = '';
        save();
        tick();
    }

    function start(fromStepId) {
        mount();
        rejectedFile = null; dismissed = ''; accepted = '';
        // 從「等分析」接續（重新整理前已經按了開始分析）：那次分析的完成時間早於現在，也要算
        analyzeStepAt = fromStepId === 'waitAnalysis' ? 0 : Date.now();
        const i = fromStepId ? stepIndex(fromStepId) : 0;
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
