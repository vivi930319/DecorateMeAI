const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');
const root = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'js/router.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'pages/admin.html'), 'utf8');
assert(html.indexOf('id="adminFeedbackJumpTraining"') > html.indexOf('id="adminFeedbackBody"'));
assert.equal((html.match(/id="adminFeedbackJumpTraining"/g) || []).length, 1);
const start = src.indexOf('const fbJumpTraining =');
const end = src.indexOf('\n            };', start);
assert(start >= 0 && end > start);
const code = src.slice(start, end + '\n            };'.length);
for (const reduced of [false, true]) {
  const button = {};
  const calls = [];
  const target = { style: {}, setAttribute: (...a) => calls.push(['attr', ...a]),
    scrollIntoView: a => calls.push(['scroll', a.behavior, a.block]),
    focus: a => calls.push(['focus', a.preventScroll]) };
  const context = {
    document: { getElementById: id => id === 'adminFeedbackJumpTraining' ? button : target },
    window: { matchMedia: () => ({matches: reduced}) }
  };
  vm.runInNewContext(code, context);
  button.onclick();
  assert.deepEqual(calls, [['attr','tabindex','-1'], ['scroll',reduced?'auto':'smooth','start'], ['focus',true]]);
  assert.equal(target.style.scrollMarginTop, '100px');
  context.document.getElementById = () => null;
  assert.doesNotThrow(() => button.onclick());
}
// No API, selection or training state mutations belong in this handler.
assert(!/Api\.|fetch\(|fbSelected|Router\.go|location\./.test(code));
console.log('PASS: bottom shortcut, scroll/focus, reduced motion, missing target; no API or selection changes');
