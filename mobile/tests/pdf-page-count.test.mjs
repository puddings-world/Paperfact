import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {countPDFPages,requirePDFPageProof} from '../pdf-page-count.mjs';
import {SHELL,cacheable} from '../sw-policy.mjs';
test('parser, worker and license match independently pinned official 6.4.299 compatibility assets',()=>{
  const expected={'pdf.mjs':'630de0bd0092cf2e9d46a23c68596b736699035e08cce4e9c85537c8eba0fc8e',
    'pdf.worker.mjs':'bb422f60804477de4a0b09091d8347a916a387755ed1cbad24ccaec1d09c78bf',
    LICENSE:'0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594'};
  const provenance=JSON.parse(readFileSync(new URL('../vendor/pdfjs-6.4.299/provenance.json',import.meta.url),'utf8'));
  assert.equal(provenance.archive_sha256,'c894bce53b2f4c3e13141e088c89cc051a1f7118ba4a2c02ec058798ae1303d1');
  assert.equal(provenance.upstream_notice_present,false);
  for(const [name,sha] of Object.entries(expected)) {
    const data=readFileSync(new URL('../vendor/pdfjs-6.4.299/'+name,import.meta.url));
    assert.equal(createHash('sha256').update(data).digest('hex'),sha);
    assert.equal(provenance.files.find(file=>file.path===name).sha256,sha);
    assert(SHELL.includes('./vendor/pdfjs-6.4.299/'+name));
  }
  assert(readFileSync(new URL('../vendor/pdfjs-6.4.299/LICENSE',import.meta.url),'utf8').trimStart().startsWith('Apache License'));
});
test('shell policy never caches authenticated bytes or CDN parser/worker assets',()=>{
  const scope='https://fixture.invalid/mobile/';
  for(const name of ['pdf.mjs','pdf.worker.mjs']) {
    const url=scope+'vendor/pdfjs-6.4.299/'+name;
    assert.equal(cacheable(new Request(url),scope),true);
    assert.equal(cacheable(new Request(url,{headers:{authorization:'Bearer fixture'}}),scope),false);
  }
  assert.equal(cacheable(new Request('https://cdn.invalid/pdf.worker.mjs'),scope),false);
});
test('domain-object metadata cannot forge count authority',()=>{
  assert.throws(()=>requirePDFPageProof({sha256:'a'.repeat(64),pageCount:5},'a'.repeat(64),2),/pdf_count_required/);
});
test('unsupported sizes, cancelled input and wrong exact hash refuse before importing or creating a worker',async()=>{
  await assert.rejects(countPDFPages({bytes:new Uint8Array(),sha256:'a'.repeat(64)}),/pdf_count_size_limit/);
  const controller=new AbortController();controller.abort();
  await assert.rejects(countPDFPages({bytes:new Uint8Array([1]),sha256:'a'.repeat(64)},{signal:controller.signal}),/cancelled/);
  await assert.rejects(countPDFPages({bytes:new Uint8Array([1]),sha256:'a'.repeat(64)}),/corrupt_file/);
});
