"""Everyday task choices use reusable accounts; connection details stay elsewhere."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from paper_daily import ai_accounts, ai_choices, llm, model_catalog
from paper_daily.ai_types import Settings
from paper_daily.desktop.ai_dialog import TASK_LABELS
from paper_daily.desktop.ask import AskRunner
from paper_daily.desktop.settings_style import apply as style_settings


class AITasksDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        style_settings(self)
        self.setWindowTitle("Paperfact · 進階設定")
        self.resize(900, 760)
        self.runner = AskRunner(self, read_only=True)
        self.rows = {}
        self.effective = {}
        self.row_widgets = {}
        self._cache = {}
        self._queue = {}
        self._scheduled = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 18)
        heading = QLabel("進階設定 · 各功能的 AI")
        heading.setStyleSheet("font-size:20px;font-weight:600;")
        layout.addWidget(heading)
        default_box = QGroupBox("全域預設")
        default_layout = QHBoxLayout(default_box)
        self.default_label = QLabel()
        self.default_label.setWordWrap(True)
        default_layout.addWidget(self.default_label, 1)
        self.default_button = QPushButton("變更全域預設…")
        self.default_button.clicked.connect(self._default)
        default_layout.addWidget(self.default_button)
        layout.addWidget(default_box)
        instruction = QLabel(
            "跟隨全域的功能會一起更新；個別指定的功能保留自己的帳號與模型。"
        )
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        bar = QHBoxLayout()
        self.accounts_button = QPushButton("帳號與用量…")
        self.accounts_button.clicked.connect(self._accounts)
        bar.addWidget(self.accounts_button)
        self.refresh_button = QPushButton("重新取得模型")
        self.refresh_button.clicked.connect(self._retry_models)
        bar.addWidget(self.refresh_button)
        bar.addStretch()
        self.follow_button = QPushButton("全部跟隨全域")
        self.follow_button.clicked.connect(self._follow)
        bar.addWidget(self.follow_button)
        layout.addLayout(bar)
        options = QHBoxLayout()
        self.only_overrides = QCheckBox("只看個別指定")
        self.only_overrides.toggled.connect(self._filter)
        options.addWidget(self.only_overrides)
        options.addStretch()
        self.custom_models = QCheckBox("自訂模型 ID（進階）")
        self.custom_models.toggled.connect(self._custom_models)
        options.addWidget(self.custom_models)
        layout.addLayout(options)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        for column, label in enumerate(("功能", "AI 服務／帳號", "模型")):
            grid.addWidget(QLabel(label), 0, column)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        for index, (task, label) in enumerate(TASK_LABELS.items(), 1):
            account, model = QComboBox(), QComboBox()
            for combo in (account, model):
                combo.setSizeAdjustPolicy(
                    QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
                )
                combo.setMinimumContentsLength(18)
            account.setMinimumHeight(32)
            model.setMinimumHeight(32)
            model.setEditable(True)
            model.lineEdit().setReadOnly(True)
            model.lineEdit().setPlaceholderText("選擇模型，或輸入名稱")
            account.setAccessibleName(f"{label} AI 帳號")
            model.setAccessibleName(f"{label} 模型")
            self.rows[task] = account, model
            label_widget = QLabel(label)
            grid.addWidget(label_widget, index * 2 - 1, 0)
            grid.addWidget(account, index * 2 - 1, 1)
            grid.addWidget(model, index * 2 - 1, 2)
            resolved = QLabel()
            resolved.setWordWrap(True)
            grid.addWidget(resolved, index * 2, 1, 1, 2)
            self.effective[task] = resolved
            resolved.setProperty("role", "muted")
            self.row_widgets[task] = (label_widget, account, model, resolved)
            model.currentTextChanged.connect(lambda _text, task=task: self._resolved(task))
            account.currentIndexChanged.connect(lambda _i, task=task: self._changed(task))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.status = QLabel("選擇後按儲存；只影響之後開始的工作。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.save_button = buttons.addButton("儲存分配", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setProperty("role", "primary")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        routes = llm.task_routes()
        selections = {
            task: (llm.settings(task=task), llm.settings(task=task).model)
            if task in routes
            else None
            for task in self.rows
        }
        self._refresh(selections)
        self.only_overrides.setChecked(bool(routes))
        self._queue_default()
        from paper_daily.desktop.account_status import AccountStatus

        self.identities = AccountStatus(self, self._identity_changed)

    def showEvent(self, event):
        super().showEvent(event)
        self.identities.check(ai_choices.accounts())
        self._identity_changed()
        if self._queue:
            self._schedule()

    def _identity_changed(self):
        self.default_label.setText("全域 AI：" + ai_choices.connection_label(llm.settings()))
        for task, (account, _model) in self.rows.items():
            for index in range(1, account.count()):
                cfg = account.itemData(index)
                account.setItemText(index, self._account_label(cfg))
            if account.currentData() is None:
                self._changed(task)
            else:
                self._resolved(task)

    def _custom_models(self, enabled):
        for _account, model in self.rows.values():
            model.lineEdit().setReadOnly(not enabled)

    def _filter(self):
        for task, widgets in self.row_widgets.items():
            visible = not self.only_overrides.isChecked() or bool(self.rows[task][0].currentData())
            for widget in widgets:
                widget.setVisible(visible)

    def _queue_default(self):
        cfg = llm.settings()
        key = ai_choices.account_key(cfg)
        if cfg.backend in ("cli", "codex") and key not in self._cache:
            self._queue.setdefault(key, cfg)
            self._schedule()

    def _retry_models(self):
        if self.runner.busy:
            return
        self._cache.clear()
        for task, (account, model) in self.rows.items():
            if account.currentData():
                self._changed(task, selected=self._model(model))
        self._queue_default()
        self.status.setText("正在重新取得模型；已選擇的模型會保留。")

    @staticmethod
    def _account_label(cfg):
        brand = ai_choices.LABELS.get(cfg.backend, cfg.backend)
        return f"{brand} · {ai_choices.account_title(cfg)}"

    def _resolved(self, task):
        from dataclasses import replace

        account, model = self.rows[task]
        cfg = account.currentData()
        chosen = replace(cfg, model=self._model(model) or None) if cfg else llm.settings()
        scope = "個別指定" if cfg else "沿用全域"
        self.effective[task].setText(f"{scope} · {ai_choices.model_label(chosen)}")
        self.effective[task].setToolTip(ai_choices.connection_label(chosen))
        model.setToolTip(ai_choices.model_hint(chosen.backend, chosen.model, cfg=chosen))

    def _refresh(self, selections):
        default = llm.settings()
        self.default_label.setText("全域 AI：" + ai_choices.connection_label(default))
        options = ai_choices.accounts()
        keys = {ai_choices.account_key(cfg) for cfg in options}
        for selection in selections.values():
            if selection and ai_choices.account_key(selection[0]) not in keys:
                options.append(selection[0])
                keys.add(ai_choices.account_key(selection[0]))
        present = {cfg.backend for cfg in options}
        options += [
            Settings(backend, isolated=True)
            for backend in ai_choices.LABELS
            if backend not in present
        ]
        labels = [self._account_label(cfg) for cfg in options]
        for task, (account, _model) in self.rows.items():
            account.blockSignals(True)
            account.clear()
            account.addItem("跟隨全域", None)
            for cfg, label in zip(options, labels, strict=True):
                account.addItem(label, cfg)
            selection = selections.get(task)
            if selection:
                cfg, model = selection
                index = next(
                    (
                        i + 1
                        for i, option in enumerate(options)
                        if ai_choices.account_key(option) == ai_choices.account_key(cfg)
                    ),
                    0,
                )
                account.setCurrentIndex(index)
            account.blockSignals(False)
            self._changed(task, selected=(selection[1] or "") if selection else None)
        self._filter()

    @staticmethod
    def _model(picker):
        text = picker.currentText().strip()
        index = picker.currentIndex()
        return picker.itemData(index) if index >= 0 and text == picker.itemText(index) else text

    def _fill(self, task, models, selected):
        picker = self.rows[task][1]
        cfg = self.rows[task][0].currentData() or llm.settings()
        picker.clear()
        picker.addItem(ai_choices.model_option_label(cfg.backend, "", cfg=cfg), "")
        for model in dict.fromkeys(models):
            if model:
                picker.addItem(ai_choices.model_option_label(cfg.backend, model, cfg=cfg), model)
                picker.setItemData(picker.count() - 1, model, Qt.ItemDataRole.ToolTipRole)
        if selected and picker.findData(selected) < 0:
            picker.addItem(ai_choices.model_option_label(cfg.backend, selected, cfg=cfg), selected)
        picker.setCurrentIndex(max(0, picker.findData(selected or "")))

    def _changed(self, task, *, selected=None):
        account, model = self.rows[task]
        cfg = account.currentData()
        model.setEnabled(cfg is not None)
        if cfg is None:
            model.clear()
            model.addItem(ai_choices.model_label(llm.settings()), "")
            self._resolved(task)
            return
        selected = cfg.model if selected is None else selected
        if hasattr(self, "identities"):
            self.identities.check([cfg])
        key = ai_choices.account_key(cfg)
        if cfg.backend == "gemini" and key not in self._cache:
            self._cache[key] = ai_accounts.models(cfg)
        self._fill(task, self._cache.get(key, model_catalog.models(cfg)), selected)
        self._resolved(task)
        if cfg.backend in ("cli", "codex") and key not in self._cache:
            self._queue[key] = cfg
            self._schedule()

    def _schedule(self):
        if not self._scheduled:
            self._scheduled = True
            QTimer.singleShot(50, self._pump)

    def _pump(self):
        self._scheduled = False
        if not self.isVisible() or not self._queue:
            return
        if self.runner.busy:
            self._schedule()
            return
        selected = {ai_choices.account_key(account.currentData())
                    for account, _model in self.rows.values() if account.currentData()}
        key = next((key for key in self._queue if key in selected), next(iter(self._queue)))
        cfg = self._queue[key]
        self._queue.pop(key)
        if key in self._cache:
            self._schedule()
            return
        self.status.setText(f"正在取得 {ai_choices.LABELS[cfg.backend]} 模型清單…")

        def fetch(_prompt):
            try:
                return json.dumps(ai_accounts.models(cfg)), "ok"
            except (ValueError, OSError, TimeoutError):
                return None, "模型清單暫時無法取得；可保留原模型或自行輸入名稱。"

        def finish(models, message):
            if models is not None:
                self._cache[key] = models
            for task, (account, model) in self.rows.items():
                current = account.currentData()
                if current and ai_choices.account_key(current) == key:
                    self._fill(task, models or self._cache.get(key, []), self._model(model))
                    self._resolved(task)
                elif current is None:
                    self._changed(task)
            self.default_label.setText("全域 AI：" + ai_choices.connection_label(llm.settings()))
            self.status.setText(message)
            self._schedule()

        self.runner.start(
            "",
            lambda value: finish(json.loads(value), "模型清單已更新；選好後按儲存。"),
            lambda reason: finish(None, reason),
            call=fetch,
        )

    def _selections(self):
        return {
            task: (account.currentData(), self._model(model)) if account.currentData() else None
            for task, (account, model) in self.rows.items()
        }

    def _follow(self):
        for account, _model in self.rows.values():
            account.setCurrentIndex(0)
        self.only_overrides.setChecked(False)

    def _accounts(self):
        from paper_daily.desktop.ai_picker import AIPickerDialog

        selections = self._selections()
        dialog = AIPickerDialog(self, accounts_only=True)
        dialog.exec()
        self._refresh(selections)

    def _default(self):
        from paper_daily.desktop.ai_picker import AIPickerDialog

        selections = self._selections()
        dialog = AIPickerDialog(self, show_advanced=False)
        dialog.exec()
        self._refresh(selections)
        self._queue_default()

    def _save(self):
        try:
            llm.save_task_choices(self._selections())
        except (ValueError, OSError) as exc:
            self.status.setText(f"未儲存：{exc}")
            return
        self.accept()

    def accept(self):
        self.runner.cancel_read()
        self._queue.clear()
        super().accept()

    def reject(self):
        self.runner.cancel_read()
        self._queue.clear()
        super().reject()
