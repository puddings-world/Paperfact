"""Editable OpenDocument slides for Google Drive conversion and local editors."""

from __future__ import annotations

import io
import struct
import xml.etree.ElementTree as ET
import zipfile

from paper_daily.presentation_export import speaker_notes_text
from paper_daily.presentations import deck_from_dict, figure_bytes
from paper_daily.slide_layout import elements_for, text_box

MIME = "application/vnd.oasis.opendocument.presentation"
NS = {
    name: f"urn:oasis:names:tc:opendocument:xmlns:{suffix}:1.0"
    for name, suffix in (
        ("office", "office"),
        ("style", "style"),
        ("text", "text"),
        ("draw", "drawing"),
        ("fo", "xsl-fo-compatible"),
        ("svg", "svg-compatible"),
        ("presentation", "presentation"),
        ("manifest", "manifest"),
        ("table", "table"),
    )
}
NS["xlink"] = "http://www.w3.org/1999/xlink"
for prefix, namespace in NS.items():
    ET.register_namespace(prefix, namespace)


def tag(name):
    prefix, local = name.split(":", 1)
    return "{" + NS[prefix] + "}" + local


def node(parent, name, attrs=None, text=None):
    el = ET.SubElement(parent, tag(name), {tag(k): str(v) for k, v in (attrs or {}).items()})
    el.text = text
    return el


def xml(el):
    return ET.tostring(el, encoding="utf-8", xml_declaration=True)


def cm(value):
    return f"{value * 32 / 1200:.5f}cm"


def render_odp(deck, *, include_notes=True) -> bytes:
    deck_from_dict(deck.to_dict())
    root = ET.Element(tag("office:document-content"), {tag("office:version"): "1.2"})
    auto = node(root, "office:automatic-styles")
    bold = node(auto, "style:style", {"style:name": "bold", "style:family": "text"})
    node(bold, "style:text-properties", {"fo:font-weight": "bold"})
    style = node(auto, "style:style", {"style:name": "page", "style:family": "drawing-page"})
    node(
        style, "style:drawing-page-properties", {"draw:fill": "solid", "draw:fill-color": "#ffffff"}
    )
    presentation = node(node(root, "office:body"), "office:presentation")
    images = {}
    for si, slide in enumerate(deck.slides):
        page = node(
            presentation,
            "draw:page",
            {
                "draw:name": f"Slide {si + 1}",
                "draw:style-name": "page",
                "draw:master-page-name": "Default",
            },
        )
        objects = elements_for(slide) + [
            text_box(
                f"Paperfact  {si + 1}/{len(deck.slides)}  " + " · ".join(slide.sources),
                56,
                628,
                1088,
                26,
                14,
                "#68788f",
            )
        ]
        for oi, obj in enumerate(objects):
            name = f"s{si}o{oi}"
            st = node(auto, "style:style", {"style:name": name, "style:family": "graphic"})
            node(
                st,
                "style:graphic-properties",
                {
                    "draw:stroke": "none",
                    "draw:fill": "none",
                    "fo:padding": "0cm",
                    "draw:auto-grow-height": "false",
                    "draw:textarea-vertical-align": "top",
                },
            )
            x, y, w, h = (obj[k] for k in ("x", "y", "w", "h"))
            if obj["kind"] == "figure":
                data = figure_bytes(deck, obj["figure"])
                iw, ih = struct.unpack(">II", data[16:24])
                scale = min(w / iw, h / ih)
                x, y = x + (w - iw * scale) / 2, y + (h - ih * scale) / 2
                w, h = iw * scale, ih * scale
                filename = f"Pictures/{name}.png"
                images[filename] = data
            frame = node(
                page,
                "draw:frame",
                {
                    "draw:name": name,
                    "draw:style-name": name,
                    "svg:x": cm(x),
                    "svg:y": cm(y),
                    "svg:width": cm(w),
                    "svg:height": cm(h),
                },
            )
            if obj["kind"] == "figure":
                node(
                    frame,
                    "draw:image",
                    {
                        "xlink:href": filename,
                        "xlink:type": "simple",
                        "xlink:show": "embed",
                        "xlink:actuate": "onLoad",
                    },
                )
            elif obj["kind"] == "table":
                cellstyle = node(
                    auto, "style:style", {"style:name": name + "c", "style:family": "table-cell"}
                )
                node(
                    cellstyle,
                    "style:table-cell-properties",
                    {"fo:border": "0.5pt solid #c9d2e0", "fo:padding": "0.08cm"},
                )
                textstyle = node(
                    auto, "style:style", {"style:name": name + "p", "style:family": "paragraph"}
                )
                node(
                    textstyle,
                    "style:text-properties",
                    {
                        "fo:font-family": "Noto Sans TC",
                        "fo:font-size": f"{obj['size'] * 32 / 1200 * 72 / 2.54:.3f}pt",
                    },
                )
                table = node(frame, "table:table")
                node(
                    table,
                    "table:table-column",
                    {"table:number-columns-repeated": len(obj["rows"][0])},
                )
                for ri, row in enumerate(obj["rows"]):
                    tr = node(table, "table:table-row")
                    for cell in row:
                        td = node(tr, "table:table-cell", {"table:style-name": name + "c"})
                        p = node(td, "text:p", {"text:style-name": name + "p"})
                        if ri == 0 and obj["header"]:
                            node(p, "text:span", {"text:style-name": "bold"}, cell)
                        else:
                            p.text = cell
            else:
                textstyle = node(
                    auto, "style:style", {"style:name": name + "p", "style:family": "paragraph"}
                )
                node(
                    textstyle,
                    "style:paragraph-properties",
                    {
                        "fo:margin-top": "0cm",
                        "fo:margin-bottom": "0cm",
                        "fo:text-align": obj["align"],
                    },
                )
                node(
                    textstyle,
                    "style:text-properties",
                    {
                        "fo:font-family": "Noto Sans TC",
                        "fo:font-size": f"{obj['size'] * 32 / 1200 * 72 / 2.54:.3f}pt",
                        "fo:color": obj["color"],
                        "fo:font-weight": "bold" if obj["bold"] else "normal",
                    },
                )
                box = node(frame, "draw:text-box")
                for line in obj["text"].split("\n"):
                    node(box, "text:p", {"text:style-name": name + "p"}, line)
        if include_notes:
            notes = node(page, "presentation:notes")
            frame = node(
                notes,
                "draw:frame",
                {
                    "presentation:class": "notes",
                    "svg:x": "1cm",
                    "svg:y": "1cm",
                    "svg:width": "25cm",
                    "svg:height": "15cm",
                },
            )
            box = node(frame, "draw:text-box")
            for line in speaker_notes_text(deck, slide).split("\n"):
                node(box, "text:p", text=line)
    styles = ET.Element(tag("office:document-styles"), {tag("office:version"): "1.2"})
    node(styles, "office:styles")
    layout = node(
        node(styles, "office:automatic-styles"), "style:page-layout", {"style:name": "wide"}
    )
    node(
        layout,
        "style:page-layout-properties",
        {
            "fo:page-width": "32cm",
            "fo:page-height": "18cm",
            "style:print-orientation": "landscape",
            "fo:margin": "0cm",
        },
    )
    node(
        node(styles, "office:master-styles"),
        "style:master-page",
        {"style:name": "Default", "style:page-layout-name": "wide"},
    )
    manifest = ET.Element(tag("manifest:manifest"), {tag("manifest:version"): "1.2"})
    for filename, mime in [
        ("/", MIME),
        ("content.xml", "text/xml"),
        ("styles.xml", "text/xml"),
        *((f, "image/png") for f in images),
    ]:
        node(
            manifest,
            "manifest:file-entry",
            {"manifest:full-path": filename, "manifest:media-type": mime},
        )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", MIME, compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", xml(root))
        z.writestr("styles.xml", xml(styles))
        z.writestr("META-INF/manifest.xml", xml(manifest))
        for filename, data in images.items():
            z.writestr(filename, data)
    return out.getvalue()


def export_odp(deck, dest, *, include_notes=True):
    dest.write_bytes(render_odp(deck, include_notes=include_notes))
    return dest
