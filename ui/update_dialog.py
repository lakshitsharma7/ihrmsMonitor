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

from config.settings import APP_NAME, get_running_app_version
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
        pipeline_worker: object | None = None,
    ) -> None:
        super().__init__(parent)
        self._version = version
        self._is_force = is_force
        self._installer_path = installer_path
        self._pipeline_worker = pipeline_worker

        self.setWindowTitle(f"{APP_NAME} Update")
        self.setFixedSize(450, 260)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        if self._is_force:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._setup_ui()

        if self._pipeline_worker:
            self.attach_pipeline_worker(self._pipeline_worker)

    def attach_pipeline_worker(self, worker: object) -> None:
        """Connect UpdatePipelineWorker signals to auto-advancing UI."""
        self._pipeline_worker = worker
        worker.phase_changed.connect(self._on_phase_changed)
        worker.progress_changed.connect(self._on_progress_changed)
        worker.status_message.connect(self._on_status_message)
        worker.upload_completed.connect(self._on_upload_completed)
        worker.download_completed.connect(self._on_download_completed)
        worker.error_occurred.connect(self._on_error_occurred)

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

        srv_display = str(self._version).lstrip("vV").strip()
        cur_display = str(get_running_app_version()).lstrip("vV").strip()
        version_sub = QLabel(f"Version {srv_display} is ready to install (Current: v{cur_display})")
        version_sub.setStyleSheet("font-size: 12px; color: #5f6368; background: transparent;")
        title_col.addWidget(version_sub)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Separator
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("color: #e0e0e0; background-color: #e0e0e0; max-height: 1px;")
        layout.addWidget(line)

        # Status & Progress Area
        self.status_label = QLabel(
            "An update has been downloaded and is ready to install."
            if self._installer_path
            else "Preparing update in background...",
            self,
        )
        self.status_label.setStyleSheet("font-size: 13px; color: #3c4043; background: transparent;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar(self)
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

        self.install_btn = QPushButton("Restart & Install" if self._installer_path else "Updating...")
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

    def _on_phase_changed(self, phase: str, desc: str) -> None:
        """Handle transition between update phases."""
        self.status_label.setStyleSheet("font-size: 13px; color: #1a73e8; background: transparent;")
        self.status_label.setText(desc)
        if phase == "uploading_pending":
            self.install_btn.setEnabled(False)
            self.install_btn.setText("Uploading...")
        elif phase == "downloading":
            self.progress_bar.setValue(0)
            self.install_btn.setEnabled(False)
            self.install_btn.setText("Downloading...")
        elif phase == "installing":
            self.install_btn.setEnabled(False)
            self.install_btn.setText("Restarting...")

    def _on_progress_changed(self, percent: int, current: int, total: int) -> None:
        """Update progress bar percentage."""
        self.progress_bar.setValue(max(0, min(100, percent)))

    def _on_status_message(self, message: str) -> None:
        """Update status message text."""
        self.status_label.setText(message)

    def _on_upload_completed(self) -> None:
        """Advance immediately when pending data upload reaches 100%."""
        self.progress_bar.setValue(100)
        self.status_label.setText("Pending data upload complete. Starting download...")
        self.status_label.setStyleSheet("font-size: 13px; color: #0f9d58; background: transparent;")

    def _on_download_completed(self, installer_path: str, version: str = "", force: bool = False) -> None:
        """Called when download finishes - automatically install without waiting."""
        self._installer_path = installer_path
        self.progress_bar.setValue(100)
        self.status_label.setText("Download complete! Restarting to install update...")
        self.status_label.setStyleSheet("font-size: 13px; color: #0f9d58; font-weight: 600; background: transparent;")
        self.install_btn.setText("Restarting...")
        self.install_btn.setEnabled(False)
        if not self._is_force:
            self.later_btn.setEnabled(False)

    def _on_error_occurred(self, phase: str, message: str) -> None:
        """Display error and enable retry without hanging."""
        friendly_msg = message
        if "could not be downloaded" in message.lower():
            friendly_msg = f"Update installer for v{self._version} could not be downloaded. Please try again."
        elif "connection" in message.lower() or "timeout" in message.lower() or "offline" in message.lower():
            friendly_msg = "Network error while downloading update. Please check your connection and try again."
        self.status_label.setText(f"Update failed: {friendly_msg}")
        self.status_label.setStyleSheet("font-size: 13px; color: #d93025; background: transparent;")
        self.install_btn.setText("Retry")
        self.install_btn.setEnabled(True)
        if not self._is_force:
            self.later_btn.setEnabled(True)

    def update_progress(self, percent: int, downloaded: int, total: int) -> None:
        """Backward-compatible progress updater."""
        self.progress_bar.setValue(percent)
        if total > 0:
            mb_down = downloaded / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            self.status_label.setText(f"Downloading update: {mb_down:.1f} MB / {mb_total:.1f} MB ({percent}%)")
        else:
            self.status_label.setText(f"Downloading update... ({percent}%)")

    def set_download_complete(self, installer_path: str) -> None:
        """Backward-compatible download completed callback - auto launches install."""
        self._on_download_completed(installer_path)

    def set_error(self, message: str) -> None:
        """Backward-compatible error handler."""
        self._on_error_occurred("general", message)

    def _on_install_clicked(self) -> None:
        """Handle install or retry button click."""
        if self.install_btn.text() == "Retry":
            from config.settings import get_running_app_version
            from services.update_service import is_newer_version, get_updates_directory, UpdateService
            from services.update_state import UpdateStateManager
            from config.api_config import ApiConfig
            from services.session_service import SessionService
            from PySide6.QtCore import QTimer

            cur_ver = get_running_app_version()
            if not is_newer_version(self._version, cur_ver):
                self.status_label.setText(f"Application is already up to date (v{cur_ver}).")
                self.status_label.setStyleSheet("font-size: 13px; color: #0f9d58; font-weight: 600; background: transparent;")
                self.install_btn.setEnabled(False)
                self.progress_bar.setValue(100)
                QTimer.singleShot(1500, self.accept)
                return

            # Clean up stale partial download files before fresh attempt
            try:
                updates_dir = get_updates_directory()
                clean_v = str(self._version).lstrip("vV").strip()
                for p in list(updates_dir.glob(f"iHRMS-Desktop-Setup_v{clean_v}.*")) + list(updates_dir.glob(f"iHRMS-Desktop_v{clean_v}.*")) + list(updates_dir.glob(f"WorkpulseSetup_v{clean_v}.*")):
                    try:
                        p.unlink()
                    except Exception:
                        pass
                for p in updates_dir.glob("*.download"):
                    try:
                        p.unlink()
                    except Exception:
                        pass
            except Exception:
                pass

            # Reset cooldown in update state store for manual retry
            try:
                UpdateStateManager().reset_cooldown(self._version)
            except Exception:
                pass

            self.progress_bar.setValue(0)
            self.install_btn.setEnabled(False)
            self.status_label.setText("Retrying update...")
            self.status_label.setStyleSheet("font-size: 13px; color: #1a73e8; background: transparent;")

            base_url = ""
            try:
                base_url = ApiConfig().base_url
            except Exception:
                base_url = ""

            session = None
            try:
                session = SessionService().current_user
            except Exception:
                pass

            worker = UpdateService().start_pipeline(
                api_url=base_url,
                indo_code=session.indo_code if session else None,
                api_key=session.api_key if session else None,
                force_restart=True,
            )
            self.attach_pipeline_worker(worker)
            return

        if self._installer_path:
            self.status_label.setText("Starting update installer and restarting...")
            self.install_btn.setEnabled(False)
            parent_win = self.parent()
            if parent_win and hasattr(parent_win, "_really_quit"):
                parent_win._really_quit = True
            install_update_and_restart(self._installer_path, target_version=self._version, exit_process=True)
