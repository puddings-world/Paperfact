"""Stage bundle files and restore them if file installation or DB commit fails."""

import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path


class StagedFiles:
    def __init__(self, root, archive, relatives):
        self.root = Path(root).resolve()
        self.work = Path(tempfile.mkdtemp(prefix=".bundle-import-", dir=self.root)).resolve()
        self.entries = []
        self.changed = []
        try:
            for index, relative in enumerate(relatives):
                target = (self.root / relative).resolve()
                if not target.is_relative_to(self.root) or target == self.root:
                    raise ValueError("Bundle file escapes the workspace")
                staged = self.work / f"{index}.new"
                with (
                    archive.open("files/" + relative.as_posix()) as source,
                    staged.open("wb") as out,
                ):
                    shutil.copyfileobj(source, out)
                self.entries.append((target, staged, self.work / f"{index}.old"))
        except BaseException:
            self.cleanup()
            raise

    def install(self):
        for target, staged, backup in self.entries:
            if target.resolve() != target or not target.is_relative_to(self.root):
                raise ValueError("Bundle destination changed while importing")
            target.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            if existed and not target.is_file():
                raise OSError("A bundle destination is not a file")
            if existed:
                os.replace(target, backup)
            self.changed.append((target, backup, existed))
            os.replace(staged, target)
        return len(self.entries)

    def rollback(self):
        for target, backup, existed in reversed(self.changed):
            if existed:
                os.replace(backup, target)
            else:
                target.unlink(missing_ok=True)

    def cleanup(self):
        # Only remove the absolute temporary directory created for this transaction.
        if (
            self.work.parent != self.root
            or not self.work.name.startswith(".bundle-import-")
            or self.work.resolve() != self.work
        ):
            raise ValueError("Unexpected bundle staging directory")
        shutil.rmtree(self.work)


@contextmanager
def stage(root, archive, relatives):
    transaction = StagedFiles(root, archive, relatives)
    try:
        yield transaction
    except BaseException:
        try:
            transaction.rollback()
        except OSError as error:
            # Do not delete recovery files when restoring a locked file fails.
            raise OSError(
                f"匯入未完成，原檔還原失敗；請保留修復資料夾：{transaction.work}"
            ) from error
        transaction.cleanup()
        raise
    else:
        try:
            transaction.cleanup()
        except OSError:
            logging.getLogger(__name__).warning("Committed bundle staging cleanup is pending")
