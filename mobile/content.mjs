/** Read-only mirror of the closed SQL content contract. No model or file access. */
import {
  contentId
} from './ids.mjs';
const HASH = /^[0-9a-f]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ID = /^[A-Za-z0-9_.:-]{1,128}$/;
export const CONTENT_FIELDS = {
  dive: 'body written_at spec',
  close_reading: 'body spec written_at',
  citation: 'title s2_id year venue citations influential purpose gist verdict why contexts_json doi basis spec edited written_at',
  followup: 'title year venue doi citations abstract verdict why relation contexts_json arxiv_id edited fetched_at',
  context: 'summary reading_json written_at edited',
  resource: 'kind own source context stars license pushed_at note alive checked_at',
  manual_highlight: 'anchor quote created_at',
  ai_highlight: 'analysis_hash anchor quote reason hidden',
  chat: 'role body created_at page anchor',
  list_survey: 'body papers spec written_at edited'
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
  const expected = feature === 'list_survey' ? 'list': 'paper';
  expect(scope.kind === expected && typeof scope.id === 'string' && ID.test(scope.id));
  if(expected === 'paper') expect(UUID.test(scope.id));
  text(key, 4096, {
    nullable: false,
    nonempty: true
  });
  if(['dive', 'close_reading', 'context', 'list_survey'].includes(feature)) expect(key === 'main');
  if(['manual_highlight', 'chat'].includes(feature)) expect(UUID.test(key));
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
  expect(parents.length === 1 && parents[0].kind === expected && parents[0].id === scope.id);
  hash(source, !['manual_highlight', 'ai_highlight'].includes(feature));
  closed(data, CONTENT_FIELDS[feature].split(' '));
  for(const [name, value] of Object.entries(data)) {
    if(['created_at', 'written_at', 'fetched_at', 'checked_at'].includes(name)) stamp(value);
    else if(['edited', 'hidden', 'influential', 'own'].includes(name)) integer(value, 1);
    else if(['year', 'citations', 'stars', 'papers', 'page', 'alive'].includes(name)) integer(value, name === 'alive' ? 1: 2 ** 31 - 1,
    true);
    else if(name === 'anchor') {
      validateAnchor(value);
      if(['manual_highlight', 'ai_highlight'].includes(feature)) expect(value !== null);
      if(value?.document_hash !== null && value?.document_hash !== undefined) expect(value.document_hash === source);
    } else if(name === 'analysis_hash') hash(value);
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
  if(feature === 'chat') expect(['user', 'assistant', 'system'].includes(data.role));
  if(feature === 'ai_highlight') expect(key.startsWith(source + ':'));
  // Python's payload bound uses its default separator spaces, not compact JSON.
  const pythonJSON = value => Array.isArray(value) ? '[' + value.map(pythonJSON).join(', ') + ']': value && typeof value === 'object' ? '{' + Object.entries(value).map(([k,
  v]) => JSON.stringify(k) + ': ' + pythonJSON(v)).join(', ') + '}': JSON.stringify(value);
  expect(bytes(pythonJSON(payload)) <= 240 * 1024);
}
export function projectContent(papers, lists, rows) {
  const highlights =[];
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
    target.research_content ??=[];
    target.research_content.push({
      id: row.operation.entity_id,
      feature,
      key,
      data: structuredClone(data),
      source_document_hash: source,
      revision: row.revision
    });
    if(['dive', 'close_reading', 'context', 'list_survey'].includes(feature)) {
      const kind = {
        dive: 'deep_reading',
        close_reading: 'close_reading',
        context: 'context',
        list_survey: 'survey'
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
  return highlights;
}
export function suppressSnapshotContent(papers, lists, heads, receipts, highlights) {
  const coveredHighlights = new Set();
  for(const head of heads) {
    const op = head.operation;
    if(op.entity_type !== 'research_content') continue;
    const payload = op.action === 'put' ? op.payload: receipts.filter(event => event.outcome === 'accepted' && event.operation.entity_type === 'research_content' && event.operation.entity_id === op.entity_id && event.operation.action === 'put' && event.sequence < head.revision).sort((a,
    b) => b.sequence - a.sequence)[0]?.operation.payload;
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
      list_survey: 'survey'
    }
    [feature];
    if(kind) target.analysis_sections =(target.analysis_sections ??[]).filter(section => section.kind !== kind);
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
