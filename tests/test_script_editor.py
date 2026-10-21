"""The speaker script reads as a page and says how long it takes to say."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from paper_daily.desktop.script_editor import (  # noqa: E402
    ScriptEditor,
    length_label,
    speaking_seconds,
)


def test_speaking_time_counts_chinese_characters_and_english_words():
    assert speaking_seconds("字" * 250) == 60
    assert speaking_seconds(" ".join(["word"] * 150)) == 60
    assert speaking_seconds("今天介紹 Cataract-1K 這份 dataset") == round(
        6 * 60 / 250 + 2 * 60 / 150
    )


def test_the_length_line_names_count_time_and_per_slide_budget():
    assert length_label("字" * 300, budget=60) == "300 字 · 約 1 分 12 秒 · 每頁目標 1 分 0 秒"
    assert length_label("") == "0 字 · 約 0 秒"


def test_a_loaded_script_comes_back_unchanged_and_spacing_is_not_an_undo_step():
    QApplication.instance() or QApplication([])
    editor = ScriptEditor()
    editor.setPlainText("第一段\n第二段")
    editor.undo()
    assert editor.toPlainText() == "第一段\n第二段"
    assert editor.document().begin().blockFormat().lineHeight() > 100
