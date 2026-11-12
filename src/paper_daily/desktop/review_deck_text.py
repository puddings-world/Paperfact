"""Readable, bounded plain-text deck summaries for retained-work comparison."""

MAX_PREVIEW = 200_000


def deck_text(value, *, chinese=False):
    if value is None:
        return "不存在或無法取得" if chinese else "Absent or unavailable"
    if not isinstance(value, dict) or not isinstance(value.get("slides"), list):
        return ("按「核對保留簡報」讀取投影片、講稿與來源。" if chinese
                else "Choose Verify retained slides to read the slides, notes and sources.")
    lines = [value.get("title", ""), value.get("paper_title", "")]
    sources = {row["id"]: row for row in value.get("sources", [])}
    for number, slide in enumerate(value["slides"], 1):
        lines += ["", str(number) + ". " + slide.get("title", "")]
        for key in ("section", "takeaway"):
            if slide.get(key):
                lines.append(slide[key])
        lines.extend("• " + text for text in slide.get("bullets", []))
        if slide.get("speaker_notes"):
            lines += ["講稿：" if chinese else "Speaker notes:", slide["speaker_notes"]]
        labels = [sources[key].get("label", key) for key in slide.get("sources", [])
                  if key in sources]
        if labels:
            lines.append(("來源：" if chinese else "Sources: ") + "; ".join(labels))
        if sum(len(line) + 1 for line in lines) > MAX_PREVIEW:
            text = "\n".join(lines)[:MAX_PREVIEW]
            notice = ("預覽已縮短，儲存的完整簡報不受影響。" if chinese else
                      "Preview shortened; the complete saved deck is unchanged.")
            return text + "\n\n" + notice
    return "\n".join(lines)


def evidence_text(data, *, chinese=False):
    """Readable metadata only; complete retained science/bytes remain in owned storage."""
    evidence = data.get("retained_evidence") or {}
    retained = data.get("retained") or {}
    images, originals = data.get("image_manifest", []), data.get("original_manifest", [])
    lines = [
        (f"素材：{len(images)} 張；保留原文：{len(originals)} 份" if chinese else
         f"Images: {len(images)}; retained originals: {len(originals)}"),
        "", "來源摘錄" if chinese else "Source passages",
    ]
    sources = evidence.get("sources", retained.get("sources", []))
    for row in sources:
        lines += [row.get("label", row["id"])]
        if row.get("text"):
            lines.append(row["text"])
        if row.get("page"):
            lines.append(("頁碼：" if chinese else "Page: ") + str(row["page"]))
        if row.get("document_hash"):
            lines.append(("原文版本：" if chinese else "Original version: ")
                         + row["document_hash"][:12])
        lines.append("")
    figures = {row["id"]: row for row in retained.get("figures", [])}
    figures.update({row["id"]: row for row in evidence.get("figures", [])})
    lines += ["素材與圖說" if chinese else "Images and captions"]
    for item in images:
        row = figures.get(item["id"], {"id": item["id"]})
        lines.append(row.get("label", row["id"]))
        if row.get("caption"):
            lines.append(row["caption"])
        lines.append(("頁碼：" if chinese else "Page: ") + str(row.get("page") or "—"))
        if row.get("document_hash"):
            lines.append(("原文版本：" if chinese else "Original version: ")
                         + row["document_hash"][:12])
        lines.append("")
    lines.append("保留的原文版本" if chinese else "Retained original versions")
    for item in originals:
        lines.append(item["sha256"][:12] + f" · {item['size'] / 1024**2:.2f} MB")
    text = "\n".join(lines)
    if len(text) > MAX_PREVIEW:
        notice = ("預覽已縮短；完整素材與原文仍保留於研究資料中。" if chinese else
                  "Preview shortened; complete images and originals remain retained.")
        text = text[:MAX_PREVIEW] + "\n\n" + notice
    return text
