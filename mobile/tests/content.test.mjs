import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CONTENT_FIELDS,
  validateContent,
  validateRichNote
} from '../content.mjs';
import {
  asciiJSON,
  contentId
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
    kind: feature === 'list_survey' ? 'list': 'paper',
    id: feature === 'list_survey' ? 'demo-list': PAPER
  };
  const key =['manual_highlight', 'chat'].includes(feature) ? '00000000-0000-4000-8000-000000000002': feature === 'ai_highlight' ? hash + ':claim': feature === 'resource' ? 'https://example.org/code': feature === 'citation' ? '引用🚀': feature === 'followup' ? 'work-1': 'main';
  const data = {};
  for(const field of CONTENT_FIELDS[feature].split(' ')) {
    data[field] =['created_at', 'written_at', 'fetched_at', 'checked_at'].includes(field) ? stamp: ['edited',
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
  return {
    scope,
    feature,
    key,
    data,
    source_document_hash: hash
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
    parents: [ref(item.scope.kind, item.scope.id)]
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
  assert.equal(scope.research_content[0].source_document_hash, hash);
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
