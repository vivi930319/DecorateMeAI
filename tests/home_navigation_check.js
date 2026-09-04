#!/usr/bin/env node
// Regression check for the homepage face-analysis entry point.
// The primary CTA must use the global data-page route handler so it still works
// when the dashboard page is rendered from the fallback template.

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const index = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const dashboard = fs.readFileSync(path.join(root, 'pages', 'dashboard.html'), 'utf8');
const router = fs.readFileSync(path.join(root, 'js', 'router.js'), 'utf8');
const mainCss = fs.readFileSync(path.join(root, 'css', 'main.css'), 'utf8');

const fail = message => {
    console.error(`FAIL ${message}`);
    process.exit(1);
};
const pass = message => console.log(`PASS ${message}`);

const primaryCta = dashboard.match(/<button\b[^>]*\bid="dashPrimaryCta"[^>]*>/)?.[0]
    || dashboard.match(/<button\b[^>]*\bdata-page="analysis"[^>]*>/)?.[0]
    || '';
if (!primaryCta.includes('data-page="analysis"') || !primaryCta.includes('id="dashPrimaryCta"')) {
    fail('dashboard primary CTA must use data-page="analysis"');
}
if (primaryCta.includes('data-nav=')) {
    fail('dashboard primary CTA must not depend on data-nav');
}
if (/<button[^>]*>\s*重新分析\s*<\/button>/.test(dashboard)) {
    fail('dashboard must not render a re-analyze button');
}
const fallbackCta = router.match(/<button\b[^>]*\bid="dashPrimaryCta"[^>]*>/)?.[0]
    || router.match(/<button\b[^>]*\bdata-page="analysis"[^>]*>/)?.[0]
    || '';
if (!fallbackCta.includes('data-page="analysis"') || !fallbackCta.includes('id="dashPrimaryCta"')) {
    fail('fallback dashboard must use data-page="analysis"');
}
if (/data-rec-reanalyze/.test(router) || /<button[^>]*>\s*重新分析\s*<\/button>/.test(router)) {
    fail('router must not render a re-analyze button');
}
if (/class="topbar-user"[^>]*data-page="profile"[^>]*onclick=/.test(index)) {
    fail('topbar user must not have a second inline Router.go handler');
}
if (/querySelectorAll\('\.topbar-nav a, \.topbar-user'\)/.test(router)) {
    fail('topbar navigation must use only the delegated click handler');
}
if (/intro\.addEventListener\(['"]click['"]/.test(index)
    || !/#brand-intro\s*\{[\s\S]*?pointer-events\s*:\s*none/.test(mainCss)) {
    fail('brand intro must not consume the homepage first click');
}
if (!/const openFilePicker = \(input\) =>/.test(router)
    || !/input\.value = ''/.test(router)
    || !/uploadBox\.onclick = \(event\) =>/.test(router)) {
    fail('face analysis upload must reset the file input before opening the picker');
}
if (!/go\(page, opts\) \{[\s\S]*?const tracked = promise\.finally\(\(\) => \{[\s\S]*?this\._navigationPromise === tracked/s.test(router)
    || !/async _go\(page, opts\)/.test(router)) {
    fail('router must deduplicate concurrent navigation to the same page');
}
if (!/this\._fetchPageTemplate\(page\)/.test(router)
    || !/_pageTemplateCache: new Map\(\)/.test(router)
    || !/cache: 'default'/.test(router)
    || !/this\._prefetchPageTemplates\(page\)/.test(router)) {
    fail('page navigation must reuse versioned templates and prefetch them while idle');
}
if (!/function renderDashboardProductArea\(\)/.test(router)
    || !/if \(Router\.currentPage === 'dashboard'\) renderDashboardProductArea\(\)/.test(router)
    || /if \(Router\.currentPage === 'dashboard'\) PageInit\.dashboard\(\)/.test(router)) {
    fail('dashboard product refresh must not reinitialize the whole homepage');
}
if (!/const ROUTE_PAGES = new Set\(NAV_ORDER\)/.test(router) || !/\['dashboard','analysis'/.test(router)) {
    fail('analysis route must remain registered');
}
if (!router.includes("e.target.closest('a[data-page], button[data-page]')")
    || !/Router\.go\(page\)/.test(router)) {
    fail('global data-page handler must route to Router.go');
}

pass('homepage face-analysis CTA uses global analysis route');
pass('homepage and fallback contain no re-analyze button');
pass('recommendation empty state contains no re-analyze button');
pass('analysis route remains registered');
pass('brand intro does not consume the homepage first click');
pass('page templates are cached and prefetched without blocking navigation');
pass('dashboard background product loading only refreshes its own area');
