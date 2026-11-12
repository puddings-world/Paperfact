/** Each scope is one atomic record: content, drafts, outbox, receipts and cursor. */
export function scopeKey(workspace, device) {
  return JSON.stringify([workspace, device]);
}
export const copy = value => structuredClone(value);
export const own =(record, key) => Object.hasOwn(record, key) ? record[key]: undefined;
export function put(record, key, value) {
  Object.defineProperty(record, key, {
    value,
    enumerable: true,
    writable: true,
    configurable: true
  });
}
export function emptyState(workspace, device) {
  return {
    workspace,
    device,
    cursor: 0,
    entities: {},
    graph: {},
    receipts: {},
    outbox: [],
    conflicts: {},
    drafts: {},
    draftBases: {},
    files: {},
    artifactFiles: {},
    appliedArtifacts: {},
    selection: {
      list: null,
      paper: null
    },
    readProjection: null
  };
}
export class MemoryStore {
  constructor(workspace, device, state = null) {
    this.value = copy(state ?? emptyState(workspace, device));
    this.failure = null;
  }
  async read() {
    return copy(this.value);
  }
  async update(change) {
    const draft = copy(this.value),
    result = change(draft);
    if(result?.then) throw new Error('transaction_callback_must_be_synchronous');
    if(this.failure) throw new Error(this.failure);
    this.value = draft;
    return copy(result);
  }
}
export class IndexedStore {
  constructor(db, workspace, device, {existingOnly=false}={}) {
    this.db = db;
    this.existingOnly = existingOnly;
    this.workspace = workspace;
    this.device = device;
    this.key = scopeKey(workspace, device);
  }
  static async open(workspace, device, indexedDB = globalThis.indexedDB) {
    if(! indexedDB) throw new Error('storage_unavailable');
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('paperfact-mobile-v1', 1);
      request.onupgradeneeded =() => request.result.createObjectStore('scopes');
      request.onsuccess =() => resolve(request.result);
      request.onerror =() => reject(new Error('storage_unavailable'));
      request.onblocked =() => reject(new Error('storage_blocked'));
    });
    db.onversionchange =() => db.close();
    return new IndexedStore(db, workspace, device);
  }
  static async openExisting(workspace,device,indexedDB=globalThis.indexedDB) {
    if(!indexedDB)throw Error('storage_unavailable');
    const db=await new Promise((resolve,reject)=>{
      let absent=false,settled=false;
      const request=indexedDB.open('paperfact-mobile-v1',1);
      request.onupgradeneeded=()=>{absent=true;request.transaction.abort();};
      request.onerror=event=>{event.preventDefault();if(settled)return;settled=true;absent?resolve(null):reject(Error('storage_unavailable'));};
      request.onblocked=()=>{settled=true;reject(Error('storage_blocked'));};
      request.onsuccess=()=>{
        const opened=request.result;
        if(settled){opened.close();return;}
        settled=true;
        if(!opened.objectStoreNames.contains('scopes')){opened.close();reject(Error('storage_unavailable'));return;}
        opened.onversionchange=()=>opened.close();resolve(opened);
      };
    });
    if(db===null)return null;
    const store=new IndexedStore(db,workspace,device,{existingOnly:true});
    try { await store.read();return store; }
    catch(error){store.close();if(error.message==='workspace_not_cached')return null;throw error;}
  }
  async read() {
    return this.transaction('readonly', null);
  }
  async update(change) {
    return this.transaction('readwrite', change);
  }
  transaction(mode, change) {
    return new Promise((resolve, reject) => {
      let result,
      failure;
      const tx = this.db.transaction('scopes', mode),
      table = tx.objectStore('scopes');
      const request = table.get(this.key);
      request.onsuccess =() => {
        try {
          if(this.existingOnly && request.result===undefined)throw Error('workspace_not_cached');
          if(this.existingOnly && (!request.result || typeof request.result!=='object' || Array.isArray(request.result)))throw Error('wrong_scope');
          const state = request.result ?? emptyState(this.workspace, this.device);
          if(state.workspace !== this.workspace || state.device !== this.device) throw new Error('wrong_scope');
          result = change ? change(state): state;
          if(result?.then) throw new Error('transaction_callback_must_be_synchronous');
          if(change) table.put(state, this.key);
        } catch(error) {
          failure = error;
          tx.abort();
        }
      };
      tx.oncomplete =() => resolve(copy(result));
      tx.onabort = tx.onerror =() => reject(failure ?? new Error('storage_write_failed'));
    });
  }
  close() {
    this.db.close();
  }
}
