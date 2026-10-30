/** Read-only per-membership flag; never changes ordering or offline retention. */
export function pinBadge(member, el, t) {
  return member?.pinned === true ? el('small', {class:'pill', 'aria-label':t('pinned')},
    ' · ' + t('pinned')) : null;
}
