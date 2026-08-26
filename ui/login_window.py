"""Login screen for the iHRMS Monitor application."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from database.database import get_session
from services.session_service import SessionService
from utils.logger import get_logger

logger = get_logger(__name__)

# Selling points shown on the dark hero panel: (icon name, text).
HERO_BULLETS = (
    ("monitor", "Automatic app & window tracking"),
    ("chart", "Live productivity and idle insights"),
    ("shield", "Secure, role-based access"),
)


def _asset_path(relative: str) -> str:
    """Return the absolute path to a bundled asset.

    Works both when running from source (``python app.py``) and from a
    PyInstaller single-file executable (where files are extracted to a
    temporary ``_MEIXXXXXX`` directory).
    """
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _load_icon(name: str) -> QIcon:
    """Load an icon from ``assets/icons``.

    The SVG is preferred; the pre-rendered PNG is a fallback for
    environments where the Qt SVG image plugin is unavailable.
    """
    for extension in (".svg", ".png"):
        path = _asset_path(os.path.join("assets", "icons", name + extension))
        if os.path.isfile(path):
            icon = QIcon(path)
            if not icon.isNull():
                return icon
    return QIcon()


def _load_emoji_icon(emoji_text: str) -> QIcon:
    """Create a QIcon from a unicode emoji character drawn on a transparent QPixmap."""
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    font = QFont("Segoe UI Emoji", 14)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, emoji_text)
    painter.end()
    return QIcon(pixmap)


def _icon_label(name: str, size: int) -> QLabel:
    """Return a fixed-size ``QLabel`` displaying the named icon."""
    label = QLabel()
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pixmap = _load_icon(name).pixmap(QSize(size, size))
    if not pixmap.isNull():
        label.setPixmap(pixmap)
    return label


class LoginWindow(QMainWindow):
    """Secure, offline login screen for iHRMS Monitor."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("iHRMS Monitor - Login")
        self.setMinimumSize(760, 520)
        self.resize(860, 560)
        self.main_window = None

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("LoginBackground")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Card split into a dark hero panel and the white form panel
        card = QFrame()
        card.setObjectName("LoginCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setFixedSize(780, 470)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(self._build_hero_panel())
        card_layout.addWidget(self._build_form_panel())

        layout.addWidget(card)
        self.setCentralWidget(central)

    def _build_hero_panel(self) -> QWidget:
        """Dark branded panel: app mark, tagline and three bullet points."""
        hero = QFrame()
        hero.setObjectName("LoginHero")
        hero.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hero.setFixedWidth(320)

        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(32, 40, 32, 32)
        hero_layout.setSpacing(0)

        # Hero illustration / App Icon (big iHRMS star logo)
        icon_label = QLabel()
        icon_label.setFixedSize(64, 64)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("background-color: #ffffff; border-radius: 8px; padding: 4px;")
        logo_path = _asset_path(os.path.join("assets", "ihrms_icon.png"))
        if os.path.isfile(logo_path):
            pixmap = QPixmap(logo_path)
            icon_label.setPixmap(
                pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            icon_label.setText("iHRMS")
            icon_label.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        hero_layout.addWidget(icon_label)
        hero_layout.addSpacing(18)

        brand_name = QLabel("iHRMS Monitor")
        brand_name.setObjectName("LoginBrandName")
        hero_layout.addWidget(brand_name)

        hero_layout.addSpacing(6)
        tagline = QLabel("Smart workforce activity monitoring")
        tagline.setObjectName("LoginTagline")
        hero_layout.addWidget(tagline)

        hero_layout.addSpacing(26)
        rule = QFrame()
        rule.setObjectName("LoginHeroRule")
        rule.setFixedHeight(1)
        hero_layout.addWidget(rule)
        hero_layout.addSpacing(24)

        for icon_name, text in HERO_BULLETS:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            row.addWidget(_icon_label(icon_name, 18), 0, Qt.AlignmentFlag.AlignTop)
            bullet = QLabel(text)
            bullet.setObjectName("LoginBullet")
            bullet.setWordWrap(True)
            row.addWidget(bullet, 1)
            hero_layout.addLayout(row)
            hero_layout.addSpacing(18)

        hero_layout.addStretch(1)
        return hero

    def _build_form_panel(self) -> QWidget:
        """White panel holding the brand logo and the credential form."""
        panel = QFrame()
        panel.setObjectName("LoginFormPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(46, 40, 46, 26)
        panel_layout.setSpacing(0)

        # ── Brand logo (Centered) ──────────────────────────────────
        logo_label = QLabel()
        logo_label.setObjectName("LoginLogo")
        logo_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        logo_path = _asset_path(os.path.join("assets", "logo.png"))
        if os.path.isfile(logo_path):
            pixmap = QPixmap(logo_path)
            logo_label.setPixmap(
                pixmap.scaledToWidth(190, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            logo_label.setText("indoVISION")
        panel_layout.addWidget(logo_label)

        panel_layout.addSpacing(12)
        caption = QLabel("Sign in to continue")
        caption.setObjectName("LoginCaption")
        panel_layout.addWidget(caption)

        panel_layout.addSpacing(26)

        # ── Username ──────────────────────────────────────────────
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username or Email")
        self.username_input.setMinimumHeight(42)
        self.username_input.addAction(
            _load_icon("user"), QLineEdit.ActionPosition.LeadingPosition
        )
        panel_layout.addWidget(self.username_input)

        panel_layout.addSpacing(12)

        # ── Password (eye icon replaces the old "Show password" box) ──
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setMinimumHeight(42)
        self.password_input.addAction(
            _load_icon("lock"), QLineEdit.ActionPosition.LeadingPosition
        )

        self._eye_icon = _load_icon("eye")
        self._eye_off_icon = _load_icon("eye-off")
        self.toggle_password_action = self.password_input.addAction(
            self._eye_icon, QLineEdit.ActionPosition.TrailingPosition
        )
        self.toggle_password_action.setToolTip("Show password")
        self.toggle_password_action.triggered.connect(self._toggle_password_visibility)
        panel_layout.addWidget(self.password_input)

        # Error label
        panel_layout.addSpacing(12)
        self.error_label = QLabel("")
        self.error_label.setObjectName("LoginError")
        self.error_label.setWordWrap(True)
        panel_layout.addWidget(self.error_label)

        # Login button
        panel_layout.addSpacing(10)
        self.login_button = QPushButton("Login")
        self.login_button.setObjectName("LoginButton")
        self.login_button.setMinimumHeight(44)
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self._handle_login)
        panel_layout.addWidget(self.login_button)

        panel_layout.addStretch(1)

        # ── Copyright / acknowledgment text ───────────────────────
        copyright_label = QLabel(
            "By logging in to iHRMS Monitor, you acknowledge that you are "
            "sharing your activity information with iHRMS Monitor."
        )
        copyright_label.setObjectName("LoginCopyright")
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copyright_label.setWordWrap(True)
        panel_layout.addWidget(copyright_label)

        return panel

    def show_and_clear(self) -> None:
        """Clear fields and show the window again (used for logout)."""
        self.username_input.clear()
        self.password_input.clear()
        self.username_input.setEnabled(True)
        self.password_input.setEnabled(True)
        self._set_password_visible(False)
        self.toggle_password_action.setEnabled(True)
        self.login_button.setText("Login")
        self.login_button.setEnabled(True)
        self.error_label.clear()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _set_password_visible(self, visible: bool) -> None:
        """Apply the masked/plain state and keep the eye icon in sync."""
        self.password_input.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.toggle_password_action.setIcon(
            self._eye_off_icon if visible else self._eye_icon
        )
        self.toggle_password_action.setToolTip(
            "Hide password" if visible else "Show password"
        )

    def _toggle_password_visibility(self, *_args: object) -> None:
        """Flip the password field between masked and plain text."""
        self._set_password_visible(
            self.password_input.echoMode() == QLineEdit.EchoMode.Password
        )

    def _handle_login(self) -> None:
        self.error_label.clear()
        username = self.username_input.text().strip()
        password = self.password_input.text()

        # Simple validation
        if not username or not password:
            self.error_label.setText("Please enter both username and password.")
            return

        # Show loading/processing state
        self.login_button.setText("Logging in...")
        self.login_button.setEnabled(False)
        self.username_input.setEnabled(False)
        self.password_input.setEnabled(False)
        self.toggle_password_action.setEnabled(False)

        # Simulate brief latency for transition smoothness (like a native desktop processing check)
        QTimer.singleShot(400, lambda: self._process_login(username, password))

    def _process_login(self, username: str, password: str) -> None:
        import urllib.request
        import urllib.parse
        import json
        import codecs

        # ROT13 encode the user-entered password immediately before API processing
        password = codecs.encode(password, "rot_13")

        from config.api_config import ApiConfig, ApiConfigError
        from utils.device import get_device_info

        # The API base URL is resolved from the fixed Company Code, so it is
        # never hardcoded here.
        api_config = ApiConfig()

        try:
            api_url = api_config.base_url
        except ApiConfigError as config_err:
            logger.error("Could not resolve API configuration: %s", config_err)
            self._show_login_error(
                "Could not reach the configuration service. "
                "Please check your connection and try again."
            )
            return

        device_info = get_device_info()

        url = f"{api_url}/login/login"
        data = {
            "uname": username,
            "pass": password,
            "imei_number": device_info["device_identifier"],
            "device_detail": device_info["device_detail"],
        }

        try:
            encoded_data = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(url, data=encoded_data, method="POST")
            
            with urllib.request.urlopen(req, timeout=10) as response:
                res_body = response.read().decode("utf-8")
                
            res_json = json.loads(res_body)
            
            if res_json.get("status") == 2:
                logger.info("User %s logged in successfully via API", username)

                # ----------------------------------------------
                # Check New Version API
                # ----------------------------------------------
                import platform

                # Auth values come from the login response, not from the
                # credentials the user typed. The encoded-password fallback
                # is the pre-existing behaviour for responses that omit
                # api_key; it is never a hardcoded value.
                indo_code = res_json.get("indo_code") or username
                api_key = res_json.get("api_key")

                if not api_key:
                    logger.warning(
                        "Login response contained no api_key; "
                        "falling back to the encoded password as key."
                    )
                    api_key = password
                
                try:
                    os_name = platform.system().upper()
                    os_type = "MACOS" if os_name == "DARWIN" else "WINDOWS"
                    version_url = f"{api_url}/punch/check_new_version"
                    version_data = {
                        "indo_code": indo_code,
                        "key": api_key,
                        "os_type": os_type
                    }
                    encoded_version_data = urllib.parse.urlencode(version_data).encode("utf-8")
                    version_req = urllib.request.Request(
                        version_url,
                        data=encoded_version_data,
                        method="POST"
                    )
                    with urllib.request.urlopen(version_req, timeout=10) as version_response:
                        version_body = version_response.read().decode("utf-8")
                    version_json = json.loads(version_body)
                    logger.info(
                        "Check version response: status=%s, version_code=%s, force_update=%s",
                        version_json.get("status"),
                        version_json.get("version_code"),
                        version_json.get("force_update")
                    )
                except Exception as version_err:
                    logger.warning("Check version API call failed: %s", version_err)

                # ----------------------------------------------
                # Device Enrollment
                # ----------------------------------------------
                enroll_url = f"{api_url}/tracking/enroll_device"

                enroll_data = {
                    "indo_code": indo_code,
                    "key": api_key,
                    "hostname": device_info["hostname"],
                    "platform": device_info["platform"],
                    "os_username": device_info["os_username"],
                }

                try:
                    encoded_enroll_data = urllib.parse.urlencode(enroll_data).encode("utf-8")
                    enroll_request = urllib.request.Request(
                        enroll_url,
                        data=encoded_enroll_data,
                        method="POST"
                    )
                    
                    with urllib.request.urlopen(enroll_request, timeout=10) as enroll_response:
                        enroll_response_body = enroll_response.read().decode("utf-8")
                        
                    enroll_json = json.loads(enroll_response_body)
                    device_token = enroll_json.get("device_token") or enroll_json.get("data", {}).get("device_token")
                    if not device_token:
                        raise ValueError("No device_token returned by enroll_device")
                        
                    SessionService().device_token = device_token
                    
                except Exception as enroll_err:
                    logger.exception("Device enrollment failed: %s", enroll_err)
                    self._show_login_error("Device enrollment failed. Please check backend server status.")
                    return

                full_name = res_json.get("fullName") or res_json.get("username") or username
                user_type = res_json.get("user_type") or "User"
                role_lower = str(user_type).strip().lower()
                tracking_permitted = role_lower not in ("admin", "administrator", "superadmin")

                employee_id = (
                    res_json.get("employee_id")
                    or res_json.get("emp_id")
                    or res_json.get("fk_employee_id")
                )

                SessionService().login(
                    username,
                    role=user_type,
                    full_name=full_name,
                    user_type=user_type,
                    tracking_permitted=tracking_permitted,
                    indo_code=indo_code,
                    api_key=api_key,
                    employee_id=(
                        str(employee_id)
                        if employee_id is not None
                        else None
                    ),
                    raw_login_data=res_json,
                )

                # Open existing main window
                from ui.main_window import MainWindow

                self.main_window = MainWindow(login_window=self)
                self.main_window.hide()
                if hasattr(self.main_window, "tray") and self.main_window.tray:
                    self.main_window.tray.show_message(
                        "iHRMS Monitor",
                        "iHRMS Monitor is running in the background."
                    )

                # Hide login window
                self.hide()
            else:
                msg = res_json.get("message") or "Invalid username or password."
                self._show_login_error(msg)
                
        except Exception:
            logger.exception("Error calling external login API")
            self._show_login_error("Could not connect to authentication server. Please check your network connection.")

    def _show_login_error(self, message: str = "Invalid username or password.") -> None:
        self.error_label.setText(message)
        self.login_button.setText("Login")
        self.login_button.setEnabled(True)
        self.username_input.setEnabled(True)
        self.password_input.setEnabled(True)
        self.toggle_password_action.setEnabled(True)
