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
  const chat = spawnSync(process.execPath,
    ['chat-service-check.mjs', process.argv[pythonIndex + 1], ...(coreIndex >= 0 ? [process.argv[coreIndex + 1]]: [])],
    {cwd, stdio: 'inherit'});
  if(chat.status !== 0) process.exit(chat.status ?? 1);
  const claims = spawnSync(process.execPath,
    ['claim-service-check.mjs', process.argv[pythonIndex + 1], ...(coreIndex >= 0 ? [process.argv[coreIndex + 1]]: [])],
    {cwd, stdio: 'inherit'});
  if(claims.status !== 0) process.exit(claims.status ?? 1);
  const sources = spawnSync(process.execPath,
    ['source-service-check.mjs', process.argv[pythonIndex + 1], ...(coreIndex >= 0 ? [process.argv[coreIndex + 1]]: [])],
    {cwd, stdio: 'inherit'});
  if(sources.status !== 0) process.exit(sources.status ?? 1);
  const activity = spawnSync(process.execPath,
    ['research-activity-service-check.mjs', process.argv[pythonIndex + 1], ...(coreIndex >= 0 ? [process.argv[coreIndex + 1]]: [])],
    {cwd, stdio: 'inherit'});
  if(activity.status !== 0) process.exit(activity.status ?? 1);
  const inbox = spawnSync(process.execPath,
    ['inbox-service-check.mjs', process.argv[pythonIndex + 1], ...(coreIndex >= 0 ? [process.argv[coreIndex + 1]]: [])],
    {cwd, stdio: 'inherit'});
  if(inbox.status !== 0) process.exit(inbox.status ?? 1);
  const legacy = spawnSync(process.execPath,
    ['legacy-workflow-service-check.mjs', process.argv[pythonIndex + 1], ...(coreIndex >= 0 ? [process.argv[coreIndex + 1]]: [])],
    {cwd, stdio: 'inherit'});
  if(legacy.status !== 0) process.exit(legacy.status ?? 1);
}

if(pythonIndex >= 0) {
  const coreIndex = process.argv.indexOf('--core-root');
  const initial = spawnSync(process.execPath,
    ['initial-deletion-service-check.mjs', process.argv[pythonIndex + 1],
      ...(coreIndex >= 0 ? [process.argv[coreIndex + 1]] : [])],
    {cwd, stdio: 'inherit'});
  if(initial.status !== 0) process.exit(initial.status ?? 1);
}

if(pythonIndex >= 0) {
  const coreIndex = process.argv.indexOf('--core-root');
  const nullable = spawnSync(process.execPath,
    ['nullable-list-service-check.mjs', process.argv[pythonIndex + 1],
      ...(coreIndex >= 0 ? [process.argv[coreIndex + 1]] : [])],
    {cwd, stdio: 'inherit'});
  if(nullable.status !== 0) process.exit(nullable.status ?? 1);
}

if(pythonIndex >= 0) {
  const coreIndex=process.argv.indexOf('--core-root');
  const pins=spawnSync(process.execPath,['queue-pin-service-check.mjs',process.argv[pythonIndex+1],
    ...(coreIndex>=0?[process.argv[coreIndex+1]]:[])],{cwd,stdio:'inherit'});
  if(pins.status!==0)process.exit(pins.status??1);
}

if(pythonIndex >= 0) {
  const coreIndex=process.argv.indexOf('--core-root');
  const positions=spawnSync(process.execPath,['position-service-check.mjs',process.argv[pythonIndex+1],
    ...(coreIndex>=0?[process.argv[coreIndex+1]]:[])],{cwd,stdio:'inherit'});
  if(positions.status!==0)process.exit(positions.status??1);
}
