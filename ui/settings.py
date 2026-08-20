"""Settings page: idle threshold, start-with-system, track-window-titles."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from services.settings_service import AppSettings, SettingsService
from system import startup
from utils.logger import get_logger

logger = get_logger(__name__)


class SettingsPage(QWidget):
    """Renders and persists user preferences.

    Signal:
        settings_changed(AppSettings): emitted whenever the user changes a
            setting, so ``MainWindow`` can immediately apply it to the
            running tracker without requiring a restart.
    """

    settings_changed = Signal(object)  # AppSettings

    def __init__(self, settings_service: SettingsService, parent=None) -> None:
        super().__init__(parent)
        self._service = settings_service
        self._loading = False
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        group = QGroupBox("Tracking")
        form = QFormLayout()

        self.start_with_system_checkbox = QCheckBox("Start with system")
        self.start_with_system_checkbox.stateChanged.connect(self._on_changed)
        form.addRow(self.start_with_system_checkbox)

        self.idle_threshold_spinbox = QSpinBox()
        self.idle_threshold_spinbox.setRange(1, 120)
        self.idle_threshold_spinbox.setSuffix(" minutes")
        self.idle_threshold_spinbox.valueChanged.connect(self._on_changed)
        form.addRow("Idle threshold:", self.idle_threshold_spinbox)

        self.track_window_titles_checkbox = QCheckBox("Track window titles")
        self.track_window_titles_checkbox.stateChanged.connect(self._on_changed)
        form.addRow(self.track_window_titles_checkbox)

        group.setLayout(form)
        layout.addWidget(group)
        layout.addStretch()

    def reload(self) -> None:
        """Refresh the displayed values from the database."""
        self._loading = True
        try:
            settings = self._service.get_settings()
            self.start_with_system_checkbox.setChecked(settings.start_with_system)
            self.idle_threshold_spinbox.setValue(max(1, settings.idle_threshold // 60))
            self.track_window_titles_checkbox.setChecked(settings.track_window_titles)
        finally:
            self._loading = False

    def _on_changed(self, *_args) -> None:
        if self._loading:
            return

        idle_threshold_seconds = self.idle_threshold_spinbox.value() * 60
        start_with_system = self.start_with_system_checkbox.isChecked()
        track_window_titles = self.track_window_titles_checkbox.isChecked()

        updated: AppSettings = self._service.update_settings(
            idle_threshold=idle_threshold_seconds,
            start_with_system=start_with_system,
            track_window_titles=track_window_titles,
        )

        ok = startup.set_enabled(start_with_system)
        if not ok:
            logger.warning("Could not update OS-level start-with-system registration")

        self.settings_changed.emit(updated)
