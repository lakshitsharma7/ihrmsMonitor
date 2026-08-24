"""Login screen for the Activity Tracker application."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
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
from database.repository import UserRepository
from services.session_service import SessionService
from utils.logger import get_logger
from utils.security import verify_password

logger = get_logger(__name__)


class LoginWindow(QMainWindow):
    """Secure, offline login screen for Activity Tracker."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Activity Tracker - Login")
        self.resize(400, 350)
        self.main_window = None

        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Card container
        container = QWidget()
        container.setObjectName("LoginContainer")
        container.setFixedWidth(320)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(12)

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
                full_name = res_json.get("fullName") or res_json.get("username") or username
                SessionService().login(username, "User", full_name=full_name)

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
