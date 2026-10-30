/** Closed claim-set mirror and read-only cards. Quote location never certifies semantics. */
const enc = new TextEncoder();
const HASH = /^[0-9a-f]{64}$/;
const expect = value => { if (!value) throw new Error('unsupported_claim_set'); };
const WS = '[\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
function closed(value, fields) {
  expect(value && typeof value === 'object' && !Array.isArray(value));
  expect(Object.keys(value).length === fields.length && fields.every(key => Object.hasOwn(value, key)));
}
function text(value, maximum, nullable = false) {
  if (nullable && value === null) return;
  expect(typeof value === 'string' && [...value].length <= maximum);
  expect(value.replace(new RegExp(WS, 'g'), '').length > 0);
  expect([...value].every(char => char.codePointAt(0) < 0xd800 || char.codePointAt(0) > 0xdfff));
}
function number(value, maximum, minimum = 0) {
  expect(Number.isInteger(value) && value >= minimum && value <= maximum);
}
function digest(value) { expect(typeof value === 'string' && value.length === 64 && HASH.test(value)); }
export function normalizeClaimText(value) {
  return value.normalize('NFKC').replace(/\u00ad/g, '')
    .replace(new RegExp('-' + WS + '*\\n' + WS + '*(?=[a-z])', 'g'), '')
    .split(new RegExp(WS + '+', 'g')).filter(Boolean).join(' ');
}
const canonical = value => Array.isArray(value) ? '[' + value.map(canonical).join(',') + ']'
  : value && typeof value === 'object' ? '{' + Object.keys(value).sort().map(key =>
    JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}' : JSON.stringify(value);
// Synchronous bounded hashing is required by the existing receive/validation contract.
// Inputs here contain only closed ASCII object keys, strings, booleans and bounded integers.
export function claimHash(value) {
  const input = enc.encode(canonical(value));
  expect(input.length <= 220 * 1024);
  const size = Math.ceil((input.length + 9) / 64) * 64, bytes = new Uint8Array(size);
  bytes.set(input); bytes[input.length] = 128;
  const view = new DataView(bytes.buffer);
  view.setUint32(size - 4, input.length * 8);
  const k = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
  const h = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
  const r = (x,n) => (x >>> n) | (x << (32-n)), words = new Int32Array(64);
  for (let offset = 0; offset < size; offset += 64) {
    for (let i=0;i<16;i++) words[i] = view.getInt32(offset + i*4);
    for (let i=16;i<64;i++) {
      const a=words[i-15], b=words[i-2];
      words[i]=(words[i-16] + (r(a,7)^r(a,18)^(a>>>3)) + words[i-7] + (r(b,17)^r(b,19)^(b>>>10)))|0;
    }
    let [a,b,c,d,e,f,g,j]=h;
    for (let i=0;i<64;i++) {
      const t1=(j+(r(e,6)^r(e,11)^r(e,25))+((e&f)^(~e&g))+k[i]+words[i])|0;
      const t2=((r(a,2)^r(a,13)^r(a,22))+((a&b)^(a&c)^(b&c)))|0;
      j=g; g=f; f=e; e=(d+t1)|0; d=c; c=b; b=a; a=(t1+t2)|0;
    }
    [a,b,c,d,e,f,g,j].forEach((word,i) => { h[i]=(h[i]+word)|0; });
  }
  return h.map(word => (word>>>0).toString(16).padStart(8,'0')).join('');
}
function anchor(value, pages) {
  closed(value, ['p0','o0','p1','o1']);
  for (const key of ['p0','p1']) number(value[key], pages-1);
  for (const key of ['o0','o1']) number(value[key], 19999);
  expect(value.p1 > value.p0 || (value.p1 === value.p0 && value.o1 >= value.o0));
}
function location(value, pages) {
  closed(value, ['state','reason','anchor','page','candidates','truncated']);
  const states = {located:[null], missing:['quote_not_found'], ambiguous:['multiple_quote_locations'],
    invalid_page:['page_out_of_range'], invalid_anchor:['anchor_out_of_range_or_page_mismatch','anchor_does_not_bound_unique_quote']};
  expect(typeof value.state === 'string' && Object.hasOwn(states,value.state) && states[value.state].includes(value.reason));
  expect(typeof value.truncated === 'boolean' && Array.isArray(value.candidates) && value.candidates.length <= 8);
  value.candidates.forEach(item => anchor(item,pages));
  if (value.state === 'located') {
    anchor(value.anchor,pages);
    expect(Number.isInteger(value.page) && value.page === value.anchor.p0+1 && !value.candidates.length && !value.truncated);
  } else expect(value.anchor === null && value.page === null);
  if (value.state === 'ambiguous') expect(value.candidates.length >= (value.truncated ? 1 : 2));
  else expect(!value.candidates.length && !value.truncated);
}
function citation(value) {
  closed(value,['state','reason','proposed']);
  if (value.proposed === null) { expect(value.state === 'not_requested' && value.reason === null); return; }
  closed(value.proposed,['paper_id','doi','title']);
  expect(Object.values(value.proposed).some(Boolean));
  Object.values(value.proposed).forEach(item => text(item,1000,true));
  expect(value.state === 'unresolved' && value.reason === 'no_trusted_citation_mapping');
}
export function validateClaims(body, documentHash) {
  closed(body,['format','recipe','inputs','generation','report']);
  expect(body.format === 'paperfact.claim-set.v1' && body.recipe === 'claim-extraction.v1');
  closed(body.inputs,['dive','close_reading']); Object.values(body.inputs).forEach(digest);
  const metadata = body.generation;
  closed(metadata,['task','backend','requested_model','returned_model']);
  expect(metadata.task === 'claims'); text(metadata.backend,64);
  text(metadata.requested_model,512,true); text(metadata.returned_model,512,true);
  const report = body.report;
  closed(report,['format','source','normalization','page_count','claims','id','verification_scope']);
  expect(report.format === 'paperfact.claim-evidence.report.v1' &&
    report.normalization === 'nfkc-whitespace-soft-hyphen-wrap.v1' && report.verification_scope === 'original_snapshot');
  closed(report.source,['paper_id','document_hash']); text(report.source.paper_id,512); digest(report.source.document_hash);
  if (arguments.length > 1) { digest(documentHash); expect(documentHash === report.source.document_hash); }
  number(report.page_count,500,1);
  expect(Array.isArray(report.claims) && report.claims.length <= 16);
  const claims = new Set(); let count=0;
  for (const claim of report.claims) {
    closed(claim,['id','text','atomicity','judgment','semantic_validation','passages']);
    text(claim.text,2000); digest(claim.id);
    expect(!claims.has(claim.id) && claim.id === claimHash(['claim',report.source,normalizeClaimText(claim.text)]));
    claims.add(claim.id);
    expect(claim.atomicity === 'caller_supplied' && claim.semantic_validation === 'not_performed');
    closed(claim.judgment,['status','reason','authority']);
    expect(['supported','inferred','unresolved'].includes(claim.judgment.status) && claim.judgment.authority === 'caller');
    text(claim.judgment.reason,2000);
    expect(Array.isArray(claim.passages)); count += claim.passages.length; expect(count <= 48);
    const passages = new Set(), anchors = new Set();
    for (const passage of claim.passages) {
      closed(passage,['id','proposal_id','quote','location','citation_identity']);
      digest(passage.id); digest(passage.proposal_id); text(passage.quote,4000);
      expect(!passages.has(passage.id)); passages.add(passage.id);
      location(passage.location,report.page_count); citation(passage.citation_identity);
      if (passage.location.state === 'located') {
        const point = passage.location.anchor, key = claimHash(point);
        expect(passage.id === claimHash(['located-passage',report.source,normalizeClaimText(passage.quote),point]) && !anchors.has(key));
        anchors.add(key);
      } else expect(passage.id === passage.proposal_id);
    }
  }
  digest(report.id);
  expect(report.id === claimHash(Object.fromEntries(Object.entries(report).filter(([key]) => key !== 'id'))));
  expect(enc.encode(JSON.stringify(body)).length <= 220*1024);
  return body;
}
export function renderClaimSet(panel, row, el, t) {
  expect(row.source_document_hash === row.data.document_hash);
  const body = validateClaims(row.data.body_json,row.data.document_hash);
  const card = el('article',{class:'card claim-set prose'},el('h2',{},t('research_claims')),
    el('p',{class:'muted'},t('claimSnapshotScope')),
    el('p',{class:'muted'},t('claimNoSemanticValidation')));
  if (!body.report.claims.length) card.append(el('p',{},t('claimEmpty')));
  for (const claim of body.report.claims) {
    const section = el('section',{},el('h3',{},claim.text),
      el('p',{},t('claimJudgment_'+claim.judgment.status)),el('p',{},claim.judgment.reason));
    if (!claim.passages.length) section.append(el('p',{class:'muted'},t('claimNoPassages')));
    for (const passage of claim.passages) {
      section.append(el('blockquote',{},passage.quote));
      const located = passage.location;
      section.append(el('p',{class:'muted'},t('claimLocation_'+located.state) +
        (located.state === 'located' ? ' · '+t('annotationPage')+' '+located.page : '')));
      if (passage.citation_identity.state === 'unresolved') section.append(
        el('p',{class:'muted'},t('claimCitationUnresolved')));
    }
    card.append(section);
  }
  panel.append(card);
}
