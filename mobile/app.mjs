import {
  IndexedStore,
  own,
  put
} from './store.mjs';
import {
  Engine,
  documentTarget
} from './engine.mjs';
import {
  active,
  keyOf,
  observeNote,
  projection,
  receive,
  states,
  statusFor
} from './domain.mjs';
import {
  HttpTransport
} from './transport.mjs';
import {
  demoTransport,
  demoProjection
} from './fixture.mjs';
import {
  translator
} from './i18n.mjs';
import {
  ReaderView,
  flushDrafts
} from './view.mjs';
import { renderChatCards } from './chat-view.mjs';
const app = document.querySelector('#app');
let deckURLs = [];
function clearDeckURLs() { deckURLs.forEach(url => URL.revokeObjectURL(url)); deckURLs = []; }
let switchingWorkspace = false;
let language = navigator.language.toLowerCase().startsWith('zh') ? 'zh-TW': 'en', t = translator(language);
let engine, store, state, view = new ReaderView(), notice = 'demoHelp', busy = false, isError = false,
demo = true, connected = false, pdfURL = null, pdfHash = null, renderSerial = 0, draftTimer;
const el =(tag, attributes = {}, ...children) => {
  const node = document.createElement(tag);
  for(const [key, value] of Object.entries(attributes)) {
    if(key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if(key === 'class') node.className = value;
    else if(value !== null && value !== undefined) node.setAttribute(key, String(value));
  }
  for(const child of children.flat(Infinity)) if(child !== null && child !== undefined) node.append(child instanceof Node ? child: document.createTextNode(String(child)));
  return node;
};
const button =(label, fn, attrs = {}) => el('button', {
  type: 'button',
  onclick: fn,
  ...attrs
}, label);
const text =(key, cls = 'muted') => el('p', {
  class: cls
}, t(key));
function clearPdf() {
  if(pdfURL) URL.revokeObjectURL(pdfURL);
  pdfURL = null;
  pdfHash = null;
}
async function attempt(action, {
  working = false
} = {}) {
  if(working && busy) return;
  if(working) {
    busy = true;
    render();
  }
  try {
    await action();
    isError = false;
  } catch(error) {
    notice = t(error.message) === t('error') ? 'error': error.message;
    isError = true;
  } finally {
    if(working) busy = false;
    await refresh();
  }
}
async function refresh() {
  if(! store) return;
  const owner = store,
  value = await owner.read();
  if(owner !== store) return;
  state = value;
  view.refresh(state);
  render();
}
function announce(code, progress) {
  notice = code;
  isError = false;
  if(code === 'downloading') notice = 'downloading';
  const live = document.querySelector('#notice-text');
  if(live) live.textContent = t(code) +(progress !== undefined ? ` · ${progress}%`: '');
  if(!['downloading', 'syncing'].includes(code)) void refresh();
}
async function openWorkspace(workspace, device, transport, {
  token = null,
  fixture = false
} = {}) {
  switchingWorkspace = true;
  render();
  try {
    clearTimeout(draftTimer);
    if(store) await flushDrafts(store, view);
    const next = await IndexedStore.open(workspace, device);
    engine?.disconnect();
    clearPdf();
    store?.close();
    connected = false;
    store = next;
    engine = new Engine(store, {
      transport,
      onChange: announce
    });
    view = new ReaderView();
    demo = fixture;
    await refresh();
    if(token) {
      await engine.connect(token);
      connected = true;
      await engine.sync();
    }
    if(fixture) await engine.importProjection(demoProjection);
    await refresh();
  } finally {
    switchingWorkspace = false;
    render();
  }
}
async function startDemo() {
  const authority = await IndexedStore.open('demo-workspace', 'fixture-authority');
  const retained = Object.values((await authority.read()).receipts).sort((a, b) => a.sequence - b.sequence);
  const transport = await demoTransport(retained.length ? retained: null);
  transport.persist = events => authority.update(next => receive(next, events));
  await transport.persist(transport.events);
  await openWorkspace('demo-workspace', 'demo-phone', transport, {
    token: 'fixture-token',
    fixture: true
  });
  notice = 'demoHelp';
  render();
}
function retainFocus() {
  const current = document.activeElement;
  return current?.id ? {
    id: current.id,
    start: current.selectionStart,
    end: current.selectionEnd,
    scroll: window.scrollY
  }
  : null;
}
function render() {
  if(! state) return;
  clearDeckURLs();
  const focus = retainFocus(),
  data = projection(state),
  paper = data.papers.find(p => p.id === view.paper),
  collection = data.lists.find(l => l.id === view.list);
  document.documentElement.lang = language;
  const serial =++ renderSerial;
  const header = el(
  'header',
  {},
  el(
  'div',
  {
    class: 'logo'
  },
  el('img', {
    src: './icon.svg',
    alt: ''
  }),
  el('span', {}, t('brand'))
  ),
  el('div', {
    class: 'workspace'
  }, demo ? t('demo'): state.workspace),
  el(
  'div',
  {
    class: 'header-actions'
  },
  button(
  t(busy ? 'syncing': 'sync'),
  () => attempt(() => engine.sync(), {
    working: true
  }),
  {
    disabled: busy || ! connected ? '': null
  }
  ),
  button(t('settings'), showConnection, {
    class: 'quiet'
  })
  )
  );
  const status = el(
  'div',
  {
    class: 'status',
    role: 'status',
    'aria-live': 'polite',
    'aria-atomic': 'true',
    'data-error': isError,
    'data-busy': busy
  },
  el('span', {
    class: 'status-dot'
  }),
  el('span', {
    id: 'notice-text'
  }, t(notice))
  );
  const aside = el(
  'aside',
  {},
  el('p', {
    class: 'eyebrow'
  }, t('library')),
  el('h2', {
    class: 'shelf-title'
  }, t('tagline')),
  data.lists.map(list => button(
  [el('strong', {}, list.name), el('small', {}, `${list.members.length} ${t('papers')}`)],
  () => select(list.id),
  {
    class: 'list-button' +(view.list === list.id ? ' selected': '')
  }
  )),
  el('div', {
    class: 'aside-foot'
  }, t('foreground'))
  );
  const main = el('main', {
    id: 'content'
  });
  if(paper) {
    main.append(
    button('← ' + t('back'), () => select(view.list), {
      class: 'quiet'
    }),
    el('p', {
      class: 'eyebrow'
    }, collection?.name ?? t('library')),
    el('div', {
      class: 'title-row'
    }, el('h1', {}, paper.title)),
    el('p', {
      class: 'subtitle'
    }, [...(paper.authors ??[]), paper.year].filter(Boolean).join(' · '))
    );
    const member = collection?.members.find(m => m.paper_id === paper.id);
    if(member) {
      const picker = el(
      'select',
      {
        'aria-label': t('progress'),
        onchange: event => attempt(() => engine.reading(member.id, collection.id, paper.id, event.target.value)),
        disabled: ! active(state, 'membership', member.id) ? '': null
      },
      states.map(value => el(
      'option',
      {
        value,
        selected: member.state === value ? '': null
      },
      t(value === 'pending' ? 'pendingLabel': value)
      ))
      );
      main.append(el(
      'div',
      {
        class: 'toolbar'
      },
      el('label', {}, t('progress')),
      picker,
      el('span', {
        class: 'pill'
      }, t(statusFor(state, 'reading_state', member.id)))
      ));
    }
    const tabs =['overview', 'pdf', 'notes', 'evidence', 'slides'];
    main.append(el(
    'div',
    {
      class: 'tabs',
      role: 'tablist',
      'aria-label': t('source')
    },
    tabs.map((tab, index) => button(
    t(tab),
    () => {
      view.tab = tab;
      render();
    },
    {
      role: 'tab',
      id: 'tab-' + tab,
      'aria-selected': view.tab === tab,
      'aria-controls': 'reader-panel',
      tabindex: view.tab === tab ? 0: - 1,
      onkeydown: event => {
        if(['ArrowLeft', 'ArrowRight'].includes(event.key)) {
          event.preventDefault();
          view.tab = tabs[(index +(event.key === 'ArrowRight' ? 1: tabs.length - 1)) % tabs.length];
          render();
          document.querySelector('#tab-' + view.tab)?.focus();
        }
      }
    }
    ))
    ));
    const panel = el('section', {
      id: 'reader-panel',
      role: 'tabpanel',
      'aria-labelledby': 'tab-' + view.tab
    });
    if(view.tab === 'overview') renderOverview(panel, paper);
    if(view.tab === 'notes') renderNotes(panel, paper, data);
    if(view.tab === 'pdf') renderPdf(panel, paper);
    if(view.tab === 'evidence') renderEvidence(panel, paper, data);
    if(view.tab === 'slides') renderSlides(panel, paper, data);
    main.append(panel);
  } else {
    main.append(
    el('p', {
      class: 'eyebrow'
    }, t('allLists')),
    el('div', {
      class: 'title-row'
    }, el('h1', {}, collection?.name ?? t('library'))),
    el('p', {
      class: 'subtitle'
    }, collection?.note ?? t('tagline'))
    );
    const selected = collection ? collection.members.map(m => data.papers.find(p => p.id === m.paper_id)).filter(Boolean): data.papers;
    if(! selected.length) main.append(el('div', {
      class: 'empty'
    }, el('div', {
      class: 'empty-symbol'
    }, '◇'), t('empty')));
    selected.forEach((entry, index) => {
      const owner = collection ?? data.lists.find(l => l.members.some(m => m.paper_id === entry.id));
      const member = owner?.members.find(m => m.paper_id === entry.id);
      main.append(button(
      [el('span', {
        class: 'paper-number'
      }, String(index + 1).padStart(2, '0')), el(
      'div',
      {},
      el('div', {
        class: 'paper-title'
      }, entry.title),
      el('div', {
        class: 'paper-meta'
      }, [entry.authors?.[0], entry.year].filter(Boolean).join(' · '))
      ), el('span', {
        class: 'pill'
      }, t(member?.state === 'read' ? 'read': 'pendingLabel'))],
      () => select(owner?.id ?? null, entry.id),
      {
        class: 'paper-card'
      }
      ));
    });
    main.append(el('footer', {}, demo ? t('demoHelp'): t('lastLocal')));
  }
  app.replaceChildren(header, status, el('div', {
    class: 'layout' +(! paper ? ' overview': '')
  }, aside, main));
  if(focus && serial === renderSerial) {
    const node = document.getElementById(focus.id);
    if(node) {
      node.focus({
        preventScroll: true
      });
      if(typeof node.setSelectionRange === 'function' && focus.start !== null) node.setSelectionRange(focus.start,
      focus.end);
    }
  }
}
function select(list, paper = null) {
  clearPdf();
  view.select(list, paper);
  void store.update(s => {
    s.selection = {
      list,
      paper
    };
  });
  render();
  window.scrollTo({
    top: 0,
    behavior: 'instant'
  });
}
function renderOverview(panel, paper) {
  renderChatCards(panel, paper, el, t);
  for(const item of paper.research_content ??[]) {
    if(!['resource', 'followup'].includes(item.feature)) continue;
    const data = item.data;
    const body =[data.title, data.body, data.why, data.context, data.note, data.abstract].filter(value => typeof value === 'string' && value.trim()).join('\n\n');
    panel.append(el(
    'article',
    {
      class: 'card'
    },
    el('h2', {}, t('research_' + item.feature)),
    el('div', {
      class: 'prose'
    }, body)
    ));
  }
  panel.append(el(
  'div',
  {
    class: 'card'
  },
  el('h2', {}, t('abstract')),
  el('div', {
    class: 'prose'
  }, paper.abstract ?? '')
  ));
  const sections = paper.analysis_sections ??[];
  if(! sections.length) panel.append(el('div', {
    class: 'card'
  }, el('h2', {}, t('explanation')), text('noAnalysis')));
  sections.forEach(section => panel.append(el(
  'article',
  {
    class: 'card'
  },
  el('h2', {}, t('explanation')),
  el('div', {
    class: 'prose'
  }, section.body ?? '')
  )));
}
function renderNotes(panel, paper, data) {
  const notes = data.notes.filter(n => n.paper_id === paper.id);
  for(const conflict of Object.values(state.conflicts)) {
    const op = conflict.event.operation;
    if(! conflict.resolvedBy && op.entity_type === 'note' && op.payload.paper_id === paper.id && ! notes.some(n => n.id === op.entity_id)) notes.push({
      id: op.entity_id,
      paper_id: paper.id,
      body: op.payload.body,
      editable: false,
      status: 'conflict'
    });
  }
  panel.append(el(
  'div',
  {
    class: 'toolbar'
  },
  button(
  '+ ' + t('newNote'),
  () => {
    view.note = crypto.randomUUID();
    view.drafts[view.note] = '';
    render();
    document.querySelector('#note-editor')?.focus();
  },
  {
    disabled: ! active(state, 'paper', paper.id) ? '': null,
    class: 'primary'
  }
  )
  ));
  panel.append(el(
  'div',
  {
    class: 'note-list'
  },
  notes.map((note, i) => button(
  `${i+1} · ${t(note.status)}`,
  () => {
    view.note = note.id;
    render();
  },
  {
    'aria-pressed': view.note === note.id
  }
  ))
  ));
  if(! view.note && notes.length) view.note = notes[0].id;
  if(! view.note) {
    panel.append(text('noNotes'));
    return;
  }
  const id = view.note,
  note = notes.find(n => n.id === id),
  body = own(view.drafts, id) ?? own(state.drafts, id) ?? note?.body ?? '',
  editable = active(state, 'paper', paper.id) &&(note?.editable !== false);
  if(! Object.hasOwn(view.observed, id)) put(view.observed, id, observeNote(state, id, paper.id));
  const currentObservation = observeNote(state, id, paper.id);
  const stale = view.observed[id].note_operation_id !== currentObservation.note_operation_id || view.observed[id].paper_incarnation !== currentObservation.paper_incarnation;
  if(stale) {
    panel.append(el(
    'section',
    {
      class: 'card'
    },
    text('stale_draft'),
    el('h2', {}, t('canonical')),
    el('p', {
      class: 'prose'
    }, note?.body ?? t('deleted')),
    button(
    t('saveSeparate'),
    () => attempt(
    async() => {
      const newId = crypto.randomUUID(),
      value = own(view.drafts, id) ?? body;
      await engine.saveNote(newId, paper.id, value);
      view.dirty.delete(id);
      view.note = newId;
      view.drafts[newId] = value;
    },
    {
      working: true
    }
    ),
    {
      disabled: active(state, 'paper', paper.id) ? null: ''
    }
    )
    ));
  }
  const textarea = el(
  'textarea',
  {
    id: 'note-editor',
    class: 'editor',
    'aria-label': t('noteHint'),
    placeholder: t('noteHint'),
    disabled: editable && ! switchingWorkspace ? null: '',
    oninput: event => {
      const value = event.target.value,
      owner = engine;
      view.edit(id, value);
      document.querySelector('#save-state').textContent = t('draft');
      clearTimeout(draftTimer);
      const observation = view.observed[id];
      draftTimer = setTimeout(
      () => {
        void owner.draft(id, value, observation).then(() => {
          if(owner === engine && view.note === id) document.querySelector('#save-state').textContent = t('draftStored');
        }).catch(() => {
          notice = 'storage_write_failed';
          isError = true;
          render();
        });
      },
      350
      );
    }
  },
  body
  );
  panel.append(
  textarea,
  el(
  'div',
  {
    class: 'editor-footer'
  },
  el(
  'span',
  {
    class: 'muted',
    id: 'save-state'
  },
  t(view.dirty.has(id) ? 'draft': Object.hasOwn(state.drafts, id) ? 'draftStored': note?.status ?? 'local')
  ),
  el(
  'div',
  {
    class: 'toolbar'
  },
  button(
  t('save'),
  () => attempt(
  async() => {
    const value = view.drafts[id] ?? body;
    await engine.saveNote(id, paper.id, value, {
      observed: view.observed[id]
    });
    view.saved(id, value);
    view.observed[id] = await engine.observeNote(id, paper.id);
  },
  {
    working: true
  }
  ),
  {
    class: 'primary',
    disabled: editable && ! stale ? null: ''
  }
  ),
  button(
  t('delete'),
  () => confirmDelete(id),
  {
    class: 'quiet danger',
    disabled: note?.editable && ! stale ? null: ''
  }
  )
  )
  )
  );
  if(! editable) panel.append(text('readOnly'));
  for(const [conflictId, conflict] of Object.entries(state.conflicts)) {
    if(conflict.resolvedBy || conflict.event.operation.entity_type !== 'note' || conflict.event.operation.entity_id !== id) continue;
    const local = conflict.event.operation,
    remote = state.entities[keyOf('note', id)]?.operation;
    panel.append(el(
    'section',
    {
      class: 'card'
    },
    el('h2', {}, t('conflictTitle')),
    el(
    'div',
    {
      class: 'conflict-grid'
    },
    el(
    'div',
    {},
    el('h3', {}, t('mine')),
    el('p', {
      class: 'prose'
    }, local.action === 'delete' ? t('deleted'): local.payload.body)
    ),
    el(
    'div',
    {},
    el('h3', {}, t('canonical')),
    el('p', {
      class: 'prose'
    }, remote?.action === 'put' ? remote.payload.body: t('deleted'))
    )
    ),
    el(
    'div',
    {
      class: 'toolbar'
    },
    button(
    t('keepMine'),
    () => attempt(() => engine.resolve(conflictId)),
    {
      disabled: ! active(state, 'note', id) || local.action === 'delete' ? '': null
    }
    ),
    button(t('keepRemote'), () => attempt(() => engine.resolve(conflictId, {
      discard: true
    }))),
    ! active(state, 'note', id) && local.action === 'put' ? button(t('restore'), () => attempt(() => engine.resolve(conflictId,
    {
      restore: true
    }))): null
    )
    ));
  }
}
function confirmDelete(id) {
  const observed = view.observed[id];
  const dialog = el(
  'dialog',
  {},
  el('h2', {}, t('delete')),
  text('deleteConfirm'),
  el(
  'div',
  {
    class: 'toolbar'
  },
  button(t('cancel'), () => dialog.close()),
  button(
  t('delete'),
  () => {
    dialog.close();
    void attempt(async() => {
      await engine.deleteNote(id, {
        observed
      });
      view.note = null;
    });
  },
  {
    class: 'danger'
  }
  )
  )
  );
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}
function renderPdf(panel, paper) {
  const target = documentTarget(state, paper.id),
  file = target && state.files[target.payload.sha256];
  panel.append(el(
  'div',
  {
    class: 'card'
  },
  el('h2', {}, t(file?.verified ? 'localFile': 'missing')),
  text('pdfLimit'),
  el(
  'div',
  {
    class: 'toolbar'
  },
  button(
  t('download'),
  () => attempt(() => engine.download(paper.id), {
    working: true
  }),
  {
    class: 'primary',
    disabled: ! connected || ! target || busy ? '': null
  }
  ),
  button(
  t('openPdf'),
  () => attempt(async() => {
    const owner = engine,
    id = paper.id,
    result = await owner.pdf(id);
    if(owner !== engine || view.paper !== id) return;
    clearPdf();
    pdfURL = URL.createObjectURL(new Blob([result.bytes], {
      type: 'application/pdf'
    }));
    pdfHash = result.sha256;
  }),
  {
    disabled: ! file?.verified ? '': null
  }
  ),
  busy ? button(t('downloadCancel'), () => {
    engine.disconnect();
    connected = false;
    clearPdf();
    render();
  }): null
  )
  ));
  if(pdfURL && pdfHash === target?.payload.sha256) panel.append(el(
  'object',
  {
    data: pdfURL,
    type: 'application/pdf',
    class: 'pdf-frame',
    'aria-label': t('pdf')
  },
  el('a', {
    href: pdfURL,
    target: '_blank',
    rel: 'noopener'
  }, t('openPdf'))
  ));
}
function renderEvidence(panel, paper, data) {
  const imported =(data.imported_highlights ??[]).filter(item => item.paper_id === paper.id && ! item.hidden);
  if(imported.length) panel.append(el(
  'details',
  {
    class: 'card'
  },
  el('summary', {}, t('importedSnapshot')),
  text('snapshotHelp'),
  imported.map(item => el('p', {
    class: 'prose'
  }, item.quote))
  ));
  const highlights = data.highlights.filter(h => h.paper_id === paper.id && ! h.hidden);
  if(! highlights.length) panel.append(text('noEvidence'));
  highlights.forEach(h => {
    const card = el(
    'article',
    {
      class: 'card'
    },
    el('blockquote', {}, h.quote),
    el('h3', {}, t('reason')),
    el('p', {
      class: 'prose'
    }, h.reason)
    );
    // Word offsets are not PDF geometry. Only a verified matching page may open.
    if(pdfURL && pdfHash === h.pdf_hash && h.anchor?.kind === 'word_range' && Number.isInteger(h.anchor.p0) && h.anchor.p0 >= 0) card.append(el(
    'a',
    {
      href: pdfURL + '#page=' +(h.anchor.p0 + 1),
      target: '_blank',
      rel: 'noopener'
    },
    t('viewPage')
    ));
    else card.append(text('quoteUnavailable'));
    panel.append(card);
  });
  const cites = paper.citations ??[];
  if(cites.length) panel.append(el(
  'div',
  {
    class: 'card'
  },
  el('h2', {}, t('references')),
  cites.map(c => el('div', {}, el('strong', {}, c.title ?? ''), el('p', {
    class: 'prose'
  }, c.gist ?? c.why ?? '')))
  ));
}
function showConnection() {
  const workspace = el('input', {
    value: state.workspace,
    autocomplete: 'off'
  }),
  device = el('input', {
    value: state.device,
    autocomplete: 'off'
  }),
  origin = el('input', {
    placeholder: 'https://sync.example.org',
    autocomplete: 'off'
  }),
  token = el('input', {
    type: 'password',
    autocomplete: 'off'
  });
  const dialog = el(
  'dialog',
  {},
  el('h2', {}, t('connectionTitle')),
  text('connectionHelp'),
  el(
  'div',
  {
    class: 'fields'
  },
  [[t('workspace'), workspace], [t('device'), device], [t('origin'), origin], [t('token'), token]].map(([label,
  input]) => el('label', {}, label, input))
  ),
  el(
  'div',
  {
    class: 'toolbar'
  },
  button(
  t('connect'),
  () => {
    const credential = token.value;
    token.value = '';
    dialog.close();
    void attempt(
    () => openWorkspace(workspace.value, device.value, new HttpTransport(origin.value), {
      token: credential
    }),
    {
      working: true
    }
    );
  },
  {
    class: 'primary'
  }
  ),
  button(
  t('disconnect'),
  () => {
    engine.disconnect();
    connected = false;
    clearPdf();
    token.value = '';
    dialog.close();
    render();
  }
  ),
  button(t('close'), () => dialog.close())
  ),
  el('div', {
    class: 'divider'
  }),
  text('foreground'),
  button(t('useDemo'), () => {
    dialog.close();
    void attempt(startDemo, {
      working: true
    });
  }),
  el(
  'div',
  {
    class: 'fields'
  },
  el(
  'label',
  {},
  t('language'),
  el(
  'select',
  {
    onchange: event => {
      language = event.target.value;
      t = translator(language);
      dialog.close();
      render();
    }
  },
  ['en', 'zh-TW'].map(value => el('option', {
    value,
    selected: value === language ? '': null
  }, value === 'en' ? 'English': '繁體中文'))
  )
  )
  ),
  button(
  t('export'),
  () => attempt(async() => {
    const recovery = await engine.exportLocal();
    recovery.drafts = {
      ...recovery.drafts,
      ...view.drafts
    };
    downloadJSON(recovery, 'Paperfact-unsent-work.json');
  })
  ),
  text('exportHelp'),
  el(
  'label',
  {},
  t('import'),
  el(
  'input',
  {
    type: 'file',
    accept: '.json,application/json',
    onchange: event => {
      const file = event.target.files[0];
      if(! file) return;
      void attempt(async() => {
        if(file.size > 8 * 1024 * 1024) throw new Error('projection_too_large');
        await engine.importProjection(JSON.parse(await file.text()));
        dialog.close();
      });
    }
  }
  )
  ),
  text('importHelp')
  );
  dialog.addEventListener('close', () => {
    token.value = '';
    dialog.remove();
  });
  document.body.append(dialog);
  dialog.showModal();
}
function downloadJSON(value, name) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {
    type: 'application/json'
  }));
  const link = el('a', {
    href: url,
    download: name
  });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
window.addEventListener(
'online',
() => {
  if(connected) void attempt(() => engine.sync(), {
    working: true
  });
}
);
window.addEventListener('offline', () => {
  notice = 'offline';
  render();
});
document.addEventListener(
'visibilitychange',
() => {
  if(! document.hidden && connected) void attempt(() => engine.sync(), {
    working: true
  });
}
);
window.addEventListener(
'beforeunload',
event => {
  if(view.dirty.size) {
    event.preventDefault();
    event.returnValue = '';
  }
}
);
window.addEventListener('pagehide', () => {
  engine?.disconnect();
  clearPdf();
});
if('serviceWorker' in navigator) void navigator.serviceWorker.register('./sw.mjs', {
  type: 'module'
}).catch(() => {});
try {
  await startDemo();
} catch(error) {
  app.replaceChildren(el('main', {}, el('h1', {}, 'Paperfact'), text(error.message), text('copyHint')));
}

function renderSlides(panel, paper, data) {
  const decks = data.decks.filter(deck => deck.paper_id === paper.id);
  if(!decks.length) { panel.append(el('div',{class:'card'},text('noSlides'))); return; }
  panel.append(text('readOnlySlides'));
  const serial = renderSerial, owner = engine;
  for(const manifest of decks) {
    const card = el('section',{class:'card'},el('h2',{},manifest.slot === 'guide' ? t('guideDeck') : t('notesDeck')));
    const body = el('div',{},text('loadingSlides'));
    card.append(button(t('downloadSlides'),() => attempt(() => owner.downloadArtifact(manifest.id),{working:true}),
      {disabled:!connected || busy ? '' : null}),body);
    panel.append(card);
    owner.deck(manifest.id).then(result => {
      if(serial !== renderSerial || owner !== engine || view.paper !== paper.id || view.tab !== 'slides') return;
      body.replaceChildren();
      if(result.awaiting) body.append(text('slidesPending'));
      body.append(el('h3',{},result.body.deck.title));
      const deck = result.body.deck;
      const figures = new Map(deck.figures.map(figure => {
        const asset = result.operation.payload.assets.find(item => item.id === figure.asset_id);
        const url = URL.createObjectURL(new Blob([result.blobs.get(asset.sha256)],{type:'image/png'}));
        deckURLs.push(url); return [figure.id,{...figure,url}];
      }));
      deck.slides.forEach((slide,index) => {
        const surface = el('div',{class:'slide-surface',role:'img','aria-label':`${index+1}. ${slide.title}`});
        const objects = slide.elements ?? [
          {kind:'text',text:slide.section,x:56,y:34,w:1088,h:30,size:17,color:'#2356bd'},
          {kind:'text',text:slide.title,x:56,y:82,w:1088,h:112,size:40,bold:true},
          {kind:'text',text:slide.takeaway,x:56,y:206,w:1088,h:85,size:27,color:'#2356bd'},
          {kind:'text',text:slide.bullets.map(value=>'• '+value).join('\n'),x:56,y:313,w:slide.figure?470:1088,h:285,size:slide.figure?24:27},
          ...(slide.figure?[{kind:'figure',figure:slide.figure,x:564,y:310,w:580,h:285}]:[])
        ];
        for(const object of objects) {
          const box=el('div',{class:'slide-object'});
          Object.assign(box.style,{left:`${object.x/12}%`,top:`${object.y/6.75}%`,width:`${object.w/12}%`,height:`${object.h/6.75}%`,fontSize:`${(object.size??26)/12}cqw`});
          if(object.kind==='figure') {
            const figure=figures.get(object.figure);
            box.append(el('img',{src:figure.url,alt:figure.caption??figure.label}));
          } else if(object.kind==='table') {
            box.append(el('table',{},object.rows.map((cells,row)=>el('tr',{},cells.map(cell=>el(row===0&&object.header!==false?'th':'td',{},cell))))));
          } else {
            box.style.color=object.color??'#172238'; box.style.fontWeight=object.bold?'700':'400';
            box.style.textAlign=object.align??'left'; box.textContent=object.text??'';
          }
          surface.append(box);
        }
        const notes=el('details',{},el('summary',{},t('speakerNotes')),el('p',{class:'slide-notes'},slide.speaker_notes));
        notes.append(el('h4',{},t('slideSources')),...slide.sources.map(id=> {
          const source=deck.sources.find(item=>item.id===id);
          return el('p',{},source.label,source.page ? ` - p. ${source.page}` : '',source.text ? ` - ${source.text}` : '');
        }));
        body.append(el('article',{class:'slide-page'},el('p',{class:'muted'},`${index+1} / ${deck.slides.length}`),surface,notes));
      });
    }).catch(() => {
      if(serial===renderSerial && owner===engine) body.replaceChildren(text('artifact_unavailable'));
    });
  }
}
