// Ticket workflow typecheck gate: `tsc --noEmit -p <tsconfig>` over the whole project.
//   node .atw/core/presets/tsc/tsc-gate.cjs [--project <tsconfig.json>] <changed files...>
// tsc cannot apply a tsconfig to a subset of files, so the changed files the lint gate passes
// in are ignored: the gate only calls this when a matching file changed. The result is the
// exit code (lint output "exit-code"), so every type error fails, also on unchanged lines.
'use strict';
const path = require('path');
const { spawnSync } = require('child_process');

const root = process.cwd();
const args = process.argv.slice(2);
const i = args.indexOf('--project');
const project = i >= 0 ? args[i + 1] : 'tsconfig.json';
let tsc;
try {
  tsc = require.resolve('typescript/bin/tsc', { paths: [root] });
} catch (_) {
  console.error('[atw] typescript is not installed in this project (npm install)');
  process.exit(2);
}
const res = spawnSync(process.execPath, [tsc, '--noEmit', '-p', path.resolve(root, project)], { cwd: root, stdio: 'inherit' });
process.exit(res.status === null ? 1 : res.status);
