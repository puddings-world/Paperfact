/** Read-only observations. Markdown always becomes a text node. */
export function renderLegacyWorkflow(panel,paper,el,t,options={}) {
  if(paper.queue_pin) panel.append(el('section',{class:'card'},
    el('h2',{},t('queuePin')),el('p',{class:'muted'},paper.queue_pin.pinned_at)));
  const queue=paper.legacy_queue,events=paper.reading_events??[];
  if(!queue && !events.length)return;
  const card=el('section',{class:'card'},el('h2',{},t('legacyHistory')),el('p',{class:'muted'},t('legacyReadOnly')));
  panel.append(card);
  if(queue)card.append(el('h3',{},t('legacyQueue')),el('p',{},t('legacyState_'+queue.state)),
    el('p',{},queue.role),el('p',{class:'prose'},queue.reason??''));
  for(const event of events) {
    const row=el('article',{},el('h3',{},event.data.delivered_at),el('p',{},event.data.role??''),
      el('p',{class:'prose'},event.data.note??''));card.append(row);
    if(!event.data.brief)continue;
    const manifest=(options.briefs??[]).find(f=>f.paper_id===paper.id && f.event_id===event.id);
    const body=el('pre',{class:'prose'},t('legacyBriefUnavailable'));row.append(body);
    if(!manifest || !options.read)continue;
    const current=()=>options.current?.()!==false;
    void options.read(manifest.id).then(result=>{
      if(current())body.replaceChildren(el('span',{},result.text));
    }).catch(()=>{});
    let pending=false;
    const button=el('button',{type:'button'},t('legacyDownload'));
    button.disabled=!options.canDownload;
    button.addEventListener('click',async()=>{
      if(pending || !options.canDownload || !current())return;
      pending=true;button.disabled=true;
      try {
        await options.download(manifest.id);
        if(!current())return;
        const result=await options.read(manifest.id);
        if(current())body.replaceChildren(el('span',{},result.text));
      } catch {
        if(current())body.replaceChildren(el('span',{},t('legacyBriefUnavailable')));
      } finally {
        pending=false;if(current())button.disabled=!options.canDownload;
      }
    });row.append(button);
  }
}
