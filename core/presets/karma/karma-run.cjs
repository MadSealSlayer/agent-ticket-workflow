// Ticket workflow test runner for Angular workspaces that test with Karma.
//   node .atw/core/presets/karma/karma-run.cjs [--junit <out.xml>] [--dry-run] <spec files...>
//
// Karma has no single-test filter and no JUnit reporter by default. This wrapper:
//   1. maps each spec file to the angular.json project whose root (or sourceRoot) holds it,
//      the longest match first;
//   2. skips, with a warning, a spec that the project's tsconfig.spec.json does not include:
//      the project's own test target never runs it either;
//   3. runs one `ng test <project> --watch=false --karma-config <karma.atw.cjs> --include ...`
//      per project (the bundle build takes most of the time, so specs are grouped);
//   4. merges the per-project JUnit files into --junit.
// --dry-run prints the mapping as JSON and runs nothing.
// Node standard library only; it adds no dependency to the project.
'use strict';
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const root = process.cwd();
const posix = (p) => p.replace(/\\/g, '/');

function readJsonc(file) {
  const text = fs.readFileSync(file, 'utf8')
    .replace(/("(?:[^"\\]|\\.)*")|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, (m, str) => str || '')
    .replace(/,(\s*[}\]])/g, '$1');
  return JSON.parse(text);
}

function globRegex(glob) {
  let out = '';
  for (let i = 0; i < glob.length;) {
    if (glob.startsWith('**/', i)) { out += '(?:.*/)?'; i += 3; }
    else if (glob.startsWith('**', i)) { out += '.*'; i += 2; }
    else if (glob[i] === '*') { out += '[^/]*'; i += 1; }
    else if (glob[i] === '?') { out += '[^/]'; i += 1; }
    else { out += glob[i].replace(/[.+^${}()|[\]\\]/g, '\\$&'); i += 1; }
  }
  return new RegExp(`^${out}$`);
}

// include/exclude/files of a tsconfig, following relative `extends` for keys it does not set.
function tsconfigScope(file) {
  const scope = { dir: path.dirname(file) };
  const seen = new Set();
  let current = file;
  while (current && !seen.has(current) && fs.existsSync(current)) {
    seen.add(current);
    const data = readJsonc(current);
    for (const key of ['include', 'exclude', 'files']) {
      if (scope[key] === undefined && Array.isArray(data[key])) {
        scope[key] = data[key].map((g) => posix(path.relative(scope.dir, path.resolve(path.dirname(current), g))));
      }
    }
    const ext = typeof data.extends === 'string' && data.extends.startsWith('.') ? data.extends : null;
    current = ext ? path.resolve(path.dirname(current), ext.endsWith('.json') ? ext : `${ext}.json`) : null;
  }
  return scope;
}

function asGlob(pattern) {
  // A bare folder (no wildcard, no extension) means everything under it.
  return /[*?]/.test(pattern) || path.extname(pattern) ? pattern : `${pattern.replace(/\/$/, '')}/**/*`;
}

function included(spec, scope) {
  const rel = posix(path.relative(scope.dir, path.resolve(root, spec)));
  if ((scope.files || []).some((f) => posix(f) === rel)) return true;
  const include = scope.include || (scope.files ? [] : ['**/*']);
  const hit = include.some((g) => globRegex(asGlob(posix(g))).test(rel));
  return hit && !(scope.exclude || []).some((g) => globRegex(asGlob(posix(g))).test(rel));
}

function karmaProjects() {
  const file = path.join(root, 'angular.json');
  if (!fs.existsSync(file)) throw new Error('angular.json not found in the working directory');
  const ws = readJsonc(file);
  const out = [];
  for (const [name, p] of Object.entries(ws.projects || {})) {
    const test = (p.architect || p.targets || {}).test;
    if (!test || !/karma/.test(test.builder || '')) continue;
    const prefixes = [p.sourceRoot, p.root].filter((x) => typeof x === 'string').map((x) => {
      const s = posix(x).replace(/^\.\//, '').replace(/\/$/, '');
      return s ? `${s}/` : '';
    });
    const tsConfig = (test.options || {}).tsConfig;
    out.push({ name, prefixes, tsConfig: tsConfig ? path.resolve(root, tsConfig) : null });
  }
  return out;
}

function plan(files) {
  const projects = karmaProjects();
  const byProject = {};
  const skipped = [];
  for (const f of files) {
    let best = null;
    let bestLen = -1;
    for (const p of projects) {
      for (const pre of p.prefixes) {
        if (f.startsWith(pre) && pre.length > bestLen) { best = p; bestLen = pre.length; }
      }
    }
    if (!best) { skipped.push({ file: f, why: 'no angular.json project with a Karma test target holds it' }); continue; }
    if (best.tsConfig && fs.existsSync(best.tsConfig) && !included(f, tsconfigScope(best.tsConfig))) {
      skipped.push({ file: f, why: `not included by ${posix(path.relative(root, best.tsConfig))}, so ${best.name}'s tests never run it` });
      continue;
    }
    (byProject[best.name] = byProject[best.name] || []).push(f);
  }
  return { projects: byProject, skipped };
}

function mergeJunit(parts, out) {
  const cases = [];
  for (const p of parts) {
    if (!fs.existsSync(p)) continue;
    const text = fs.readFileSync(p, 'utf8');
    cases.push(...(text.match(/^ {2}<testcase [\s\S]*?(?:\/>|<\/testcase>)$/gm) || []));
    fs.rmSync(p, { force: true });
  }
  const count = (re) => cases.filter((c) => re.test(c)).length;
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, `<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="karma" tests="${cases.length}" `
    + `failures="${count(/<failure /)}" errors="${count(/<error /)}" skipped="${count(/<skipped\/>/)}">\n`
    + `${cases.join('\n')}\n</testsuite>\n`);
}

function main(argv) {
  let junit = null;
  let dryRun = false;
  const files = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--junit') junit = path.resolve(root, argv[++i]);
    else if (argv[i] === '--dry-run') dryRun = true;
    else if (argv[i]) files.push(posix(argv[i]).replace(/^\.\//, ''));
  }
  const specs = files.filter((f) => /\.spec\.[cm]?[jt]s$/.test(f));
  for (const f of files) if (!specs.includes(f)) console.error(`[atw] not a spec file, ignored: ${f}`);
  const p = plan(specs);
  if (dryRun) {
    console.log(JSON.stringify(p, null, 2));
    return 0;
  }
  for (const s of p.skipped) console.error(`[atw] skipped ${s.file}: ${s.why}`);
  if (!Object.keys(p.projects).length) console.error('[atw] no spec file to run');

  const ng = require.resolve('@angular/cli/bin/ng.js', { paths: [root] });
  const karmaConfig = posix(path.relative(root, path.join(__dirname, 'karma.atw.cjs')));
  const parts = [];
  let failed = false;
  for (const [project, list] of Object.entries(p.projects)) {
    const part = junit ? `${junit}.${project.replace(/[^\w.-]+/g, '_')}.xml` : null;
    if (part) fs.rmSync(part, { force: true });
    console.error(`[atw] ng test ${project}: ${list.length} spec file(s)`);
    const res = spawnSync(process.execPath, [ng, 'test', project, '--watch=false', '--karma-config', karmaConfig,
      ...list.flatMap((s) => ['--include', s])], {
      cwd: root, stdio: 'inherit',
      env: { ...process.env, ATW_JUNIT: part || '', ATW_SPEC_FILES: JSON.stringify(list) },
    });
    if (res.status !== 0) failed = true;
    if (part) parts.push(part);
  }
  // A project whose build failed adds no test cases, so its proof ids show as "not reported".
  if (junit) mergeJunit(parts, junit);
  return failed ? 1 : 0;
}

try {
  process.exitCode = main(process.argv.slice(2));
} catch (e) {
  console.error(`[atw] karma-run: ${e.message}`);
  process.exitCode = 2;
}
