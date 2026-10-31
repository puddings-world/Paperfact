/** Count exact verified bytes in an owned real worker; no viewer or scripting UI. */
export const PDF_PARSER_VERSION='6.4.299',MAX_COUNT_PDF=32*1024**2;
const proofs=new WeakSet(),jobs=new Set();let library;
const expect=(value,code)=>{if(!value)throw Error(code);};
export function requirePDFPageProof(proof,sha256,page) {
  expect(proof && proofs.has(proof) && proof.sha256===sha256,'pdf_count_required');
  expect(Number.isSafeInteger(page) && page>=1 && page<=proof.pageCount,'page_out_of_bounds');
  return proof;
}
export async function countPDFPages({bytes,sha256},{signal,timeoutMs=30000}={}) {
  expect(bytes instanceof Uint8Array && bytes.length>0 && bytes.length<=MAX_COUNT_PDF,'pdf_count_size_limit');
  expect(typeof sha256==='string' && /^[0-9a-f]{64}$/.test(sha256),'invalid_pdf_hash');
  expect(Number.isSafeInteger(timeoutMs) && timeoutMs>=1 && timeoutMs<=30000,'invalid_parse_deadline');
  expect(!signal?.aborted,'cancelled');expect(jobs.size<1,'pdf_parser_busy');
  // The parser may transfer its input buffer. Neither caller bytes nor cache chunks detach.
  const size=bytes.length,data=new Uint8Array(bytes),job={};jobs.add(job);
  let task,worker,nativeWorker,timer,retired=false,rejectStop;
  const stopped=new Promise((_,reject)=>{rejectStop=reject;});
  const stop=code=>{retired=true;rejectStop(Error(code));};
  const abort=()=>stop('cancelled'),workerError=()=>stop('pdf_parser_unavailable');
  signal?.addEventListener('abort',abort,{once:true});
  timer=setTimeout(()=>stop('pdf_parse_timeout'),timeoutMs);
  const check=()=>expect(!retired && !signal?.aborted,'cancelled');
  const work=(async()=>{
    const actual=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))]
      .map(value=>value.toString(16).padStart(2,'0')).join('');
    expect(actual===sha256,'corrupt_file');check();
    library??=import('./vendor/pdfjs-6.4.299/pdf.mjs').catch(error=>{library=null;throw error;});
    const pdf=await library;check();expect(pdf.version===PDF_PARSER_VERSION,'pdf_parser_version');
    expect(typeof Worker==='function','pdf_worker_required');
    nativeWorker=new Worker(new URL('./vendor/pdfjs-6.4.299/pdf.worker.mjs',import.meta.url),
      {type:'module',name:'Paperfact PDF page verification'});
    nativeWorker.addEventListener('error',workerError);
    worker=pdf.PDFWorker.create({port:nativeWorker});
    task=pdf.getDocument({data,worker,stopAtErrors:true,enableXfa:false,useWasm:false,useWorkerFetch:false,
      disableFontFace:true,useSystemFonts:false,disableRange:true,disableStream:true,disableAutoFetch:true});
    task.onPassword=()=>stop('pdf_password_required');
    const document=await task.promise;check();
    const count=document.numPages;
    expect(Number.isSafeInteger(count) && count>=1 && count<=1000001,'invalid_pdf_page_count');
    const last=await document.getPage(count);check();
    expect(last.pageNumber===count,'invalid_pdf_page_count');
    const proof=Object.freeze({sha256,size,pageCount:count,parserVersion:PDF_PARSER_VERSION});
    proofs.add(proof);return proof;
  })();
  try {return await Promise.race([work,stopped]);}
  finally {
    retired=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);
    let cleanupTimer;
    try {
      if(task)await Promise.race([task.destroy().catch(()=>{}),new Promise(resolve=>{cleanupTimer=setTimeout(resolve,250);})]);
    } finally {
      clearTimeout(cleanupTimer);nativeWorker?.removeEventListener('error',workerError);
      worker?.destroy();nativeWorker?.terminate();jobs.delete(job);
    }
  }
}
