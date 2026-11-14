/** Versioned, allowlisted PWA assets; no bundler, install, network or deployment. */
import {createHash} from 'node:crypto';
import {lstat,realpath,open,mkdir,readdir,readFile} from 'node:fs/promises';
import {resolve,dirname,relative,isAbsolute,join,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {SHELL} from '../mobile/sw-policy.mjs';

const SOURCE=fileURLToPath(new URL('../mobile/',import.meta.url));
const VERSION=fileURLToPath(new URL('../src/paper_daily/__init__.py',import.meta.url));
const FORMAT='paperfact.mobile-artifact.v1',MAX_FILE=16*1024**2,MAX_TOTAL=64*1024**2,MAX_FILES=256;
const HASH=/^[a-f0-9]{64}$/,sort=(a,b)=>a<b?-1:a>b?1:0;
const fail=code=>{throw Error(code);},hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const closed=(value,keys)=>{if(!value||Array.isArray(value)||typeof value!=='object'||
 Object.keys(value).length!==keys.length||!keys.every(key=>Object.hasOwn(value,key)))fail('invalid_manifest');};
function assetPath(value){
 if(typeof value!=='string'||value.length>256||!value||
  !/^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/.test(value))fail('invalid_asset_path');
 const parts=value.split('/');
 if(parts.some(part=>part.startsWith('.')||part.endsWith('.')||/^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part))||
  parts.some(part=>['tests','test','node_modules','data','sync-service'].includes(part.toLowerCase()))||
  /-(?:test|check|fixture)\./.test(value))fail('private_asset_path');
 if(!/\.(?:html|css|mjs|json|webmanifest|svg)$/.test(value)&&parts.at(-1)!=='LICENSE')fail('invalid_asset_type');
 return value;
}
const within=(root,path)=>{const child=relative(root,path);return child===''||(child!=='..'&&!child.startsWith('..'+sep)&&!isAbsolute(child));};
async function noLinks(path,{missing=false}={}){
 path=resolve(path);let parent=path;
 while(true){
  try{const info=await lstat(parent);if(info.isSymbolicLink())fail('linked_path');}
  catch(error){if(!missing||error.code!=='ENOENT')throw error;}
  const next=dirname(parent);if(next===parent)break;parent=next;
 }
 return path;
}
const same=(a,b)=>a.dev===b.dev&&a.ino===b.ino&&a.size===b.size&&a.mtimeMs===b.mtimeMs&&a.nlink===b.nlink;
async function bytes(root,name,limit=MAX_FILE){
 const path=join(root,...name.split('/'));await noLinks(path);
 if(!within(root,await realpath(path)))fail('escaped_path');
 const before=await lstat(path);
 if(!before.isFile()||before.nlink!==1||before.size>limit)fail('invalid_asset_file');
 const handle=await open(path,'r');
 try{
  const first=await handle.stat();if(!same(before,first))fail('changed_asset');
  const data=Buffer.alloc(first.size+1);let bytesRead=0;
  while(bytesRead<data.length){const part=await handle.read(data,bytesRead,data.length-bytesRead,bytesRead);
   if(part.bytesRead===0)break;bytesRead+=part.bytesRead;}
  const after=await handle.stat();
  if(bytesRead!==first.size||!same(first,after)||!same(after,await lstat(path)))fail('changed_asset');
  return data.subarray(0,bytesRead);
 }finally{await handle.close();}
}
function privateRecord(name,data){
 if(!/\.(?:json|webmanifest)$/.test(name))return;
 let value;try{value=JSON.parse(data.toString('utf8'));}catch{fail('invalid_public_json');}
 if(value?.format==='paperfact.browser-signing-key.v1'||
  (value?.format===1&&typeof value.token==='string')||value?.installed?.client_secret||value?.web?.client_secret)
  fail('private_json_record');
}
function paths(){
 const names=SHELL.map(name=>name==='./'?'index.html':assetPath(name.startsWith('./')?name.slice(2):''));
 names.push('sw.mjs');const unique=[...new Set(names)].sort(sort);
 if(unique.length>MAX_FILES||new Set(unique.map(name=>name.toLowerCase())).size!==unique.length)fail('asset_limit');
 return unique;
}
function mapFor(files){
 return '# Generated public-asset allowlist; include in the nginx http context.\n'+
  'map $uri $paperfact_static_allowed {\n    default 0;\n    "/" 1;\n'+
  files.map(row=>'    "/'+row.path+'" 1;').join('\n')+'\n}\n';
}
async function write(path,data){
 await noLinks(dirname(path));const handle=await open(path,'wx',0o644);
 try{await handle.writeFile(data);await handle.sync();}finally{await handle.close();}
}
function validateManifest(value){
 closed(value,['format','version','shell_cache','files','nginx_map_sha256','artifact_id']);
 if(value.format!==FORMAT||typeof value.version!=='string'||value.version.length>64||!/^\d+\.\d+\.\d+(?:[.-][A-Za-z0-9.-]+)?$/.test(value.version)||
  typeof value.shell_cache!=='string'||!/^paperfact-mobile-shell-v\d+$/.test(value.shell_cache)||
  !HASH.test(value.nginx_map_sha256)||!HASH.test(value.artifact_id)||!Array.isArray(value.files)||
  !value.files.length||value.files.length>MAX_FILES)fail('invalid_manifest');
 let previous='',total=0;const folded=new Set();
 for(const row of value.files){closed(row,['path','size','sha256']);assetPath(row.path);
  if(sort(previous,row.path)>=0||folded.has(row.path.toLowerCase())||!Number.isSafeInteger(row.size)||
   row.size<0||row.size>MAX_FILE||!HASH.test(row.sha256))fail('invalid_manifest');
  folded.add(row.path.toLowerCase());previous=row.path;total+=row.size;
 }
 if(total>MAX_TOTAL)fail('asset_limit');
 const {artifact_id,...payload}=value;
 if(hash(JSON.stringify(payload))!==artifact_id||hash(mapFor(value.files))!==value.nginx_map_sha256)fail('invalid_manifest_digest');
 return value;
}
async function inventory(root){
 const found=[];let visited=0;
 async function visit(path,prefix='',depth=0){
  if(depth>8)fail('asset_limit');
  for(const entry of await readdir(path,{withFileTypes:true})){
   if(++visited>MAX_FILES*3)fail('asset_limit');
   const name=prefix+entry.name,full=join(path,entry.name);await noLinks(full);
   if(entry.isDirectory())await visit(full,name+'/',depth+1);
   else if(entry.isFile())found.push(name);else fail('invalid_asset_file');
  }
 }
 await visit(root);return found.sort(sort);
}
export async function verifyMobile(directory,{expectedId=null}={}){
 const root=await noLinks(directory);
 const manifest=validateManifest(JSON.parse((await bytes(root,'artifact.json',256*1024)).toString('utf8')));
 if(expectedId!==null&&(!HASH.test(expectedId)||manifest.artifact_id!==expectedId))fail('unexpected_artifact');
 const expected=['artifact.json','nginx-static-map.conf',...manifest.files.map(row=>'public/'+row.path)].sort(sort);
 const actual=await inventory(root);
 if(JSON.stringify(actual)!==JSON.stringify(expected))fail('unexpected_artifact_entry');
 if(hash(await bytes(root,'nginx-static-map.conf',256*1024))!==manifest.nginx_map_sha256)fail('changed_proxy_map');
 for(const row of manifest.files){
  const data=await bytes(join(root,'public'),row.path);privateRecord(row.path,data);
  if(data.length!==row.size||hash(data)!==row.sha256)fail('changed_asset');
 }
 return {state:'verified',directory:root,version:manifest.version,artifact_id:manifest.artifact_id,
  files:manifest.files.length,bytes:manifest.files.reduce((n,row)=>n+row.size,0)};
}
export async function buildMobile({output,sourceRoot=SOURCE,version=null,onProgress=()=>{}}={}){
 if(typeof output!=='string'||!output)fail('output_required');
 const source=await noLinks(sourceRoot),destination=await noLinks(output,{missing:true});
 if(within(source,destination)||within(destination,source))fail('overlapping_paths');
 try{await lstat(destination);fail('existing_output');}catch(error){if(error.code!=='ENOENT')throw error;}
 version??=(await readFile(VERSION,'utf8')).match(/^__version__ = "([^"]+)"$/m)?.[1];
 const staged=[],files=[];let total=0;
 for(const name of paths()){
  const data=await bytes(source,name);privateRecord(name,data);total+=data.length;if(total>MAX_TOTAL)fail('asset_limit');
  staged.push({name,data});files.push({path:name,size:data.length,sha256:hash(data)});
 }
 const shell=staged.find(row=>row.name==='sw.mjs').data.toString('utf8').match(/const CACHE = '(paperfact-mobile-shell-v\d+)';/)?.[1];
 const map=mapFor(files),payload={format:FORMAT,version,shell_cache:shell,files,nginx_map_sha256:hash(map)},
  manifest={...payload,artifact_id:hash(JSON.stringify(payload))};validateManifest(manifest);
 await mkdir(dirname(destination),{recursive:true});await noLinks(dirname(destination));
 await mkdir(destination);await mkdir(join(destination,'public'));
 for(const row of staged){
  const target=join(destination,'public',...row.name.split('/'));await mkdir(dirname(target),{recursive:true});
  await write(target,row.data);
 }
 await write(join(destination,'nginx-static-map.conf'),map);
 await onProgress({stage:'staged',completed:files.length,total:files.length});
 // Confirm the source did not change during export before publishing completion.
 for(const row of files)if(hash(await bytes(source,row.path))!==row.sha256)fail('source_changed');
 await write(join(destination,'artifact.json'),JSON.stringify(manifest,null,2)+'\n');
 return verifyMobile(destination,{expectedId:manifest.artifact_id});
}
export async function main(args=process.argv.slice(2)){
 if(args.length===1&&args[0]==='--help'){
  console.log('node scripts/build_mobile.mjs --output NEW_DIRECTORY\nnode scripts/build_mobile.mjs --verify DIRECTORY [--expect SHA256]');return 0;
 }
 try{
  const options={};for(let i=0;i<args.length;i+=2){
   if(!['--output','--verify','--expect'].includes(args[i])||Object.hasOwn(options,args[i])||!args[i+1]||args[i+1].startsWith('--'))fail('invalid_options');
   options[args[i]]=args[i+1];
  }
  if(Boolean(options['--output'])===Boolean(options['--verify'])||options['--expect']&&!options['--verify'])fail('invalid_options');
  const result=options['--output']?await buildMobile({output:options['--output']}):
   await verifyMobile(options['--verify'],{expectedId:options['--expect']??null});
  console.log(JSON.stringify(result));return 0;
 }catch(error){console.error('Mobile artifact failed: '+(/^[a-z_]+$/.test(error.message)?error.message:'invalid_or_unavailable_files'));return 2;}
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))process.exitCode=await main();
