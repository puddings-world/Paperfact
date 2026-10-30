import test from 'node:test';
import assert from 'node:assert/strict';
import { renderReadingGoal } from '../reading-goal.mjs';
import { validateContent, projectContent, suppressSnapshotContent } from '../content.mjs';
import { contentId } from '../ids.mjs';
import { translator } from '../i18n.mjs';

const scope = { kind: 'list', id: 'list' };
const payload = body => ({ scope, feature:'reading_goal', key:'main',
  source_document_hash:null, data:{ body, written_at:'2026-10-30T00:00:00+00:00' } });
const row = body => ({ revision: 1, operation:{ entity_id:contentId(scope,'reading_goal','main'),
  payload:payload(body) } });
test('list purpose projects separately from generated survey and clears snapshot on deletion', () => {
  const lists=[{id:'list',analysis_sections:[{kind:'survey',body:'Keep survey'}]}];
  const item=row('Question to pursue');
  validateContent(item.operation.payload,item.operation.entity_id,[{kind:'list',id:'list'}]);
  projectContent([],lists,[item]);
  assert.deepEqual(lists[0].analysis_sections.map(s=>s.body),['Keep survey','Question to pursue']);
  const deleted={ revision:2,operation:{...item.operation,entity_type:'research_content',action:'delete'} };
  suppressSnapshotContent([],lists,[deleted],[{sequence:1,outcome:'accepted',
    operation:{...item.operation,entity_type:'research_content',action:'put'}}],[]);
  assert.deepEqual(lists[0].analysis_sections,[{kind:'survey',body:'Keep survey'}]);
});
test('purpose rejects paper scope, PDF provenance, extra fields and excess text', () => {
  for(const bad of [
    {...payload('q'),scope:{kind:'paper',id:'list'}},
    {...payload('q'),source_document_hash:'a'.repeat(64)},
    {...payload('q'),data:{...payload('q').data,prompt:'secret'}},
    payload('x'.repeat(2001))
  ]) assert.throws(()=>validateContent(bad,contentId(scope,'reading_goal','main'),[{kind:'list',id:'list'}]));
});
test('purpose display is plain text, localized, and absent when cleared', () => {
  const children=[],parent={append(node){children.push(node);}};
  const el=(tag,attrs,...kids)=>({tag,attrs,kids});
  renderReadingGoal(parent,{analysis_sections:[{kind:'reading_goal',body:'<script>literal</script>'}]},
    el,translator('en'));
  assert.equal(children[0].kids[0].kids[0],'Research purpose');
  assert.equal(children[0].kids[1].kids[0],'<script>literal</script>');
  renderReadingGoal(parent,{analysis_sections:[{kind:'reading_goal',body:'  '}]},el,translator('zh-TW'));
  assert.equal(children.length,1);
  assert.equal(translator('zh-TW')('readingGoal'),'研究目的');
});
