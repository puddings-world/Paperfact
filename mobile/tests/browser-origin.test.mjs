import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {browserTransport,HttpTransport} from '../transport.mjs';
import {translator} from '../i18n.mjs';

test('browser facade preserves local restore but rejects cross-origin IPv6 before credentials',async()=>{
 let calls=0;const fetch=()=>{calls++;throw new Error('Unexpected credential send');};
 for(const pageOrigin of ['https://paperfact.invalid','http://127.0.0.1:8000','http://[::1]:9000']){
  const transport=browserTransport('http://[::1]:8000',{pageOrigin,fetch});assert.equal(transport.origin,'http://[::1]:8000');
  await assert.rejects(transport.session_info('synthetic'),/ipv6_same_origin_required/);
 }
 assert.equal(calls,0);
});
test('same-origin IPv6 makes the real bounded session request through injected fetch',async()=>{
 let calls=0;const transport=browserTransport('http://[::1]:8000',{pageOrigin:'http://[::1]:8000',fetch:async(url,options)=>{
  calls++;assert.equal(url,'http://[::1]:8000/v1/session/info');assert.equal(options.headers.Authorization,'Bearer synthetic');
  assert.equal(options.credentials,'omit');assert.equal(options.redirect,'error');
  return new Response(JSON.stringify({workspace_id:'fixture',device_id:'phone'}),{headers:{'content-type':'application/json'}});
 }});
 assert.deepEqual(await transport.session_info('synthetic'),{workspace_id:'fixture',device_id:'phone'});assert.equal(calls,1);
});
test('low-level IPv6, HTTPS services and IPv4 loopback retain their existing capabilities',()=>{
 assert.equal(new HttpTransport('http://[::1]:8000').origin,'http://[::1]:8000');
 for(const origin of ['https://paperfact.invalid','https://[::1]:8000','http://127.0.0.1:8000'])
  assert.equal(browserTransport(origin,{pageOrigin:'https://reader.invalid'}).origin,origin);
});
test('browser facade preserves all existing URL rejection boundaries',()=>{
 for(const origin of ['http://example.org','https://user:secret@example.org','https://example.org/path','https://example.org/?token=x','https://example.org/#secret'])
  assert.throws(()=>browserTransport(origin,{pageOrigin:'https://reader.invalid'}));
});
test('CSP stays restricted and the connection error has useful bilingual copy',()=>{
 const html=readFileSync(new URL('../index.html',import.meta.url),'utf8'),policy=html.match(/connect-src ([^;]+)/)[1];
 assert.equal(policy,"'self' https: http://127.0.0.1:*");assert(!policy.includes('[::1]'));
 for(const language of ['en','zh-TW']){const t=translator(language);assert.notEqual(t('ipv6_same_origin_required'),t('error'));assert(t('ipv6_same_origin_required').includes('127.0.0.1'));}
});
