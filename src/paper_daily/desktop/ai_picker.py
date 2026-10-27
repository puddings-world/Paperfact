"""The everyday AI UI: choose a service, sign in, choose a model."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paper_daily import ai_accounts, ai_choices, ai_providers, llm, model_catalog, usage_cache
from paper_daily.desktop.ai_usage import UsageSummary
from paper_daily.desktop.ask import AskRunner
from paper_daily.desktop.settings_style import apply as style_settings


class AIPickerDialog(QDialog):
    def __init__(self, parent=None, *, accounts_only=False, task=None, show_advanced=True):
        super().__init__(parent)
        style_settings(self)
        self.accounts_only = accounts_only
        self.task = task
        from paper_daily.desktop.ai_dialog import TASK_LABELS

        self.task_label = TASK_LABELS.get(task, task)
        self.setWindowTitle("Paperfact · " + (
            "帳號與用量" if accounts_only else (
                f"{self.task_label}使用的 AI" if task else "全域預設 AI"
            )
        ))
        self.resize(660, 720)
        self.runner = AskRunner(self, read_only=True)
        self.auth_runner = AskRunner(self)
        self.cfg = None
        self._models = []
        self._epoch = 0
        self._inspection_pending = False
        self._usage_version = None
        self._authenticated = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        title = QLabel("帳號與用量" if accounts_only else (
            f"{self.task_label}使用的 AI" if task else "全域預設 AI"
        ))
        title.setStyleSheet("font-size:22px;font-weight:600;")
        layout.addWidget(title)
        self.scope_hint = QLabel(
            "加入帳號後，可回到各功能選用；登入本身不會切換全域預設。" if accounts_only else
            f"只變更「{self.task_label}」；其他功能與全域預設保持原設定。" if task else
            "未個別指定的功能都使用這裡的帳號與模型。"
        )
        self.scope_hint.setWordWrap(True)
        self.scope_hint.setProperty("role", "muted")
        layout.addWidget(self.scope_hint)
        self.services = QWidget()
        row = QHBoxLayout(self.services)
        row.setContentsMargins(0, 0, 0, 0)
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.providers = {}
        for backend, label in ai_choices.LABELS.items():
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(46)
            group.addButton(button)
            row.addWidget(button)
            button.clicked.connect(lambda _checked=False, backend=backend: self._select(backend))
            self.providers[backend] = button
        layout.addWidget(self.services)
        self.accounts = QComboBox()
        self.accounts.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.accounts.setMinimumContentsLength(18)
        self.accounts.currentIndexChanged.connect(self._account_changed)
        layout.addWidget(self.accounts)
        account_row = QHBoxLayout()
        self.account_status = QLabel()
        self.account_status.setWordWrap(True)
        account_row.addWidget(self.account_status, 1)
        self.login_button = QPushButton("登入")
        self.login_button.clicked.connect(self._login)
        account_row.addWidget(self.login_button)
        self.manage_button = QPushButton("帳號選項")
        menu = QMenu(self.manage_button)
        menu.addAction("設定暱稱…", self._rename)
        self.logout_action = menu.addAction("登出此帳號…", self._logout)
        menu.addSeparator()
        menu.addAction("移除此連線…", self._forget)
        self.manage_button.setMenu(menu)
        account_row.addWidget(self.manage_button)
        layout.addLayout(account_row)
        self.model = QComboBox()
        self.model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.model.setMinimumContentsLength(18)
        self.model.setEditable(True)
        self.model.setMinimumHeight(36)
        self.model.lineEdit().setPlaceholderText("使用預設模型，或輸入模型名稱")
        self.model.lineEdit().setReadOnly(True)
        self.model_row = QWidget()
        model_row = QHBoxLayout(self.model_row)
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.addWidget(QLabel("模型"))
        model_row.addWidget(self.model, 1)
        self.custom_model = QCheckBox("自訂 ID")
        self.custom_model.setToolTip("進階：自行輸入服務支援的完整模型 ID。")
        self.custom_model.toggled.connect(lambda enabled: self.model.lineEdit().setReadOnly(
            not enabled
        ))
        model_row.addWidget(self.custom_model)
        layout.addWidget(self.model_row)
        self.model_row.setVisible(not accounts_only)
        self.model_hint = QLabel()
        self.model_hint.setProperty("role", "muted")
        self.model_hint.setWordWrap(True)
        layout.addWidget(self.model_hint)
        self.model_hint.setVisible(not accounts_only)
        self.model.currentTextChanged.connect(self._update_model_hint)
        self.usage = UsageSummary()
        self.usage.refresh_button.clicked.connect(self._refresh_usage)
        layout.addWidget(self.usage)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.route_hint = QLabel()
        self.route_hint.setWordWrap(True)
        layout.addWidget(self.route_hint)
        layout.addStretch(1)
        footer = QHBoxLayout()
        self.advanced = QPushButton("進階設定…")
        self.advanced.setFlat(True)
        self.advanced.clicked.connect(self._advanced)
        footer.addWidget(self.advanced)
        self.advanced.setVisible(not accounts_only and show_advanced)
        self.feedback_button = QPushButton("使用資料與回饋…")
        self.feedback_button.setFlat(True)
        self.feedback_button.clicked.connect(self._feedback)
        footer.addWidget(self.feedback_button)
        footer.addStretch(1)
        self.use_button = QPushButton("使用此 AI")
        self.use_button.setProperty("role", "primary")
        self.use_button.setMinimumHeight(36)
        self.use_button.clicked.connect(self._use)
        footer.addWidget(self.use_button)
        layout.addLayout(footer)
        current = llm.settings(task=task or "default")
        backend = self._provider(current) if self._provider(current) in self.providers else "cli"
        self._select(backend, check=False, selected=current.profile)
        if task and self._provider(current) == backend:
            self._fill_models(current.model)
        if self._provider(current) not in self.providers:
            self.notice.setText("目前使用 API 或其他設定；按下套用按鈕才會切換。")
        QTimer.singleShot(0, self._inspect)
        self.usage_timer = QTimer(self)
        self.usage_timer.setInterval(500)
        self.usage_timer.timeout.connect(self._cached_usage)
        self.usage_timer.start()

    @staticmethod
    def _provider(cfg):
        return "gemini" if ai_choices.is_gemini_api(cfg) else cfg.backend

    def _cached_usage(self):
        if self.cfg and self._authenticated is not False:
            snapshot = usage_cache.cache.peek(self.cfg)
            if snapshot and snapshot["version"] != self._usage_version:
                self.usage.reset(self.cfg)
                self.usage.show_result(snapshot["quota"], snapshot["local"])
                self._usage_version = snapshot["version"]

    def _select(self, backend, *, check=True, selected=None):
        self._epoch += 1
        self.providers[backend].setChecked(True)
        self.accounts.blockSignals(True)
        self.accounts.clear()
        current = selected or llm.active_profile()
        options = ai_choices.account_options(backend, current)
        for index, cfg in enumerate(options):
            label = ai_choices.account_title(cfg)
            self.accounts.addItem(label, cfg)
            if cfg.profile == current:
                self.accounts.setCurrentIndex(index)
        self.accounts.blockSignals(False)
        self.accounts.setVisible(len(options) > 1)
        self._account_changed(check=check)

    def _account_changed(self, _index=0, *, check=True):
        self._epoch += 1
        self.cfg = self.accounts.currentData()
        if self.cfg is None:
            return
        self.usage.reset(self.cfg)
        self._authenticated = None
        self._usage_version = None
        self._cached_usage()
        self._models = model_catalog.models(self.cfg)
        if self.cfg.backend == "gemini":
            self._models = ai_accounts.models(self.cfg)
        if ai_choices.uses_key(self.cfg):
            self._models = []
        self._fill_models(self.cfg.model)
        keyed = ai_choices.uses_key(self.cfg)
        self.account_status.setText(
            ai_choices.account_title(self.cfg) if keyed else "帳號尚未確認"
        )
        self.login_button.setText(
            ("更換 API 金鑰…" if self.cfg.api_key else "輸入 API 金鑰…") if keyed else "新增帳號"
        )
        self.logout_action.setEnabled(bool(self.cfg.account_id))
        self.manage_button.setToolTip(
            "暱稱、登出與移除連線" if self.cfg.account_id
            else "移除此連線會一併刪除 Paperfact 保存的金鑰。" if keyed
            else "本機共用登入由官方 CLI 管理；新增帳號可使用獨立登入。"
        )
        self.notice.clear()
        count = len(llm.task_routes())
        self.route_hint.setText(
            f"{count} 個功能另有指定 AI，可在「進階設定」修改。" if count else ""
        )
        self.route_hint.setVisible(bool(count) and not self.accounts_only)
        self.use_button.setText(
            "完成" if self.accounts_only else f"僅套用至{self.task_label}" if self.task
            else "設為全域預設"
        )
        if check:
            self._inspect()

    def _fill_models(self, selected):
        self.model.clear()
        # A key-based service has no account default to fall back on: a model is chosen.
        if not ai_choices.uses_key(self.cfg):
            self.model.addItem(
                ai_choices.model_option_label(self.cfg.backend, "", cfg=self.cfg), ""
            )
        for model in self._models:
            self.model.addItem(
                ai_choices.model_option_label(self.cfg.backend, model, cfg=self.cfg), model
            )
            self.model.setItemData(self.model.count() - 1, model, Qt.ItemDataRole.ToolTipRole)
        if selected and self.model.findData(selected) < 0:
            self.model.addItem(
                ai_choices.model_option_label(self.cfg.backend, selected, cfg=self.cfg), selected
            )
        self.model.setCurrentIndex(max(0, self.model.findData(selected or "")))
        self._update_model_hint()

    def _update_model_hint(self):
        if self.cfg:
            self.model_hint.setText(
                ai_choices.model_hint(self.cfg.backend, self._model(), cfg=self.cfg)
            )

    def _model(self):
        text = self.model.currentText().strip()
        index = self.model.currentIndex()
        if index >= 0 and text == self.model.itemText(index):
            return self.model.itemData(index)
        return text

    def _inspect(self, *, force=False):
        if self.auth_runner.busy:
            self._schedule_inspection()
            return
        if self.runner.busy:
            self._schedule_inspection()
            return
        if not self.cfg:
            return
        cfg, epoch = self.cfg, self._epoch
        if ai_choices.uses_key(cfg):
            self._inspect_key(cfg, epoch)
            return
        if not usage_cache.cache.peek(cfg):
            self.usage.reset(cfg)
        try:
            ai_accounts.command(cfg.backend)
        except ValueError:
            self.account_status.setText("尚未安裝 " + ai_choices.LABELS[cfg.backend])
            self.login_button.setText("安裝 " + ai_choices.LABELS[cfg.backend])
            self.usage.failed()
            return
        self.account_status.setText("正在確認帳號…")

        def inspect(_prompt):
            answer, reason = ai_accounts.auth(cfg, "status")
            models = []
            model_error = ""
            if answer and cfg.backend in ("cli", "codex"):
                try:
                    models = ai_accounts.models(cfg)
                    if not models:
                        model_error = "官方 CLI 未回傳可選模型；可保留原模型或輸入完整模型 ID。"
                except (ValueError, OSError, TimeoutError):
                    model_error = (
                        f"暫時無法取得 {ai_choices.LABELS[cfg.backend]} 模型清單；"
                        "可保留原模型或輸入完整模型 ID，按「重新整理」重試。"
                    )
            snapshot = usage_cache.cache.read(cfg, force=force) if answer else {
                "quota": {"windows": [], "message": "尚未確認登入，登入後可查詢方案用量。"},
                "local": (usage_cache.cache.peek(cfg) or {}).get("local"),
                "version": "unconfirmed",
            }
            return json.dumps({
                "account": answer or reason, "models": models, "model_error": model_error,
                "authenticated": bool(answer),
                **snapshot,
            }), "ok"

        def done(text):
            if epoch != self._epoch:
                self._schedule_inspection()
                return
            result = json.loads(text)
            self.account_status.setText(result["account"])
            self._authenticated = result.get("authenticated", True)
            ai_choices.remember_identity(cfg, result["account"])
            if self._authenticated:
                identity = ai_choices.account_title(cfg)
                self.account_status.setText(
                    identity if cfg.account_id else "本機共用登入 · " + identity
                )
            for index in range(self.accounts.count()):
                self.accounts.setItemText(
                    index, ai_choices.account_title(self.accounts.itemData(index))
                )
            self.usage.reset(cfg)
            self.usage.show_result(result["quota"], result["local"])
            self._usage_version = result["version"]
            self.notice.setText(result.get("model_error", ""))
            if cfg.backend in ("cli", "codex"):
                selected = self._model()
                self._models = result["models"]
                self._fill_models(selected)

        def failed(reason):
            if epoch == self._epoch:
                self.account_status.setText(reason)
                self.usage.reset(cfg)
                self.usage.failed()
            else:
                self._schedule_inspection()

        self.runner.start("", done, failed, call=inspect)

    def _inspect_key(self, cfg, epoch):
        """A key has no plan quota to show; checking it means listing its models."""
        self.usage.reset(cfg)
        self.usage.show_result(
            {"windows": [], "message": "API 金鑰按用量計費；費用請在服務商的帳單頁查看。"},
            None,
        )
        self._authenticated = bool(cfg.api_key)
        if not cfg.api_key:
            self.account_status.setText(
                "請按「輸入 API 金鑰…」，貼上 Google AI Studio（aistudio.google.com）的金鑰。"
            )
            return
        self.account_status.setText("正在確認 API 金鑰…")

        def check(_prompt):
            models, message = ai_providers.list_models(cfg)
            return json.dumps({"models": models, "message": message}), "ok"

        def done(text):
            if epoch != self._epoch:
                self._schedule_inspection()
                return
            result = json.loads(text)
            self._authenticated = bool(result["models"])
            self.account_status.setText(
                ai_choices.account_title(cfg) if result["models"] else result["message"]
            )
            selected = self._model() or cfg.model or self._suggested(result["models"])
            self._models = result["models"]
            self._fill_models(selected)

        def failed(reason):
            if epoch == self._epoch:
                self.account_status.setText(reason)

        self.runner.start("", done, failed, call=check)

    @staticmethod
    def _suggested(models):
        """The strongest model the key lists, so "use" works without a choice first."""
        for wanted in ("argon", "pro", "flash"):
            match = next((m for m in models if wanted in m and "preview" not in m), None)
            if match:
                return match
        return models[0] if models else ""

    def _refresh_usage(self):
        # Repeated refresh clicks do not queue another status/quota request.
        if not self.runner.busy:
            self.usage.refresh_button.setEnabled(False)
            self._inspect(force=True)

    def _schedule_inspection(self):
        if not self._inspection_pending:
            self._inspection_pending = True
            QTimer.singleShot(50, self._flush_inspection)

    def _flush_inspection(self):
        self._inspection_pending = False
        if self.isVisible():
            self._inspect()

    def _busy(self, busy):
        for widget in (
            self.services,
            self.accounts,
            self.model,
            self.login_button,
            self.manage_button,
            self.use_button,
            self.advanced,
            self.usage.refresh_button,
        ):
            widget.setEnabled(not busy)

    def _login(self):
        if self.auth_runner.busy:
            return
        self.runner.cancel_read()
        self._epoch += 1
        if ai_choices.uses_key(self.cfg):
            self._enter_key()
            return
        try:
            ai_accounts.command(self.cfg.backend)
        except ValueError:
            QDesktopServices.openUrl(QUrl(ai_choices.HELP[self.cfg.backend]))
            return
        cfg = ai_choices.new_account(self.cfg.backend, self._model())
        self._busy(True)
        self.notice.setText("請在瀏覽器完成登入；原帳號仍會保留。")

        def done(_text):
            self._busy(False)
            try:
                saved = ai_choices.save(cfg, cfg.model, activate=False)
            except (ValueError, OSError) as exc:
                self.notice.setText(str(exc))
                return
            self._select(cfg.backend, selected=saved.profile, check=False)
            self.account_status.setText("登入完成")
            self.notice.setText(
                "帳號已加入，可回到功能頁選用。"
                if self.accounts_only
                else f"選好模型後，按「{self.use_button.text()}」。"
            )
            QTimer.singleShot(0, self._inspect)

        def failed(reason):
            self._busy(False)
            self.notice.setText(reason)

        self.auth_runner.start(
            "", done, failed, call=lambda _prompt: ai_accounts.auth(cfg, "login")
        )

    def _enter_key(self):
        key, accepted = QInputDialog.getText(
            self,
            "Gemini API 金鑰",
            "到 aistudio.google.com 建立 API 金鑰後貼上。\n"
            "按用量計費；Google AI Pro / Ultra 訂閱額度不適用。金鑰只存在這台電腦。",
            QLineEdit.EchoMode.Password,
        )
        if not accepted or not key.strip():
            return
        try:
            saved = ai_choices.save_gemini_key(key, self._model(), profile=self.cfg.profile)
        except (ValueError, OSError) as exc:
            self.notice.setText(str(exc))
            return
        self._select("gemini", selected=saved.profile)
        self.notice.setText(
            "金鑰已保存，可回到功能頁選用。" if self.accounts_only
            else f"選好模型後，按「{self.use_button.text()}」。"
        )

    def _rename(self):
        if self.auth_runner.busy:
            return
        text, accepted = QInputDialog.getText(
            self, "帳號暱稱", "例如：個人研究、實驗室（留空可移除）"
        )
        if not accepted:
            return
        try:
            ai_choices.rename_account(self.cfg, text)
        except (ValueError, OSError) as exc:
            self.notice.setText(str(exc))
            return
        self.accounts.setItemText(self.accounts.currentIndex(), ai_choices.account_title(self.cfg))
        self.account_status.setText(ai_choices.account_title(self.cfg))

    def _affected(self):
        from paper_daily.desktop.ai_dialog import TASK_LABELS

        return "、".join("全域預設" if task == "default" else TASK_LABELS.get(task, task)
                        for task in ai_choices.dependents(self.cfg)) or "目前沒有指定功能"

    def _logout(self):
        if self.auth_runner.busy or not self.cfg.account_id:
            return
        if QMessageBox.question(
            self, "登出此帳號", f"使用範圍：{self._affected()}。\n"
            "登出後須重新登入才能執行相關 AI 功能。"
        ) != QMessageBox.StandardButton.Yes:
            return
        cfg = self.cfg
        self.runner.cancel_read()
        self._epoch += 1
        self._busy(True)

        def done(_):
            self._busy(False)
            ai_choices.remember_identity(cfg, "尚未登入")
            self._authenticated = False
            usage_cache.invalidate(cfg)
            self.account_status.setText("已登出；可新增獨立登入後重新分配給各功能。")
            self.usage.reset(cfg)
            self.usage.failed()

        def failed(reason):
            self._busy(False)
            self.notice.setText(reason)

        self.auth_runner.start("", done, failed, call=lambda _: ai_accounts.auth(cfg, "logout"))

    def _forget(self):
        if self.auth_runner.busy:
            return
        try:
            if ai_choices.dependents(self.cfg):
                self.notice.setText(f"仍用於：{self._affected()}。請先在全域或進階設定變更分配。")
                return
            if QMessageBox.question(
                self, "移除此連線", "只移除 Paperfact 的連線設定；官方登入資料會保留。\n"
                "如需登出，請先選「登出此帳號」。確定移除？"
            ) != QMessageBox.StandardButton.Yes:
                return
            ai_choices.forget_account(self.cfg)
        except (ValueError, OSError) as exc:
            self.notice.setText(str(exc))
            return
        self.runner.cancel_read()
        self._select(self._provider(self.cfg))

    def _use(self):
        if self.auth_runner.busy:
            self.notice.setText("登入操作尚未完成，請稍候。")
            return
        if self.accounts_only:
            self.accept()
            return
        if ai_choices.uses_key(self.cfg) and not (self.cfg.api_key and self._model()):
            self.notice.setText(
                "請先輸入 API 金鑰。" if not self.cfg.api_key else "請選擇要使用的模型。"
            )
            return
        try:
            if not ai_choices.uses_key(self.cfg):
                ai_accounts.command(self.cfg.backend)
            if self.task:
                llm.save_task_choices({self.task: (self.cfg, self._model())})
            else:
                ai_choices.save(self.cfg, self._model())
        except (ValueError, OSError) as exc:
            self.notice.setText(str(exc))
            return
        self.accept()

    def _advanced(self):
        if self.auth_runner.busy:
            return
        from paper_daily.desktop.ai_tasks import AITasksDialog

        cfg, model = self.cfg, self._model()
        dialog = AITasksDialog(self)
        dialog.exec()
        self._select(self._provider(cfg), selected=cfg.profile)
        self._fill_models(model)

    def _feedback(self):
        from paper_daily.desktop.feedback_dialog import FeedbackDialog

        FeedbackDialog(self).exec()

    def accept(self):
        self.runner.cancel_read()
        self._epoch += 1
        self.usage_timer.stop()
        super().accept()

    def reject(self):
        if self.auth_runner.busy:
            self.notice.setText("正在完成帳號登入，請稍候；一般資料查詢可直接關閉。")
            return
        self.runner.cancel_read()
        self._epoch += 1
        self.usage_timer.stop()
        super().reject()
