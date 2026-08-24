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
    border: 1px solid #e0e0e0;
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #444444;
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

QTableWidget {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    gridline-color: #f0f0f0;
}

QHeaderView::section {
    background-color: #fafafa;
    color: #5f6368;
    padding: 6px;
    border: none;
    border-bottom: 1px solid #e0e0e0;
    font-weight: 600;
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

#LoginContainer {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 12px;
}

#LoginTitle {
    font-size: 22px;
    font-weight: 700;
    color: #1a73e8;
}

#LoginError {
    color: #d93025;
    font-weight: 600;
}
"""

