const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const src = fs.readFileSync(require('path').join(__dirname, '../js/router.js'), 'utf8');
const start = src.indexOf('if (submit) submit.onclick = async () => {');
assert(start >= 0);
const end = src.indexOf('\n    };', start);
assert(end > start);
const handler = src.slice(start, end + 7);
(async () => {
  for (const ok of [true, false]) {
    let sent;
    const note = {};
    const ctx = {
      submit: { disabled: false }, packageId: 'pkg', predicted: {臉型:'圓形臉'},
      corrections: {臉型:'方形臉'}, allowTraining: false,
      isGuest: () => true,
      AnalysisFeedback: {save() {}}, applyAnalysisCorrections() {}, showToast() {},
      document: {getElementById: () => note},
      Router: {analyzeMode:'basic',analysisPackage:{async:{jobId:'JOB-test',resultToken:'test-token'}}},
      Api: {sendAnalysisFeedback: async payload => { sent=payload; return {ok}; }}
    };
    vm.runInNewContext(handler, ctx);
    await ctx.submit.onclick();
    assert.equal(sent.jobId, 'JOB-test');
    assert.equal(sent.resultToken, 'test-token');
    assert.equal(sent.imageDataUrl, '');
    assert.equal(sent.allowTrainingUse, false);
    assert.equal(ctx.submit.disabled, false);
    assert(note.textContent.includes(ok ? '已送至模型修正複核' : '未送達後台'));
  }
  console.log('PASS guest feedback: delivery, token, consent, success/failure, retry enabled');
})().catch(e => { console.error(e); process.exitCode=1; });
