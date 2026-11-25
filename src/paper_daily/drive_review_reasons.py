"""Why a list is waiting, in the reader's language and in a local sync.log.

The sync code raises short English reasons at well over a hundred sites. They were
shown nowhere and written nowhere, so a device that received nothing gave no clue.
"""

from datetime import datetime
from pathlib import Path
from threading import Lock

LOG_NAME = "sync.log"
LOG_LIMIT = 512 * 1024

# First match wins; the more specific wording comes first.
_RULES = (
    (("sign in",), "需要重新登入 Google 帳號。"),
    (("enrolled workspace",), "這個工作區已用「工作區同步」連線，請改用那邊同步。"),
    (("budget", "exceed", "supported size", "page size"),
     "內容超過目前 Drive 同步的容量上限。"),
    (("retry", "sync again", "changed during", "changed before", "changed while",
      "workspace changed", "refresh", "selection", "directory"),
     "同步途中資料有變動，下次檢查會自動重試。"),
    (("pdf", "original"), "PDF 原檔與 Drive 上的不同或無法讀取，已保留本機檔案。"),
    (("note",), "筆記在兩台裝置都改過，已保留兩份待核對。"),
    (("conversation", "message", "answers"), "問答紀錄在兩台裝置不同，待核對。"),
    (("explanation",), "講解版本在兩台裝置不同，待核對。"),
    (("reading",), "閱讀進度在兩台裝置不同，已保留兩端狀態。"),
    (("removed locally", "removal", "retire", "added again", "re-added"),
     "本機移除或重新加入過的項目與 Drive 不一致，請確認要保留還是移除。"),
    (("possible existing", "identity", "binding"),
     "這篇論文在本機對應到不只一筆資料，無法自動合併。"),
    (("membership", "bibliography", "paper", "entry"),
     "清單裡的論文與 Drive 上的記錄不一致。"),
    (("list",), "清單名稱或說明在兩台裝置不同，待核對。"),
    (("locked", "busy"), "資料庫正在使用中，下次檢查會自動重試。"),
)

_lock = Lock()
_written: dict[tuple[str, str], str] = {}


def explain(reason: str) -> str:
    """One Chinese sentence per distinct cause, joined the way the reasons were."""
    parts = []
    for part in filter(None, (piece.strip() for piece in (reason or "").split(" · "))):
        lowered = part.casefold()
        text = next(
            (text for keys, text in _RULES if any(key in lowered for key in keys)),
            "需要核對。",
        )
        if text not in parts:
            parts.append(text)
    return "".join(parts)


def record(directory, entries: dict[str, str], *, names=None) -> None:
    """Append what changed since the last write: a standing reason repeats every poll."""
    path = Path(directory) / LOG_NAME
    lines = []
    with _lock:
        for key, reason in entries.items():
            if _written.get((str(path), key)) == reason:
                continue
            _written[(str(path), key)] = reason
            label = (names or {}).get(key, key)
            lines.append(
                f"{datetime.now().isoformat(timespec='seconds')}\t{key}\t{label}\t"
                f"{reason or 'ok'}\n"
            )
        if not lines:
            return
        try:
            if path.exists() and path.stat().st_size > LOG_LIMIT:
                path.write_bytes(b"")
            with path.open("a", encoding="utf-8", newline="") as stream:
                stream.writelines(lines)
        except OSError:
            # A log that cannot be written must not become a reason sync fails.
            for key in entries:
                _written.pop((str(path), key), None)
