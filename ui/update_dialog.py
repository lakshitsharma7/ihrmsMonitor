"""Update Notification & Progress Dialog for iHRMS Monitor."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QFrame,
    QWidget,
)

from config.settings import APP_VERSION
from services.update_service import UpdateService, install_update_and_restart


class UpdateDialog(QDialog):
    """Modern modal/modeless dialog displaying update availability, download progress, and restart options."""

    restart_requested = Signal(str)  # installer_path

    def __init__(
        self,
        version: str,
        is_force: bool = False,
        installer_path: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._version = version
        self._is_force = is_force
        self._installer_path = installer_path

        self.setWindowTitle("iHRMS Monitor Update")
        self.setFixedSize(450, 260)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        if self._is_force:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Header Section
        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)

        icon_label = QLabel("🚀")
        icon_label.setStyleSheet("font-size: 28px; background: transparent;")
        header_layout.addWidget(icon_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_label = QLabel("New Version Available!")
        title_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #1a1a1a; background: transparent;")
        title_col.addWidget(title_label)

        version_sub = QLabel(f"Version {self._version} is ready to install (Current: v{APP_VERSION})")
        version_sub.setStyleSheet("font-size: 12px; color: #5f6368; background: transparent;")
        title_col.addWidget(version_sub)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("color: #e0e0e0; background-color: #e0e0e0; max-height: 1px;")
        layout.addWidget(line)

        # Status & Progress Area
        self.status_label = QLabel(
            "An update has been downloaded and is ready to install."
            if self._installer_path
            else "Downloading update in the background..."
        )
        self.status_label.setStyleSheet("font-size: 13px; color: #3c4043; background: transparent;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100 if self._installer_path else 0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #dadce0;
                border-radius: 6px;
                text-align: center;
                height: 18px;
                background-color: #f1f3f4;
                font-weight: 600;
                font-size: 11px;
                color: #202124;
            }
            QProgressBar::chunk {
                background-color: #1a73e8;
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.progress_bar)

        layout.addStretch()

        # Buttons Area
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.later_btn = QPushButton("Later")
        self.later_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #dadce0;
                border-radius: 6px;
                padding: 6px 16px;
                color: #3c4043;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #f8f9fa;
                border-color: #dadce0;
            }
        """)
        self.later_btn.clicked.connect(self.reject)
        if self._is_force:
            self.later_btn.setVisible(False)
        btn_layout.addWidget(self.later_btn)

        self.install_btn = QPushButton("Restart & Install" if self._installer_path else "Downloading...")
        self.install_btn.setEnabled(bool(self._installer_path))
        self.install_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a73e8;
                border: none;
                border-radius: 6px;
                padding: 6px 18px;
                color: #ffffff;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
            QPushButton:disabled {
                background-color: #dadce0;
                color: #80868b;
            }
        """)
        self.install_btn.clicked.connect(self._on_install_clicked)
        btn_layout.addWidget(self.install_btn)

        layout.addLayout(btn_layout)

    def update_progress(self, percent: int, downloaded: int, total: int) -> None:
        """Update progress bar percentage and status."""
        self.progress_bar.setValue(percent)
        if total > 0:
            mb_down = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self.status_label.setText(f"Downloading update: {mb_down:.1f} MB / {mb_total:.1f} MB ({percent}%)")
        else:
            self.status_label.setText(f"Downloading update... ({percent}%)")

    def set_download_complete(self, installer_path: str) -> None:
        """Called when download finishes."""
        self._installer_path = installer_path
        self.progress_bar.setValue(100)
        self.status_label.setText("Download complete! Ready to install and restart.")
        self.install_btn.setText("Restart & Install")
        self.install_btn.setEnabled(True)

    def set_error(self, message: str) -> None:
        """Display download or check error."""
        self.status_label.setText(f"Update error: {message}")
        self.status_label.setStyleSheet("font-size: 13px; color: #d93025; background: transparent;")
        self.install_btn.setText("Close")
        self.install_btn.setEnabled(True)
        self.install_btn.clicked.disconnect()
        self.install_btn.clicked.connect(self.reject)

    def _on_install_clicked(self) -> None:
        if self._installer_path:
            self.status_label.setText("Uploading pending activity and screenshots before update...")
            self.status_label.setStyleSheet("font-size: 13px; color: #1a73e8; background: transparent;")
            self.install_btn.setEnabled(False)
            if not self._is_force:
                self.later_btn.setEnabled(False)
            
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            
            self.restart_requested.emit(self._installer_path)
            
            # Execute apply_update with pre-update flush
            success = UpdateService().apply_update(pre_flush=True)
            if not success:
                self.status_label.setText("Could not upload pending data. Update postponed.")
                self.status_label.setStyleSheet("font-size: 13px; color: #d93025; background: transparent;")
                self.install_btn.setEnabled(True)
                self.install_btn.setText("Retry")
                if not self._is_force:
                    self.later_btn.setEnabled(True)
            else:
                self.accept()
