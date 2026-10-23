"""Preview a topic's evidence-grounded reading route before creating a list."""

import json
import threading
import time

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from paper_daily import ai_choices, list_create, llm, research_plan
from paper_daily.desktop.ai_access import requires_ai
from paper_daily.desktop.ask import AskRunner


class ImportListDialog(QDialog):
    progress = Signal(str)

    def __init__(self, palette, repo_root, parent=None, *, on_analysis=None):
        super().__init__(parent)
        self.imported = False
        self.list_id = None
        self.analyze_after = False
        self._confirming_analysis = False
        self._can_analyze = on_analysis is not None
        self._added = 0
        self.plan = None
        self.cancel = threading.Event()
        self._working = False
        self._stage = ""
        self.runner = AskRunner(self)
        self.setWindowTitle("建立研究清單")
        self.resize(900, 780)
        layout = QVBoxLayout(self)
        self.mode = QComboBox()
        for text, key in (
            ("描述主題／研究問題 → 調查文獻與規畫路線", "topic"),
            ("貼上參考文獻／已知論文清單", "references"),
            ("建立空白清單", "empty"),
        ):
            self.mode.addItem(text, key)
        layout.addWidget(self.mode)
        self.name = QLineEdit()
        self.name.setPlaceholderText("清單名稱（可自行命名）")
        layout.addWidget(self.name)
        self.body = QPlainTextEdit()
        layout.addWidget(self.body, 1)
        options_row = QHBoxLayout()
        output_column, depth_column = QVBoxLayout(), QVBoxLayout()
        options_row.addLayout(output_column, 1)
        options_row.addLayout(depth_column, 1)
        layout.addLayout(options_row)
        self.output_label = QLabel("產出形式")
        output_column.addWidget(self.output_label)
        self.output = QComboBox()
        for key, options in research_plan.OUTPUTS.items():
            self.output.addItem(options["label"], key)
            self.output.setItemData(self.output.count() - 1, options["hint"],
                                    Qt.ItemDataRole.ToolTipRole)
        output_column.addWidget(self.output)
        self.output_hint = QLabel()
        self.output_hint.setWordWrap(True)
        layout.addWidget(self.output_hint)
        self.depth_label = QLabel("搜尋深度（各產出形式皆可調整）")
        depth_column.addWidget(self.depth_label)
        self.depth = QComboBox()
        for key, options in research_plan.DEPTHS.items():
            self.depth.addItem(
                f"{options['label']} · 最多 {options['papers']} 篇"
                f" · 最多 {options['rounds']} 輪搜尋",
                key,
            )
        self.depth.setCurrentIndex(self.depth.findData("standard"))
        depth_column.addWidget(self.depth)
        self.help = QLabel()
        self.help.setWordWrap(True)
        layout.addWidget(self.help)
        ai_row = QHBoxLayout()
        self.ai_label = QLabel()
        self.ai_label.setWordWrap(True)
        ai_row.addWidget(self.ai_label, 1)
        self.ai_button = QPushButton("切換 AI")
        self.ai_button.clicked.connect(self._choose_ai)
        ai_row.addWidget(self.ai_button)
        layout.addLayout(ai_row)
        self._refresh_ai()
        self.preview = QTabWidget()
        self.papers = QTreeWidget()
        self.papers.setHeaderLabels(["選入／建議閱讀順序", "分支 · 角色", "選入理由", "PDF 來源"])
        self.papers.setColumnWidth(0, 320)
        self.papers.setColumnWidth(1, 150)
        self.papers.setAlternatingRowColors(True)
        self.papers.itemDoubleClicked.connect(self._open_source)
        self.preview.addTab(self.papers, "勾選文獻")
        self.explanation = QPlainTextEdit()
        self.explanation.setReadOnly(True)
        self.preview.addTab(self.explanation, "研究脈絡與檢索限制")
        layout.addWidget(self.preview, 2)
        self.preview.hide()
        self.confirm = QCheckBox("我已核對研究問題、範圍與納入／排除條件")
        self.confirm.hide()
        layout.addWidget(self.confirm)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress.connect(self._progress)
        self.progress.connect(self.runner.report)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.bar)
        row = QHBoxLayout()
        self.go = QPushButton()
        self.go.clicked.connect(self._start)
        row.addWidget(self.go)
        self.again = QPushButton("重新調查")
        self.again.clicked.connect(self._again)
        self.again.hide()
        row.addWidget(self.again)
        self.stop = QPushButton("取消調查")
        self.stop.clicked.connect(self._cancel)
        self.stop.hide()
        row.addWidget(self.stop)
        self.close_btn = QPushButton("關閉")
        self.close_btn.clicked.connect(self.reject)
        row.addWidget(self.close_btn)
        layout.addLayout(row)
        self.fulltext = QPushButton("開啟清單並逐篇深入分析…")
        self.fulltext.clicked.connect(self._request_fulltext)
        self.fulltext.hide()
        layout.addWidget(self.fulltext)
        self.elapsed = QTimer(self)
        self.elapsed.setInterval(1000)
        self.elapsed.timeout.connect(self._tick)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.body.textChanged.connect(self._invalidate)
        self.depth.currentIndexChanged.connect(self._invalidate)
        self.output.currentIndexChanged.connect(self._output_changed)
        self._output_changed()
        self._mode_changed()

    def _output_changed(self):
        self._invalidate()
        self.output_hint.setText(research_plan.OUTPUTS[self.output.currentData()]["hint"])

    def _request_fulltext(self):
        if (not self.imported or not self._can_analyze or self._working or self.runner.busy
                or self.analyze_after or self._confirming_analysis):
            return
        self._confirming_analysis = True
        try:
            answer = QMessageBox.question(
                self, "開始全文深入分析？",
                f"將對剛建立清單的 {self._added} 篇文獻取得可用 PDF 並補齊深入分析。\n"
                "會使用各分析功能設定的 AI 帳號／模型，耗時與用量較高；"
                "無法取得的全文會標示未完成。\n"
                "這不會自動完成正式系統性回顧，也不會自動更新清單綜覽。確定開始？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
        finally:
            self._confirming_analysis = False
        if answer == QMessageBox.StandardButton.Yes:
            self.analyze_after = True
            self.accept()

    def _refresh_ai(self):
        try:
            self.ai_label.setText("本次調查：" + ai_choices.connection_label(
                llm.settings(task="list_parse")))
        except (ValueError, OSError):
            self.ai_label.setText("請先選擇建立清單使用的 AI。")

    def _choose_ai(self):
        from paper_daily.desktop.ai_picker import AIPickerDialog

        dialog = AIPickerDialog(self, task="list_parse")
        dialog.exec()
        self._refresh_ai()

    def _open_source(self, row, _column):
        if self.plan:
            pid = row.data(0, Qt.ItemDataRole.UserRole)
            url = research_plan._url(self.plan["candidates"][pid]["url"])
            if url:
                QDesktopServices.openUrl(QUrl(url))

    def _key(self):
        return (self.mode.currentData(), self.body.toPlainText(), self.depth.currentData(),
                self.output.currentData())

    def _invalidate(self):
        if self.imported:
            return
        self.plan = None
        self.preview.hide()
        self.again.hide()
        self.confirm.hide()
        self.confirm.setChecked(False)
        self.body.setMaximumHeight(16777215)
        self.go.setText("調查並預覽研究路線" if self.mode.currentData() == "topic" else "建立清單")

    def _mode_changed(self):
        mode = self.mode.currentData()
        self._invalidate()
        self.body.setVisible(mode != "empty")
        self.depth.setVisible(mode == "topic")
        for widget in (self.output, self.output_label, self.output_hint, self.depth_label):
            widget.setVisible(mode == "topic")
        self.ai_label.setVisible(mode != "empty")
        self.ai_button.setVisible(mode != "empty")
        self.body.setPlaceholderText(
            "直接描述想解決的研究問題，不必知道論文標題。\n"
            "可補充：應用情境、目前理解程度、時間範圍、想排除的方向，或一篇種子論文。\n"
            "例如：我想研究推理模型量化後的可靠性，先補基礎，再看評測方法與反例。"
            if mode == "topic" else "貼上真正的論文標題或參考文獻，不必整理格式。"
        )
        self.help.setText(
            "使用「建立清單」的 AI 帳號／模型設定。先依標題與摘要調查、預覽並勾選，"
            "確認後才建立清單；開啟清單可自動下載公開 PDF，全文 AI 分析需另外啟動。"
            if mode == "topic" else
            "若輸入的是研究方向或問題，請切換上方的「描述主題／研究問題」。"
            "AI 建立需要登入；空白清單不需要 AI。"
        )

    def _start(self):
        if self._working or self.runner.busy:
            return
        if self.imported:
            self.accept()
            return
        if not self.name.text().strip():
            self.status.setText("請先輸入清單名稱。")
            return
        if self.mode.currentData() != "empty" and not self.body.toPlainText().strip():
            self.status.setText("請輸入研究問題或參考文獻。")
            return
        if self.plan is not None:
            self._commit()
        elif self.mode.currentData() == "empty":
            self._create()
        else:
            self._create_ai()

    @requires_ai("list_parse")
    def _create_ai(self):
        if self.mode.currentData() == "topic":
            self._propose()
        else:
            self._create()

    def _set_busy(self, value, cancellable=False):
        self._working = value
        for widget in (self.go, self.mode, self.body, self.name,
                       self.depth, self.again, self.papers, self.ai_button,
                       self.output, self.confirm):
            widget.setEnabled(not value)
        self.bar.setVisible(value)
        self.stop.setVisible(value and cancellable)
        self.stop.setEnabled(True)
        if value:
            self._started = time.monotonic()
            self.elapsed.start()
        else:
            self.elapsed.stop()

    def _progress(self, message):
        self._stage = message
        self._tick()

    def _tick(self):
        if self._working:
            seconds = int(time.monotonic() - self._started)
            stage = ("已要求取消，等待目前查詢／AI 回覆結束…"
                     if self.cancel.is_set() else self._stage)
            self.status.setText(f"{stage}\n已用 {seconds // 60} 分 {seconds % 60} 秒")

    def _cancel(self):
        self.cancel.set()
        self.stop.setEnabled(False)
        self._tick()

    def _failed(self, reason):
        self._set_busy(False)
        if self.mode.currentData() == "references":
            reason += "\n若貼的是研究問題，請改選「描述主題／研究問題」做文獻調查。"
        self.status.setText("未完成：" + reason)

    def _propose(self):
        key = self._key()
        self.cancel.clear()
        self._stage = "規畫研究路線…"
        self._refresh_ai()
        self._set_busy(True, cancellable=True)
        self._tick()

        def call(_):
            try:
                value = research_plan.propose(
                    key[1], key[2], self.progress.emit, self.cancel, key[3])
                return json.dumps(value, ensure_ascii=False), "ok"
            except (ValueError, OSError) as exc:
                return None, str(exc)

        def done(text):
            self._set_busy(False)
            if self.cancel.is_set() or self._key() != key:
                self.status.setText("調查已取消或輸入已變更；未套用舊結果，也未建立清單。")
                return
            self.plan = json.loads(text)
            self.papers.clear()
            for i, item in enumerate(self.plan["items"], 1):
                paper = self.plan["candidates"][item["id"]]
                from paper_daily import pdf_sources

                links = pdf_sources.known_links(dict(
                    pdf_url=(paper.get("openAccessPdf") or {}).get("url"),
                    arxiv_id=(paper.get("externalIds") or {}).get("ArXiv"),
                    doi=(paper.get("externalIds") or {}).get("DOI"), page_url=paper.get("url")))
                row = QTreeWidgetItem([
                    f"{i}. {paper['title']} ({paper.get('year') or '?'})",
                    item["branch"] + " · " + item["role"], item["why"],
                    "已找到連結" if links else "開啟後尋找",
                ])
                row.setToolTip(3, "\n".join(links) if links else
                               "背景查找公開原文，無法保證可取得全文。")
                row.setData(0, Qt.ItemDataRole.UserRole, item["id"])
                row.setCheckState(0, Qt.CheckState.Checked)
                for column in range(3):
                    row.setToolTip(column, item["why"] + "\n" + paper["url"])
                self.papers.addTopLevelItem(row)
            self.explanation.setPlainText(research_plan.report(self.plan))
            self.preview.show()
            self.confirm.setVisible(self.plan.get("output") in ("staged", "protocol"))
            self.body.setMaximumHeight(100)
            self.again.show()
            self.go.setText("以勾選文獻建立清單")
            self.status.setText(
                f"已找到 {len(self.plan['candidates'])} 篇候選，建議 {len(self.plan['items'])} 篇。"
                "雙擊文獻可核對來源；查看脈絡與理由後勾選建立。"
                + (" 部分搜尋未成功，請查看檢索限制。" if self.plan["warnings"] else "")
            )

        self.runner.start("", done, self._failed, call=call, task="list_parse")

    def _again(self):
        if self._working or self.runner.busy:
            return
        self._invalidate()
        self._start()

    def _commit(self):
        selected = [self.papers.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                    for i in range(self.papers.topLevelItemCount())
                    if self.papers.topLevelItem(i).checkState(0) == Qt.CheckState.Checked]
        if not selected:
            self.status.setText("請至少勾選一篇；目前尚未建立清單。")
            return
        confirmed = self.confirm.isChecked()
        if self.plan.get("output") in ("staged", "protocol") and not confirmed:
            self.status.setText("請先閱讀研究脈絡頁中的範圍草案，再勾選確認研究問題及納排條件。")
            return
        plan, name = self.plan, self.name.text()
        self._stage = "儲存勾選文獻與研究路線…"
        self._set_busy(True)

        def call(_):
            try:
                return json.dumps(research_plan.commit(name, plan, selected, confirmed)), "ok"
            except (ValueError, OSError) as exc:
                return None, str(exc)

        self.runner.start("", self._created, self._failed, call=call, task="list_parse")

    def _created(self, text):
        result = json.loads(text)
        self.list_id, self.imported = result["id"], True
        self._added = result["added"]
        self._set_busy(False)
        for widget in (self.mode, self.body, self.name, self.depth, self.again, self.papers,
                       self.output, self.confirm):
            widget.setEnabled(False)
        self.status.setText(
            f"已建立清單，共 {result['added']} 篇。"
            + ("研究路線已存入「清單綜覽」，可編輯並隨資料包分享。" if self.plan else
               "選擇文章後可下載原文或深入分析。")
        )
        self.go.setText("開啟清單")
        self.fulltext.setVisible(bool(self.plan and self._can_analyze and self._added))
        if self.plan and self.confirm.isChecked():
            confirmed = dict(self.plan, scope_confirmed=True)
            self.explanation.setPlainText(research_plan.report(confirmed))

    def _create(self):
        name, raw, mode = self.name.text(), self.body.toPlainText(), self.mode.currentData()
        self.cancel.clear()
        self._stage = "正在建立清單…"
        self._set_busy(True)

        def call(_):
            try:
                result = list_create.create(name, raw, mode, self.progress.emit)
                return json.dumps(result), "ok"
            except (ValueError, OSError) as exc:
                return None, str(exc)

        self.runner.start("", self._created, self._failed, call=call, task="list_parse")

    def reject(self):
        if self._working or self.runner.busy:
            self.status.setText("工作仍在執行；調查可先按「取消調查」，結束後即可關閉。")
            return
        super().reject()

    def closeEvent(self, event):
        if self._working or self.runner.busy:
            event.ignore()
        else:
            super().closeEvent(event)


def run_import(palette, repo_root, parent=None, *, on_analysis=None):
    dialog = ImportListDialog(palette, repo_root, parent, on_analysis=on_analysis)
    dialog.exec()
    if dialog.imported and dialog.analyze_after and on_analysis is not None:
        list_id = dialog.list_id
        if parent is not None:
            QTimer.singleShot(0, parent, lambda: on_analysis(list_id))
        else:
            QTimer.singleShot(0, lambda: on_analysis(list_id))
    return dialog.list_id if dialog.imported else None
