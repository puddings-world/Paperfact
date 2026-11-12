"""Task-oriented workspace navigation; persistence stays in the existing handlers."""

from PySide6.QtWidgets import QLabel, QSizePolicy, QTabWidget, QVBoxLayout, QWidget


def arrange(view, layout, actions, recovery, unavailable):
    zh = view.zh
    tabs = QTabWidget()
    tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    tabs.setMinimumWidth(0)
    tabs.setAccessibleName("Workspace tasks")
    view.task_tabs = tabs
    pages = []
    for title in (
        ("跨裝置同步", "備份與還原", "進階")
        if zh
        else ("Sync devices", "Backup and restore", "Advanced")
    ):
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(8, 12, 8, 12)
        column.setSpacing(12)
        tabs.addTab(page, title)
        pages.append(column)
    sync, backup, advanced = pages

    def label(column, text):
        widget = QLabel(text)
        widget.setWordWrap(True)
        column.addWidget(widget)
        return widget

    label(sync, "在自己的電腦之間接續閱讀" if zh else "Continue reading on your other devices")
    label(
        sync,
        (
            "資料會先保存在這台電腦。設定同步後，才能在其他裝置接續使用。"
            if zh
            else (
                "Research is saved on this computer. "
                "Set up a sync connection to continue on another device."
            )
        ),
    )
    label(
        sync,
        (
            "1. 準備同步服務的連線資料。\n"
            "2. 連接並驗證這台電腦。\n"
            "3. 在另一台裝置加入同一個工作區。"
            if zh
            else (
                "1. Get your sync service connection details.\n"
                "2. Connect and verify this computer.\n"
                "3. Join the same workspace on your other device."
            )
        ),
    )
    view.sync_connection_button.setText("設定跨裝置同步…" if zh else "Set up device sync…")
    sync.addWidget(view.sync_connection_button)
    label(
        sync,
        (
            "目前需使用已部署的同步服務；這裡不會自動建立雲端帳號。尚未設定也可以正常閱讀與做筆記。"
            if zh
            else (
                "A deployed sync service is currently required; "
                "this does not create a cloud account. Reading and notes work without sync."
            )
        ),
    )
    sync.addStretch()

    label(
        backup,
        "備份是一份可攜出的研究快照，不會持續同步。"
        if zh
        else "A backup is a portable snapshot of your research; it does not keep devices in sync.",
    )
    view.inspect_button.setText(
        "從備份還原：選擇備份檔…" if zh else "Restore a backup: choose file…"
    )
    backup.addWidget(recovery)
    backup.addStretch()

    label(advanced, "本機資料與進階工具" if zh else "Local data and advanced tools")
    for widget in (view.location, view.policy):
        advanced.addWidget(widget)
    layout.removeItem(actions)
    actions.setParent(None)
    advanced.addLayout(actions)
    advanced.addWidget(view.summary)
    label(
        advanced,
        "副本工具會建立另一份資料，不會開啟跨裝置同步。"
        if zh
        else "Copy tools create separate data; they do not enable device sync.",
    )
    advanced.addWidget(view.enrollment_button)
    advanced.addWidget(view.recovery_copy_button)
    advanced.addWidget(unavailable)
    advanced.addStretch()
    while layout.count():
        layout.takeAt(0)
    layout.addWidget(tabs)
    tabs.setCurrentIndex(0)
