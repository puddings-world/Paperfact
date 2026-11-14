import test from 'node:test';
import assert from 'node:assert/strict';
import {CookieTransport,COOKIE_SESSION,HttpTransport} from '../transport.mjs';

const origin='https://sync.example.org';
const json=value=>new Response(JSON.stringify(value),{headers:{'content-type':'application/json'}});
test('cookie pairing and ordinary Engine calls never send a JavaScript bearer credential',async()=>{
  const seen=[],identity={workspace_id:'research',device_id:'phone'};
  const transport=new CookieTransport(origin,{pageOrigin:origin,fetch:async(url,options)=>{
    seen.push({url,options});
    assert.equal(options.credentials,'same-origin');
    assert.equal(options.redirect,'error');assert.equal(options.cache,'no-store');
    assert(!Object.hasOwn(options.headers,'Authorization'));
    assert(!Object.hasOwn(options.headers,'Cookie'));
    assert.equal(options.headers['X-Paperfact-Browser'],'1');
    if(!url.endsWith('/prepare') && !url.endsWith('/forget')) {
      assert.equal(options.headers['X-Paperfact-Workspace'],identity.workspace_id);
      assert.equal(options.headers['X-Paperfact-Device'],identity.device_id);
    }
    if(url.endsWith('/forget'))return json({forgotten:true});
    if(url.endsWith('/pull'))return json([]);
    return json(identity);
  }});
  const controller=new AbortController();
  assert.deepEqual(await transport.preparePairing('synthetic invitation',controller.signal),identity);
  assert.deepEqual(await transport.completePairing(controller.signal),identity);
  assert.deepEqual(await transport.session_info(COOKIE_SESSION),identity);
  assert.deepEqual(await transport.pull(COOKIE_SESSION),[]);
  assert.deepEqual(await transport.forgetSession(),{forgotten:true});
  assert.deepEqual(seen.map(row=>new URL(row.url).pathname),[
    '/v1/browser/pairing/prepare','/v1/browser/pairing/complete',
    '/v1/browser/session/info','/v1/browser/pull','/v1/browser/session/forget']);
  assert.equal(seen[0].options.signal,controller.signal);
  assert.equal(seen[0].options.body,JSON.stringify({invitation:'synthetic invitation'}));
  assert(!seen.slice(1).some(row=>row.options.body.includes('credential')));
});

test('cookie transport refuses cross-origin, real-token misuse and unsupported responses',async()=>{
  let calls=0;
  const fetch=async()=>{calls++;return json({workspace_id:'research',device_id:'phone',credential:'unexpected'});};
  assert.throws(()=>new CookieTransport(origin,{pageOrigin:'https://reader.example.org',fetch}),
    /browser_same_origin_required/);
  const transport=new CookieTransport(origin,{pageOrigin:origin,fetch});
  await assert.rejects(transport.session_info('actual-token-is-not-this-interface'),/invalid_session/);
  await assert.rejects(transport.session_info(COOKIE_SESSION),/invalid_session/);
  assert.equal(calls,0);
  await assert.rejects(transport.completePairing());assert.equal(calls,1);
  const denied=new CookieTransport(origin,{pageOrigin:origin,fetch:async()=>new Response('',{status:403})});
  await assert.rejects(denied.completePairing(),/session_denied/);
});

test('legacy bearer transport still omits cookies and cancellation stays sanitized',async()=>{
  const controller=new AbortController();controller.abort();
  const transport=new CookieTransport(origin,{pageOrigin:origin,fetch:async(_url,options)=>{
    assert.equal(options.signal,controller.signal);throw Error('private internal error');
  }});
  await assert.rejects(transport.completePairing(controller.signal),/^Error: cancelled$/);
  let called=false;
  const legacy=new HttpTransport(origin,{fetch:async(_url,options)=>{
    called=true;assert.equal(options.credentials,'omit');
    assert.equal(options.headers.Authorization,'Bearer synthetic');
    return json({workspace_id:'research',device_id:'phone'});
  }});
  await legacy.session_info('synthetic');assert(called);
});
