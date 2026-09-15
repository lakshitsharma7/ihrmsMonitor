"""Shared QSS stylesheet applied identically on Windows and macOS.

Keeping all styling in one QSS string (rather than native widget styles)
is what makes the GUI "look and behave similarly" on both platforms, per
the spec.
"""

from __future__ import annotations

APP_STYLESHEET = """
QWidget {
    background-color: #f5f6fa;
    color: #202124;
    font-family: -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}

QLabel {
    background: transparent;
}

QMainWindow {
    background-color: #f5f6fa;
}

#HeaderBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e0e0e0;
}

#AppTitle {
    font-size: 18px;
    font-weight: 600;
    color: #1a1a1a;
}

#StatusBadge {
    padding: 4px 10px;
    border-radius: 10px;
    font-weight: 600;
}

#StatusBadge[tracking="true"] {
    background-color: #e6f4ea;
    color: #137333;
}

#StatusBadge[tracking="false"] {
    background-color: #fce8e6;
    color: #a50e0e;
}

#StatusBadge[tracking="idle"] {
    background-color: #fef7e0;
    color: #b06000;
}

QGroupBox {
    background-color: #ffffff;
    border: 1px solid #dfe3eb;
    border-radius: 8px;
    margin-top: 10px;
    padding: 16px 14px 12px 14px;
    font-weight: 600;
    font-size: 13px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #374151;
    font-weight: 600;
}

QPushButton {
    background-color: #1a73e8;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #1765cc;
}

QPushButton:disabled {
    background-color: #c7c7c7;
    color: #8a8a8a;
}

QPushButton#StopButton {
    background-color: #d93025;
}

QPushButton#StopButton:hover {
    background-color: #b3261e;
}

QPushButton#SecondaryButton {
    background-color: #ffffff;
    color: #1a73e8;
    border: 1px solid #1a73e8;
}

QPushButton#SecondaryButton:hover {
    background-color: #eaf1fd;
}

QPushButton#RefreshButton {
    background-color: #ffffff;
    color: #1a73e8;
    border: 1px solid #bfdbfe;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
    font-size: 12px;
}

QPushButton#RefreshButton:hover {
    background-color: #eff6ff;
    border-color: #3b82f6;
    color: #1d4ed8;
}

QPushButton#WeeklyTimelineButton {
    background-color: #f0f7ff;
    color: #1a73e8;
    border: 1px solid #bfdbfe;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 600;
    font-size: 12px;
}

QPushButton#WeeklyTimelineButton:hover {
    background-color: #e0f2fe;
    border-color: #38bdf8;
    color: #0369a1;
}

QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #dfe3eb;
    border-radius: 6px;
    gridline-color: #f1f5f9;
}

QTableWidget::item {
    padding: 4px 10px;
    color: #1e293b;
    border: none;
}

QHeaderView {
    background-color: #f8fafc;
}

QHeaderView::section {
    background-color: #f8fafc;
    color: #475569;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    font-weight: 600;
    font-size: 12px;
}

QTableCornerButton::section {
    background-color: #f8fafc;
    border: none;
}

QTabWidget::pane {
    background-color: #f5f6fa;
    border: none;
}

QTabBar::tab {
    background-color: transparent;
    color: #5f6368;
    padding: 8px 16px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}

QTabBar::tab:selected {
    color: #1a73e8;
    border-bottom: 2px solid #1a73e8;
}

QTabBar::tab:hover:!selected {
    color: #202124;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #c9ced6;
    border-radius: 5px;
    min-height: 28px;
}

QScrollBar::handle:vertical:hover {
    background-color: #aeb5bf;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background-color: #c9ced6;
    border-radius: 5px;
    min-width: 28px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #aeb5bf;
}

QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
    width: 0;
}

QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}

QListWidget {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
}

#BigTimeLabel {
    font-size: 32px;
    font-weight: 700;
    color: #1a73e8;
}

#CurrentAppName {
    font-size: 20px;
    font-weight: 700;
}

#CurrentWindowTitle {
    color: #5f6368;
}

QLabel#StatusLabel {
    font-size: 14px;
    font-weight: 500;
    color: #3c4043;
}

QLabel#TimeValueLabel {
    font-size: 16px;
    font-weight: 700;
    color: #0F172A;
}

QLineEdit {
    background-color: #ffffff;
    border: 1px solid #c7c7c7;
    border-radius: 6px;
    padding: 8px 12px;
    color: #202124;
}

QLineEdit:focus {
    border: 2px solid #1a73e8;
    padding: 7px 11px;
}

#LoginBackground {
    background-color: #eef1f6;
}

#LoginCard {
    background-color: #ffffff;
    border: 1px solid #dfe4ec;
    border-radius: 14px;
}

#LoginHero {
    background-color: #0e2233;
    border-top-left-radius: 14px;
    border-bottom-left-radius: 14px;
}

#LoginHero QLabel {
    background: transparent;
    color: #e8eef5;
}

#LoginHero #LoginBrandName {
    font-size: 21px;
    font-weight: 700;
    color: #ffffff;
}

#LoginHero #LoginTagline {
    font-size: 12px;
    font-style: italic;
    color: #00c8f0;
}

#LoginHeroRule {
    background-color: #24394b;
    border: none;
}

#LoginHero #LoginBullet {
    font-size: 12px;
    color: #aebdcb;
}

#LoginHero #LoginHeroVersion {
    color: #ffffff;
}

#LoginFormPanel {
    background-color: #ffffff;
    border-top-right-radius: 14px;
    border-bottom-right-radius: 14px;
}

#LoginFormPanel QLabel {
    background: transparent;
}

#LoginCaption {
    font-size: 13px;
    color: #5f6368;
}

#LoginCard QLineEdit {
    background-color: #ffffff;
    border: 1px solid #d6dce4;
    border-radius: 8px;
    padding: 9px 12px;
    color: #202124;
}

#LoginCard QLineEdit:focus {
    border: 2px solid #00a0c6;
    padding: 8px 11px;
}

#LoginCard QLineEdit:disabled {
    background-color: #f5f6fa;
    color: #9aa0a6;
}

#LoginCard QLineEdit:read-only {
    background-color: #ffffff;
    border: 2px solid #00a0c6;
    padding: 8px 11px;
    color: #202124;
}

#LoginButton {
    background-color: #00a0c6;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
}

#LoginButton:hover {
    background-color: #0090b4;
}

#LoginButton:pressed {
    background-color: #007e9e;
}

#LoginButton:disabled {
    background-color: #c3ced7;
    color: #ffffff;
}

#LoginError {
    color: #d93025;
    font-weight: 600;
}

#LoginCopyright {
    color: #5f6368;
    font-size: 11px;
    background-color: #f8f9fa;
    border: 1px solid #dadce0;
    border-radius: 6px;
    padding: 8px 12px;
}
"""

