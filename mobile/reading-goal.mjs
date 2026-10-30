/** Plain-text user intent, never interpreted as HTML or an automatic AI request. */
export function renderReadingGoal(parent, collection, el, t) {
  const section = collection?.analysis_sections?.find(item => item.kind === 'reading_goal');
  if (!section?.body?.trim()) return;
  parent.append(el('article', { class: 'card' },
    el('h2', {}, t('readingGoal')),
    el('p', { class: 'prose' }, section.body)));
}
