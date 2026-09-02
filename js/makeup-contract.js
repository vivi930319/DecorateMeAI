(function (root) {
    'use strict';

    const EXPECTED_PART_KEYS = ['base', 'brow', 'eyes', 'contour', 'lips'];
    const PART_LABELS = {
        base: '底妝',
        brow: '眉型',
        eyes: '眼妝',
        contour: '腮紅修容',
        lips: '唇妝'
    };
    const PART_ALIASES = {
        base: ['base', 'foundation', 'skin'],
        brow: ['brow', 'brows', 'eyebrow', 'eyebrows'],
        eyes: ['eyes', 'eye', 'eyeMakeup'],
        contour: ['contour', 'cheeks', 'blush', 'blushContour'],
        lips: ['lips', 'lip', 'lipMakeup']
    };

    function isObject(value) {
        return !!value && typeof value === 'object' && !Array.isArray(value);
    }

    function text(value) {
        return typeof value === 'string' ? value.trim() : '';
    }

    function textList(value) {
        const list = Array.isArray(value) ? value : (text(value) ? [value] : []);
        return list.map(text).filter(Boolean);
    }

    function unique(list) {
        return [...new Set((list || []).map(text).filter(Boolean))];
    }

    function safePalette(value, fallback) {
        const picked = Array.isArray(value) && value.length ? value : fallback;
        return (Array.isArray(picked) ? picked : [])
            .map(text)
            .filter(color => /^#[0-9a-f]{3,8}$/i.test(color))
            .slice(0, 6);
    }

    function findPart(parts, key) {
        if (!isObject(parts)) return null;
        for (const alias of PART_ALIASES[key]) {
            if (isObject(parts[alias])) return parts[alias];
        }
        return null;
    }

    // 結構化內容可能出現在三個位置，全部都要認：
    //   1. response.structured        —— 規格書寫的位置
    //   2. response.suggestion        —— **Ollama 端實際回的位置**（2026-08-14 實測）
    //   3. response 本身              —— 直接把 overall/parts 放最外層
    //
    // 第 2 種是這支程式碼原本沒有處理的，而它正是線上壞掉的原因：
    // `suggestion` 以前是一段中文字串（走 parseLegacy），現在變成
    // `{overall:{summary}, parts:{base,eyebrow,eyes,cheeks,lips}}` 這種物件。
    // 於是 normalizeStructured 在最外層找不到 overall/parts 而回 null，
    // parseLegacy 又因為 text(物件) 得到空字串而回 null，最後拋出
    // 「Ollama 回傳格式不完整：缺少 suggestion」——但其實內容完整，只是位置變了。
    function structuredCandidate(response) {
        if (isObject(response?.structured)) return response.structured;
        const nested = response?.suggestion;
        if (isObject(nested) && (isObject(nested.overall) || isObject(nested.parts))) return nested;
        if (isObject(response) && (isObject(response.overall) || isObject(response.parts))) return response;
        return null;
    }

    function normalizeStructured(response, context) {
        const candidate = structuredCandidate(response);
        if (!candidate) return null;

        const overallRaw = isObject(candidate.overall) ? candidate.overall : {};
        const summary = text(overallRaw.summary);
        const partsRaw = isObject(candidate.parts) ? candidate.parts : {};
        const parts = {};
        const missingParts = [];

        for (const key of EXPECTED_PART_KEYS) {
            const raw = findPart(partsRaw, key);
            if (!raw) missingParts.push(key);
            parts[key] = {
                label: text(raw?.label) || PART_LABELS[key],
                analysis: text(raw?.analysis),
                steps: textList(raw?.steps),
                avoid: textList(raw?.avoid)
            };
        }

        return {
            source: 'structured',
            valid: !!summary && missingParts.length === 0,
            issues: [
                ...(!summary ? ['overall.summary'] : []),
                ...missingParts.map(key => `parts.${key}`)
            ],
            overall: {
                title: text(overallRaw.title),
                summary,
                palette: safePalette(overallRaw.palette, context?.palette),
                paletteSource: Array.isArray(overallRaw.palette) && overallRaw.palette.length ? 'response' : 'style'
            },
            parts,
            globalAvoid: textList(candidate.avoid),
            rawSuggestion: text(response?.suggestion)
        };
    }

    const HEADING_RULES = [
        ['overall', /^(?:第?[一1][、.．)\s]*)?整體妝容方向\s*[:：]?\s*(.*)$/i],
        ['base', /^(?:第?[二2][、.．)\s]*)?底妝建議\s*[:：]?\s*(.*)$/i],
        ['browEyes', /^(?:第?[三3][、.．)\s]*)?眉眼妝建議\s*[:：]?\s*(.*)$/i],
        ['contour', /^(?:第?[四4][、.．)\s]*)?(?:腮紅(?:與|及|\/)?修容|腮紅修容建議)\s*[:：]?\s*(.*)$/i],
        ['lips', /^(?:第?[四4五5][、.．)\s]*)?唇妝建議\s*[:：]?\s*(.*)$/i],
        ['avoid', /^(?:第?[五5六6][、.．)\s]*)?避免事項\s*[:：]?\s*(.*)$/i],
        ['summary', /^(?:第?[六6七7][、.．)\s]*)?總結與建議\s*[:：]?\s*(.*)$/i]
    ];

    function cleanLegacyLine(line) {
        return String(line || '')
            .replace(/^\s*(?:#{1,6}|>|[-+])\s*/, '')
            .replace(/^\s*\*+|\*+\s*$/g, '')
            .trim();
    }

    function parseSections(rawText) {
        const sections = {};
        let current = 'unsectioned';
        for (const originalLine of String(rawText || '').replace(/\r/g, '').split('\n')) {
            const line = cleanLegacyLine(originalLine);
            if (!line) continue;
            let matched = false;
            for (const [key, pattern] of HEADING_RULES) {
                const result = line.match(pattern);
                if (!result) continue;
                current = key;
                sections[current] = sections[current] || [];
                if (text(result[1])) sections[current].push(text(result[1]));
                matched = true;
                break;
            }
            if (!matched) {
                sections[current] = sections[current] || [];
                sections[current].push(line);
            }
        }
        return Object.fromEntries(Object.entries(sections).map(([key, lines]) => [key, lines.join('\n').trim()]));
    }

    function splitSentences(rawText) {
        const chunks = String(rawText || '').replace(/\r/g, '').match(/[^。！？；\n]+[。！？；]?/g) || [];
        return unique(chunks.map(chunk => chunk
            .replace(/^\s*(?:[-+•]|\d+[、.．)]|[一二三四五六七八九十]+[、.．)])\s*/, '')
            .trim()));
    }

    function matching(sentences, pattern, limit) {
        return unique((sentences || []).filter(sentence => pattern.test(sentence))).slice(0, limit || 4);
    }

    function firstUsefulSentence(rawText) {
        return splitSentences(rawText)[0] || '';
    }

    function parseLegacy(response, context) {
        const rawSuggestion = text(response?.suggestion);
        if (!rawSuggestion) return null;

        const sections = parseSections(rawSuggestion);
        const allSentences = splitSentences(rawSuggestion);
        const browEyeSentences = splitSentences(sections.browEyes);
        const avoidSentences = splitSentences(sections.avoid);
        const contourSentences = matching(
            splitSentences([sections.contour, sections.base, sections.overall, sections.summary].filter(Boolean).join('\n')),
            /腮紅|修容|顴骨|輪廓|鼻影|鼻翼|打亮|高光/,
            4
        );
        const summary = sections.overall || sections.summary || firstUsefulSentence(rawSuggestion);

        const partSteps = {
            base: splitSentences(sections.base).slice(0, 4),
            brow: matching(browEyeSentences, /眉|眉峰|眉尾|眉頭|毛流/, 4),
            eyes: matching(browEyeSentences, /眼|睫|臥蠶/, 4),
            contour: contourSentences,
            lips: splitSentences(sections.lips).slice(0, 4)
        };
        const avoidPatterns = {
            base: /底妝|粉底|遮瑕|定妝|膚|高光|打亮/,
            brow: /眉/,
            eyes: /眼|睫|臥蠶/,
            contour: /腮紅|修容|顴骨|輪廓|鼻影|鼻翼|高光|打亮/,
            lips: /唇|口紅|唇膏|唇釉/
        };
        const parts = {};
        for (const key of EXPECTED_PART_KEYS) {
            parts[key] = {
                label: PART_LABELS[key],
                analysis: '',
                steps: partSteps[key],
                avoid: matching(avoidSentences, avoidPatterns[key], 4)
            };
        }

        return {
            source: 'legacy',
            valid: !!summary,
            issues: EXPECTED_PART_KEYS.filter(key => !parts[key].steps.length).map(key => `parts.${key}.steps`),
            overall: {
                title: '',
                summary,
                palette: safePalette([], context?.palette),
                paletteSource: 'style'
            },
            parts,
            globalAvoid: avoidSentences,
            legacySections: sections,
            rawSuggestion,
            sentenceCount: allSentences.length
        };
    }

    function normalize(response, context) {
        const structured = normalizeStructured(response, context);
        if (structured?.valid) return structured;

        const legacy = parseLegacy(response, context);
        if (legacy?.valid) {
            if (structured?.issues?.length) legacy.issues = [...structured.issues, ...legacy.issues];
            return legacy;
        }

        const missing = structured?.issues?.length ? structured.issues.join(', ') : 'suggestion';
        const error = new Error(`Ollama 回傳格式不完整：缺少 ${missing}`);
        error.code = 'INVALID_SUGGESTION_CONTRACT';
        throw error;
    }

    root.MakeupSuggestionContract = {
        EXPECTED_PART_KEYS: [...EXPECTED_PART_KEYS],
        normalize,
        normalizeStructured,
        parseLegacy,
        parseSections,
        splitSentences
    };
})(typeof window !== 'undefined' ? window : globalThis);
