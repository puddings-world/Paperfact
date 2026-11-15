import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateAnnotations, renderAnnotations, renderCitationCards} from '../annotations.mjs';
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


const element=(tag,attrs={},...children)=>({tag,attrs,children,
  append(...items){this.children.push(...items);}});
const all=(node,tag)=>[...(node?.tag===tag?[node]:[]),
  ...(node?.children??[]).flatMap(child=>typeof child==='object'?all(child,tag):[])];
const visible=node=>(node?.children??[]).map(child=>typeof child==='object'?visible(child):String(child)).join(' ');
function citation(overrides={}) {
  return {feature:'citation',key:'ref-key',source_document_hash:'a'.repeat(64),
    data:{title:'A saved reference',year:2026,venue:'Fixture',purpose:'Background',
      gist:'Method summary',verdict:'Relevant',why:'Supports the design',basis:'original',
      contexts_json:['Exact saved passage <img src=x onerror=alert(1)>'],...overrides}};
}

test('overview renders read-only citation content, collapsed passages and no executable links',()=>{
  const panel=element('main'),row=citation(),paper={research_content:[row]},before=structuredClone(paper);
  renderAnnotations(panel,paper,element,key=>key,{documentHash:'a'.repeat(64)});
  const text=visible(panel);
  for(const value of ['A saved reference','2026','Fixture','Background','Method summary',
    'Relevant','Supports the design','original',row.data.contexts_json[0],'citationSource_same'])assert(text.includes(value));
  assert.equal(all(panel,'details').length,2);
  assert(all(panel,'details').every(node=>!node.attrs.open));
  assert.equal(all(panel,'blockquote').length,1);
  assert.equal(all(panel,'a').length+all(panel,'img').length+all(panel,'script').length,0);
  assert.deepEqual(paper,before);
});

for(const [source,current,expected] of [[null,null,'unknown'],['a',null,'unavailable'],
  ['a','b','different'],['a','a','same']])test('citation version state '+expected,()=>{
  const panel=element('main'),row=citation({title:null,contexts_json:null});
  row.source_document_hash=source;
  renderCitationCards(panel,{research_content:[row]},element,key=>key,{documentHash:current});
  assert(visible(panel).includes('citationSource_'+expected));
  assert(visible(panel).includes('citationNoContexts'));
  assert(visible(panel).includes('ref-key'));
  assert(!visible(panel).includes('citationSource_'+(expected==='same'?'different':'same')));
});

test('empty and removed citation sets leave no stale card and translations describe source limits',async()=>{
  const {translator}=await import('../i18n.mjs');
  for(const paper of [{},{research_content:[]},{research_content:[{feature:'resource'}]}]){
    const panel=element('main');renderCitationCards(panel,paper,element,key=>key);
    assert.equal(panel.children.length,0);
  }
  for(const language of ['en','zh-TW']){
    const t=translator(language);
    for(const key of ['research_citation','citation_purpose','citation_gist','citation_verdict',
      'citation_why','citation_basis','citationContexts','citationNoContexts',
      ...['same','different','unknown','unavailable'].map(value=>'citationSource_'+value)])
      assert.notEqual(t(key),key);
  }
});
