/** Origin-wide browser persistence; never a research write or a per-paper pin. */
export class BrowserStorageProtection {
 constructor(storage) {
  try {this.storage=arguments.length?storage:globalThis.navigator?.storage;}catch {this.storage=null;}
  this.status='unknown';this.pending=null;this.serial=0;
 }
 get supported(){try {return typeof this.storage?.persisted==='function' && typeof this.storage?.persist==='function';}catch {return false;}}
 snapshot(){return {status:this.supported?this.status:'unsupported',phase:this.pending?.kind??null,supported:this.supported};}
 inspect(){return this.pending?.promise??this.run('inspect',()=>this.storage.persisted());}
 request(){
  if(this.pending?.kind==='request')return this.pending.promise;
  // Invoke synchronously from the explicit click; do not wait for an old query.
  return this.run('request',()=>this.storage.persist());
 }
 run(kind,operation) {
  if(!this.supported)return Promise.resolve(this.snapshot());
  const serial=++this.serial,pending={kind,promise:null};this.pending=pending;
  let result;
  try {result=operation();}catch {result=Promise.reject(Error('storage_unavailable'));}
  pending.promise=Promise.resolve(result).then(value=>{
   if(serial===this.serial)this.status=typeof value==='boolean'?(value?'persistent':'best_effort'):'unknown';
  },()=>{if(serial===this.serial)this.status='unknown';}).finally(()=>{
   if(this.pending===pending)this.pending=null;
  }).then(()=>this.snapshot());
  return pending.promise;
 }
}

export function storageProtectionPanel(el,{controller,t,current=()=>true}={}) {
 let disposed=false;
 const status=el('p',{'data-storage-status':'','role':'status','aria-live':'polite'}),
  request=el('button',{type:'button',class:'quiet','data-storage-request':'',onclick:()=>{void ask();}},t('storageProtect')),
  element=el('section',{class:'storage-protection','aria-label':t('storageTitle')},
   el('h3',{},t('storageTitle')),status,request,el('p',{class:'muted'},t('storageHelp')));
 const live=()=>!disposed && current() && element.isConnected;
 function show(initial=false) {
  if(!initial&&!live())return;
  const state=controller.snapshot();
  const key=state.phase==='request'?'storageRequesting':state.phase==='inspect'&&state.status==='unknown'?
   'storageChecking':({persistent:'storagePersistent',best_effort:'storageTemporary',unsupported:'storageUnsupported',unknown:'storageUnknown'})[state.status];
  status.textContent=t(key);element.setAttribute('data-storage-state',state.status);
  request.textContent=t(state.status==='persistent'?'storageEnabled':'storageProtect');
  request.disabled=!state.supported || state.phase==='request' || state.status==='persistent';
  request.setAttribute('aria-busy',String(state.phase==='request'));
 }
 function refresh() {
  if(disposed||!current())return Promise.resolve(false);
  const pending=controller.inspect();show(true);
  return pending.then(()=>{show();return live();});
 }
 function ask() {
  if(!live())return Promise.resolve(false);
  const pending=controller.request();show();
  return pending.then(()=>{show();return live();});
 }
 show(true);void refresh();
 return {element,status,button:request,refresh,request:ask,dispose:()=>{disposed=true;}};
}
