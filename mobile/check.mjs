import {
  spawnSync
} from 'node:child_process';
import {
  readdirSync
} from 'node:fs';
import {
  fileURLToPath
} from 'node:url';
const cwd = fileURLToPath(new URL('.', import.meta.url));
const files = readdirSync(new URL('./tests/', import.meta.url)).filter(name => name.endsWith('.test.mjs')).map(name => 'tests/' + name);
const result = spawnSync(process.execPath, ['--test', ...files], {
  cwd,
  stdio: 'inherit'
});
if(result.status !== 0) process.exit(result.status ?? 1);
const pythonIndex = process.argv.indexOf('--python');
if(pythonIndex >= 0) {
  const coreIndex = process.argv.indexOf('--core-root');
  const integration = spawnSync(
  process.execPath,
  ['service-check.mjs', process.argv[pythonIndex + 1], ...(coreIndex >= 0 ?[process.argv[coreIndex + 1]]: [])],
  {
    cwd,
    stdio: 'inherit'
  }
  );
  if(integration.status !== 0) process.exit(integration.status ?? 1);
}
