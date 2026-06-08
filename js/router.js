// ═══ SPA Router ═══
// 每個 page 是一個 HTML fragment，由 fetch 載入 main-content
const Router = {
    currentPage: null,
    analysisResult: null,
    analyzeMode: 'basic',
    selectedFile: null,
    analysisPackage: null,
    packageImageFiles: {},
    proFiles: { front: null, left45: null, right45: null, side: null },
    cameraStream: null,
    selectedStyleId: null,
    pendingRegister: null,
    latestRenderedAfter: false,
    currentCategory: null,

    async go(page, opts) {
        try {
            const res = await fetch(`pages/${page}.html?v=20260608-ios-sync`, { cache: 'no-store' });
            if (!res.ok) throw new Error('Page not found');
            const html = await res.text();
            document.getElementById('mainContent').innerHTML = html;
            this.currentPage = page;
            // 更新 sidebar active
            document.querySelectorAll('.sidebar-nav a').forEach(a => {
                a.classList.toggle('active', a.dataset.page === page);
            });
            // 頁面初始化
            if (typeof PageInit[page] === 'function') PageInit[page](opts);
        } catch (e) {
            document.getElementById('mainContent').innerHTML = `<div class="empty-state">頁面載入失敗</div>`;
        }
    }
};

// ═══ 每頁的初始化邏輯 ═══
const PageInit = {
    dashboard() {
        document.querySelectorAll('[data-nav]').forEach(el => {
            el.onclick = () => Router.go(el.dataset.nav);
        });
    },

    analysis() {
        const fileInput = document.getElementById('fileInput');
        const uploadBox = document.getElementById('uploadBox');
        const preview = document.getElementById('preview');
        const analyzeBtn = document.getElementById('analyzeBtn');
        const bar = document.getElementById('loadingBar');
        const fill = document.getElementById('loadingFill');
        const loadingStatus = document.getElementById('loadingStatus');
        const packageStatus = document.getElementById('packageStatus');
        const basicPanel = document.getElementById('basicPanel');
        const proPanel = document.getElementById('proPanel');
        const basicModeBtn = document.getElementById('basicModeBtn');
        const proModeBtn = document.getElementById('proModeBtn');

        Router.analyzeMode = Router.analyzeMode || 'basic';
        Router.proFiles = Router.proFiles || { front: null, left45: null, right45: null, side: null };
        Router.analysisPackage = AnalysisDraft.load() || Router.analysisPackage;

        const setLoadingStatus = (text, active = false) => {
            if (!loadingStatus) return;
            loadingStatus.textContent = text;
            loadingStatus.classList.toggle('active', active);
        };

        const updatePackageStatus = () => {
            if (!packageStatus) return;
            const pkg = Router.analysisPackage;
            packageStatus.classList.toggle('ready', !!pkg);
            packageStatus.querySelector('span').textContent = pkg
                ? `${pkg.mode.toUpperCase()} · ${pkg.status} · ${Object.keys(pkg.images || {}).length} 張`
                : '尚未建立';
        };

        const fileMeta = (file, role) => ({
            role,
            serial: `${role}-${Date.now()}`,
            originalName: file.name,
            originalType: file.type,
            originalSize: file.size,
            compressedSize: null,
            width: null,
            height: null,
            compressedWidth: null,
            compressedHeight: null,
            compressionRatio: null
        });

        const compressImagesForPackage = async () => {
            const files = Router.analyzeMode === 'basic'
                ? { front: Router.selectedFile }
                : Router.proFiles;
            const images = {};
            Router.packageImageFiles = {};
            for (const [role, file] of Object.entries(files)) {
                if (!file) continue;
                const compressed = await ImagePipeline.compressForPackage(file, { role });
                Router.packageImageFiles[role] = compressed.file;
                images[role] = {
                    ...compressed.meta,
                    compressedDataUrl: compressed.dataUrl && compressed.dataUrl.length < 900000 ? compressed.dataUrl : null
                };
            }
            return images;
        };

        const saveDraft = (status = 'draft') => {
            const images = {};
            if (Router.analyzeMode === 'basic' && Router.selectedFile) {
                images.front = fileMeta(Router.selectedFile, 'front');
            }
            if (Router.analyzeMode === 'pro') {
                Object.entries(Router.proFiles).forEach(([role, file]) => {
                    if (file) images[role] = fileMeta(file, role);
                });
            }
            Router.analysisPackage = AnalysisPackage.create({ mode: Router.analyzeMode, images, status });
            AnalysisDraft.save(Router.analysisPackage);
            updatePackageStatus();
        };

        const showPreview = (file) => {
            const reader = new FileReader();
            reader.onload = ev => { preview.src = ev.target.result; preview.style.display = 'block'; };
            reader.readAsDataURL(file);
        };

        const setMode = (mode) => {
            Router.analyzeMode = mode;
            basicModeBtn.classList.toggle('active', mode === 'basic');
            proModeBtn.classList.toggle('active', mode === 'pro');
            basicPanel.classList.toggle('active', mode === 'basic');
            proPanel.classList.toggle('active', mode === 'pro');
            analyzeBtn.textContent = mode === 'basic' ? '開 始 分 析' : '開 始 PRO 分 析';
            setLoadingStatus('等待圖片');
            updatePackageStatus();
        };

        basicModeBtn.onclick = () => setMode('basic');
        proModeBtn.onclick = () => setMode('pro');
        setMode(Router.analyzeMode);

        uploadBox.onclick = () => fileInput.click();
        fileInput.onchange = (e) => {
            const file = e.target.files[0];
            if (!file) return;
            Router.selectedFile = file;
            showPreview(file);
            saveDraft('image-selected');
        };

        document.querySelectorAll('[data-pro-slot]').forEach(slot => {
            const key = slot.dataset.proSlot;
            const input = document.getElementById(`${key}Input`);
            const nameEl = document.getElementById(`${key}FileName`);
            slot.onclick = () => input.click();
            input.onchange = (e) => {
                const file = e.target.files[0];
                if (!file) return;
                Router.proFiles[key] = file;
                nameEl.textContent = file.name;
                if (key === 'front') {
                    Router.selectedFile = file;
                    showPreview(file);
                }
                saveDraft('image-selected');
            };
        });

        document.getElementById('startCameraBtn').onclick = async () => {
            try {
                if (Router.cameraStream) return;
                Router.cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
                const video = document.getElementById('cameraVideo');
                video.srcObject = Router.cameraStream;
                document.getElementById('cameraBox').classList.add('active');
            } catch (err) {
                alert('無法開啟鏡頭：' + err.message);
            }
        };

        document.getElementById('capturePhotoBtn').onclick = () => {
            const video = document.getElementById('cameraVideo');
            if (!Router.cameraStream || !video.videoWidth) {
                alert('請先開啟鏡頭');
                return;
            }
            const canvas = document.getElementById('cameraCanvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            canvas.getContext('2d').drawImage(video, 0, 0);
            canvas.toBlob(blob => {
                if (!blob) {
                    alert('拍照失敗');
                    return;
                }
                Router.selectedFile = new File([blob], 'basic-camera.jpg', { type: 'image/jpeg' });
                showPreview(Router.selectedFile);
                saveDraft('camera-captured');
            }, 'image/jpeg', 0.92);
        };

        analyzeBtn.onclick = async () => {
            if (Router.analyzeMode === 'basic' && !Router.selectedFile) {
                alert('請先選擇照片或拍照');
                return;
            }
            if (Router.analyzeMode === 'pro' && !Router.proFiles.front) {
                alert('PRO 分析至少需要正面照');
                return;
            }
            const startedAt = Date.now();
            if (!Router.analysisPackage) saveDraft('queued');
            Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                status: 'preparing-image',
                async: { ...Router.analysisPackage.async, startedAt: new Date(startedAt).toISOString(), error: null }
            });
            AnalysisDraft.save(Router.analysisPackage);
            updatePackageStatus();
            setLoadingStatus('原圖送出分析中', true);
            bar.style.display = 'block'; fill.style.width = '30%';
            try {
                Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, { status: 'analyzing' });
                AnalysisDraft.save(Router.analysisPackage);
                updatePackageStatus();
                setLoadingStatus('已送出原圖，等待臉部模型回傳', true);
                fill.style.width = '60%';
                const response = Router.analyzeMode === 'basic'
                    ? await Api.analyzeFace(Router.selectedFile)
                    : await Api.analyzeFacePro(Router.proFiles);
                const data = response.data || response;
                Router.analysisResult = data;
                setLoadingStatus('分析完成，正在壓縮圖片並封裝資料包', true);
                const packagedImages = await compressImagesForPackage();
                const completedAt = Date.now();
                Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                    status: 'completed',
                    images: packagedImages,
                    analysis: {
                        ...Router.analysisPackage.analysis,
                        [Router.analyzeMode]: data
                    },
                    generativeText: {
                        ...Router.analysisPackage.generativeText,
                        prompt: null,
                        suggestion: null,
                        status: 'ready-for-text-ai'
                    },
                    render: {
                        ...Router.analysisPackage.render,
                        beforeImageId: packagedImages.front?.serial || null,
                        styleId: Router.selectedStyleId
                    },
                    async: {
                        ...Router.analysisPackage.async,
                        completedAt: new Date(completedAt).toISOString(),
                        durationMs: completedAt - startedAt,
                        error: null
                    }
                });
                AnalysisDraft.save(Router.analysisPackage);
                updatePackageStatus();
                fill.style.width = '100%';
                setLoadingStatus('資料包已完成：壓縮照片 + 分析 JSON，等待文字建議', false);
                setTimeout(() => { bar.style.display = 'none'; fill.style.width = '0'; }, 400);

                document.getElementById('r-face').textContent = data['臉型'] || '—';
                document.getElementById('r-brow').textContent = data['眉型'] || '—';
                document.getElementById('r-eye').textContent = data['眼型'] || '—';
                document.getElementById('r-nose').textContent = data['鼻型'] || '—';
                document.getElementById('r-lip').textContent = data['嘴型'] || '—';
                document.getElementById('r-season').textContent = data['膚色']?.['四季型'] || '—';

                const skin = data['膚色'] || {}, lab = skin['LAB'] || {};
                document.getElementById('skinName').textContent = skin['膚色分級'] || '—';
                document.getElementById('skinLab').textContent = `L ${lab.L||0} a ${lab.a||0} b ${lab.b||0}`;
                document.getElementById('skinSwatch').style.background = Api.labToRgb(lab.L||50, lab.a||0, lab.b||0);

                const lipLab = data['嘴唇_LAB'] || {};
                document.getElementById('lipLab').textContent = `L ${lipLab.L||0} a ${lipLab.a||0} b ${lipLab.b||0}`;
                document.getElementById('lipSwatch').style.background = Api.labToRgb(lipLab.L||40, lipLab.a||0, lipLab.b||0);

                document.getElementById('goStyleBtn').style.display = 'inline-block';
                History.add({ ...data, analysisPackageId: Router.analysisPackage.id });
            } catch (err) {
                bar.style.display = 'none'; fill.style.width = '0';
                Router.analysisPackage = AnalysisPackage.update(Router.analysisPackage, {
                    status: 'failed',
                    async: { ...Router.analysisPackage.async, error: err.message }
                });
                AnalysisDraft.save(Router.analysisPackage);
                updatePackageStatus();
                setLoadingStatus('分析失敗，已保留草稿狀態', false);
                alert('分析失敗：' + err.message);
            }
        };

        document.getElementById('goStyleBtn').onclick = () => Router.go('style');
        updatePackageStatus();
    },

    style() {
        const grid = document.getElementById('styleGrid');
        const renderGrid = () => {
            grid.innerHTML = STYLES.map(s => `
                <div class="style-card ${Router.selectedStyleId===s.id?'selected':''}" data-sid="${s.id}">
                    <div class="sc-name">${s.name}</div>
                    <div class="sc-tags">${s.tags.map(t=>`<span class="sc-tag">${t}</span>`).join('')}</div>
                </div>
            `).join('');
            grid.querySelectorAll('.style-card').forEach(card => {
                card.onclick = () => { Router.selectedStyleId = card.dataset.sid; renderGrid(); };
            });
        };
        renderGrid();

        document.getElementById('confirmStyleBtn').onclick = () => {
            if (!Router.selectedStyleId) { alert('請先選擇風格'); return; }
            renderAnalysisResult();
        };

        function renderAnalysisResult() {
            const style = STYLES.find(s => s.id === Router.selectedStyleId);
            const advice = style.advice || defaultAdvice();
            const palette = style.palette || ['#D8B69E', '#B97970', '#7C544A'];
            const r = Router.analysisResult || {};
            const skin = r['膚色'] || {};
            const container = document.getElementById('styleResultArea');
            container.innerHTML = `
                <h2 style="font-family:'Cormorant Garamond',serif;font-size:24px;text-align:center;margin:24px 0 16px;">
                    ⭐ ${style.name} 妝容分析指南
                </h2>
                <div class="analysis-tags" style="justify-content:center;">
                    ${style.tags.map(t=>`<span class="analysis-tag">${t}</span>`).join('')}
                </div>
                <div class="style-intro-card">
                    <h3>${style.name} 妝容介紹</h3>
                    <p>${style.intro || '此風格介紹尚待補充。'}</p>
                    <div class="palette-row">${palette.map(c => `<span style="background:${c}"></span>`).join('')}</div>
                </div>
                <div class="makeup-category-grid">
                    ${MAKEUP_CATEGORIES.map(c => `<div><b>${c.icon}</b><span>${c.title}</span></div>`).join('')}
                </div>
                <div class="analysis-section">
                    <h3>五官與膚色分析</h3>
                    <div class="analysis-item"><span class="ai-label">臉型</span><span class="ai-value">${r['臉型']||'—'}</span></div>
                    <div class="analysis-item"><span class="ai-label">眉型</span><span class="ai-value">${r['眉型']||'—'}</span></div>
                    <div class="analysis-item"><span class="ai-label">眼型</span><span class="ai-value">${r['眼型']||'—'}</span></div>
                    <div class="analysis-item"><span class="ai-label">鼻型</span><span class="ai-value">${r['鼻型']||'—'}</span></div>
                    <div class="analysis-item"><span class="ai-label">嘴型</span><span class="ai-value">${r['嘴型']||'—'}</span></div>
                    <div class="analysis-item"><span class="ai-label">膚色</span><span class="ai-value">${skin['膚色分級']||'—'} / ${skin['四季型']||'—'}</span></div>
                </div>
                <div class="analysis-section">
                    <h3>專屬妝容建議</h3>
                    <div class="advice-grid">
                        <div><b>底妝建議</b><p>${advice.base}</p></div>
                        <div><b>眉型建議</b><p>${advice.brow}</p></div>
                        <div><b>眼妝建議</b><p>${advice.eye}</p></div>
                        <div><b>腮紅 & 修容</b><p>${advice.blush}</p></div>
                        <div><b>唇妝建議</b><p>${advice.lip}</p></div>
                    </div>
                </div>
                <div style="text-align:center;margin-top:20px;">
                    <button class="btn-outline" onclick="Router.go('compare')" style="margin-right:8px;">查看前後對比</button>
                    <button class="btn-outline" onclick="Router.go('suggestion')" style="margin-right:8px;">收藏妝容建議</button>
                    <button class="btn-gold" onclick="Router.go('products')">查看推薦商品 →</button>
                </div>
            `;
        }

        function defaultAdvice() {
            return { base:'清透柔霧底妝', brow:'自然平眉', eye:'柔霧大地色', blush:'甜感腮紅', lip:'紅色系' };
        }
    },

    products(opts) {
        if (opts && opts.category) {
            renderProductList(opts.category);
        } else if (opts && opts.productId) {
            renderProductDetail(opts.productId);
        } else {
            renderCategoryGrid();
        }

        function renderCategoryGrid() {
            const area = document.getElementById('productsArea');
            area.innerHTML = `
                <div class="page-header"><h1>商品分類</h1><div class="divider"></div></div>
                <div class="cat-grid">
                    ${CATEGORIES.map(c => `<div class="cat-card" data-cat="${c.id}"><div class="cc-icon">${c.icon}</div><div class="cc-name">${c.id}</div></div>`).join('')}
                </div>
            `;
            area.querySelectorAll('.cat-card').forEach(card => {
                card.onclick = () => { Router.currentCategory = card.dataset.cat; renderProductList(card.dataset.cat); };
            });
        }

        function renderProductList(cat) {
            const products = ALL_PRODUCTS.filter(p => p.cat === cat);
            const area = document.getElementById('productsArea');
            area.innerHTML = `
                <div class="page-header">
                    <p><a href="#" onclick="PageInit.products();return false;" style="color:var(--gold);text-decoration:none;">← 返回分類</a></p>
                    <h1>${cat}</h1><div class="divider"></div>
                </div>
                ${products.map(p => `
                    <div class="product-row" data-pid="${p.id}">
                        <div class="product-thumb">🧴</div>
                        <div class="product-info"><div class="pname">${p.name}</div><div class="pprice">${p.price}</div></div>
                        <button class="heart-btn ${Fav.has(p.id)?'fav':''}" data-fav="${p.id}">${Fav.has(p.id)?'❤️':'🤍'}</button>
                    </div>
                `).join('')}
            `;
            area.querySelectorAll('.product-row').forEach(row => {
                row.onclick = (e) => { if (!e.target.closest('.heart-btn')) renderProductDetail(+row.dataset.pid); };
            });
            area.querySelectorAll('.heart-btn').forEach(btn => {
                btn.onclick = (e) => { e.stopPropagation(); Fav.toggle(+btn.dataset.fav); renderProductList(cat); };
            });
        }

        function renderProductDetail(id) {
            const p = ALL_PRODUCTS.find(x => x.id === id);
            if (!p) return;
            const area = document.getElementById('productsArea');
            area.innerHTML = `
                <div class="page-header">
                    <p><a href="#" onclick="PageInit.products({category:'${p.cat}'});return false;" style="color:var(--gold);text-decoration:none;">← 返回 ${p.cat}</a></p>
                </div>
                <div class="product-detail-card">
                    <div class="product-hero">
                        <div class="product-hero-sky"></div>
                        <div class="product-hero-ground"></div>
                        <div class="product-hero-label">商品圖</div>
                    </div>
                    <div class="product-detail-body">
                        <div class="product-detail-head">
                            <div>
                                <div class="product-detail-name">${p.name}</div>
                                <div class="product-detail-price">${p.price}</div>
                                <div class="product-detail-cat">適合妝容：${STYLES.find(s => s.id === Router.selectedStyleId)?.name || '通用'}</div>
                            </div>
                            <button class="heart-btn ${Fav.has(p.id)?'fav':''}" style="font-size:30px;" onclick="Fav.toggle(${p.id});PageInit.products({productId:${p.id}});">
                                ${Fav.has(p.id)?'❤️':'🤍'}
                            </button>
                        </div>
                        <div class="detail-pill">商品介紹</div>
                        <p class="detail-copy">此商品可搭配目前選擇的妝容風格，用於完成對應部位的色彩與質地。後續可接正式商品資料庫、成分說明與購買連結。</p>
                        <div class="review-row">
                            <span class="detail-pill">用戶評價</span>
                            <span class="stars">★★★★★</span>
                        </div>
                        <div class="review-box">
                            <b>用戶名稱：Name</b>
                            <p>質地、顯色度與持妝度評論區預留。之後可串接真實評價 API。</p>
                        </div>
                    </div>
                </div>
            `;
        }
    },

    favorites() {
        const items = ALL_PRODUCTS.filter(p => Fav.has(p.id));
        const area = document.getElementById('favArea');
        if (!items.length) { area.innerHTML = '<div class="empty-state">目前尚無收藏商品</div>'; return; }
        area.innerHTML = items.map(p => `
            <div class="product-row" onclick="Router.go('products',{productId:${p.id}})">
                <div class="product-thumb">🧴</div>
                <div class="product-info"><div class="pname">${p.name}</div><div class="pprice">${p.price}</div></div>
                <button class="heart-btn fav" onclick="event.stopPropagation();Fav.toggle(${p.id});PageInit.favorites();">❤️</button>
            </div>
        `).join('');
    },

    compare() {
        const style = STYLES.find(s => s.id === Router.selectedStyleId);
        const nameEl = document.getElementById('compareStyleName');
        const tagsEl = document.getElementById('compareStyleTags');
        const stage = document.getElementById('compareStage');
        const label = document.getElementById('comparePhotoLabel');
        const holdBtn = document.getElementById('compareHoldBtn');

        nameEl.textContent = style ? style.name : '尚未選擇風格';
        tagsEl.innerHTML = style ? style.tags.map(t => `<span class="analysis-tag">${t}</span>`).join('') : '';

        const showAfter = () => {
            stage.classList.remove('before');
            stage.classList.add('after');
            label.textContent = style ? `${style.name} 渲染後照片` : '渲染後照片';
        };
        const showBefore = () => {
            stage.classList.remove('after');
            stage.classList.add('before');
            label.textContent = '渲染前照片';
        };
        holdBtn.onpointerdown = showAfter;
        holdBtn.onpointerup = showBefore;
        holdBtn.onpointerleave = showBefore;
        holdBtn.onfocus = showAfter;
        holdBtn.onblur = showBefore;
        document.getElementById('compareGoStyleBtn').onclick = () => Router.go('style');
    },

    suggestion() {
        const style = STYLES.find(s => s.id === Router.selectedStyleId) || STYLES[0];
        const advice = style.advice || { base:'清透柔霧底妝', brow:'自然平眉', eye:'柔霧大地色', blush:'甜感腮紅', lip:'紅色系' };
        const r = Router.analysisResult || {};
        const skin = r['膚色'] || {};
        const area = document.getElementById('suggestionArea');
        area.innerHTML = `
            <div class="style-intro-card">
                <h3>${style.name} 專屬妝容建議</h3>
                <p>${style.intro || '此風格介紹尚待補充。'}</p>
                <div class="analysis-tags">${style.tags.map(t => `<span class="analysis-tag">${t}</span>`).join('')}</div>
            </div>
            <div class="analysis-section">
                <h3>五官與膚色摘要</h3>
                <div class="analysis-item"><span class="ai-label">臉型</span><span class="ai-value">${r['臉型']||'—'}</span></div>
                <div class="analysis-item"><span class="ai-label">眼型</span><span class="ai-value">${r['眼型']||'—'}</span></div>
                <div class="analysis-item"><span class="ai-label">鼻型</span><span class="ai-value">${r['鼻型']||'—'}</span></div>
                <div class="analysis-item"><span class="ai-label">膚色</span><span class="ai-value">${skin['膚色分級']||'—'} / ${skin['四季型']||'—'}</span></div>
            </div>
            <div class="analysis-section">
                <h3>建議收藏</h3>
                <div class="advice-grid">
                    ${Object.entries(advice).map(([key, text]) => `<div><b>${adviceTitle(key)}</b><p>${text}</p></div>`).join('')}
                </div>
                <button class="btn-gold" id="saveSuggestionBtn" style="margin-top:14px;">收藏這組建議</button>
            </div>
        `;
        document.getElementById('saveSuggestionBtn').onclick = () => {
            const records = JSON.parse(localStorage.getItem('beautySuggestions') || '[]');
            records.unshift({ style: style.name, advice, analysis: r, timestamp: new Date().toISOString() });
            localStorage.setItem('beautySuggestions', JSON.stringify(records.slice(0, 20)));
            alert('已收藏妝容建議');
        };

        function adviceTitle(key) {
            return ({ base:'底妝建議', brow:'眉型建議', eye:'眼妝建議', blush:'腮紅 & 修容', lip:'唇妝建議' })[key] || key;
        }
    },

    history() {
        const records = History.list();
        const area = document.getElementById('historyArea');
        if (!records.length) { area.innerHTML = '<div class="empty-state">尚無分析紀錄</div>'; return; }
        area.innerHTML = records.map((r, i) => `
            <div class="product-row" style="cursor:default;">
                <div class="product-thumb" style="font-size:14px;">#${i+1}</div>
                <div class="product-info">
                    <div class="pname">${r['臉型']||'—'} · ${r['眼型']||'—'} · ${r['鼻型']||'—'}</div>
                    <div class="pprice">${r.timestamp ? new Date(r.timestamp).toLocaleString('zh-TW') : ''}</div>
                </div>
            </div>
        `).join('');
    },

    profile() {
        const profile = Auth.getProfile();
        document.getElementById('profileName').textContent = profile.name || Auth.getUser() || '訪客';
        document.getElementById('profileEmail').textContent = profile.email || '—';
        document.getElementById('profilePhone').textContent = profile.phone || '—';
        document.getElementById('profileAge').textContent = profile.age || '—';
        document.getElementById('profileLevel').textContent = profile.level || '一般會員';
        document.getElementById('profileFavCount').textContent = Fav.list().length;
        document.getElementById('profileAnalyzeCount').textContent = History.list().length;
        const avatar = document.getElementById('profileAvatar');
        const fallback = document.getElementById('profileAvatarFallback');
        if (profile.avatar) {
            avatar.src = profile.avatar;
            avatar.style.display = 'block';
            fallback.style.display = 'none';
        }
    }
};

// ═══ 初始化 ═══
(function init() {
    // Sidebar 導航
    document.querySelectorAll('.sidebar-nav a').forEach(a => {
        a.onclick = (e) => { e.preventDefault(); Router.go(a.dataset.page); };
    });

    // 判斷登入狀態
    if (Auth.isLoggedIn()) {
        showApp();
    } else {
        showLogin();
    }
})();

function showApp() {
    document.getElementById('auth-layer').innerHTML = '';
    document.getElementById('app').style.display = 'flex';
    document.getElementById('sidebarUsername').textContent = Auth.getUser();
    Router.go('dashboard');
}

function showLogin() {
    document.getElementById('app').style.display = 'none';
    document.getElementById('auth-layer').innerHTML = `
        <div class="auth-overlay">
            <div class="auth-card">
                <h2>裝飾你的美</h2>
                <p class="subtitle">Log in to continue your beauty journey</p>
                <div class="input-group"><label>電子郵件</label><input type="email" id="loginEmail" placeholder="your@email.com"></div>
                <div class="input-group"><label>密碼</label><input type="password" id="loginPwd" placeholder="••••••••"></div>
                <button class="btn-gold btn-full" onclick="doLoginAction()" style="margin-top:8px;">登　入</button>
                <button class="btn-outline btn-full" onclick="doGuestLogin()" style="margin-top:12px;">訪客登入</button>
                <div style="margin-top:12px;"><span class="auth-link" onclick="showForgotPassword()">忘記密碼？</span></div>
                <div style="margin-top:16px;"><span class="auth-link" onclick="showRegister()">還沒有帳號？立即註冊</span></div>
            </div>
        </div>
    `;
}

function showRegister() {
    document.getElementById('auth-layer').innerHTML = `
        <div class="auth-overlay">
            <div class="auth-card auth-card-wide">
                <h2>建立帳號</h2>
                <p class="subtitle">Create your beauty profile</p>
                <div class="avatar-picker" onclick="document.getElementById('regAvatar').click()">
                    <img id="regAvatarPreview" alt="">
                    <span id="regAvatarIcon">👤</span>
                    <b>📷</b>
                    <input type="file" id="regAvatar" accept="image/*" style="display:none;" onchange="previewRegisterAvatar(event)">
                </div>
                <div class="input-group"><label>使用者名稱</label><input type="text" id="regName" placeholder="你的名字"></div>
                <div class="input-group"><label>電話號碼</label><input type="tel" id="regPhone" placeholder="0912345678"></div>
                <div class="input-group"><label>電子郵件</label><input type="email" id="regEmail" placeholder="your@email.com"></div>
                <div class="input-group"><label>年齡</label><input type="number" id="regAge" placeholder="20"></div>
                <div class="input-group"><label>密碼</label><input type="password" id="regPwd" placeholder="••••••••"></div>
                <div class="input-group"><label>確認密碼</label><input type="password" id="regPwd2" placeholder="••••••••"></div>
                <button class="btn-gold btn-full" onclick="doRegisterAction()" style="margin-top:8px;">註　冊</button>
                <div style="margin-top:16px;"><span class="auth-link" onclick="showLogin()">已有帳號？返回登入</span></div>
            </div>
        </div>
    `;
}

function showVerification(email) {
    const masked = maskEmail(email);
    document.getElementById('auth-layer').innerHTML = `
        <div class="auth-overlay">
            <div class="auth-card">
                <h2>驗證信箱</h2>
                <p class="subtitle">已將驗證碼發送至<br>${masked}</p>
                <div class="input-group"><label>驗證碼</label><input type="text" id="otpCode" placeholder="請輸入驗證碼"></div>
                <button class="btn-gold btn-full" onclick="doVerifyOTP()" style="margin-top:8px;">驗　證</button>
                <button class="btn-outline btn-full" onclick="resendOTP()" style="margin-top:12px;">重新發送驗證碼</button>
                <div style="margin-top:16px;"><span class="auth-link" onclick="showRegister()">回上一頁</span></div>
            </div>
        </div>
    `;
}

function showForgotPassword() {
    document.getElementById('auth-layer').innerHTML = `
        <div class="auth-overlay">
            <div class="auth-card">
                <h2>忘記密碼</h2>
                <p class="subtitle">輸入信箱以接收驗證碼</p>
                <div class="input-group"><label>電子郵件</label><input type="email" id="forgotEmail" placeholder="your@email.com"></div>
                <button class="btn-gold btn-full" onclick="sendForgotOTP()">發送驗證碼</button>
                <div style="margin-top:16px;"><span class="auth-link" onclick="showLogin()">返回登入</span></div>
            </div>
        </div>
    `;
}

async function doLoginAction() {
    const email = document.getElementById('loginEmail').value.trim();
    const password = document.getElementById('loginPwd').value;
    if (!email || !password) { alert('請輸入帳號密碼'); return; }
    try {
        const data = await Api.login(email, password);
        const member = data.member || {};
        Auth.setProfile({
            name: member.name || email.split('@')[0],
            email: member.email || email,
            phone: member.phone_number || '',
            age: member.age || '',
            level: member.level || '一般會員',
        });
    } catch (_) {
        Auth.setProfile({ name: email.split('@')[0], email, level: '本地原型會員' });
    }
    showApp();
}

function doGuestLogin() {
    Auth.setProfile({ name: '訪客', level: '訪客', age: '', phone: '', email: '' });
    showApp();
}

async function doRegisterAction() {
    const name = document.getElementById('regName').value.trim();
    const phone = document.getElementById('regPhone').value.trim();
    const email = document.getElementById('regEmail').value.trim();
    const age = document.getElementById('regAge').value.trim();
    const password = document.getElementById('regPwd').value;
    const confirm = document.getElementById('regPwd2').value;
    const avatar = document.getElementById('regAvatarPreview').src || '';

    if (!name || !phone || !email || !age || !password || !confirm) {
        alert('請完整填寫所有欄位');
        return;
    }
    if (password !== confirm) {
        alert('密碼與確認密碼不一致');
        return;
    }

    Router.pendingRegister = { name, phone, email, age, password, avatar, level: 'VIP會員' };
    try {
        await Api.register(Router.pendingRegister);
        await Api.sendOTP(email);
    } catch (_) {
        console.warn('Auth API unavailable, using local OTP simulation.');
    }
    showVerification(email);
}

async function doVerifyOTP() {
    const code = document.getElementById('otpCode').value.trim();
    if (!code) { alert('請輸入驗證碼'); return; }
    const pending = Router.pendingRegister;
    if (!pending) { alert('註冊資料已過期，請重新註冊'); showRegister(); return; }
    try {
        await Api.verifyOTP(pending.email, code);
    } catch (_) {
        if (code.length < 4) {
            alert('驗證碼至少 4 碼');
            return;
        }
    }
    Auth.setProfile({
        name: pending.name,
        phone: pending.phone,
        email: pending.email,
        age: pending.age,
        level: pending.level,
        avatar: pending.avatar
    });
    Router.pendingRegister = null;
    alert('帳號已成功建立');
    showApp();
}

async function resendOTP() {
    const email = Router.pendingRegister?.email;
    if (!email) return;
    try { await Api.sendOTP(email); } catch (_) {}
    alert('驗證碼已重新發送（原型模式）');
}

async function sendForgotOTP() {
    const email = document.getElementById('forgotEmail').value.trim();
    if (!email) { alert('請輸入 Email'); return; }
    try { await Api.sendOTP(email); } catch (_) {}
    alert('驗證碼已發送（原型模式）');
    showLogin();
}

function previewRegisterAvatar(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => {
        const img = document.getElementById('regAvatarPreview');
        img.src = ev.target.result;
        img.style.display = 'block';
        document.getElementById('regAvatarIcon').style.display = 'none';
    };
    reader.readAsDataURL(file);
}

function maskEmail(email) {
    const [name, domain] = email.split('@');
    if (!name || !domain || name.length <= 3) return email;
    return `${name.slice(0, 3)}******@${domain}`;
}
