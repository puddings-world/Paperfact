/** Closed reading annotation mirror. No model, network or executable markup. */
import { validateClaims, renderClaimSet } from './claims.mjs';
export const ANNOTATION_FEATURES = ['highlight_analysis', 'reading_links', 'research_questions', 'claims'];
const HASH = /^[0-9a-f]{64}$/;
const KINDS = ['problem', 'contribution', 'method', 'evidence', 'limitation', 'definition'];
const expect = value => { if(!value) throw new Error('unsupported_reading_annotation'); };
function closed(value, fields) {
  expect(value && typeof value === 'object' && !Array.isArray(value));
  expect(Object.keys(value).length === fields.length && fields.every(key => Object.hasOwn(value, key)));
}
function text(value, max, min = 1) {
  expect(typeof value === 'string' && value.length <= max * 2);
  const length = Array.from(value).length;
  expect(length >= min && length <= max && (!min || value.trim()));
}
function number(value, max, min = 0) { expect(Number.isInteger(value) && value >= min && value <= max); }
function page(value) { if(value !== null) number(value, 1000000, 1); }
function items(value, max, min = 0) { expect(Array.isArray(value) && value.length >= min && value.length <= max); }

export function validateAnnotations(feature, body) {
  if(feature === 'claims') return validateClaims(body);
  if(feature === 'research_questions') {
    closed(body, ['items']); items(body.items, 6, 1);
    const seen = new Set();
    for(const item of body.items) {
      closed(item, ['question', 'why', 'evidence', 'page']);
      text(item.question, 280); text(item.why, 800); text(item.evidence, 8192, 15); page(item.page);
      const normalized = item.question.trim(); expect(!seen.has(normalized)); seen.add(normalized);
    }
  } else if(feature === 'highlight_analysis') {
    closed(body, ['items', 'coverage']); items(body.items, 32);
    const seen = new Set();
    for(const item of body.items) {
      closed(item, ['text', 'page', 'kind', 'reason', 'source']);
      text(item.text, 4000, 20); text(item.reason, 1600); page(item.page);
      expect(KINDS.includes(item.kind));
      expect(item.source === (item.page === null ? 'original' : `page:${item.page}`));
      const key = JSON.stringify([item.page, item.text]); expect(!seen.has(key)); seen.add(key);
    }
    const coverage = body.coverage;
    closed(coverage, ['pages', 'empty_pages', 'chunks', 'has_page_numbers']);
    number(coverage.pages, 20000, 1); number(coverage.chunks, 20000, 1);
    expect(typeof coverage.has_page_numbers === 'boolean'); items(coverage.empty_pages, coverage.pages);
    const pages = new Set();
    for(const p of coverage.empty_pages) {
      page(p); expect(!pages.has(p) && !(p === null && coverage.has_page_numbers)); pages.add(p);
    }
    if(coverage.has_page_numbers) expect(body.items.every(item => item.page !== null));
  } else if(feature === 'reading_links') {
    closed(body, ['links', 'analysis_hash']);
    expect(typeof body.analysis_hash === 'string' && HASH.test(body.analysis_hash)); items(body.links, 32);
    const seen = new Set();
    for(const link of body.links) {
      closed(link, ['quote', 'section', 'explanation']); number(link.quote, 31); text(link.explanation, 1200);
      expect(typeof link.section === 'string' && /^(?:dive|close):(?:0|[1-9][0-9]{0,5})$/.test(link.section));
      expect(!seen.has(link.quote)); seen.add(link.quote);
    }
  } else throw new Error('unsupported_reading_annotation');
  expect(new TextEncoder().encode(JSON.stringify(body)).length <= 220 * 1024);
  return body;
}

export function renderAnnotations(panel, paper, el, t) {
  for(const row of paper.research_content ?? []) {
    if(!ANNOTATION_FEATURES.includes(row.feature)) continue;
    if(row.feature === 'claims') { renderClaimSet(panel,row,el,t); continue; }
    const body = validateAnnotations(row.feature, row.data.body_json);
    const card = el('article', {class: 'card reading-annotations'}, el('h2', {}, t('research_' + row.feature)));
    if(row.feature === 'reading_links') {
      for(const link of body.links) card.append(el('p', {}, `${link.section} · ${link.explanation}`));
    } else {
      for(const item of body.items) {
        const quote = item.evidence ?? item.text;
        const part = el('section', {}, el('h3', {}, item.question ?? t('annotationQuote')),
          el('blockquote', {}, quote), el('p', {}, item.why ?? item.reason));
        if(item.page !== null) part.append(el('p', {class: 'muted'}, `${t('annotationPage')} ${item.page}`));
        card.append(part);
      }
    }
    panel.append(card);
  }
}
