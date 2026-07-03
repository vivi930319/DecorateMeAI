// ═══ 風格資料 ═══
const STYLES = [
    {
        id:'softBaddie', name:'Soft Baddie', img:'softbaddie.jpg', tags:['柔霧底妝','甜酷氛圍','自然修容','微性感'],
        intro:'柔霧底妝搭配甜酷眼唇重點，適合想保留精緻感又帶一點攻擊性的妝容。',
        palette:['#D8B69E','#B97970','#7C544A'],
        advice:{ base:'清透柔霧底妝，局部遮瑕保留自然膚質。', brow:'眉峰略拉高，保留俐落毛流。', eye:'柔霧大地色加深眼尾，眼線略拉長。', blush:'腮紅位置偏高，搭配輕微修容。', lip:'低飽和玫瑰或肉桂色，邊界可微霧化。' }
    },
    {
        id:'richGirl', name:'千金', img:'千金.png', tags:['高級感','精緻底妝','低調奢華','氣質妝容'],
        intro:'強調乾淨底妝、低飽和色彩與細節光澤，整體看起來精緻但不厚重。',
        palette:['#E8CDBB','#CBA384','#A77E68'],
        advice:{ base:'薄透光澤底妝，重點放在膚色均勻。', brow:'順著原生眉型補空隙，避免過重。', eye:'燕麥、奶茶色眼影，眼頭少量提亮。', blush:'低飽和裸粉或杏色，淡淡掃在蘋果肌。', lip:'奶茶玫瑰、裸豆沙色最穩。' }
    },
    {
        id:'hongKong', name:'港風', img:'港風.png', tags:['復古感','濃郁五官','氛圍唇色','立體眉眼'],
        intro:'復古港風重點是濃郁眉眼與飽和唇色，適合五官需要被強化的妝容。',
        palette:['#B85B4D','#7E2F2A','#C79C6E'],
        advice:{ base:'霧面底妝搭配明確輪廓。', brow:'眉型可稍粗，保留自然眉峰。', eye:'暖棕大面積暈染，內眼線強化眼神。', blush:'偏暖磚紅或杏棕，連接修容。', lip:'復古紅、磚紅、濃郁玫瑰色。' }
    },
    {
        id:'koreanClean', name:'韓系亞裔', img:'韓系亞裔.jpg', tags:['清透感','偽素顏','低飽和','日常自然'],
        intro:'乾淨、透明、低負擔的日常妝感，重點在於膚質和淡色系層次。',
        palette:['#F1C9C5','#E6AFA8','#D9BFA9'],
        advice:{ base:'保濕氣墊或輕薄粉底，保留自然光澤。', brow:'平柔眉或自然野生眉，顏色比髮色淺一點。', eye:'粉裸、米棕消腫，臥蠶自然提亮。', blush:'蜜桃粉或淡杏色，範圍小而柔。', lip:'水光唇釉、粉裸色或MLBB。' }
    },
    {
        id:'yandere', name:'病嬌', img:'病嬌.png', tags:['白皙氛圍','眼下腮紅','微病感','角色感'],
        intro:'偏角色感的妝容，透過白皙底妝、眼下腮紅與血色唇營造脆弱氛圍。',
        palette:['#E7A0A6','#B84B5C','#F3D8D9'],
        advice:{ base:'底妝可比平常略亮，但避免灰白。', brow:'眉色淡化，降低攻擊感。', eye:'眼下粉紅暈染，眼線微下垂。', blush:'腮紅集中眼下到顴骨上方。', lip:'咬唇、血色紅或莓果色。' }
    },
    {
        id:'japaneseClear', name:'日雜清透', img:'日雜.png', tags:['透明感','柔和自然','淡色系','溫柔日常'],
        intro:'空氣感、柔霧與淡色層次，適合想要自然但有細節的日系妝容。',
        palette:['#F0B7A8','#E2A78D','#D6B6A4'],
        advice:{ base:'輕薄霧光底妝，局部定妝。', brow:'淡眉色與柔和眉尾。', eye:'單色蜜桃或淡棕眼影，少量珠光。', blush:'淡粉橘橫向暈染，營造親和感。', lip:'潤澤珊瑚、透明紅或蜜桃色。' }
    },
    {
        id:'mensPlain', name:'男士白開水', img:'男士白開水.png', tags:['乾淨自然','原生質感','清爽眉眼','低妝感'],
        intro:'保留男性原生輪廓與肌膚質感，以輕薄修飾、整潔眉型和低彩度唇色呈現乾淨清爽的白開水妝感。',
        palette:['#E6D8CF','#BFA99A','#806F65'],
        advice:{ base:'局部遮瑕並薄透均勻膚色，保留自然肌理，T 字輕微控油。', brow:'順著原生眉流補齊空隙，眉尾保持俐落但不刻意描框。', eye:'使用霧面淺棕輕掃眼窩與下眼尾，避免明顯珠光與濃眼線。', blush:'以低飽和裸杏色少量修飾氣色，也可依膚況省略。', lip:'使用透明護唇或低彩度裸豆沙色，修飾唇色不製造明顯妝感。' }
    },
];

const MAKEUP_CATEGORIES = [
    { title:'底妝', icon:'💧' },
    { title:'眼影', icon:'🎨' },
    { title:'眼線', icon:'✒️' },
    { title:'睫毛膏', icon:'👁' },
    { title:'腮紅', icon:'🌸' },
    { title:'唇彩', icon:'💄' },
];

// ═══ 商品分類 ═══
const CATEGORIES = [
    { id:'底妝', icon:'💧' }, { id:'眼影', icon:'🎨' },
    { id:'眼線/睫毛', icon:'👁' }, { id:'唇彩', icon:'💄' },
    { id:'腮紅', icon:'🌸' }, { id:'眉毛彩妝', icon:'✏️' },
    { id:'修容', icon:'🔲' }, { id:'打亮', icon:'✨' },
];

// ═══ 全部商品 ═══
const ALL_PRODUCTS = [
    {id:1,cat:'底妝',name:'粉底液 A',price:'NT$1,000'},
    {id:2,cat:'底妝',name:'氣墊粉餅 B',price:'NT$890'},
    {id:3,cat:'底妝',name:'遮瑕膏 C',price:'NT$520'},
    {id:4,cat:'底妝',name:'妝前乳 D',price:'NT$760'},
    {id:5,cat:'底妝',name:'蜜粉 E',price:'NT$680'},
    {id:6,cat:'底妝',name:'粉餅 F',price:'NT$930'},
    {id:7,cat:'眼影',name:'眼影盤 A',price:'NT$1,000'},
    {id:8,cat:'眼影',name:'單色眼影 B',price:'NT$420'},
    {id:9,cat:'眼影',name:'大地色眼影 C',price:'NT$790'},
    {id:10,cat:'眼影',name:'珠光眼影 D',price:'NT$560'},
    {id:11,cat:'眼影',name:'霧面眼影 E',price:'NT$610'},
    {id:12,cat:'眼影',name:'九宮格眼影 F',price:'NT$1,180'},
    {id:13,cat:'眼線/睫毛',name:'眼線筆 A',price:'NT$390'},
    {id:14,cat:'眼線/睫毛',name:'睫毛膏 B',price:'NT$520'},
    {id:15,cat:'眼線/睫毛',name:'眼線液 C',price:'NT$450'},
    {id:16,cat:'眼線/睫毛',name:'睫毛底膏 D',price:'NT$480'},
    {id:17,cat:'眼線/睫毛',name:'睫毛雨衣 E',price:'NT$320'},
    {id:18,cat:'眼線/睫毛',name:'棕色眼線膠 F',price:'NT$540'},
    {id:19,cat:'唇彩',name:'口紅 A',price:'NT$1,000'},
    {id:20,cat:'唇彩',name:'唇釉 B',price:'NT$850'},
    {id:21,cat:'唇彩',name:'唇蜜 C',price:'NT$430'},
    {id:22,cat:'唇彩',name:'霧面唇膏 D',price:'NT$780'},
    {id:23,cat:'唇彩',name:'水光唇釉 E',price:'NT$920'},
    {id:24,cat:'唇彩',name:'裸色唇膏 F',price:'NT$690'},
    {id:25,cat:'腮紅',name:'粉狀腮紅 A',price:'NT$620'},
    {id:26,cat:'腮紅',name:'液態腮紅 B',price:'NT$730'},
    {id:27,cat:'腮紅',name:'膏狀腮紅 C',price:'NT$690'},
    {id:28,cat:'腮紅',name:'蜜桃色腮紅 D',price:'NT$580'},
    {id:29,cat:'腮紅',name:'珊瑚色腮紅 E',price:'NT$610'},
    {id:30,cat:'腮紅',name:'玫瑰色腮紅 F',price:'NT$640'},
    {id:31,cat:'眉毛彩妝',name:'眉筆 A',price:'NT$350'},
    {id:32,cat:'眉毛彩妝',name:'染眉膏 B',price:'NT$420'},
    {id:33,cat:'眉毛彩妝',name:'眉粉 C',price:'NT$480'},
    {id:34,cat:'眉毛彩妝',name:'眉膠 D',price:'NT$520'},
    {id:35,cat:'眉毛彩妝',name:'細芯眉筆 E',price:'NT$390'},
    {id:36,cat:'眉毛彩妝',name:'雙頭眉筆 F',price:'NT$460'},
    {id:37,cat:'修容',name:'修容盤 A',price:'NT$880'},
    {id:38,cat:'修容',name:'修容棒 B',price:'NT$760'},
    {id:39,cat:'修容',name:'陰影粉 C',price:'NT$530'},
    {id:40,cat:'修容',name:'輪廓盤 D',price:'NT$990'},
    {id:41,cat:'修容',name:'冷調修容 E',price:'NT$620'},
    {id:42,cat:'修容',name:'暖調修容 F',price:'NT$620'},
    {id:43,cat:'打亮',name:'打亮餅 A',price:'NT$790'},
    {id:44,cat:'打亮',name:'液態打亮 B',price:'NT$860'},
    {id:45,cat:'打亮',name:'香檳色打亮 C',price:'NT$650'},
    {id:46,cat:'打亮',name:'粉金打亮 D',price:'NT$690'},
    {id:47,cat:'打亮',name:'珠光打亮 E',price:'NT$570'},
    {id:48,cat:'打亮',name:'提亮棒 F',price:'NT$510'},
];

// ═══ 測試版假圖片資料：接後端後可用商品 img / imageUrl 覆蓋 ═══
function svgDataUrl(svg) {
    return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

// 純色塊 + 分類文字的中性佔位圖，不假裝畫出商品照片
function demoProductImage(product) {
    const palettes = {
        '底妝': ['#EFE4D8', '#8C5B3A'],
        '眼影': ['#F3DEDA', '#A94F4D'],
        '眼線/睫毛': ['#E7DED2', '#3A241C'],
        '唇彩': ['#F4DEDF', '#B85B4D'],
        '腮紅': ['#F5DEDC', '#A94F4D'],
        '眉毛彩妝': ['#EAE0D2', '#6B4430'],
        '修容': ['#EBDED2', '#6B4430'],
        '打亮': ['#F6EBD6', '#A78544'],
    };
    const [bg, ink] = palettes[product.cat] || ['#EFE4D8', '#8C5B3A'];
    return svgDataUrl(`
        <svg xmlns="http://www.w3.org/2000/svg" width="600" height="760" viewBox="0 0 600 760">
            <rect width="600" height="760" fill="${bg}"/>
            <text x="300" y="390" text-anchor="middle" fill="${ink}" font-size="22" letter-spacing="4" font-family="Jost, Arial" opacity=".7">${product.cat || ''}</text>
            <text x="300" y="424" text-anchor="middle" fill="${ink}" font-size="13" letter-spacing="3" font-family="Jost, Arial" opacity=".45">尚無商品圖片</text>
        </svg>
    `);
}

ALL_PRODUCTS.forEach((product, index) => {
    product.reviews = product.reviews || (420 + ((index * 37) % 360));
    product.popularity = product.popularity || (1000 - index * 9);
});

const DEMO_RENDER_IMAGES = {
    before: svgDataUrl(`
        <svg xmlns="http://www.w3.org/2000/svg" width="720" height="900" viewBox="0 0 720 900">
            <defs><linearGradient id="bg" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#F7E7DF"/><stop offset="1" stop-color="#E9D3C9"/></linearGradient></defs>
            <rect width="720" height="900" fill="url(#bg)"/>
            <circle cx="360" cy="315" r="145" fill="#E7B79E"/>
            <path d="M225 300 C270 255 450 255 495 300" stroke="#5A382B" stroke-width="14" fill="none" opacity=".35"/>
            <circle cx="305" cy="330" r="16" fill="#3A241C"/><circle cx="415" cy="330" r="16" fill="#3A241C"/>
            <path d="M326 392 C352 410 383 410 410 392" stroke="#8B442B" stroke-width="10" fill="none"/>
            <text x="360" y="705" text-anchor="middle" fill="#8B442B" font-size="38" font-family="Noto Serif TC, serif">渲染前照片 DEMO</text>
        </svg>
    `),
    after: svgDataUrl(`
        <svg xmlns="http://www.w3.org/2000/svg" width="720" height="900" viewBox="0 0 720 900">
            <defs><linearGradient id="bg" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#F8D8D9"/><stop offset="1" stop-color="#E6B7B1"/></linearGradient></defs>
            <rect width="720" height="900" fill="url(#bg)"/>
            <circle cx="360" cy="315" r="145" fill="#E7B79E"/>
            <path d="M225 300 C270 248 450 248 495 300" stroke="#5A382B" stroke-width="18" fill="none" opacity=".55"/>
            <ellipse cx="305" cy="330" rx="26" ry="18" fill="#6B4430"/><ellipse cx="415" cy="330" rx="26" ry="18" fill="#6B4430"/>
            <circle cx="278" cy="388" r="36" fill="#D97375" opacity=".38"/><circle cx="442" cy="388" r="36" fill="#D97375" opacity=".38"/>
            <path d="M322 398 C350 430 384 430 414 398" stroke="#B85B4D" stroke-width="16" fill="none"/>
            <text x="360" y="705" text-anchor="middle" fill="#8B442B" font-size="38" font-family="Noto Serif TC, serif">渲染後妝容 DEMO</text>
        </svg>
    `)
};
