import test from 'node:test';
import assert from 'node:assert/strict';
import {HttpTransport} from '../transport.mjs';
const response=()=>new Response(JSON.stringify({workspace_id:'workspace',device_id:'phone'}),
  {headers:{'Content-Type':'application/json'}});
test('a fetch function is called without an invented transport receiver, with original signal and privacy headers',async()=>{
  const controller=new AbortController();let calls=0;
  async function fetchFunction(url,options) {
    assert.equal(this,undefined);calls++;assert.equal(url,'https://fixture.invalid/v1/session/info');
    assert.equal(options.signal,controller.signal);assert.equal(options.headers.Authorization,'Bearer fixture-only');
    assert.equal(options.credentials,'omit');assert.equal(options.redirect,'error');assert.equal(options.cache,'no-store');
    return response();
  }
  const transport=new HttpTransport('https://fixture.invalid',{fetch:fetchFunction});
  assert.deepEqual(await transport.session_info('fixture-only',controller.signal),{workspace_id:'workspace',device_id:'phone'});
  assert.equal(calls,1);
});
test('a prebound custom fetch adapter keeps its explicit owner',async()=>{
  const owner={calls:0,async fetch(){assert.equal(this,owner);this.calls++;return response();}};
  const transport=new HttpTransport('https://fixture.invalid',{fetch:owner.fetch.bind(owner)});
  await transport.session_info('fixture-only');assert.equal(owner.calls,1);
});
