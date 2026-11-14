/** Explicit browser pairing. No secret persistence or workspace adoption in this view. */
import {CookieTransport} from './transport.mjs';

export const PAIRING_COPY={
 en:{title:'Connect this browser',hint:'Paste pairing details from your connected desktop.',
  remember:'Remember this browser for up to 14 days. Reconnect explicitly to sync; offline research stays available.',
  packet:'Private pairing details',pair:'Pair and remember this browser',resume:'Reconnect saved connection',
  forget:'Forget browser connection',confirm:'Forget connection',keep:'Keep connection',
  question:'Forget this browser connection? Local research stays here. A device already paired remains in your desktop device list.',
  preparing:'Preparing a private connection on this browser...',verifying:'Verifying this browser and its saved connection...',
  forgetting:'Removing this browser connection...',ready:'Connection verified. Opening your workspace...',
  forgotten:'Browser connection forgotten. Local research is unchanged.',cancelled:'Stopped. A sent pairing may have completed; reconnect to check.',
  failed:'Connection did not finish. Your local research is unchanged; reconnect to retry.',
  denied:'Connection was rejected or expired. Reconnect a pending attempt, or forget it before using fresh pairing details.',
  throttled:'The service is busy. Wait a moment, then reconnect. Local research is unchanged.',
  unsupported:'This service has not enabled browser pairing. Check the service setup or use Advanced manual connection.',
  wrongOrigin:'Open this reader on the same website as your sync service.',invalid:'Pairing details could not be read. Copy them again from your desktop.',
  empty:'Paste pairing details first.',stop:'Stop'},
 'zh-TW':{title:'連接此瀏覽器',hint:'貼上已連線桌面裝置提供的配對資料。',
  remember:'在此瀏覽器保留連線最長 14 天。按重新連線才會同步；離線時仍可閱讀本機研究。',
  packet:'私人配對資料',pair:'配對並記住此瀏覽器',resume:'重新連線',forget:'移除瀏覽器連線',
  confirm:'移除連線',keep:'保留連線',
  question:'要移除此瀏覽器的連線嗎？本機研究會保留，已配對裝置仍會留在桌面版的裝置清單。',
  preparing:'正在此瀏覽器準備私人連線…',verifying:'正在核對此瀏覽器與已存連線…',
  forgetting:'正在移除瀏覽器連線…',ready:'連線已核對，正在開啟工作區…',
  forgotten:'已移除瀏覽器連線，本機研究未變更。',cancelled:'已停止。已送出的配對可能已完成，可重新連線確認。',
  failed:'連線未完成，本機研究未變更。可按重新連線重試。',
  denied:'連線被拒絕或已過期。可重試未完成配對，或先移除已存連線再使用新資料。',
  throttled:'服務暫時忙碌，請稍後重新連線。本機研究未變更。',
  unsupported:'此服務尚未啟用瀏覽器配對，請確認服務設定，或使用進階手動連線。',
  wrongOrigin:'請從同步服務的相同網站開啟此閱讀器。',invalid:'無法讀取配對資料，請從桌面版重新複製。',
  empty:'請先貼上配對資料。',stop:'停止'}
};

export function browserPairingPanel(el,{language='en',transport=null,current=()=>true,blocked=()=>false,
 onConnected=()=>{},onForgotten=()=>{},onPending=()=>{}}={}) {
 const t=PAIRING_COPY[language]??PAIRING_COPY.en;
 const element=el('section',{class:'browser-pairing','aria-label':t.title}),
  status=el('p',{class:'pairing-status',role:'status','aria-live':'polite','aria-atomic':'true'}),
  packet=el('input',{type:'password',autocomplete:'off',spellcheck:'false','aria-label':t.packet,
    placeholder:t.packet,'data-pairing':'packet',onkeydown:event=>{
     if(event.key==='Enter'&&!event.isComposing){event.preventDefault();void run('pair');}
    }}),question=el('div',{class:'pairing-question',hidden:''});
 let disposed=false,pending=false,confirming=false,controller=null,serial=0,service=transport;
 const live=()=>!disposed&&current(),controls={packet,status,question};
 const say=key=>{if(!disposed)status.replaceChildren(t[key]??t.failed);};
 const button=(key,fn,attrs={})=>el('button',{type:'button',onclick:()=>void fn(),
  'data-pairing':key,...attrs},t[key]);
 const pair=button('pair',()=>run('pair'),{class:'primary'}),resume=button('resume',()=>run('resume')),
  forget=button('forget',()=>askForget(),{class:'quiet'}),stop=button('stop',()=>cancel()),
  confirm=button('confirm',()=>run('forget')),keep=button('keep',()=>keepConnection());
 Object.assign(controls,{pair,resume,forget,stop,confirm,keep});
 question.append(el('p',{},t.question),el('div',{class:'toolbar'},keep,confirm));
 element.append(el('h3',{},t.title),el('p',{class:'muted'},t.hint),packet,
  el('p',{class:'muted pairing-help'},t.remember),el('div',{class:'toolbar'},pair,resume),
  el('div',{class:'toolbar'},forget,stop),question,status);
 function enable() {
  const off=!live()||blocked();
  for(const control of [packet,pair,resume,forget])control.disabled=off||pending||confirming;
  stop.hidden=!pending;stop.disabled=!pending;
  keep.disabled=off||pending;confirm.disabled=off||pending;
  question.hidden=!confirming;element.setAttribute('aria-busy',String(pending));
 }
 function errorKey(error) {
  if(controller?.signal.aborted||error.message==='cancelled')return 'cancelled';
  if(error.message==='session_denied')return 'denied';
  if(error.message==='unsupported_service')return 'unsupported';
  if(error.message==='rate_limited')return 'throttled';
  if(error.message==='browser_same_origin_required')return 'wrongOrigin';
  if(['invalid_pairing','invalid_request','request_rejected'].includes(error.message))return 'invalid';
  return 'failed';
 }
 async function run(kind) {
  if(!live()||blocked()||pending||(confirming&&kind!=='forget'))return false;
  if(kind==='forget'&&!confirming)return false;
  const body=packet.value;
  if(kind==='pair'&&!body.trim()){say('empty');return false;}
  pending=true;confirming=false;controller=new AbortController();const signal=controller.signal,epoch=++serial;
  packet.value='';onPending(true);enable();
  const valid=()=>live()&&epoch===serial&&!signal.aborted;
  const check=()=>{if(!valid())throw Error('cancelled');};
  try {
   service??=new CookieTransport();
   if(kind==='forget') {
    say('forgetting');await service.forgetSession(signal);check();
    say('forgotten');onForgotten();return true;
   }
   if(kind==='pair'){say('preparing');await service.preparePairing(body,signal);check();}
   say('verifying');const identity=await service.completePairing(signal);check();
   say('ready');onConnected(identity,service);return true;
  } catch(error) {if(live()&&epoch===serial)say(errorKey(error));return false;}
  finally {if(epoch===serial){pending=false;controller=null;onPending(false);enable();}}
 }
 function askForget() {
  if(!live()||blocked()||pending||confirming)return false;
  confirming=true;enable();keep.focus();return true;
 }
 function keepConnection(){if(pending)return false;confirming=false;enable();forget.focus();return true;}
 function cancel(){if(pending){controller?.abort();say('cancelled');}}
 function dispose(){if(disposed)return;disposed=true;serial++;controller?.abort();packet.value='';pending=false;
  confirming=false;onPending(false);enable();}
 enable();
 return {element,controls,run,askForget,keepConnection,cancel,dispose,refresh:enable,
  get pending(){return pending;},get disposed(){return disposed;}};
}
