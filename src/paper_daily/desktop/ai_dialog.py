"""Choose AI profiles and route individual research tasks without editing JSON."""

from __future__ import annotations

import json
from uuid import uuid4

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from paper_daily import ai_accounts, ai_choices, ai_providers, llm
from paper_daily.desktop import fonts
from paper_daily.desktop.ask import AskRunner
from paper_daily.desktop.settings_style import apply as style_settings

TASK_LABELS = {
    "ask": "論文問答",
    "translate": "AI 翻譯",
    "dive": "深度講解",
    "list_parse": "建立清單",
    "citations": "引用分析",
    "followups": "後續研究",
    "overview": "研究脈絡",
    "compare": "論文比較",
    "slides": "論文簡報",
    "paper_highlights": "原文研究重點",
    "survey": "清單綜覽",
}
BACKEND_LABELS = {
    "none": "停用 AI",
    "auto": "自動選擇",
    "cli": "Claude CLI",
    "codex": "Codex CLI（ChatGPT 帳號）",
    "gemini": "Gemini CLI（企業版 Google 帳號）",
    "anthropic": "Anthropic API",
    "openai": "OpenAI 相容 API / 本機模型",
    "gateway": "自訂服務 API",
}


class AIStatusButton(QPushButton):
    """Compact global status; one click opens the account/model picker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(fonts.font(pixels=fonts.UI_PIXELS))
        self.setMaximumWidth(280)
        self.setAccessibleName("AI 設定：選擇帳號與模型")
        self.refresh()

    def refresh(self):
        try:
            current = llm.settings()
            brand = ai_choices.brand(current)
            label = (
                "AI 設定：尚未啟用" if current.backend == "none"
                else "全域 AI：" + (f"{brand} · " if current.model else "")
                + ai_choices.model_label(current)
            )
            self.setText(self.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, 250))
            detail = [
                "點擊選擇帳號與模型；只影響新工作。",
                "全域 AI：" + ai_choices.connection_label(current),
                f"另有 {len(llm.task_routes())} 個功能指定其他 AI；可在進階設定查看。",
            ]
            self.setToolTip("\n".join(detail))
        except (ValueError, OSError):
            self.setText("AI 設定需要修復")
            self.setToolTip("點擊開啟 AI 設定，檢查帳號與模型。")


class AISettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        style_settings(self)
        self.setWindowTitle("Paperfact · AI 帳號與連線")
        self.resize(660, 700)
        self.runner = AskRunner(self)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "新增連線 → 登入帳號或填 API 金鑰 → 選模型 → 設為預設。\n"
            "各功能也能分別選用不同連線；閱讀與手動筆記不需要 AI。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.profile_picker = QComboBox()
        layout.addWidget(self.profile_picker)
        self.presets = QComboBox()
        self.presets.addItem("快速新增連線…", None)
        for label, preset in (
            ("Claude 帳號登入", "cli"),
            ("Codex / ChatGPT 帳號登入", "codex"),
            ("Gemini API 金鑰（Google AI Studio）", "gemini_api"),
            ("Gemini CLI（企業版 Google 帳號）", "gemini"),
            ("Anthropic API 金鑰", "anthropic"),
            ("OpenAI 相容 API", "openai"),
            ("Ollama 本機模型", "local"),
            ("自訂服務 / Paperfact API", "gateway"),
        ):
            self.presets.addItem(label, preset)
        self.presets.activated.connect(self._preset)
        layout.addWidget(self.presets)
        tabs = QTabWidget()
        self.tabs = tabs
        layout.addWidget(tabs)
        connection = QWidget()
        form = QFormLayout(connection)
        self.connection_form = form
        self.name_edit = QLineEdit()
        form.addRow("連線名稱", self.name_edit)
        self.name_edit.setPlaceholderText("例如 personal-claude、work-codex、local-model")
        self.backend_picker = QComboBox()
        for backend in ("none", "auto", *llm.backend_names()):
            self.backend_picker.addItem(BACKEND_LABELS.get(backend, backend), backend)
        form.addRow("使用方式", self.backend_picker)
        self.account_picker = QComboBox()
        form.addRow("登入帳號", self.account_picker)
        self.account_help = QLabel("")
        self.account_help.setWordWrap(True)
        form.addRow(self.account_help)
        auth_bar = QWidget()
        auth_layout = QHBoxLayout(auth_bar)
        auth_layout.setContentsMargins(0, 0, 0, 0)
        self.login_button = QPushButton("登入／切換此帳號")
        self.auth_status_button = QPushButton("檢查登入")
        self.logout_button = QPushButton("登出")
        self.install_button = QPushButton("官方安裝說明")
        for button, action in (
            (self.login_button, "login"),
            (self.auth_status_button, "status"),
            (self.logout_button, "logout"),
        ):
            auth_layout.addWidget(button)
            button.clicked.connect(lambda _checked=False, action=action: self._authenticate(action))
        auth_layout.addWidget(self.install_button)
        self.install_button.clicked.connect(self._install_help)
        self.auth_bar = auth_bar
        form.addRow(auth_bar)
        self.resolved = QLabel("")
        self.resolved.setWordWrap(True)
        form.addRow("", self.resolved)
        self.model_picker = QComboBox()
        self.model_picker.setEditable(True)
        self.model_edit = self.model_picker.lineEdit()
        self.model_edit.setPlaceholderText("模型 ID；自訂服務請填寫服務提供的名稱")
        form.addRow("模型（可自行輸入）", self.model_picker)
        self.models_button = QPushButton("取得服務模型清單")
        self.models_button.clicked.connect(self._models)
        form.addRow(self.models_button)
        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("例如 http://localhost:11434/v1")
        form.addRow("API 網址", self.base_edit)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API 金鑰", self.key_edit)
        self.clear_key = QCheckBox("清除已保存的金鑰")
        form.addRow("", self.clear_key)
        self.advanced = QGroupBox("進階連線設定")
        self.advanced.setCheckable(True)
        self.advanced.setChecked(False)
        advanced_layout = QVBoxLayout(self.advanced)
        self.advanced_body = QWidget()
        advanced_layout.addWidget(self.advanced_body)
        advanced_form = QFormLayout(self.advanced_body)
        self.advanced.toggled.connect(self.advanced_body.setVisible)
        self.advanced_body.hide()
        form.addRow(self.advanced)
        self.key_env_edit = QLineEdit()
        self.key_env_edit.setPlaceholderText("選填；填寫後只讀這個環境變數")
        advanced_form.addRow("金鑰環境變數", self.key_env_edit)
        self.requires_key = QCheckBox("API 需要金鑰（本機免驗證服務可取消）")
        advanced_form.addRow("", self.requires_key)
        self.limit = QSpinBox()
        self.limit.setRange(1, 1_000_000)
        advanced_form.addRow("API 最大輸出 tokens", self.limit)
        self.token_parameter = QComboBox()
        self.token_parameter.addItems(["max_completion_tokens", "max_tokens"])
        advanced_form.addRow("相容 API token 參數", self.token_parameter)
        self.make_default = QCheckBox("設為預設 AI")
        self.make_default.setChecked(True)
        form.addRow("", self.make_default)
        note = QLabel(
            "API 金鑰保存在本機 data/llm.json（明文），或指定環境變數。\n"
            "獨立 CLI 登入憑證由官方 CLI 保存在 data/ai-accounts；請勿分享 data。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        connection_scroll = QScrollArea()
        connection_scroll.setWidgetResizable(True)
        connection_scroll.setWidget(connection)
        tabs.addTab(connection_scroll, "帳號與模型")
        routing = QWidget()
        route_form = QFormLayout(routing)
        route_form.addRow(QLabel("各功能可以選用不同 AI；跟隨預設會使用目前的預設設定檔。"))
        # The pickers list saved profiles, so with none saved they offer nothing but
        # 跟隨預設 and read as broken.
        self.route_hint = QLabel(
            "目前還沒有建立任何設定檔，所以每個功能只能跟隨預設。要讓某個功能改用"
            "別的 AI，先在最上方選「＋ 新增設定檔」建立一個並儲存，這裡就能選它。"
        )
        self.route_hint.setWordWrap(True)
        route_form.addRow(self.route_hint)
        self.routes: dict[str, QComboBox] = {}
        for task, label in TASK_LABELS.items():
            picker = QComboBox()
            route_form.addRow(label, picker)
            self.routes[task] = picker
        self.follow_default_button = QPushButton("全部功能跟隨預設")
        self.follow_default_button.clicked.connect(self._follow_default)
        route_form.addRow(self.follow_default_button)
        self.save_routes_button = QPushButton("儲存功能分配")
        self.save_routes_button.clicked.connect(self._save_routes)
        route_form.addRow(self.save_routes_button)
        routing_scroll = QScrollArea()
        routing_scroll.setWidgetResizable(True)
        routing_scroll.setWidget(routing)
        tabs.addTab(routing_scroll, "各功能使用的 AI")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.save_button = buttons.addButton("儲存", QDialogButtonBox.ButtonRole.ActionRole)
        self.test_button = buttons.addButton("儲存並測試", QDialogButtonBox.ButtonRole.ActionRole)
        self.save_button.clicked.connect(self._save)
        self.test_button.clicked.connect(self._test)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.profile_picker.currentIndexChanged.connect(self._load)
        self.backend_picker.currentIndexChanged.connect(self._backend_changed)
        self._refresh_profiles()
        self._refresh_routes()
        self._load()

    def _backend_changed(self, index=None):
        if index is not None:
            self.base_edit.clear()
            self.key_edit.clear()
            self.key_env_edit.clear()
            self.model_edit.clear()
            self.requires_key.setChecked(True)
        backend = self.backend_picker.currentData()
        cli = backend in ai_accounts.CLI_NAMES
        self.account_picker.clear()
        self.account_picker.addItem("新增獨立登入帳號", "new")
        self.account_picker.addItem("沿用本機 CLI 登入（共用）", None)
        for name in llm.profile_names():
            raw = llm.profile_fields(name)
            account = raw.get("account_id")
            if (
                raw.get("backend") == backend
                and account
                and self.account_picker.findData(account) < 0
            ):
                self.account_picker.addItem(f"沿用 {name} 的帳號", account)
        self.connection_form.setRowVisible(self.account_picker, cli)
        self.auth_bar.setVisible(cli)
        for field in (self.base_edit, self.key_edit, self.clear_key):
            self.connection_form.setRowVisible(field, not cli)
        self.advanced.setVisible(not cli)
        self.models_button.setVisible(True)
        self.account_help.setText(
            "由官方 CLI 開啟瀏覽器登入；不同獨立帳號可同時保留。模型留空使用 CLI 預設。"
            if cli
            else "填入服務的 API 金鑰與模型；本機免驗證模型可在進階設定取消需要金鑰。"
        )
        current = self.model_edit.text()
        self.model_picker.clear()
        self.model_picker.addItem("")
        for name in llm.profile_names():
            raw = llm.profile_fields(name)
            if (
                raw.get("backend") == backend
                and raw.get("model")
                and self.model_picker.findText(raw["model"]) < 0
            ):
                self.model_picker.addItem(raw["model"])
        self.model_edit.setText(current)

    def _preset(self, _index):
        preset = self.presets.currentData()
        if not preset:
            return
        self.profile_picker.setCurrentIndex(self.profile_picker.count() - 1)
        backend = "openai" if preset in ("local", "gemini_api") else preset
        self.backend_picker.setCurrentIndex(self.backend_picker.findData(backend))
        self.model_edit.clear()
        self.base_edit.setText(
            "http://localhost:11434/v1" if preset == "local"
            else ai_choices.GEMINI_API_URL if preset == "gemini_api" else ""
        )
        self.requires_key.setChecked(preset != "local")
        self.key_edit.clear()
        self.key_env_edit.clear()
        self.account_picker.setCurrentIndex(0)
        self.tabs.setCurrentIndex(0)
        self.presets.setCurrentIndex(0)
        self.name_edit.setFocus()

    def _follow_default(self):
        for picker in self.routes.values():
            picker.setCurrentIndex(0)

    def _save_routes(self):
        try:
            llm.save_routes(
                {
                    task: picker.currentData()
                    for task, picker in self.routes.items()
                    if picker.currentData()
                }
            )
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "無法儲存功能分配", str(exc))
            return False
        self.status.setText("功能分配已儲存；只影響新工作。")
        return True

    def _install_help(self):
        from paper_daily.ai_choices import HELP

        url = HELP.get(self.backend_picker.currentData(), HELP["cli"])
        QDesktopServices.openUrl(QUrl(url))

    def _models(self):
        if self.runner.busy or not self._save():
            return
        cfg = llm.settings(profile=self.name_edit.text().strip())
        self._connection_busy(True)
        self.status.setText("正在取得此連線可用的模型…")

        def fetch(_prompt):
            models, reason = ai_providers.list_models(cfg)
            return (json.dumps(models) if models else None), reason

        def done(result):
            current = self.model_edit.text()
            self.model_picker.clear()
            self.model_picker.addItems(json.loads(result))
            self.model_edit.setText(current)
            self._connection_busy(False)
            self.status.setText("已取得模型清單；選擇模型後按儲存。")

        def failed(reason):
            self._connection_busy(False)
            self.status.setText(reason)

        self.runner.start("", done, failed, call=fetch)

    def _connection_busy(self, busy):
        for widget in (
            self.tabs,
            self.profile_picker,
            self.presets,
            self.save_button,
            self.test_button,
        ):
            widget.setEnabled(not busy)

    def _authenticate(self, action):
        if self.runner.busy or not self._save():
            return
        cfg = llm.settings(profile=self.name_edit.text().strip())
        if (
            action == "logout"
            and QMessageBox.question(
                self, "登出帳號", "登出會影響沿用此帳號的所有模型連線。確定繼續？"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._connection_busy(True)
        self.status.setText(
            "請在官方 CLI 開啟的瀏覽器完成登入（最多等候 4 分鐘）…"
            if action == "login"
            else "正在檢查帳號…"
        )

        def done(text):
            self._connection_busy(False)
            self.status.setText(text)

        self.runner.start("", done, done, call=lambda _prompt: ai_accounts.auth(cfg, action))

    def _refresh_profiles(self, selected: str | None = None) -> None:
        self.profile_picker.blockSignals(True)
        self.profile_picker.clear()
        names = llm.profile_names()
        if not names:
            self.profile_picker.addItem("目前設定", "default")
        for name in names:
            self.profile_picker.addItem(name, name)
        self.profile_picker.addItem("＋ 新增設定檔", None)
        chosen = selected or llm.active_profile()
        index = self.profile_picker.findData(chosen) if chosen else 0
        self.profile_picker.setCurrentIndex(max(index, 0))
        self.profile_picker.blockSignals(False)

    def _refresh_routes(self) -> None:
        saved = llm.task_routes()
        names = llm.profile_names()
        for task, picker in self.routes.items():
            previous = picker.currentData() if picker.count() else saved.get(task)
            picker.clear()
            picker.addItem("跟隨預設", None)
            for name in names:
                picker.addItem(name, name)
            picker.setCurrentIndex(max(picker.findData(previous), 0))
        self.route_hint.setVisible(not names)

    def _load(self, _index: int = 0) -> None:
        name = self.profile_picker.currentData()
        raw = (
            llm.profile_fields(name)
            if name in llm.profile_names()
            else (llm.profile_fields() if name == "default" and not llm.profile_names() else {})
        )
        self.name_edit.setText(name or "")
        # With nothing saved the app runs on "auto" (the Claude CLI when installed);
        # showing an empty OpenAI form here meant one press of 儲存 replaced a working
        # setup with a connection that has no model.
        self.backend_picker.blockSignals(True)
        self.backend_picker.setCurrentIndex(
            max(self.backend_picker.findData(raw.get("backend", "auto")), 0)
        )
        self.backend_picker.blockSignals(False)
        self._backend_changed()
        account = raw.get("account_id") or (None if raw else "new")
        self.account_picker.setCurrentIndex(max(0, self.account_picker.findData(account)))
        if name is None:
            self.resolved.setText("")
        else:
            try:
                using = llm.describe(
                    llm.settings(profile=name if name in llm.profile_names() else None)
                )
            except (ValueError, OSError) as exc:
                using = f"設定有誤：{exc}"
            self.resolved.setText(f"目前實際使用：{using}")
        self.model_edit.setText(raw.get("model") or "")
        self.base_edit.setText(raw.get("base_url") or "")
        self.key_env_edit.setText(raw.get("api_key_env") or "")
        self.key_edit.clear()
        self.key_edit.setPlaceholderText(
            "已保存；留空保留" if raw.get("has_api_key") else "選填；也可使用環境變數"
        )
        self.clear_key.setChecked(False)
        self.requires_key.setChecked(raw.get("requires_key", True))
        self.limit.setValue(raw.get("max_tokens", llm.DEFAULT_MAX_TOKENS))
        self.token_parameter.setCurrentText(raw.get("token_parameter", "max_completion_tokens"))
        self.status.setText("")

    def _save(self) -> bool:
        name = self.name_edit.text().strip()
        key = "" if self.clear_key.isChecked() else (self.key_edit.text().strip() or None)
        backend = self.backend_picker.currentData()
        account = self.account_picker.currentData() if backend in ai_accounts.CLI_NAMES else ""
        if account == "new":
            account = uuid4().hex
        try:
            llm.save_settings(
                profile=name,
                backend=self.backend_picker.currentData(),
                model=self.model_edit.text().strip(),
                base_url=self.base_edit.text().strip(),
                api_key_env=self.key_env_edit.text().strip(),
                api_key=key,
                max_tokens=self.limit.value(),
                token_parameter=self.token_parameter.currentText(),
                requires_key=self.requires_key.isChecked(),
                isolated=True,
                account_id=account or "",
            )
            if self.make_default.isChecked():
                llm.use_profile(name, desktop=True)
            if not self._save_routes():
                return False
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "無法儲存 AI 設定", str(exc))
            return False
        self._refresh_profiles(name)
        self._refresh_routes()
        self._load()
        self.status.setText("已儲存；之後開始的 AI 工作會使用新設定。")
        return True

    def _test(self) -> None:
        if self.runner.busy or not self._save():
            return
        try:
            cfg = llm.settings(profile=self.name_edit.text().strip())
        except (ValueError, OSError) as exc:
            self.status.setText(str(exc))
            return
        self._connection_busy(True)
        self.status.setText("測試連線中…")

        def probe(_prompt):
            ok, reason = llm.probe(cfg)
            return ("連線成功" if ok else None), reason

        self.runner.start("", self._tested, self._failed, call=probe)

    def _tested(self, text: str) -> None:
        self.status.setText(text)
        self._connection_busy(False)

    def _failed(self, reason: str) -> None:
        self.status.setText(reason)
        self._connection_busy(False)

    def reject(self) -> None:
        if self.runner.busy:
            self.status.setText("連線操作進行中，請等候完成再關閉。")
            return
        super().reject()
