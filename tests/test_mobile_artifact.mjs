import test from 'node:test';
import {createHash} from 'node:crypto';
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

const digest=data=>createHash('sha256').update(data).digest('hex');
async function refreshManifest(output,name,data){
 await writeFile(join(output,'public',name),data);
 const manifest=JSON.parse(await readFile(join(output,'artifact.json'),'utf8'));
 Object.assign(manifest.files.find(row=>row.path===name),{size:Buffer.byteLength(data),sha256:digest(data)});
 const {artifact_id,...payload}=manifest;
 manifest.artifact_id=digest(JSON.stringify(payload));
 await writeFile(join(output,'artifact.json'),JSON.stringify(manifest));return manifest;
}

test('exported cache follows asset and worker content without changing the source cache revision',async()=>fixture(async({root,sourceRoot,output})=>{
 const original=await readFile(join(sourceRoot,'sw.mjs'),'utf8');
 await build({sourceRoot,output});
 const first=JSON.parse(await readFile(join(output,'artifact.json'),'utf8'));
 assert.match(first.shell_cache,/^paperfact-mobile-shell-[a-f0-9]{64}$/);
 assert((await readFile(join(output,'public','sw.mjs'),'utf8')).includes("const CACHE = '"+first.shell_cache+"';"));
 assert.equal(await readFile(join(sourceRoot,'sw.mjs'),'utf8'),original);
 await writeFile(join(sourceRoot,'style.css'),'/* revised style without a cache revision edit */');
 const next=join(root,'style-change');await build({sourceRoot,output:next});
 const second=JSON.parse(await readFile(join(next,'artifact.json'),'utf8'));
 assert.notEqual(second.shell_cache,first.shell_cache);
 await writeFile(join(sourceRoot,'sw.mjs'),original+'\n// revised worker logic\n');
 const last=join(root,'worker-change');await build({sourceRoot,output:last});
 const third=JSON.parse(await readFile(join(last,'artifact.json'),'utf8'));
 assert.notEqual(third.shell_cache,second.shell_cache);
 assert.equal((await verifyMobile(last)).state,'verified');
}));

test('rehashing changed assets cannot conceal a stale derived shell identity',async()=>fixture(async({sourceRoot,output})=>{
 await build({sourceRoot,output});
 const changed=await refreshManifest(output,'style.css','/* internally rehashed but stale worker */');
 await assert.rejects(verifyMobile(output,{expectedId:changed.artifact_id}),/invalid_shell_identity/);
}));

test('legacy numeric cache artifacts remain readable but mismatched worker names are refused',async()=>fixture(async({sourceRoot,output})=>{
 await build({sourceRoot,output});
 const worker=(await readFile(join(output,'public','sw.mjs'),'utf8'))
  .replace(/const CACHE = '[^']+';/,"const CACHE = 'paperfact-mobile-shell-v34';");
 const manifest=await refreshManifest(output,'sw.mjs',worker);
 manifest.shell_cache='paperfact-mobile-shell-v34';
 const {artifact_id,...payload}=manifest;manifest.artifact_id=digest(JSON.stringify(payload));
 await writeFile(join(output,'artifact.json'),JSON.stringify(manifest));
 assert.equal((await verifyMobile(output,{expectedId:manifest.artifact_id})).state,'verified');
 await refreshManifest(output,'sw.mjs',worker.replace('shell-v34','shell-v35'));
 await assert.rejects(verifyMobile(output),/invalid_shell_identity/);
}));


test('LF and CRLF first-party checkouts produce identical artifacts without altering vendor bytes',async()=>fixture(async({root,sourceRoot,output})=>{
 const names=[...new Set([...SHELL.map(path=>path==='./'?'index.html':path.slice(2)),'sw.mjs'])];
 const firstParty=names.filter(name=>!name.startsWith('vendor/'));
 for(const name of firstParty){const path=join(sourceRoot,name);await writeFile(path,(await readFile(path,'utf8')).replace(/\r\n/g,'\n'));}
 const css=join(sourceRoot,'style.css');
 await writeFile(css,'\ufeff/* Unicode: \u96e2\u7dda \ud83d\udd2c */\n'+await readFile(css,'utf8'));
 // A synthetic CRLF vendor license verifies that vendor bytes stay opaque.
 const license='vendor/pdfjs-6.4.299/LICENSE',vendor=Buffer.from('Synthetic vendor license\r\nretain exact bytes\r\n');
 await writeFile(join(sourceRoot,license),vendor);
 const first=await build({sourceRoot,output});
 const vendorCode=await readFile(join(sourceRoot,'vendor/pdfjs-6.4.299/pdf.mjs'));
 for(const name of firstParty){const path=join(sourceRoot,name);await writeFile(path,(await readFile(path,'utf8')).replace(/\n/g,'\r\n'));}
 const sourceBefore=await Promise.all(names.map(name=>readFile(join(sourceRoot,name))));
 const again=join(root,'crlf');
 const second=await build({sourceRoot,output:again});
 assert.equal(second.artifact_id,first.artifact_id);
 for(const name of ['artifact.json','nginx-static-map.conf'])assert.deepEqual(await readFile(join(output,name)),await readFile(join(again,name)));
 for(let index=0;index<names.length;index++){
  const name=names[index];
  assert.deepEqual(await readFile(join(sourceRoot,name)),sourceBefore[index]);
  assert.deepEqual(await readFile(join(output,'public',name)),await readFile(join(again,'public',name)));
 }
 assert.deepEqual(await readFile(join(again,'public',license)),vendor);
 assert.deepEqual(await readFile(join(again,'public','vendor/pdfjs-6.4.299/pdf.mjs')),vendorCode);
 assert((await readFile(join(again,'public','style.css'))).subarray(0,3).equals(Buffer.from([0xef,0xbb,0xbf])));
 assert.equal((await verifyMobile(again,{expectedId:first.artifact_id})).state,'verified');
}));


test('invalid first-party UTF-8 fails before publishing output instead of replacing text',async()=>fixture(async({sourceRoot,output})=>{
 await writeFile(join(sourceRoot,'style.css'),Buffer.from([0x63,0x73,0x73,0xc3,0x28]));
 await assert.rejects(build({sourceRoot,output}),/invalid_asset_encoding/);
 await assert.rejects(readdir(output),error=>error.code==='ENOENT');
}));

test('newline-only edits during export remain source changes and retry uses a new destination',async()=>fixture(async({root,sourceRoot,output})=>{
 const css=join(sourceRoot,'style.css'),original='body{color:#111}\n';
 await writeFile(css,original);
 await assert.rejects(build({sourceRoot,output,onProgress:async()=>{
  await writeFile(css,original.replace(/\n/g,'\r\n'));
 }}),/source_changed/);
 await assert.rejects(readFile(join(output,'artifact.json')),error=>error.code==='ENOENT');
 assert.equal(await readFile(css,'utf8'),original.replace(/\n/g,'\r\n'));
 const retry=join(root,'retry-newlines');
 assert.equal((await build({sourceRoot,output:retry})).state,'verified');
 assert.equal(await readFile(join(retry,'public','style.css'),'utf8'),original);
}));
