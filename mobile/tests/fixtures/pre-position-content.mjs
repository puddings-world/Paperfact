/** Read-only mirror of the closed SQL content contract. No model or file access. */
import { contentId, uuid5Name, asciiJSON } from '../../ids.mjs';
import { ANNOTATION_FEATURES, validateAnnotations } from '../../annotations.mjs';
import { validateClaims } from '../../claims.mjs';
import { LEGACY_FIELDS, validateWorkflow } from '../../legacy-workflow.mjs';
const HASH = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ID = /^[A-Za-z0-9_.:-]{1,128}$/;
export const CONTENT_FIELDS = {
  ...LEGACY_FIELDS,
  ...Object.fromEntries(ANNOTATION_FEATURES.map(feature => [feature, 'body_json source_hash document_hash written_at'])),
  dive: 'body written_at spec',
  close_reading: 'body spec written_at',
  citation: 'title s2_id year venue citations influential purpose gist verdict why contexts_json doi basis spec edited written_at',
  followup: 'title year venue doi citations abstract verdict why relation contexts_json arxiv_id edited fetched_at',
  context: 'summary reading_json written_at edited',
  resource: 'kind own source context stars license pushed_at note alive checked_at',
  manual_highlight: 'anchor quote created_at',
  ai_highlight: 'analysis_hash anchor quote reason hidden',
  chat: 'role body created_at page anchor',
  list_survey: 'body papers spec written_at edited',
  reading_goal: 'body written_at',
  reference_edge: 'influential',
  list_pin: 'pinned_at',
  queue_pin: 'pinned_at'
};
const bytes = value => new TextEncoder().encode(value).length;
function expect(value) {
  if(! value) throw new Error('unsupported_research_content');
}
function closed(value, fields, optional =[]) {
  expect(value && typeof value === 'object' && ! Array.isArray(value));
  expect(fields.every(f => Object.hasOwn(value, f)) && Object.keys(value).every(f =>[...fields, ...optional].includes(f)));
}
function text(value, limit, {
  nullable = true,
  nonempty = false
} = {}) {
  expect((nullable && value === null) ||(typeof value === 'string' && bytes(value) <= limit &&(! nonempty || value.trim())));
}
function integer(value, max = 2 ** 31 - 1, nullable = false) {
  expect((nullable && value === null) ||(Number.isInteger(value) && value >= 0 && value <= max));
}
function hash(value, nullable = false) {
  expect((nullable && value === null) ||(typeof value === 'string' && HASH.test(value)));
}
function stamp(value) {
  text(value, 64, {
    nullable: false,
    nonempty: true
  });
  const date = value.match(/^(\d{4})(?:-(\d{2})-(\d{2})|(\d{2})(\d{2})|-?W(\d{2})-?([1-7]))[\s\S]([\s\S]+)$/u);
  expect(date);
  const year = Number(date[1]);
  expect(year >= 1 && year <= 9999);
  const leap = year % 4 === 0 &&(year % 100 !== 0 || year % 400 === 0);
  if(date[6]) {
    const jan = new Date(0);
    jan.setUTCFullYear(year, 0, 1);
    const day = jan.getUTCDay() || 7;
    const max = day === 4 ||(day === 3 && leap) ? 53: 52;
    expect(Number(date[6]) >= 1 && Number(date[6]) <= max);
  } else {
    const month = Number(date[2] ?? date[4]),
    day = Number(date[3] ?? date[5]);
    expect(month >= 1 && month <= 12 && day >= 1 && day <=[31, leap ? 29: 28, 31, 30, 31, 30, 31, 31,
    30, 31, 30, 31][month - 1]);
  }
  const time = date[8],
  zone = time.match(/(?:Z|[+-](\d{2})(?::?(\d{2}))?(?::?(\d{2})(?:[.,]\d+)?)?)$/);
  expect(zone);
  if(zone[1]) expect(Number(zone[1]) < 24 && Number(zone[2] ?? 0) < 60 && Number(zone[3] ?? 0) < 60);
  const clock = time.slice(0, zone.index).match(/^(\d{2})(?::?(\d{2}))?(?::?(\d{2}))?(?:[.,]\d+)?$/);
  expect(clock && Number(clock[1]) < 24 && Number(clock[2] ?? 0) < 60 && Number(clock[3] ?? 0) < 60);
}
export function validateAnchor(anchor) {
  if(anchor === null) return;
  closed(anchor, ['p0', 'o0', 'p1', 'o1'], ['document_hash']);
  for(const key of['p0', 'o0', 'p1', 'o1']) integer(anchor[key], 1000000);
  expect(anchor.p1 > anchor.p0 ||(anchor.p1 === anchor.p0 && anchor.o1 >= anchor.o0));
  if(Object.hasOwn(anchor, 'document_hash')) hash(anchor.document_hash, true);
}
export {stamp as validateContentTimestamp};

export function validateRichNote(payload) {
  closed(payload, ['paper_id', 'body', 'kind', 'created_at', 'page', 'anchor']);
  expect(typeof payload.paper_id === 'string' && UUID.test(payload.paper_id));
  text(payload.body, 200 * 1024, {
    nullable: false
  });
  text(payload.kind, 40, {
    nullable: false,
    nonempty: true
  });
  stamp(payload.created_at);
  integer(payload.page, 1000001, true);
  expect(payload.page !== 0);
  validateAnchor(payload.anchor);
  if(payload.anchor !== null) expect(payload.page === null || payload.page === payload.anchor.p0 + 1);
}
export function validateContent(payload, id, parents) {
  closed(payload, ['scope', 'feature', 'key', 'data', 'source_document_hash']);
  const {
    scope,
    feature,
    key,
    data,
    source_document_hash: source
  } = payload;
  expect(typeof feature === 'string' && Object.hasOwn(CONTENT_FIELDS, feature));
  closed(scope, ['kind', 'id']);
  const expected = ['list_survey', 'reading_goal', 'list_pin'].includes(feature) ? 'list': 'paper';
  expect(scope.kind === expected && typeof scope.id === 'string' && ID.test(scope.id));
  if(expected === 'paper') expect(UUID.test(scope.id));
  text(key, 4096, {
    nullable: false,
    nonempty: true
  });
  if(['dive', 'close_reading', 'context', 'list_survey', 'reading_goal', 'queue_entry', 'queue_pin', ...ANNOTATION_FEATURES].includes(feature)) expect(key === 'main');
  if(['manual_highlight', 'chat', 'reading_event'].includes(feature)) expect(UUID.test(key));
  if(feature === 'resource') {
    expect(/^https?:\/\//i.test(key));
    let url;
    try {
      url = new URL(key);
    } catch {
      expect(false);
    }
    expect(['http:', 'https:'].includes(url.protocol) && url.hostname && ! url.username && ! url.password);
  }
  expect(id === contentId(scope, feature, key));
  const endpoints = [[expected, scope.id]];
  if(feature === 'queue_entry') {
    expect(data && typeof data === 'object' && !Array.isArray(data));
    if(data.parent_id !== null && data.parent_id !== scope.id) endpoints.push(['paper',data.parent_id]);
  }
  if(feature === 'reference_edge') {
    expect(UUID.test(key) && source === null);
    if(key !== scope.id) endpoints.push(['paper',key]);
  }
  if(feature === 'queue_pin') expect(source === null);
  if(feature === 'list_pin') {
    expect(scope.id !== 'queue' && UUID.test(key) && source === null);
    endpoints.push(['paper',key],['membership',uuid5Name('paperfact:membership:' + asciiJSON([scope.id,key]))]);
  }
  expect(parents.length === endpoints.length && parents.every((p,index) =>
    p.kind === endpoints[index][0] && p.id === endpoints[index][1]));
  hash(source, !['manual_highlight', 'ai_highlight'].includes(feature));
  if(Object.hasOwn(LEGACY_FIELDS,feature)) { validateWorkflow(payload,stamp); return; }
  closed(data, CONTENT_FIELDS[feature].split(' '), feature === 'chat' ? ['exchange_id', 'reply_to']: []);
  if(feature === 'chat') {
    const linked = Object.hasOwn(data, 'exchange_id');
    expect(linked === Object.hasOwn(data, 'reply_to'));
    if(linked) {
      expect(typeof data.exchange_id === 'string' && UUID.test(data.exchange_id));
      expect(data.reply_to === null ||(typeof data.reply_to === 'string' && UUID.test(data.reply_to)));
      expect((data.role === 'user' && data.reply_to === null) ||
      (data.role === 'assistant' && data.reply_to !== null && data.reply_to !== key));
    }
  }
  for(const [name, value] of Object.entries(data)) {
    if(['exchange_id', 'reply_to'].includes(name)) continue;
    if(['created_at', 'written_at', 'fetched_at', 'checked_at', 'pinned_at'].includes(name)) stamp(value);
    else if(['edited', 'hidden', 'influential', 'own'].includes(name)) integer(value, 1);
    else if(['year', 'citations', 'stars', 'papers', 'page', 'alive'].includes(name)) integer(value, name === 'alive' ? 1: 2 ** 31 - 1,
    true);
    else if(name === 'anchor') {
      validateAnchor(value);
      if(['manual_highlight', 'ai_highlight'].includes(feature)) expect(value !== null);
      if(value?.document_hash !== null && value?.document_hash !== undefined) expect(value.document_hash === source);
    } else if(name === 'document_hash') { hash(value, true); expect(value === source); }
    else if(name === 'body_json') {
      if(feature === 'claims') validateClaims(value,data.document_hash);
      else validateAnnotations(feature, value);
    }
    else if(['analysis_hash', 'source_hash'].includes(name)) hash(value);
    else if(name === 'contexts_json') {
      if(value !== null) {
        expect(Array.isArray(value) && value.length <= 200);
        value.forEach(item => text(item, 8192, {
          nullable: false
        }));
      }
    } else if(name === 'reading_json') {
      if(value !== null) {
        expect(Array.isArray(value) && value.length <= 100);
        value.forEach(item => {
          closed(item, ['title', 'direction', 'why']);
          Object.values(item).forEach(v => text(v, 8192, {
            nullable: false
          }));
        });
      }
    } else text(
    value,
    name === 'body' ? 200 * 1024: 32 * 1024,
    {
      nullable: !['body', 'quote', 'role', 'kind', 'source', 'reason'].includes(name)
    }
    );
  }
  if(feature === 'claims') expect(data.source_hash.length === 64);
  if(feature === 'reading_goal') {
    expect(source === null);
    text(data.body, 8000, { nullable: false });
    expect([...data.body].length <= 2000);
  }
  if(feature === 'chat') expect(['user', 'assistant', 'system'].includes(data.role));
  if(feature === 'ai_highlight') expect(key.startsWith(source + ':'));
  // Python's payload bound uses its default separator spaces, not compact JSON.
  const pythonJSON = value => Array.isArray(value) ? '[' + value.map(pythonJSON).join(', ') + ']': value && typeof value === 'object' ? '{' + Object.entries(value).map(([k,
  v]) => JSON.stringify(k) + ': ' + pythonJSON(v)).join(', ') + '}': JSON.stringify(value);
  expect(bytes(pythonJSON(payload)) <= 240 * 1024);
}
export function projectContent(papers, lists, rows) {
  const highlights =[], markInputs = new Map();
  for(const row of rows) {
    const {
      scope,
      feature,
      key,
      data,
      source_document_hash: source
    } = row.operation.payload;
    const target =(scope.kind === 'paper' ? papers: lists).find(item => item.id === scope.id);
    if(! target) continue;
    if(feature === 'queue_pin') target.queue_pin = {pinned_at:data.pinned_at};
    if(feature === 'list_pin') {
      const member = target.members?.find(item => item.paper_id === key);
      if(member) { member.pinned = true; member.pinned_at = data.pinned_at; }
    }
    if(feature === 'reference_edge') {
      target.references ??=[];
      target.references.push({paper_id:key,influential:data.influential,revision:row.revision});
    }
    target.research_content ??=[];
    target.research_content.push({
      id: row.operation.entity_id,
      feature,
      key,
      data: structuredClone(data),
      source_document_hash: source,
      revision: row.revision
    });
    if(feature === 'queue_entry') {
      target.legacy_queue = structuredClone(data);
      target.legacy_queue_known = true;
    }
    if(feature === 'reading_event') {
      target.reading_events ??=[];
      target.reading_events.push({id:key,data:structuredClone(data),incarnation:row.operation.incarnation,
        revision:row.revision,editable:false});
    }
    if(['dive', 'close_reading', 'context', 'list_survey', 'reading_goal'].includes(feature)) {
      const kind = {
        dive: 'deep_reading',
        close_reading: 'close_reading',
        context: 'context',
        list_survey: 'survey',
        reading_goal: 'reading_goal'
      }
      [feature];
      target.analysis_sections =(target.analysis_sections ??[]).filter(section => section.kind !== kind);
      target.analysis_sections.push({
        kind,
        body: data.body ?? data.summary,
        written_at: data.written_at,
        source_document_hash: source
      });
    } else if(feature === 'citation') {
      target.citations =(target.citations ??[]).filter(c => c.ref_key !== key);
      target.citations.push({
        ...structuredClone(data),
        ref_key: key,
        source_document_hash: source
      });
    } else if(['manual_highlight', 'ai_highlight'].includes(feature)) {
      markInputs.set(row.operation.entity_id, data);
      const anchor = data.anchor;
      highlights.push({
        id: row.operation.entity_id,
        paper_id: scope.id,
        origin: feature === 'ai_highlight' ? 'ai': 'manual',
        quote: data.quote,
        reason: data.reason ?? '',
        hidden: data.hidden === 1,
        pdf_hash: source,
        anchor: {
          schema_version: 1,
          kind: 'word_range',
          p0: anchor.p0,
          o0: anchor.o0,
          p1: anchor.p1,
          o1: anchor.o1
        },
        anchor_status: 'available'
      });
    }
  }
  return highlights.filter(mark => {
    if(mark.origin !== 'ai') return true;
    const paper = papers.find(item => item.id === mark.paper_id);
    const layer = paper?.research_content?.find(item => item.feature === 'highlight_analysis');
    if(!layer) return !paper?.highlight_analysis_known;
    // Identical input digests can produce different selections. The current
    // quote and page must still be present, as well as both source identities.
    return mark.pdf_hash === layer.data.document_hash &&
      markInputs.get(mark.id).analysis_hash === layer.data.source_hash &&
      layer.data.body_json.items.some(item => item.text === mark.quote &&
        item.page === mark.anchor.p0 + 1 && mark.anchor.p1 === mark.anchor.p0);
  });
}
/** An absent singleton deletion has no fabricated body or prior put receipt. */
export function initialAnnotationDeletion(op, heads = []) {
  if(op?.version !== 2 || op.entity_type !== 'research_content' || op.action !== 'delete' ||
      !op.payload || Array.isArray(op.payload) || Object.keys(op.payload).length ||
      !Array.isArray(op.parents) || op.parents.length !== 1) return null;
  const parent = op.parents[0];
  if(!parent || parent.kind !== 'paper' || !UUID.test(parent.id) || !ID.test(parent.incarnation)) return null;
  const current = heads.find(row => row.operation?.entity_type === 'paper' &&
    row.operation.entity_id === parent.id && row.operation.action === 'put');
  if(!current || current.operation.incarnation !== parent.incarnation) return null;
  const scope = {kind: 'paper', id: parent.id};
  const feature = ANNOTATION_FEATURES.find(value => contentId(scope,value,'main') === op.entity_id);
  return feature ? {scope, feature, key: 'main'} : null;
}

export function suppressSnapshotContent(papers, lists, heads, receipts, highlights) {
  const coveredHighlights = new Set();
  for(const head of heads) {
    const op = head.operation;
    if(op.entity_type !== 'research_content') continue;
    const payload = op.action === 'put' ? op.payload: receipts.filter(event => event.outcome === 'accepted' && event.operation.entity_type === 'research_content' && event.operation.entity_id === op.entity_id && event.operation.action === 'put' && event.sequence < head.revision).sort((a,
    b) => b.sequence - a.sequence)[0]?.operation.payload ?? initialAnnotationDeletion(op,heads);
    if(! payload) continue;
    const {
      scope,
      feature,
      key
    } = payload,
    target =(scope.kind === 'paper' ? papers: lists).find(item => item.id === scope.id);
    if(! target) continue;
    const kind = {
      dive: 'deep_reading',
      close_reading: 'close_reading',
      context: 'context',
      list_survey: 'survey',
        reading_goal: 'reading_goal'
    }
    [feature];
    if(kind) target.analysis_sections =(target.analysis_sections ??[]).filter(section => section.kind !== kind);
    if(ANNOTATION_FEATURES.includes(feature)) {
      target.research_content = (target.research_content ?? []).filter(item => item.feature !== feature);
      if(feature === 'highlight_analysis') {
        target.highlight_analysis_known = true;
        coveredHighlights.add(scope.id + '/ai');
      }
    }
    if(feature==='queue_pin') target.queue_pin=null;
    if(feature==='queue_entry') { target.legacy_queue=null; target.legacy_queue_known=true; }
    if(feature==='reading_event') target.reading_events=(target.reading_events??[]).filter(row=>row.id!==key);
    if(feature === 'list_pin') {
      const member = target.members?.find(item => item.paper_id === key);
      if(member) { member.pinned = false; delete member.pinned_at; }
    }
    if(feature === 'reference_edge') target.references = (target.references ?? []).filter(item => item.paper_id !== key);
    if(feature === 'citation') target.citations =(target.citations ??[]).filter(citation => citation.ref_key !== key);
    if(['manual_highlight', 'ai_highlight'].includes(feature)) coveredHighlights.add(scope.id + '/' +(feature === 'ai_highlight' ? 'ai': 'manual'));
  }
  const archived =[],
  live =[];
  for(const highlight of highlights)(coveredHighlights.has(highlight.paper_id + '/' + highlight.origin) ? archived: live).push(highlight);
  return {
    archived,
    live
  };
}

/** Pair only inside this paper. Linked orphan answers never use adjacency. */
export function chatExchanges(paper) {
  const rows = (paper.research_content ?? []).filter(row => row.feature === 'chat');
  const linked = row => Object.hasOwn(row.data, 'exchange_id');
  const users = new Map(rows.filter(row => linked(row) && row.data.role === 'user').map(row => [row.key, row]));
  const answers = new Map(), matched = new Set();
  for(const row of rows) {
    if(!linked(row) || row.data.role !== 'assistant') continue;
    const question = users.get(row.data.reply_to);
    if(question?.data.exchange_id !== row.data.exchange_id) continue;
    if(!answers.has(question.key)) answers.set(question.key, []);
    answers.get(question.key).push(row);
    matched.add(row);
  }
  const result = [];
  let pending = null;
  for(const row of rows) {
    if(linked(row)) {
      pending = null;
      if(row.data.role === 'user') {
        const replies = answers.get(row.key) ?? [];
        if(!replies.length) result.push({question: row, answer: null, orphan: false});
        for(const answer of replies) result.push({question: row, answer, orphan: false});
      } else if(!matched.has(row)) result.push({question: null, answer: row, orphan: true});
    } else if(row.data.role === 'user') {
      pending = {question: row, answer: null, orphan: false};
      result.push(pending);
    } else if(row.data.role === 'assistant') {
      if(pending) pending.answer = row;
      else result.push({question: null, answer: row, orphan: true});
      pending = null;
    } else pending = null;
  }
  return result;
}
