import { fileId } from './artifacts.mjs';
/** Full-stack fixture: JavaScript client → actual Python HTTP/reference service. */
import {
  spawn
} from 'node:child_process';
import {
  fileURLToPath
} from 'node:url';
import {
  createInterface
} from 'node:readline';
import assert from 'node:assert/strict';
import {
  HttpTransport
} from './transport.mjs';
import {
  MemoryStore
} from './store.mjs';
import {
  Engine
} from './engine.mjs';
import {
  demoTransport,
  PAPER,
  MEMBER
} from './fixture.mjs';
import {
  projection
} from './domain.mjs';
import {
  contentId
} from './ids.mjs';
const executable = process.argv[2];
if(! executable) throw new Error('Pass the project Python executable.');
const child = spawn(
executable,
[fileURLToPath(new URL('./service-fixture.py', import.meta.url)), ...(process.argv[3] ?[process.argv[3]]: [])],
{
  stdio: ['pipe', 'pipe', 'pipe'],
  windowsHide: true
}
);
let errors = '';
child.stderr.on('data', chunk => {
  errors += chunk;
});
const ready = await new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error('Fixture service did not start')), 15000);
  createInterface({
    input: child.stdout
  }).once(
  'line',
  line => {
    clearTimeout(timer);
    resolve(JSON.parse(line));
  }
  );
  child.once(
  'exit',
  code => {
    clearTimeout(timer);
    reject(new Error('Fixture exited ' + code + ': ' + errors));
  }
  );
});
try {
  const transport = new HttpTransport(ready.url),
  fixture = await demoTransport();
  const post = async(route, body, token) => {
    const response = await fetch(
    ready.url + route,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + token
      },
      body: JSON.stringify(body)
    }
    );
    assert.equal(response.status, 200, await response.clone().text());
    return response.json();
  };
  const target = fixture.events.at(- 1).operation.payload,
  bytes = fixture.blobs.get(target.sha256);
  const upload = await post('/v1/blobs/begin', {
    sha256: target.sha256,
    size: target.size
  }, ready.desktop_token);
  await post(
  '/v1/blobs/append',
  {
    upload_id: upload.upload_id,
    offset: 0,
    data: Buffer.from(bytes).toString('base64')
  },
  ready.desktop_token
  );
  await post('/v1/blobs/commit', {
    upload_id: upload.upload_id
  }, ready.desktop_token);
  for(const event of fixture.events) assert.equal((await transport.push(ready.desktop_token, event.operation)).outcome,
  'accepted');
  const store = new MemoryStore('demo-workspace', 'demo-phone'),
  engine = new Engine(store, {
    transport
  });
  await engine.connect(ready.token);
  await engine.sync();
  assert.equal((await store.read()).cursor, 6);
  const observed = await engine.observeNote('demo-note', PAPER);
  await engine.draft('demo-note', 'Draft kept while desktop analysis arrives', observed);
  const scope = {
    kind: 'paper',
    id: PAPER
  };
  const richOps =[{
    entity_type: 'research_content',
    entity_id: contentId(scope, 'dive', 'main'),
    payload: {
      scope,
      feature: 'dive',
      key: 'main',
      data: {
        body: 'Actual desktop analysis',
        written_at: '2026-01-01T00:00:00+00:00',
        spec: null
      },
      source_document_hash: target.sha256
    }
  }, {
    entity_type: 'note',
    entity_id: 'desktop-anchored',
    payload: {
      paper_id: PAPER,
      body: 'Anchored desktop note',
      kind: 'note',
      created_at: '2026-01-01T00:00:00+00:00',
      page: 1,
      anchor: {
        p0: 0,
        o0: 1,
        p1: 0,
        o1: 3,
        document_hash: target.sha256
      }
    }
  }];
  for(const [index, value] of richOps.entries()) {
    const op = {
      version: 2,
      operation_id: 'rich-desktop-' + index,
      workspace_id: 'demo-workspace',
      device_id: 'demo-desktop',
      ...value,
      action: 'put',
      base_revision: 0,
      depends_on: null,
      incarnation: 'rich-desktop-' + index,
      parents: [{
        kind: 'paper',
        id: PAPER,
        incarnation: PAPER + '-created'
      }],
      structure_revision: 0
    };
    assert.equal((await transport.push(ready.desktop_token, op)).outcome, 'accepted');
  }
  await engine.sync();
  let richState = await store.read();
  assert.equal(richState.drafts['demo-note'], 'Draft kept while desktop analysis arrives');
  assert.deepEqual(richState.draftBases['demo-note'], observed);
  const richView = projection(richState);
  assert.equal(richView.papers[0].analysis_sections[0].body, 'Actual desktop analysis');
  assert.equal(richView.papers[0].analysis_sections[0].source_document_hash, target.sha256);
  assert.equal(richView.notes.find(n => n.id === 'desktop-anchored').editable, false);
  await assert.rejects(
  engine.saveNote(
  'desktop-anchored',
  PAPER,
  'Do not flatten',
  {
    observed: await engine.observeNote('desktop-anchored', PAPER)
  }
  ),
  /rich_note_read_only/
  );
  await saveCurrent(engine, 'phone-note', PAPER, 'Actual Python authority', {
    operationId: 'phone-note-one'
  });
  await saveCurrent(engine, 'phone-note', PAPER, 'Actual Python authority, revised', {
    operationId: 'phone-note-two'
  });
  await engine.reading(MEMBER, 'demo-list', PAPER, 'read');
  await engine.sync();
  let state = await store.read();
  assert.equal(state.outbox.length, 0);
  assert.equal(projection(state).notes.find(n => n.id === 'phone-note').body, 'Actual Python authority, revised');
  assert.equal(projection(state).lists[0].members[0].state, 'read');
  const operation = state.receipts['phone-note-two'].operation;
  assert.equal((await transport.push(ready.token, operation)).sequence, state.receipts['phone-note-two'].sequence);
  await engine.download(PAPER);
  assert.deepEqual((await engine.pdf(PAPER)).bytes, bytes);
  await saveCurrent(engine, 'phone-note', PAPER, 'Offline phone branch', {
    operationId: 'phone-conflict'
  });
  const peer = {
    ...operation,
    operation_id: 'desktop-concurrent',
    device_id: 'demo-desktop',
    base_revision: state.entities['note/phone-note'].revision,
    depends_on: null,
    payload: {
      paper_id: PAPER,
      body: 'Concurrent desktop branch'
    }
  };
  assert.equal((await transport.push(ready.desktop_token, peer)).outcome, 'accepted');
  await engine.sync();
  state = await store.read();
  assert.equal(state.conflicts['phone-conflict'].event.outcome, 'conflict');
  await engine.resolve('phone-conflict', {
    body: 'Explicit combined text'
  });
  await engine.sync();
  state = await store.read();
  assert.ok(state.conflicts['phone-conflict'].resolvedBy);
  assert.equal(projection(state).notes.find(n => n.id === 'phone-note').body, 'Explicit combined text');
  await saveCurrent(engine, 'phone-note', PAPER, 'Edit immediately before deletion');
  await deleteCurrent(engine, 'phone-note');
  await engine.sync();
  state = await store.read();
  assert.equal(state.entities['note/phone-note'].operation.action, 'delete');
  assert.equal(state.outbox.length, 0);
  // Python serializes float coordinates as 200.0; keep authoritative raw bytes.
  const artifact = ready.artifact;
  assert.ok(Buffer.from(artifact.blobs[artifact.payload.body.sha256],'base64').toString('utf8').includes('200.0'));
  for(const description of [artifact.payload.body,...artifact.payload.assets]) {
    const data = Buffer.from(artifact.blobs[description.sha256],'base64');
    const upload = await post('/v1/blobs/begin',{sha256:description.sha256,size:data.length},ready.desktop_token);
    await post('/v1/blobs/append',{upload_id:upload.upload_id,offset:0,data:data.toString('base64')},ready.desktop_token);
    await post('/v1/blobs/commit',{upload_id:upload.upload_id},ready.desktop_token);
  }
  const artifactId = fileId(PAPER,'notes');
  const artifactOp = {version:2,operation_id:'desktop-deck',workspace_id:'demo-workspace',device_id:'demo-desktop',
    entity_type:'research_file',entity_id:artifactId,action:'put',base_revision:0,depends_on:null,
    payload:artifact.payload,incarnation:'desktop-deck',parents:[{kind:'paper',id:PAPER,incarnation:PAPER+'-created'}],structure_revision:0};
  assert.equal((await transport.push(ready.desktop_token,artifactOp)).outcome,'accepted');
  await engine.sync();
  assert.equal(projection(await store.read()).decks[0].id,artifactId);
  await engine.downloadArtifact(artifactId); engine.disconnect();
  const deck = await engine.deck(artifactId);
  assert.equal(deck.body.deck.title,'研究 🧪');
  assert.equal(deck.body.deck.slides[0].elements[1].x,200);
  assert.equal(deck.body.deck.slides[0].speaker_notes,'原文引用與講稿');
  console.log('PASS actual Python HTTP authority: session, seed history, rich analysis + anchored note without draft loss, offline note chain, reading state, retry, verified PDF, conflict resolution, edit-delete and verified Python float/Unicode deck+PNG offline closure');
} finally {
  child.stdin.end('\n');
  await new Promise(resolve => {
    child.once('exit', resolve);
    setTimeout(() => {
      child.kill();
      resolve();
    }, 5000).unref();
  });
}
async function saveCurrent(engine, id, paperId, body, options = {}) {
  return engine.saveNote(id, paperId, body, {
    observed: await engine.observeNote(id, paperId),
    ...options
  });
}
async function deleteCurrent(engine, id, options = {}) {
  const state = await engine.store.read();
  const row = state.entities['note/' + id]?.operation;
  const pending =[...state.outbox].reverse().find(item => item.operation.entity_type === 'note' && item.operation.entity_id === id)?.operation;
  const source = pending ?? row;
  const paper = source?.payload.paper_id ?? source?.parents.find(parent => parent.kind === 'paper')?.id;
  return engine.deleteNote(id, {
    observed: await engine.observeNote(id, paper),
    ...options
  });
}
