"""Login screen for the IHRMS Monitor application."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
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


class LoginWindow(QMainWindow):
    """Secure, offline login screen for IHRMS Monitor."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("iHRMS Monitor - Login")
        self.resize(400, 480)
        self.main_window = None

        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Card container
        container = QWidget()
        container.setObjectName("LoginContainer")
        container.setFixedWidth(340)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(24, 24, 24, 20)
        container_layout.setSpacing(12)

        # ── Logo ──────────────────────────────────────────────────
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_path = _asset_path(os.path.join("assets", "logo.png"))
        if os.path.isfile(logo_path):
            pixmap = QPixmap(logo_path)
            # Scale to fit nicely inside the card (max width 220, keep ratio)
            scaled = pixmap.scaledToWidth(
                220, Qt.TransformationMode.SmoothTransformation
            )
            logo_label.setPixmap(scaled)
        else:
            logo_label.setText("IndoVision")
            logo_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #00a0c6;")
        logo_label.setStyleSheet("background: transparent;")
        container_layout.addWidget(logo_label)

        # Small spacer after logo
        container_layout.addSpacing(4)

        # Title
        title_label = QLabel("Welcome Back")
        title_label.setObjectName("LoginTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(title_label)

        # Form layout
        form = QFormLayout()
        form.setSpacing(8)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username or Email")
        form.addRow("Username:", self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self.password_input)

        container_layout.addLayout(form)

        # Show/hide password option
        self.show_password_checkbox = QCheckBox("Show password")
        self.show_password_checkbox.stateChanged.connect(self._toggle_password_visibility)
        container_layout.addWidget(self.show_password_checkbox)

        # Error label
        self.error_label = QLabel("")
        self.error_label.setObjectName("LoginError")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setWordWrap(True)
        container_layout.addWidget(self.error_label)

        # Login button
        self.login_button = QPushButton("Login")
        self.login_button.clicked.connect(self._handle_login)
        container_layout.addWidget(self.login_button)

        # ── Copyright / acknowledgment text ───────────────────────
        container_layout.addSpacing(8)
        copyright_label = QLabel(
            "By using iHRMS, you acknowledge that you are\n"
            "sharing your information with iHRMS."
        )
        copyright_label.setObjectName("LoginCopyright")
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        copyright_label.setWordWrap(True)
        copyright_label.setStyleSheet(
            "color: #888888; font-size: 10px; background: transparent;"
        )
        container_layout.addWidget(copyright_label)

        layout.addWidget(container)
        self.setCentralWidget(central)

    def show_and_clear(self) -> None:
        """Clear fields and show the window again (used for logout)."""
        self.username_input.clear()
        self.password_input.clear()
        self.username_input.setEnabled(True)
        self.password_input.setEnabled(True)
        self.show_password_checkbox.setChecked(False)
        self.show_password_checkbox.setEnabled(True)
        self.login_button.setText("Login")
        self.login_button.setEnabled(True)
        self.error_label.clear()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _toggle_password_visibility(self, state: int) -> None:
        if state == Qt.CheckState.Checked.value:
            self.password_input.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

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
        self.show_password_checkbox.setEnabled(False)

        # Simulate brief latency for transition smoothness (like a native desktop processing check)
        QTimer.singleShot(400, lambda: self._process_login(username, password))

    def _process_login(self, username: str, password: str) -> None:
        import urllib.request
        import urllib.parse
        import json
        import codecs

        # ROT13 encode the user-entered password immediately before API processing
        password = codecs.encode(password, "rot_13")

        url = "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api/login/login"
        data = {
            "uname": username,
            "pass": password,
            "imei_number": "357327072154830",
            "device_detail": "Samsung"
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
                import os
                import platform
                api_url = os.environ.get("API_URL", "https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api")
                
                try:
                    os_name = platform.system().upper()
                    os_type = "MACOS" if os_name == "DARWIN" else "WINDOWS"
                    version_url = f"{api_url.rstrip('/')}/punch/check_new_version"
                    version_data = {
                        "indo_code": res_json.get("indo_code") or username,
                        "key": res_json.get("api_key") or password,
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
                import socket
                import getpass

                hostname = socket.gethostname()
                platform_name = platform.system()
                os_username = getpass.getuser()

                enroll_url = f"{api_url.rstrip('/')}/tracking/enroll_device"

                enroll_data = {
                    "indo_code": res_json.get("indo_code") or username,
                    "key": res_json.get("api_key") or password,
                    "hostname": hostname,
                    "platform": platform_name,
                    "os_username": os_username,
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

                SessionService().login(
                    username,
                    role=user_type,
                    full_name=full_name,
                    user_type=user_type,
                    tracking_permitted=tracking_permitted,
                    raw_login_data=res_json,
                )

                # Open existing main window
                from ui.main_window import MainWindow

                self.main_window = MainWindow(login_window=self)
                self.main_window.show()

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
        self.show_password_checkbox.setEnabled(True)
