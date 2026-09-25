// 妝容規劃方式的分岔：臉部分析完成後、選風格之前，先問一次要用哪種推薦。
//
// 這支刻意獨立成一個檔案，而且是**包在既有 openMakeupStyleModal 外面**，
// 沒有改它一行。理由：系統推薦是已經上線、使用者每天在用的流程，
// 新功能壞掉可以修，舊功能壞掉是事故。這樣包起來，最壞情況也只是多一層視窗。
//
// 載入順序必須在 makeup-flow.js 之後——那支會覆寫 openMakeupStyleModal，
// 先載就會被它蓋掉。
(function (window, document) {
    'use strict';

    // ── 規劃方式的記憶 ────────────────────────────────────────────
    //
    // 只在首次或設定變更時問，選過就記住。每次都問等於多一個沒必要的步驟，
    // 而這個選擇對同一個人通常不會變。
    const MakeupPlan = {
        _key: 'beautyMakeupPlan',
        get() {
            try { return localStorage.getItem(this._key) || ''; } catch (_) { return ''; }
        },
        set(value) {
            try { localStorage.setItem(this._key, value); } catch (_) {}
        },
        clear() {
            try { localStorage.removeItem(this._key); } catch (_) {}
        },
        shouldAsk() { return !['system', 'makeupBag'].includes(this.get()); },
    };

    const PLAN_OPTIONS = [
        {
            id: 'makeupBag',
            title: '用我的化妝包',
            desc: '從你已經有的化妝品裡，推薦你能畫的妝容。',
        },
        {
            id: 'system',
            title: '依想嘗試的風格',
            desc: '從七種妝容選一款，系統依你的臉部分析推薦商品。',
        },
    ];

    function closeModal(id) {
        document.getElementById(id)?.remove();
    }

    // 沿用 makeup-style-modal 那組 class。它本來就是共用的
    // （productRecommendationModal 也用同一組），不另做一套視覺。
    function shell(id, labelId) {
        let modal = document.getElementById(id);
        if (!modal) {
            modal = document.createElement('div');
            modal.id = id;
            modal.className = 'makeup-style-modal open';
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-modal', 'true');
            modal.setAttribute('aria-labelledby', labelId);
            document.body.appendChild(modal);
        }
        return modal;
    }

    // ── 第一步：選規劃方式 ────────────────────────────────────────
    function openMakeupPlanModal(preselectedStyleId) {
        const modal = shell('makeupPlanModal', 'makeupPlanModalTitle');
        const bagCount = (typeof MakeupBag !== 'undefined') ? MakeupBag.count() : 0;
        let picked = MakeupPlan.get() || null;

        const draw = () => {
            modal.innerHTML = `<div class="makeup-style-dialog">
                <div class="makeup-style-head">
                    <div>
                        <span class="eyebrow">Plan</span>
                        <h2 id="makeupPlanModalTitle">這次想怎麼規劃妝容？</h2>
                        <p>兩種方式都可以，之後在會員中心隨時能改。</p>
                    </div>
                    <button class="makeup-style-close" type="button" aria-label="關閉">×</button>
                </div>
                <div class="makeup-style-grid mp-grid">
                    ${PLAN_OPTIONS.map(opt => {
                        // 化妝包是空的時候路徑 A 不可選，但**路徑 B 永遠可用**——
                        // 不讓使用者卡在這裡。灰掉並說明為什麼，比靜默把他轉去別條路好：
                        // 靜默轉走的話，他不會知道結果為什麼跟預期不同。
                        const disabled = opt.id === 'makeupBag' && !bagCount;
                        const note = opt.id === 'makeupBag'
                            ? (bagCount ? `目前 ${bagCount} 件商品` : '你的化妝包目前是空的')
                            : '';
                        return `<button class="makeup-style-option mp-option ${picked === opt.id ? 'selected' : ''}"
                            type="button" data-plan="${opt.id}" ${disabled ? 'disabled' : ''}>
                            <span class="makeup-style-option-copy">
                                <b>${opt.title}</b>
                                <small>${opt.desc}</small>
                                ${note ? `<em class="mp-note">${note}</em>` : ''}
                            </span>
                        </button>`;
                    }).join('')}
                </div>
                ${bagCount ? '' : '<div class="mp-hint">要用化妝包推薦，請先把你已經有的化妝品加進去。</div>'}
                <div class="makeup-style-actions">
                    ${bagCount ? '' : '<button class="btn-outline" type="button" data-goto-bag>前往建立化妝包</button>'}
                    <button class="btn-outline" type="button" data-modal-cancel>稍後再選</button>
                    <button class="btn-gold" type="button" data-modal-confirm ${picked ? '' : 'disabled'}>下一步 →</button>
                </div>
            </div>`;

            modal.querySelectorAll('[data-plan]').forEach(btn => {
                btn.onclick = () => { picked = btn.dataset.plan; draw(); };
            });
            modal.querySelector('.makeup-style-close').onclick = () => closeModal('makeupPlanModal');
            modal.querySelector('[data-modal-cancel]').onclick = () => closeModal('makeupPlanModal');
            const gotoBag = modal.querySelector('[data-goto-bag]');
            if (gotoBag) gotoBag.onclick = () => { closeModal('makeupPlanModal'); Router.go('makeupBag'); };
            const moreBtn = modal.querySelector('[data-more-style]');
            // 按鈕上**不放數字**：這條走 /recommend-products，結果是依臉部分析個人化過的，
            // 跟「資料庫裡有幾件這個風格」不是同一個數。把後者放在按鈕上，
            // 使用者點進去看到比較少的筆數會以為壞了。數量在結果頁講。
            if (moreBtn) moreBtn.onclick = () => {
                closeModal('bagStyleModal');
                openStyleMoreModal(picked, () => openBagStyleModal(picked));
            };
            modal.querySelector('[data-modal-confirm]').onclick = () => {
                if (!picked) return;
                MakeupPlan.set(picked);
                closeModal('makeupPlanModal');
                if (picked === 'makeupBag') openBagStyleModal(preselectedStyleId);
                else window.__openStyleModalDirect(preselectedStyleId);
            };
        };
        draw();
    }

    // ── 第二步（路徑 A）：依化妝包反推妝容 ──────────────────────────
    //
    // 顯示規則跟一般排序不同，刻意的：
    //   · 不顯示 score。實測它會擠在 0.21~0.28，使用者看到「最推薦的 0.28」
    //     會以為系統沒把握；而那個數字是拿全資料集最大值正規化出來的，
    //     本來就不是信心度。改顯示名次與支持它的商品件數。
    //   · 七種妝容一律可選。反推是建議不是判決——化妝包只涵蓋部分商品，
    //     而且使用者今天可能就是想化不一樣的。
    function openBagStyleModal(preselectedStyleId) {
        const modal = shell('bagStyleModal', 'bagStyleModalTitle');
        let picked = preselectedStyleId || Router.selectedStyleId || null;
        let result = null;
        let loading = true;

        const styleById = (id) => STYLES.find(s => s.id === id) || null;

        // 相對強度條。**在本次回傳的集合內重新縮放**，不是拿原始 score 直接畫。
        //
        // 原始 score 是拿全資料集最大值正規化的，實測會擠在 0.21~0.28——
        // 直接畫成長條的話七個看起來一樣長，等於沒說話。
        //
        // 重新縮放之後它必然隨名次遞減，所以**永遠不會跟排序矛盾**。
        // 這正是先前那個問題的根源：卡片上用因果語氣描述件數，
        // 而件數不是排序依據（3、9、6、9…），看起來就像排壞了。
        //
        // 它表達的是「在這幾個之中相對強一點」，不是契合度或準確率——
        // 所以不標百分比數字，只給長度。
        const strengthPct = (row) => {
            const scores = (result?.styles || []).map(r => Number(r.score) || 0);
            if (!scores.length) return 100;
            const max = Math.max(...scores);
            const min = Math.min(...scores);
            const v = Number(row.score) || 0;
            // 全部同分時一律給滿，不要畫出 0 長度讓人以為是最差的。
            if (max === min) return 100;
            // 下限 22%：最後一名也要看得見，否則會像「沒有資料」。
            return Math.round(22 + ((v - min) / (max - min)) * 78);
        };

        const draw = () => {
            const ranked = (result?.styles || [])
                .map(row => ({ row, style: styleById(row.id) }))
                .filter(x => x.style);
            const rankedIds = new Set(ranked.map(x => x.style.id));
            const others = STYLES.filter(s => !rankedIds.has(s.id));

            const body = loading
                ? '<div class="mp-hint">正在依你的化妝包計算…</div>'
                : (!result?.ok
                    ? `<div class="mp-hint is-error">${escapeHtml(errorText())}
                       <button type="button" class="mp-link" data-bag>去化妝包看看</button>
                       <button type="button" class="mp-link" data-fallback>改用系統推薦</button></div>`
                    : `
                    ${ranked.length ? `
                    <div class="mp-section-title">依你的化妝包推薦</div>
                    <div class="makeup-style-grid">
                        ${ranked.map(({ row, style }, i) => `
                        <button class="makeup-style-option ${picked === style.id ? 'selected' : ''}"
                            type="button" data-style-id="${escapeHtml(style.id)}">
                            <img src="${escapeHtml(style.img)}" alt="${escapeHtml(style.name)}">
                            <span class="makeup-style-option-copy">
                                <b>${escapeHtml(style.name)}</b>
                                <small>第 ${i + 1} 推薦</small>
                                <span class="mp-strength" aria-hidden="true"><i style="width:${strengthPct(row)}%"></i></span>
                                <em class="mp-used">用到你的 ${(row.contributingProducts || []).length} 件商品</em>
                            </span>
                        </button>`).join('')}
                    </div>` : '<div class="mp-hint">你的化妝包還不足以推論適合的妝容，可以直接從下面挑一款。</div>'}

                    ${others.length ? `
                    <div class="mp-section-title">其他妝容（仍可選）</div>
                    <div class="makeup-style-grid mp-grid-small">
                        ${others.map(style => `
                        <button class="makeup-style-option ${picked === style.id ? 'selected' : ''}"
                            type="button" data-style-id="${escapeHtml(style.id)}">
                            <img src="${escapeHtml(style.img)}" alt="${escapeHtml(style.name)}">
                            <span class="makeup-style-option-copy"><b>${escapeHtml(style.name)}</b></span>
                        </button>`).join('')}
                    </div>` : ''}

                    ${noticeHtml()}`);

            modal.innerHTML = `<div class="makeup-style-dialog">
                <div class="makeup-style-head">
                    <div>
                        <span class="eyebrow">Makeup Bag</span>
                        <h2 id="bagStyleModalTitle">依你的化妝包推薦</h2>
                        <p>這是依你已有的化妝品排出來的建議，你仍然可以選其他妝容。</p>
                    </div>
                    <button class="makeup-style-close" type="button" aria-label="關閉">×</button>
                </div>
                ${body}
                <div class="makeup-style-actions">
                    <button class="btn-outline" type="button" data-replan>換一種規劃方式</button>
                    ${picked ? `<button class="btn-outline" type="button" data-more-style>看看其他${escapeHtml(styleById(picked)?.name || '')}商品 →</button>` : ''}
                    <button class="btn-gold" type="button" data-modal-confirm ${picked ? '' : 'disabled'}>產生妝容建議 →</button>
                </div>
            </div>`;

            modal.querySelectorAll('[data-style-id]').forEach(btn => {
                btn.onclick = () => { picked = btn.dataset.styleId; draw(); };
            });
            modal.querySelector('.makeup-style-close').onclick = () => closeModal('bagStyleModal');
            modal.querySelector('[data-replan]').onclick = () => {
                closeModal('bagStyleModal');
                MakeupPlan.clear();
                openMakeupPlanModal(picked);
            };
            const bagBtn = modal.querySelector('[data-bag]');
            if (bagBtn) bagBtn.onclick = () => {
                closeModal('bagStyleModal');
                Router.go('makeupBag');
            };
            const fallback = modal.querySelector('[data-fallback]');
            if (fallback) fallback.onclick = () => {
                closeModal('bagStyleModal');
                window.__openStyleModalDirect(picked);
            };
            modal.querySelector('[data-modal-confirm]').onclick = () => {
                if (!picked) return;
                // 選到化妝包涵蓋不到的風格時，改走系統推薦——這是定案的分流規則。
                // 路徑 A 的承諾是「用你現有的」，涵蓋不到就沒有東西可推。
                const covered = rankedIds.has(picked);
                Router.makeupBagCoveredStyle = covered;
                closeModal('bagStyleModal');
                window.__openStyleModalDirect(picked);
            };
        };

        // 上游說「沒有化妝包」但本機明明有東西，那不是「還沒建立」，
        // 是**加入的時候沒寫進資料庫**。照抄上游那句話會讓使用者一直回去重加，
        // 而每一次都同樣只寫進本機。
        const errorText = () => {
            const localCount = (typeof MakeupBag !== 'undefined') ? MakeupBag.count() : 0;
            const notFound = /NOT_FOUND|EMPTY|尚未建立|沒有化妝包/.test(
                `${result?.code || ''} ${result?.error || ''}`);
            if (notFound && localCount) {
                return `你加的 ${localCount} 件商品還沒同步到雲端，所以這裡讀不到。` +
                       '妝容推薦是在伺服器上算的，需要雲端那份資料。';
            }
            return result?.error || '化妝包推薦暫時無法使用。';
        };

        // 覆蓋狀況要說出來，不能只給結論：
        //   · uncovered 是「還沒有風格資料」的商品
        //   · baseExcludedKeys 是粉底，它走膚色色差，不是缺漏——文案必須分開
        const noticeHtml = () => {
            if (!result?.ok) return '';
            const base = (result.baseExcludedKeys || []).length;
            const other = Math.max(0, (result.uncovered || 0) - base);
            const lines = [];
            if (other) lines.push(`有 ${other} 件商品尚未具備妝容資料，不影響其他商品的建議。`);
            if (base) lines.push(`粉底液會依膚色與色差另行比對，因此不納入妝容風格判斷。`);
            return lines.length ? `<div class="mp-notice">${lines.map(t => `<div>${t}</div>`).join('')}</div>` : '';
        };

        draw();

        const keys = (typeof MakeupBag !== 'undefined') ? MakeupBag.localList() : [];
        // 只送 candidateKeys。bagId 不是第一期的輸入，送了會被回 400。
        Promise.resolve(Api.recommendStyles({ candidateKeys: keys })).then(res => {
            loading = false;
            result = res;
            if (document.getElementById('bagStyleModal')) draw();
        }).catch(() => {
            loading = false;
            result = { ok: false, error: '化妝包推薦暫時無法使用。' };
            if (document.getElementById('bagStyleModal')) draw();
        });
    }

    // ── 同風格商品延伸推薦 ────────────────────────────────────────
    //
    // 「看看其他千金妝商品」**就是路徑 B**，只是風格已經由化妝包決定好了。
    // 所以直接用既有的 recommendProducts，不自己用標籤篩——本機篩得出來，
    // 但那樣會丟掉臉部分析，而臉部分析正是這個系統的賣點。
    //
    // 這裡不呼叫 Ollama、不呼叫 /recommend-styles：延伸推薦是「資料庫裡還有什麼可以買」，
    // 跟「你包裡的怎麼搭」是兩件事，混在一起只會增加失敗面。
    function openStyleMoreModal(styleId, onBack) {
        const modal = shell('styleMoreModal', 'styleMoreModalTitle');
        const style = STYLES.find(s => s.id === styleId) || null;
        let items = null;
        let failed = false;

        const draw = () => {
            let body;
            if (items === null && !failed) {
                body = '<div class="mp-hint">正在為你挑選…</div>';
            } else if (failed) {
                body = '<div class="mp-hint is-error">商品推薦暫時無法使用，請稍後再試。</div>';
            } else if (!items.length) {
                // 0 件是會發生的，不是例外：男士白開水全庫只有約 113 件，
                // 千金妝的打亮只有 6 件。空白畫面會讓人以為壞了。
                body = `<div class="mp-hint">目前沒有適合你的${escapeHtml(style?.name || '')}商品。</div>`;
            } else {
                body = `<div class="mp-section-title">依你的臉部分析，從${escapeHtml(style?.name || '')}商品中為你挑了 ${items.length} 件</div>
                    <div class="prod-grid mp-more-grid">${items.map(p => `
                        <div class="prod-card" data-pid="${escapeHtml(p.id)}">
                            <div class="pc-imgwrap">${phBox('', p.name, p.img)}</div>
                            <div class="pc-cat">${escapeHtml(p.brand || '')}</div>
                            <div class="pc-name">${escapeHtml(p.name)}</div>
                            <div class="pc-foot">
                                <span class="pc-price">${escapeHtml(p.price || '')}</span>
                                ${p.candidateKey ? `<button type="button" class="pc-own${MakeupBag.has(p.candidateKey) ? ' is-own' : ''}"
                                    data-own="${escapeHtml(p.candidateKey)}">${MakeupBag.has(p.candidateKey) ? '已有' : '加入化妝包'}</button>` : ''}
                            </div>
                        </div>`).join('')}</div>`;
            }

            modal.innerHTML = `<div class="makeup-style-dialog">
                <div class="makeup-style-head">
                    <div>
                        <span class="eyebrow">More</span>
                        <h2 id="styleMoreModalTitle">其他${escapeHtml(style?.name || '')}商品</h2>
                        <p>這些是資料庫裡的商品，不在你的化妝包內。</p>
                    </div>
                    <button class="makeup-style-close" type="button" aria-label="關閉">×</button>
                </div>
                ${body}
                <div class="makeup-style-actions">
                    <button class="btn-outline" type="button" data-back>← 回到我的化妝包結果</button>
                </div>
            </div>`;

            modal.querySelector('.makeup-style-close').onclick = () => closeModal('styleMoreModal');
            // 單向道會讓使用者出不去，只能重做一次分析。
            modal.querySelector('[data-back]').onclick = () => {
                closeModal('styleMoreModal');
                if (typeof onBack === 'function') onBack();
            };
            modal.querySelectorAll('.pc-own').forEach(btn => {
                btn.onclick = async (e) => {
                    e.stopPropagation();
                    if (btn.classList.contains('is-own')) return;
                    btn.disabled = true;
                    const result = await MakeupBag.add(btn.dataset.own);
                    btn.disabled = false;
                    if (!result.ok) { showToast(result.error); return; }
                    btn.classList.add('is-own');
                    btn.textContent = '已有';
                    showToast(result.already ? '已經在化妝包裡了' : '已加入化妝包');
                };
            });
        };

        draw();
        Promise.resolve(Api.recommendProducts(Router.analysisPackage, styleId)).then(rec => {
            if (!document.getElementById('styleMoreModal')) return;
            if (!rec || !rec.ok) { failed = true; draw(); return; }
            // 已經在化妝包裡的不再列出來——這一頁的用途是「還可以買什麼」。
            items = (rec.products || []).filter(p => !p.candidateKey || !MakeupBag.has(p.candidateKey));
            draw();
        }).catch(() => { failed = true; draw(); });
    }

    // ── 包在既有視窗外面 ──────────────────────────────────────────
    //
    // 等 makeup-flow.js 把 openMakeupStyleModal 覆寫完之後才包。用 setTimeout(0)
    // 排到目前呼叫堆疊結束，避免依賴 script 標籤的相對順序——那種依賴很脆弱，
    // 有人調整載入順序就會靜默失效。
    function install() {
        if (typeof window.openMakeupStyleModal !== 'function') return false;
        if (window.__openStyleModalDirect) return true;
        window.__openStyleModalDirect = window.openMakeupStyleModal;
        window.openMakeupStyleModal = function (preselectedStyleId) {
            if (MakeupPlan.shouldAsk()) { openMakeupPlanModal(preselectedStyleId); return; }
            if (MakeupPlan.get() === 'makeupBag' && typeof MakeupBag !== 'undefined' && MakeupBag.count()) {
                openBagStyleModal(preselectedStyleId);
                return;
            }
            // 記著要用化妝包、但包被清空了：不要卡住，直接走系統推薦。
            window.__openStyleModalDirect(preselectedStyleId);
        };
        return true;
    }
    if (!install()) setTimeout(install, 0);

    window.MakeupPlan = MakeupPlan;
    window.openMakeupPlanModal = openMakeupPlanModal;
    window.openBagStyleModal = openBagStyleModal;
    window.openStyleMoreModal = openStyleMoreModal;
})(window, document);
