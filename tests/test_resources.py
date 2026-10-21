"""Finding a paper's code and data from what it prints, and from what links to it."""

from __future__ import annotations

import sqlite3

from paper_daily import resources, store


def test_a_url_broken_inside_its_host_or_after_a_slash_is_joined():
    text = (
        "usage instructions in the GitHub repository of the paper (https://github.\n"
        "com/Negin-Ghamsarian/Cataract-1K).\n"
        "Code: https://github.com/sukjuoh/\nSurgical-Mamba\n"
    )
    urls = [link["url"] for link in resources.links_in(text)]
    assert urls == [
        "https://github.com/Negin-Ghamsarian/Cataract-1K",
        "https://github.com/sukjuoh/Surgical-Mamba",
    ]


def test_a_section_number_after_a_url_is_not_part_of_it():
    text = "The project website is available at:\nhttps://sl2005.github.io/x-seg/\n1. Introduction"
    assert resources.links_in(text)[0]["url"] == "https://sl2005.github.io/x-seg/"


def test_a_break_where_the_url_could_end_offers_both_readings():
    text = "GitHub repository (https://github.com/MJAHMADEE/C\nataract-LMM).\n"
    link = resources.links_in(text)[0]
    assert link["url"] == "https://github.com/MJAHMADEE/C"
    assert link["alt"] == "https://github.com/MJAHMADEE/Cataract-LMM"


def test_our_code_is_own_and_a_tool_used_is_not():
    text = (
        "Code is available at https://github.com/MECLabTUDA/SASVi.\n"
        "We use the evaluation harness of [12] (https://github.com/EleutherAI/lm-eval)."
    )
    own = {link["url"]: link["own"] for link in resources.links_in(text)}
    assert own == {
        "https://github.com/MECLabTUDA/SASVi": True,
        "https://github.com/EleutherAI/lm-eval": False,
    }


def test_links_are_sorted_into_kinds():
    assert resources.classify("github.com/felixholm/CAT-SG/tree/main") == (
        "code",
        "https://github.com/felixholm/CAT-SG",
    )
    assert resources.classify("https://huggingface.co/datasets/mjahmadi/Cataract-LMM")[0] == "data"
    assert resources.classify("https://huggingface.co/SsharvienKumar/SASVi")[0] == "model"
    assert resources.classify("https://zenodo.org/records/123")[0] == "data"
    assert resources.classify("https://mjahmadee.github.io/Cataract-LMM/")[0] == "page"
    assert resources.classify("https://github.com/sukjuoh") is None
    assert resources.classify("https://huggingface.co/papers/2502.09653") is None


def test_short_names_and_author_accounts():
    assert resources.short_name("CataractSAM-2: A Domain-Adapted Model") == "CataractSAM-2"
    assert resources.short_name("SASVi - Segment Any Surgical Video") == "SASVi"
    assert resources.short_name("Deep learning for multi-class segmentation") is None
    assert resources.by_an_author("SsharvienKumar", ["Ssharvien Kumar R. Sivakumar"])
    assert resources.by_an_author("mjahmadi", ["Mohammad Javad Ahmadi"])
    assert not resources.by_an_author("blinksh", ["Marvin Li", "Sitan Chen"])


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(store.SCHEMA)
    store._migrate(conn)
    store.upsert_papers(
        conn,
        [
            {
                "id": "ref:brain",
                "title": "BRAIN: Bi-directional Motion Reasoning",
                "venue": "MICCAI",
                "year": 2026,
                "source": "test",
                "authors_json": '["Chuanzhen Xu"]',
            }
        ],
    )
    return conn


def test_code_promised_but_not_pushed_is_said_so(monkeypatch, tmp_path):
    monkeypatch.setattr(resources, "TEXT_DIR", tmp_path)
    monkeypatch.setattr(resources, "PDF_DIR", tmp_path)
    (tmp_path / "ref_brain.txt").write_text(
        "Our code is available at https://github.com/ChuanzhenXu/BRAIN.", encoding="utf-8"
    )
    monkeypatch.setattr(resources, "_repo", lambda url: {"url": url, "alive": False})
    monkeypatch.setattr(resources, "_search", lambda *a: [])
    conn = _db()

    assert resources.needs_check(conn, "ref:brain")
    assert resources.find(conn, "ref:brain") == 1
    found = resources.of(conn, "ref:brain")
    assert found[0]["own"] == 1 and found[0]["alive"] == 0
    assert resources.label(found[0]) == "程式碼 ChuanzhenXu/BRAIN(repo 尚未公開)"
    assert not resources.needs_check(conn, "ref:brain")


def test_a_paper_checked_before_its_text_arrived_is_checked_again(monkeypatch, tmp_path):
    monkeypatch.setattr(resources, "TEXT_DIR", tmp_path)
    monkeypatch.setattr(resources, "PDF_DIR", tmp_path)
    monkeypatch.setattr(resources, "_search", lambda *a: [])
    conn = _db()
    resources.find(conn, "ref:brain")
    assert not resources.needs_check(conn, "ref:brain")
    (tmp_path / "ref_brain.txt").write_text("text", encoding="utf-8")
    assert resources.needs_check(conn, "ref:brain")
