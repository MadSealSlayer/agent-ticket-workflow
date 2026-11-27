// Karma config used only by the ticket workflow's proof and tests gates (via karma-run.cjs).
// Headless and single-run, like the Angular builder defaults, plus an inline JUnit reporter,
// so no dependency is added to the project.
// Env: ATW_JUNIT (output path, optional), ATW_SPEC_FILES (JSON list of the included spec paths),
//      ATW_KARMA_BROWSER (default ChromeHeadless).
'use strict';
const fs = require('fs');
const path = require('path');

const root = process.cwd();
const load = (name) => require(require.resolve(name, { paths: [root] }));
const has = (name) => { try { require.resolve(name, { paths: [root] }); return true; } catch (_) { return false; } };

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Karma does not say which spec file a test came from. Attribute each result to the first
// included spec file whose text contains its top-level describe title in quotes. This is a
// heuristic: two files with the same top-level title, or a computed title, give a wrong or
// empty `file`, and a proof id with a path may then not be found.
function fileFor(topTitle, specFiles) {
  for (const f of specFiles) {
    try {
      const text = fs.readFileSync(path.resolve(root, f), 'utf8');
      if (['\'', '"', '`'].some((q) => text.includes(q + topTitle + q))) return f;
    } catch (_) { /* unreadable: try the next file */ }
  }
  return '';
}

function AtwJunitReporter(baseReporterDecorator) {
  baseReporterDecorator(this);
  this.adapters = [function () {}]; // the progress reporter already prints to the console
  const out = process.env.ATW_JUNIT;
  const specFiles = JSON.parse(process.env.ATW_SPEC_FILES || '[]');
  const cases = [];

  this.onSpecComplete = function (browser, result) {
    const suite = result.suite || [];
    cases.push({
      name: [...suite, result.description].join(' '),
      classname: suite.join(' '),
      file: fileFor(suite[0] || '', specFiles),
      time: (result.time || 0) / 1000,
      skipped: !!(result.skipped || result.pending),
      failure: result.success ? null : (result.log || []).join('\n') || 'failed',
    });
  };

  this.onBrowserError = function (browser, error) {
    cases.push({ name: 'karma browser error', classname: 'karma', file: '', time: 0, skipped: false,
      error: typeof error === 'string' ? error : JSON.stringify(error) });
  };

  this.onRunComplete = function () {
    if (!out) return;
    const fail = cases.filter((c) => c.failure).length;
    const err = cases.filter((c) => c.error).length;
    const skip = cases.filter((c) => c.skipped).length;
    const body = cases.map((c) => {
      const attrs = `classname="${esc(c.classname)}" name="${esc(c.name)}" file="${esc(c.file)}" time="${c.time}"`;
      if (c.error) return `  <testcase ${attrs}><error message="${esc(c.error.split('\n')[0])}">${esc(c.error)}</error></testcase>`;
      if (c.skipped) return `  <testcase ${attrs}><skipped/></testcase>`;
      if (c.failure) return `  <testcase ${attrs}><failure message="${esc(c.failure.split('\n')[0])}">${esc(c.failure)}</failure></testcase>`;
      return `  <testcase ${attrs}/>`;
    }).join('\n');
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, `<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="karma" tests="${cases.length}" `
      + `failures="${fail}" errors="${err}" skipped="${skip}">\n${body}\n</testsuite>\n`);
  };
}
AtwJunitReporter.$inject = ['baseReporterDecorator'];

module.exports = function (config) {
  // @angular-devkit/build-angular:karma needs its Karma plugin; @angular/build:karma does not.
  const devkit = has('@angular-devkit/build-angular/plugins/karma');
  config.set({
    basePath: '',
    frameworks: devkit ? ['jasmine', '@angular-devkit/build-angular'] : ['jasmine'],
    plugins: [
      load('karma-jasmine'),
      load('karma-chrome-launcher'),
      ...(devkit ? [load('@angular-devkit/build-angular/plugins/karma')] : []),
      { 'reporter:atw-junit': ['type', AtwJunitReporter] },
    ],
    reporters: ['progress', 'atw-junit'],
    browsers: [process.env.ATW_KARMA_BROWSER || 'ChromeHeadless'],
    singleRun: true,
    autoWatch: false,
    restartOnFileChange: false,
  });
};
module.exports.AtwJunitReporter = AtwJunitReporter; // for the package's own tests
