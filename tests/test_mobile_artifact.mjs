import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,copyFile,writeFile,readFile,readdir,rm,link,unlink,realpath,lstat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve,dirname,relative} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {buildMobile,verifyMobile} from '../scripts/build_mobile.mjs';
import {SHELL} from '../mobile/sw-policy.mjs';
const source=fileURLToPath(new URL('../mobile/',import.meta.url));
async function fixture(run){
 const root=await mkdtemp(join(await realpath(tmpdir()),'paperfact-mobile-artifact-')),local=join(root,'source'),owned=await lstat(root);
 try{
  const paths=[...new Set([...SHELL.map(path=>path==='./'?'index.html':path.slice(2)),'sw.mjs'])];
  for(const name of paths){const target=join(local,...name.split('/'));await mkdir(dirname(target),{recursive:true});await copyFile(join(source,name),target);}
  await run({root,sourceRoot:local,output:join(root,'artifact')});
 }finally{
  // Remove only this exact test-owned allocation, never enumerate/prefix-delete TEMP.
  const actual=await realpath(root),parent=await realpath(tmpdir()),current=await lstat(root);
  assert.equal(relative(actual,resolve(root)),'');assert.equal(relative(parent,dirname(actual)),'');
  assert.equal(current.dev,owned.dev);assert.equal(current.ino,owned.ino);
  await rm(actual,{recursive:true,force:true});
 }
}
const build=options=>buildMobile({...options,version:'0.5.0.dev'});

test('actual runtime assets produce a deterministic, pinned artifact without private/test files',async()=>fixture(async({root,sourceRoot,output})=>{
 await writeFile(join(sourceRoot,'private-connection.json'),'private synthetic transport record');
 await writeFile(join(sourceRoot,'.env'),'synthetic-private-data');
 const result=await build({sourceRoot,output});assert.equal(result.state,'verified');
 assert.deepEqual((await readdir(output)).sort(),['artifact.json','nginx-static-map.conf','public']);
 const manifest=JSON.parse(await readFile(join(output,'artifact.json'),'utf8'));
 assert.equal(result.files,manifest.files.length);assert(result.files>30);
 assert(manifest.files.some(row=>row.path==='browser-pairing.mjs'));
 assert(!manifest.files.some(row=>/test|check|private|\.py$|\.env/.test(row.path)));
 const policy=await readFile(join(output,'nginx-static-map.conf'),'utf8');
 assert(policy.includes('default 0;')&&policy.includes('"/" 1;'));
 for(const row of manifest.files)assert(policy.includes('"/'+row.path+'" 1;'));
 assert(!policy.includes('private-connection.json'));
 assert.equal((await verifyMobile(output,{expectedId:result.artifact_id})).artifact_id,result.artifact_id);
 const second=await build({sourceRoot,output:join(root,'again')});assert.equal(second.artifact_id,result.artifact_id);
 assert.equal(await readFile(join(root,'again','artifact.json'),'utf8'),await readFile(join(output,'artifact.json'),'utf8'));
 const help=spawnSync(process.execPath,[fileURLToPath(new URL('../scripts/build_mobile.mjs',import.meta.url)),'--help'],{encoding:'utf8'});
 assert.equal(help.status,0);assert(help.stdout.includes('--expect SHA256'));
}));

test('existing or overlapping output refuses without replacing content; unknown deployed files fail verification',async()=>fixture(async({sourceRoot,output})=>{
 await build({sourceRoot,output});const before=await readFile(join(output,'artifact.json'));
 await assert.rejects(build({sourceRoot,output}),/existing_output/);
 assert.deepEqual(await readFile(join(output,'artifact.json')),before);
 await assert.rejects(build({sourceRoot,output:join(sourceRoot,'export')}),/overlapping_paths/);
 await assert.rejects(build({sourceRoot,output:join(sourceRoot,'..nested-artifact')}),/overlapping_paths/);
 await writeFile(join(output,'public','unexpected.sqlite'),'synthetic private data');
 await assert.rejects(verifyMobile(output),/unexpected_artifact_entry/);
 assert.equal(await readFile(join(output,'public','unexpected.sqlite'),'utf8'),'synthetic private data');
}));

test('source edits during staging leave no completion marker and a new-path retry uses the new bytes',async()=>fixture(async({root,sourceRoot,output})=>{
 await assert.rejects(build({sourceRoot,output,onProgress:async phase=>{
  assert.equal(phase.stage,'staged');await writeFile(join(sourceRoot,'style.css'),'/* changed source */');
 }}),/source_changed/);
 await assert.rejects(readFile(join(output,'artifact.json')),error=>error.code==='ENOENT');
 await assert.rejects(build({sourceRoot,output}),/existing_output/);
 const retry=await build({sourceRoot,output:join(root,'retry')});assert.equal(retry.state,'verified');
 assert.equal(await readFile(join(root,'retry','public','style.css'),'utf8'),'/* changed source */');
}));

test('corruption, forged pins and changed proxy maps are refused without repair or deletion',async()=>fixture(async({sourceRoot,output})=>{
 const result=await build({sourceRoot,output});
 await assert.rejects(verifyMobile(output,{expectedId:'0'.repeat(64)}),/unexpected_artifact/);
 const file=join(output,'public','app.mjs'),before=await readFile(file);await writeFile(file,'broken');
 await assert.rejects(verifyMobile(output,{expectedId:result.artifact_id}),/changed_asset/);
 assert.equal(await readFile(file,'utf8'),'broken');await writeFile(file,before);
 await writeFile(join(output,'nginx-static-map.conf'),'map changed');
 await assert.rejects(verifyMobile(output),/changed_proxy_map/);
}));

test('linked source files and private key records cannot become public assets',async()=>fixture(async({root,sourceRoot,output})=>{
 const external=join(root,'outside.html');await writeFile(external,'private synthetic bytes');
 await unlink(join(sourceRoot,'index.html'));await link(external,join(sourceRoot,'index.html'));
 await assert.rejects(build({sourceRoot,output}),/invalid_asset_file/);
 await unlink(join(sourceRoot,'index.html'));await copyFile(join(source,'index.html'),join(sourceRoot,'index.html'));
 await writeFile(join(sourceRoot,'vendor/pdfjs-6.4.299/provenance.json'),JSON.stringify({
  format:'paperfact.browser-signing-key.v1',key:'synthetic-placeholder-not-a-real-key'}));
 await assert.rejects(build({sourceRoot,output}),/private_json_record/);
 await assert.rejects(readdir(output),error=>error.code==='ENOENT');
}));
