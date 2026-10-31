/** Preserve Python's integer boundary for position pages before JSON erases 1.0. */
export function parsePositionJSON(source,{maxBytes=8*1024**2}={}) {
  if(!Number.isSafeInteger(maxBytes) || maxBytes<1 || maxBytes>64*1024**2 || typeof source!=='string' ||
    new TextEncoder().encode(source).length>maxBytes)throw Error('invalid_position_json');
  const value=JSON.parse(source),targets=new WeakSet(),todo=[value];let found=false;
  if(value?.format==='paperfact-mobile-recovery' && value.version===2 && Array.isArray(value.archives))
    for(const archive of value.archives)if(Array.isArray(archive?.positions))for(const row of archive.positions)
      if(row?.data && typeof row.data==='object'){targets.add(row.data);found=true;}
  while(todo.length) {
    const node=todo.pop();if(!node || typeof node!=='object')continue;
    if(node.entity_type==='research_content' && node.action==='put' && node.payload?.feature==='reading_position' &&
        node.payload.data && typeof node.payload.data==='object') {targets.add(node.payload.data);found=true;}
    if(Array.isArray(node.reading_positions))for(const row of node.reading_positions)if(row && typeof row==='object') {
      targets.add(row);found=true;
    }
    for(const child of Object.values(node))todo.push(child);
  }
  if(!found)return value;
  let at=0;
  const expect=value=>{if(!value)throw Error('invalid_position_json');};
  const space=()=>{while(/[ \t\r\n]/.test(source[at]??'!'))at++;};
  const string=()=>{
    expect(source[at]==='"');const start=at++;
    while(at<source.length) {
      const char=source[at++];if(char==='\\'){at++;continue;}
      if(char==='"')return JSON.parse(source.slice(start,at));
    }
    throw Error('invalid_position_json');
  };
  const walk=(node,depth,page=false)=>{
    expect(depth<=64);space();
    if(node && typeof node==='object') {
      if(Array.isArray(node)) {
        expect(source[at++]==='[');space();let index=0;
        if(source[at]!==']')while(true) {
          walk(node[index++],depth+1);space();if(source[at]!==',')break;at++;
        }
        expect(source[at++]===']' && index===node.length);return;
      }
      expect(source[at++]==='{');space();const seen=new Set();
      if(source[at]!=='}')while(true) {
        space();const key=string();expect(!seen.has(key) && Object.hasOwn(node,key));seen.add(key);
        space();expect(source[at++]===':');walk(node[key],depth+1,targets.has(node)&&key==='page');
        space();if(source[at]!==',')break;at++;
      }
      expect(source[at++]==='}' && seen.size===Object.keys(node).length);return;
    }
    if(typeof node==='string'){expect(string()===node);return;}
    for(const [word,known] of [['true',true],['false',false],['null',null]])if(node===known) {
      expect(source.startsWith(word,at));at+=word.length;return;
    }
    const number=source.slice(at).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
    expect(number && Number(number[0])===node);
    if(page)expect(/^[1-9]\d*$/.test(number[0]));
    at+=number[0].length;
  };
  walk(value,0);space();expect(at===source.length);return value;
}
