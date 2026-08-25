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
    QComboBox,
    QLabel,
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

        screenshot_group = QGroupBox("Screenshots")
        screenshot_form = QFormLayout()

        self.interval_combobox = QComboBox()
        self.interval_combobox.addItems(["3 minutes", "5 minutes", "10 minutes", "Custom interval"])
        self.interval_combobox.currentIndexChanged.connect(self._on_changed)
        screenshot_form.addRow("Capture interval:", self.interval_combobox)

        self.custom_interval_spinbox = QSpinBox()
        self.custom_interval_spinbox.setRange(1, 1440)
        self.custom_interval_spinbox.setSuffix(" minutes")
        self.custom_interval_spinbox.valueChanged.connect(self._on_changed)
        screenshot_form.addRow("Custom interval:", self.custom_interval_spinbox)

        self.capture_on_switch_checkbox = QCheckBox("Capture on application/window/page switch")
        self.capture_on_switch_checkbox.stateChanged.connect(self._on_changed)
        screenshot_form.addRow(self.capture_on_switch_checkbox)

        # Status displays
        self.current_interval_label = QLabel("3 minutes")
        screenshot_form.addRow("Current Interval:", self.current_interval_label)

        self.capture_status_label = QLabel("Inactive")
        screenshot_form.addRow("Capture Status:", self.capture_status_label)

        screenshot_group.setLayout(screenshot_form)
        layout.addWidget(screenshot_group)

        layout.addStretch()

    def reload(self) -> None:
        """Refresh the displayed values from the database."""
        self._loading = True
        try:
            settings = self._service.get_settings()
            self.start_with_system_checkbox.setChecked(settings.start_with_system)
            self.idle_threshold_spinbox.setValue(max(1, settings.idle_threshold // 60))
            self.track_window_titles_checkbox.setChecked(settings.track_window_titles)

            # Screenshot settings
            self.capture_on_switch_checkbox.setChecked(settings.capture_on_switch)

            type_map = {"3_min": 0, "5_min": 1, "10_min": 2, "custom": 3}
            idx = type_map.get(settings.screenshot_interval_type, 0)
            self.interval_combobox.setCurrentIndex(idx)

            self.custom_interval_spinbox.setValue(max(1, settings.screenshot_custom_interval // 60))
            self.custom_interval_spinbox.setEnabled(settings.screenshot_interval_type == "custom")

            self._update_status_labels(settings)
        finally:
            self._loading = False

    def _on_changed(self, *_args) -> None:
        if self._loading:
            return

        idx = self.interval_combobox.currentIndex()
        type_rev = {0: "3_min", 1: "5_min", 2: "10_min", 3: "custom"}
        screenshot_interval_type = type_rev.get(idx, "3_min")

        self.custom_interval_spinbox.setEnabled(screenshot_interval_type == "custom")

        idle_threshold_seconds = self.idle_threshold_spinbox.value() * 60
        start_with_system = self.start_with_system_checkbox.isChecked()
        track_window_titles = self.track_window_titles_checkbox.isChecked()
        capture_on_switch = self.capture_on_switch_checkbox.isChecked()
        screenshot_custom_interval = self.custom_interval_spinbox.value() * 60

        updated: AppSettings = self._service.update_settings(
            idle_threshold=idle_threshold_seconds,
            start_with_system=start_with_system,
            track_window_titles=track_window_titles,
            screenshot_interval_type=screenshot_interval_type,
            screenshot_custom_interval=screenshot_custom_interval,
            capture_on_switch=capture_on_switch,
        )

        ok = startup.set_enabled(start_with_system)
        if not ok:
            logger.warning("Could not update OS-level start-with-system registration")

        self._update_status_labels(updated)
        self.settings_changed.emit(updated)

    def _update_status_labels(self, settings: AppSettings) -> None:
        if settings.screenshot_interval_type == "3_min":
            interval_str = "3 minutes"
        elif settings.screenshot_interval_type == "5_min":
            interval_str = "5 minutes"
        elif settings.screenshot_interval_type == "10_min":
            interval_str = "10 minutes"
        else:
            interval_str = f"{settings.screenshot_custom_interval // 60} minutes (custom)"
        self.current_interval_label.setText(interval_str)

    def update_capture_status(self, is_tracking: bool) -> None:
        status_str = "Active" if is_tracking else "Inactive"
        self.capture_status_label.setText(status_str)
