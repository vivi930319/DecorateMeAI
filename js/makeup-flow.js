(function () {
    'use strict';

    if (typeof Router === 'undefined' || typeof PageInit === 'undefined' || !window.MakeupSuggestionContract) return;

    const Contract = window.MakeupSuggestionContract;
    document.documentElement.dataset.makeupFlow = 'ready';

    function getStyle() {
        return STYLES.find(style => style.id === Router.selectedStyleId)
            || STYLES.find(style => style.id === 'richGirl')
            || STYLES[0];
    }

    function contractContext(style) {
        return { palette: Array.isArray(style?.palette) ? style.palette : [] };
    }

    function resolveStructured(pkg, style) {
        const saved = pkg?.generativeText?.structured;
        if (saved?.overall && saved?.parts) return saved;
        const raw = pkg?.generativeText?.suggestion;
        if (!raw) return null;
        try {
            return Contract.normalize({ suggestion: raw }, contractContext(style));
        } catch (_) {
            return null;
        }
    }

    function safeColors(structured) {
        return (Array.isArray(structured?.overall?.palette) ? structured.overall.palette : [])
            .filter(color => /^#[0-9a-f]{3,8}$/i.test(String(color)))
            .slice(0, 6);
    }

    function removeJourneyModal() {
        document.getElementById('journeyModal')?.remove();
    }

    // SPA 換頁不會像傳統頁面載入一樣自動回到頂端。手機從全螢幕流程視窗進入
    // 成果頁時，Safari 會沿用上一頁的垂直位置，畫面因此直接落在人像或標籤中段。
    // 立即重設一次，再等新頁完成兩輪排版後重設一次，避免轉場與圖片版面把位置帶回去。
    function resetSuggestionViewport() {
        try {
            if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
        } catch (_) {}
        const reset = () => window.scrollTo(0, 0);
        reset();
        if (typeof requestAnimationFrame === 'function') {
            requestAnimationFrame(() => requestAnimationFrame(reset));
        }
    }

    function journeyShell(kicker, title, body, actions) {
        removeJourneyModal();
        const modal = document.createElement('div');
        modal.id = 'journeyModal';
        modal.className = 'makeup-style-modal journey-modal open';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.innerHTML = `<div class="makeup-style-dialog journey-dialog">
            <button class="journey-dialog-close" type="button" aria-label="關閉">×</button>
            <div class="makeup-style-head">
                <div><span class="eyebrow">${escapeHtml(kicker)}</span><h2>${escapeHtml(title)}</h2></div>
            </div>
            <div class="journey-body">${body}</div>
            <div class="makeup-style-actions journey-actions">${actions}</div>
        </div>`;
        document.body.appendChild(modal);
        // 手機上內容可能超過視窗高度;右上角 ✕ 一律可關,不必捲到底部按鈕。
        modal.querySelector('.journey-dialog-close')?.addEventListener('click', removeJourneyModal);
        modal.addEventListener('click', event => { if (event.target === modal) removeJourneyModal(); });
        return modal;
    }

    function progressTimeline(items, activeIndex) {
        return `<ol class="beauty-progress-list">${items.map((item, index) => `
            <li class="${index < activeIndex ? 'done' : index === activeIndex ? 'active' : ''}">
                <span class="beauty-progress-dot">${index < activeIndex ? '✓' : String(index + 1).padStart(2, '0')}</span>
                <span><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.note)}</small></span>
            </li>`).join('')}</ol>`;
    }

    runMakeupSuggestion = async function (onProgress) {
        const notify = typeof onProgress === 'function' ? onProgress : () => {};
        const pkg = Router.analysisPackage;
        if (!pkg || !Router.analysisResult) return { ok: false, missingAnalysis: true };
        const style = getStyle();

        try {
            notify(12, '正在了解你的臉部特徵');
            const response = await Api.suggestMakeup({
                faceAnalysis: pkg.faceAnalysis || AnalysisPackage.fromRawFaceAnalysis(Router.analysisResult, Router.analyzeMode),
                style: style.name,
                userNote: style.tags.join('、')
            });
            const structured = Contract.normalize(response, contractContext(style));
            const rawSuggestion = String(response?.suggestion || structured.rawSuggestion || structured.overall.summary || '').trim();
            if (!rawSuggestion && structured.source !== 'structured') {
                throw new Error('Ollama 沒有回傳可顯示的妝容建議。');
            }
            // 這裡原本把 Ollama 的 renderPromptEn 強制寫成 null，且把簽章丟掉。
            // Journey 流程載入本檔後會覆蓋 router.js 的同名核心函式，導致下一步
            // 渲染只能退回固定風格，甚至再次呼叫 Ollama。保留原始 prompt 與簽章，
            // 渲染端才能驗證後使用同一份指令。
            const ollamaRenderPromptEn = String(response?.renderPromptEn || '').trim();

            Router.analysisPackage = AnalysisPackage.update(pkg, {
                generativeText: {
                    provider: response?.provider || 'ollama',
                    model: response?.model || null,
                    suggestion: rawSuggestion || structured.overall.summary,
                    structured,
                    contractSource: structured.source,
                    contractIssues: structured.issues || [],
                    status: 'completed',
                    error: null,
                    fallbackUsed: false,
                    promptSignature: response?.promptSignature || null,
                    promptSignatureVersion: response?.promptSignatureVersion || null,
                    renderPromptEn: ollamaRenderPromptEn
                        ? buildRenderPrompt(pkg.faceAnalysis, Router.selectedStyleId, rawSuggestion, ollamaRenderPromptEn)
                        : null,
                    ollamaRenderPromptEn: ollamaRenderPromptEn || null
                },
                recommendations: {
                    ...(pkg.recommendations || {}),
                    style: style.name
                }
            });

            const recommended = await Api.recommendProducts(Router.analysisPackage, Router.selectedStyleId).catch(() => null);
            // 降級原因與錯誤碼要記下來，商品頁與推薦彈窗才顯示得出提示。
            // 先前這裡只取 products，其餘整包丟掉。
            if (typeof RecommendationNotice !== 'undefined') RecommendationNotice.record(recommended);
            // 三色階不是只給當下的商品頁用；它必須跟推薦商品一起寫回分析資料包，
            // 否則 SPA 換頁、重新整理或從分析結果再次進推薦頁時，
            // Router.shadeRecommendation 一清空，畫面就只剩舊的單一色差區塊。
            // 這裡要保存完整 shadeRecommendation，不能只保存 products。
            if (recommended?.products?.length || recommended?.shadeRecommendation?.anchor) {
                Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                    recommendations: {
                        ...(Router.analysisPackage.recommendations || {}),
                        style: style.name,
                        ...(recommended?.products?.length ? { products: recommended.products } : {}),
                        shadeRecommendation: recommended?.shadeRecommendation || null
                    }
                });
            }

            AnalysisDraft.save(Router.analysisPackage);
            Router.pendingLook = buildCurrentLookRecord();
            Router.pendingLookSaved = false;
            notify(100, '專屬建議已完成');
            return { ok: true, response, structured };
        } catch (error) {
            Router.analysisPackage = AnalysisPackage.update(pkg, {
                generativeText: { ...(pkg.generativeText || {}), status: 'failed', error: error.message }
            });
            AnalysisDraft.save(Router.analysisPackage);
            return { ok: false, error };
        }
    };

    function paletteHtml(structured) {
        const colors = safeColors(structured);
        if (!colors.length) return '';
        const label = structured.overall.paletteSource === 'response' ? 'Ollama 回傳色系' : '所選風格色系';
        return `<div class="journey-palette" aria-label="${escapeHtml(label)}">${colors
            .map(color => `<span style="background:${color}"></span>`).join('')}</div>`;
    }

    function openAdviceReadyModal() {
        const style = getStyle();
        const structured = resolveStructured(Router.analysisPackage, style);
        if (!structured) {
            showAlert('妝容建議格式不完整，請重新產生。', { type: 'error' });
            return;
        }
        const body = `<div class="journey-ready-card">
            <span class="journey-ready-check">✓</span>
            <div><b>${escapeHtml(style.name)}妝容建議已完成</b><p>${escapeHtml(structured.overall.summary)}</p></div>
        </div>
        ${paletteHtml(structured)}
        <p class="journey-next-note">下一步會根據這份建議產生妝容圖片，通常需要 60–150 秒。</p>`;
        const modal = journeyShell('MAKEUP SUGGESTION', '妝容建議完成', body,
            '<button class="btn-outline" type="button" data-back>上一步</button><button class="btn-gold" type="button" data-render>開始妝容渲染 →</button>');
        modal.querySelector('[data-back]').onclick = () => {
            removeJourneyModal();
            openMakeupStyleModal(Router.selectedStyleId);
        };
        modal.querySelector('[data-render]').onclick = openRenderJourneyModal;
    }

    function openSuggestionJourneyModal() {
        const style = getStyle();
        const steps = [
            { title: '了解你的臉部特徵', note: '整理輪廓、五官與膚色重點' },
            { title: `搭配${style.name}風格`, note: '選出適合的色彩與妝感' },
            { title: '完成專屬妝容建議', note: '整理整體方向與五個部位做法' }
        ];
        let active = 0;
        const body = `<div id="journeyProgress">${progressTimeline(steps, active)}</div><p class="journey-wait-note">建議正在整理中，完成後就能進行妝容渲染。</p>`;
        // 等待中不顯示右邊那顆按鈕。
        //
        // 先前是一顆 disabled、寫著「請稍候」的金色按鈕。它看起來像主要動作，
        // 但按不下去，而且**成功時根本用不到**——完成會直接開下一個視窗。
        // 它只有在失敗時才會變成「重新產生」。
        // 一顆等在那裡卻不能按的主按鈕，只會讓人一直去試它。
        // 這裡只留「上一步」。
        //
        // 先前等待時是一顆 disabled 的「請稍候」，失敗時變成「重新產生」。
        // 兩個都不該在：進到這一步就代表建議已經在跑了，再給一顆「重新產生」
        // 等於把同一件事再問一次；而失敗時真正有用的動作是回上一步換個風格
        // 或重新分析，那顆按鈕本來就在旁邊。
        const modal = journeyShell('MAKEUP SUGGESTION', '正在產生妝容建議', body,
            '<button class="btn-outline" type="button" data-back>上一步</button>');
        modal.querySelector('[data-back]').onclick = () => {
            removeJourneyModal();
            openMakeupStyleModal(Router.selectedStyleId);
        };
        const painter = modal.querySelector('#journeyProgress');
        const timer = setInterval(() => {
            active = Math.min(2, active + 1);
            if (painter) painter.innerHTML = progressTimeline(steps, active);
        }, 1200);

        runMakeupSuggestion().then(result => {
            clearInterval(timer);
            if (!document.getElementById('journeyModal')) return;
            if (!result.ok) {
                // 失敗就把原因寫在說明那一行，出口是旁邊的「上一步」。
                const note = modal.querySelector('.journey-wait-note');
                note.textContent = result.missingAnalysis
                    ? '目前沒有臉部分析結果，請先回到臉部分析。'
                    : `目前無法完成建議：${result.error?.message || '服務暫時無法使用'}`;
                return;
            }
            if (painter) painter.innerHTML = progressTimeline(steps, steps.length);
            setTimeout(openAdviceReadyModal, 350);
        });
    }

    function openRenderJourneyModal() {
        const style = getStyle();
        const steps = [
            { title: '保留原有五官', note: '維持臉型、表情與人物辨識度' },
            { title: `套用${style.name}妝感`, note: '依照文字建議完成色彩與層次' },
            { title: '整理妝容細節', note: '完成底妝、眉眼、腮紅與唇色' }
        ];
        let active = 0;
        const body = `<div id="renderJourneyProgress">${progressTimeline(steps, active)}</div>
            <div class="render-estimate"><span class="render-spinner" aria-hidden="true"></span><div><b>正在生成妝容圖片</b><small>一般需要 60–150 秒，請保持此頁開啟。</small></div><strong id="renderJourneyPct">1%</strong></div>`;
        const modal = journeyShell('MAKEUP RENDER', '妝容渲染中', body,
        // 這裡也只留「上一步」。
        //
        // 渲染走 Replicate，一次要 60–150 秒而且按次計費。一顆放在失敗訊息旁邊的
        // 「重新生成」，最容易被連按——而失敗多半不是按一次就會好的原因
        // （服務忙碌、額度、上游逾時），連按只是把同一個錯誤重打好幾次。
        // 真的要再試，從「上一步」走回去——那要多按兩下，而多按兩下正是重點：
        // 重試應該是一個決定，不是一個反射動作。
        //
        // 額度本身由 runMakeupRender 裡的 UsageQuota 擋（訪客每天 2 次、會員 4 次，
        // 與妝容建議分開計算），那是每一次渲染都會走到的地方，不分入口。
        // 所以拿掉這顆按鈕不是在補額度的漏洞，是在減少「按了也沒用的重試」。
            '<button class="btn-outline" type="button" data-back>上一步</button>');
        modal.querySelector('[data-back]').onclick = openAdviceReadyModal;
        const painter = modal.querySelector('#renderJourneyProgress');
        const pct = modal.querySelector('#renderJourneyPct');

        runMakeupRender(progress => {
            const value = Number.isFinite(Number(progress)) ? Number(progress) : 1;
            const nextActive = value < 35 ? 0 : value < 75 ? 1 : 2;
            if (nextActive !== active) {
                active = nextActive;
                if (painter) painter.innerHTML = progressTimeline(steps, active);
            }
            if (pct) pct.textContent = `${Math.max(1, Math.round(value))}%`;
        }).then(outcome => {
            if (!document.getElementById('journeyModal')) return;
            if (!outcome.ok && handleRenderBlocked(outcome.reason)) {
                removeJourneyModal();
                return;
            }
            if (!outcome.ok) {
                // 失敗就把原因寫在進度那一行，出口是旁邊的「上一步」。
                const estimate = modal.querySelector('.render-estimate b');
                if (estimate) estimate.textContent = `生成失敗：${outcome.error?.message || '服務暫時無法使用'}`;
                return;
            }
            if (painter) painter.innerHTML = progressTimeline(steps, steps.length);
            if (pct) pct.textContent = '100%';
            const title = modal.querySelector('.makeup-style-head h2');
            if (title) title.textContent = '妝容渲染完成';
            // 成功就直接帶過去，不要再要求按一次「查看妝容結果」。
            //
            // 使用者剛等了一兩分鐘，那一刻他要的就是看結果——中間再隔一個動作，
            // 只是把「完成」這件事重複講兩遍。停 600ms 讓「渲染完成」與 100%
            // 看得到，然後走。
            //
            // 回妝容建議：那裡有妝前妝後、五個部位的做法與收藏，是這次結果的完整樣貌。
            setTimeout(() => {
                removeJourneyModal();
                Router.go('suggestion');
            }, 600);
        });
    }

    openMakeupStyleModal = function (preselectedStyleId) {
        if (!hasStartedJourney()) { Router.go('analysis'); return; }
        let modal = document.getElementById('makeupStyleModal');
        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'makeupStyleModal';
            modal.className = 'makeup-style-modal';
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-modal', 'true');
            modal.setAttribute('aria-labelledby', 'makeupStyleModalTitle');
            document.body.appendChild(modal);
        }
        pendingStyleModalSelection = preselectedStyleId || Router.selectedStyleId || null;

        const draw = () => {
            modal.innerHTML = `<div class="makeup-style-dialog"><div class="makeup-style-head"><div><span class="eyebrow">Style</span><h2 id="makeupStyleModalTitle">選擇妝容風格</h2><p>選擇一款風格，接著產生你的專屬妝容建議。</p></div><button class="makeup-style-close" type="button" aria-label="關閉">×</button></div><div class="makeup-style-grid">${STYLES.map(style => `<button class="makeup-style-option ${pendingStyleModalSelection === style.id ? 'selected' : ''}" type="button" data-style-id="${escapeHtml(style.id)}"><img src="${escapeHtml(style.img)}" alt="${escapeHtml(style.name)}"><span class="makeup-style-option-copy"><b>${escapeHtml(style.name)}</b><small>${style.tags.map(escapeHtml).join(' · ')}</small></span></button>`).join('')}</div><div class="makeup-style-actions"><button class="btn-outline" type="button" data-modal-cancel>上一步</button><button class="btn-gold" type="button" data-modal-confirm ${pendingStyleModalSelection ? '' : 'disabled'}>產生妝容建議 →</button></div></div>`;
            modal.querySelectorAll('[data-style-id]').forEach(button => {
                button.onclick = () => {
                    pendingStyleModalSelection = button.dataset.styleId;
                    draw();
                };
            });
            modal.querySelector('.makeup-style-close').onclick = closeMakeupStyleModal;
            modal.querySelector('[data-modal-cancel]').onclick = closeMakeupStyleModal;
            modal.querySelector('[data-modal-confirm]').onclick = () => {
                if (!pendingStyleModalSelection) return;
                Router.selectedStyleId = pendingStyleModalSelection;
                Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                    recommendations: { ...(Router.analysisPackage?.recommendations || {}), style: getStyle().name }
                });
                closeMakeupStyleModal();
                openSuggestionJourneyModal();
            };
        };
        draw();
        modal.classList.add('open');
    };

    function partFallbackText(label, field) {
        if (field === 'analysis') return `本次 Ollama 回傳沒有獨立的${label}分析說明。`;
        if (field === 'steps') return `本次 Ollama 回傳沒有可對應到${label}的獨立操作步驟。`;
        return `本次 Ollama 回傳沒有可對應到${label}的避免事項。`;
    }

    function openPartAdviceModal(partKey) {
        const style = getStyle();
        const structured = resolveStructured(Router.analysisPackage, style);
        const advice = structured?.parts?.[partKey];
        if (!advice) return;
        const steps = Array.isArray(advice.steps) ? advice.steps.filter(Boolean) : [];
        const partAvoid = Array.isArray(advice.avoid) ? advice.avoid.filter(Boolean) : [];
        const globalAvoid = Array.isArray(structured.globalAvoid) ? structured.globalAvoid.filter(Boolean) : [];
        const avoidList = partAvoid.length ? partAvoid : globalAvoid;
        const avoidTitle = partAvoid.length ? '避免' : (globalAvoid.length ? '整體避免事項' : '避免');
        const stepsHtml = steps.length
            ? `<ol>${steps.map(step => `<li>${escapeHtml(step)}</li>`).join('')}</ol>`
            : `<p>${escapeHtml(partFallbackText(advice.label, 'steps'))}</p>`;
        const avoidText = avoidList.length ? avoidList.join(' ') : partFallbackText(advice.label, 'avoid');
        const modal = journeyShell('LOOK SUGGESTION', `${advice.label}建議`, `
            <div class="part-advice-analysis"><span>分析</span><p>${escapeHtml(advice.analysis || partFallbackText(advice.label, 'analysis'))}</p></div>
            <div class="part-advice-section"><h3>建議做法</h3>${stepsHtml}</div>
            <div class="part-advice-avoid"><b>${escapeHtml(avoidTitle)}</b><p>${escapeHtml(avoidText)}</p></div>`,
            '<button class="btn-gold" type="button" data-close>看完了</button>');
        modal.querySelector('[data-close]').onclick = removeJourneyModal;
        // backdrop 與右上 ✕ 的關閉已由 journeyShell 統一處理。
    }

    function renderResumeCard(area, structured, hasRender) {
        const style = getStyle();
        if (!structured) {
            area.innerHTML = `<section class="lookbook-result journey-resume-card"><span class="eyebrow">MAKEUP JOURNEY</span><h2>從妝容風格開始</h2><p>完成臉部分析後，先選擇妝容風格，再產生個人化文字建議。</p><div class="lookbook-actions"><button class="btn-gold" type="button" data-resume-style>選擇妝容風格 →</button></div></section>`;
            area.querySelector('[data-resume-style]').onclick = () => openMakeupStyleModal(Router.selectedStyleId);
            return;
        }
        if (!hasRender) {
            area.innerHTML = `<section class="lookbook-result journey-resume-card"><span class="eyebrow">MAKEUP SUGGESTION</span><h2>${escapeHtml(style.name)}妝容建議已完成</h2><p>${escapeHtml(structured.overall.summary)}</p>${paletteHtml(structured)}<div class="lookbook-actions"><button class="btn-outline" type="button" data-resume-style>重新選擇風格</button><button class="btn-gold" type="button" data-resume-render>開始妝容渲染 →</button></div></section>`;
            area.querySelector('[data-resume-style]').onclick = () => openMakeupStyleModal(Router.selectedStyleId);
            area.querySelector('[data-resume-render]').onclick = openRenderJourneyModal;
        }
    }

    PageInit.suggestion = function () {
        resetSuggestionViewport();
        if (!hasStartedJourney()) { renderAnalysisGate('妝容建議'); return; }
        const area = document.getElementById('suggestionArea');
        if (!area) return;
        const style = getStyle();
        const structured = resolveStructured(Router.analysisPackage, style);
        const pkg = Router.analysisPackage || {};
        const render = pkg.render || {};
        const before = pkg.images?.front?.compressedDataUrl
            || pkg.images?.front?.dataUrl
            || render.beforeImageUrl
            || render.beforeImageDataUrl
            || '';
        const after = render.afterImageUrl
            || render.afterImageDataUrl
            || render.makeupOutput?.imageUrl
            || render.makeupOutput?.imageDataUrl
            || '';

        if (!structured || !after) {
            renderResumeCard(area, structured, !!after);
            return;
        }

        const pinLayout = [
            { key: 'brow', side: 'left', slot: 'top' },
            { key: 'base', side: 'left', slot: 'middle' },
            { key: 'contour', side: 'left', slot: 'bottom' },
            { key: 'eyes', side: 'right', slot: 'top' },
            { key: 'lips', side: 'right', slot: 'bottom' }
        ];
        const pin = item => {
            const label = structured.parts?.[item.key]?.label || item.key;
            return `<button class="look-pin ${item.side} ${item.slot}" type="button" data-look-part="${item.key}"><span>${escapeHtml(label)}</span><i aria-hidden="true"></i></button>`;
        };
        const colors = safeColors(structured);
        const title = structured.overall.title || `${style.name}妝容建議`;
        area.innerHTML = `
            <section class="lookbook-result">
                <div class="lookbook-heading">
                    <div><span class="eyebrow">MAKEUP LOOKBOOK</span><h2>${escapeHtml(title)}</h2></div>
                    ${colors.length ? `<div class="lookbook-palette">${colors.map(color => `<span style="background:${color}"></span>`).join('')}</div>` : ''}
                </div>
                <p class="lookbook-summary">${escapeHtml(structured.overall.summary)}</p>
                <div class="look-map-shell">
                    <div class="look-pin-lane left-lane">${pinLayout.filter(item => item.side === 'left').map(pin).join('')}</div>
                    <figure class="look-portrait-frame">
                        <img id="lookPortrait" src="${escapeHtml(after)}" alt="${escapeHtml(style.name)}妝後效果">
                        <figcaption id="lookPhotoCaption">妝後</figcaption>
                    </figure>
                    <div class="look-pin-lane right-lane">${pinLayout.filter(item => item.side === 'right').map(pin).join('')}</div>
                </div>
                <div class="look-photo-switch" role="group" aria-label="切換妝前妝後">
                    <button type="button" data-photo="before" ${before ? '' : 'disabled'}>妝前</button>
                    <button type="button" class="active" data-photo="after">妝後</button>
                </div>
                <p class="look-pin-hint">點選人像兩側的部位標籤，查看本次 Ollama 回傳所對應的妝容做法。</p>
                <div class="lookbook-actions">
                    <button class="btn-outline" type="button" data-prev-style>上一步：重新選擇風格</button>
                    <button class="btn-outline" type="button" data-save-look>收藏這次妝容</button>
                    <button class="btn-gold" type="button" data-products>查看推薦商品 →</button>
                </div>
            </section>`;

        const portrait = area.querySelector('#lookPortrait');
        const caption = area.querySelector('#lookPhotoCaption');
        area.querySelectorAll('[data-photo]').forEach(button => {
            button.onclick = () => {
                const isAfter = button.dataset.photo === 'after';
                const source = isAfter ? after : before;
                if (!source) return;
                portrait.src = source;
                portrait.alt = `${style.name}${isAfter ? '妝後效果' : '妝前照片'}`;
                caption.textContent = isAfter ? '妝後' : '妝前';
                area.querySelectorAll('[data-photo]').forEach(item => item.classList.toggle('active', item === button));
            };
        });
        area.querySelectorAll('[data-look-part]').forEach(button => {
            button.onclick = () => openPartAdviceModal(button.dataset.lookPart);
        });
        area.querySelector('[data-prev-style]').onclick = () => openMakeupStyleModal(Router.selectedStyleId);
        area.querySelector('[data-save-look]').onclick = openSaveLookModal;
        area.querySelector('[data-products]').onclick = openProductRecommendationModal;
    };

    window.MakeupFlowUI = {
        openSuggestionJourneyModal,
        openRenderJourneyModal,
        openAdviceReadyModal
    };
})();
