/** Download exact manifest closures; activation never outruns verified bytes. */
import {copy,own,put} from './store.mjs';
import {active,keyOf,stable,validateOperation} from './domain.mjs';
import {CHUNK} from './transport.mjs';
import {artifactJSON,validateArtifact,validateDeck,validateEvidence,validatePNG,requireArtifact} from './artifacts.mjs';
export const ARTIFACT_CACHE_BYTES = 128 * 1024 ** 2;
export const digest = async bytes => [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))]
  .map(value=>value.toString(16).padStart(2,'0')).join('');
export function artifactTarget(state,id) {
  const entry=own(state.entities,keyOf('research_file',id));
  return entry && active(state,'research_file',id) ? copy(entry.operation) : null;
}
function joined(file) {
  requireArtifact(file && Number.isSafeInteger(file.size) && file.size>0);
  const bytes=new Uint8Array(file.size); let offset=0;
  for (const chunk of file.chunks) {
    requireArtifact(chunk instanceof Uint8Array && offset+chunk.length<=bytes.length);
    bytes.set(chunk,offset); offset+=chunk.length;
  }
  requireArtifact(offset === bytes.length); return bytes;
}
function current(state,target) {
  requireArtifact(stable(artifactTarget(state,target.entity_id))===stable(target),'stale_artifact');
}
async function closure(state,target) {
  validateArtifact(target.payload,target.entity_id,target.parents);
  const blobs=new Map();
  for (const descriptor of [target.payload.body,...target.payload.assets]) {
    if (blobs.has(descriptor.sha256)) continue;
    const file=own(state.artifactFiles ?? {},descriptor.sha256);
    requireArtifact(file?.verified && file.size===descriptor.size,'artifact_unavailable');
    const bytes=joined(file);
    requireArtifact(await digest(bytes)===descriptor.sha256,'corrupt_file');
    blobs.set(descriptor.sha256,bytes);
  }
  const body=validateDeck(artifactJSON(blobs.get(target.payload.body.sha256)),target.payload);
  for (const asset of target.payload.assets) {
    if (asset.role==='figure') await validatePNG(blobs.get(asset.sha256));
    else if (asset.role==='evidence') validateEvidence(artifactJSON(blobs.get(asset.sha256)));
    else throw new Error('invalid_artifact');
  }
  return {body,blobs};
}
export async function downloadArtifact(engine,id,token,generation) {
  await engine.authenticated(generation);
  const target=artifactTarget(await engine.store.read(),id);
  requireArtifact(target,'artifact_unavailable');
  validateArtifact(target.payload,id,target.parents);
  const unique=new Map([target.payload.body,...target.payload.assets].map(row=>[row.sha256,row]));
  let done=0; const total=[...unique.values()].reduce((n,row)=>n+row.size,0);
  for (const description of unique.values()) {
    const state=await engine.store.read(); engine.check(generation); current(state,target);
    const existing=own(state.artifactFiles ?? {},description.sha256);
    const chunks=existing?.size===description.size ? copy(existing.chunks) : [];
    let offset=0;
    for (const chunk of chunks) {
      requireArtifact(chunk instanceof Uint8Array && chunk.length>0 && chunk.length<=CHUNK);
      offset+=chunk.length;
    }
    requireArtifact(offset<=description.size);
    while (offset<description.size) {
      const bytes=await engine.transport.blob_read(token,description.sha256,description.size,offset,CHUNK,engine.controller.signal);
      engine.check(generation);
      requireArtifact(bytes instanceof Uint8Array && bytes.length===Math.min(CHUNK,description.size-offset),'invalid_file');
      chunks.push(bytes); offset+=bytes.length;
      await engine.store.update(next=>{
        engine.check(generation); current(next,target);
        next.artifactFiles ??= {};
        const used=Object.entries(next.artifactFiles).filter(([hash])=>hash!==description.sha256)
          .reduce((n,[,file])=>n+file.chunks.reduce((size,chunk)=>size+chunk.length,0),0);
        requireArtifact(used+offset<=ARTIFACT_CACHE_BYTES,'storage_quota');
        put(next.artifactFiles,description.sha256,{size:description.size,chunks:copy(chunks),verified:false});
      });
      engine.onChange('downloading',Math.floor((done+offset)/total*100));
    }
    const bytes=joined({size:description.size,chunks});
    if (await digest(bytes)!==description.sha256) {
      await engine.store.update(next=>{
        engine.check(generation); current(next,target);
        next.artifactFiles ??= {}; put(next.artifactFiles,description.sha256,{size:description.size,chunks:[],verified:false});
      });
      throw new Error('corrupt_file');
    }
    await engine.store.update(next=>{
      engine.check(generation); current(next,target); next.artifactFiles ??= {};
      put(next.artifactFiles,description.sha256,{size:description.size,chunks:copy(chunks),verified:true});
    });
    done+=description.size;
  }
  await closure(await engine.store.read(),target); engine.check(generation);
  await engine.store.update(next=>{
    engine.check(generation); current(next,target); next.appliedArtifacts ??= {};
    put(next.appliedArtifacts,id,{operation:copy(target)});
  });
  engine.onChange('file_ready'); return id;
}
export async function readArtifact(engine,id) {
  const generation=engine.generation, state=await engine.store.read();
  const target=artifactTarget(state,id), applied=own(state.appliedArtifacts ?? {},id)?.operation;
  requireArtifact(target && applied && target.incarnation===applied.incarnation && stable(target.parents)===stable(applied.parents),'artifact_unavailable');
  validateOperation(applied,state.workspace);
  requireArtifact(applied.entity_type==='research_file' && applied.entity_id===id && applied.action==='put');
  const result=await closure(state,applied);
  engine.check(generation);
  const now=await engine.store.read(), latest=artifactTarget(now,id);
  requireArtifact(latest && latest.incarnation===applied.incarnation && stable(latest.parents)===stable(applied.parents) &&
    stable(own(now.appliedArtifacts ?? {},id)?.operation)===stable(applied),'stale_artifact');
  return {...result,operation:applied,awaiting:latest.operation_id!==applied.operation_id};
}
