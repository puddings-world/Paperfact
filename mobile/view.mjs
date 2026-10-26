/** UI state is separate from canonical synchronization state. */
import {
  put,
  copy
} from './store.mjs';
export class ReaderView {
  constructor() {
    this.list = null;
    this.paper = null;
    this.tab = 'overview';
    this.note = null;
    this.drafts = {};
    this.observed = {};
    this.dirty = new Set();
    this.scroll = {};
  }
  select(list, paper = null) {
    this.list = list;
    this.paper = paper;
    this.note = null;
  }
  edit(id, body) {
    put(this.drafts, id, body);
    this.dirty.add(id);
  }
  saved(id, body) {
    if(this.drafts[id] === body) this.dirty.delete(id);
  }
  refresh(state) {
    // Incoming data never selects another paper, overwrites a draft or scrolls.
    for(const [id, body] of Object.entries(state.drafts)) if(! Object.hasOwn(this.drafts, id)) put(this.drafts,
    id, body);
    for(const [id, base] of Object.entries(state.draftBases ?? {})) if(! Object.hasOwn(this.observed,
    id)) put(this.observed, id, base);
    if(this.list === null && state.selection?.list) {
      this.list = state.selection.list;
      this.paper = state.selection.paper;
    }
  }
}
export function safeLink(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && ! url.username && ! url.password ? url.href: null;
  } catch {
    return null;
  }
}
export async function flushDrafts(store, view) {
  const pending =[...view.dirty].filter(id => Object.hasOwn(view.drafts, id)).map(id =>({
    id,
    body: view.drafts[id],
    observed: copy(view.observed[id] ?? null)
  }));
  if(! pending.length) return;
  await store.update(state => {
    state.draftBases ??= {};
    for(const draft of pending) {
      put(state.drafts, draft.id, draft.body);
      if(draft.observed) put(state.draftBases, draft.id, draft.observed);
    }
  });
}
