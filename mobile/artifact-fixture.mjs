/** Synthetic deck for native browser rendering checks; no real research. */
import {PAPER} from './fixture.mjs';
import {stable} from './domain.mjs';
import {digest} from './artifact-engine.mjs';
export async function artifactFixture() {
  const image=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAACXBIWXMAAA7EAAAOxAGVKw4bAAAADklEQVR4nGM4AQYMEAoAQa4JYQOnncMAAAAASUVORK5CYII='),c=>c.charCodeAt(0));
  const body={version:1,evidence_asset:null,deck:{paper_id:PAPER,paper_title:'Synthetic research',title:'From evidence to understanding',mode:'guide',audience:'Research colleagues',minutes:10,
    slides:[{title:'Why this result matters',section:'RESEARCH CONTEXT',takeaway:'Make the evidence traceable to the original paper.',bullets:['Start with the research question.','Explain the result and its limits.'],
      speaker_notes:'This synthetic slide shows how a reading guide retains its background and citations. No personal research is included.',sources:['figure-1'],figure:'figure-1',elements:null}],
    sources:[{id:'figure-1',label:'Figure 1 · illustrative evidence',kind:'figure',page:1}],figures:[{id:'figure-1',label:'Synthetic figure',asset_id:'image',caption:'An intentionally simple test image',page:1}],
    coverage:['Background','Main result'],created_at:'2026-10-26T00:00:00Z',deck_id:'browser-fixture',source_hash:'',generation:{},edited:false,version:1}};
  const raw=new TextEncoder().encode(stable(body)), bodyHash=await digest(raw),imageHash=await digest(image);
  return {body,blobs:new Map([[bodyHash,raw],[imageHash,image]]),payload:{paper_id:PAPER,feature:'deck',slot:'guide',format_version:1,source_document_hash:null,
    input_versions:{schema_version:1,complete:false,entities:[],documents:[],inputs_sha256:null},body:{sha256:bodyHash,size:raw.length,media_type:'application/json'},
    assets:[{id:'image',role:'figure',sha256:imageHash,size:image.length,media_type:'image/png'}]}};
}
