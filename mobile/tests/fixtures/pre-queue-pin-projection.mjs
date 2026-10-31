/** Frozen pre-queue-pin validator and transactional import boundary. */
export function requireThat(test,code='invalid_data'){if(!test)throw Error(code);}
export function integer(value){requireThat(Number.isSafeInteger(value)&&value>=0);return value;}
const copy=value=>structuredClone(value),utf8=value=>new TextEncoder().encode(value).length;
export function closed(value, required, optional =[]) {
  requireThat(value && typeof value === 'object' && ! Array.isArray(value));
  requireThat(required.every(key => Object.hasOwn(value, key)) && Object.keys(value).every(key =>[...required,
  ...optional].includes(key)));
}
function boundedText(value, limit, nullable = false) {
  requireThat((nullable && value === null) ||(typeof value === 'string' &&[...value].length <= limit));
}
export function validateProjection(value, workspace) {
  requireThat(value?.schema_version === 1 || value?.schema_version === 2, 'unsupported_version');
  requireThat(value.workspace_id === workspace, 'wrong_workspace');
  integer(value.cursor);
  for(const name of['lists', 'papers', 'notes', 'highlights', 'decks', 'assets']) requireThat(Array.isArray(value[name]) && value[name].length <= 10000);
  requireThat(utf8(JSON.stringify(value)) <= 8 * 1024 * 1024, 'projection_too_large');
  requireThat(value.capabilities?.sync_bootstrap === false, 'unsupported_bootstrap');
  closed(
  value,
  ['schema_version', 'workspace_id', 'cursor', 'capabilities', 'local_state', 'lists', 'papers', 'notes',
  'highlights', 'decks', 'assets'],
  ['list_order']
  );
  // Copy only read-contract fields. Imported credentials/config/path fields never persist.
  const pick =(row, fields) => Object.fromEntries(fields.filter(field => Object.hasOwn(row, field)).map(field =>[field,
  copy(row[field])]));
  const sections = rows =>(rows ??[]).map(row => pick(row, ['kind', 'body', 'written_at']));
  const result = {
    schema_version: value.schema_version,
    workspace_id: workspace,
    cursor: value.cursor,
    capabilities: {
      sync_bootstrap: false
    },
    local_state: {},
    lists: [],
    papers: [],
    notes: [],
    highlights: [],
    decks: [],
    assets: []
  };
  result.lists = value.lists.map(row =>({
    ...pick(row, ['id', 'name', 'note']),
    members: (row.members ??[]).map(member => {
      if(Object.hasOwn(member,'pinned')) {
        requireThat(typeof member.pinned === 'boolean');
        if(member.pinned) {
          boundedText(member.pinned_at,64);
          requireThat(/(Z|[+-]\d\d:\d\d)$/.test(member.pinned_at) && Number.isFinite(Date.parse(member.pinned_at)));
        } else requireThat(member.pinned_at === null || member.pinned_at === undefined);
      }
      if(Object.hasOwn(member,'pinned_at')) requireThat(Object.hasOwn(member,'pinned'));
      return pick(member, ['id', 'paper_id', 'position', 'state','pinned','pinned_at']);
    }),
    analysis_sections: sections(row.analysis_sections)
  }));
  result.papers = value.papers.map(row =>({
    ...pick(row, ['id', 'title', 'authors', 'year', 'doi', 'url', 'pdf_asset_id']),
    analysis_sections: sections(row.analysis_sections),
    citations: (row.citations ??[]).map(c => pick(c, ['ref_key', 'title', 'doi', 'purpose', 'gist', 'verdict',
    'why', 'basis', 'year']))
  }));
  result.notes = value.notes.map(row =>({
    ...pick(row, ['id', 'paper_id', 'body', 'kind', 'page', 'revision', 'anchor', 'pdf_hash', 'anchor_status']),
    editable: false
  }));
  result.highlights = value.highlights.map(row => pick(row, ['id', 'paper_id', 'origin', 'quote', 'reason',
  'hidden', 'pdf_hash', 'anchor', 'anchor_status']));
  for(const rows of[result.notes, result.highlights]) for(const row of rows) {
    if(row.anchor !== null && row.anchor !== undefined) {
      const a = row.anchor;
      closed(a, ['schema_version', 'kind', 'p0', 'o0', 'p1', 'o1']);
      requireThat(a.schema_version === 1 && a.kind === 'word_range');
      for(const n of['p0', 'o0', 'p1', 'o1']) integer(a[n]);
    }
  }
  return result;
}
export class LegacyProjectionImporter {
  constructor(store){this.store=store;this.onChange=()=>{};}
  async importProjection(value) {
    await this.store.update(state => {
      state.readProjection = validateProjection(value, state.workspace);
    });
    this.onChange('projection_loaded');
  }
}
