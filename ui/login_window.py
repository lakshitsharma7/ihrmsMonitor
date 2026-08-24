"""Login screen for the Activity Tracker application."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

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

from services.session_service import SessionService
from utils.logger import get_logger


logger = get_logger(__name__)


class LoginWindow(QMainWindow):
    """Login screen for Activity Tracker."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle(
            "Activity Tracker - Login"
        )

        self.resize(
            400,
            350,
        )

        self.main_window = None

        self._build_ui()

    # ==========================================================
    # UI
    # ==========================================================

    def _build_ui(self) -> None:
        """Build the login interface."""

        central = QWidget()

        layout = QVBoxLayout(
            central
        )

        layout.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        # ------------------------------------------------------
        # Login card
        # ------------------------------------------------------

        container = QWidget()

        container.setObjectName(
            "LoginContainer"
        )

        container.setFixedWidth(
            320
        )

        container_layout = QVBoxLayout(
            container
        )

        container_layout.setContentsMargins(
            20,
            20,
            20,
            20,
        )

        container_layout.setSpacing(
            12
        )

        # ------------------------------------------------------
        # Title
        # ------------------------------------------------------

        title_label = QLabel(
            "Welcome Back"
        )

        title_label.setObjectName(
            "LoginTitle"
        )

        title_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        container_layout.addWidget(
            title_label
        )

        # ------------------------------------------------------
        # Login form
        # ------------------------------------------------------

        form = QFormLayout()

        form.setSpacing(
            8
        )

        # Username
        self.username_input = QLineEdit()

        self.username_input.setPlaceholderText(
            "Username or Email"
        )

        form.addRow(
            "Username:",
            self.username_input,
        )

        # Password
        self.password_input = QLineEdit()

        self.password_input.setPlaceholderText(
            "Password"
        )

        self.password_input.setEchoMode(
            QLineEdit.EchoMode.Password
        )

        form.addRow(
            "Password:",
            self.password_input,
        )

        container_layout.addLayout(
            form
        )

        # ------------------------------------------------------
        # Show password
        # ------------------------------------------------------

        self.show_password_checkbox = QCheckBox(
            "Show password"
        )

        self.show_password_checkbox.stateChanged.connect(
            self._toggle_password_visibility
        )

        container_layout.addWidget(
            self.show_password_checkbox
        )

        # ------------------------------------------------------
        # Error message
        # ------------------------------------------------------

        self.error_label = QLabel(
            ""
        )

        self.error_label.setObjectName(
            "LoginError"
        )

        self.error_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.error_label.setWordWrap(
            True
        )

        container_layout.addWidget(
            self.error_label
        )

        # ------------------------------------------------------
        # Login button
        # ------------------------------------------------------

        self.login_button = QPushButton(
            "Login"
        )

        self.login_button.clicked.connect(
            self._handle_login
        )

        container_layout.addWidget(
            self.login_button
        )

        layout.addWidget(
            container
        )

        self.setCentralWidget(
            central
        )

    # ==========================================================
    # RESET LOGIN WINDOW
    # ==========================================================

    def show_and_clear(self) -> None:
        """
        Clear fields and show the login window again.

        Used when the user logs out.
        """

        self.username_input.clear()

        self.password_input.clear()

        self.username_input.setEnabled(
            True
        )

        self.password_input.setEnabled(
            True
        )

        self.show_password_checkbox.setChecked(
            False
        )

        self.show_password_checkbox.setEnabled(
            True
        )

        self.login_button.setText(
            "Login"
        )

        self.login_button.setEnabled(
            True
        )

        self.error_label.clear()

        self.showNormal()

        self.raise_()

        self.activateWindow()

    # ==========================================================
    # PASSWORD VISIBILITY
    # ==========================================================

    def _toggle_password_visibility(
        self,
        state: int,
    ) -> None:
        """Toggle password visibility."""

        if state == Qt.CheckState.Checked.value:

            self.password_input.setEchoMode(
                QLineEdit.EchoMode.Normal
            )

        else:

            self.password_input.setEchoMode(
                QLineEdit.EchoMode.Password
            )

    # ==========================================================
    # LOGIN BUTTON
    # ==========================================================

    def _handle_login(self) -> None:
        """Validate input and start login."""

        self.error_label.clear()

        username = (
            self.username_input
            .text()
            .strip()
        )

        password = (
            self.password_input.text()
        )

        # ------------------------------------------------------
        # Validate fields
        # ------------------------------------------------------

        if not username or not password:

            self.error_label.setText(
                "Please enter both username and password."
            )

            return

        # ------------------------------------------------------
        # Disable controls while authenticating
        # ------------------------------------------------------

        self.login_button.setText(
            "Logging in..."
        )

        self.login_button.setEnabled(
            False
        )

        self.username_input.setEnabled(
            False
        )

        self.password_input.setEnabled(
            False
        )

        self.show_password_checkbox.setEnabled(
            False
        )

        # ------------------------------------------------------
        # Small UI delay
        # ------------------------------------------------------

        QTimer.singleShot(
            400,
            lambda: self._process_login(
                username,
                password,
            ),
        )

    # ==========================================================
    # LOGIN API
    # ==========================================================

    def _process_login(
        self,
        username: str,
        password: str,
    ) -> None:
        """Authenticate the user using the HRMS login API."""

        url = (
            "https://softdev.indovisionservices.in/"
            "ihrms84/hrms_api/ci4/api/login/login"
        )

        data = {
            "uname": username,
            "pass": password,
            "imei_number": "357327072154830",
            "device_detail": "Samsung",
        }

        try:

            # --------------------------------------------------
            # Encode request body
            # --------------------------------------------------

            encoded_data = (
                urllib.parse.urlencode(
                    data
                ).encode("utf-8")
            )

            # --------------------------------------------------
            # Create request
            # --------------------------------------------------

            request = urllib.request.Request(
                url,
                data=encoded_data,
                method="POST",
            )

            # --------------------------------------------------
            # Call authentication API
            # --------------------------------------------------

            with urllib.request.urlopen(
                request,
                timeout=10,
            ) as response:

                response_body = (
                    response
                    .read()
                    .decode("utf-8")
                )

            # --------------------------------------------------
            # Parse response
            # --------------------------------------------------

            response_json = json.loads(
                response_body
            )

            # --------------------------------------------------
            # Successful login
            # --------------------------------------------------

            if response_json.get(
                "status"
            ) == 2:

                logger.info(
                    "User %s logged in successfully via API",
                    username,
                )

                full_name = (
                    response_json.get(
                        "fullName"
                    )
                    or response_json.get(
                        "username"
                    )
                    or username
                )

                # ----------------------------------------------
                # Store local session
                # ----------------------------------------------

                SessionService().login(
                    username,
                    "User",
                    full_name=full_name,
                )

                # ----------------------------------------------
                # Open main window
                # ----------------------------------------------

                from ui.main_window import MainWindow

                self.main_window = MainWindow(
                    login_window=self
                )

                self.main_window.show()

                # ----------------------------------------------
                # Hide login window
                # ----------------------------------------------

                self.hide()

                return

            # --------------------------------------------------
            # Failed login
            # --------------------------------------------------

            message = (
                response_json.get(
                    "message"
                )
                or "Invalid username or password."
            )

            self._show_login_error(
                message
            )

        except Exception:

            logger.exception(
                "Error calling external login API"
            )

            self._show_login_error(
                "Could not connect to authentication "
                "server. Please check your network connection."
            )

    # ==========================================================
    # LOGIN ERROR
    # ==========================================================

    def _show_login_error(
        self,
        message: str = (
            "Invalid username or password."
        ),
    ) -> None:
        """Display login error and re-enable controls."""

        self.error_label.setText(
            message
        )

        self.login_button.setText(
            "Login"
        )

        self.login_button.setEnabled(
            True
        )

        self.username_input.setEnabled(
            True
        )

        self.password_input.setEnabled(
            True
        )

        self.show_password_checkbox.setEnabled(
            True
        )