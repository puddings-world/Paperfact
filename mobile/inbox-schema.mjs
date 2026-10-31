/** Closed capture text; importing this module never fetches or opens an address. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const STAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/;
export const INBOX_KINDS = ['doi','url','idea'];
export const INBOX_STATES = ['new','kept','dismissed'];
const SPACE=/[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/;
export const inboxTrim=value=>value.replace(/^[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g,'');
const utf8 = value => new TextEncoder().encode(value).length;
export function requireInbox(value, code='invalid_inbox') { if(!value) throw new Error(code); }
export function inboxUUID(value) {
  requireInbox(typeof value==='string' && UUID.test(value)); return value;
}
export function inboxStamp(value) {
  requireInbox(typeof value==='string' && value.length<=64);
  const match=STAMP.exec(value); requireInbox(match);
  const [year,month,day,hour,minute,second]=match.slice(1,7).map(Number);
  const leap=year%4===0 && (year%100!==0 || year%400===0);
  const days=[31,leap?29:28,31,30,31,30,31,31,30,31,30,31];
  requireInbox(year>=1 && month>=1 && month<=12 && day>=1 && day<=days[month-1] &&
    hour<=23 && minute<=59 && second<=59 && Number.isFinite(Date.parse(value)));
}
export function inboxDisplay(kind,text) {
  const value=inboxTrim(text);
  return kind==='doi'?value.replace(/^(?:doi:\s*|https?:\/\/(?:dx\.)?doi\.org\/)/i,'').toLowerCase():value;
}
export function validateInbox(value) {
  requireInbox(value && typeof value==='object' && !Array.isArray(value));
  const fields=['kind','text','state','created_at','updated_at'];
  requireInbox(Object.keys(value).length===fields.length && fields.every(key=>Object.hasOwn(value,key)));
  requireInbox(INBOX_KINDS.includes(value.kind) && INBOX_STATES.includes(value.state));
  requireInbox(typeof value.text==='string' && inboxTrim(value.text) && [...value.text].length<=2048 &&
    utf8(value.text)<=8192 && new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(new TextEncoder().encode(value.text))===value.text && !/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value.text));
  const text=inboxDisplay(value.kind,value.text);
  if(value.kind==='doi') requireInbox(/^10\.[0-9]{4,9}\/.+$/.test(text) && !SPACE.test(text));
  if(value.kind==='url') {
    requireInbox(/^https?:\/\/[^/?#]+/i.test(text) && !SPACE.test(text) && !/[\x00-\x20\x7f\\]/.test(text));
    let url; try { url=new URL(text); } catch { throw new Error('invalid_inbox'); }
    requireInbox(['http:','https:'].includes(url.protocol) && url.hostname && !url.username && !url.password);
    requireInbox(!text.split('/')[2]?.includes('%') && !text.split('/')[2]?.includes('@'));
  }
  inboxStamp(value.created_at); inboxStamp(value.updated_at); return value;
}
export function validateInboxProjection(value) {
  requireInbox(value && typeof value==='object' && !Array.isArray(value) &&
    Object.keys(value).length===2 && Array.isArray(value.items) && Number.isSafeInteger(value.retained) && value.retained>=0 && value.retained<=100000);
  requireInbox(Object.hasOwn(value,'items') && Object.hasOwn(value,'retained') && value.items.length<=10000);
  const ids=new Set();
  for(const row of value.items) {
    requireInbox(row && typeof row==='object' && !Array.isArray(row) &&
      Object.keys(row).length===6 && ['id','payload','active','version','incarnation','sync_state'].every(key=>Object.hasOwn(row,key)));
    inboxUUID(row.id); requireInbox(!ids.has(row.id)); ids.add(row.id);
    requireInbox(typeof row.active==='boolean' && ['local','pending','awaiting','deferred','synced','conflict'].includes(row.sync_state));
    for(const key of ['version','incarnation']) requireInbox(typeof row[key]==='string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(row[key]));
    if(row.payload!==null) validateInbox(row.payload); else requireInbox(!row.active);
  }
  requireInbox(value.items.length>0 || value.retained>0,'unused_inbox_capability');
  return structuredClone(value);
}
