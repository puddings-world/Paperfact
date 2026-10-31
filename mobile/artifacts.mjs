/** Closed portable deck manifests and byte validation. No paths, HTML or network. */
import {uuid5Name, asciiJSON} from './ids.mjs';
import {validateLegacyManifest} from './legacy-workflow.mjs';
const enc = new TextEncoder();
const HASH = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ID = /^[A-Za-z0-9_.:-]{1,128}$/;
export const MAX_BODY = 8 * 1024 ** 2;
export const MAX_ORIGINAL_PDF = 150 * 1024 ** 2;
const KINDS = ['paper','list','membership','note','reading_state','paper_document',
  'research_content','research_file','list_order','workspace_list_order'];
export function requireArtifact(value, code = 'invalid_artifact') {
  if (!value) throw new Error(code);
}
function closed(value, fields, optional = []) {
  requireArtifact(value && typeof value === 'object' && !Array.isArray(value));
  requireArtifact(fields.every(k => Object.hasOwn(value,k)) &&
    Object.keys(value).every(k => [...fields,...optional].includes(k)));
}
function text(value, max, empty = false, characters = false) {
  requireArtifact(typeof value === 'string' && (characters ? [...value].length : enc.encode(value).length) <= max &&
    (empty || value.trim()));
}
function id(value) { requireArtifact(typeof value === 'string' && ID.test(value)); }
function uuid(value) { requireArtifact(typeof value === 'string' && UUID.test(value)); }
function hash(value, nullable = false) {
  requireArtifact((nullable && value === null) || (typeof value === 'string' && HASH.test(value)));
}
function integer(value,max = Number.MAX_SAFE_INTEGER,min = 0) {
  requireArtifact(Number.isSafeInteger(value) && value >= min && value <= max);
}
function array(value,max,min = 0) {
  requireArtifact(Array.isArray(value) && value.length >= min && value.length <= max);
}
export const fileId = (paper,slot) => uuid5Name('paperfact:research-file:' + asciiJSON([paper,'deck',slot]));
export const sourceFileId = (paper,sha) => uuid5Name('paperfact:research-file:' + asciiJSON([paper,'original_source',sha]));
export function validateInputVersions(value) {
  closed(value,['schema_version','complete','entities','documents','inputs_sha256']);
  requireArtifact(value.schema_version === 1 && typeof value.complete === 'boolean');
  hash(value.inputs_sha256,true);
  array(value.entities,256); array(value.documents,128);
  const seen = new Set();
  for (const row of value.entities) {
    closed(row,['kind','id','incarnation','revision','depends_on']);
    requireArtifact(KINDS.includes(row.kind)); id(row.id); id(row.incarnation); integer(row.revision);
    if (!['list','note','list_order','workspace_list_order'].includes(row.kind)) uuid(row.id);
    if (row.kind === 'workspace_list_order') requireArtifact(row.id === 'workspace-lists');
    if (row.depends_on !== null) id(row.depends_on);
    const key = row.kind + '/' + row.id;
    requireArtifact(!seen.has(key)); seen.add(key);
  }
  seen.clear();
  for (const row of value.documents) {
    closed(row,['paper_id','operation_id','incarnation','parent_incarnation','sha256']);
    uuid(row.paper_id); id(row.operation_id); id(row.incarnation); id(row.parent_incarnation); hash(row.sha256);
    requireArtifact(!seen.has(row.paper_id)); seen.add(row.paper_id);
  }
  requireArtifact(enc.encode(JSON.stringify(value)).length <= 64 * 1024);
}
export function validateArtifact(payload, entityId, parents) {
  closed(payload,['paper_id','feature','slot','format_version','source_document_hash','input_versions','body','assets']);
  uuid(payload.paper_id);
  if(payload.feature==='legacy_brief') {
    validateInputVersions(payload.input_versions);
    return validateLegacyManifest(payload,entityId,parents);
  }
  if (payload.feature === 'original_source') {
    requireArtifact(payload.format_version === 1);
    hash(payload.slot); requireArtifact(payload.source_document_hash === payload.slot);
    requireArtifact(entityId === sourceFileId(payload.paper_id,payload.slot));
    if (parents) requireArtifact(parents.length === 1 && parents[0].kind === 'paper' && parents[0].id === payload.paper_id);
    validateInputVersions(payload.input_versions);
    const versions = payload.input_versions;
    requireArtifact(versions.complete === false && versions.entities.length === 0 &&
      versions.documents.length === 0 && versions.inputs_sha256 === null);
    closed(payload.body,['sha256','size','media_type']);
    hash(payload.body.sha256); integer(payload.body.size,1024,1);
    requireArtifact(payload.body.media_type === 'application/json');
    array(payload.assets,1,1);
    const pdf = payload.assets[0];
    closed(pdf,['id','role','sha256','size','media_type']);
    requireArtifact(pdf.id === 'original' && pdf.role === 'original_pdf' &&
      pdf.sha256 === payload.slot && pdf.media_type === 'application/pdf');
    integer(pdf.size,MAX_ORIGINAL_PDF,1);
    return payload;
  }
  requireArtifact(payload.feature === 'deck' && ['notes','guide'].includes(payload.slot) && payload.format_version === 1);
  requireArtifact(entityId === fileId(payload.paper_id,payload.slot));
  if (parents) requireArtifact(parents.length === 1 && parents[0].kind === 'paper' && parents[0].id === payload.paper_id);
  hash(payload.source_document_hash,true); validateInputVersions(payload.input_versions);
  closed(payload.body,['sha256','size','media_type']); array(payload.assets,256);
  const ids = new Set(), hashes = new Map(); let total = 0;
  for (const row of [payload.body,...payload.assets]) {
    let media = 'application/json', limit = MAX_BODY;
    if (row !== payload.body) {
      closed(row,['id','role','sha256','size','media_type']); text(row.id,250);
      requireArtifact(!ids.has(row.id)); ids.add(row.id);
      requireArtifact(['figure','evidence','source_text'].includes(row.role));
      media = {figure:'image/png',evidence:'application/json',source_text:'text/plain'}[row.role];
      limit = row.role === 'figure' ? 8_000_000 : MAX_BODY;
      total += row.size;
    }
    hash(row.sha256); integer(row.size,limit,1); requireArtifact(row.media_type === media);
    const signature = row.size + '/' + row.media_type;
    requireArtifact(!hashes.has(row.sha256) || hashes.get(row.sha256) === signature);
    hashes.set(row.sha256,signature);
  }
  requireArtifact(total <= 64 * 1024 ** 2);
  return payload;
}

/** Canonical JSON grammar without duplicate keys, preserving Python float lexemes. */
export function artifactJSON(bytes) {
  requireArtifact(bytes instanceof Uint8Array && bytes.length <= MAX_BODY);
  const source = new TextDecoder('utf-8',{fatal:true}).decode(bytes); let at = 0;
  const compare = (a,b) => {
    const aa = [...a].map(c => c.codePointAt(0)), bb = [...b].map(c => c.codePointAt(0));
    for (let i=0;i<Math.min(aa.length,bb.length);i++) if (aa[i] !== bb[i]) return aa[i]-bb[i];
    return aa.length-bb.length;
  };
  const string = () => {
    const start = at++;
    while (at < source.length) {
      const c = source[at++];
      if (c === '\\') { at++; continue; }
      if (c === '"') {
        const raw = source.slice(start,at), value = JSON.parse(raw);
        requireArtifact(JSON.stringify(value) === raw);
        return value;
      }
    }
    throw new Error('invalid_artifact');
  };
  const parse = depth => {
    requireArtifact(depth <= 32 && at < source.length);
    const c = source[at];
    if (c === '"') return string();
    if (c === '[') {
      at++; const result = [];
      if (source[at] !== ']') while (true) {
        result.push(parse(depth+1));
        if (source[at] !== ',') break; at++;
      }
      requireArtifact(source[at++] === ']'); return result;
    }
    if (c === '{') {
      at++; const result = Object.create(null); let previous = null;
      if (source[at] !== '}') while (true) {
        requireArtifact(source[at] === '"'); const key = string();
        requireArtifact(previous === null || compare(previous,key) < 0); previous = key;
        requireArtifact(source[at++] === ':'); result[key] = parse(depth+1);
        if (source[at] !== ',') break; at++;
      }
      requireArtifact(source[at++] === '}'); return result;
    }
    for (const [word,value] of [['true',true],['false',false],['null',null]]) {
      if (source.startsWith(word,at)) { at += word.length; return value; }
    }
    const number = source.slice(at).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
    requireArtifact(number && Number.isFinite(Number(number[0]))); at += number[0].length;
    return Number(number[0]);
  };
  const value = parse(0); requireArtifact(at === source.length); return value;
}

/** Original-source proof is byte integrity/format scope, not a PDF readability verdict. */
export function validateOriginalSource(bytes,payload) {
  requireArtifact(payload.feature === 'original_source' && bytes instanceof Uint8Array && bytes.length <= 1024);
  const body = artifactJSON(bytes);
  closed(body,['version','paper_id','document_hash']);
  requireArtifact(body.version === 1 && body.paper_id === payload.paper_id &&
    body.document_hash === payload.slot && body.document_hash === payload.source_document_hash);
  // This closed body has integers/ASCII only; preserve the reference's integer type boundary.
  requireArtifact(new TextDecoder('utf-8',{fatal:true}).decode(bytes) === JSON.stringify(body));
  return body;
}
export function validateOriginalPDF(bytes) {
  requireArtifact(bytes instanceof Uint8Array && bytes.length > 0 && bytes.length <= MAX_ORIGINAL_PDF,'invalid_pdf');
  requireArtifact(new TextDecoder().decode(bytes.subarray(0,5)) === '%PDF-' &&
    new TextDecoder().decode(bytes.subarray(-1024)).includes('%%EOF'),'invalid_pdf');
}

function sourceRow(row, figure = false) {
  closed(row, figure ? ['id','label','asset_id'] : ['id','label','kind'],
    figure ? ['caption','page','document_hash'] : ['page','url','document_hash','text']);
  for (const [key,max] of [['id',250],['label',2000],['kind',30],['caption',10000],['text',200*1024],['asset_id',250]])
    if (Object.hasOwn(row,key)) text(row[key],max,['caption','text'].includes(key));
  if (row.page != null) integer(row.page,1_000_001,1);
  hash(row.document_hash ?? null,true);
  if (row.url != null) {
    text(row.url,4096); requireArtifact(/^https?:\/\//.test(row.url));
    const url = new URL(row.url); requireArtifact(url.hostname && !url.username && !url.password);
  }
}
function elements(value, figures, refs) {
  if (value === null) return [];
  array(value,60); const used = [];
  for (const row of value) {
    requireArtifact(['text','figure','table'].includes(row?.kind));
    closed(row,['kind','x','y','w','h'], [...({text:['text','size','color','bold','align'],figure:['figure'],table:['rows','size','header']}[row.kind]),'role']);
    for (const [key,max] of [['x',1200],['w',1200],['y',675],['h',675]])
      requireArtifact(typeof row[key] === 'number' && Number.isFinite(row[key]) && row[key] >= 0 && row[key] <= max);
    requireArtifact(row.w >= 20 && row.h >= 12 && row.x+row.w <= 1201 && row.y+row.h <= 676);
    if ('role' in row) requireArtifact(['title','section','takeaway','bullets'].includes(row.role));
    for (const field of ['bold','header']) if (field in row) requireArtifact(typeof row[field] === 'boolean');
    if (row.kind === 'figure') {
      requireArtifact(figures.has(row.figure) && refs.includes(row.figure)); used.push(row.figure);
    } else {
      const size = row.size ?? (row.kind === 'table' ? 18 : 26);
      requireArtifact(typeof size === 'number' && Number.isFinite(size) && size >= 10 && size <= 96);
      if (row.kind === 'text') {
        text(row.text ?? '',12000,true,true);
        requireArtifact(/^#[0-9a-fA-F]{6}$/.test(row.color ?? '#172238'));
        requireArtifact(['left','center','right'].includes(row.align ?? 'left'));
      } else {
        array(row.rows,30,1); array(row.rows[0],12,1);
        for (const cells of row.rows) {
          requireArtifact(Array.isArray(cells) && cells.length === row.rows[0].length);
          cells.forEach(cell => text(cell,200,true,true));
        }
      }
    }
  }
  return used;
}
export function validateDeck(body,payload) {
  closed(body,['version','deck','evidence_asset']); requireArtifact(body.version === 1);
  const deck = body.deck;
  closed(deck,['paper_id','paper_title','title','mode','audience','minutes','slides','sources','figures','coverage','created_at','deck_id','source_hash','generation','edited','version']);
  requireArtifact(deck.paper_id === payload.paper_id && deck.mode === payload.slot && deck.version === 1 && typeof deck.edited === 'boolean');
  integer(deck.minutes,120,1);
  for (const [key,max] of [['paper_title',2000],['title',200],['audience',500],['created_at',100],['deck_id',100],['source_hash',100]])
    text(deck[key],max,['audience','source_hash'].includes(key),true);
  for (const key of ['sources','figures','coverage']) array(deck[key],1000);
  deck.sources.forEach(row => sourceRow(row)); deck.figures.forEach(row => sourceRow(row,true));
  deck.coverage.forEach(value => text(value,4000,true));
  closed(deck.generation,[],['inputs','backend','model']);
  if ('inputs' in deck.generation) { array(deck.generation.inputs,30); deck.generation.inputs.forEach(v => text(v,100)); }
  for (const key of ['backend','model']) if (key in deck.generation) text(deck.generation[key],200,true);
  const sources = new Set(deck.sources.map(row => row.id)), figures = new Set(deck.figures.map(row => row.id)), used = new Set();
  requireArtifact(sources.size === deck.sources.length && figures.size === deck.figures.length);
  array(deck.slides,24,1);
  for (const slide of deck.slides) {
    closed(slide,['title','section','takeaway','bullets','speaker_notes','sources','figure','elements']);
    for (const [key,max] of [['title',70],['section',100],['takeaway',160],['speaker_notes',6000]]) text(slide[key],max,key !== 'title',true);
    requireArtifact(slide.figure === null || figures.has(slide.figure));
    array(slide.bullets,slide.figure ? 3 : 5,1); slide.bullets.forEach(v => text(v,120,false,true));
    requireArtifact(slide.bullets.reduce((n,v)=>n+[...v].length,0) <= (slide.figure ? 220 : 420));
    array(slide.sources,8,1); requireArtifact(slide.sources.every(id => sources.has(id)));
    if (slide.figure) requireArtifact(slide.sources.includes(slide.figure));
    elements(slide.elements,figures,slide.sources).forEach(id => used.add(id));
    if (slide.elements === null && slide.figure) used.add(slide.figure);
  }
  requireArtifact(used.size === figures.size && [...used].every(id => figures.has(id)));
  const declared = new Map(payload.assets.map(asset=>[asset.id,asset])), refs = new Set();
  for (const figure of deck.figures) {
    requireArtifact(declared.get(figure.asset_id)?.role === 'figure'); refs.add(figure.asset_id);
  }
  if (body.evidence_asset !== null) {
    requireArtifact(typeof body.evidence_asset === 'string' && declared.get(body.evidence_asset)?.role === 'evidence'); refs.add(body.evidence_asset);
  }
  requireArtifact(refs.size === declared.size && [...refs].every(id=>declared.has(id)));
  return body;
}
export function validateEvidence(value) {
  closed(value,['version','sources','coverage','source_hash']); requireArtifact(value.version === 1);
  array(value.sources,1000); value.sources.forEach(row=>sourceRow(row));
  array(value.coverage,1000); value.coverage.forEach(v=>text(v,4000,true)); text(value.source_hash,100,true);
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit=0;bit<8;bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
export async function validatePNG(bytes) {
  requireArtifact(bytes instanceof Uint8Array && bytes.length >= 33 && bytes.length <= 8_000_000);
  requireArtifact([137,80,78,71,13,10,26,10].every((value,i)=>bytes[i] === value));
  const data = new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  let at=8, ended=false, width=0,height=0,depth=0,color=0,interlace=0, hasPalette=false;
  const compressed=[];
  while (at<bytes.length) {
    requireArtifact(at+12 <= bytes.length);
    const size=data.getUint32(at), end=at+12+size;
    requireArtifact(end <= bytes.length);
    const kind=String.fromCharCode(...bytes.subarray(at+4,at+8));
    requireArtifact(/^[A-Za-z]{4}$/.test(kind));
    requireArtifact(crc32(bytes.subarray(at+4,end-4)) === data.getUint32(end-4));
    if (at === 8) requireArtifact(kind === 'IHDR' && size === 13);
    if (kind === 'IHDR') {
      requireArtifact(at === 8 && size === 13);
      width=data.getUint32(at+8); height=data.getUint32(at+12);
      depth=bytes[at+16]; color=bytes[at+17]; interlace=bytes[at+20];
      requireArtifact(width>0 && height>0 && width<=16384 && height<=16384 && width*height<=40_000_000);
      requireArtifact(({0:[1,2,4,8,16],2:[8,16],3:[1,2,4,8],4:[8,16],6:[8,16]})[color]?.includes(depth));
      requireArtifact(bytes[at+18] === 0 && bytes[at+19] === 0 && [0,1].includes(interlace));
    } else if (kind === 'IDAT') compressed.push(bytes.subarray(at+8,end-4));
    else if (kind === 'PLTE') { requireArtifact(size>0 && size<=768 && size%3===0); hasPalette=true; }
    else if (kind === 'IEND') { requireArtifact(size === 0 && end === bytes.length); ended=true; }
    else requireArtifact(kind[0] === kind[0].toLowerCase(), 'unsupported_png');
    at=end;
  }
  requireArtifact(ended && compressed.length && (color !== 3 || hasPalette));
  const channels={0:1,2:3,3:1,4:2,6:4}[color];
  const passes=interlace ? [[0,0,8,8],[4,0,8,8],[0,4,4,8],[2,0,4,4],[0,2,2,4],[1,0,2,2],[0,1,1,2]] : [[0,0,1,1]];
  const rowLengths=[]; let expected=0;
  for (const [x,y,dx,dy] of passes) {
    const w=Math.max(0,Math.ceil((width-x)/dx)), h=Math.max(0,Math.ceil((height-y)/dy));
    if (!w || !h) continue;
    const length=Math.ceil(w*channels*depth/8);
    for (let row=0;row<h;row++) rowLengths.push(length);
    expected += (length+1)*h;
  }
  requireArtifact(expected <= 320 * 1024 ** 2, 'file_too_large');
  const stream = new Blob(compressed).stream().pipeThrough(new DecompressionStream('deflate'));
  const reader=stream.getReader(); let total=0,row=0,column=0;
  try {
    while (true) {
      const chunk=await reader.read(); if (chunk.done) break;
      total += chunk.value.length; requireArtifact(total <= expected);
      for (const value of chunk.value) {
        if (column===0) requireArtifact(value <= 4);
        column++;
        if (column===rowLengths[row]+1) { column=0; row++; }
      }
    }
    requireArtifact(total === expected && row === rowLengths.length && column === 0);
  } finally { await reader.cancel().catch(()=>{}); }
  if (typeof createImageBitmap === 'function') {
    const bitmap=await createImageBitmap(new Blob([bytes],{type:'image/png'}));
    try { requireArtifact(bitmap.width===width && bitmap.height===height); }
    finally { bitmap.close(); }
  }
  return {width,height};
}
