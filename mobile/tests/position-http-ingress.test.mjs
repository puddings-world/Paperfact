import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {HttpTransport} from '../transport.mjs';
import {Engine} from '../engine.mjs';
import {MemoryStore} from '../store.mjs';
import {demoTransport,operation,ref,PAPER} from '../fixture.mjs';
import {receive} from '../domain.mjs';
const vectors=JSON.parse(readFileSync(new URL('../../tests/fixtures/reading-position-wire.json',import.meta.url),'utf8'));
test('actual HTTP rejects float/exponent position pages before cursor or data, escaped keys and note strings included',async()=>{
  const initial=await demoTransport(),store=new MemoryStore('demo-workspace','demo-phone');
  await store.update(state=>receive(state,initial.events));
  const before=await store.read(),position=structuredClone(vectors.cases[0].operation);
  position.payload.data.page=1;
  const note=operation('note','raw-wire-note',{paper_id:PAPER,body:'Nested text: "page":1.0 and \\u0070age:1e0'},{parents:[ref('paper',PAPER)]});
  const accepted=(operation,sequence)=>({sequence,outcome:'accepted',operation,head:{revision:sequence,operation}});
  const events=[accepted(position,before.cursor+1),accepted(note,before.cursor+2)];
  let token='1.0';
  const server=createServer(async(request,response)=>{
    assert.equal(request.headers.authorization,'Bearer fixture-token');
    const parts=[];for await(const part of request)parts.push(part);
    const body=JSON.parse(Buffer.concat(parts));
    let value;
    if(request.url==='/v1/session/info')value=JSON.stringify({workspace_id:'demo-workspace',device_id:'demo-phone'});
    else {
      assert.equal(request.url,'/v1/pull');
      value=body.after>=before.cursor+2?'[]':JSON.stringify(events)
        .replaceAll('"page":1,','"p\\u0061ge" : '+token+' ,');
    }
    response.writeHead(200,{'Content-Type':'application/json'});response.end(value);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try {
    const engine=new Engine(store,{transport:new HttpTransport('http://127.0.0.1:'+server.address().port)});
    await engine.connect('fixture-token');
    for(token of ['1.0','1e0']) {
      await assert.rejects(engine.sync(),/invalid_response/);
      assert.deepEqual(await store.read(),before);
    }
    token='1';await engine.sync();
    const state=await store.read();assert.equal(state.cursor,before.cursor+2);
    assert.equal(state.entities['note/raw-wire-note'].operation.payload.body,note.payload.body);
    assert.equal(state.entities['research_content/'+position.entity_id].operation.payload.data.page,1);
    engine.disconnect();
  } finally {await new Promise(resolve=>server.close(resolve));}
});
