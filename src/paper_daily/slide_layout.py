"""Portable, editable slide geometry shared by desktop and exporters."""

from __future__ import annotations

import math
import re
from copy import deepcopy

WIDTH, HEIGHT = 1200, 675
MAX_TABLE_ROWS, MAX_TABLE_COLS, MAX_CELL = 30, 12, 200


def validate_rows(value) -> list[list[str]]:
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= MAX_TABLE_ROWS
        or any(not isinstance(r, list) for r in value)
    ):
        raise ValueError("A table needs 1-30 rows")
    width = len(value[0])
    if not 1 <= width <= MAX_TABLE_COLS or any(len(r) != width for r in value):
        raise ValueError("A table needs 1-12 columns, the same in every row")
    for row in value:
        for cell in row:
            if not isinstance(cell, str) or len(cell) > MAX_CELL:
                raise ValueError("Table cells are text of at most 200 characters")
    return [list(r) for r in value]


def validate_elements(value, figure_ids: set[str]) -> list[dict] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 60:
        raise ValueError("A canvas supports at most 60 objects")
    result = []
    for raw in value:
        if not isinstance(raw, dict) or raw.get("kind") not in ("text", "figure", "table"):
            raise ValueError("Invalid canvas object")
        obj = {"kind": raw["kind"]}
        for key, upper in (("x", WIDTH), ("y", HEIGHT), ("w", WIDTH), ("h", HEIGHT)):
            n = raw.get(key)
            if type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= upper:
                raise ValueError("Invalid canvas geometry")
            obj[key] = n
        if obj["w"] < 20 or obj["h"] < 12:
            raise ValueError("Canvas objects are too small")
        if obj["x"] + obj["w"] > WIDTH + 1 or obj["y"] + obj["h"] > HEIGHT + 1:
            raise ValueError("Canvas object extends beyond the slide")
        if obj["kind"] == "figure":
            if raw.get("figure") not in figure_ids:
                raise ValueError("Unknown canvas figure")
            obj["figure"] = raw["figure"]
        elif obj["kind"] == "table":
            size = raw.get("size", 18)
            if type(size) not in (int, float) or not math.isfinite(size) or not 10 <= size <= 96:
                raise ValueError("Invalid canvas font size")
            obj.update(
                rows=validate_rows(raw.get("rows")), size=size, header=bool(raw.get("header", True))
            )
        else:
            text = raw.get("text", "")
            size = raw.get("size", 26)
            if not isinstance(text, str) or len(text) > 12000:
                raise ValueError("Canvas text is too long")
            if type(size) not in (int, float) or not math.isfinite(size) or not 10 <= size <= 96:
                raise ValueError("Invalid canvas font size")
            color = raw.get("color", "#172238")
            if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                raise ValueError("Invalid canvas text color")
            align = raw.get("align", "left")
            if align not in ("left", "center", "right"):
                raise ValueError("Invalid canvas text alignment")
            obj.update(text=text, size=size, color=color, bold=bool(raw.get("bold")), align=align)
        if raw.get("role") in ("title", "section", "takeaway", "bullets"):
            obj["role"] = raw["role"]
        result.append(obj)
    return result


def text_box(text, x, y, w, h, size=26, color="#172238", bold=False):
    return dict(
        kind="text", text=text, x=x, y=y, w=w, h=h, size=size, color=color, bold=bold, align="left"
    )


def table_box(rows, x, y, w, h, size=18):
    return dict(kind="table", rows=validate_rows(rows), x=x, y=y, w=w, h=h, size=size, header=True)


def table_markdown(rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(c.replace("|", "\\|") for c in rows[0]) + " |"]
    lines.append("|" + "---|" * len(rows[0]))
    lines += ["| " + " | ".join(c.replace("|", "\\|") for c in r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def elements_for(slide) -> list[dict]:
    if slide.elements is not None:
        return deepcopy(slide.elements)
    objects = [
        text_box(slide.section.upper(), 56, 34, 1088, 30, 17, "#2356bd", True),
        text_box(slide.title, 56, 82, 1088, 112, 40, bold=True),
        text_box(slide.takeaway, 56, 206, 1088, 85, 27, "#2356bd"),
        text_box(
            "\n".join("• " + b for b in slide.bullets),
            56,
            313,
            470 if slide.figure else 1088,
            285,
            24 if slide.figure else 27,
        ),
    ]
    for obj, role in zip(objects, ("section", "title", "takeaway", "bullets"), strict=True):
        obj["role"] = role
    if slide.figure:
        objects.append(dict(kind="figure", figure=slide.figure, x=564, y=310, w=580, h=285))
    return objects


def used_figures(deck) -> set[str]:
    return {
        obj["figure"] for s in deck.slides for obj in elements_for(s) if obj["kind"] == "figure"
    }
