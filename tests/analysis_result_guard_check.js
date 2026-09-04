#!/usr/bin/env node
// Regression check: a completed analysis must not be reported as failed just
// because the result panel was unmounted before the async response returned.

const fs = require('fs');
const path = require('path');

const root = path.resolve(process.argv[2] || '.');
const router = fs.readFileSync(path.join(root, 'js', 'router.js'), 'utf8');

const checks = [
    [
        '結果文字欄位使用存在性防呆',
        router.includes("const paintResultText = (id, value) =>")
            && router.includes("if (el) el.textContent = value || '—';")
            && !router.includes("document.getElementById('r-face').textContent =")
    ],
    [
        '結果色塊與導向按鈕使用存在性防呆',
        router.includes("if (skinName) skinName.textContent =")
            && router.includes("if (skinSwatch) skinSwatch.style.background =")
            && router.includes("if (lipSwatch) lipSwatch.style.background =")
            && router.includes("if (goStyleBtn) goStyleBtn.style.display =")
    ],
    [
        '成功結果先保存再更新呈現層',
        router.indexOf("History.add({ ...data") >= 0
            && router.indexOf("History.add({ ...data") < router.indexOf("const paintResultText = (id, value) =>")
    ]
];

let failed = 0;
for (const [label, ok] of checks) {
    if (ok) console.log(`PASS ${label}`);
    else {
        failed += 1;
        console.error(`FAIL ${label}`);
    }
}

console.log(`${checks.length - failed}/${checks.length} passed`);
process.exitCode = failed ? 1 : 0;
