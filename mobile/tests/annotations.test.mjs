import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateAnnotations, renderAnnotations} from '../annotations.mjs';
import {validateContent} from '../content.mjs';
import {contentId} from '../ids.mjs';
const fixtures = JSON.parse(readFileSync(new URL('../../tests/fixtures/reading-annotations.json', import.meta.url)));
for(const example of fixtures) test(example.name, () => {
  if(example.valid) assert.equal(validateAnnotations(example.feature, example.body), example.body);
  else assert.throws(() => validateAnnotations(example.feature, example.body));
});
for(const example of fixtures.filter(x=>x.valid)) test('portable envelope '+example.name, () => {
  const scope = {kind:'paper',id:'11111111-1111-4111-8111-111111111111'};
  const value = {scope, feature:example.feature, key:'main', data:{body_json:example.body,
    source_hash:'a'.repeat(64),document_hash:null,written_at:'2026-01-01T00:00:00+00:00'}, source_document_hash:null};
  validateContent(value, contentId(scope,example.feature,'main'), [{kind:'paper',id:scope.id}]);
});
test('read-only cards expose reasons and original quotes without HTML or model calls', () => {
  const node = (tag, attrs={}, ...children) => ({tag,attrs,children,append(...items){this.children.push(...items);}});
  const panel = node('div');
  const body = structuredClone(fixtures[0].body);
  body.items[0].why = '<script>do not execute</script>';
  renderAnnotations(panel, {research_content:[{feature:'research_questions',data:{body_json:body}}]}, node, x=>x);
  const rendered = JSON.stringify(panel);
  assert.ok(rendered.includes(body.items[0].evidence));
  assert.ok(rendered.includes(body.items[0].why));
  assert.equal(panel.children[0].tag,'article');
});
