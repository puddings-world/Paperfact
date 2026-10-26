/** Synthetic service adapter. Never used as production authorization. */
import {
  emptyState,
  copy
} from './store.mjs';
import {
  active,
  keyOf,
  receive,
  requireThat,
  stable,
  validateOperation
} from './domain.mjs';
import {
  sha256
} from './engine.mjs';
export const PAPER = '00000000-0000-4000-8000-000000000001';
export const MEMBER = 'ffc29204-612e-5b34-adb4-ce4a690d9e5c';
export function operation(kind, id, payload, {
  operationId = id + '-created',
  device = 'demo-desktop',
  parents =[],
  action = 'put',
  base = 0,
  incarnation = operationId,
  structure = 0
} = {}) {
  return {
    version: 2,
    operation_id: operationId,
    workspace_id: 'demo-workspace',
    device_id: device,
    entity_type: kind,
    entity_id: id,
    action,
    base_revision: base,
    depends_on: null,
    payload,
    incarnation,
    parents,
    structure_revision: structure
  };
}
export const ref =(kind, id, incarnation = id + '-created') =>({
  kind,
  id,
  incarnation
});
export class FixtureTransport {
  constructor({
    workspace = 'demo-workspace',
    device = 'demo-phone',
    events =[]
  } = {}) {
    this.workspace = workspace;
    this.device = device;
    this.events = copy(events);
    this.state = emptyState(workspace, 'authority');
    receive(this.state, this.events);
    this.blobs = new Map();
    this.revoked = false;
    this.offline = false;
    this.loseResponse = false;
    this.calls =[];
  }
  check(token, signal) {
    requireThat(! signal?.aborted, 'cancelled');
    requireThat(! this.offline, 'connection_failed');
    requireThat(! this.revoked && token === 'fixture-token', 'session_denied');
  }
  async session_info(token, signal) {
    this.check(token, signal);
    return {
      workspace_id: this.workspace,
      device_id: this.device
    };
  }
  async push(token, op, signal) {
    this.check(token, signal);
    this.calls.push(['push', op.operation_id]);
    validateOperation(op, this.workspace);
    requireThat(op.device_id === this.device, 'wrong_device');
    const prior = this.state.receipts[op.operation_id];
    if(prior) {
      requireThat(stable(prior.operation) === stable(op), 'changed_retry');
      return copy(prior);
    }
    const head = this.state.entities[keyOf(op.entity_type, op.entity_id)],
    graph = this.state.graph[keyOf(op.entity_type, op.entity_id)];
    let base = op.base_revision,
    accepted = true;
    if(op.depends_on) {
      const dep = this.state.receipts[op.depends_on];
      requireThat(
      dep && dep.operation.device_id === op.device_id && dep.operation.entity_id === op.entity_id && dep.operation.entity_type === op.entity_type,
      'missing_dependency'
      );
      base = dep.sequence;
      accepted = dep.outcome === 'accepted';
    }
    accepted = accepted && base ===(head?.revision ?? 0);
    for(const parent of op.parents ??[]) {
      const value = this.state.graph[keyOf(parent.kind, parent.id)];
      requireThat(value, 'missing_parent');
      if(! active(this.state, parent.kind, parent.id) || value.incarnation !== parent.incarnation) accepted = false;
    }
    if(graph) {
      if(op.action === 'put') accepted = accepted &&(active(this.state, op.entity_type, op.entity_id) ? op.incarnation === graph.incarnation: op.incarnation === op.operation_id && op.incarnation !== graph.incarnation);
      else {
        const marker = op.structure_depends_on ? this.state.receipts[op.structure_depends_on]?.sequence: op.structure_revision;
        accepted = accepted && op.incarnation === graph.incarnation && marker === graph.structure_revision;
      }
    } else accepted = accepted && op.incarnation === op.operation_id;
    if(op.resolution_of) {
      const conflict = this.state.receipts[op.resolution_of];
      requireThat(
      conflict?.outcome === 'conflict' && conflict.operation.entity_type === op.entity_type && conflict.operation.entity_id === op.entity_id,
      'unknown_conflict'
      );
    }
    const sequence = this.events.length + 1,
    event = {
      sequence,
      outcome: accepted ? 'accepted': 'conflict',
      operation: copy(op),
      head: accepted ? {
        revision: sequence,
        operation: copy(op)
      }
      : {
        revision: head?.revision ?? 0,
        operation: copy(head?.operation ?? null)
      }
    };
    receive(this.state, [event]);
    this.events.push(event);
    if(this.persist) await this.persist(copy(this.events));
    if(this.loseResponse) {
      this.loseResponse = false;
      throw new Error('connection_failed');
    }
    return copy(event);
  }
  async pull(token, after = 0, limit = 100, signal) {
    this.check(token, signal);
    requireThat(after <= this.events.length, 'event_gap');
    this.calls.push(['pull', after]);
    return copy(this.events.slice(after, after + Math.min(limit, 4)));
  }
  async blob_read(token, hash, size, offset, limit, signal) {
    this.check(token, signal);
    this.calls.push(['blob', hash, offset]);
    const blob = this.blobs.get(hash);
    requireThat(blob && blob.length === size, 'file_unavailable');
    return blob.slice(offset, offset + limit);
  }
}
function pdfFixture() {
  const lines =['%PDF-1.4\n'],
  offsets =[0];
  const stream = 'BT /F1 24 Tf 48 730 Td (Paperfact demo research) Tj 0 -42 Td /F1 13 Tf (Synthetic material. No personal research.) Tj ET';
  const objects =['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
  '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`];
  objects.forEach((body, index) => {
    offsets.push(lines.join('').length);
    lines.push(`${index+1} 0 obj\n${body}\nendobj\n`);
  });
  const start = lines.join('').length;
  lines.push(`xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(n=>String(n).padStart(10,'0')+' 00000 n \n').join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`);
  return new TextEncoder().encode(lines.join(''));
}
export async function demoTransport(history = null) {
  const data = pdfFixture(),
  hash = await sha256(data);
  const ops =[operation(
  'list',
  'demo-list',
  {
    name: 'Learning across disciplines',
    note: 'A small synthetic workspace to explore offline research.'
  }
  ), operation(
  'paper',
  PAPER,
  {
    title: 'How explanations help us learn',
    authors: ['A. Researcher', 'B. Collaborator'],
    year: 2026,
    venue: 'Demo collection',
    abstract: 'A synthetic paper about making complex ideas understandable. Explore the explanation, keep a note, and try reading offline.',
    doi: null,
    arxiv_id: null,
    s2_id: null,
    page_url: null,
    pdf_url: null,
    source: 'fixture'
  }
  ), operation(
  'membership',
  MEMBER,
  {
    list_id: 'demo-list',
    paper_id: PAPER,
    citation: null,
    added_at: '2026-01-01T00:00:00Z'
  },
  {
    parents: [ref('list', 'demo-list'), ref('paper', PAPER)]
  }
  ), operation(
  'reading_state',
  MEMBER,
  {
    list_id: 'demo-list',
    paper_id: PAPER,
    state: 'pending',
    delivered_at: null,
    read_at: null
  },
  {
    operationId: 'demo-reading-created',
    parents: [ref('membership', MEMBER), ref('list', 'demo-list'), ref('paper', PAPER)]
  }
  ), operation(
  'note',
  'demo-note',
  {
    paper_id: PAPER,
    body: 'Connect the main argument to a concrete example before evaluating the evidence.'
  },
  {
    parents: [ref('paper', PAPER)]
  }
  ), operation(
  'paper_document',
  PAPER,
  {
    paper_id: PAPER,
    sha256: hash,
    size: data.length,
    media_type: 'application/pdf'
  },
  {
    operationId: 'demo-pdf-created',
    parents: [ref('paper', PAPER)]
  }
  )];
  const events = ops.map((op, i) =>({
    sequence: i + 1,
    outcome: 'accepted',
    operation: op,
    head: {
      revision: i + 1,
      operation: op
    }
  }));
  const transport = new FixtureTransport({
    events: history ?? events
  });
  transport.blobs.set(hash, data);
  return transport;
}
export const demoProjection = {
  schema_version: 2,
  workspace_id: 'demo-workspace',
  cursor: 6,
  capabilities: {
    sync_bootstrap: false,
    database_read_projection: true,
    decks: false,
    assets: true
  },
  local_state: {
    pending_operations: 0,
    awaiting_receipts: 0,
    deferred_entities: 0
  },
  lists: [],
  papers: [{
    id: PAPER,
    analysis_sections: [{
      kind: 'deep_reading',
      body: 'Background\nGood explanations connect unfamiliar claims to familiar ideas.\n\nKey idea\nAn explanation should make assumptions explicit, then connect a method to the evidence that supports it.\n\nResearch question\nWhat evidence would change the conclusion? This is synthetic demonstration text.',
      written_at: null
    }],
    citations: [{
      title: 'A synthetic predecessor',
      gist: 'Earlier work motivates asking how people transfer knowledge.',
      year: 2024
    }]
  }],
  notes: [],
  highlights: [{
    id: 'demo-highlight',
    paper_id: PAPER,
    quote: 'Synthetic material. No personal research.',
    reason: 'Identifies the scope of this demonstration.',
    hidden: false,
    pdf_hash: null,
    anchor: null,
    anchor_status: 'absent'
  }],
  decks: [],
  assets: []
};
