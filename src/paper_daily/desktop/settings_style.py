"""Settings use the same palette and control hierarchy as the research workspace."""


def apply(dialog):
    from paper_daily.desktop.main import palette

    p = palette()
    dialog.setStyleSheet(f"""
        QDialog {{ background:{p['ground']}; color:{p['ink']}; }}
        QLabel {{ color:{p['ink']}; background:transparent; }}
        QLabel[role="muted"] {{ color:{p['muted']}; }}
        QLabel[role="title"] {{ font-size:22px; font-weight:600; }}
        QGroupBox {{ background:{p['surface']}; border:1px solid {p['border']};
            border-radius:10px; margin-top:12px; padding:16px 12px 12px; font-weight:600; }}
        QGroupBox::title {{ subcontrol-origin:margin; left:14px; padding:0 5px;
            color:{p['muted']}; }}
        QScrollArea {{ border:0; background:{p['surface']}; }}
        QScrollArea > QWidget > QWidget {{ background:{p['surface']}; }}
        QPushButton {{ color:{p['ink']}; background:{p['surface']};
            border:1px solid {p['firm']}; border-radius:6px; padding:7px 12px; }}
        QPushButton:hover {{ background:{p['accentSoft']}; border-color:{p['accent']}; }}
        QPushButton:checked {{ background:{p['aiSoft']}; color:{p['ai']};
            border:2px solid {p['ai']}; font-weight:600; }}
        QPushButton[role="primary"] {{ background:{p['accent']}; color:{p['surface']};
            border-color:{p['accent']}; font-weight:600; }}
        QPushButton:disabled {{ background:{p['sunk']}; color:{p['faint']};
            border-color:{p['border']}; }}
        QComboBox, QPlainTextEdit {{ color:{p['ink']}; background:{p['surface']};
            border:1px solid {p['firm']}; border-radius:6px; padding:6px; }}
        QComboBox QAbstractItemView {{ background:{p['surface']}; color:{p['ink']};
            selection-background-color:{p['accentSoft']}; selection-color:{p['ink']}; }}
        QComboBox:disabled {{ background:{p['sunk']}; color:{p['muted']};
            border-color:{p['border']}; }}
        QProgressBar {{ background:{p['sunk']}; color:{p['ink']}; border:0;
            border-radius:5px; min-height:16px; text-align:center; }}
        QProgressBar::chunk {{ background:{p['ai']}; border-radius:5px; }}
        QCheckBox {{ color:{p['ink']}; spacing:8px; }}
    """)
