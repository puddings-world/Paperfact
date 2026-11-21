/** Optional real Chromium check. Requires an explicit browser executable; no profile reuse. */
import {
  spawn
} from 'node:child_process';
import {
  mkdtemp,
  readFile,
  writeFile,
  mkdir,
  rm
} from 'node:fs/promises';
import {
  tmpdir
} from 'node:os';
import {
  join,
  extname,
  resolve,
  relative,
  isAbsolute
} from 'node:path';
import {
  fileURLToPath
} from 'node:url';
import {
  createServer
} from 'node:http';
import {createInterface} from 'node:readline';
import {verifyMobile} from '../scripts/build_mobile.mjs';
const executable = process.argv[2] ?? process.env.PAPERFACT_TEST_BROWSER;
const journey=process.env.PAPERFACT_TEST_JOURNEY??'fixture';
if(!['fixture','offline-reading'].includes(journey))throw Error('Unknown browser journey.');
const offlineReadingMode=journey==='offline-reading';
if(offlineReadingMode&&[process.env.PAPERFACT_NOTE_SERVICE_PYTHON,process.env.PAPERFACT_POSITION_SERVICE_PYTHON,process.env.PAPERFACT_PAIRING_SERVICE_PYTHON,process.argv[3]].some(Boolean))throw Error('Offline reading is an independent bounded journey.');
const testPage=process.env.PAPERFACT_TEST_PAGE??'browser-test.html';
if(!['browser-test.html','position-browser-test.html','position-ui-browser-test.html','workspace-startup-browser-test.html','browser-pairing-browser-test.html'].includes(testPage))throw Error('Unknown fixture page.');
if(! executable) throw new Error('Pass an explicit Chromium/Edge executable path.');
const root = fileURLToPath(new URL('.', import.meta.url)), profile = await mkdtemp(join(tmpdir(), 'paperfact-mobile-fixture-'));
let assetRoot=root;
if(process.env.PAPERFACT_TEST_ARTIFACT){
  await verifyMobile(process.env.PAPERFACT_TEST_ARTIFACT,{expectedId:process.env.PAPERFACT_TEST_ARTIFACT_ID??null});
  assetRoot=join(resolve(process.env.PAPERFACT_TEST_ARTIFACT),'public');
}
const plainNoteMode=!!process.env.PAPERFACT_NOTE_SERVICE_PYTHON;
const pairingMode=testPage==='browser-pairing-browser-test.html';
if(pairingMode&&!process.env.PAPERFACT_PAIRING_SERVICE_PYTHON)throw Error('Pairing fixture needs an explicit Python interpreter.');
const fixtureResearchRequests=[];
let positionService,positionReady,positionErrors='',lastFixtureText='';
const serviceLines=[],serviceWaiting=[];
async function serviceMessage(command) {
  if(command)positionService.stdin.write((plainNoteMode?JSON.stringify(command):command)+'\n');
  return JSON.parse(await new Promise((resolve,reject)=>{
    if(serviceLines.length){resolve(serviceLines.shift());return;}
    const timer=setTimeout(()=>reject(Error('Isolated position service timed out: '+positionErrors)),30000);
    serviceWaiting.push(line=>{clearTimeout(timer);resolve(line);});
    positionService.once('exit',code=>{clearTimeout(timer);reject(Error('Position service exited '+code+': '+positionErrors+'\nLast browser results:\n'+lastFixtureText.slice(-8000)));});
  }));
}
if(plainNoteMode) {
  if(testPage!=='browser-test.html')throw Error('Plain-note fixtures require the ordinary browser test page.');
  positionService=spawn(process.env.PAPERFACT_NOTE_SERVICE_PYTHON,[join(root,'plain-note-service-fixture.py'),resolve(root,'..')],
    {stdio:['pipe','pipe','pipe'],windowsHide:true});
  positionService.stderr.on('data',chunk=>positionErrors+=chunk);
  createInterface({input:positionService.stdout}).on('line',line=>{const next=serviceWaiting.shift();if(next)next(line);else serviceLines.push(line);});
  positionReady=await serviceMessage();
  const origin=new URL(positionReady.url);
  if(origin.protocol!=='http:'||origin.hostname!=='127.0.0.1'||origin.pathname!=='/')throw Error('Invalid note fixture origin.');
}
if(['position-browser-test.html','position-ui-browser-test.html'].includes(testPage) && process.env.PAPERFACT_POSITION_SERVICE_PYTHON) {
  positionService=spawn(process.env.PAPERFACT_POSITION_SERVICE_PYTHON,[join(root,'position-service-fixture.py'),resolve(root,'..')],
    {stdio:['pipe','pipe','pipe'],windowsHide:true});
  positionService.stderr.on('data',chunk=>positionErrors+=chunk);
  createInterface({input:positionService.stdout}).on('line',line=>{const next=serviceWaiting.shift();if(next)next(line);else serviceLines.push(line);});
  positionReady=await serviceMessage();
  const origin=new URL(positionReady.url);
  if(origin.protocol!=='http:' || origin.hostname!=='127.0.0.1' || origin.pathname!=='/')throw Error('Invalid fixture origin.');
}
const server = createServer(async(request, response) => {
  if(pairingMode && request.url==='/__position_requests') {
    response.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});
    response.end(JSON.stringify(fixtureResearchRequests));return;
  }
  if(positionReady && request.url==='/__position_fixture') {
    response.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});
    response.end(JSON.stringify(positionReady));return;
  }
  if(positionReady && (request.url==='/__position_command' || request.url.startsWith('/v1/'))) {
    const parts=[];let size=0;for await(const part of request){size+=part.length;if(size>512*1024){response.writeHead(413);response.end();return;}parts.push(part);}
    const body=Buffer.concat(parts);
    if(request.url==='/__position_command') {
      const {command}=JSON.parse(body);
      if(!['inspect','primary','position','delete','delete-current','retire','retire-b','revoke','peer','peer-recovery'].includes(command)){response.writeHead(400);response.end();return;}
      const result=await serviceMessage(command);
      response.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});response.end(JSON.stringify(result));return;
    }
    if(!(pairingMode?['/v1/browser/pairing/prepare','/v1/browser/pairing/complete','/v1/browser/session/forget','/v1/browser/session/info','/v1/browser/control/checkpoint','/v1/browser/push','/v1/browser/pull','/v1/browser/history/pull','/v1/browser/history/push']:['/v1/session/info','/v1/pull','/v1/push','/v1/history/pull','/v1/history/push','/v1/history/blobs/begin','/v1/history/blobs/append','/v1/history/blobs/commit','/v1/history/blobs/cancel','/v1/blobs/read','/v1/blobs/begin','/v1/blobs/append','/v1/blobs/commit']).includes(request.url) || request.method!=='POST') {
      response.writeHead(404);response.end();return;
    }
    if(plainNoteMode||pairingMode)fixtureResearchRequests.push({path:request.url,document:request.headers['x-paperfact-test-document']??null});
    const upstream=await fetch(positionReady.url+request.url,{method:'POST',body,
      headers:pairingMode?Object.fromEntries(Object.entries(request.headers).filter(([name])=>
        ['content-type','origin','cookie','x-paperfact-browser','x-paperfact-workspace','x-paperfact-device','x-paperfact-sync-instance','x-paperfact-control-checkpoint','sec-fetch-site'].includes(name)))
        :{'Content-Type':'application/json',Authorization:request.headers.authorization??'',
          'X-Paperfact-Sync-Instance':request.headers['x-paperfact-sync-instance']??''},redirect:'error'});
    response.writeHead(upstream.status,{'Content-Type':'application/json','Cache-Control':'no-store',
      ...(upstream.headers.has('X-Paperfact-Sync-Instance')?{'X-Paperfact-Sync-Instance':upstream.headers.get('X-Paperfact-Sync-Instance')}:{}),
      ...(upstream.headers.has('X-Paperfact-Control-History')?{'X-Paperfact-Control-History':upstream.headers.get('X-Paperfact-Control-History')}:{}),
      ...(pairingMode&&upstream.headers.has('set-cookie')?{'Set-Cookie':upstream.headers.get('set-cookie')}:{})});
    response.end(new Uint8Array(await upstream.arrayBuffer()));return;
  }
  const name = decodeURIComponent(new URL(request.url, 'http://localhost').pathname),
  selectedRoot=pairingMode&&['/browser-pairing-browser-test.html','/browser-pairing-browser-test.mjs'].includes(name)?root:assetRoot,
  path = resolve(selectedRoot, '.' +(name === '/' ? '/index.html': name));
  const local = relative(selectedRoot, path);
  if(local.startsWith('..') || isAbsolute(local)) {
    response.writeHead(404);
    response.end();
    return;
  }
  try {
    const bytes = await readFile(path);
    response.writeHead(
    200,
    {
      'Content-Type': ({
        '.mjs': 'text/javascript',
        '.html': 'text/html',
        '.css': 'text/css',
        '.svg': 'image/svg+xml',
        '.webmanifest': 'application/manifest+json'
      })[extname(path)] ?? 'application/octet-stream'
    }
    );
    response.end(bytes);
  } catch {
    response.writeHead(404);
    response.end();
  }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
if(pairingMode) {
  positionService=spawn(process.env.PAPERFACT_PAIRING_SERVICE_PYTHON,
    [join(root,'browser-pairing-service-fixture.py'),resolve(root,'..'),`http://127.0.0.1:${server.address().port}`],
    {stdio:['pipe','pipe','pipe'],windowsHide:true});
  positionService.stderr.on('data',chunk=>positionErrors+=chunk);
  createInterface({input:positionService.stdout}).on('line',line=>{const next=serviceWaiting.shift();if(next)next(line);else serviceLines.push(line);});
  positionReady=await serviceMessage();
}
const browser = spawn(
executable,
['--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
'--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'],
{
  stdio: ['ignore', 'ignore', 'pipe'],
  windowsHide: true
}
);
let socket;
const browserErrors=[];
const pending = new Map();
let nextId = 0, session;
const send =(method, params = {}, sessionId = session) => new Promise((resolve, reject) => {
  const id =++ nextId;
  const timeout = setTimeout(() => {
    pending.delete(id);
    reject(new Error('Browser command timed out: ' + method));
  }, 5000);
  pending.set(
  id,
  {
    resolve: value => {
      clearTimeout(timeout);
      resolve(value);
    },
    reject: error => {
      clearTimeout(timeout);
      reject(error);
    }
  }
  );
  socket.send(JSON.stringify({
    id,
    method,
    params,
    ...(sessionId ? {
      sessionId
    }
    : {})
  }));
});
async function offlineReadingMainHook() {
  const evaluate=async expression=>{
    const value=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
    if(value.exceptionDetails)throw Error('Offline reading evaluation failed: '+value.exceptionDetails.text);
    return value.result.value;
  };
  const wait=async(expression,label)=>{
    for(let tick=0;tick<100;tick++){
      if(await evaluate(expression))return;
      await new Promise(resolve=>setTimeout(resolve,80));
    }
    const status=await evaluate('document.querySelector("#notice-text")?.textContent');
    throw Error('Offline reading timed out: '+label+'; status='+status);
  };
  const stateExpression=`(async()=>{const {IndexedStore}=await import('./store.mjs');const s=await IndexedStore.open('demo-workspace','demo-phone');try{const v=await s.read(),meta={...v};delete meta.files;delete meta.artifactFiles;delete meta.selection;const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(meta)));return {files:Object.keys(v.files).length,outbox:v.outbox.length,metadata_sha256:[...new Uint8Array(hash)].map(x=>x.toString(16).padStart(2,'0')).join('')};}finally{s.close();}})()`;
  await send('Network.enable');
  await send('Page.addScriptToEvaluateOnNewDocument',{source:`
    window.__storageRequests=0;
    if(typeof navigator.storage?.persist==='function') {
      const native=navigator.storage.persist.bind(navigator.storage);
      Object.defineProperty(navigator.storage,'persist',{value:()=>{window.__storageRequests++;return native();}});
    }`});
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/index.html`});
  await wait('!!document.querySelector(".paper-card")','demo startup');
  if (!await evaluate(`document.querySelector('.paper-card').dataset.pdfLocal === 'false' &&
      document.querySelector('[data-offline-summary]').textContent.includes('0/')`))
    throw Error('An original appeared to be saved before preparation');
  await evaluate('document.querySelector(".paper-card").click();document.querySelector("#tab-pdf").click()');
  await wait('!!document.querySelector("#prepare-reading-offline:not(:disabled)")','preparation enabled');
  await evaluate('document.querySelector("#prepare-reading-offline").click();document.querySelector("#prepare-reading-offline").click()');
  await wait(`(async()=>{const {translator}=await import('./i18n.mjs');return document.querySelector('[role=status]')?.textContent===translator(document.documentElement.lang)('reading_ready');})()`,'verified completion');
  const before=await evaluate(stateExpression);
  if(before.files!==1||before.outbox!==0)throw Error('Preparation changed research or omitted the PDF');
  const storageSettled=`(async()=>{const {translator}=await import('./i18n.mjs');return document.querySelector('[data-storage-status]')?.textContent!==translator(document.documentElement.lang)('storageChecking');})()`;
  await wait(storageSettled,'storage inspection');
  const storageBefore=await evaluate(`({calls:window.__storageRequests,state:document.querySelector('[data-storage-state]')?.dataset.storageState})`);
  if(storageBefore.calls!==0)throw Error('Opening/preparing research requested browser permission');
  if(!['persistent','unsupported'].includes(storageBefore.state)) {
    await evaluate(`document.querySelector('[data-storage-request]').click();document.querySelector('[data-storage-request]').click()`);
    await wait(`document.querySelector('[data-storage-request]')?.getAttribute('aria-busy')==='false'`,'storage request');
  }
  const storageProtection=await evaluate(`(async()=>({calls:window.__storageRequests,
    state:document.querySelector('[data-storage-state]').dataset.storageState,
    actual:typeof navigator.storage?.persisted==='function'?await navigator.storage.persisted():null}))()`);
  const expectedRequests=['persistent','unsupported'].includes(storageBefore.state)?0:1;
  if(storageProtection.calls!==expectedRequests || storageProtection.actual===true&&storageProtection.state!=='persistent' ||
    storageProtection.actual===false&&storageProtection.state!=='best_effort')throw Error('Storage request did not render actual browser truth');
  if(JSON.stringify(await evaluate(stateExpression))!==JSON.stringify(before))throw Error('Storage permission changed research cache/outbox');
  const viewports=[];
  const output=process.env.PAPERFACT_TEST_SCREENSHOTS;
  if(output)await mkdir(output,{recursive:true});
  for(const language of ['en','zh-TW']){
    await evaluate(`(async()=>{const {translator}=await import('./i18n.mjs');[...document.querySelectorAll('header button')].find(n=>n.textContent===translator(document.documentElement.lang)('settings')).click();const select=document.querySelector('dialog select');select.value='${language}';select.dispatchEvent(new Event('change',{bubbles:true}));})()`);
    await evaluate('window.scrollTo(0,0)');
    const metrics=await evaluate(`({language:document.documentElement.lang,width:innerWidth,scrollWidth:document.documentElement.scrollWidth,prepareHeight:document.querySelector('#prepare-reading-offline').getBoundingClientRect().height,storageHeight:document.querySelector('[data-storage-request]').getBoundingClientRect().height})`);
    if(metrics.language!==language||metrics.scrollWidth>metrics.width||metrics.prepareHeight<44||metrics.storageHeight<44)throw Error('Offline controls overflow or miss the touch target');
    viewports.push(metrics);
    if(output){
      const shot=await send('Page.captureScreenshot',{format:'png'});
      await writeFile(join(output,'offline-reading-'+language+'.png'),Buffer.from(shot.data,'base64'));
      const clip=await evaluate(`(()=>{const r=document.querySelector('.storage-protection').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()`);
      const detail=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip});
      await writeFile(join(output,'storage-protection-'+language+'.png'),Buffer.from(detail.data,'base64'));
    }
  }
  await evaluate('navigator.serviceWorker.ready.then(()=>true)');
  // A new worker controls the next document; do not force-claim a live reader.
  await send('Page.reload');
  await wait('!!navigator.serviceWorker.controller && !!document.querySelector("#tab-pdf")','activated shell control');
  const previousDocument=await evaluate('performance.timeOrigin');
  await send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
  await send('Page.reload');
  await wait(`performance.timeOrigin!==${previousDocument} && !!document.querySelector('#tab-pdf')`,'new offline document');
  await evaluate('document.querySelector("#tab-pdf").click()');
  await wait(`(async()=>{const {translator}=await import('./i18n.mjs');return document.body.textContent.includes(translator(document.documentElement.lang)('localFile'));})()`,'cached PDF card');
  const persisted=await evaluate(`(async()=>{const {IndexedStore}=await import('./store.mjs');const {Engine}=await import('./engine.mjs');const s=await IndexedStore.open('demo-workspace','demo-phone');const e=new Engine(s,{});try{const v=await s.read();const id=Object.values(v.entities).find(x=>x.operation.entity_type==='paper').operation.entity_id;const r=await e.prepareOffline(id);return {ready:r.ready,verified:r.verified_targets};}finally{e.disconnect();s.close();}})()`);
  const after=await evaluate(stateExpression);
  if(!persisted.ready||persisted.verified!==1||after.files!==1||after.outbox!==0||browserErrors.length)throw Error('Offline verification failed or changed research');
  await evaluate("document.querySelector('#back-to-list').click()");
  await wait(`document.querySelector('.paper-card')?.dataset.pdfLocal === 'true' &&
      document.querySelector('[data-offline-summary]')?.textContent.includes('1/')`,
      'saved PDF on the offline list');
  const reopenStorageRequests=await evaluate('window.__storageRequests');
  // Populate the isolated reader with a large offline catalog, preserving its original PDF.
  await evaluate(`(async()=>{
    const {IndexedStore}=await import('./store.mjs');
    const db=await IndexedStore.open('demo-workspace','demo-phone');
    try {await db.update(s=>{
      const original=Object.values(s.entities).find(row=>row.operation.entity_type==='paper');
      for(let i=1;i<5000;i++) {
        const id='catalog-'+i,key='paper/'+id;
        s.entities[key]={...original,created:i+100,operation:{...original.operation,
          entity_id:id,operation_id:id,incarnation:id,payload:{...original.operation.payload,title:id}}};
        s.graph[key]={active:true,incarnation:id,parents:[],structure_revision:0};
      }
      s.selection={list:null,paper:null};
    });} finally {db.close();}
  })()`);
  await send('Page.reload');
  await wait("document.querySelector('[data-offline-summary]')?.textContent.includes('1/5000')",
    'large offline catalog');
  await evaluate("document.querySelector('#next-papers-bottom').click()");
  const selectedRow=await evaluate(`(()=>{
    const cards=document.querySelectorAll('.paper-card');
    if(cards.length!==50||cards[0].querySelector('.paper-number').textContent!=='51')
      throw Error('Unbounded or unordered mobile list');
    const row=cards[24];row.scrollIntoView();row.click();return row.id;
  })()`);
  await wait("!!document.querySelector('#back-to-list')",'paper from second page');
  await evaluate("document.querySelector('#back-to-list').click()");
  await wait('document.activeElement.id==='+JSON.stringify(selectedRow),'original paper row');
  await evaluate("document.querySelector('#previous-papers').click()");
  await wait("document.querySelector('#previous-papers')?.disabled === true",'first page boundary');
  if(reopenStorageRequests!==0)throw Error('Offline reopening requested storage permission');
  const result={status:'passed',journey:'offline-reading',artifact:process.env.PAPERFACT_TEST_ARTIFACT_ID??null,before,persisted,after,storageProtection,reopenStorageRequests,viewports,errors:browserErrors,physical_device_verified:false};
  if(output)await writeFile(join(output,'offline-reading-result.json'),JSON.stringify(result,null,2)+'\n');
  console.log('PASS actual offline reading UI, repeated activation, EN/ZH touch layout, new offline document and transport-free cached PDF verification');
}

async function plainNoteMainHook() {
  const evaluate=async(expression,awaitPromise=false)=>{
    const value=await send('Runtime.evaluate',{expression,awaitPromise,returnByValue:true});
    if(value.exceptionDetails)throw Error('Plain-note app evaluation failed: '+(value.exceptionDetails.exception?.description??value.exceptionDetails.text));
    return value.result.value;
  };
  const wait=async(expression,label)=>{
    for(let tick=0;tick<150;tick++){
      if(await evaluate(expression,true))return;
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    const notice=await evaluate('document.querySelector("#notice-text")?.textContent');
    throw Error('Plain-note app timed out: '+label+' '+notice);
  };
  const origin=`http://127.0.0.1:${server.address().port}`;
  const config={workspace:positionReady.workspace,device:positionReady.device,origin,token:positionReady.token};
  const stateExpression=`(async()=>{const {IndexedStore}=await import('./store.mjs'),s=await IndexedStore.open(${JSON.stringify(config.workspace)},${JSON.stringify(config.device)});try{return await s.read();}finally{s.close();}})()`;
  const connect=async(token)=>{
    await evaluate('[...document.querySelectorAll("header button")].find(b=>["Connection","連線"].includes(b.textContent)).click()');
    await evaluate(`(()=>{const c=${JSON.stringify({...config,token})},d=document.querySelector('dialog'),inputs=d.querySelectorAll('.fields input');[c.workspace,c.device,c.origin,c.token].forEach((v,i)=>inputs[i].value=v);d.querySelector('.connection-fields').closest('details').open=true;d.querySelector('.connection-fields button.primary').click();})()`);
    await wait(`document.querySelector('.workspace')?.textContent===${JSON.stringify(config.workspace)} && !document.querySelector('.status[data-busy="true"]') && !!(document.querySelector('.paper-card') || document.querySelector('#tab-notes'))`,'open fixture workspace');
    await evaluate('document.querySelector(".paper-card")?.click();document.querySelector("#tab-notes").click()');
    await wait('!!document.querySelector("#note-editor") && !document.querySelector("#note-editor").disabled','editable unpositioned desktop text');
  };
  await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await send('Network.enable');
  await send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await send('Page.addScriptToEvaluateOnNewDocument',{source:`{
    const original=globalThis.fetch;
    globalThis.__workspaceFetchTrace=[];
    globalThis.fetch=function(input,options){
      const url=new URL(typeof input==='string'?input:input.url,location.href);
      if(url.pathname.startsWith('/v1/')){
        const entry={path:url.pathname,document:performance.timeOrigin};
        globalThis.__workspaceFetchTrace.push(entry);
        const headers=new Headers(options?.headers);headers.set('X-Paperfact-Test-Document',String(performance.timeOrigin));options={...options,headers};
      }
      return original.call(this,input,options);
    };
  }`});
  await send('Page.navigate',{url:origin+'/index.html'});
  await wait('!!document.querySelector(".layout")','startup');
  await connect(config.token);
  if(await evaluate('document.querySelector("#note-editor").value')!=='Desktop plain note')throw Error('Wrong desktop note on phone');
  await send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
  await evaluate(`(()=>{const e=document.querySelector('#note-editor');e.focus();e.value='Actual PWA offline edit';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await wait(`(async()=>{const s=await ${stateExpression};return s.drafts[${JSON.stringify(positionReady.note)}]==='Actual PWA offline edit';})()`,'durable debounced draft');
  await evaluate(`(()=>{const b=[...document.querySelectorAll('main button')].find(b=>['Save note','儲存筆記'].includes(b.textContent));b.click();b.click();})()`);
  await wait(`(async()=>{const s=await ${stateExpression};return s.outbox.length===1&&s.outbox[0].operation.payload.body==='Actual PWA offline edit';})()`,'one offline note operation');
  await evaluate('navigator.serviceWorker.ready',true);
  const beforeReloadRequests=fixtureResearchRequests.length;
  const beforeReloadDocument=await evaluate('performance.timeOrigin');
  await evaluate('globalThis.__plainNoteBeforeReload=true');
  await send('Page.reload');
  await wait('globalThis.__plainNoteBeforeReload!==true && document.readyState==="complete" && !!document.querySelector(".layout")','fresh offline cached shell reload');
  await wait(`document.querySelector('.workspace')?.textContent===${JSON.stringify(config.workspace)} && !!document.querySelector('#tab-notes')`,'automatic cached workspace restore');
  await evaluate('document.querySelector("#tab-notes").click()');
  await wait('!!document.querySelector("#note-editor")','restored note editor');
  const resumedDocument=await evaluate('performance.timeOrigin');
  const newPageRequests=await evaluate('globalThis.__workspaceFetchTrace');
  const completedOutgoing=fixtureResearchRequests.slice(beforeReloadRequests);
  if(resumedDocument===beforeReloadDocument || !Array.isArray(newPageRequests) || newPageRequests.length ||
    completedOutgoing.some(request=>request.document!==String(beforeReloadDocument)||request.path!=='/v1/session/info'))
    throw Error('Restored page made a request, or an unowned old request completed: '+JSON.stringify({newPageRequests,completedOutgoing}));
  const hint=await evaluate(`JSON.parse(window.localStorage.getItem('paperfact.last-workspace.v1'))`);
  if(JSON.stringify(Object.keys(hint).sort())!==JSON.stringify(['version','workspace','device','origin'].sort())||hint.workspace!==config.workspace||hint.device!==config.device||hint.origin!==config.origin)throw Error('Resume hint changed owner or stored extra data');
  if(!await evaluate('document.querySelector("header button").disabled'))throw Error('Resume reused a credential');
  if(await evaluate('document.querySelector("#note-editor").value')!=='Actual PWA offline edit')throw Error('Reload lost offline text');
  const offline=await evaluate(stateExpression,true);
  if(offline.outbox.length!==1||offline.outbox[0].operation.payload.created_at===undefined)throw Error('Reload lost queue/creation metadata');
  await send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await connect(config.token);
  await wait(`(async()=>{const s=await ${stateExpression};return s.outbox.length===0;})()`,'reconnected upload');
  const accepted=await serviceMessage({command:'inspect'});
  if(accepted.note.body!=='Actual PWA offline edit'||accepted.note.created_at!==offline.outbox[0].operation.payload.created_at)throw Error('Desktop did not receive exact text/identity');
  await serviceMessage({command:'edit',body:'Desktop edit after PWA reload'});
  await wait('document.querySelector("header button") && !document.querySelector("header button").disabled','enabled sync action');
  await evaluate('document.querySelector("header button").click()');
  await wait(`document.querySelector('#note-editor')?.value==='Desktop edit after PWA reload' && !document.querySelector('#note-editor').disabled`,'desktop reply remains editable');
  await wait(`!![...document.querySelectorAll('main button')].find(b=>['Save note','儲存筆記'].includes(b.textContent)&&!b.disabled)`,'clean remote update allows saving');
  await evaluate(`(()=>{const e=document.querySelector('#note-editor');e.value='Phone continues after desktop reply';e.dispatchEvent(new Event('input',{bubbles:true}));[...document.querySelectorAll('main button')].find(b=>['Save note','儲存筆記'].includes(b.textContent)).click();})()`);
  await wait(`(async()=>{const s=await ${stateExpression};return s.outbox.length===1&&s.outbox[0].operation.payload.body==='Phone continues after desktop reply';})()`,'continued phone save');
  await wait('document.querySelector("header button") && !document.querySelector("header button").disabled','enabled sync action');
  await evaluate('document.querySelector("header button").click()');
  await wait(`(async()=>{const s=await ${stateExpression};return s.outbox.length===0;})()`,'continued phone upload');
  const final=await serviceMessage({command:'inspect'});
  if(final.note.body!=='Phone continues after desktop reply')throw Error('Clean editor could not continue roundtrip');
  const result={scenarios:2,offlineReload:true,manualWorkspaceSelection:false,automaticWorkspaceResume:true,backgroundResearchRequestsOnResume:0,outgoingAuthenticationRequestsCompletedDuringReload:completedOutgoing.length,duplicateSaves:1,metadataPreserved:true,desktopRoundTrip:true,cleanRemoteEditable:true,errors:0};
  if(process.env.PAPERFACT_TEST_SCREENSHOTS){
    await mkdir(process.env.PAPERFACT_TEST_SCREENSHOTS,{recursive:true});
    for(const width of [1100,600,390,320]){
      await send('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});
      const metric=await evaluate(`({language:document.documentElement.lang,width:innerWidth,scrollWidth:document.documentElement.scrollWidth,reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,
        buttons:[...document.querySelectorAll('header button')].map(b=>({height:b.getBoundingClientRect().height,width:b.getBoundingClientRect().width,scroll:b.scrollWidth,client:b.clientWidth,text:b.textContent}))})`);
      if(metric.scrollWidth>width||metric.buttons.some(b=>b.height<44||b.scroll>b.client))throw Error('Header labels/touch targets overflow: '+JSON.stringify(metric));
      result.viewports??=[];result.viewports.push(metric);
      const shot=await send('Page.captureScreenshot',{format:'png'});
      await writeFile(join(process.env.PAPERFACT_TEST_SCREENSHOTS,`plain-note-${width}.png`),Buffer.from(shot.data,'base64'));
    }

  }
  await evaluate('[...document.querySelectorAll("header button")].find(b=>["Connection","連線"].includes(b.textContent)).click()');
  await evaluate(`(()=>{const select=document.querySelector('dialog select');select.value='en';select.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  for(const width of [320,390,600,1100]){
    await send('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});
    const metric=await evaluate(`({language:document.documentElement.lang,width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
      buttons:[...document.querySelectorAll('header button')].map(b=>({height:b.getBoundingClientRect().height,scroll:b.scrollWidth,client:b.clientWidth,text:b.textContent}))})`);
    if(metric.scrollWidth>width||metric.buttons.some(b=>b.height<44||b.scroll>b.client))throw Error('English header overflow: '+JSON.stringify(metric));
    result.viewports??=[];result.viewports.push(metric);
    if(width===390&&process.env.PAPERFACT_TEST_SCREENSHOTS){const shot=await send('Page.captureScreenshot',{format:'png'});await writeFile(join(process.env.PAPERFACT_TEST_SCREENSHOTS,'workspace-resume-en-390.png'),Buffer.from(shot.data,'base64'));}
  }
  await evaluate(`[...document.querySelectorAll('header button')].find(b=>b.textContent==='Connection').focus()`);
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',unmodifiedText:'\r',windowsVirtualKeyCode:13});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});
  await wait('!!document.querySelector("dialog")','keyboard connection action');
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await wait('!document.querySelector("dialog")','keyboard dialog dismissal');
  result.keyboardConnection=true;
  await evaluate(`(()=>{const e=document.querySelector('#note-editor');e.value='Actual unsaved phone words';e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await wait(`(async()=>{const s=await ${stateExpression};return s.drafts[${JSON.stringify(positionReady.note)}]==='Actual unsaved phone words';})()`,'persist real unsaved words');
  await serviceMessage({command:'edit',body:'New desktop while phone is typing'});
  await wait('document.querySelector("header button") && !document.querySelector("header button").disabled','enabled sync action');
  await evaluate('document.querySelector("header button").click()');
  await wait(`document.querySelector('#note-editor')?.value==='Actual unsaved phone words' && !![...document.querySelectorAll('main button')].find(b=>['Save note','儲存筆記'].includes(b.textContent)&&b.disabled)`,'dirty remote update retains words and blocks stale save');
  const protectedState=await evaluate(stateExpression,true);
  if(protectedState.outbox.length!==0||protectedState.drafts[positionReady.note]!=='Actual unsaved phone words')throw Error('Dirty editor changed newer research or lost private text');
  result.unsavedDraftPreserved=true;
  if(process.env.PAPERFACT_TEST_SCREENSHOTS)await writeFile(join(process.env.PAPERFACT_TEST_SCREENSHOTS,'plain-note-browser-result.json'),JSON.stringify(result,null,2));
  console.log('PASS actual PWA offline note UI, IndexedDB save/reload/automatic cached scope reopen, one queued save and desktop Data roundtrip preserving metadata');
}

async function positionMainHook() {
  await send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  const evaluate=async(expression,awaitPromise=false)=>(await send('Runtime.evaluate',
    {expression,awaitPromise,returnByValue:true})).result.value;
  const wait=async(expression,label)=>{
    for(let tick=0;tick<100;tick++){if(await evaluate(expression,true))return;await new Promise(resolve=>setTimeout(resolve,50));}
    const evidence=await evaluate('JSON.stringify({positionDisabled:document.querySelector("#reading-position-button")?.disabled,'+
      'beforePositionClick:globalThis.__positionBeforeClick,notice:document.querySelector("#notice-text")?.textContent,'+
      'dialogs:[...document.querySelectorAll("dialog")].map(d=>({status:d.querySelector("[role=status]")?.textContent,pageDisabled:d.querySelector("#position-page")?.disabled}))})');
    throw Error('Actual app hook timed out: '+label+' '+evidence);
  };
  await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/index.html`});
  await wait('Boolean(document.querySelector(".layout"))','demo startup');
  await evaluate('[...document.querySelectorAll("header button")].find(b=>["Connection","連線"].includes(b.textContent)).click()');
  const config={workspace:positionReady.workspace,device:'unsent-receiver',origin:`http://127.0.0.1:${server.address().port}`,
    token:positionReady.unsent_receiver_token};
  const stateExpression=`(async()=>{const {IndexedStore}=await import('./store.mjs'),s=await IndexedStore.open(${JSON.stringify(config.workspace)},${JSON.stringify(config.device)});try{return await s.read();}finally{s.close();}})()`;
  await evaluate(`(()=>{const c=${JSON.stringify(config)},d=document.querySelector('dialog'),inputs=d.querySelectorAll('.fields input');
    [c.workspace,c.device,c.origin,c.token].forEach((value,i)=>inputs[i].value=value);d.querySelector('.connection-fields').closest('details').open=true;d.querySelector('.connection-fields button.primary').click();return true;})()`);
  await wait(`document.querySelector('.workspace')?.textContent===${JSON.stringify(positionReady.workspace)} &&
    !document.querySelector('header button')?.disabled && !!document.querySelector('.paper-card')`,'private fake connection');
  await evaluate('document.querySelector(".paper-card").click();document.querySelector("#tab-pdf").click()');
  await evaluate('[...document.querySelectorAll("main button")].find(b=>["Save PDF offline","下載 PDF 供離線閱讀"].includes(b.textContent)).click()');
  await wait('Boolean([...document.querySelectorAll("main button")].find(b=>["Open verified PDF","開啟已驗證 PDF"].includes(b.textContent))?.disabled===false)','verified primary');
  await evaluate('[...document.querySelectorAll("main button")].find(b=>["Open verified PDF","開啟已驗證 PDF"].includes(b.textContent)).click()');
  await wait('Boolean(document.querySelector("object.pdf-frame"))','actual current PDF');
  await evaluate('globalThis.__positionMainPDF=document.querySelector("object.pdf-frame").data;document.querySelector("#tab-notes").click();'+
    '[...document.querySelectorAll("main button")].find(b=>b.textContent.includes("New note")||b.textContent.includes("新增筆記")).click();'+
    'document.querySelector("#note-editor").value="Keep main reader draft";document.querySelector("#note-editor").dispatchEvent(new Event("input",{bubbles:true}));'+
    'document.querySelector("#tab-pdf").click();document.querySelector("#reading-position-button").click()');
  await wait('document.querySelector(".position-dialog #position-page")?.disabled===false','PDF-card dialog count');
  const blocked=await evaluate('(()=>{const d=document.querySelector(".position-dialog"),p=d.querySelector("#position-page");p.value="2";p.dispatchEvent(new Event("input",{bubbles:true}));'+
    'return [...d.querySelectorAll("button")].find(b=>["Remember","記住頁碼"].includes(b.textContent)).disabled;})()');
  if(!blocked)throw Error('Actual note draft did not block Remember');
  await wait(`(async()=>{const s=await ${stateExpression};return Object.values(s.drafts).includes('Keep main reader draft');})()`,'note draft commit after tab switch');
  if(await evaluate('document.querySelector(".status")?.dataset.error==="true"'))throw Error('Committed draft falsely reported storage failure after PDF tab switch');
  if(process.env.PAPERFACT_TEST_SCREENSHOTS) {
    await mkdir(process.env.PAPERFACT_TEST_SCREENSHOTS,{recursive:true});
    const shot=await send('Page.captureScreenshot',{format:'png'});
    await writeFile(join(process.env.PAPERFACT_TEST_SCREENSHOTS,'main-draft-hook.png'),Buffer.from(shot.data,'base64'));
  }
  await evaluate('(()=>{const d=document.querySelector(".position-dialog");[...d.querySelectorAll("button")].find(b=>["Close","關閉"].includes(b.textContent)).click();'+
    '[...d.querySelectorAll("button")].find(b=>["Discard changes","捨棄變更"].includes(b.textContent)).click();})()');
  await wait('!document.querySelector(".position-dialog")','draft-safe modal close');
  await evaluate('document.querySelector("#tab-notes").click()');
  if(!await evaluate('document.querySelector("#note-editor")?.value==="Keep main reader draft"'))throw Error('Reading position discarded actual note draft');
  await evaluate('[...document.querySelectorAll("main button")].find(b=>["Save note","儲存筆記"].includes(b.textContent)).click()');
  await wait(`(async()=>{const s=await ${stateExpression};return s.outbox.some(row=>row.operation.entity_type==='note'&&row.operation.payload.body==='Keep main reader draft');})()`,'actual note save');
  await evaluate('document.querySelector("#tab-pdf").click();globalThis.__positionBeforeClick=document.querySelector("#reading-position-button").disabled;document.querySelector("#reading-position-button").click()');
  await wait('document.querySelector(".position-dialog #position-page")?.disabled===false','unblocked position count');
  await evaluate('(()=>{const d=document.querySelector(".position-dialog"),p=d.querySelector("#position-page");globalThis.__positionRequestedPage=p.value==="1"?2:1;'+
    'p.value=String(globalThis.__positionRequestedPage);p.dispatchEvent(new Event("input",{bubbles:true}));'+
    '[...d.querySelectorAll("button")].find(b=>["Remember","記住頁碼"].includes(b.textContent)).click();})()');
  await wait('!document.querySelector(".position-dialog")','actual remembered page');
  const correct=await evaluate(`(async()=>{const s=await ${stateExpression},positions=s.outbox.filter(row=>row.operation.payload?.feature==='reading_position');
    return positions.length===1&&positions[0].operation.payload.data.page===globalThis.__positionRequestedPage&&
      positions[0].operation.payload.data.method==='entered'&&s.outbox.filter(row=>row.operation.entity_type==='note'&&row.operation.payload.body==='Keep main reader draft').length===1&&
      document.querySelector('object.pdf-frame')?.data===globalThis.__positionMainPDF;})()`,true);
  if(!correct)throw Error('Actual PDF-card hook changed current PDF/note or saved duplicate/wrong page');
  console.log('PASS actual app PDF-card Reading position hook honors raw note drafts, real count, exact entered page, duplicate-free queue and unchanged loaded primary');
}
try {
  const endpoint = await new Promise((resolve, reject) => {
    let output = '';
    const timeout = setTimeout(() => reject(new Error('Browser did not expose test debugging socket')),
    15000);
    browser.stderr.on(
    'data',
    chunk => {
      output += chunk;
      const match = output.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if(match) {
        clearTimeout(timeout);
        resolve(match[1]);
      }
    }
    );
    browser.on('error', reject);
  });
  socket = new WebSocket(endpoint);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  socket.onmessage = event => {
    const value = JSON.parse(event.data);
    if(value.id) {
      const promise = pending.get(value.id);
      pending.delete(value.id);
      if(value.error) promise.reject(new Error(value.error.message));
      else promise.resolve(value.result);
    } else if(value.method === 'Runtime.exceptionThrown') {browserErrors.push(value.params.exceptionDetails.text);process.stderr.write('Browser exception: ' + JSON.stringify(value.params.exceptionDetails) + '\n');}
  };
  const target = await send('Target.createTarget', {
    url: 'about:blank'
  }, null);
  session =(await send('Target.attachToTarget', {
    targetId: target.targetId,
    flatten: true
  }, null)).sessionId;
  await send('Runtime.enable');
  await send('Page.enable');
  if(offlineReadingMode) {await offlineReadingMainHook();} else {
  await send('Page.navigate', {
    url: `http://127.0.0.1:${server.address().port}/${testPage}`
  });
  let finished = false, offlineStarted=false, onlineStarted=false;
  const metricSeen=new Set(),keySeen=new Set(),captureSeen=new Set();
  for(let tick = 0; tick < 160; tick++) {
    await new Promise(resolve => setTimeout(resolve, 250));
    const result = await send(
    'Runtime.evaluate',
    {
      expression: 'JSON.stringify({done:document.body?.dataset.result,offlineReady:document.body?.dataset.offlineReady,metrics:document.body?.dataset.metrics,onlineReady:document.body?.dataset.onlineReady,keyboard:document.body?.dataset.keyboard,capture:document.body?.dataset.capture,text:document.querySelector("#result")?.textContent})',
      returnByValue: true
    }
    );
    const value = JSON.parse(result.result.value ?? '{}');
    if(typeof value.text==='string')lastFixtureText=value.text;
    if(['position-ui-browser-test.html','browser-pairing-browser-test.html'].includes(testPage)) {
      if(value.metrics&&!metricSeen.has(value.metrics)) {
        const sizes={'phone-en':[390,844,true],'phone-zh':[360,780,true],'laptop-en':[1280,900,false]},size=sizes[value.metrics];
        if(!size)throw Error('Unknown fixture viewport');metricSeen.add(value.metrics);
        await send('Emulation.setDeviceMetricsOverride',{width:size[0],height:size[1],deviceScaleFactor:1,mobile:size[2]});
        await send('Runtime.evaluate',{expression:'document.body.dataset.metricsReady='+JSON.stringify(value.metrics)});
      }
      if(value.capture&&!captureSeen.has(value.capture)) {
        if(!['phone-en','phone-zh'].includes(value.capture))throw Error('Unknown fixture capture');captureSeen.add(value.capture);
        if(process.env.PAPERFACT_TEST_SCREENSHOTS) {
          await mkdir(process.env.PAPERFACT_TEST_SCREENSHOTS,{recursive:true});
          const shot=await send('Page.captureScreenshot',{format:'png'});
          await writeFile(join(process.env.PAPERFACT_TEST_SCREENSHOTS,value.capture+'.png'),Buffer.from(shot.data,'base64'));
        }
        await send('Runtime.evaluate',{expression:'document.body.dataset.captureReady='+JSON.stringify(value.capture)});
      }
      if(value.keyboard&&!keySeen.has(value.keyboard)) {
        const keys={'pair-en':['Enter','Enter',13],'remember-zh':['Enter','Enter',13],'dirty-escape-en':['Escape','Escape',27]},key=keys[value.keyboard];
        if(!key)throw Error('Unknown fixture key');keySeen.add(value.keyboard);
        await send('Input.dispatchKeyEvent',{type:'keyDown',key:key[0],code:key[1],windowsVirtualKeyCode:key[2],
          ...(key[0]==='Enter'?{text:'\r',unmodifiedText:'\r'}:{})});
        await send('Input.dispatchKeyEvent',{type:'keyUp',key:key[0],code:key[1],windowsVirtualKeyCode:key[2]});
      }
    }
    if(pairingMode&&value.offlineReady&&!offlineStarted) {
      offlineStarted=true;await send('Network.enable');
      await send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
      await send('Runtime.evaluate',{expression:'document.body.dataset.offlineActive="true"'});
    }
    if(pairingMode&&value.onlineReady&&!onlineStarted) {
      onlineStarted=true;
      await send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
      await send('Runtime.evaluate',{expression:'document.body.dataset.onlineActive="true"'});
    }
    if(['position-browser-test.html','position-ui-browser-test.html'].includes(testPage) && value.offlineReady && !offlineStarted) {
      offlineStarted=true;
      await send('Network.enable');
      await send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
      await send('Runtime.evaluate',{expression:'void globalThis.runOfflinePositionChecks()'});
    }
    if(value.done) {
      console.log(value.text);
      if(value.done !== 'pass') process.exitCode = 1;
      if(value.done==='pass'&&testPage==='position-ui-browser-test.html')await positionMainHook();
      finished = true;
      break;
    }
  }
  if(! finished) {
    const result = await send(
    'Runtime.evaluate',
    {
      expression: 'document.querySelector("#result")?.textContent',
      returnByValue: true
    }
    );
    throw new Error('Browser fixture timed out: ' + result.result.value);
  }
  if(plainNoteMode && process.exitCode!==1)await plainNoteMainHook();
  if(process.argv[3]) {
    await mkdir(process.argv[3], {
      recursive: true
    });
    await send('Page.navigate', {
      url: `http://127.0.0.1:${server.address().port}/index.html`
    });
    for(let tick = 0; tick < 40; tick++) {
      await new Promise(resolve => setTimeout(resolve, 100));
      const ready = await send(
      'Runtime.evaluate',
      {
        expression: 'Boolean(document.querySelector(".layout"))',
        returnByValue: true
      }
      );
      if(ready.result.value) break;
    }
    await send('Runtime.evaluate', {
      expression: 'document.querySelector(".paper-card")?.click()'
    });
    await send('Runtime.evaluate', {expression:'document.querySelector("#tab-slides")?.click()'});
    for(let tick=0;tick<60;tick++) {
      const ready=await send('Runtime.evaluate',{expression:'Boolean(document.querySelector(".slide-surface img")?.complete && document.querySelector(".slide-surface img")?.naturalWidth)',returnByValue:true});
      if(ready.result.value) break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    for(const [name, width, height, mobile] of[['slides-desktop', 1320, 900, false], ['slides-phone', 390, 844, true]]) {
      await send(
      'Emulation.setDeviceMetricsOverride',
      {
        width,
        height,
        deviceScaleFactor: 1,
        mobile
      }
      );
      await new Promise(resolve => setTimeout(resolve, 200));
      const shot = await send('Page.captureScreenshot', {
        format: 'png',
        captureBeyondViewport: false
      });
      await writeFile(join(process.argv[3], name + '.png'), Buffer.from(shot.data, 'base64'));
    }
  }
  }
} finally {
  if(socket?.readyState === WebSocket.OPEN) {
    await send('Browser.close', {}, null).catch(() => {});
    socket.close();
  }
  if(browser.exitCode===null&&browser.signalCode===null){
    await new Promise(resolve=>{
      const timer=setTimeout(()=>{browser.kill();resolve();},3000);
      browser.once('exit',()=>{clearTimeout(timer);resolve();});
    });
  }
  server.closeAllConnections();server.close();
  if(positionService) {
    positionService.stdin.end(plainNoteMode ? JSON.stringify({command:'quit'})+'\n' : 'quit\n');
    const code=await new Promise(resolve=>{if(positionService.exitCode!==null){resolve(positionService.exitCode);return;}
      positionService.once('exit',resolve);setTimeout(()=>{positionService.kill();resolve(null);},5000).unref();});
    if(code!==0){process.exitCode=1;console.error('Position service cleanup failed: '+positionErrors);}
  }
  // This exact directory was created by mkdtemp above; never enumerate TEMP.
  const owned=relative(resolve(tmpdir()),resolve(profile));
  if(!owned.startsWith('paperfact-mobile-fixture-')||owned.includes('/')||owned.includes('\\')||isAbsolute(owned))throw Error('Unexpected owned browser profile path');
  await rm(profile,{recursive:true,force:true,maxRetries:3,retryDelay:100});
}
