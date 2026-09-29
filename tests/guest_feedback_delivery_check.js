const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const src = fs.readFileSync(require('path').join(__dirname, '../js/router.js'), 'utf8');
const start = src.indexOf('  const submitFeedback = async () => {');
assert(start >= 0);
const end = src.indexOf('\n  };', start);
assert(end > start);
const handler = src.slice(start, end + 5);
(async () => {
  for (const ok of [true, false]) {
    let sent;
    const note = {};
    const submit = { disabled: false };
    const ctx = {
      packageId: 'pkg', predicted: {臉型:'圓形臉'},
      corrections: {臉型:'方形臉'}, allowTraining: false,
      submitting: false,
      isGuest: () => true,
      AnalysisFeedback: {save() {}}, applyAnalysisCorrections() {}, showToast() {},
      box: {querySelector: selector => selector === '#afSubmit' ? submit : note},
      Router: {analyzeMode:'basic',analysisPackage:{async:{jobId:'JOB-test',resultToken:'test-token'}}},
      Api: {sendAnalysisFeedback: async payload => { sent=payload; return {ok}; }}
    };
    vm.runInNewContext(handler + '\nresult = submitFeedback;', ctx);
    await ctx.result();
    assert.equal(sent.jobId, 'JOB-test');
    assert.equal(sent.resultToken, 'test-token');
    assert.equal(sent.imageDataUrl, '');
    assert.equal(sent.allowTrainingUse, false);
    assert.equal(submit.disabled, false);
    assert(note.textContent.includes(ok ? '已送至模型修正複核' : '未送達後台'));
  }
  console.log('PASS guest feedback: delivery, token, consent, success/failure, retry enabled');
})().catch(e => { console.error(e); process.exitCode=1; });
