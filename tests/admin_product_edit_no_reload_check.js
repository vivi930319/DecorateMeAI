#!/usr/bin/env node
// Regression check: editing an existing product (especially season tags) must
// update the current row without clearing and refetching the entire catalogue.
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const router = fs.readFileSync(path.join(root, 'js', 'router.js'), 'utf8');
const fail = message => { console.error(`FAIL ${message}`); process.exit(1); };

if (!/const updateAdminProductInPlace = \(target, result, payload\) =>/.test(router)
    || !/syncAdminBrandOptions\(dbProducts\);\s*renderProducts\(\);/.test(router)) {
    fail('admin product edits must merge the saved product into the current list');
}
if (!/finish\(result, '產品已更新並寫入資料庫', \{[\s\S]*?reload: false[\s\S]*?updateAdminProductInPlace/s.test(router)) {
    fail('existing product edits must disable the full catalogue reload');
}
if (!/if \(reload\) loadAdminProducts\(\);/.test(router)) {
    fail('new product creation and explicit reload paths must remain available');
}

console.log('商品編輯不整頁重載測試通過');
