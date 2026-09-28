// 妝後照上的「上妝示範」：斜線色塊＋筆刷順向掃過，一步步示範每個部位怎麼畫。
//
// 幾何、配色、動畫時間全部照 makeup-tutorial-spec-for-claude-code.md（使用者提供的規格，
// 已在真臉上逐一校正過），**不要自己重推**。這裡只做三件規格沒有的事：
//
//   1. 定位點不是預先烤好的，要對「這一張妝後圖」即時偵測。gpt-image-2 輸出的尺寸與構圖
//      不保證跟妝前照一樣，拿妝前的點疊上去會歪。
//   2. 網站的人像框是 object-fit:cover、靠上對齊（見 makeup-flow.css 的 .look-portrait-frame），
//      規格要求的「img 與 canvas 完全重疊、不要 cover」做不到，所以座標要自己換算 cover 的縮放與位移。
//   3. 規格沒有「底妝」這一步，但網站的部位按鈕有。這裡補一個臉部輪廓內的淡色塊（避開眼、眉、唇）。
//
// 偵測用的 MediaPipe 只有在使用者按下示範時才載入（約數 MB），不影響一般瀏覽。
(function (window, document) {
    'use strict';

    // ── 規格 §4：各部位索引 ─────────────────────────────────────────
    const BROW_R = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46], BROW_L = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276];
    const LID_R = [133, 173, 157, 158, 159, 160, 161, 246, 33], LID_L = [362, 398, 384, 385, 386, 387, 388, 466, 263];
    const CREASE_R = [29, 27, 28, 222, 223, 224], CREASE_L = [259, 257, 258, 442, 443, 444];
    const LIPS_OUT = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146];
    // 底妝（本檔補的）：MediaPipe FACEMESH_FACE_OVAL 與兩眼輪廓
    const FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109];
    const EYE_R = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246];
    const EYE_L = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398];

    // ── 規格 §6、§7：步驟、配色、教學文字 ─────────────────────────────
    // part 是網站部位按鈕的 key（makeup-flow.js 的 pinLayout），一個部位可以對應好幾步。
    const STEPS = [
        { id: 'base', part: 'base', label: '底妝', color: [244, 196, 160], blur: 1.4,
          body: '從臉部中央往外，用海綿或粉底刷少量多次推開，髮際線與下顎邊緣推薄，讓膚色自然銜接。',
          tip: '重點：眼周與鼻翼容易卡粉，用剩下的量輕拍就好。' },
        { id: 'brows', part: 'eyebrow', label: '眉毛', color: [205, 151, 99], blur: 1.0,
          body: '順著原本的眉型，用眉筆／眉粉從眉頭往眉尾「一筆一筆順刷」。眉頭最淡、眉峰到眉尾稍實，尾端收成自然的角度。',
          tip: '重點：眉頭用餘粉帶過就好，太深會顯兇。' },
        { id: 'eyeshadow-base', part: 'eyes', label: '眼影・主題色', color: [183, 148, 232], blur: 1.2,
          body: '第一層打底：從睫毛根部往上、由眼頭往眼尾橫向來回輕掃，鋪滿整片上眼皮，高度到雙眼皮褶為止。',
          tip: '重點：分次少量堆疊顏色才勻；這是上眼皮色塊，不要框整圈眼睛。' },
        { id: 'eyeshadow-deep', part: 'eyes', label: '眼影・加深眼尾', color: [230, 108, 162], blur: 1.2,
          body: '第二層加深：換深色，只集中在眼尾外側＋雙眼皮褶，沿眼尾往內、往斜上暈成一個小小的 V，做出深邃層次。',
          tip: '重點：深色範圍要比主題色小，越往眼頭越淡，才有漸層。' },
        { id: 'eyeliner', part: 'eyes', label: '眼線', color: [120, 89, 84], blur: 1.2,
          body: '沿著上睫毛根部，從眼頭一筆拉到眼尾，填滿睫毛空隙。越靠眼尾越加粗，尾端順著下眼瞼延伸線稍微拉長、微微上揚。',
          tip: '重點：內眼角細、眼尾粗，線條才自然。' },
        { id: 'blush', part: 'cheeks', label: '腮紅', color: [255, 124, 144], blur: 1.4,
          body: '微笑找到蘋果肌最高點，刷子順著往太陽穴的斜向一下一下掃上去。中心稍濃、邊緣往外帶開，位置不要低於鼻翼。',
          tip: '重點：少量多次、邊緣推乾淨，才不會像色塊貼上去。' },
        { id: 'contour', part: 'contour', label: '修容', color: [200, 152, 107], blur: 1.4,
          body: '在顴骨下緣的凹陷、以及鼻樑兩側，順著方向刷上比膚色深一號的顏色，做出立體與陰影。',
          tip: '重點：用霧面、不要有亮粉，邊緣一定要推開。' },
        { id: 'lips', part: 'lips', label: '口紅', color: [252, 79, 75], blur: 1.0,
          body: '先沿著唇型描出輪廓，再從一側往另一側刷滿。上唇帶出唇峰角度，下唇中央可加一點提亮做出唇珠。',
          tip: '重點：想更自然就用手指把邊緣輕輕抿開。' },
    ];
    const TINT_A = 0.23, LINE_A = 0.50, APPLY = 1.45, STEP_TIME = 3.3;
    // 規格 §6 的每部位微調；底妝是本檔補的，刻意更淡，免得整張臉蓋一層色。
    const ZONE_MUL = { blush: 0.8, contour: 1.1, base: 0.55 };

    // ── 小工具（規格原樣） ────────────────────────────────────────
    const add = (a, b) => ({ x: a.x + b.x, y: a.y + b.y }), sub = (a, b) => ({ x: a.x - b.x, y: a.y - b.y });
    const scale = (a, s) => ({ x: a.x * s, y: a.y * s }), len = a => Math.hypot(a.x, a.y);
    const norm = a => { const l = len(a) || 1; return { x: a.x / l, y: a.y / l }; };
    const dot = (a, b) => a.x * b.x + a.y * b.y, dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
    const lerp = (a, b, t) => a + (b - a) * t, clamp = (v, a, b) => Math.max(a, Math.min(b, v));
    const smooth = t => { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); };
    const centroid = p => { let x = 0, y = 0; for (const q of p) { x += q.x; y += q.y; } return { x: x / p.length, y: y / p.length }; };
    const bbox = p => { const b = { minX: 1e9, minY: 1e9, maxX: -1e9, maxY: -1e9 }; for (const q of p) { b.minX = Math.min(b.minX, q.x); b.minY = Math.min(b.minY, q.y); b.maxX = Math.max(b.maxX, q.x); b.maxY = Math.max(b.maxY, q.y); } return b; };
    const ebox = e => { const r = Math.max(e.rx, e.ry); return { minX: e.cx - r, minY: e.cy - r, maxX: e.cx + r, maxY: e.cy + r }; };
    const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

    // ── MediaPipe：只載一次，偵測結果依圖片網址快取 ─────────────────────
    // 版本鎖死：不鎖的話 CDN 換版就可能在沒人改程式的情況下壞掉。
    const MP_BASE = 'https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh@0.4.1633559619/';
    let mpLoading = null, faceMesh = null, pendingResolve = null;
    const landmarkCache = new Map();

    function loadMediaPipe() {
        if (window.FaceMesh) return Promise.resolve();
        if (mpLoading) return mpLoading;
        mpLoading = new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = `${MP_BASE}face_mesh.js`;
            s.crossOrigin = 'anonymous';
            s.onload = () => resolve();
            s.onerror = () => { mpLoading = null; reject(new Error('臉部定位模型載入失敗')); };
            document.head.appendChild(s);
        });
        return mpLoading;
    }

    function getFaceMesh() {
        if (faceMesh) return faceMesh;
        faceMesh = new window.FaceMesh({ locateFile: f => `${MP_BASE}${f}` });
        faceMesh.setOptions({ staticImageMode: true, maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5 });
        faceMesh.onResults(res => {
            const r = pendingResolve;
            pendingResolve = null;
            if (!r) return;
            const lm = res.multiFaceLandmarks && res.multiFaceLandmarks[0];
            r(lm ? lm.map(p => [p.x, p.y]) : null);
        });
        return faceMesh;
    }

    // 偵測用另外載一張帶 crossOrigin 的圖，**不去動畫面上那張**：
    // 畫面上的 <img> 若加了 crossOrigin 而 CORS 沒過，整張妝後圖會直接顯示不出來；
    // 這裡失敗只是示範不能用，妝後圖照常。
    function loadDetectImage(url) {
        return new Promise((resolve, reject) => {
            const im = new Image();
            if (!/^data:|^blob:/.test(url)) im.crossOrigin = 'anonymous';
            im.onload = () => resolve(im);
            im.onerror = () => reject(new Error('讀不到妝後圖的像素（跨網域設定）'));
            im.src = url;
        });
    }

    async function detectLandmarks(url) {
        if (landmarkCache.has(url)) return landmarkCache.get(url);
        await loadMediaPipe();
        const im = await loadDetectImage(url);
        const fm = getFaceMesh();
        let lm = null;
        // 規格 §2：偶爾第一次送出沒有結果，重試最多三次。
        for (let tries = 0; tries < 3 && !lm; tries++) {
            lm = await new Promise(resolve => { pendingResolve = resolve; fm.send({ image: im }).catch(() => resolve(null)); });
        }
        const out = lm ? { lm, w: im.naturalWidth, h: im.naturalHeight } : null;
        if (out) landmarkCache.set(url, out);
        return out;
    }

    // ── 控制器：一個人像框一個 ─────────────────────────────────────
    function create({ frame, img, url, onChange }) {
        const canvas = document.createElement('canvas');
        canvas.className = 'look-tutor-canvas';
        canvas.setAttribute('aria-hidden', 'true');
        frame.appendChild(canvas);
        const ctx = canvas.getContext('2d');
        const off = document.createElement('canvas'), octx = off.getContext('2d');
        const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        let data = null;          // { lm, w, h }
        let W = 0, H = 0, S = 1, DX = 0, DY = 0;
        let state = 'idle';       // idle | loading | ready | error
        let error = '';
        let seq = [];             // 這次要播的步驟 index
        let pos = 0, stepT = 0, clock = 0, playing = false, finished = false, raf = 0, last = null;
        let mode = null;          // 'all' | 部位 key

        const emit = () => { if (typeof onChange === 'function') onChange(api.snapshot()); };

        // cover＋靠上：與 .look-portrait-frame img 的 object-fit/object-position 一致
        function layout() {
            const r = frame.getBoundingClientRect();
            W = Math.round(r.width); H = Math.round(r.height);
            canvas.width = W; canvas.height = H; off.width = W; off.height = H;
            if (data) {
                S = Math.max(W / data.w, H / data.h);
                DX = (W - data.w * S) / 2;
                DY = 0;
            }
        }
        const getP = i => ({ x: DX + data.lm[i][0] * data.w * S, y: DY + data.lm[i][1] * data.h * S });
        const getPs = a => a.map(getP);
        const faceAxisAngle = () => { const d = sub(getP(454), getP(234)); return Math.atan2(d.y, d.x); };
        const faceUpVec = () => norm(sub(getP(10), getP(152)));
        // 線距以「臉在畫面上的寬度」為基準：cover 裁切後，框寬不等於臉的比例尺
        const unitW = () => data.w * S;

        // ── 規格 §4 幾何（原樣） ──
        function eyeshadowPoly(s) {
            const lid = getPs(s === 'R' ? LID_R : LID_L), lidC = centroid(lid);
            const creaseC = centroid(getPs(s === 'R' ? CREASE_R : CREASE_L));
            const up = norm(sub(creaseC, lidC)), h = dot(sub(creaseC, lidC), up) * 0.92;
            const outer = lid[lid.length - 1], eyeW = dist(lid[0], outer), n = lid.length;
            const top = lid.map((p, i) => add(p, scale(up, h * (0.55 + 0.45 * (i / (n - 1))))));
            const outward = norm(sub(outer, lidC)), tail = add(add(outer, scale(up, h * 0.85)), scale(outward, eyeW * 0.12));
            const poly = []; for (let i = 0; i < n; i++) poly.push(lid[i]); poly.push(tail); for (let i = n - 1; i >= 0; i--) poly.push(top[i]);
            return poly;
        }
        function eyeshadowDeepPoly(s) {
            const lid = getPs(s === 'R' ? LID_R : LID_L), n = lid.length, k = Math.floor(n * 0.52);
            const lidC = centroid(lid), creaseC = centroid(getPs(s === 'R' ? CREASE_R : CREASE_L));
            const up = norm(sub(creaseC, lidC)), h = dot(sub(creaseC, lidC), up);
            const outer = lid[n - 1], eyeW = dist(lid[0], outer);
            const bottom = []; for (let i = k; i < n; i++) bottom.push(lid[i]);
            const top = []; for (let i = k; i < n; i++) { const f = (i - k) / (n - 1 - k); top.push(add(lid[i], scale(up, h * (0.72 + 0.45 * f)))); }
            const outward = norm(sub(outer, lidC)), tail = add(add(outer, scale(up, h * 0.95)), scale(outward, eyeW * 0.16));
            const poly = []; for (const p of bottom) poly.push(p); poly.push(tail); for (let i = top.length - 1; i >= 0; i--) poly.push(top[i]);
            return poly;
        }
        function linerData(s) {
            const lid = getPs(s === 'R' ? LID_R : LID_L), eyeW = dist(lid[0], lid[lid.length - 1]);
            const eyeC = centroid(lid), browC = centroid(getPs(s === 'R' ? BROW_R : BROW_L)), up = norm(sub(browC, eyeC));
            const outer = lid[lid.length - 1], prev = lid[lid.length - 2], dir = norm(sub(outer, prev));
            let wing = add(outer, scale(dir, eyeW * 0.13)); wing = add(wing, scale(up, eyeW * 0.05));
            return { lid, wing, eyeW };
        }
        function blushEllipse(s) {
            const c = s === 'R' ? centroid(getPs([50, 101, 205])) : centroid(getPs([280, 330, 425]));
            const faceW = dist(getP(234), getP(454));
            const lat = norm(sub(s === 'R' ? getP(234) : getP(454), c)), cc = add(c, scale(lat, faceW * 0.05));
            const rot = faceAxisAngle() + (s === 'R' ? -0.349 : 0.349);
            return { cx: cc.x, cy: cc.y, rx: faceW * 0.095, ry: faceW * 0.072, rot };
        }
        function stripPoly(idx, wtop, wbot) {
            const pts = getPs(idx), m = pts.length, left = [], right = [];
            for (let i = 0; i < m; i++) {
                let t;
                if (i === 0) t = sub(pts[1], pts[0]); else if (i === m - 1) t = sub(pts[m - 1], pts[m - 2]); else t = sub(pts[i + 1], pts[i - 1]);
                t = norm(t);
                const perp = { x: -t.y, y: t.x }, f = i / (m - 1), w = (wtop + (wbot - wtop) * f) / 2;
                left.push(add(pts[i], scale(perp, w))); right.push(sub(pts[i], scale(perp, w)));
            }
            return left.concat(right.reverse());
        }
        function noseStrips() {
            const noseW = dist(getP(48), getP(278));
            return [
                { pts: stripPoly([55, 122, 196, 3, 51, 45], noseW * 0.12, noseW * 0.26), axis: { S: getP(55), E: getP(45) } },
                { pts: stripPoly([285, 351, 419, 248, 281, 275], noseW * 0.12, noseW * 0.26), axis: { S: getP(285), E: getP(275) } },
            ];
        }
        function contourEllipses() {
            const faceW = dist(getP(234), getP(454)), out = [];
            for (const [a, b] of [[116, 206], [345, 426]]) {
                const pa = getP(a), pb = getP(b), c = { x: (pa.x + pb.x) / 2, y: (pa.y + pb.y) / 2 }, d = sub(pb, pa);
                out.push({ cx: c.x, cy: c.y, rx: len(d) * 0.52, ry: faceW * 0.028, rot: Math.atan2(d.y, d.x) });
            }
            return out;
        }
        function shapesFor(id) {
            switch (id) {
                case 'base': return [{ type: 'poly', pts: getPs(FACE_OVAL), side: 'M', holes: [getPs(EYE_R), getPs(EYE_L), getPs(BROW_R), getPs(BROW_L), getPs(LIPS_OUT)] }];
                case 'brows': return [{ type: 'poly', pts: getPs(BROW_R), side: 'R' }, { type: 'poly', pts: getPs(BROW_L), side: 'L' }];
                case 'eyeshadow-base': return [{ type: 'poly', pts: eyeshadowPoly('R'), side: 'R' }, { type: 'poly', pts: eyeshadowPoly('L'), side: 'L' }];
                case 'eyeshadow-deep': return [{ type: 'poly', pts: eyeshadowDeepPoly('R'), side: 'R' }, { type: 'poly', pts: eyeshadowDeepPoly('L'), side: 'L' }];
                case 'eyeliner': return [{ type: 'line', d: linerData('R'), side: 'R' }, { type: 'line', d: linerData('L'), side: 'L' }];
                case 'blush': return [{ type: 'ellipse', e: blushEllipse('R'), side: 'R' }, { type: 'ellipse', e: blushEllipse('L'), side: 'L' }];
                case 'contour': {
                    const arr = contourEllipses().map(e => ({ type: 'ellipse', e, side: 'C' }));
                    for (const s of noseStrips()) arr.push({ type: 'poly', pts: s.pts, side: 'N', axis: s.axis });
                    return arr;
                }
                case 'lips': return [{ type: 'poly', pts: getPs(LIPS_OUT), side: 'M' }];
            }
            return [];
        }

        // ── 規格 §5：斜線色塊 ──
        const pathPoly = (c, pts) => { c.beginPath(); c.moveTo(pts[0].x, pts[0].y); for (let i = 1; i < pts.length; i++) c.lineTo(pts[i].x, pts[i].y); c.closePath(); };
        const pathEllipse = (c, e) => { c.beginPath(); c.ellipse(e.cx, e.cy, Math.max(1, e.rx), Math.max(1, e.ry), e.rot, 0, Math.PI * 2); };
        function compositeSoft(blur) { ctx.save(); ctx.filter = blur > 0 ? `blur(${blur}px)` : 'none'; ctx.drawImage(off, 0, 0); ctx.restore(); ctx.filter = 'none'; }
        function renderZoneContent(traceFn, box, color, tintA, lineA, holes) {
            octx.clearRect(0, 0, W, H); octx.save(); traceFn(octx); octx.clip();
            if (tintA > 0) { octx.globalAlpha = tintA; octx.fillStyle = rgba(color, 1); octx.fillRect(0, 0, W, H); }
            if (lineA > 0) {
                octx.globalAlpha = lineA; octx.strokeStyle = rgba(color, 1); octx.lineWidth = Math.max(1.2, unitW() * 0.0022); octx.lineCap = 'butt';
                const cx = (box.minX + box.maxX) / 2, cy = (box.minY + box.maxY) / 2, diag = Math.hypot(box.maxX - box.minX, box.maxY - box.minY) + 30;
                octx.translate(cx, cy); octx.rotate(-Math.PI / 4);
                const sp = Math.max(5, Math.min(10, unitW() * 0.011));
                for (let x = -diag; x <= diag; x += sp) { octx.beginPath(); octx.moveTo(x, -diag); octx.lineTo(x, diag); octx.stroke(); }
            }
            octx.restore();
            if (holes) {
                octx.save(); octx.globalCompositeOperation = 'destination-out';
                for (const h of holes) { pathPoly(octx, h); octx.fill(); }
                octx.restore();
            }
        }
        function dirReveal(Sp, Ep, p) {
            const d = sub(Ep, Sp), Ltot = len(d) || 1, feather = Math.max(14, Ltot * 0.22);
            const head = p * (Ltot + feather), t0 = clamp(head / Ltot, 0, 1), t1 = clamp((head + feather) / Ltot, 0, 1);
            const g = octx.createLinearGradient(Sp.x, Sp.y, Ep.x, Ep.y);
            g.addColorStop(0, 'rgba(0,0,0,1)'); g.addColorStop(Math.min(t0, 1), 'rgba(0,0,0,1)');
            if (t1 > t0 + 0.001) g.addColorStop(Math.min(t1, 1), 'rgba(0,0,0,0)');
            if (t1 < 0.999) g.addColorStop(1, 'rgba(0,0,0,0)');
            octx.save(); octx.globalCompositeOperation = 'destination-in'; octx.fillStyle = g; octx.fillRect(0, 0, W, H); octx.restore();
        }
        function strokeAxis(id, sh, side) {
            if (sh.axis) return sh.axis;
            if (sh.type === 'poly') {
                if (id === 'base') return { S: getP(10), E: getP(152) };
                if (id === 'brows') return side === 'R' ? { S: getP(55), E: getP(46) } : { S: getP(285), E: getP(276) };
                if (id === 'eyeshadow-base') return side === 'R' ? { S: getP(133), E: getP(33) } : { S: getP(362), E: getP(263) };
                if (id === 'eyeshadow-deep') return side === 'R' ? { S: getP(33), E: getP(159) } : { S: getP(263), E: getP(386) };
                if (id === 'lips') return { S: getP(61), E: getP(291) };
                const b = bbox(sh.pts); return { S: { x: b.minX, y: (b.minY + b.maxY) / 2 }, E: { x: b.maxX, y: (b.minY + b.maxY) / 2 } };
            }
            const e = sh.e, C = { x: e.cx, y: e.cy };
            if (id === 'blush') {
                const up = faceUpVec(), lat = norm(sub(side === 'R' ? getP(234) : getP(454), C));
                const dir = norm(add(scale(up, 0.72), scale(lat, 0.72))), r = Math.max(e.rx, e.ry);
                return { S: sub(C, scale(dir, r)), E: add(C, scale(dir, r)) };
            }
            let dir, r;
            if (e.rx >= e.ry) { dir = { x: Math.cos(e.rot), y: Math.sin(e.rot) }; r = e.rx; } else { dir = { x: -Math.sin(e.rot), y: Math.cos(e.rot) }; r = e.ry; }
            if (dir.y < 0) dir = { x: -dir.x, y: -dir.y };
            return { S: sub(C, scale(dir, r)), E: add(C, scale(dir, r)) };
        }
        function drawLinerZone(ld, color, opts) {
            const { lid, wing, eyeW } = ld, path = lid.concat([wing]);
            const segs = []; let total = 0;
            for (let i = 0; i < path.length - 1; i++) { const L = dist(path[i], path[i + 1]); segs.push(L); total += L; }
            const p = opts.reveal ? opts.p : 1, drawLen = total * p;
            octx.clearRect(0, 0, W, H); octx.save(); octx.strokeStyle = rgba(color, 1); octx.globalAlpha = 0.9 * opts.fillMul; octx.lineJoin = 'round'; octx.lineCap = 'round';
            let acc = 0;
            for (let i = 0; i < path.length - 1; i++) {
                const L = segs[i], t = i / (path.length - 2); octx.lineWidth = eyeW * (0.020 + 0.06 * t);
                if (acc + L <= drawLen) { octx.beginPath(); octx.moveTo(path[i].x, path[i].y); octx.lineTo(path[i + 1].x, path[i + 1].y); octx.stroke(); }
                else if (acc < drawLen) { const f = (drawLen - acc) / L; octx.beginPath(); octx.moveTo(path[i].x, path[i].y); octx.lineTo(lerp(path[i].x, path[i + 1].x, f), lerp(path[i].y, path[i + 1].y, f)); octx.stroke(); break; }
                acc += L;
            }
            octx.restore(); compositeSoft(1.2);
        }
        function drawZone(idx, opts) {
            const st = STEPS[idx], za = ZONE_MUL[st.id] || 1;
            for (const sh of shapesFor(st.id)) {
                if (sh.type === 'line') { drawLinerZone(sh.d, st.color, opts); continue; }
                const traceFn = sh.type === 'poly' ? c => pathPoly(c, sh.pts) : c => pathEllipse(c, sh.e);
                const box = sh.type === 'poly' ? bbox(sh.pts) : ebox(sh.e);
                renderZoneContent(traceFn, box, st.color, TINT_A * opts.fillMul * za, LINE_A * opts.lineMul * za, sh.holes);
                if (opts.reveal && opts.p < 1) { const ax = strokeAxis(st.id, sh, sh.side); dirReveal(ax.S, ax.E, opts.p); }
                compositeSoft(st.blur);
            }
        }

        // ── 播放（規格 §7） ──
        function render() {
            ctx.clearRect(0, 0, W, H);
            if (!data || !seq.length) return;
            for (let i = 0; i < pos; i++) drawZone(seq[i], { fillMul: 0.85, lineMul: 0.5, reveal: false });
            if (finished) { drawZone(seq[pos], { fillMul: 0.85, lineMul: 0.5, reveal: false }); return; }
            const p = reduceMotion ? 1 : smooth(clamp((stepT - 0.18) / APPLY, 0, 1));
            drawZone(seq[pos], { fillMul: 1, lineMul: 1, reveal: !reduceMotion, p });
        }
        function frameTick(ts) {
            raf = 0;
            if (last == null) last = ts;
            let dt = (ts - last) / 1000; last = ts; if (dt > 0.1) dt = 0.1;
            clock += dt; stepT += dt;
            if (stepT >= STEP_TIME) {
                if (pos < seq.length - 1) { pos += 1; stepT = 0; emit(); }
                else { finished = true; playing = false; emit(); }
            }
            render();
            if (playing) raf = requestAnimationFrame(frameTick);
        }
        function startLoop() { if (!raf) { last = null; raf = requestAnimationFrame(frameTick); } }
        function stopLoop() { if (raf) cancelAnimationFrame(raf); raf = 0; }

        async function ensureReady() {
            if (state === 'ready') return true;
            if (state === 'loading') return false;
            state = 'loading'; error = ''; emit();
            try {
                data = await detectLandmarks(url);
                if (!data) throw new Error('這張妝後圖找不到清楚的正臉');
                layout(); state = 'ready';
            } catch (e) {
                state = 'error'; error = e && e.message ? e.message : '臉部定位失敗';
            }
            emit();
            return state === 'ready';
        }

        function begin(nextSeq, nextMode) {
            seq = nextSeq; mode = nextMode; pos = 0; stepT = 0; finished = false;
            canvas.classList.add('is-on');
            playing = true; emit(); startLoop();
        }

        const ro = window.ResizeObserver ? new ResizeObserver(() => { layout(); render(); }) : null;
        if (ro) ro.observe(frame);

        const api = {
            async playAll() {
                if (!await ensureReady()) return;
                begin(STEPS.map((_, i) => i), 'all');
            },
            async playPart(part) {
                if (!await ensureReady()) return;
                const idx = STEPS.map((s, i) => (s.part === part ? i : -1)).filter(i => i >= 0);
                if (idx.length) begin(idx, part);
            },
            toggle() {
                if (!seq.length) return;
                if (finished) { pos = 0; stepT = 0; finished = false; playing = true; startLoop(); emit(); return; }
                playing = !playing;
                if (playing) startLoop(); else stopLoop();
                emit();
            },
            go(delta) {
                if (!seq.length) return;
                // 手動換步時直接顯示刷完的樣子並停住——使用者按「下一步」是想看，不是想等。
                pos = clamp(pos + delta, 0, seq.length - 1); finished = false;
                playing = false; stopLoop(); stepT = APPLY + 0.2; render(); emit();
            },
            hide() { stopLoop(); playing = false; seq = []; canvas.classList.remove('is-on'); ctx.clearRect(0, 0, W, H); emit(); },
            destroy() { stopLoop(); if (ro) ro.disconnect(); canvas.remove(); },
            snapshot() {
                const st = seq.length ? STEPS[seq[pos]] : null;
                return { state, error, mode, playing, finished, index: pos, total: seq.length, step: st };
            },
        };
        return api;
    }

    window.MakeupTutorial = { create, STEPS };
})(window, document);
