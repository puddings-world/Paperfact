import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const script=fileURLToPath(new URL('../check.mjs',import.meta.url));
const root=fileURLToPath(new URL('../../',import.meta.url));
const harness=String.raw`
const child=require('node:child_process');
const {syncBuiltinESMExports}=require('node:module');
const {pathToFileURL}=require('node:url');
const fs=require('node:fs');
const [script,root,mode]=process.argv.slice(1);
const seen=[];
child.spawnSync=(command,args,options)=>{
  seen.push({command,args,cwd:options.cwd});
  return {status:mode==='unit-fail'&&args[0]==='--test'?13:
    mode==='later-fail'&&args[0]==='later-outcome-service-check.mjs'?7:
    mode==='note-fail'&&args[0]==='plain-note-service-check.mjs'?9:0};
};
syncBuiltinESMExports();
process.argv=[process.execPath,script,...(mode==='pure'?[]:
  ['--python','fixture-python','--core-root',root])];
process.on('exit',()=>fs.writeSync(1,JSON.stringify(seen)));
import(pathToFileURL(script).href).catch(error=>{console.error(error);process.exit(90);});
`;

function execute(mode){
  const result=spawnSync(process.execPath,['--input-type=commonjs','-e',harness,script,root,mode],
    {encoding:'utf8',timeout:10000,windowsHide:true});
  assert.equal(result.error,undefined);
  assert.equal(result.stderr,'');
  return {status:result.status,calls:JSON.parse(result.stdout)};
}

const existing=['service-check.mjs','chat-service-check.mjs','claim-service-check.mjs',
  'source-service-check.mjs','research-activity-service-check.mjs','inbox-service-check.mjs',
  'legacy-workflow-service-check.mjs','initial-deletion-service-check.mjs',
  'nullable-list-service-check.mjs','queue-pin-service-check.mjs','position-service-check.mjs'];

test('full mobile gate executes every existing HTTP journey and the later-outcome journey',()=>{
  const {status,calls}=execute('success');
  assert.equal(status,0);
  const programs=calls.filter(call=>call.args[0]!=='--test');
  assert.deepEqual(programs.map(call=>call.args[0]).sort(),
    [...existing,'later-outcome-service-check.mjs','plain-note-service-check.mjs'].sort());
  for(const call of programs){
    assert.equal(call.command,process.execPath);
    assert.deepEqual(call.args.slice(1),['fixture-python',root]);
  }
});

test('later-outcome HTTP failure fails the maintained mobile gate',()=>{
  const {status,calls}=execute('later-fail');
  assert.equal(status,7);
  assert.equal(calls.filter(call=>call.args[0]==='later-outcome-service-check.mjs').length,1);
});

test('pure mobile mode never launches Python service fixtures',()=>{
  const {status,calls}=execute('pure');
  assert.equal(status,0);
  assert.equal(calls.length,1);
  assert.equal(calls[0].args[0],'--test');
});

test('domain failure stops before any HTTP fixture is launched',()=>{
  const {status,calls}=execute('unit-fail');
  assert.equal(status,13);
  assert.equal(calls.length,1);
  assert.equal(calls[0].args[0],'--test');
});

test('plain-note HTTP failure fails the maintained mobile gate',()=>{
  const {status,calls}=execute('note-fail');
  assert.equal(status,9);
  assert.equal(calls.filter(call=>call.args[0]==='plain-note-service-check.mjs').length,1);
});
