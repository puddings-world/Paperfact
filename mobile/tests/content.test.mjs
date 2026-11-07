import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const annotationFixtures = JSON.parse(readFileSync(new URL('../../tests/fixtures/reading-annotations.json', import.meta.url)));
const claimFixture = JSON.parse(readFileSync(new URL('../../tests/fixtures/claim-sets.json', import.meta.url))).find(item => item.valid).body;
import {
  CONTENT_FIELDS,
  validateContent,
  validateRichNote
} from '../content.mjs';
import {
  asciiJSON,
  contentId, uuid5Name
} from '../ids.mjs';
import {
  MemoryStore
} from '../store.mjs';
import {
  Engine
} from '../engine.mjs';
import {
  demoTransport,
  demoProjection,
  PAPER,
  operation,
  ref
} from '../fixture.mjs';
import {
  projection,
  receive,
  validateOperation
} from '../domain.mjs';
const hash = 'a'.repeat(64), stamp = '2026-01-01T00:00:00+00:00';
function payload(feature) {
  const scope = {
    kind: ['list_survey', 'reading_goal', 'list_pin'].includes(feature) ? 'list': 'paper',
    id: ['list_survey', 'reading_goal', 'list_pin'].includes(feature) ? 'demo-list': PAPER
  };
  const key = ['reference_edge','list_pin'].includes(feature) ? PAPER : ['manual_highlight', 'chat', 'reading_event'].includes(feature) ? '00000000-0000-4000-8000-000000000002': feature === 'ai_highlight' ? hash + ':claim': feature === 'resource' ? 'https://example.org/code': feature === 'citation' ? '引用🚀': feature === 'followup' ? 'work-1': 'main';
  const data = {};
  for(const field of CONTENT_FIELDS[feature].split(' ')) {
    data[field] =['created_at', 'written_at', 'fetched_at', 'checked_at', 'pinned_at'].includes(field) ? stamp: ['edited',
    'hidden', 'influential', 'own'].includes(field) ? 0: field === 'anchor' ? {
      p0: 0,
      o0: 2,
      p1: 0,
      o1: 4,
      document_hash: hash
    }
    : field === 'analysis_hash' ? hash: field === 'role' ? 'assistant': ['body', 'quote', 'kind', 'source',
    'reason'].includes(field) ? 'Fixture research': null;
  }
  if(feature === 'queue_entry') Object.assign(data,{rank:-2.75,state:'pending',role:'manual',parent_id:null,
    reason:'Fixture reason',queued_at:stamp,delivered_at:null,read_at:null});
  if(feature === 'reading_event') Object.assign(data,{delivered_at:stamp,role:null,note:'Original note',brief:null});
  const annotation = annotationFixtures.find(item => item.valid && item.feature === feature);
  if(annotation) { data.body_json = structuredClone(annotation.body); data.source_hash = hash; data.document_hash = hash; }
  if(feature === 'claims') { data.body_json=structuredClone(claimFixture); data.source_hash=hash; data.document_hash=claimFixture.report.source.document_hash; }
  if(feature === 'later_outcome') {
    data.document_hash=hash;
    data.body_json={format:'paperfact.later-outcome.v1',state:'queried_no_judged_inputs',
      policy:'followups.empty-query.v1',input_hash:hash,
      query:{request_id:'11111111-1111-4111-8111-111111111111',queried_at:stamp,
        lookup:{title:'Paper',doi:null,s2_id:null,arxiv_id:null},
        providers:{openalex:'queried_empty',semantic_scholar:'unknown'}},
      source:{availability:'available',document_hash:hash,desired_hash:null}};
  }
  return {
    scope,
    feature,
    key,
    data,
    source_document_hash: feature === 'claims' ? data.document_hash : ['reading_goal','reference_edge','list_pin','queue_entry','queue_pin','reading_event'].includes(feature) ? null : hash
  };
}
test(
'UUID5 identities match Python ASCII-escaped Unicode and DEL vectors',
() => {
  const scope = {
    kind: 'paper',
    id: '11111111-1111-4111-8111-111111111111'
  };
  for(const [key, expected] of[['引用α', 'b69dec61-f8b5-586e-a1dc-ece351ad3ea6'], ['🚀', '38458576-b694-51e0-8b17-0c46ec2c5fe8'],
  ['\u007f', '93a69a81-0176-57ba-af6e-e5d3e7dafd24']]) assert.equal(contentId(scope, 'citation', key),
  expected);
  assert.equal(asciiJSON(['中文😀']), '["\\u4e2d\\u6587\\ud83d\\ude00"]');
}
);
for(const feature of Object.keys(CONTENT_FIELDS)) test(
'closed read-only content preserves ' + feature,
async() => {
  const transport = await demoTransport(),
  store = new MemoryStore('demo-workspace', 'demo-phone');
  await store.update(state => receive(state, transport.events));
  const item = payload(feature),
  id = contentId(item.scope, feature, item.key),
  op = operation(
  'research_content',
  id,
  item,
  {
    operationId: 'content-created',
    parents: feature === 'list_pin' ? [ref('list',item.scope.id),ref('paper',PAPER),ref('membership',uuid5Name('paperfact:membership:' + JSON.stringify([item.scope.id,PAPER])))] : [ref(item.scope.kind, item.scope.id)]
  }
  );
  validateOperation(op, 'demo-workspace');
  await store.update(state => receive(
  state,
  [{
    sequence: 7,
    outcome: 'accepted',
    operation: op,
    head: {
      revision: 7,
      operation: op
    }
  }]
  ));
  const view = projection(await store.read()),
  scope =(item.scope.kind === 'paper' ? view.papers: view.lists).find(x => x.id === item.scope.id);
  assert.deepEqual(scope.research_content[0].data, item.data);
  assert.equal(scope.research_content[0].source_document_hash, item.source_document_hash);
}
);
test(
'rich notes preserve anchor/hash/kind/time and reject flattening or delete writes',
async() => {
  const transport = await demoTransport(),
  store = new MemoryStore('demo-workspace', 'demo-phone'),
  engine = new Engine(store, {
    transport
  });
  await engine.connect('fixture-token');
  await engine.sync();
  const rich = {
    paper_id: PAPER,
    body: 'Rich anchored note',
    kind: 'quote',
    created_at: stamp,
    page: 1,
    anchor: {
      p0: 0,
      o0: 1,
      p1: 0,
      o1: 4,
      document_hash: hash
    }
  };
  const op = operation('note', 'rich-note', rich, {
    parents: [ref('paper', PAPER)]
  });
  await store.update(state => receive(
  state,
  [{
    sequence: 7,
    outcome: 'accepted',
    operation: op,
    head: {
      revision: 7,
      operation: op
    }
  }]
  ));
  const note = projection(await store.read()).notes.find(n => n.id === 'rich-note');
  assert.equal(note.editable, false);
  assert.deepEqual(note.anchor, rich.anchor);
  assert.equal(note.pdf_hash, hash);
  assert.equal(note.created_at, stamp);
  const observed = await engine.observeNote('rich-note', PAPER);
  await assert.rejects(engine.saveNote('rich-note', PAPER, 'Plain', {
    observed
  }), /rich_note_read_only/);
  await assert.rejects(engine.deleteNote('rich-note', {
    observed
  }), /rich_note_read_only/);
  assert.equal((await store.read()).outbox.length, 0);
}
);
test(
'malformed feature fields, source hashes, identity, types and timestamp normalization fail closed',
() => {
  const base = payload('dive'),
  parents =[ref('paper', PAPER)],
  id = contentId(base.scope, base.feature, base.key);
  for(const mutate of[x => x.data.extra = 'secret', x => x.feature =['dive'], x => x.data.written_at = '2026-02-30T00:00:00Z',
  x => x.source_document_hash = 'bad', x => x.data.body = null]) {
    const changed = structuredClone(base);
    mutate(changed);
    assert.throws(() => validateContent(changed, id, parents));
  }
  assert.throws(() => validateContent(base, '00000000-0000-4000-8000-000000000009', parents));
  for(const date of['20260101T000000+0000', '2026-W01-4T00:00:00+00:00:00', '2026-01-01T00:00:00Z']) validateContent({
    ...base,
    data: {
      ...base.data,
      written_at: date
    }
  }, id, parents);
  const resource = payload('resource');
  resource.key = 'https:example.org';
  assert.throws(() => validateContent(resource, contentId(resource.scope, resource.feature, resource.key),
  parents));
  const rich = {
    paper_id: [PAPER],
    body: 'Text',
    kind: 'note',
    created_at: stamp,
    page: null,
    anchor: null
  };
  assert.throws(() => validateRichNote(rich));
}
);
test(
'canonical deletion suppresses stale imported analysis/highlights without deleting snapshot text',
async() => {
  const transport = await demoTransport(),
  store = new MemoryStore('demo-workspace', 'demo-phone'),
  engine = new Engine(store, {
    transport
  });
  await engine.connect('fixture-token');
  await engine.sync();
  const imported = structuredClone(demoProjection);
  imported.highlights[0].origin = 'manual';
  await engine.importProjection(imported);
  let sequence = 6;
  for(const feature of['dive', 'manual_highlight']) {
    const item = payload(feature),
    id = contentId(item.scope, feature, item.key),
    op = operation('research_content', id, item, {
      parents: [ref('paper', PAPER)]
    });
    await store.update(state => {
      const n =++ sequence;
      receive(
      state,
      [{
        sequence: n,
        outcome: 'accepted',
        operation: op,
        head: {
          revision: n,
          operation: op
        }
      }]
      );
    });
    const removed = {
      ...op,
      operation_id: 'remove-' + feature,
      action: 'delete',
      payload: {},
      base_revision: sequence
    };
    await store.update(state => {
      const n =++ sequence;
      receive(
      state,
      [{
        sequence: n,
        outcome: 'accepted',
        operation: removed,
        head: {
          revision: n,
          operation: removed
        }
      }]
      );
    });
  }
  const state = await store.read(),
  view = projection(state);
  assert.equal(view.papers[0].analysis_sections.length, 0);
  assert.equal(view.highlights.length, 0);
  assert.equal(view.imported_highlights.length, 1);
  assert.equal(state.readProjection.highlights[0].quote, imported.highlights[0].quote);
}
);


for(const feature of ['highlight_analysis','reading_links','research_questions']) {
  test(`annotation ${feature} preserves known or unknown PDF provenance explicitly`,()=>{
    const value=payload(feature);
    validateContent(value,contentId(value.scope,feature,value.key),[value.scope]);
    value.data.document_hash='b'.repeat(64);
    assert.throws(()=>validateContent(value,contentId(value.scope,feature,value.key),[value.scope]));
    value.data.document_hash=null;
    assert.throws(()=>validateContent(value,contentId(value.scope,feature,value.key),[value.scope]));
    value.source_document_hash=null;
    validateContent(value,contentId(value.scope,feature,value.key),[value.scope]);
  });
}


test('current highlight selection hides historical AI marks even with the same input digest', async()=>{
  const {projectContent} = await import('../content.mjs');
  const analysis=payload('highlight_analysis'), automatic=payload('ai_highlight'), manual=payload('manual_highlight');
  const item=analysis.data.body_json.items[0];
  automatic.data.quote=item.text;
  automatic.data.anchor={p0:item.page-1,o0:0,p1:item.page-1,o1:4};
  const row=value=>({operation:{entity_id:contentId(value.scope,value.feature,value.key),payload:value},revision:1});
  const read=()=>projectContent([{id:PAPER}],[],[row(automatic),row(manual),row(analysis)]);
  assert.deepEqual(read().map(mark=>mark.origin),['ai','manual']);
  analysis.data.body_json.items=[];
  assert.deepEqual(read().map(mark=>mark.origin),['manual']);
  analysis.data.body_json.items=[item];
  analysis.data.source_hash='b'.repeat(64);
  assert.deepEqual(read().map(mark=>mark.origin),['manual']);
  analysis.data.source_hash=hash;
  analysis.data.document_hash='b'.repeat(64);
  assert.deepEqual(read().map(mark=>mark.origin),['manual']);
  analysis.data.document_hash=hash;
  automatic.data.anchor.p0++;
  automatic.data.anchor.p1++;
  assert.deepEqual(read().map(mark=>mark.origin),['manual']);
});

test('canonical deletion hides historical and snapshot AI marks without hiding manual highlights',async()=>{
  const {projectContent,suppressSnapshotContent}=await import('../content.mjs');
  const analysis=payload('highlight_analysis'), automatic=payload('ai_highlight'), manual=payload('manual_highlight');
  const id=contentId(analysis.scope,analysis.feature,analysis.key);
  const old={sequence:1,outcome:'accepted',operation:{entity_type:'research_content',entity_id:id,action:'put',payload:analysis}};
  const removed={revision:2,operation:{entity_type:'research_content',entity_id:id,action:'delete'}};
  const papers=[{id:PAPER,research_content:[{feature:'highlight_analysis',data:analysis.data}]}];
  const archived=[{paper_id:PAPER,origin:'ai',quote:'Prior AI mark'}, {paper_id:PAPER,origin:'manual',quote:'My mark'}];
  const result=suppressSnapshotContent(papers,[],[removed],[old],archived);
  assert.deepEqual(result.live.map(mark=>mark.origin),['manual']);
  const row=value=>({operation:{entity_id:contentId(value.scope,value.feature,value.key),payload:value},revision:1});
  assert.deepEqual(projectContent(papers,[],[row(automatic),row(manual)]).map(mark=>mark.origin),['manual']);
  assert.equal(papers[0].research_content.some(item=>item.feature==='highlight_analysis'),false);
  assert.deepEqual(projectContent([{id:PAPER}],[],[row(automatic)]).map(mark=>mark.origin),['ai']);
});
