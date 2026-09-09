// Execute the real analysis handler with deferred APIs. No DOM/network/model required.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('node:assert/strict');
const root = path.resolve(process.argv[2] || path.join(__dirname, '..'));
const source = fs.readFileSync(path.join(root, 'js/router.js'), 'utf8').replace(/\r\n/g, '\n');
function statement(signature) {
    const start = source.indexOf(signature);
    assert.notEqual(start, -1, signature);
    const end = source.indexOf('\n        };', start);
    assert.ok(end > start, signature);
    return source.slice(start, end + '\n        };'.length);
}
const guardStart = source.indexOf('        const pageGeneration =');
const guardEnd = source.indexOf('\n        Router.analyzeMode =', guardStart);
assert.ok(guardStart > 0 && guardEnd > guardStart);
const tick = () => new Promise(resolve => setImmediate(resolve));

function setup({ deferredCompression = false, deferredBrightness = false } = {}) {
    const events = [], pending = [], timers = [];
    const noop = () => {};
    const element = () => ({ disabled: false, style: {}, classList: { toggle: noop, remove: noop }, removeAttribute: noop });
    const button = element();
    let currentButton = button, finishCompression, finishBrightness;
    const ctx = {
        Router: { analyzeMode: 'basic', selectedFile: { name: 'photo-A' }, proFiles: {},
            analysisPackage: { id: 'pkg-A', async: {}, analysis: {}, generativeText: {}, render: {} } },
        analyzeBtn: button, basicModeBtn: element(), proModeBtn: element(), basicPanel: element(), proPanel: element(),
        uploadBox: element(), preview: element(), bar: element(), fill: element(), bpSlider: { value: '0' },
        bpSliderTimer: null, bpApplyVersion: 0, isProUnlocked: true,
        bpApplyMode: async () => { if (deferredBrightness) await new Promise(resolve => { finishBrightness = resolve; }); },
        bpRefreshPanel: noop, stopProScan: noop, setResultState: noop, updatePackageStatus: noop, saveDraft: noop,
        setLoadingStatus: text => events.push({ status: text }), showAlert: message => events.push({ alert: message }),
        AnalysisPackage: { update: (p, patch) => ({ ...p, ...patch }), fromRawFaceAnalysis: (data, mode) => ({ data, mode }) },
        AnalysisDraft: { save: noop }, History: { add: data => events.push({ history: data }) },
        document: { getElementById: id => id === 'analyzeBtn' ? currentButton : null, querySelectorAll: () => [] },
        paintNoseCell: noop, renderAnalysisFeedback: noop,
        setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout: noop,
        ImagePipeline: { compressForPackage: async file => {
            events.push({ compressed: file.name });
            if (deferredCompression) await new Promise(resolve => { finishCompression = resolve; });
            return { file, meta: { originalName: file.name }, dataUrl: file.name };
        } },
        Api: {
            _pinnedActor: () => 'actor-A',
            createFaceJob: async file => { events.push({ submitted: file.name }); return { jobId: 'JOB-A', resultToken: 'fixture' }; },
            createFaceProJob: async () => { throw new Error('unexpected PRO submission'); },
            waitForFaceJob: (mode, id, token, progress) => new Promise((resolve, reject) => {
                events.push({ polled: mode, id }); pending.push({ resolve, reject, progress });
            })
        }
    };
    vm.runInNewContext(source.slice(guardStart, guardEnd)
        + '\n' + statement('        const compressImagesForPackage =')
        + '\n' + statement('        const setMode =') + '\nthis.switchMode = setMode;'
        + '\n' + statement('        analyzeBtn.onclick ='), ctx);
    return { ctx, events, pending, timers, click: () => button.onclick(),
        detach: () => { currentButton = element(); ctx.Router._analysisGeneration += 1; },
        complete: () => pending.shift().resolve({ result: { label: 'result-for-A' } }),
        finishCompression: () => finishCompression(), finishBrightness: () => finishBrightness() };
}

let passed = 0;
async function check(name, test) { await test(); passed += 1; console.log(`PASS ${name}`); }
(async () => {
    await check('normal result retains its submitted photo and restores controls', async () => {
        const s = setup(); const run = s.click(); await tick();
        assert.equal(s.ctx.analyzeBtn.disabled, true);
        s.complete(); await run;
        assert.equal(s.ctx.Router.analysisPackage.images.front.originalName, 'photo-A');
        assert.equal(s.ctx.Router.analysisPackage.faceAnalysis.data.label, 'result-for-A');
        assert.equal(s.ctx.analyzeBtn.disabled, false);
    });
    await check('double click and mode switching cannot start or redirect a pending run', async () => {
        const s = setup(); const run = s.click(); await s.click(); s.ctx.switchMode('pro'); await tick();
        assert.equal(s.ctx.Router.analyzeMode, 'basic');
        assert.equal(s.events.filter(e => e.submitted).length, 1);
        assert.equal(s.events.find(e => e.polled).polled, 'basic');
        s.complete(); await run;
    });
    await check('changed photo cannot receive an old result or photo package', async () => {
        const s = setup(); const run = s.click(); await tick();
        s.ctx.Router.selectedFile = { name: 'photo-B' };
        s.ctx.Router.analysisPackage = { id: 'pkg-B' };
        s.complete(); await run;
        assert.equal(s.ctx.Router.analysisPackage.id, 'pkg-B');
        assert.equal(s.ctx.Router.analysisPackage.images, undefined);
        assert.equal(s.events.filter(e => e.history).length, 0);
    });
    await check('navigation ignores both stale success and stale failure', async () => {
        for (const fail of [false, true]) {
            const s = setup(); const run = s.click(); await tick(); s.detach();
            s.ctx.Router.analysisPackage = { id: 'new-page' };
            if (fail) s.pending.shift().reject(new Error('old API failure')); else s.complete();
            await run;
            assert.equal(s.ctx.Router.analysisPackage.id, 'new-page');
            assert.equal(s.events.filter(e => e.history || e.alert).length, 0);
        }
    });
    await check('account changes discard the old account result', async () => {
        const s = setup(); const run = s.click(); await tick();
        s.ctx.Api._pinnedActor = () => 'actor-B'; s.complete(); await run;
        assert.equal(s.events.filter(e => e.history).length, 0);
    });
    await check('compression uses the snapshot and never overwrites a new page', async () => {
        const s = setup({ deferredCompression: true }); const run = s.click(); await tick(); s.complete(); await tick();
        assert.equal(s.events.find(e => e.compressed).compressed, 'photo-A');
        s.detach(); s.ctx.Router.analysisPackage = { id: 'new-page' };
        s.finishCompression(); await run;
        assert.equal(s.ctx.Router.analysisPackage.id, 'new-page');
        assert.equal(s.ctx.Router.packageImageFiles, undefined);
    });
    await check('submission awaits image processing and locks before the first await', async () => {
        const s = setup({ deferredBrightness: true }); const run = s.click(); await tick();
        assert.equal(s.ctx.analyzeBtn.disabled, true);
        assert.equal(s.events.filter(e => e.submitted).length, 0);
        await s.click(); s.finishBrightness(); await tick();
        assert.equal(s.events.filter(e => e.submitted).length, 1);
        s.complete(); await run;
    });
    await check('old completion timer cannot clear a later analysis progress bar', async () => {
        const s = setup(); const first = s.click(); await tick(); s.complete(); await first;
        const oldTimer = s.timers[0]; const second = s.click(); await tick();
        const progress = s.ctx.fill.style.width; oldTimer();
        assert.equal(s.ctx.fill.style.width, progress);
        s.complete(); await second;
    });
    console.log(`${passed}/${passed} behavioral regressions passed`);
})().catch(error => { console.error(error); process.exitCode = 1; });
