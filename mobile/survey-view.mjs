/** Saved-only list overview. All research strings become literal text nodes. */
export const SURVEY_COPY={"en":{"title":"List research overview","notSaved":"Report not downloaded.","download":"Save report offline","working":"Downloading report...","ready":"Report saved offline","update":"Saved report - update available","retry":"Could not load the report. Retry when connected.","sourceNote":"Retained excerpts; original PDFs download separately.","sources":"Source records","passages":"Source excerpts","captured":"Original captured for this report","unavailable":"Original unavailable","not_selected":"Original not selected","located":"Retained location","missing":"Location unresolved"},"zh-TW":{"title":"??????","notSaved":"???????","download":"?????????","working":"???????","ready":"????????","update":"?????????????","retry":"????????????????","sourceNote":"?????????PDF ??????","sources":"????","passages":"????","captured":"??????????","unavailable":"???????","not_selected":"?????","located":"???????","missing":"?????"}};
export function renderSurveys(panel,collection,rows,el,options={}){
  if(!collection)return;
  const selected=(rows??[]).filter(row=>row.list_id===collection.id);
  if(!selected.length)return;
  const t=SURVEY_COPY[options.language]??SURVEY_COPY.en;
  for(const row of selected){
    const status=el('p',{class:'muted','aria-live':'polite'},t.notSaved);
    const body=el('div',{}),button=el('button',{type:'button'},t.download);
    button.disabled=!options.canDownload;
    const card=el('section',{class:'card'},el('h2',{},t.title),status,button,body);
    panel.append(card);let pending=false;
    const current=()=>options.current?.()!==false;
    const show=result=>{
      if(!current())return;
      const report=result.body.report,names=new Map(report.inputs.members.map(member=>[member.paper_id,member.title]));
      status.replaceChildren(result.awaiting?t.update:t.ready);button.hidden=!result.awaiting;
      const contents=[el('p',{class:'muted'},t.sourceNote)];
      for(const section of report.sections){
        const block=el('article',{},el('h3',{},section.heading));
        for(const item of section.statements){
          block.append(el('p',{class:'prose'},item.text));
          if(item.passages.length){
            const excerpts=el('details',{},el('summary',{},t.passages+' ('+item.passages.length+')'));
            for(const passage of item.passages)excerpts.append(el('blockquote',{class:'prose'},passage.quote),
              el('p',{class:'muted'},passage.location?.state==='located'?
                t.located+' - '+passage.location.page:t.missing));
            block.append(excerpts);
          }
        }
        contents.push(block);
      }
      const sources=el('details',{},el('summary',{},t.sources+' ('+report.sources.length+')'));
      let populated=false;sources.addEventListener('toggle',()=>{
        if(!sources.open||populated||!current())return;populated=true;
        for(const source of report.sources)sources.append(el('p',{},names.get(source.paper_id)??source.paper_id),
          el('p',{class:'muted'},t[source.state]));
      });contents.push(sources);body.replaceChildren(...contents);
    };
    if(options.read)void options.read(row.id).then(show).catch(()=>{});
    button.addEventListener('click',async()=>{
      if(pending||!options.canDownload||!current())return;
      pending=true;button.disabled=true;status.replaceChildren(t.working);
      try{await options.download(row.id);if(current())show(await options.read(row.id));}
      catch{if(current())status.replaceChildren(t.retry);}
      finally{pending=false;if(current())button.disabled=!options.canDownload;}
    });
  }
}
