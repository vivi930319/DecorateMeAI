// 五官圖鑑：分析結果的每一格點開來，看那個分類長什麼樣、依據什麼判斷。
//
// 為什麼需要它：結果頁只給一個詞（「落尾眉」），使用者無從判斷準不準，
// 也不知道那個詞是什麼意思。回饋面板雖然可以改，但那是一排下拉選單——
// 要先知道「彎月眉」跟「落尾眉」差在哪，才有辦法選。
//
// 三個設計決定
// ------------
// 1. 分類清單**不在這裡定義**，一律讀 AnalysisFeedback.OPTIONS。
//    2026-08-24 才踩過：那份清單多一個「細長眼」，而模型早就把它併進鳳眼，
//    使用者選到就整包被後端退回。同一份清單抄兩份，遲早會分岔。
//    這裡只補「說明文字」與「示意圖」，缺哪一類就不顯示那一類，不自己補。
//
// 2. 改答案**不自己送出**，而是去操作回饋面板既有的那個 <select>。
//    送出的路徑只能有一條：allowTrainingUse 的同意、影像上傳的說明、
//    _modelRaw 的比對全都長在那裡，另外寫一套等於把那些保護繞過去。
//
// 3. 小圖優先用 assets/feature-atlas/{部位}-{分類}.webp，載不到才用內建的 SVG。
//    這樣美術資源可以之後再補，補上去不用改任何程式碼。

const FeatureAtlas = (() => {
    const IMG_BASE = 'assets/feature-atlas/';
    const IMG_EXT = '.webp';

    // 中文欄位名 ←→ 部位代號。欄位名是回饋面板與後端在用的，代號用於圖檔命名。
    const FIELD_TO_PART = { '臉型': 'face', '眉型': 'brow', '眼型': 'eye', '鼻型': 'nose', '嘴型': 'lip' };

    // 每一類的說明。key 必須是 AnalysisFeedback.OPTIONS 裡的字串。
    //
    // `how` 是**正式的分類定義**（2026-08-26 由專案定稿），描述的是形狀本身，
    // 不含任何美容宣稱。措辭刻意用「較」「通常」這種比較級而不是絕對值——
    // 分類是相對的，寫成「臉長大於臉寬」會讓使用者拿尺去量，然後發現量不出來。
    //
    // `look` 是妝容參考，跟定義分開放：使用者困惑的時候要看的是「這個詞是什麼意思」，
    // 把化妝建議混進定義裡，會讓他讀完還是不知道自己是不是這一類。
    const DEF = {
        '圓形臉': { how: '臉長與臉寬較接近，臉頰較圓潤，下顎與下巴線條柔和，整體輪廓的角度感較少。',
                    look: '修容放在兩側可以拉長比例。' },
        '心形臉': { how: '上半臉相對較寬，從額頭、顴骨往下巴逐漸收窄，下巴較小或較尖，形成上寬下窄的輪廓。',
                    look: '重心放在中段可以平衡上寬下窄。' },
        '方形臉': { how: '臉部上下寬度較接近，下顎線條較明顯，下巴偏寬，整體輪廓帶有較清楚的角度感。',
                    look: '下顎角是特徵，修飾時避免整條抹平。' },
        '長形臉': { how: '臉部縱向比例較長，臉長明顯大於臉寬，額頭、顴骨到下顎的寬度變化通常較小。',
                    look: '橫向的腮紅位置可以縮短視覺長度。' },
        '鵝蛋臉': { how: '臉長略大於臉寬，臉部比例較均衡，下半臉自然收窄，下巴圓潤中帶有些微尖度。',
                    look: '比例本身平衡，修容以維持為主。' },

        '一字眉': { how: '眉如其名，如同一字般，眉頭、眉峰、眉尾水平高度幾乎一致。',
                    look: '線條乾淨，適合維持平直的填色方式。' },
        '彎月眉': { how: '如一道月亮在眉毛上，眉頭、眉峰、眉尾三者連線成弧形，眉峰的高度介於落尾眉和挑眉之間。',
                    look: '弧線本身柔和，重點是不要把弧度畫斷。' },
        '落尾眉': { how: '眉峰前眉毛弧度平直，眉峰後眉毛走向下斜。',
                    look: '眉尾往上延伸可以改變視覺重心。' },
        '挑眉':   { how: '眉峰高於其他的眉型，不像彎月眉那樣需要都是圓弧狀，眉尾沒有要求。',
                    look: '眉形本身帶起精神，眉尾不必再刻意上揚。' },

        '圓眼':   { how: '眼睛上下開口較大，眼長與眼高的比例較接近，整體輪廓較圓潤，視覺上有較明顯的張開感。',
                    look: '眼線貼睫毛根部即可，加粗會讓圓感消失。' },
        '桃杏眼': { how: '結合桃花眼與杏仁眼的柔和特徵，眼型呈自然的橢圓或杏仁狀，眼頭與眼尾逐漸收窄，'
                         + '眼尾可帶有些微上揚，但不像鳳眼那麼明顯。',
                    look: '眼尾順著原本的角度延伸最自然。' },
        '鳳眼':   { how: '眼型偏細長，外眼角通常高於內眼角，眼尾向外延伸並帶有上揚感，整體線條較俐落。',
                    look: '眼尾拉長會強化原本的走向。' },
        '下垂眼': { how: '外眼角的位置較內眼角低，眼睛由內向外呈現微微向下的走向，因此眼尾帶有自然的下垂感。',
                    look: '眼尾往上提可以改變視覺角度。' },

        '標準鼻': { how: '從正面看，鼻翼寬度與雙眼之間的比例較接近，鼻部在臉部中央的橫向比例較為適中。',
                    look: '鼻影沿著鼻樑兩側即可。' },
        '寬鼻':   { how: '從正面看，鼻翼向左右延伸的寬度較明顯，相較雙眼之間的距離，鼻部具有較寬的橫向比例。',
                    look: '鼻影收在鼻翼外緣可以修飾寬度。' },

        '薄唇':   { how: '上下唇的唇部高度較小，唇線較纖細，整體嘴唇看起來較薄、較平。',
                    look: '唇線稍微外擴可以增加厚度感。' },
        '微笑唇': { how: '在自然閉嘴的狀態下，左右嘴角仍微微向上，唇線呈現自然上揚的感覺，看起來像帶有淡淡的微笑。',
                    look: '順著嘴角原本的角度收尾即可。' },
        '花瓣唇': { how: '上唇中央的唇峰與唇谷較明顯，中央輪廓具有自然起伏，搭配較圓潤的下唇，整體像花瓣般具有曲線感。',
                    look: '唇峰是特徵，描邊時保留形狀。' },
        '厚唇':   { how: '上下唇的唇部高度較明顯，整體唇形較飽滿，嘴唇在臉部中的立體感與存在感較高。',
                    look: '霧面質地會讓厚度感降低。' },

        // 側面鼻型（PRO 流程才有）。模型輸出五類。
        //
        // 前四類是 2026-08-26 的定稿，蒜頭鼻是後補的：定稿漏了它，但模型會輸出，
        // 而一個會出現在畫面上卻沒有說明的分類，正好是這個功能要解決的問題。
        // 補寫時照其他幾類的規則走——只描述形狀，用比較級不用絕對值，
        // 不寫「大」「不好看」這類帶評價的字：使用者是在看自己的臉。
        '塌鼻':   { how: '從側面看，鼻樑的前突程度較低，鼻根至鼻尖的立體起伏較小，整體鼻部輪廓較平緩。' },
        '翹鼻':   { how: '從側面看，鼻尖具有較明顯的向上走向，鼻尖位置上翹，使鼻部末端形成較明顯的上揚輪廓。' },
        '直挺鼻': { how: '從側面看，鼻根到鼻尖的鼻樑線條較直且連續，鼻部具有明顯的前突感，沒有明顯隆起或凹折。' },
        '駝峰鼻': { how: '從側面看，鼻樑中段具有較明顯的隆起或凸點，使鼻根到鼻尖之間的線條呈現向外凸出的輪廓。' },
        '蒜頭鼻': { how: '鼻尖較圓潤飽滿，鼻頭的體積感較明顯，鼻尖與鼻翼之間的界線較不分明，'
                         + '使鼻部末端的輪廓看起來較圓、較有厚度。' },
    };

    // 畫小圖用的參數。缺的類別會自動退回「沒有示意圖」，不會壞掉。
    const SHAPE = {
        '圓形臉': [34, 40, 33, 52, .16], '方形臉': [38, 40, 37, 55, .06], '心形臉': [39, 38, 28, 58, .60],
        '鵝蛋臉': [35, 38, 30, 60, .40], '長形臉': [34, 36, 30, 68, .34],
        '挑眉': [4, -7, .62, -3, 5.5], '一字眉': [0, -2, .50, 0, 6.5],
        '彎月眉': [2, -9, .44, 1, 5.5], '落尾眉': [-2, -4, .40, 7, 5.5],
        '圓眼': [30, 11, 0, 1], '桃杏眼': [34, 9, 3, 2], '鳳眼': [38, 6.5, 7, 3], '下垂眼': [34, 8.5, -5, 0],
        '標準鼻': [17], '寬鼻': [25],
        '薄唇': [4, 5, 1.5, 0, 30], '微笑唇': [5, 7, 3, 3.5, 31],
        '花瓣唇': [7, 9, 5.5, 1, 29], '厚唇': [10, 12, 4, 1, 31],
    };

    // 眉尾高度的實測分布（422 張，以眼距正規化）。只有眉型量過，其他部位沒有就不顯示。
    // 來源：tools/brow_geometry_probe.py，2026-08-24。
    const DIST = {
        '眉型': {
            unit: '眉尾相對眉頭的高度',
            min: -.085, max: -.015,
            rows: [
                { name: '一字眉', med: -.042, q1: -.054, q3: -.022 },
                { name: '落尾眉', med: -.056, q1: -.075, q3: -.043 },
                { name: '彎月眉', med: -.058, q1: -.073, q3: -.047 },
            ],
            note: '三類的中間 50% 幾乎完全疊在一起，而且彎月眉的中位數比落尾眉更低。'
                + '「眉尾低於眉頭」在這批資料上分不出類別，因為九成以上的人都是這樣。',
        },
    };

    /* ── 小圖：同一組畫法吃不同參數，四張並排才會有一致的筆觸 ────────── */
    const ART = {
        brow([head, peak, pos, tail, th]) {
            const x0 = 12, x1 = 68, w = x1 - x0, pk = x0 + w * pos, Y = v => 26 + v;
            const up = `M${x0},${Y(head)} C${x0 + w * .24},${Y(peak + (head - peak) * .25)} ${pk - w * .16},${Y(peak)} ${pk},${Y(peak)}`
                + ` C${pk + w * .22},${Y(peak)} ${x1 - w * .16},${Y(tail - (tail - peak) * .3)} ${x1},${Y(tail)}`;
            const dn = `C${x1 - w * .2},${Y(tail - (tail - peak) * .3 + th * .55)} ${pk + w * .22},${Y(peak + th)} ${pk},${Y(peak + th)}`
                + ` C${pk - w * .18},${Y(peak + th)} ${x0 + w * .24},${Y(peak + (head - peak) * .25 + th * 1.15)} ${x0},${Y(head + th * 1.1)} Z`;
            const hairs = [.2, .38, .56, .74].map(t => {
                const hx = x0 + w * t, hy = Y(peak + (head - peak) * (1 - t) * .6) + 1.5;
                return `<path d="M${hx},${hy + th * .8} l${3 - t * 4},${-th * 1.5}" stroke="#8B6553" stroke-width="1" stroke-linecap="round" fill="none" opacity=".55"/>`;
            }).join('');
            return `<path d="${up} ${dn}" fill="#6B4A3C"/>${hairs}`;
        },
        // 動漫感靠三件事：粗上眼線、大虹膜加兩個高光、外眼角翹起來的睫毛
        eye([w, h, up, dn]) {
            const cx = 40, cy = 30, L = cx - w / 2, R = cx + w / 2, ly = cy + dn, ry = cy - up;
            const uid = 'fa' + Math.random().toString(36).slice(2, 8);
            const lid = `M${L},${ly} C${L + w * .26},${cy - h} ${R - w * .26},${cy - h - up * .5} ${R},${ry}`;
            const low = `M${L},${ly} C${L + w * .28},${cy + h * .78} ${R - w * .24},${cy + h * .62 - up * .5} ${R},${ry}`;
            const ir = Math.min(w * .24, h * .95), icx = cx + up * .25, icy = cy - h * .06 + dn * .3;
            const lash = [0, 1, 2].map(i => {
                const t = .80 + i * .075, x = L + w * t, y = cy - h * (1 - Math.abs(t - .5) * 1.1) - up * (t - .3);
                return `<path d="M${x},${y} l${3 + i},${-4 - i}" stroke="#2C2024" stroke-width="1.7" stroke-linecap="round" fill="none"/>`;
            }).join('');
            return `<path d="${lid} ${low.replace('M', 'L').slice(1)} Z" fill="#FFF9F7"/>
      <clipPath id="${uid}"><path d="${lid} ${low.replace('M', 'L').slice(1)} Z"/></clipPath>
      <g clip-path="url(#${uid})">
        <circle cx="${icx}" cy="${icy}" r="${ir}" fill="#5C3A2E"/>
        <circle cx="${icx}" cy="${icy + ir * .18}" r="${ir * .55}" fill="#2C2024"/>
        <circle cx="${icx + ir * .34}" cy="${icy - ir * .36}" r="${ir * .28}" fill="#FFF" opacity=".92"/>
        <circle cx="${icx - ir * .30}" cy="${icy + ir * .34}" r="${ir * .15}" fill="#FFF" opacity=".6"/>
      </g>
      <path d="${lid}" stroke="#2C2024" stroke-width="3" fill="none" stroke-linecap="round"/>
      <path d="${low}" stroke="#7A5A4E" stroke-width="1.3" fill="none" stroke-linecap="round" opacity=".75"/>${lash}`;
        },
        lip([ut, lt, pk, sm, w]) {
            const cx = 40, cy = 30, L = cx - w / 2, R = cx + w / 2, cl = cy - sm;
            const uid = 'fa' + Math.random().toString(36).slice(2, 8);
            const top = `M${L},${cl} C${cx - w * .30},${cy - ut - pk * .55} ${cx - w * .13},${cy - ut - pk} ${cx},${cy - ut + pk * .42}`
                + ` C${cx + w * .13},${cy - ut - pk} ${cx + w * .30},${cy - ut - pk * .55} ${R},${cl}`;
            const bot = `C${cx + w * .30},${cy + lt * 1.08} ${cx - w * .30},${cy + lt * 1.08} ${L},${cl} Z`;
            return `<defs><linearGradient id="${uid}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#BC7068"/><stop offset="1" stop-color="#F1CFC8"/></linearGradient></defs>
      <path d="${top} ${bot}" fill="#D98C82"/><path d="${top} ${bot}" fill="url(#${uid})" opacity=".55"/>
      <path d="M${L},${cl} C${cx - w * .2},${cy + 1.6} ${cx + w * .2},${cy + 1.6} ${R},${cl}" stroke="#BC7068" stroke-width="1.4" fill="none" stroke-linecap="round"/>
      <ellipse cx="${cx}" cy="${cy + lt * .52}" rx="${w * .15}" ry="${lt * .26}" fill="#FFF" opacity=".55"/>`;
        },
        // 動漫的鼻子本來就只留最少的資訊，畫滿反而怪
        nose([aw]) {
            const cx = 40, t = 14, b = 40;
            return `<path d="M${cx - 2.5},${t} C${cx - 4},${t + 13} ${cx - aw / 2},${b - 7} ${cx - aw / 2},${b - 2.5}" stroke="#8B6553" stroke-width="1.8" fill="none" stroke-linecap="round" opacity=".6"/>
      <path d="M${cx - aw / 2},${b - 2.5} C${cx - aw / 2},${b + 2} ${cx - aw * .2},${b + 3} ${cx},${b + 1.5} C${cx + aw * .2},${b + 3} ${cx + aw / 2},${b + 2} ${cx + aw / 2},${b - 2.5}" stroke="#2C2024" stroke-width="2" fill="none" stroke-linecap="round"/>
      <ellipse cx="${cx - aw * .26}" cy="${b - .5}" rx="1.6" ry="1.1" fill="#2C2024" opacity=".55"/>
      <ellipse cx="${cx + aw * .26}" cy="${b - .5}" rx="1.6" ry="1.1" fill="#2C2024" opacity=".55"/>`;
        },
        face([fw, cw, jw, fl, ch]) {
            const cx = 40, top = 8, bot = top + fl, jy = top + fl * .64, chin = jw / 2 * (1 - ch * .55);
            const out = `M${cx - fw / 2},${top + fl * .16} C${cx - fw / 2 - 3},${top - fl * .10} ${cx + fw / 2 + 3},${top - fl * .10} ${cx + fw / 2},${top + fl * .16}`
                + ` C${cx + cw / 2 + 2},${top + fl * .34} ${cx + jw / 2 + 2},${jy} ${cx + chin},${bot - fl * .12}`
                + ` C${cx + chin * .5},${bot} ${cx - chin * .5},${bot} ${cx - chin},${bot - fl * .12}`
                + ` C${cx - jw / 2 - 2},${jy} ${cx - cw / 2 - 2},${top + fl * .34} ${cx - fw / 2},${top + fl * .16} Z`;
            const hair = `M${cx - fw / 2 - 2},${top + fl * .20} C${cx - fw / 2 - 5},${top - fl * .26} ${cx + fw / 2 + 5},${top - fl * .26} ${cx + fw / 2 + 2},${top + fl * .20}`
                + ` C${cx + fw / 2 - 3},${top + fl * .02} ${cx - fw / 2 + 3},${top + fl * .02} ${cx - fw / 2 - 2},${top + fl * .20} Z`;
            return `<path d="${out}" fill="#FBE8DE"/><path d="${out}" stroke="#2C2024" stroke-width="2" fill="none"/><path d="${hair}" fill="#4A3229"/>`;
        },
    };


    // 最常被判斷分歧的配對。
    //
    // 不是憑印象挑的，是從 146 次真實回饋裡算出來的：使用者把 A 改成 B 的次數。
    // 資料在 tools/export_feedback_aggregate.py 的輸出裡，重算方式見
    // docs/模型與訓練/系統統計數字總覽_公式與依據。
    //
    // 為什麼要放這個：使用者困惑時真正面對的問題不是「什麼是彎月眉」，
    // 而是「我到底是彎月眉還是落尾眉」。單獨看一個定義答不出這件事，
    // 要兩個定義擺在一起才分得出來。
    //
    // 三個從資料看到的傾向，也順便說明為什麼是這幾組：
    //   眼型  什麼都被改成桃杏眼（鳳眼 18、圓眼 15、下垂眼 10）——名字最「安全」
    //   嘴型  薄唇被改成什麼都有（微笑唇 18、厚唇 14、花瓣唇 13）——模型過度預測薄唇
    //   鼻型  寬鼻→標準鼻 17 次，反向只有 4 次——模型偏向寬鼻
    const CONFUSED = {
        '圓形臉': ['方形臉', '鵝蛋臉'],
        '鵝蛋臉': ['方形臉', '心形臉'],
        '長形臉': ['鵝蛋臉', '方形臉'],
        '方形臉': ['圓形臉', '鵝蛋臉'],
        '心形臉': ['鵝蛋臉'],

        '落尾眉': ['一字眉', '彎月眉'],
        '一字眉': ['彎月眉', '落尾眉'],
        '彎月眉': ['一字眉', '落尾眉'],
        '挑眉':   ['彎月眉'],

        '鳳眼':   ['桃杏眼', '下垂眼'],
        '圓眼':   ['桃杏眼'],
        '下垂眼': ['桃杏眼', '鳳眼'],
        '桃杏眼': ['鳳眼', '圓眼'],

        '寬鼻':   ['標準鼻'],
        '標準鼻': ['寬鼻'],

        '薄唇':   ['微笑唇', '厚唇', '花瓣唇'],
        '厚唇':   ['薄唇', '花瓣唇'],
        '花瓣唇': ['薄唇', '厚唇'],
        '微笑唇': ['薄唇'],
    };


    // 各部位「按人切分」的 macro accuracy（TR-b673609456f9cb05，2026-08-28）。
    //
    // 為什麼用按人切分而不是隨機切分：同一個人的多張照片如果被拆到訓練與驗證兩邊，
    // 模型只要認出「這是同一個人」就會答對，分數會虛高。按人切分才是它面對
    // 沒看過的臉時的表現。
    //
    // 這些數字會直接顯示給使用者，包含**難看的那幾個**。
    // 臉型 0.454 就是 0.454——蓋掉它不會讓模型變好，只會讓使用者以為
    // 系統比實際上更有把握，然後照著一個不可靠的結論去買東西。
    const ACC = {
        '鼻型': 0.822, '眼型': 0.679, '眉型': 0.592, '嘴型': 0.579, '臉型': 0.454,
    };
    const CLASS_COUNT = { '臉型': 5, '眉型': 4, '眼型': 4, '嘴型': 4, '鼻型': 2 };

    // 一問一答，格式跟商品推薦那邊的色差說明一致。
    //
    // 為什麼要 QA 而不是只有定義：定義回答「這個詞是什麼意思」，
    // 但使用者心裡真正的問題是「這準嗎」「我覺得不對怎麼辦」「改了會怎樣」。
    // 那三個問題沒被回答的話，他要嘛盲目相信，要嘛整個不信——兩種都不好。
    function qaHtml(field) {
        const acc = ACC[field];
        const n = CLASS_COUNT[field] || 0;
        const pct = acc != null ? Math.round(acc * 100) : null;
        const chance = n ? Math.round(100 / n) : null;
        const items = [
            {
                q: '系統怎麼判斷的？',
                a: '先用 MediaPipe 在照片上標出 468 個臉部特徵點，依那些點裁出' + esc(field) +
                   '那一小塊，再交給一個叫 ConvNeXt 的影像分類模型判斷屬於哪一類。'
                   + '判斷只看形狀，不看膚色、年齡或性別。',
            },
            pct != null ? {
                q: '這個部位判得準嗎？',
                a: '在沒看過的臉上，' + esc(field) + '的平均正確率大約 ' + pct + '%'
                   + (chance != null ? ('（' + n + '類隨機猜是 ' + chance + '%）') : '') + '。'
                   + (acc < 0.6
                      ? '這個數字不高，代表這個部位的判斷只能當參考——覺得不對請直接改。'
                      : '這是「按人切分」算出來的：同一個人的照片不會同時出現在訓練與驗證，'
                        + '所以它反映的是面對陌生臉孔的表現，不是背answers的成績。'),
            } : null,
            {
                q: '為什麼我覺得判錯了？',
                a: '這些分類是**相對的**，不是量出來就有標準答案。相鄰兩類的實際數值範圍會重疊，'
                   + '落在重疊區的臉，判成哪一邊都說得通。上面的定義就是用來自己比對的——'
                   + '照定義看比較準，照印象看容易受「我希望自己是哪一類」影響。',
            },
            {
                q: '我改掉之後會發生什麼事？',
                a: '你的答案會先存起來，經過人工覆核確認合理之後，才會成為重新訓練模型的標籤。'
                   + '所以改一次不會立刻改變系統，但會讓下一版更接近真實的臉。'
                   + '沒有勾選保存影像的話，只有你的判斷會被留下，照片不會。',
            },
            {
                q: '一定要改嗎？',
                a: '不用。這個分類只影響妝容建議與商品推薦的排序，不影響你能用哪些功能。'
                   + '覺得判得對就不用動它。',
            },
        ].filter(Boolean);
        return '<div class="fa-qa">' + items.map(function (x, i) {
            return '<details' + (i === 0 ? ' open' : '') + '>'
                + '<summary>' + esc(x.q) + '</summary><p>' + esc(x.a) + '</p></details>';
        }).join('') + '</div>';
    }

    // 「我到底是哪一個」——把當前分類與最常混淆的那幾類，定義並排。
    //
    // 只在看的是**模型給的那一類**時出現。使用者已經自己點去看別類時，
    // 他就是在比較了，再塞一塊比較只是重複。
    function confusedHtml(field, current, options) {
        const others = (CONFUSED[current] || []).filter(n => options.includes(n) && DEF[n]);
        if (!others.length || !DEF[current]) return '';
        const row = (name, isMine) => `
          <div class="fa-cmp-row${isMine ? ' fa-cmp-mine' : ''}">
            <div class="fa-cmp-name">${esc(name)}${isMine ? '<em>目前的判斷</em>' : ''}</div>
            <p class="fa-cmp-def">${esc(DEF[name].how)}</p>
            ${isMine ? '' : `<button type="button" class="fa-cmp-pick" data-fa-pick="${esc(name)}">改成${esc(name)}</button>`}
          </div>`;
        return `<details class="fa-cmp" open>
          <summary>不確定是不是這一類？</summary>
          <div class="fa-cmp-body">
            <p class="fa-cmp-lead">這幾類最常被判斷分歧。定義擺在一起比較，會比單看一個清楚：</p>
            ${row(current, true)}
            ${others.map(n => row(n, false)).join('')}
            <p class="fa-note">照定義比對之後，如果你的答案跟系統不同，直接改——
               我們要的是符合定義的答案，不是跟系統一致的答案。</p>
          </div></details>`;
    }

    const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    // 圖檔在就用圖檔，不在才畫 SVG。onerror 只會觸發一次，不會無限重試。
    function thumb(part, name) {
        const shape = SHAPE[name];
        const fb = shape && ART[part]
            ? `<svg class="fa-thumb" viewBox="0 0 80 60" aria-hidden="true">${ART[part](shape)}</svg>`
            : '<span class="fa-thumb fa-nothumb" aria-hidden="true"></span>';
        return `<img class="fa-thumb" src="${IMG_BASE}${part}-${encodeURIComponent(name)}${IMG_EXT}"
            alt="" loading="lazy" onerror="this.outerHTML=this.dataset.fb" data-fb="${esc(fb)}">`;
    }

    function distHtml(field) {
        const d = DIST[field];
        if (!d) return '';
        const span = d.max - d.min, pct = v => (v - d.min) / span * 100;
        return `<details class="fa-why"><summary>為什麼有時候會判不準</summary>
      <div class="fa-why-body">
        <p>把 422 張照片的${esc(d.unit)}量出來，分布是這樣 —— 色塊是中間 50% 的落點，直線是中位數：</p>
        ${d.rows.map(r => `<div class="fa-dist-row"><span class="fa-dl">${esc(r.name)}</span>
          <div class="fa-dist-bar">
            <span class="fa-dist-span" style="left:${pct(r.q1)}%;width:${pct(r.q3) - pct(r.q1)}%"></span>
            <span class="fa-dist-med" style="left:${pct(r.med)}%"></span>
          </div></div>`).join('')}
        <p class="fa-note">${esc(d.note)}</p>
        <p class="fa-note">所以這裡的分類是一個參考。覺得不對就改掉，你的判斷比我們的猜測更接近答案。</p>
      </div></details>`;
    }

    // 改答案：去操作回饋面板既有的 select，不自己送出。
    // 找不到就只提示，不靜默失敗——靜默失敗會讓使用者以為改好了。
    function applyChange(field, name) {
        const sel = document.querySelector(`[data-af-field="${CSS.escape(field)}"]`);
        if (!sel) return { ok: false, msg: '回饋面板還沒載入，請捲到下方的「這些判斷準嗎？」直接修改。' };
        if (![...sel.options].some(o => o.value === name)) {
            return { ok: false, msg: `「${name}」不在目前的可選清單裡，請用下方的回饋面板確認。` };
        }
        sel.value = name;
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        const panel = sel.closest('.analysis-feedback');
        if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return { ok: true, msg: `已改成「${name}」，請到下方的回饋面板按「送出回饋」。` };
    }

    /* ── 浮層 ────────────────────────────────────────────────────
       不在頁面裡展開，理由是這頁最後要裝進手機：inline 展開會把結果區推長一大截，
       使用者得捲很久才回得到原本的位置，而且分析結果本身就在頁面中段。
       手機用從底部滑上來的 sheet，桌機用置中的視窗——同一份 DOM，靠 CSS 切。 */
    let openField = null, selected = null, lastFocus = null, getCurrentRef = null;

    function ensureLayer() {
        let layer = document.getElementById('featureAtlasLayer');
        if (layer) return layer;
        layer = document.createElement('div');
        layer.id = 'featureAtlasLayer';
        layer.className = 'fa-layer';
        layer.hidden = true;
        layer.innerHTML = `
      <div class="fa-scrim" data-fa-close></div>
      <div class="fa-sheet" role="dialog" aria-modal="true" aria-labelledby="faTitle">
        <button type="button" class="fa-x" data-fa-close aria-label="關閉">×</button>
        <div class="fa-grip" aria-hidden="true"></div>
        <div class="fa-body" id="faBody"></div>
      </div>`;
        document.body.appendChild(layer);
        layer.addEventListener('click', e => { if (e.target.closest('[data-fa-close]')) close(); });
        return layer;
    }

    function onKey(e) {
        if (e.key === 'Escape') { close(); return; }
        if (e.key !== 'Tab') return;
        // 焦點困在浮層裡，否則 Tab 會跑到底下那頁去，讀螢幕的人會不知道自己在哪
        const sheet = document.querySelector('#featureAtlasLayer .fa-sheet');
        const items = sheet && sheet.querySelectorAll('button, [href], select, summary, [tabindex]:not([tabindex="-1"])');
        if (!items || !items.length) return;
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }

    function open(field, current) {
        const layer = ensureLayer();
        openField = field; selected = current;
        lastFocus = document.activeElement;
        layer.hidden = false;
        // 背景不跟著捲：手機上浮層裡捲到底會帶動整頁，看起來像畫面壞掉
        document.body.style.overflow = 'hidden';
        render();
        document.addEventListener('keydown', onKey);
        requestAnimationFrame(() => {
            layer.classList.add('fa-on');
            const x = layer.querySelector('.fa-x');
            if (x) x.focus();
        });
    }

    function close() {
        const layer = document.getElementById('featureAtlasLayer');
        openField = null; selected = null;
        document.removeEventListener('keydown', onKey);
        document.body.style.overflow = '';
        document.querySelectorAll('[data-fa-field]').forEach(c => c.setAttribute('aria-expanded', 'false'));
        if (!layer) return;
        layer.classList.remove('fa-on');
        // 等收合動畫跑完再藏起來，直接 hidden 會讓它瞬間消失
        setTimeout(() => { if (!openField) layer.hidden = true; }, 260);
        if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    function render() {
        const field = openField;
        if (!field) return;
        const body = document.getElementById('faBody');
        if (!body) return;
        const part = FIELD_TO_PART[field];
        const options = (typeof AnalysisFeedback !== 'undefined' && AnalysisFeedback.OPTIONS[field]) || [];
        const current = getCurrentRef ? getCurrentRef(field) : '';
        if (!part || !options.length) { close(); return; }
        const sel = options.includes(selected) ? selected : current;
        const def = DEF[sel] || {};
        const isCurrent = sel === current;

        body.innerHTML = `
      <div class="fa-head" id="faTitle">${esc(field)} · ${options.length} 種分類</div>
      <div class="fa-kinds">${options.map(name => `
        <button type="button" class="fa-kind" data-fa-kind="${esc(name)}" data-cur="${name === sel ? 1 : 0}">
          ${thumb(part, name)}
          <span class="fa-kn">${esc(name)}</span>
          <span class="fa-ktag">${name === current ? '你的判斷' : ''}</span>
        </button>`).join('')}</div>
      <div class="fa-detail">
        <h3>${esc(sel)}</h3>
        ${def.how ? `<p class="fa-how">${esc(def.how)}</p>` : ''}
        ${def.look ? `<p class="fa-look"><b>對妝容的意義</b>${esc(def.look)}</p>` : ''}
        <div class="fa-acts">
          <button type="button" class="fa-act" id="faAdopt" ${isCurrent ? 'disabled' : ''}>
            ${isCurrent ? '這就是目前的判斷' : `改成「${esc(sel)}」`}</button>
        </div>
        <div class="fa-toast" id="faToast"></div>
        ${isCurrent ? confusedHtml(field, current, options) : ''}
        ${qaHtml(field)}
        ${distHtml(field)}
      </div>`;

        body.querySelectorAll('[data-fa-kind]').forEach(b => {
            b.onclick = () => { selected = b.dataset.faKind; render(); };
        });
        const adopt = body.querySelector('#faAdopt');
        if (adopt) adopt.onclick = () => {
            const r = applyChange(field, sel);
            body.querySelector('#faToast').textContent = r.msg;
            // 改成功就關掉：目的地是下面的回饋面板，浮層留著會擋住它
            if (r.ok) setTimeout(close, 900);
        };
    }

    return {
        FIELD_TO_PART,
        // 把圖鑑接到分析結果那六格上。可以重複呼叫，不會累積事件（用 onclick 而非 addEventListener）。
        attach(getCurrent) {
            getCurrentRef = getCurrent;
            const grid = document.querySelector('.result-grid');
            if (!grid) return;
            grid.querySelectorAll('[data-fa-field]').forEach(cell => {
                const field = cell.dataset.faField;
                if (!FIELD_TO_PART[field]) return;
                cell.setAttribute('role', 'button');
                cell.setAttribute('tabindex', '0');
                cell.setAttribute('aria-haspopup', 'dialog');
                cell.setAttribute('aria-expanded', 'false');
                const go = () => {
                    // 還沒有結果就不要開：使用者會看到一堆「—」對應不到任何東西
                    const current = getCurrent(field);
                    if (!current || current === '—') return;
                    cell.setAttribute('aria-expanded', 'true');
                    open(field, current);
                };
                cell.onclick = go;
                cell.onkeydown = e => {
                    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
                };
            });
        },
        // 五官被改過之後重畫，否則「你的判斷」還標在舊答案上
        refresh() { if (openField) render(); },
        close,
    };
})();
