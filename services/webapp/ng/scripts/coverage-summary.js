#!/usr/bin/env node
// Markdown summary of a karma-coverage json-summary report, for the CI job
// summary: the totals, then the files with the most uncovered statements.
//   node scripts/coverage-summary.js coverage/rmn/coverage-summary.json
const fs = require('fs');

const LEAST_COVERED = 15;
const report = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const metrics = ['statements', 'branches', 'functions', 'lines'];
const pct = (m) => `${m.pct.toFixed(1)} %`;

const lines = ['### webapp coverage', '', '| | ' + metrics.join(' | ') + ' |', '|---|' + metrics.map(() => '---:').join('|') + '|'];
lines.push('| **total** | ' + metrics.map((m) => `${pct(report.total[m])} (${report.total[m].covered}/${report.total[m].total})`).join(' | ') + ' |');

const files = Object.entries(report)
  .filter(([name]) => name !== 'total')
  .map(([name, m]) => ({ name: name.replace(/^.*\/src\/app\//, ''), m, missing: m.statements.total - m.statements.covered }))
  .filter((f) => f.missing > 0)
  .sort((a, b) => b.missing - a.missing)
  .slice(0, LEAST_COVERED);
if (files.length) {
  lines.push('', `Least covered (${files.length} files, by uncovered statements):`, '');
  lines.push('| file | uncovered | ' + metrics.join(' | ') + ' |', '|---|---:|' + metrics.map(() => '---:').join('|') + '|');
  for (const f of files) {
    lines.push(`| ${f.name} | ${f.missing} | ` + metrics.map((m) => pct(f.m[m])).join(' | ') + ' |');
  }
}
console.log(lines.join('\n'));
