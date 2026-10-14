"""Release Summary and Version History Dialog for iHRMS Desktop.

Displays the current installed version, available update status, and
release notes/changelogs for the current, newer, and older application releases.
Uses existing version metadata and local changelog (version.log / RELEASE_NOTES.md).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from config.settings import APP_NAME, get_running_app_version
from services.update_service import is_newer_version
from utils.logger import get_logger

logger = get_logger(__name__)


def _locate_changelog_file() -> Optional[Path]:
    """Search for existing version history / changelog file."""
    candidates = []

    # 1. Standard project root / source directory
    root = Path(__file__).resolve().parent.parent
    candidates.append(root / "version.log")
    candidates.append(root / "RELEASE_NOTES.md")

    # 2. Frozen PyInstaller / executable directory
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / "version.log")
        candidates.append(exe_dir / "RELEASE_NOTES.md")
        if hasattr(sys, "_MEIPASS"):
            meipass = Path(sys._MEIPASS)  # type: ignore[attr-defined]
            candidates.append(meipass / "version.log")
            candidates.append(meipass / "RELEASE_NOTES.md")

    # 3. Current working directory
    cwd = Path(os.getcwd())
    candidates.append(cwd / "version.log")
    candidates.append(cwd / "RELEASE_NOTES.md")

    for p in candidates:
        if p.is_file() and p.exists():
            return p
    return None


def parse_version_log(file_path: Path) -> List[Dict[str, Any]]:
    """
    Parse version history blocks from version.log or RELEASE_NOTES.md.
    Returns list of entries with 'version', 'date', and 'summary'.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Failed to read changelog file %s: %s", file_path, exc)
        return []

    entries: List[Dict[str, Any]] = []

    if file_path.name.lower().endswith(".log"):
        # Format in version.log: blocks separated by --------------------
        blocks = re.split(r"-{30,}", text)
        for block in blocks:
            # Match line starting with "Version <ver>"
            vm = re.search(r"^\s*Version\s+(\d[\d\.]*)", block, re.M | re.I)
            if not vm:
                continue
            ver = vm.group(1).strip()
            dm = re.search(r"^\s*Date:\s*([^\n\r]+)", block, re.M | re.I)
            date_str = dm.group(1).strip() if dm else None

            # Extract content lines after Date header
            lines = block.strip().splitlines()
            content_lines = []
            capture = False
            for line in lines:
                if capture:
                    content_lines.append(line)
                elif re.match(r"^\s*Date:", line, re.I):
                    capture = True

            summary = "\n".join(content_lines).strip()
            # If no "Date:" header found, take everything after "Version ..."
            if not summary:
                content_lines = []
                capture = False
                for line in lines:
                    if capture:
                        content_lines.append(line)
                    elif re.match(r"^\s*Version\s+\d", line, re.I):
                        capture = True
                summary = "\n".join(content_lines).strip()

            entries.append({
                "version": ver,
                "date": date_str,
                "summary": summary,
            })

    elif file_path.name.lower().endswith(".md"):
        # Basic markdown release notes parser
        vm = re.search(r"v?(\d+\.\d+(?:\.\d+)?)", text)
        ver = vm.group(1) if vm else get_running_app_version()
        dm = re.search(r"Date:\s*([^\n\r]+)", text, re.I)
        date_str = dm.group(1).strip() if dm else None
        entries.append({
            "version": ver,
            "date": date_str,
            "summary": text.strip(),
        })

    return entries


def get_all_releases(
    installed_version: Optional[str] = None,
    server_version: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Assemble the authoritative, ordered list of releases (newest to oldest).
    Distinguishes installed version and confirmed newer server update.
    """
    cur_ver = str(installed_version or get_running_app_version()).lstrip("vV").strip()
    srv_ver = str(server_version or "").lstrip("vV").strip() if server_version else None

    # Check if server version is strictly newer
    has_update = bool(srv_ver and is_newer_version(srv_ver, cur_ver))

    changelog_path = _locate_changelog_file()
    raw_entries = parse_version_log(changelog_path) if changelog_path else []

    releases: List[Dict[str, Any]] = []
    seen_versions = set()

    # 1. If newer update confirmed, place at the top
    if has_update and srv_ver:
        matching = next((e for e in raw_entries if e["version"] == srv_ver), None)
        releases.append({
            "version": srv_ver,
            "date": matching.get("date") if matching else None,
            "summary": matching.get("summary") if matching else "",
            "is_installed": False,
            "is_update": True,
        })
        seen_versions.add(srv_ver)

    # 2. Add entries from changelog
    found_installed = False
    for entry in raw_entries:
        v = entry["version"]
        if v in seen_versions:
            continue
        is_inst = (v == cur_ver)
        if is_inst:
            found_installed = True
        releases.append({
            "version": v,
            "date": entry.get("date"),
            "summary": entry.get("summary", ""),
            "is_installed": is_inst,
            "is_update": False,
        })
        seen_versions.add(v)

    # 3. Ensure installed version is present even if changelog didn't list it
    if not found_installed and cur_ver not in seen_versions:
        releases.append({
            "version": cur_ver,
            "date": None,
            "summary": "",
            "is_installed": True,
            "is_update": False,
        })

    return releases


class ReleaseSummaryDialog(QDialog):
    """
    Clean, modern popup dialog displaying version history and release summaries.
    Supports viewing current installed version, newer update (if confirmed),
    and historical older releases.
    """

    def __init__(
        self,
        installed_version: Optional[str] = None,
        server_version: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._installed_version = str(installed_version or get_running_app_version()).lstrip("vV").strip()

        # Resolve server version if not explicitly supplied
        if not server_version:
            try:
                from config.api_config import ApiConfig
                info = ApiConfig().get_platform_update_info()
                if isinstance(info, dict):
                    server_version = info.get("version_code") or info.get("version")
            except Exception:
                pass

        self._server_version = str(server_version).lstrip("vV").strip() if server_version else None
        self._releases = get_all_releases(self._installed_version, self._server_version)

        self.setWindowTitle(f"{APP_NAME} - Release Summary")
        self.resize(600, 520)
        self.setMinimumSize(520, 440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._setup_ui()
        self._select_default_version()

    def _setup_ui(self) -> None:
        self.setStyleSheet("background-color: #f8fafc;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # ── Header ──────────────────────────────────────────────────────────
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        icon_label = QLabel("📋", self)
        icon_label.setStyleSheet("font-size: 24px; background: transparent;")
        header_layout.addWidget(icon_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title_lbl = QLabel("Release Summary", self)
        title_lbl.setStyleSheet("font-size: 17px; font-weight: 700; color: #0f172a; background: transparent;")
        title_col.addWidget(title_lbl)

        sub_lbl = QLabel(f"Installed Version: v{self._installed_version}", self)
        sub_lbl.setStyleSheet("font-size: 12px; color: #64748b; background: transparent;")
        title_col.addWidget(sub_lbl)

        header_layout.addLayout(title_col)
        header_layout.addStretch(1)
        layout.addLayout(header_layout)

        # ── Version Selection Bar ───────────────────────────────────────────
        selector_frame = QFrame(self)
        selector_frame.setStyleSheet(
            "QFrame { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; }"
        )
        sel_layout = QHBoxLayout(selector_frame)
        sel_layout.setContentsMargins(14, 10, 14, 10)
        sel_layout.setSpacing(10)

        sel_label = QLabel("Select Version:", selector_frame)
        sel_label.setStyleSheet("font-size: 12.5px; font-weight: 600; color: #334155; border: none; background: transparent;")
        sel_layout.addWidget(sel_label)

        self.version_combo = QComboBox(selector_frame)
        self.version_combo.setObjectName("VersionSelectorCombo")
        self.version_combo.setFixedHeight(30)
        self.version_combo.setMinimumWidth(260)
        self.version_combo.setStyleSheet(
            """
            QComboBox {
                background-color: #f8fafc;
                border: 1.5px solid #cbd5e1;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12.5px;
                font-weight: 500;
                color: #0f172a;
            }
            QComboBox:hover {
                border-color: #3b82f6;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                selection-background-color: #eff6ff;
                selection-color: #1d4ed8;
                padding: 4px;
            }
            """
        )
        for idx, rel in enumerate(self._releases):
            v_num = rel["version"]
            if rel.get("is_update"):
                label_text = f"Version {v_num}  (Update Available)"
            elif rel.get("is_installed"):
                label_text = f"Version {v_num}  (Installed)"
            else:
                label_text = f"Version {v_num}"
            self.version_combo.addItem(label_text, rel)

        self.version_combo.currentIndexChanged.connect(self._on_version_selected)
        sel_layout.addWidget(self.version_combo, 1)
        layout.addWidget(selector_frame)

        # ── Release Details Card ────────────────────────────────────────────
        self.card_frame = QFrame(self)
        self.card_frame.setStyleSheet(
            "QFrame#ReleaseDetailCard { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; }"
        )
        self.card_frame.setObjectName("ReleaseDetailCard")
        card_layout = QVBoxLayout(self.card_frame)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(10)

        # Card Title Row: Version name + Status Badge
        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        self.detail_version_label = QLabel("Version", self.card_frame)
        self.detail_version_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #0f172a; border: none; background: transparent;")
        title_row.addWidget(self.detail_version_label)

        self.detail_badge = QLabel("Installed", self.card_frame)
        self.detail_badge.setFixedHeight(22)
        title_row.addWidget(self.detail_badge)

        title_row.addStretch(1)

        self.detail_date_label = QLabel("", self.card_frame)
        self.detail_date_label.setStyleSheet("font-size: 12px; color: #64748b; font-weight: 500; border: none; background: transparent;")
        title_row.addWidget(self.detail_date_label)

        card_layout.addLayout(title_row)

        # Separator line
        sep = QFrame(self.card_frame)
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("background-color: #e2e8f0; max-height: 1px; border: none;")
        card_layout.addWidget(sep)

        # Summary text view
        self.summary_text = QTextBrowser(self.card_frame)
        self.summary_text.setObjectName("ReleaseSummaryBrowser")
        self.summary_text.setReadOnly(True)
        self.summary_text.setOpenExternalLinks(True)
        self.summary_text.setStyleSheet(
            """
            QTextBrowser#ReleaseSummaryBrowser {
                background-color: #ffffff;
                color: #334155;
                font-size: 12.5px;
                line-height: 1.5;
                border: none;
                padding: 4px;
            }
            """
        )
        card_layout.addWidget(self.summary_text, 1)

        # Fallback empty note label
        self.empty_notes_label = QLabel("Release notes are not available for this version.", self.card_frame)
        self.empty_notes_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_notes_label.setStyleSheet(
            "font-size: 13px; font-style: italic; color: #94a3b8; padding: 40px; border: none; background: transparent;"
        )
        self.empty_notes_label.setVisible(False)
        card_layout.addWidget(self.empty_notes_label, 1)

        layout.addWidget(self.card_frame, 1)

        # ── Bottom Action Controls ──────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.update_action_btn = QPushButton("🚀 Update Now", self)
        self.update_action_btn.setObjectName("ReleaseUpdateActionButton")
        self.update_action_btn.setFixedHeight(32)
        self.update_action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_action_btn.setStyleSheet(
            """
            QPushButton#ReleaseUpdateActionButton {
                background-color: #2563eb;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 4px 16px;
                font-size: 12.5px;
                font-weight: 600;
            }
            QPushButton#ReleaseUpdateActionButton:hover {
                background-color: #1d4ed8;
            }
            """
        )
        self.update_action_btn.clicked.connect(self._on_update_clicked)
        self.update_action_btn.setVisible(False)
        btn_row.addWidget(self.update_action_btn)

        btn_row.addStretch(1)

        self.close_btn = QPushButton("Close", self)
        self.close_btn.setObjectName("ReleaseSummaryCloseButton")
        self.close_btn.setFixedHeight(32)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet(
            """
            QPushButton#ReleaseSummaryCloseButton {
                background-color: #e2e8f0;
                color: #1e293b;
                border: none;
                border-radius: 6px;
                padding: 4px 18px;
                font-size: 12.5px;
                font-weight: 600;
            }
            QPushButton#ReleaseSummaryCloseButton:hover {
                background-color: #cbd5e1;
            }
            """
        )
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)

        layout.addLayout(btn_row)

    def _select_default_version(self) -> None:
        """Select the installed version by default."""
        target_idx = 0
        for i in range(self.version_combo.count()):
            rel = self.version_combo.itemData(i)
            if isinstance(rel, dict) and rel.get("is_installed"):
                target_idx = i
                break
        self.version_combo.setCurrentIndex(target_idx)
        self._on_version_selected(target_idx)

    def _on_version_selected(self, index: int) -> None:
        """Update displayed summary when user picks a different version."""
        if index < 0 or index >= len(self._releases):
            return
        rel = self.version_combo.itemData(index)
        if not isinstance(rel, dict):
            return

        v_num = rel.get("version", "")
        self.detail_version_label.setText(f"Version {v_num}")

        # Status badge
        if rel.get("is_installed"):
            self.detail_badge.setText("Installed")
            self.detail_badge.setStyleSheet(
                "background-color: #dcfce7; color: #15803d; font-size: 11px; font-weight: 700; "
                "border: 1px solid #bbf7d0; border-radius: 11px; padding: 1px 10px;"
            )
            self.detail_badge.setVisible(True)
            self.update_action_btn.setVisible(False)
        elif rel.get("is_update"):
            self.detail_badge.setText("Update Available")
            self.detail_badge.setStyleSheet(
                "background-color: #dbeafe; color: #1d4ed8; font-size: 11px; font-weight: 700; "
                "border: 1px solid #bfdbfe; border-radius: 11px; padding: 1px 10px;"
            )
            self.detail_badge.setVisible(True)
            self.update_action_btn.setVisible(True)
        else:
            self.detail_badge.setText("Previous Version")
            self.detail_badge.setStyleSheet(
                "background-color: #f1f5f9; color: #64748b; font-size: 11px; font-weight: 600; "
                "border: 1px solid #e2e8f0; border-radius: 11px; padding: 1px 8px;"
            )
            self.detail_badge.setVisible(True)
            self.update_action_btn.setVisible(False)

        # Release date (displayed only when data source provides it)
        date_val = rel.get("date")
        if date_val and str(date_val).strip():
            self.detail_date_label.setText(f"Release Date: {str(date_val).strip()}")
            self.detail_date_label.setVisible(True)
        else:
            self.detail_date_label.setText("")
            self.detail_date_label.setVisible(False)

        # Summary / Changelog notes
        summary_val = str(rel.get("summary") or "").strip()
        if summary_val:
            self.summary_text.setPlainText(summary_val)
            self.summary_text.setVisible(True)
            self.empty_notes_label.setVisible(False)
        else:
            self.summary_text.setPlainText("")
            self.summary_text.setVisible(False)
            self.empty_notes_label.setVisible(True)

    def _on_update_clicked(self) -> None:
        """Trigger background update if user clicks Update Now."""
        self.accept()
        win = self.window()
        if hasattr(win, "_check_for_updates"):
            win._check_for_updates(manual=True)
