import test from 'node:test';
import assert from 'node:assert/strict';
import { chatExchanges, validateContent } from '../content.mjs';
import { contentId } from '../ids.mjs';
import { renderChatCards } from '../chat-view.mjs';
import { translator } from '../i18n.mjs';
import { MemoryStore } from '../store.mjs';
import { projection, receive } from '../domain.mjs';
import { demoTransport, operation, PAPER, ref } from '../fixture.mjs';
const uid = n => '10000000-0000-4000-8000-' + String(n).padStart(12, '0');
function row(n, role, exchange = 1, reply = null) {
  return {feature:'chat', key:uid(n), data:{role, body:role+' '+n,
    created_at:'2026-10-27T00:00:00Z',page:null,anchor:null,
    exchange_id:uid(exchange+100),reply_to:reply===null?null:uid(reply)}};
}
function payload(item) { return {scope:{kind:'paper',id:PAPER}, feature:'chat',key:item.key,data:item.data,source_document_hash:null}; }
function validate(item) { const p=payload(item); validateContent(p,contentId(p.scope,'chat',p.key),[ref('paper',PAPER)]); }
const pairs = paper => chatExchanges(paper).map(({question,answer,orphan})=>[question?.key??null,answer?.key??null,orphan]);

test('closed optional chat link pair mirrors desktop and preserves legacy',()=>{
  validate(row(1,'user')); validate(row(2,'assistant',1,1));
  const legacy=row(3,'system'); delete legacy.data.exchange_id; delete legacy.data.reply_to; validate(legacy);
});
for(const [name,change] of [
  ['missing exchange',d=>delete d.exchange_id],['missing reply',d=>delete d.reply_to],
  ['unknown field',d=>d.other=true],['bad exchange',d=>d.exchange_id='x'],
  ['uppercase UUID',d=>d.exchange_id='AAAAAAAA-0000-4000-8000-000000000000'],
  ['nonstring exchange',d=>d.exchange_id=3],['bad reference',d=>d.reply_to='x'],
  ['null assistant reference',d=>d.reply_to=null],['self reply',d=>d.reply_to=uid(2)],
  ['linked system',d=>d.role='system'],['user with reply',d=>d.role='user']
]) test('invalid linked chat rejects '+name,()=>{ const item=row(2,'assistant',1,1);change(item.data);assert.throws(()=>validate(item)); });

test('interleaved identical questions and answers pair by portable reference, not position',()=>{
 const a=row(1,'user',1),b=row(2,'user',2),aa=row(3,'assistant',1,1),bb=row(4,'assistant',2,2);
 a.data.body=b.data.body='Same question';
 assert.deepEqual(pairs({research_content:[a,b,bb,aa]}),[[uid(1),uid(3),false],[uid(2),uid(4),false]]);
 assert.deepEqual(pairs({research_content:[aa,b,bb,a]}),[[uid(2),uid(4),false],[uid(1),uid(3),false]]);
});
test('orphan, wrong exchange and other-paper turns never attach to adjacent user',()=>{
 const question=row(1,'user',1), answer=row(2,'assistant',2,1);
 assert.deepEqual(pairs({research_content:[question,answer]}),[[uid(1),null,false],[null,uid(2),true]]);
 assert.deepEqual(pairs({research_content:[row(3,'assistant',1,1)]}),[[null,uid(3),true]]);
 assert.deepEqual(pairs({research_content:[]}),[]);
});
test('legacy adjacency remains but linked rows interrupt legacy pairing',()=>{
 const q=row(1,'user'),a=row(2,'assistant');
 for(const item of [q,a]) {delete item.data.exchange_id;delete item.data.reply_to;}
 assert.deepEqual(pairs({research_content:[q,a]}),[[uid(1),uid(2),false]]);
 assert.deepEqual(pairs({research_content:[q,row(3,'user',3),a]}),[[uid(1),null,false],[uid(3),null,false],[null,uid(2),true]]);
});
test('contiguous received answer before user survives offline persistence and later pairing without outbox',async()=>{
 const transport=await demoTransport(),store=new MemoryStore('demo-workspace','demo-phone');
 await store.update(s=>receive(s,transport.events));
 const event=(item,sequence)=>{ const p=payload(item),op=operation('research_content',contentId(p.scope,'chat',p.key),p,{parents:[ref('paper',PAPER)]});return {sequence,outcome:'accepted',operation:op,head:{revision:sequence,operation:op}}; };
 await store.update(s=>receive(s,[event(row(2,'assistant',1,1),7)]));
 const reopened=new MemoryStore('demo-workspace','demo-phone',JSON.parse(JSON.stringify(await store.read())));
 assert.deepEqual(pairs(projection(await reopened.read()).papers[0]),[[null,uid(2),true]]);
 await reopened.update(s=>receive(s,[event(row(1,'user',1),8)]));
 const state=await reopened.read();
 assert.deepEqual(pairs(projection(state).papers[0]),[[uid(1),uid(2),false]]);
 assert.equal(state.cursor,8);assert.deepEqual(state.outbox,[]);
});
test('read-only cards render paired and orphan bodies as text with localized status',()=>{
 const el=(tag,attrs={},...children)=>({tag,attrs,children,append(...items){this.children.push(...items);}});
 const panel=el('section'),answer=row(2,'assistant',1,1);answer.data.body='<script>never execute</script>';
 renderChatCards(panel,{research_content:[answer]},el,translator('en'));
 const card=panel.children[0];assert.equal(card.attrs.class,'card chat-exchange');
 assert.equal(card.children[2].children[0],answer.data.body);
 assert.equal(card.children[3].children[0],'The linked question is not available on this device.');
 const pending=el('section');renderChatCards(pending,{research_content:[row(1,'user')]},el,translator('zh-TW'));
 assert.equal(pending.children[0].children.at(-1).children[0],'這個問題尚未收到回答。');
});
