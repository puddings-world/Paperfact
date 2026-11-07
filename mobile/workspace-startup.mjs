/** A bounded local resume hint. It is neither a credential nor sync authority. */
export const WORKSPACE_HINT_KEY='paperfact.last-workspace.v1';
const ID=/^[A-Za-z0-9_.:-]{1,128}$/;

function validate(value) {
  if(!value || typeof value!=='object' || Array.isArray(value) ||
    Object.keys(value).length!==4 || !['version','workspace','device','origin'].every(k=>Object.hasOwn(value,k)) ||
    value.version!==1 || typeof value.workspace!=='string' || !ID.test(value.workspace) ||
    typeof value.device!=='string' || !ID.test(value.device) || typeof value.origin!=='string' || value.origin.length>1024)
    throw Error('invalid_workspace_hint');
  const url=new URL(value.origin);
  if(url.origin!==value.origin || url.username || url.password || url.search || url.hash || url.pathname!=='/' ||
    !(url.protocol==='https:' || (url.protocol==='http:' && ['127.0.0.1','[::1]'].includes(url.hostname))))
    throw Error('invalid_workspace_hint');
  return {version:1,workspace:value.workspace,device:value.device,origin:url.origin};
}
function storageFor(storage) { return storage===undefined?globalThis.localStorage:storage; }

export function readWorkspaceHint(storage) {
  let raw;
  try { raw=storageFor(storage).getItem(WORKSPACE_HINT_KEY); }
  catch { return {status:'unavailable',hint:null}; }
  if(raw===null || raw===undefined)return {status:'empty',hint:null};
  try {
    if(typeof raw!=='string' || raw.length>2048)throw Error('invalid_workspace_hint');
    return {status:'ready',hint:validate(JSON.parse(raw))};
  } catch { return {status:'invalid',hint:null}; }
}

export function rememberWorkspace(value,storage) {
  try {
    if(!value || Object.keys(value).length!==3 || !['workspace','device','origin'].every(k=>Object.hasOwn(value,k)))return false;
    const hint=validate({version:1,...value});
    storageFor(storage).setItem(WORKSPACE_HINT_KEY,JSON.stringify(hint));
    return true;
  } catch { return false; }
}

export function forgetWorkspaceHint(storage) {
  try { storageFor(storage).removeItem(WORKSPACE_HINT_KEY);return true; }
  catch { return false; }
}
