import {ReaderView} from '../view.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {WORKSPACE_HINT_KEY,readWorkspaceHint,rememberWorkspace,forgetWorkspaceHint} from '../workspace-startup.mjs';

const connection={workspace:'my-workspace',device:'phone-1',origin:'https://sync.example.test'};
function storage(raw=null){
  const values=new Map(raw===null?[]:[[WORKSPACE_HINT_KEY,raw]]);
  return {values,getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};
}
test('remembered scope contains only its version and three connection descriptors',()=>{
  const local=storage();assert.equal(rememberWorkspace(connection,local),true);
  assert.deepEqual(JSON.parse(local.values.get(WORKSPACE_HINT_KEY)),{version:1,...connection});
  assert.deepEqual(readWorkspaceHint(local),{status:'ready',hint:{version:1,...connection}});
  assert.equal(rememberWorkspace({...connection,token:'must-not-be-stored'},local),false);
  assert(!local.values.get(WORKSPACE_HINT_KEY).includes('must-not-be-stored'));
});
test('empty scope hint differs from blocked storage and malformed data',()=>{
  assert.equal(readWorkspaceHint(storage()).status,'empty');
  assert.equal(readWorkspaceHint({getItem(){throw Error('blocked');}}).status,'unavailable');
  assert.equal(readWorkspaceHint(storage('{')).status,'invalid');
});
for(const [name,change] of [
  ['version',{version:2}],['empty-workspace',{workspace:''}],['array-device',{device:[]}],
  ['path-id',{workspace:'../another'}],['credentials',{origin:'https://user:password@example.test'}],
  ['path-origin',{origin:'https://example.test/private'}],['query',{origin:'https://example.test?token=x'}],
  ['fragment',{origin:'https://example.test#token'}],['remote-http',{origin:'http://example.test'}],
  ['file',{origin:'file:///private/db'}],['unknown-field',{token:'must-not-be-stored'}],
])test('reject malformed resume hint: '+name,()=>{
  const local=storage(JSON.stringify({version:1,...connection,...change}));
  const before=local.values.get(WORKSPACE_HINT_KEY);
  assert.deepEqual(readWorkspaceHint(local),{status:'invalid',hint:null});
  assert.equal(local.values.get(WORKSPACE_HINT_KEY),before);
});
test('oversized hint refuses without exposing content or changing storage',()=>{
  const local=storage('private'.repeat(1000));const result=readWorkspaceHint(local);
  assert.equal(result.status,'invalid');assert(!JSON.stringify(result).includes('private'));
});
test('storage write failure does not clear the last successful descriptor',()=>{
  const local=storage();rememberWorkspace(connection,local);const before=local.values.get(WORKSPACE_HINT_KEY);
  local.setItem=()=>{throw Error('quota');};
  assert.equal(rememberWorkspace({...connection,workspace:'second'},local),false);
  assert.equal(local.values.get(WORKSPACE_HINT_KEY),before);
});
test('explicit demo choice removes only the scope hint; failure is visible to the caller',()=>{
  const local=storage();rememberWorkspace(connection,local);local.values.set('research','keep');
  assert.equal(forgetWorkspaceHint(local),true);assert.equal(readWorkspaceHint(local).status,'empty');
  assert.equal(local.values.get('research'),'keep');
  assert.equal(forgetWorkspaceHint({removeItem(){throw Error('blocked');}}),false);
});
for(const origin of ['http://127.0.0.1:1234','http://[::1]:1234'])test('local literal HTTP hint supports '+origin,()=>{
  const local=storage();assert(rememberWorkspace({...connection,origin},local));
  assert.equal(readWorkspaceHint(local).hint.origin,origin);
});

test('blocked browser storage getter returns a status instead of throwing during startup',()=>{
  const previous=Object.getOwnPropertyDescriptor(globalThis,'localStorage');
  Object.defineProperty(globalThis,'localStorage',{configurable:true,get(){throw Error('blocked getter');}});
  try {
    assert.deepEqual(readWorkspaceHint(),{status:'unavailable',hint:null});
    assert.equal(rememberWorkspace(connection),false);
    assert.equal(forgetWorkspaceHint(),false);
  } finally {
    if(previous)Object.defineProperty(globalThis,'localStorage',previous);
    else delete globalThis.localStorage;
  }
});

test('resume a library paper without a selected list, then keep explicit navigation',()=>{
  const view=new ReaderView();
  view.refresh({drafts:{},selection:{list:null,paper:'library-paper'}});
  assert.equal(view.list,null);assert.equal(view.paper,'library-paper');
  view.select(null,'another-paper');
  view.refresh({drafts:{},selection:{list:'old-list',paper:'old-paper'}});
  assert.equal(view.list,null);assert.equal(view.paper,'another-paper');
  view.select(null,null);
  view.refresh({drafts:{},selection:{list:'old-list',paper:'old-paper'}});
  assert.equal(view.list,null);assert.equal(view.paper,null);
});
test('a clean initial overview is not silently navigated by a later refresh',()=>{
  const view=new ReaderView();view.refresh({drafts:{},selection:{list:null,paper:null}});
  view.refresh({drafts:{},selection:{list:'new-list',paper:'new-paper'}});
  assert.equal(view.list,null);assert.equal(view.paper,null);
});

test('explicit empty selection made before initial refresh is retained',()=>{
  const view=new ReaderView();view.select(null,null);
  view.refresh({drafts:{},selection:{list:'cached-list',paper:'cached-paper'}});
  assert.equal(view.list,null);assert.equal(view.paper,null);
});
