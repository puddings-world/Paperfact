"""Notes leave Paperfact as Markdown that survives being edited and exported again."""

import argparse
import json

import pytest

from paper_daily import cli, notes_export, store


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "papers.db")
    store.init_db()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO papers(id,venue,year,title,title_key,authors_json,source,doi) "
            "VALUES ('p1','ICLR',2024,'Sparse Attention: A Study','sparse',?,'list',"
            "'10.5555/1')",
            (json.dumps(["Ada Lovelace", "Alan Turing"]),),
        )
        conn.execute("INSERT INTO lists(id,name,created_at) VALUES ('L','Research','now')")
        conn.execute(
            "INSERT INTO list_papers(list_id,paper_id,position,added_at) VALUES ('L','p1',0,'now')"
        )
        anchor = json.dumps({"p0": 2, "o0": 0, "p1": 2, "o1": 5})
        conn.execute(
            "INSERT INTO pdf_highlights(paper_id,document_hash,anchor,quote,created_at) "
            "VALUES ('p1','h',?,'attention   is sparse','2026-10-01')",
            (anchor,),
        )
        conn.execute(
            "INSERT INTO pdf_ai_highlights(paper_id,document_hash,source_key,analysis_hash,"
            "anchor,quote,reason) VALUES ('p1','h','s','a',?,'the key result','main claim')",
            (anchor,),
        )
        conn.execute(
            "INSERT INTO pdf_ai_highlights(paper_id,document_hash,source_key,analysis_hash,"
            "anchor,quote,reason,hidden) VALUES ('p1','h','t','a',?,'dismissed','no',1)",
            (anchor,),
        )
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at,kind,page) "
            "VALUES ('p1','> attention is sparse\n\nWhy only local?','2026-10-02T10:00','note',3)"
        )
        conn.commit()
    return tmp_path


def _note(body):
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO notes(paper_id,body,created_at,kind) VALUES ('p1',?,'2026-10-03','ask')",
            (body,),
        )
        conn.commit()


def _export(out):
    with store.connect() as conn:
        return notes_export.export(conn, ["p1"], out)


def test_a_paper_exports_its_marks_and_notes(db):
    [result] = _export(db / "out")
    assert result["status"] == "written"
    assert result["path"].name == "Sparse Attention A Study.md"
    text = result["path"].read_text(encoding="utf-8")
    assert text.startswith(notes_export.BEGIN + "\n# Sparse Attention: A Study\n")
    assert "Ada Lovelace, Alan Turing" in text and "https://doi.org/10.5555/1" in text
    assert "> attention is sparse\n— 第 3 頁" in text
    assert "> the key result\n— 第 3 頁 · AI：main claim" in text
    assert "dismissed" not in text
    assert "### 手寫 · 第 3 頁 · 2026-10-02" in text and "Why only local?" in text


def test_re_export_keeps_what_the_person_wrote_around_the_block(db):
    [first] = _export(db / "out")
    path = first["path"]
    path.write_text(
        "My summary on top.\n\n" + path.read_text(encoding="utf-8") + "\n## Later thoughts\n",
        encoding="utf-8",
    )
    assert _export(db / "out")[0]["status"] == "unchanged"

    _note("> Is it sparse?\n\nYes, mostly.")
    assert _export(db / "out")[0]["status"] == "updated"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("My summary on top.\n\n" + notes_export.BEGIN)
    assert text.endswith("## Later thoughts\n")
    assert "### 問 AI · 2026-10-03" in text and text.count(notes_export.BEGIN) == 1


def test_a_file_without_markers_is_never_overwritten(db):
    [first] = _export(db / "out")
    first["path"].write_text("I rewrote all of it.\n", encoding="utf-8")
    [again] = _export(db / "out")
    assert again["status"] == "kept" and again["path"].name.endswith(".new.md")
    assert first["path"].read_text(encoding="utf-8") == "I rewrote all of it.\n"
    assert notes_export.BEGIN in again["path"].read_text(encoding="utf-8")


def test_merge_refuses_markers_in_the_wrong_order():
    broken = f"{notes_export.END}\nmine\n{notes_export.BEGIN}\n"
    assert notes_export.merge(broken, "new") is None


def test_notes_export_command_takes_a_list(db, capsys):
    args = argparse.Namespace(paper=None, list_id="L", out=str(db / "cli"))
    assert cli.cmd_notes_export(args) == 0
    assert (db / "cli" / "Sparse Attention A Study.md").exists()
    assert "written" in capsys.readouterr().out
    empty = argparse.Namespace(paper=None, list_id="none", out=str(db / "cli"))
    assert cli.cmd_notes_export(empty) == 1


def test_the_window_exports_the_open_list_to_a_chosen_folder(db, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog

    from paper_daily.desktop.main import MainWindow

    QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        win.active_list = None
        win.reload()
        assert not win.export_notes_action.isEnabled()
        win.active_list = "L"
        win.reload()
        assert win.export_notes_action.isEnabled()
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a: str(db / "picked"))
        win.export_notes_action.trigger()
        assert (db / "picked" / "Sparse Attention A Study.md").exists()
        assert "1 篇" in win.queue_page.analysis.text()
    finally:
        win.close()
        win.deleteLater()
