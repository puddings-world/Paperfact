import test from 'node:test';
import assert from 'node:assert/strict';
import { operation } from '../fixture.mjs';
import { emptyState } from '../store.mjs';
import { receive, projection, validateOperation } from '../domain.mjs';

for(const note of [null,'',' ','Background research']) test(`v2 list note ${JSON.stringify(note)} remains exact in projection and restart`,()=>{
  const op=operation('list','nullable-route',{name:'Reading',note});
  validateOperation(op,'demo-workspace');
  const state=emptyState('demo-workspace','phone');
  receive(state,[{sequence:1,outcome:'accepted',operation:op,head:{revision:1,operation:op}}]);
  assert.equal(projection(state).lists[0].note,note);
  const restarted=JSON.parse(JSON.stringify(state));
  assert.equal(projection(restarted).lists[0].note,note);
  receive(restarted,[{sequence:1,outcome:'accepted',operation:op,head:{revision:1,operation:op}}]);
  assert.equal(projection(restarted).lists.length,1);
  assert.equal(projection(restarted).lists[0].note,note);
});
test('v1 null and non-text scalar/object v2 list notes remain rejected',()=>{
  const modern=operation('list','nullable-route',{name:'Reading',note:null});
  const {incarnation,parents,structure_revision,...old}=modern;
  assert.throws(()=>validateOperation({...old,version:1},'demo-workspace'));
  for(const note of [false,true,0,1.0,[],{},'x'.repeat(128*1024+1)])
    assert.throws(()=>validateOperation({...modern,payload:{name:'Reading',note}},'demo-workspace'));
  assert.throws(()=>validateOperation({...modern,payload:{name:'Reading',note:null,unknown:1}},'demo-workspace'));
});
