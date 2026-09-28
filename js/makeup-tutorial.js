// 妝後照上的「上妝示範」：日式漫畫塗鴉風的斜線色塊＋墨線虛線框，依妝容一步步示範怎麼畫。
//
// 基礎幾何（眉、上眼皮、眼窩、唇、腮紅、顴骨修容、鼻影的索引與係數）照
// makeup-tutorial-spec-for-claude-code.md（使用者提供、已在真臉上校正過），**不要自己重推**。
//
// 2026-09-28 使用者追加兩件事：
//   1. 七種妝容不能只是換色——每種有自己的上妝區域、範圍、方向、強度與順序
//      （例：Soft Baddie 眼尾拉提＋高位腮紅；日雜是 Igari 眼下腮紅；港風紅唇最後上；
//       病嬌上下煙燻＋下睫毛；男士白開水幾乎沒有彩色區塊）。見 PLANS。
//   2. 原本的透明度太淡，會被照片本身的妝色蓋過。改成飽和色＋較實的斜線＋深色虛線墨框，
//      像日式漫畫的塗鴉標記。
//
// 規格以外、為了接進網站而做的事：
//   · 定位點對「這一張妝後圖」即時偵測（gpt-image-2 輸出的構圖不保證跟妝前一樣）。
//   · 人像框是 object-fit:cover、靠上對齊，座標依 cover 的縮放與位移換算。
//   · MediaPipe 只在使用者按下示範時才載入。
(function (window, document) {
    'use strict';

    // ── 索引：規格 §4 原樣 ─────────────────────────────────────────
    const BROW_R = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46], BROW_L = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276];
    const LID_R = [133, 173, 157, 158, 159, 160, 161, 246, 33], LID_L = [362, 398, 384, 385, 386, 387, 388, 466, 263];
    const CREASE_R = [29, 27, 28, 222, 223, 224], CREASE_L = [259, 257, 258, 442, 443, 444];
    const LIPS_OUT = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146];
    // ── 索引：本檔補的（MediaPipe 標準編號） ───────────────────────────
    // 下眼瞼（內→外），臥蠶／下眼影／下眼線／下睫毛共用
    const LOW_R = [133, 155, 154, 153, 145, 144, 163, 7, 33], LOW_L = [362, 382, 381, 380, 374, 373, 390, 249, 263];
    const FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109];
    const EYE_R = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246];
    const EYE_L = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398];

    // ── 七種妝容的上妝計畫 ─────────────────────────────────────────
    //
    // part 是網站部位按鈕的 key（makeup-flow.js 的 pinLayout）。k 是這一步的濃度倍率，
    // dur 是時間倍率。顏色刻意飽和——這是示範用的漫畫標記，不是擬真妝色。
    const S = (kind, part, label, color, body, tip, extra = {}) => ({ kind, part, label, color, body, tip, k: 1, dur: 1, ...extra });
    // 底妝蓋整張臉，用跟其他部位一樣的濃度會把五官整個罩住——只留極淡的底色與虛線框，不畫斜線。
    const BASE = (color, k = 0.3) => S('base', 'base', '底妝', color,
        '少量多次從臉部中央往外推開，髮際線與下顎邊緣推薄，讓膚色自然銜接。',
        '重點：眼周與鼻翼容易卡粉，用剩下的量輕拍就好。', { k });

    const PLANS = {
        softBaddie: [
            BASE([236, 178, 138]),
            S('brows', 'eyebrow', '眉毛', [150, 92, 52], '沿原生眉型填補，眉頭柔和，眉峰到眉尾加強，由眉頭往眉尾順刷。', '重點：眉尾收乾淨，才撐得起拉提感。'),
            S('shadowBase', 'eyes', '眼影・裸棕底色', [222, 146, 104], '裸棕色先鋪滿上眼皮，由內往外、由淺到深。', '重點：只在上眼皮與眼尾，不要框住整個眼睛。', { h: 0.95, axis: 'in-out' }),
            S('shadowDeep', 'eyes', '眼影・Outer V', [138, 70, 44], '大地深棕從眼尾 Outer V 往眼窩內側暈染，做出深邃輪廓。', '重點：越往眼頭越淡。', { lift: 1.15 }),
            S('liner', 'eyes', '眼線・貓眼', [40, 26, 26], '沿上睫毛根部從內眼角拉到眼尾，眼尾略微上揚成 lifted cat-eye。', '重點：尾巴順著下眼瞼延伸線往上，不要太粗。', { wingLen: 0.24, wingUp: 0.16, thick: 1.2 }),
            S('lashesUp', 'eyes', '睫毛', [30, 20, 20], '外側睫毛加強存在感，睫毛膏由根部往上刷。', '重點：外側比內側長一點，眼型更往上提。', { k: 0.9 }),
            S('contour', 'contour', '修容', [168, 104, 66], '顴骨下方、太陽穴與下顎外側，由臉外側往內輕掃。', '重點：邊緣推開，不要畫成大片深色。', { zones: ['cheek', 'temple', 'jaw'], outIn: true }),
            S('blush', 'cheeks', '腮紅', [216, 96, 82], '陶土玫瑰色放在顴骨偏高處，往太陽穴斜向上拉。', '重點：不要做日系眼下腮紅，位置要高。', { mode: 'lifted' }),
            S('highlight', 'contour', '打亮', [255, 214, 120], '顴骨高點、鼻樑中央與唇峰，用短距離掃過。', '重點：少量，只點亮骨頭最高的地方。', { spots: ['cheek', 'bridge', 'bow'] }),
            S('lips', 'lips', '唇彩', [198, 100, 92], '裸棕／米玫瑰從唇中央往外鋪滿唇形。', '重點：唇線與填色同色系，看起來才柔和。'),
        ],
        koreanClean: [
            BASE([246, 206, 176], 0.28),
            S('brows', 'eyebrow', '眉毛', [168, 116, 78], '整理成柔和平直眉，由眉頭往眉尾水平滑動。', '重點：眉頭淡、眉尾稍微清楚。', { k: 0.85 }),
            S('shadowBase', 'eyes', '眼影', [186, 120, 108], 'mocha／taupe 只放在貼近睫毛根部到眼窩的窄範圍，水平柔和暈染。', '重點：不要大面積煙燻。', { h: 0.62, axis: 'horizontal', k: 0.85 }),
            S('liner', 'eyes', '眼線', [92, 56, 44], '深棕細眼線沿上睫毛根部，眼尾只水平延伸一點點。', '重點：不要上揚，保持水平。', { wingLen: 0.08, wingUp: 0.0, thick: 0.75 }),
            S('aegyo', 'eyes', '臥蠶', [255, 226, 184], '下睫毛下方畫一條細細的亮部，下緣帶一點陰影，做出臥蠶。', '重點：只在下眼皮貼近睫毛處，不能把下眼整圈框住。'),
            S('blush', 'cheeks', '腮紅', [242, 132, 146], '低飽和玫瑰放在臉頰中央偏上，小範圍集中。', '重點：不要延伸成大片紅暈。', { mode: 'center' }),
            S('contour', 'contour', '修容', [176, 124, 92], '只在鼻側做非常輕微的修飾。', '重點：看不出來是修容才對。', { zones: ['nose'], k: 0.7 }),
            S('lips', 'lips', '唇彩', [238, 88, 110], '從唇中央開始向外做柔和漸層，中央較飽和、邊緣較柔。', '重點：邊緣用指腹抿開。', { fade: true }),
        ],
        richGirl: [
            BASE([240, 196, 160]),
            S('brows', 'eyebrow', '眉毛', [132, 88, 58], '沿原生眉型做乾淨、結構清楚的修飾，眉峰略微明確。', '重點：不要過度銳利。'),
            S('shadowBase', 'eyes', '眼影・奶茶底色', [214, 166, 124], '奶茶／taupe 先鋪眼窩底色。', '重點：底色要薄，後面還要疊。', { h: 0.9, axis: 'in-out' }),
            S('shadowDeep', 'eyes', '眼影・眼尾深度', [150, 92, 56], 'cocoa／bronze 加在眼尾做深度。', '重點：只加在眼尾三分之一。'),
            S('shimmer', 'eyes', '眼影・香檳微光', [255, 208, 110], '眼皮中央點一點香檳金微光。', '重點：很細的一小塊就夠。'),
            S('liner', 'eyes', '眼線', [64, 42, 34], '乾淨細緻的上眼線，眼尾短而精緻。', '重點：不做誇張 wing。', { wingLen: 0.1, wingUp: 0.05, thick: 0.9 }),
            S('contour', 'contour', '修容', [168, 118, 84], '顴骨下方、鼻側與下顎做細緻修容，範圍窄。', '重點：柔和，不要一條一條的。', { zones: ['cheek', 'nose', 'jaw'], narrow: true }),
            S('blush', 'cheeks', '腮紅', [224, 128, 120], '奶茶玫瑰放在偏高的位置，不做強烈拉提。', '重點：低飽和，有氣色就好。', { mode: 'high' }),
            S('highlight', 'contour', '打亮', [255, 224, 150], '顴骨高點與鼻樑加細緻香檳高光。', '重點：不要大面積發亮。', { spots: ['cheek', 'bridge'] }),
            S('lips', 'lips', '唇彩', [204, 108, 104], 'milk-tea／豆沙色，唇線乾淨、填色均勻。', '重點：先描唇線再填滿。'),
        ],
        japaneseClear: [
            BASE([250, 214, 186], 0.28),
            S('brows', 'eyebrow', '眉毛', [178, 126, 86], '沿原生眉型輕輕補色，不畫明顯眉框。', '重點：眉色比髮色淺一階。', { k: 0.8 }),
            S('shadowBase', 'eyes', '眼影', [255, 138, 150], '櫻花粉／蜜桃鋪在上眼皮，邊界非常柔和。', '重點：用指腹拍開，不要有明顯邊線。', { h: 0.8, axis: 'in-out', soft: true }),
            S('shimmer', 'eyes', '眼影・珠光', [255, 228, 168], '眼皮中央加少量珠光。', '重點：一點點就有透明感。'),
            S('liner', 'eyes', '眼線', [146, 92, 64], '棕色短眼線貼著上睫毛根部，眼尾短、模糊、自然。', '重點：不要銳利長眼線。', { wingLen: 0.05, wingUp: 0.02, thick: 0.7 }),
            S('blush', 'cheeks', '腮紅・Igari', [255, 104, 126], '眼下到上臉頰，由眼下中心往外柔和擴散，左右對稱。', '重點：不能變成整張臉泛紅。', { mode: 'igari' }),
            S('highlight', 'contour', '打亮', [255, 240, 196], '少量放在眼下、顴骨高點與鼻尖。', '重點：水光感，不要亮片。', { spots: ['undereye', 'cheek', 'tip'] }),
            S('lips', 'lips', '唇彩', [255, 84, 96], '透明感的草莓／珊瑚色，從唇中央擴散，保持水潤。', '重點：唇中央最飽和。', { fade: true, gloss: true }),
        ],
        hongKong: [
            BASE([236, 184, 146]),
            S('brows', 'eyebrow', '眉毛', [118, 72, 46], '自然豐盈、結構清楚的眉毛，不要畫成細眉。', '重點：眉身要有粗度。', { k: 1.1 }),
            S('shadowBase', 'eyes', '眼影', [196, 108, 70], '暖棕／磚紅棕從眼皮內側往外輕到中度暈染。', '重點：不要重煙燻，眼妝不能搶過紅唇。', { h: 0.85, axis: 'in-out', k: 0.9 }),
            S('shadowDeep', 'eyes', '眼影・眼尾', [150, 68, 48], '眼尾稍微加深。', '重點：範圍小。', { k: 0.85 }),
            S('liner', 'eyes', '眼線・復古', [38, 24, 24], '只畫上眼線，眼尾做短而乾淨的復古延伸。', '重點：不畫下眼線、不做全包。', { wingLen: 0.15, wingUp: 0.08, thick: 1.1 }),
            S('lashesUp', 'eyes', '睫毛', [30, 20, 20], '自然定義睫毛，不需要濃密假睫毛。', '重點：根根分明。', { k: 0.7 }),
            S('blush', 'cheeks', '腮紅', [222, 118, 86], '暖色、低調，放在臉頰偏外側。', '重點：不要大片粉紅。', { mode: 'outer', k: 0.85 }),
            S('contour', 'contour', '修容', [160, 102, 72], '成熟柔和的輪廓修飾。', '重點：順著顴骨下方帶開。', { zones: ['cheek'] }),
            S('lips', 'lips', '紅唇', [206, 26, 42], '這是視覺中心：從唇中央往外鋪滿真實唇形，最後描清楚唇緣。', '重點：唇緣要乾淨俐落，紅唇才有復古感。', { outlineLast: true, dur: 1.6, k: 1.15 }),
        ],
        yandere: [
            BASE([244, 212, 200], 0.28),
            S('brows', 'eyebrow', '眉毛', [128, 94, 86], '沿原生眉型整理，不要過度濃黑。', '重點：眉色偏灰棕。', { k: 0.8 }),
            S('shadowBase', 'eyes', '上眼影', [186, 88, 112], 'dusty rose／muted berry 從上眼皮開始做較深的煙燻暈染。', '重點：暈到眼窩，邊緣推開。', { h: 1.0, axis: 'in-out', k: 1.1 }),
            S('shadowDeep', 'eyes', '上眼影・煙燻', [118, 52, 60], 'smoky red-brown 疊在眼尾與眼褶。', '重點：眼尾最深。'),
            S('lowerShadow', 'eyes', '下眼影', [176, 66, 84], '下睫毛根部加 smoky red-brown，眼尾較深、越靠眼頭越淡。', '重點：只在下眼皮皮膚，不能蓋到眼白。'),
            S('liner', 'eyes', '眼線', [52, 28, 34], '沿上睫毛根部加強深色包覆感。', '重點：不能把眼睛畫大或改眼型。', { wingLen: 0.1, wingUp: 0.03, thick: 1.25 }),
            S('lowerLiner', 'eyes', '下眼線', [70, 34, 42], '下睫毛根部做 controlled 的定義，眼尾較明顯。', '重點：不要整圈黑框。'),
            S('lashesLow', 'eyes', '下睫毛', [40, 22, 28], '下睫毛比其他妝容更明顯，一根一根畫出來。', '重點：眼尾的比較長。'),
            S('blush', 'cheeks', '腮紅', [232, 106, 128], 'dusty rose 只放在眼下到上臉頰的小範圍。', '重點：compact、強度低，不能整片臉紅。', { mode: 'igari', compact: true, k: 0.85 }),
            S('lips', 'lips', '唇彩', [186, 36, 74], 'dried rose／muted berry，水潤光澤，從唇中央向外鋪色。', '重點：唇中央最濃。', { fade: true, gloss: true }),
        ],
        mensPlain: [
            S('basePatch', 'base', '膚色修飾', [236, 186, 150], '只在眼下、鼻翼與下巴等暗沉處做很淡的局部修正。', '重點：不要整臉上粉底。', { k: 0.8 }),
            S('brows', 'eyebrow', '眉毛', [96, 70, 54], '沿原生眉毛只補空隙，保持自然男性眉型。', '重點：不描完整眉框。', { k: 0.75, partial: true }),
            S('undereye', 'eyes', '眼周修飾', [232, 190, 156], '只做非常輕微的眼下暗沉修飾。', '重點：不要出現裝飾性眼影。', { k: 0.7 }),
            S('contour', 'contour', '輪廓陰影', [172, 128, 98], '鼻側、顴骨與下顎只做非常輕微的自然陰影。', '重點：看不出來有修容。', { zones: ['nose', 'cheek', 'jaw'], narrow: true, k: 0.6 }),
            S('lips', 'lips', '護唇', [236, 150, 140], '透明護唇或極低飽和唇色，淡淡的光澤覆蓋嘴唇。', '重點：自然就好。', { gloss: true, k: 0.55 }),
        ],
    };
    // 某些妝容刻意沒有某個部位（男士白開水不畫腮紅）。部位按鈕按下去時要講出來，不能沒反應。
    const SKIPPED_PARTS = {
        mensPlain: { cheeks: '男士白開水不上腮紅——這個妝的重點是自然修飾，不要有明顯的顏色。' },
        yandere: { contour: '病嬌妝的重點在眼妝，不特別修容；保留白皙、帶點脆弱感的臉部輪廓。' },
    };
    const DEFAULT_STYLE = 'softBaddie';

    // ── 漫畫塗鴉風的濃度 ────────────────────────────────────────────
    // 原規格是 TINT 0.23 / LINE 0.50，在照片上太淡，會被照片本身的妝色吃掉。
    // 2026-09-28 使用者反映太快：刷色 1.45→2.6 秒、每步 3.3→5.2 秒。
    const TINT_A = 0.40, LINE_A = 0.88, APPLY = 2.6, STEP_TIME = 5.2;
    // 柔和羽化的部位（腮紅、修容、打亮、底妝…）用較柔的邊，其餘保持漫畫線條的銳利
    const SOFT_KINDS = new Set(['base', 'basePatch', 'blush', 'contour', 'highlight', 'aegyo', 'lowerShadow', 'undereye', 'shimmer']);

    // ── 小工具 ───────────────────────────────────────────────────
    const add = (a, b) => ({ x: a.x + b.x, y: a.y + b.y }), sub = (a, b) => ({ x: a.x - b.x, y: a.y - b.y });
    const scale = (a, s) => ({ x: a.x * s, y: a.y * s }), len = a => Math.hypot(a.x, a.y);
    const norm = a => { const l = len(a) || 1; return { x: a.x / l, y: a.y / l }; };
    const dot = (a, b) => a.x * b.x + a.y * b.y, dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
    const lerp = (a, b, t) => a + (b - a) * t, clamp = (v, a, b) => Math.max(a, Math.min(b, v));
    const smooth = t => { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); };
    const centroid = p => { let x = 0, y = 0; for (const q of p) { x += q.x; y += q.y; } return { x: x / p.length, y: y / p.length }; };
    const mid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
    const bbox = p => { const b = { minX: 1e9, minY: 1e9, maxX: -1e9, maxY: -1e9 }; for (const q of p) { b.minX = Math.min(b.minX, q.x); b.minY = Math.min(b.minY, q.y); b.maxX = Math.max(b.maxX, q.x); b.maxY = Math.max(b.maxY, q.y); } return b; };
    const ebox = e => { const r = Math.max(e.rx, e.ry); return { minX: e.cx - r, minY: e.cy - r, maxX: e.cx + r, maxY: e.cy + r }; };
    const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
    const ink = c => c.map(v => Math.round(v * 0.5));

    // ── MediaPipe：只載一次，偵測結果依圖片網址快取 ─────────────────────
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
    // 偵測用另外載一張帶 crossOrigin 的圖，不去動畫面上那張：那張若 CORS 失敗會整張顯示不出來。
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
        for (let tries = 0; tries < 3 && !lm; tries++) {
            lm = await new Promise(resolve => { pendingResolve = resolve; fm.send({ image: im }).catch(() => resolve(null)); });
        }
        const out = lm ? { lm, w: im.naturalWidth, h: im.naturalHeight } : null;
        if (out) landmarkCache.set(url, out);
        return out;
    }

    // ── 控制器：一個人像框一個 ─────────────────────────────────────
    function create({ frame, url, styleId, onChange }) {
        const plan = PLANS[styleId] || PLANS[DEFAULT_STYLE];
        const skipped = SKIPPED_PARTS[styleId] || {};
        const canvas = document.createElement('canvas');
        canvas.className = 'look-tutor-canvas';
        canvas.setAttribute('aria-hidden', 'true');
        frame.appendChild(canvas);
        const ctx = canvas.getContext('2d');
        const off = document.createElement('canvas'), octx = off.getContext('2d');
        const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        let data = null;
        let W = 0, H = 0, SC = 1, DX = 0, DY = 0;
        let state = 'idle', error = '', note = '';
        let seq = [], pos = 0, stepT = 0, clock = 0, playing = false, finished = false, raf = 0, last = null, mode = null;

        const emit = () => { if (typeof onChange === 'function') onChange(api.snapshot()); };

        function layout() {
            const r = frame.getBoundingClientRect();
            W = Math.round(r.width); H = Math.round(r.height);
            canvas.width = W; canvas.height = H; off.width = W; off.height = H;
            if (data) { SC = Math.max(W / data.w, H / data.h); DX = (W - data.w * SC) / 2; DY = 0; }
        }
        const getP = i => ({ x: DX + data.lm[i][0] * data.w * SC, y: DY + data.lm[i][1] * data.h * SC });
        const getPs = a => a.map(getP);
        const faceAxisAngle = () => { const d = sub(getP(454), getP(234)); return Math.atan2(d.y, d.x); };
        const faceUpVec = () => norm(sub(getP(10), getP(152)));
        const faceW = () => dist(getP(234), getP(454));
        const unitW = () => data.w * SC;

        // 眼睛的共用量：上眼皮、眼窩方向與高度、眼寬
        function eyeFrame(s) {
            const lid = getPs(s === 'R' ? LID_R : LID_L), lidC = centroid(lid);
            const creaseC = centroid(getPs(s === 'R' ? CREASE_R : CREASE_L));
            const up = norm(sub(creaseC, lidC)), h = dot(sub(creaseC, lidC), up);
            const inner = lid[0], outer = lid[lid.length - 1];
            return { lid, lidC, up, down: scale(up, -1), h, inner, outer, eyeW: dist(inner, outer), outward: norm(sub(outer, lidC)),
                low: getPs(s === 'R' ? LOW_R : LOW_L) };
        }

        // ── 幾何（規格 §4 的原樣，加上參數化） ──
        function eyeshadowPoly(s, st) {
            const E = eyeFrame(s), n = E.lid.length, h = E.h * 0.92 * (st.h || 1);
            const inner0 = st.axis === 'horizontal' ? 0.8 : 0.55;   // 韓系：內外高度接近＝水平感
            const top = E.lid.map((p, i) => add(p, scale(E.up, h * (inner0 + (1 - inner0) * (i / (n - 1))))));
            const tail = add(add(E.outer, scale(E.up, h * 0.85)), scale(E.outward, E.eyeW * (st.axis === 'horizontal' ? 0.06 : 0.12)));
            const poly = []; for (let i = 0; i < n; i++) poly.push(E.lid[i]); poly.push(tail); for (let i = n - 1; i >= 0; i--) poly.push(top[i]);
            return poly;
        }
        function eyeshadowDeepPoly(s, st) {
            const E = eyeFrame(s), n = E.lid.length, k = Math.floor(n * 0.52), lift = st.lift || 1;
            const bottom = E.lid.slice(k);
            const top = []; for (let i = k; i < n; i++) { const f = (i - k) / (n - 1 - k); top.push(add(E.lid[i], scale(E.up, E.h * (0.72 + 0.45 * f) * lift))); }
            const tail = add(add(E.outer, scale(E.up, E.h * 0.95 * lift)), scale(E.outward, E.eyeW * 0.16 * lift));
            const poly = [...bottom, tail]; for (let i = top.length - 1; i >= 0; i--) poly.push(top[i]);
            return poly;
        }
        function shimmerEllipse(s) {
            const E = eyeFrame(s), c = add(E.lidC, scale(E.up, E.h * 0.38));
            const d = sub(E.outer, E.inner);
            return { cx: c.x, cy: c.y, rx: E.eyeW * 0.14, ry: E.h * 0.2, rot: Math.atan2(d.y, d.x) };
        }
        function linerData(s, st) {
            const E = eyeFrame(s), prev = E.lid[E.lid.length - 2], dir = norm(sub(E.outer, prev));
            const wing = add(add(E.outer, scale(dir, E.eyeW * (st.wingLen ?? 0.13))), scale(E.up, E.eyeW * (st.wingUp ?? 0.05)));
            return { path: E.lid.concat([wing]), eyeW: E.eyeW, thick: st.thick || 1 };
        }
        // 下眼皮的帶狀區：臥蠶（中間厚、兩端細）、下眼影（眼頭淡、眼尾厚）
        function lowerBand(s, profile) {
            const E = eyeFrame(s), n = E.low.length, off = [];
            for (let i = 0; i < n; i++) off.push(add(E.low[i], scale(E.down, E.h * profile(i / (n - 1)))));
            return E.low.concat(off.reverse());
        }
        function lowerLinerData(s) {
            const E = eyeFrame(s), n = E.low.length, start = Math.floor(n * 0.35);
            return { path: E.low.slice(start).reverse(), eyeW: E.eyeW, thick: 0.6 };
        }
        // 睫毛：沿眼瞼外側的短線，progress 決定畫到第幾根
        function lashStrokes(s, lower) {
            const E = eyeFrame(s), src = lower ? E.low : E.lid, n = src.length, out = [];
            const from = Math.floor(n * (lower ? 0.3 : 0.4));
            for (let i = n - 1; i >= from; i--) {
                const f = (i - from) / Math.max(1, n - 1 - from);
                const dir = norm(add(lower ? E.down : E.up, scale(E.outward, 0.35 + 0.4 * f)));
                const L = E.h * (lower ? 0.28 + 0.22 * f : 0.34 + 0.3 * f);
                out.push([src[i], add(src[i], scale(dir, L))]);
            }
            return out;
        }
        function blushEllipse(s, st) {
            const c = s === 'R' ? centroid(getPs([50, 101, 205])) : centroid(getPs([280, 330, 425]));
            const fw = faceW(), lat = norm(sub(s === 'R' ? getP(234) : getP(454), c)), up = faceUpVec();
            let cc = add(c, scale(lat, fw * 0.05)), rx = fw * 0.095, ry = fw * 0.072, tilt = 0.349;
            if (st.mode === 'lifted') { cc = add(add(cc, scale(up, fw * 0.035)), scale(lat, fw * 0.02)); rx *= 1.1; tilt = 0.55; }
            if (st.mode === 'high') { cc = add(cc, scale(up, fw * 0.02)); tilt = 0.2; }
            if (st.mode === 'center') { cc = add(sub(cc, scale(lat, fw * 0.035)), scale(up, fw * 0.01)); rx *= 0.72; ry *= 0.78; tilt = 0.1; }
            if (st.mode === 'outer') { cc = add(cc, scale(lat, fw * 0.045)); rx *= 0.9; tilt = 0.25; }
            if (st.mode === 'igari') {
                const E = eyeFrame(s), lowMid = E.low[Math.floor(E.low.length / 2)];
                cc = add(lowMid, scale(E.down, E.eyeW * 0.55));
                rx = E.eyeW * (st.compact ? 0.55 : 0.78); ry = E.eyeW * (st.compact ? 0.26 : 0.34); tilt = 0;
            }
            return { cx: cc.x, cy: cc.y, rx, ry, rot: faceAxisAngle() + (s === 'R' ? -tilt : tilt) };
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
        function contourShapes(st) {
            const fw = faceW(), noseW = dist(getP(48), getP(278)), out = [], narrow = st.narrow ? 0.7 : 1;
            const zones = st.zones || ['cheek', 'nose'];
            if (zones.includes('cheek')) for (const [a, b] of [[116, 206], [345, 426]]) {
                // outIn：由臉外側往內掃，所以軸的起點是外側那一點
                const pa = getP(a), pb = getP(b), c = mid(pa, pb), d = sub(pb, pa);
                out.push({ type: 'ellipse', e: { cx: c.x, cy: c.y, rx: len(d) * 0.52, ry: fw * 0.028 * narrow, rot: Math.atan2(d.y, d.x) }, axis: { S: pa, E: pb } });
            }
            if (zones.includes('temple')) for (const [a, b] of [[54, 127], [284, 356]]) {
                const pa = getP(a), pb = getP(b), c = mid(pa, pb), d = sub(pb, pa);
                out.push({ type: 'ellipse', e: { cx: c.x, cy: c.y, rx: len(d) * 0.34, ry: fw * 0.03, rot: Math.atan2(d.y, d.x) }, axis: { S: pb, E: pa } });
            }
            if (zones.includes('jaw')) for (const idx of [[172, 136, 150, 149], [397, 365, 379, 378]]) {
                const pts = getPs(idx);
                out.push({ type: 'poly', pts: stripPoly(idx, fw * 0.034 * narrow, fw * 0.02 * narrow), axis: { S: pts[0], E: pts[pts.length - 1] } });
            }
            if (zones.includes('nose')) {
                out.push({ type: 'poly', pts: stripPoly([55, 122, 196, 3, 51, 45], noseW * 0.12 * narrow, noseW * 0.26 * narrow), axis: { S: getP(55), E: getP(45) } });
                out.push({ type: 'poly', pts: stripPoly([285, 351, 419, 248, 281, 275], noseW * 0.12 * narrow, noseW * 0.26 * narrow), axis: { S: getP(285), E: getP(275) } });
            }
            return out;
        }
        function highlightShapes(st) {
            const fw = faceW(), noseW = dist(getP(48), getP(278)), out = [];
            const spots = st.spots || ['cheek'];
            const ell = (c, rx, ry, rot = faceAxisAngle()) => ({ type: 'ellipse', e: { cx: c.x, cy: c.y, rx, ry, rot } });
            if (spots.includes('cheek')) {
                out.push(ell(centroid(getPs([117, 118, 119])), fw * 0.05, fw * 0.022, faceAxisAngle() - 0.4));
                out.push(ell(centroid(getPs([346, 347, 348])), fw * 0.05, fw * 0.022, faceAxisAngle() + 0.4));
            }
            if (spots.includes('bridge')) {
                const pts = getPs([168, 6, 197, 195]);
                out.push({ type: 'poly', pts: stripPoly([168, 6, 197, 195], noseW * 0.1, noseW * 0.08), axis: { S: pts[0], E: pts[3] } });
            }
            if (spots.includes('tip')) out.push(ell(getP(4), noseW * 0.12, noseW * 0.09));
            if (spots.includes('bow')) out.push(ell(add(getP(0), scale(faceUpVec(), fw * 0.012)), fw * 0.03, fw * 0.01));
            if (spots.includes('undereye')) for (const s of ['R', 'L']) {
                const E = eyeFrame(s), m = E.low[Math.floor(E.low.length / 2)];
                out.push(ell(add(m, scale(E.down, E.eyeW * 0.28)), E.eyeW * 0.32, E.eyeW * 0.1));
            }
            return out;
        }
        function patchShapes() {
            const fw = faceW(), out = [];
            for (const s of ['R', 'L']) {
                const E = eyeFrame(s), m = E.low[Math.floor(E.low.length / 2)];
                const c = add(m, scale(E.down, E.eyeW * 0.3));
                out.push({ type: 'ellipse', e: { cx: c.x, cy: c.y, rx: E.eyeW * 0.4, ry: E.eyeW * 0.14, rot: faceAxisAngle() } });
            }
            for (const i of [129, 358]) { const p = getP(i); out.push({ type: 'ellipse', e: { cx: p.x, cy: p.y, rx: fw * 0.03, ry: fw * 0.026, rot: 0 } }); }
            const chin = add(getP(152), scale(faceUpVec(), fw * 0.06));
            out.push({ type: 'ellipse', e: { cx: chin.x, cy: chin.y, rx: fw * 0.08, ry: fw * 0.04, rot: faceAxisAngle() } });
            return out;
        }

        // 每一步要畫的形狀。side 決定筆刷方向；axis 有給就用它。
        function shapesFor(st) {
            const both = f => ['R', 'L'].map(s => ({ ...f(s), side: s }));
            switch (st.kind) {
                case 'base': return [{ type: 'poly', pts: getPs(FACE_OVAL), side: 'M', holes: [getPs(EYE_R), getPs(EYE_L), getPs(BROW_R), getPs(BROW_L), getPs(LIPS_OUT)], axis: { S: getP(10), E: getP(152) } }];
                case 'basePatch': return patchShapes();
                case 'brows': return both(s => {
                    const pts = getPs(s === 'R' ? BROW_R : BROW_L);
                    return { type: 'poly', pts, axis: s === 'R' ? { S: getP(55), E: getP(46) } : { S: getP(285), E: getP(276) } };
                });
                case 'shadowBase': return both(s => {
                    const E = eyeFrame(s);
                    return { type: 'poly', pts: eyeshadowPoly(s, st), axis: { S: E.inner, E: E.outer } };
                });
                case 'shadowDeep': return both(s => {
                    const E = eyeFrame(s);
                    return { type: 'poly', pts: eyeshadowDeepPoly(s, st), axis: { S: E.outer, E: E.lid[4] } };
                });
                case 'shimmer': return both(s => ({ type: 'ellipse', e: shimmerEllipse(s), radial: true }));
                case 'aegyo': return both(s => {
                    const E = eyeFrame(s);
                    return { type: 'poly', pts: lowerBand(s, t => 0.06 + 0.26 * Math.sin(Math.PI * t)), axis: { S: E.low[0], E: E.low[E.low.length - 1] } };
                });
                case 'lowerShadow': return both(s => {
                    const E = eyeFrame(s);
                    return { type: 'poly', pts: lowerBand(s, t => 0.08 + 0.5 * t), axis: { S: E.low[E.low.length - 1], E: E.low[0] } };
                });
                case 'undereye': return both(s => {
                    const E = eyeFrame(s);
                    return { type: 'poly', pts: lowerBand(s, t => 0.1 + 0.3 * Math.sin(Math.PI * t)), axis: { S: E.low[0], E: E.low[E.low.length - 1] } };
                });
                case 'liner': return both(s => ({ type: 'line', d: linerData(s, st) }));
                case 'lowerLiner': return both(s => ({ type: 'line', d: lowerLinerData(s) }));
                case 'lashesUp': return both(s => ({ type: 'lashes', strokes: lashStrokes(s, false) }));
                case 'lashesLow': return both(s => ({ type: 'lashes', strokes: lashStrokes(s, true) }));
                case 'blush': return both(s => {
                    const e = blushEllipse(s, st), C = { x: e.cx, y: e.cy };
                    if (st.mode === 'igari') return { type: 'ellipse', e, radial: true };
                    // 由低內往斜上外（太陽穴）掃
                    const lat = norm(sub(s === 'R' ? getP(234) : getP(454), C));
                    const dir = norm(add(scale(faceUpVec(), 0.72), scale(lat, 0.72))), r = Math.max(e.rx, e.ry);
                    return { type: 'ellipse', e, axis: { S: sub(C, scale(dir, r)), E: add(C, scale(dir, r)) } };
                });
                case 'contour': return contourShapes(st);
                case 'highlight': return highlightShapes(st).map(sh => ({ ...sh, radial: !sh.axis }));
                case 'lips': return [{ type: 'poly', pts: getPs(LIPS_OUT), radial: true, lips: true }];
            }
            return [];
        }

        // ── 繪製：飽和底色＋實斜線（會流動）＋深色虛線墨框 ──
        const pathPoly = (c, pts) => { c.beginPath(); c.moveTo(pts[0].x, pts[0].y); for (let i = 1; i < pts.length; i++) c.lineTo(pts[i].x, pts[i].y); c.closePath(); };
        const pathEllipse = (c, e) => { c.beginPath(); c.ellipse(e.cx, e.cy, Math.max(1, e.rx), Math.max(1, e.ry), e.rot, 0, Math.PI * 2); };
        function compositeSoft(blur) { ctx.save(); ctx.filter = blur > 0 ? `blur(${blur}px)` : 'none'; ctx.drawImage(off, 0, 0); ctx.restore(); ctx.filter = 'none'; }

        function renderZone(sh, st, o) {
            const color = st.color, soft = SOFT_KINDS.has(st.kind), u = unitW();
            const traceFn = sh.type === 'poly' ? c => pathPoly(c, sh.pts) : c => pathEllipse(c, sh.e);
            const box = sh.type === 'poly' ? bbox(sh.pts) : ebox(sh.e);
            octx.clearRect(0, 0, W, H);
            octx.save(); traceFn(octx); octx.clip();
            // 唇的漸層（中央較飽和、邊緣較柔）與水光：用徑向漸層取代平塗
            const tint = TINT_A * o.fill * st.k;
            if (sh.lips && st.fade) {
                const c = centroid(sh.pts), b = bbox(sh.pts), r = Math.max(b.maxX - b.minX, b.maxY - b.minY) * 0.6;
                const g = octx.createRadialGradient(c.x, c.y, 0, c.x, c.y, r);
                g.addColorStop(0, rgba(color, Math.min(1, tint * 1.9))); g.addColorStop(1, rgba(color, tint * 0.6));
                octx.fillStyle = g; octx.fillRect(0, 0, W, H);
            } else {
                octx.globalAlpha = tint; octx.fillStyle = rgba(color, 1); octx.fillRect(0, 0, W, H); octx.globalAlpha = 1;
            }
            // 斜線：線寬與間距比原規格粗、疏一點，像漫畫網點的手繪斜線；播放中的那一步會緩緩流動
            const lineA = st.kind === 'base' ? 0 : LINE_A * o.line * st.k * (soft ? 0.75 : 1);
            if (lineA > 0) {
                octx.globalAlpha = lineA; octx.strokeStyle = rgba(color, 1);
                octx.lineWidth = Math.max(1.6, u * 0.0034); octx.lineCap = 'round';
                const cx = (box.minX + box.maxX) / 2, cy = (box.minY + box.maxY) / 2, diag = Math.hypot(box.maxX - box.minX, box.maxY - box.minY) + 30;
                const sp = clamp(u * 0.014, 6, 12), flow = o.flow ? (clock * 14) % sp : 0;
                octx.translate(cx, cy); octx.rotate(-Math.PI / 4);
                for (let x = -diag + flow; x <= diag; x += sp) { octx.beginPath(); octx.moveTo(x, -diag); octx.lineTo(x, diag); octx.stroke(); }
            }
            octx.restore();
            if (sh.holes) {
                octx.save(); octx.globalCompositeOperation = 'destination-out';
                for (const h of sh.holes) { pathPoly(octx, h); octx.fill(); }
                octx.restore();
            }
            // 水光：唇上一道白色高光
            if (sh.lips && st.gloss) {
                const b = bbox(sh.pts), c = centroid(sh.pts);
                octx.save(); traceFn(octx); octx.clip();
                octx.fillStyle = `rgba(255,255,255,${0.55 * o.fill})`;
                octx.beginPath(); octx.ellipse(c.x - (b.maxX - b.minX) * 0.08, c.y + (b.maxY - b.minY) * 0.12, (b.maxX - b.minX) * 0.14, (b.maxY - b.minY) * 0.08, 0, 0, Math.PI * 2); octx.fill();
                octx.restore();
            }
            // 墨線虛線框。港風紅唇的唇緣留到最後才描清楚（outlineLast）。
            let outlineA = (soft ? 0.5 : 0.9) * o.fill;
            if (st.outlineLast && o.reveal) outlineA *= smooth((o.p - 0.7) / 0.3);
            if (outlineA > 0.01) {
                octx.save();
                octx.strokeStyle = rgba(ink(color), outlineA);
                octx.lineWidth = Math.max(1.3, u * 0.0026) * (st.outlineLast ? 1.6 : 1);
                octx.setLineDash(soft ? [u * 0.006, u * 0.01] : [u * 0.012, u * 0.007]);
                octx.lineDashOffset = o.flow ? -clock * 22 : 0;
                traceFn(octx); octx.stroke();
                octx.restore();
            }
        }
        function axisOf(sh) {
            if (sh.axis) return sh.axis;
            const b = sh.type === 'poly' ? bbox(sh.pts) : ebox(sh.e);
            return { S: { x: b.minX, y: (b.minY + b.maxY) / 2 }, E: { x: b.maxX, y: (b.minY + b.maxY) / 2 } };
        }
        // 方向陰影（2026-09-28 使用者要求「有方向感、左右移動的陰影」）：
        // 一道比色塊深的柔邊陰影帶，沿筆刷方向移動。刷色時貼著前緣走；刷完之後在區塊裡來回掃，
        // 讓人一直看得出這一步是往哪個方向刷。只畫在區塊裡面（clip），不會跑到五官外。
        // pos 是 0～1 沿軸線的位置；由內往外擴散的部位（唇、Igari 腮紅…）改成一圈往外推的環。
        function sweepShadow(sh, st, pos) {
            const trace = sh.type === 'poly' ? c => pathPoly(c, sh.pts) : c => pathEllipse(c, sh.e);
            const shade = ink(st.color);
            const a = 0.72 * Math.min(1, st.k + 0.25);
            octx.save(); trace(octx); octx.clip();
            let g;
            if (sh.radial) {
                const c = sh.type === 'poly' ? centroid(sh.pts) : { x: sh.e.cx, y: sh.e.cy };
                const b = sh.type === 'poly' ? bbox(sh.pts) : ebox(sh.e);
                const R = Math.hypot(b.maxX - b.minX, b.maxY - b.minY) * 0.55 + 2;
                g = octx.createRadialGradient(c.x, c.y, 0, c.x, c.y, R);
                const m = clamp(pos, 0.08, 0.95), w = 0.2;
                g.addColorStop(0, rgba(shade, 0)); g.addColorStop(Math.max(0, m - w), rgba(shade, 0));
                g.addColorStop(m, rgba(shade, a)); g.addColorStop(Math.min(1, m + w), rgba(shade, 0)); g.addColorStop(1, rgba(shade, 0));
            } else {
                const ax = axisOf(sh);
                g = octx.createLinearGradient(ax.S.x, ax.S.y, ax.E.x, ax.E.y);
                const m = clamp(pos, 0, 1), w = 0.22;
                g.addColorStop(0, rgba(shade, 0));
                if (m - w > 0) g.addColorStop(m - w, rgba(shade, 0));
                g.addColorStop(m, rgba(shade, a));
                if (m + w < 1) g.addColorStop(m + w, rgba(shade, 0));
                g.addColorStop(1, rgba(shade, 0));
            }
            octx.fillStyle = g; octx.fillRect(0, 0, W, H);
            octx.restore();
        }
        function revealMask(sh, p) {
            if (sh.radial) {
                const c = sh.type === 'poly' ? centroid(sh.pts) : { x: sh.e.cx, y: sh.e.cy };
                const b = sh.type === 'poly' ? bbox(sh.pts) : ebox(sh.e);
                const R = Math.hypot(b.maxX - b.minX, b.maxY - b.minY) * 0.6 + 2, head = p * R * 1.25;
                const g = octx.createRadialGradient(c.x, c.y, 0, c.x, c.y, R * 1.3);
                const t0 = clamp(head / (R * 1.3), 0, 1), t1 = clamp((head + R * 0.25) / (R * 1.3), 0, 1);
                g.addColorStop(0, 'rgba(0,0,0,1)'); g.addColorStop(t0, 'rgba(0,0,0,1)');
                if (t1 > t0 + 0.001) g.addColorStop(t1, 'rgba(0,0,0,0)');
                if (t1 < 0.999) g.addColorStop(1, 'rgba(0,0,0,0)');
                octx.save(); octx.globalCompositeOperation = 'destination-in'; octx.fillStyle = g; octx.fillRect(0, 0, W, H); octx.restore();
                return;
            }
            const ax = axisOf(sh);
            const d = sub(ax.E, ax.S), Ltot = len(d) || 1, feather = Math.max(14, Ltot * 0.22);
            const head = p * (Ltot + feather), t0 = clamp(head / Ltot, 0, 1), t1 = clamp((head + feather) / Ltot, 0, 1);
            const g = octx.createLinearGradient(ax.S.x, ax.S.y, ax.E.x, ax.E.y);
            g.addColorStop(0, 'rgba(0,0,0,1)'); g.addColorStop(Math.min(t0, 1), 'rgba(0,0,0,1)');
            if (t1 > t0 + 0.001) g.addColorStop(Math.min(t1, 1), 'rgba(0,0,0,0)');
            if (t1 < 0.999) g.addColorStop(1, 'rgba(0,0,0,0)');
            octx.save(); octx.globalCompositeOperation = 'destination-in'; octx.fillStyle = g; octx.fillRect(0, 0, W, H); octx.restore();
        }
        function drawLine(d, st, o) {
            const path = d.path, segs = []; let total = 0;
            for (let i = 0; i < path.length - 1; i++) { const L = dist(path[i], path[i + 1]); segs.push(L); total += L; }
            const drawLen = total * (o.reveal ? o.p : 1);
            octx.clearRect(0, 0, W, H); octx.save();
            octx.strokeStyle = rgba(st.color, 1); octx.globalAlpha = Math.min(1, 0.95 * o.fill * st.k); octx.lineJoin = 'round'; octx.lineCap = 'round';
            let acc = 0;
            for (let i = 0; i < path.length - 1; i++) {
                const L = segs[i], t = i / Math.max(1, path.length - 2);
                octx.lineWidth = d.eyeW * (0.022 + 0.06 * t) * d.thick;
                if (acc + L <= drawLen) { octx.beginPath(); octx.moveTo(path[i].x, path[i].y); octx.lineTo(path[i + 1].x, path[i + 1].y); octx.stroke(); }
                else if (acc < drawLen) { const f = (drawLen - acc) / L; octx.beginPath(); octx.moveTo(path[i].x, path[i].y); octx.lineTo(lerp(path[i].x, path[i + 1].x, f), lerp(path[i].y, path[i + 1].y, f)); octx.stroke(); break; }
                acc += L;
            }
            octx.restore();
            // 筆尖陰影：畫到哪裡，筆就在哪裡
            if (o.reveal && o.p < 1 && drawLen > 0) {
                let rem = drawLen, tip = path[0];
                for (let i = 0; i < segs.length; i++) {
                    if (rem <= segs[i]) { const f = rem / segs[i]; tip = { x: lerp(path[i].x, path[i + 1].x, f), y: lerp(path[i].y, path[i + 1].y, f) }; break; }
                    rem -= segs[i]; tip = path[i + 1];
                }
                const r = d.eyeW * 0.16, gg = octx.createRadialGradient(tip.x, tip.y, 0, tip.x, tip.y, r);
                gg.addColorStop(0, rgba(ink(st.color), 0.55)); gg.addColorStop(1, rgba(ink(st.color), 0));
                octx.fillStyle = gg; octx.beginPath(); octx.arc(tip.x, tip.y, r, 0, Math.PI * 2); octx.fill();
            }
            compositeSoft(0.4);
        }
        function drawLashes(strokes, st, o) {
            const n = strokes.length, shown = o.reveal ? o.p * n : n;
            octx.clearRect(0, 0, W, H); octx.save();
            octx.strokeStyle = rgba(st.color, 1); octx.lineCap = 'round'; octx.lineWidth = Math.max(1.3, unitW() * 0.0028);
            for (let i = 0; i < n; i++) {
                const f = clamp(shown - i, 0, 1); if (f <= 0) break;
                const [a, b] = strokes[i];
                octx.globalAlpha = Math.min(1, 0.95 * o.fill * st.k);
                octx.beginPath(); octx.moveTo(a.x, a.y); octx.lineTo(lerp(a.x, b.x, f), lerp(a.y, b.y, f)); octx.stroke();
            }
            octx.restore(); compositeSoft(0.3);
        }
        function drawStep(st, o) {
            for (const sh of shapesFor(st)) {
                if (sh.type === 'line') { drawLine(sh.d, st, o); continue; }
                if (sh.type === 'lashes') { drawLashes(sh.strokes, st, o); continue; }
                renderZone(sh, st, o);
                if (o.reveal && o.p < 1) revealMask(sh, o.p);
                if (o.sweep != null && st.kind !== 'base') sweepShadow(sh, st, o.sweep);
                compositeSoft(SOFT_KINDS.has(st.kind) ? 1.0 : 0.35);
            }
        }

        // ── 播放 ──
        const stepTime = st => STEP_TIME * (st.dur || 1), applyTime = st => APPLY * (st.dur || 1);
        function render() {
            ctx.clearRect(0, 0, W, H);
            if (!data || !seq.length) return;
            for (let i = 0; i < pos; i++) drawStep(plan[seq[i]], { fill: 0.9, line: 0.7, reveal: false });
            const st = plan[seq[pos]];
            if (finished) { drawStep(st, { fill: 0.9, line: 0.7, reveal: false }); return; }
            const p = reduceMotion ? 1 : smooth(clamp((stepT - 0.18) / applyTime(st), 0, 1));
            // 陰影位置：刷色時跟著前緣；刷完後以 1.1 秒一趟來回掃（0→1→0），直到下一步
            // 陰影像刷子一樣左右來回：從一開始就在「已刷到的範圍」內來回掃（範圍隨刷色擴大），
            // 刷完後在整個區塊來回。一趟 1.4 秒。
            let sweep = null;
            if (!reduceMotion) {
                const t = Math.max(0, stepT - 0.18) / 1.4;
                const swing = 0.5 - 0.5 * Math.cos(Math.PI * t);   // 0→1→0 來回
                sweep = Math.min(1, p * 1.05) * swing;
            }
            drawStep(st, { fill: 1, line: 1, reveal: !reduceMotion, p, flow: !reduceMotion, sweep });
        }
        function frameTick(ts) {
            raf = 0;
            if (last == null) last = ts;
            let dt = (ts - last) / 1000; last = ts; if (dt > 0.1) dt = 0.1;
            clock += dt;
            if (playing) {
                stepT += dt;
                if (stepT >= stepTime(plan[seq[pos]])) {
                    if (pos < seq.length - 1) { pos += 1; stepT = 0; emit(); }
                    else { finished = true; playing = false; emit(); }
                }
            }
            render();
            // 暫停時斜線仍要慢慢流動（漫畫感），所以只要有東西在畫面上就持續重畫
            if (seq.length && !finished && !reduceMotion) raf = requestAnimationFrame(frameTick);
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
            note = ''; seq = nextSeq; mode = nextMode; pos = 0; stepT = 0; finished = false;
            canvas.classList.add('is-on');
            playing = true; emit(); startLoop();
        }

        const ro = window.ResizeObserver ? new ResizeObserver(() => { if (data) { layout(); render(); } }) : null;
        if (ro) ro.observe(frame);

        const api = {
            async playAll() {
                if (!await ensureReady()) return;
                begin(plan.map((_, i) => i), 'all');
            },
            async playPart(part) {
                if (skipped[part]) {
                    stopLoop(); playing = false; seq = []; mode = part; note = skipped[part];
                    canvas.classList.remove('is-on'); ctx.clearRect(0, 0, W, H); emit();
                    return;
                }
                if (!await ensureReady()) return;
                const idx = plan.map((s, i) => (s.part === part ? i : -1)).filter(i => i >= 0);
                if (idx.length) begin(idx, part);
            },
            toggle() {
                if (!seq.length) return;
                if (finished) { pos = 0; stepT = 0; finished = false; playing = true; startLoop(); emit(); return; }
                playing = !playing; startLoop(); emit();
            },
            go(delta) {
                if (!seq.length) return;
                // 手動換步：直接顯示刷完的樣子並停住——按「下一步」是想看，不是想等。
                pos = clamp(pos + delta, 0, seq.length - 1); finished = false;
                playing = false; stepT = applyTime(plan[seq[pos]]) + 0.2; startLoop(); render(); emit();
            },
            hide() { stopLoop(); playing = false; seq = []; note = ''; canvas.classList.remove('is-on'); ctx.clearRect(0, 0, W, H); emit(); },
            destroy() { stopLoop(); if (ro) ro.disconnect(); canvas.remove(); },
            snapshot() {
                const st = seq.length ? plan[seq[pos]] : null;
                return { state, error, note, mode, playing, finished, index: pos, total: seq.length, step: st };
            },
        };
        return api;
    }

    window.MakeupTutorial = { create, PLANS, SKIPPED_PARTS };
})(window, document);
