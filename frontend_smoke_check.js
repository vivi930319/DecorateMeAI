const fs = require('fs');
const path = require('path');
const vm = require('vm');

const rootDir = __dirname;
const apiSource = fs.readFileSync(path.join(rootDir, 'js', 'api.js'), 'utf8');

const sandbox = {
  console,
  FormData: class FormData {
    append() {}
  },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  document: {
    createElement: () => ({
      getContext: () => ({ drawImage() {} }),
      toBlob: () => {}
    })
  },
  Image: class Image {},
  FileReader: class FileReader {},
  File: class File {},
  localStorage: {
    setItem() {},
    getItem() { return null; },
    removeItem() {}
  }
};

vm.createContext(sandbox);
vm.runInContext(`${apiSource}; this.ApiConfig = ApiConfig; this.Api = Api; this.ImagePipeline = ImagePipeline; this.AnalysisPackage = AnalysisPackage;`, sandbox);

const requiredServices = ['faceBasic', 'facePro', 'textSuggestion', 'render', 'product', 'memberDatabase'];
for (const service of requiredServices) {
  if (!sandbox.ApiConfig.services[service]) throw new Error(`Missing service: ${service}`);
}

const basicUrl = sandbox.ApiConfig.url('faceBasic', 'analyzePath');
const proUrl = sandbox.ApiConfig.url('facePro', 'analyzePath');
const suggestionUrl = sandbox.ApiConfig.url('textSuggestion', 'suggestPath');
if (!basicUrl.endsWith('/v1/face/analyze/basic')) throw new Error(`Bad BASIC URL: ${basicUrl}`);
if (!proUrl.endsWith('/v1/face/analyze/pro')) throw new Error(`Bad PRO URL: ${proUrl}`);
if (suggestionUrl !== 'http://127.0.0.1:8010/suggest') throw new Error(`Bad suggestion URL: ${suggestionUrl}`);

for (const method of ['createFaceJob', 'createFaceProJob', 'getFaceJob', 'getFaceJobResult', 'waitForFaceJob', 'suggestMakeup']) {
  if (typeof sandbox.Api[method] !== 'function') throw new Error(`Missing Api.${method}`);
}
for (const method of ['compressForPackage', 'compressInWorker', 'compressOnMainThread', 'canUseWorker']) {
  if (typeof sandbox.ImagePipeline[method] !== 'function') throw new Error(`Missing ImagePipeline.${method}`);
}
if (sandbox.ImagePipeline.workerPath !== 'js/image-worker.js') {
  throw new Error(`Bad image worker path: ${sandbox.ImagePipeline.workerPath}`);
}

const pkg = sandbox.AnalysisPackage.create({ mode: 'basic' });
if (pkg.schemaVersion !== '2026-06-v1') throw new Error('Bad schemaVersion');
if (!pkg.faceAnalysis || !pkg.generativeText || !pkg.render || !pkg.recommendations) {
  throw new Error('analysisPackage missing expected sections');
}
if (!pkg.async || !Object.prototype.hasOwnProperty.call(pkg.async, 'jobId')) {
  throw new Error('analysisPackage async job fields missing');
}

console.log('frontend smoke check passed');
