"""The citation map drawn in the 引用 tab, next to the itemised lists.

A circle per paper, its area its citation count, its colour the verdict the lists
give it; one or two words inside. Pointing at a circle opens the same card the lists
show -- title, venue, citations, what it is to this paper, the sentence that cites
it -- and lights its own edges while fading the rest; clicking keeps the card open.
Edges to the paper at the centre are drawn faint because every neighbour has one;
edges between neighbours are drawn in the accent colour because they are the reason
to look at a map at all.
"""

from __future__ import annotations

import html
import math
from collections.abc import Callable

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QLabel,
    QMenu,
    QStyleOptionGraphicsItem,
    QWidget,
)

from paper_daily.citegraph import Graph, Node, layout

# Fill and outline per verdict, as palette keys; the lists use the same colours.
VERDICT_STYLE = {
    "必讀": ("awardSoft", "award"),
    "值得": ("accentSoft", "accent"),
    "參考": ("border", "muted"),
    "略過": ("sunk", "faint"),
}
SIDE_NAME = {"ref": "承先 · 參考文獻", "later": "啟後 · 後續研究"}
CARD_W = 420


def _colour(hex_: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_)
    c.setAlphaF(alpha)
    return c


def card_html(n: Node, pal: dict[str, str], linked: list[str]) -> str:
    """What a list card says about a paper, for the map's hover card."""
    esc = html.escape
    meta = [str(x) for x in (n.year, n.venue) if x]
    if n.citations:
        meta.append(f"{n.citations:,} cites")
    if n.influential:
        meta.append("★ influential")
    side = {"ref": "承先 · 這篇引用了它", "later": "啟後 · 它引用了這篇"}.get(n.side, "本文")
    head = f"<span style='color:{pal['faint']};font-size:11px;'>{side}</span><br>"
    if n.verdict:
        fg, bg = {
            "必讀": ("award", "awardSoft"),
            "值得": ("accent", "accentSoft"),
        }.get(n.verdict, ("muted", "sunk"))
        head += (
            f"<span style='background:{pal[bg]};color:{pal[fg]};font-weight:600;'>"
            f"&nbsp;{esc(n.verdict)}&nbsp;</span> "
        )
    parts = [f"{head}<b style='font-size:13.5px;'>{esc(n.title)}</b>"]
    if meta:
        parts.append(
            f"<span style='color:{pal['muted']};font-size:11.5px;'>{esc(' · '.join(meta))}</span>"
        )
    for label, value in (
        ("與原文的關係", n.relation),
        ("這篇在做什麼", n.gist),
        ("判斷", n.why),
    ):
        if value:
            parts.append(f"<span style='color:{pal['accent']};'>{label}</span>　{esc(value)}")
    if n.quote:
        who = "原文引用它的句子" if n.side == "ref" else "它引用原文的句子"
        quote = n.quote if len(n.quote) <= 260 else n.quote[:259] + "…"
        parts.append(f"<span style='color:{pal['faint']};'>{who}:「{esc(quote)}」</span>")
    if linked:
        names = "、".join(linked[:8]) + (f" 等 {len(linked)} 篇" if len(linked) > 8 else "")
        parts.append(f"<span style='color:{pal['muted']};'>和圖上的 {esc(names)} 互相引用</span>")
    if n.side != "center":
        if n.here:
            where = "已在資料庫" + (",讀過" if n.here.get("read") else "") + " · 雙擊開啟"
        else:
            where = "不在資料庫 · 右鍵加入清單"
        parts.append(f"<span style='color:{pal['faint']};font-size:11px;'>{where}</span>")
    return "<div style='line-height:140%;'>" + "<br>".join(parts) + "</div>"


class Dot(QGraphicsItem):
    def __init__(self, node: Node, pal: dict[str, str], map_: CiteMap) -> None:
        super().__init__()
        self.node = node
        self.pal = pal
        self.map = map_
        self.r = node.radius
        self.lit = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(2)
        self.font = QFont()
        self.font.setBold(True)
        # A label too long for a small circle is set beneath it rather than shrunk
        # past reading; the layout leaves room for it.
        self.inside = not node.label_below
        self.font.setPixelSize(int(node.label_px if self.inside else 10))

    def boundingRect(self) -> QRectF:
        r = self.r + 3
        below = 0 if self.inside else 16
        return QRectF(-max(r, 40), -r, 2 * max(r, 40), 2 * r + below)

    def shape(self) -> QPainterPath:
        # Only the circle (and a label beneath it) answers the pointer: the painted
        # area is wider, and would steal the hover from the paper next to it.
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), self.r + 2, self.r + 2)
        if not self.inside:
            path.addRect(QRectF(-22, self.r, 44, 15))
        return path

    def paint(self, p: QPainter, _o: QStyleOptionGraphicsItem, _w: QWidget | None = None) -> None:
        pal, n = self.pal, self.node
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if n.side == "center":
            fill, line, text = pal["accent"], pal["accent"], "#ffffff"
        else:
            fk, lk = VERDICT_STYLE.get(n.verdict or "", ("surface", "firm"))
            fill, line, text = pal[fk], pal[lk], pal["ink"]
        width = 2.6 if self.lit else (1.8 if n.here else 1.0)
        pen = QPen(_colour(pal["ink"] if self.lit else line), width)
        if not n.here and n.side != "center":
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(QBrush(_colour(fill)))
        p.drawEllipse(QPointF(0, 0), self.r, self.r)
        if n.here and n.here.get("read"):
            p.setPen(QPen(_colour(pal["done"]), 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0, 0), self.r + 3, self.r + 3)
        p.setFont(self.font)
        if self.inside:
            p.setPen(_colour(text))
            p.drawText(
                QRectF(-self.r, -self.r, 2 * self.r, 2 * self.r),
                Qt.AlignmentFlag.AlignCenter,
                n.label,
            )
        else:
            p.setPen(_colour(pal["muted"]))
            p.drawText(QRectF(-40, self.r + 1, 80, 14), Qt.AlignmentFlag.AlignCenter, n.label)

    def hoverEnterEvent(self, event) -> None:
        self.map.point_at(self)

    def hoverLeaveEvent(self, event) -> None:
        self.map.point_at(None)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.map.pin(self)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if self.node.here and self.node.side != "center":
            self.map.on_open(self.node.here["id"])

    def contextMenuEvent(self, event) -> None:
        n = self.node
        if n.side == "center":
            return
        menu = QMenu()
        if n.here:
            menu.addAction("開啟", lambda: self.map.on_open(n.here["id"]))
        else:
            menu.addAction("加入清單", lambda: self.map.on_add(n))
        menu.exec(event.screenPos())


class Edge(QGraphicsPathItem):
    def __init__(self, a: Dot, b: Dot, pal: dict[str, str], central: bool) -> None:
        super().__init__()
        self.a, self.b = a, b
        self.pal = pal
        self.central = central
        self.setZValue(0 if central else 1)
        self.setAcceptHoverEvents(False)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setPath(self._path())
        self.style("rest")

    def _path(self) -> QPainterPath:
        (ax, ay), (bx, by) = self.a.pos().toTuple(), self.b.pos().toTuple()
        path = QPainterPath()
        angle = math.atan2(by - ay, bx - ax)
        start = QPointF(ax + self.a.r * math.cos(angle), ay + self.a.r * math.sin(angle))
        if abs(bx - ax) < 1:
            # Two papers in one column: bow out sideways rather than run through the
            # circles between them.
            bend = 40 + abs(by - ay) * 0.25
            end = QPointF(bx + self.b.r, by)
            start = QPointF(ax + self.a.r, ay)
            path.moveTo(start)
            path.cubicTo(start + QPointF(bend, 0), end + QPointF(bend, 0), end)
            self.tip, self.tip_angle = end, math.pi
            return path
        dx = (bx - ax) * 0.45
        end_angle = math.atan2(by - ay, bx - ax)
        end = QPointF(bx - self.b.r * math.cos(end_angle), by - self.b.r * math.sin(end_angle))
        path.moveTo(start)
        path.cubicTo(start + QPointF(dx, 0), end - QPointF(dx, 0), end)
        self.tip = end
        self.tip_angle = math.atan2(
            end.y() - (end - QPointF(dx, 0)).y(), end.x() - (end - QPointF(dx, 0)).x()
        )
        return path

    def style(self, state: str) -> None:
        pal = self.pal
        if state == "lit":
            colour, alpha, width = pal["accent"] if self.central else pal["award"], 1.0, 2.0
        elif state == "dim":
            colour, alpha, width = pal["firm"], 0.12, 1.0
        elif self.central:
            colour, alpha, width = pal["firm"], 0.5, 1.0
        else:
            # A well-studied field has hundreds of these; at full strength they bury
            # the circles, and pointing at a paper is what brings its own forward.
            colour, alpha, width = pal["accent"], 0.28, 1.1
        self.colour = _colour(colour, alpha)
        self.setPen(QPen(self.colour, width))
        self.update()

    def paint(self, p: QPainter, option, widget=None) -> None:
        super().paint(p, option, widget)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = 7.0
        a = self.tip_angle
        left = self.tip - QPointF(size * math.cos(a - 0.4), size * math.sin(a - 0.4))
        right = self.tip - QPointF(size * math.cos(a + 0.4), size * math.sin(a + 0.4))
        head = QPainterPath(self.tip)
        head.lineTo(left)
        head.lineTo(right)
        head.closeSubpath()
        p.fillPath(head, self.colour)

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(-8, -8, 8, 8)


class CiteMap(QGraphicsView):
    """Pan by dragging, zoom with the wheel, double-click the background to fit."""

    def __init__(
        self,
        pal: dict[str, str],
        on_open: Callable[[str], None],
        on_add: Callable[[Node], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.pal = pal
        self.on_open = on_open
        self.on_add = on_add
        self.dots: dict[str, Dot] = {}
        self.edges: list[Edge] = []
        self.linked: dict[str, list[str]] = {}
        self.pinned: Dot | None = None
        self.pointed: Dot | None = None
        self.zoomed = False
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # Dragging pans; scroll bars would only be a second, smaller way to do it.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QBrush(_colour(pal["surface"])))
        self.setStyleSheet(f"QGraphicsView{{border:1px solid {pal['border']};border-radius:6px;}}")

        # A card drawn by the map itself rather than a tooltip: it shows at once,
        # can be kept open, and its text can be selected and copied.
        self.card = QLabel(self.viewport())
        self.card.setTextFormat(Qt.TextFormat.RichText)
        self.card.setWordWrap(True)
        self.card.setFixedWidth(CARD_W)
        self.card.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.card.setStyleSheet(
            f"QLabel{{background:{pal['surface']};color:{pal['ink']};"
            f"border:1px solid {pal['firm']};border-radius:6px;padding:10px 12px;"
            f"font-size:12.5px;}}"
        )
        self.card.hide()

    def show_graph(self, graph: Graph) -> None:
        scene = self.scene()
        scene.clear()
        self.dots.clear()
        self.edges.clear()
        self.pinned = self.pointed = None
        self.card.hide()
        pos, heads = layout(graph)
        for n in graph.nodes:
            dot = Dot(n, self.pal, self)
            dot.setPos(*pos[n.key])
            scene.addItem(dot)
            self.dots[n.key] = dot
        centre = graph.nodes[0].key if graph.nodes else ""
        self.linked = {k: [] for k in self.dots}
        for a, b in graph.edges:
            edge = Edge(self.dots[a], self.dots[b], self.pal, centre in (a, b))
            scene.addItem(edge)
            self.edges.append(edge)
            if centre not in (a, b):
                self.linked[a].append(self.dots[b].node.label)
                self.linked[b].append(self.dots[a].node.label)

        top = min((d.pos().y() - d.r for d in self.dots.values()), default=0)
        caption = QFont()
        caption.setPixelSize(11)
        for x, text in heads:
            item = QGraphicsSimpleTextItem(text)
            item.setFont(caption)
            item.setBrush(_colour(self.pal["faint"]))
            w = QFontMetricsF(caption).horizontalAdvance(text)
            item.setPos(x - w / 2, top - 30)
            scene.addItem(item)
        side_font = QFont()
        side_font.setPixelSize(12)
        side_font.setBold(True)
        for side, name in SIDE_NAME.items():
            xs = [d.pos().x() for d in self.dots.values() if d.node.side == side]
            if not xs:
                continue
            item = QGraphicsSimpleTextItem(name)
            item.setFont(side_font)
            item.setBrush(_colour(self.pal["muted"]))
            w = QFontMetricsF(side_font).horizontalAdvance(name)
            item.setPos((min(xs) + max(xs)) / 2 - w / 2, top - 52)
            scene.addItem(item)
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-30, -20, 30, 20))
        self.fit()

    def fit(self) -> None:
        self.zoomed = False
        self.resetTransform()
        rect = self.scene().sceneRect()
        if rect.isEmpty():
            return
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        # A small map fitted to a large view would be blown up past life size.
        if self.transform().m11() > 1.0:
            self.resetTransform()
            self.centerOn(rect.center())

    # ---- pointing, pinning ----------------------------------------------------------
    def point_at(self, dot: Dot | None) -> None:
        self.pointed = dot
        self._show(dot or self.pinned)

    def pin(self, dot: Dot) -> None:
        self.pinned = None if self.pinned is dot else dot
        self._show(self.pointed or self.pinned)

    def _show(self, dot: Dot | None) -> None:
        key = dot.node.key if dot else None
        for edge in self.edges:
            if key is None:
                edge.style("rest")
            elif key in (edge.a.node.key, edge.b.node.key):
                edge.style("lit")
            else:
                edge.style("dim")
        for k, d in self.dots.items():
            d.lit = k == key or d is self.pinned
            d.update()
        if dot is None:
            self.card.hide()
            return
        self.card.setText(card_html(dot.node, self.pal, self.linked.get(key, [])))
        self.card.adjustSize()
        self._place(dot)
        self.card.show()
        self.card.raise_()

    def _place(self, dot: Dot) -> None:
        """Beside the circle, on whichever side has room, inside the view."""
        at = self.mapFromScene(dot.pos())
        scale = self.transform().m11()
        r = int(dot.r * scale) + 12
        view = self.viewport().rect()
        w, h = self.card.width(), self.card.height()
        x = at.x() + r if at.x() + r + w <= view.right() - 6 else at.x() - r - w
        x = max(6, min(x, view.right() - w - 6))
        y = max(6, min(at.y() - h // 3, view.bottom() - h - 6))
        self.card.move(QPoint(x, y))

    # ---- the background -------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if not isinstance(self.itemAt(event.position().toPoint()), Dot) and self.pinned:
            self.pinned = None
            self._show(self.pointed)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if not isinstance(self.itemAt(event.position().toPoint()), Dot):
            self.fit()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self.zoomed = True
        if self.card.isVisible() and (self.pointed or self.pinned):
            self._place(self.pointed or self.pinned)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        if self.card.isVisible() and (self.pointed or self.pinned):
            self._place(self.pointed or self.pinned)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # The view's real size is only known once it is on screen; until the reader
        # zooms, the map keeps fitting it.
        if not self.zoomed:
            self.fit()
