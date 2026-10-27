/** Read-only conversation rendering; el inserts text, never model HTML. */
import { chatExchanges } from './content.mjs';
export function renderChatCards(panel, paper, el, t) {
  for(const {question, answer, orphan} of chatExchanges(paper)) {
    const card = el('article', {class: 'card chat-exchange'}, el('h2', {}, t('research_chat')));
    if(question) card.append(el('h3', {}, t('chatQuestion')), el('div', {class: 'prose chat-question'}, question.data.body));
    if(answer) card.append(el('h3', {}, t('chatAnswer')), el('div', {class: 'prose chat-answer'}, answer.data.body));
    if(orphan || !answer) card.append(el('p', {class: 'muted'}, t(orphan ? 'chatOrphan': 'chatPending')));
    panel.append(card);
  }
}
