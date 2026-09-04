// Execute the actual delegated listener against DOM ancestry, including body[data-page].
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../js/router.js'), 'utf8');
const start = source.indexOf("document.addEventListener('click', (e) => {", source.indexOf('(function init()'));
const end = source.indexOf("window.addEventListener('hashchange'", start);
assert(start >= 0 && end > start);
let listener;
const routes = [];
vm.runInNewContext(source.slice(start, end), {
    document: { addEventListener: (_, fn) => { listener = fn; } },
    Router: { go: page => routes.push(page) }
});
function element(tag, parent, page) {
    return { tag, parent, dataset: page ? { page } : {}, closest(selectors) {
        for (let n = this; n; n = n.parent) {
            if (selectors.split(',').some(selector => {
                const match = selector.trim().match(/^(\w*)\[data-page\]$/);
                return match && (!match[1] || match[1] === n.tag) && n.dataset.page;
            })) return n;
        }
        return null;
    } };
}
const body = element('body', null, 'analysis');
for (const tag of ['input', 'select', 'div', 'button']) {
    let prevented = false;
    listener({ target: element(tag, body), preventDefault() { prevented = true; } });
    assert.equal(prevented, false, `${tag}: native action must not be cancelled`);
    assert.equal(routes.length, 0, `${tag}: body must not trigger navigation`);
}
for (const tag of ['button', 'a']) {
    let prevented = false;
    listener({ target: element('span', element(tag, body, 'analysis')), preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
}
assert.deepEqual(routes, ['analysis', 'analysis']);
console.log('PASS: input, select, content and ordinary buttons do not navigate; nested route links navigate once');
