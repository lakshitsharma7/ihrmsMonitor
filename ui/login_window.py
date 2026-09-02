"""Login screen for the iHRMS Monitor application."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QFont
from PySide6.QtWidgets import (
    QCheckBox,
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


CONSENT_REQUIRED_MESSAGE = "Please accept the consent to continue."

CONSENT_TEXT = (
    "By logging in to iHRMS Monitor, you acknowledge that you are "
    "sharing your activity information with iHRMS Monitor."
)

# Hero logo tile on the login screen.
LOGO_BOX_SIZE = 96
LOGO_BOX_PADDING = 4


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
        self.setMinimumSize(760, 600)
        self.resize(860, 640)
        
        # Set window icon explicitly
        from PySide6.QtGui import QIcon
        import os
        import sys
        if getattr(sys, "frozen", False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(base_dir, "assets", "ihrms-logo-icon.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.main_window = None
        self.login_step = 1

        # Company Code starts blank and nothing is verified yet.
        self._verified_company_code = None

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
        card.setFixedSize(780, 545)
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
        icon_label.setFixedSize(LOGO_BOX_SIZE, LOGO_BOX_SIZE)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(
            "background-color: #ffffff; border-radius: 8px;"
            f" padding: {LOGO_BOX_PADDING}px;"
        )
        logo_path = _asset_path(os.path.join("assets", "ihrms_icon.png"))
        if os.path.isfile(logo_path):
            pixmap = QPixmap(logo_path)

            # Fit inside the label's content box (the stylesheet padding is
            # not part of it), and render at the screen's device pixel ratio.
            # Without the ratio the pixmap is built at logical size and then
            # stretched by the compositor on scaled displays, which is what
            # made the logo look blurry.
            inner = LOGO_BOX_SIZE - 2 * LOGO_BOX_PADDING

            ratio = self.devicePixelRatioF() or 1.0

            scaled_logo = pixmap.scaled(
                round(inner * ratio),
                round(inner * ratio),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            scaled_logo.setDevicePixelRatio(ratio)

            icon_label.setPixmap(scaled_logo)
        else:
            icon_label.setText("iHRMS")
            icon_label.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        hero_layout.addWidget(
            icon_label,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        hero_layout.addSpacing(18)

        brand_name = QLabel("iHRMS Monitor")
        brand_name.setObjectName("LoginBrandName")
        brand_name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        hero_layout.addWidget(brand_name)

        hero_layout.addSpacing(6)
        tagline = QLabel("Smart workforce activity monitoring")
        tagline.setObjectName("LoginTagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignHCenter)
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

        # Application version display on hero panel
        from config.settings import APP_VERSION
        hero_version = QLabel(f"Version {APP_VERSION}")
        hero_version.setObjectName("LoginHeroVersion")
        hero_version.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        hero_version.setStyleSheet("color: rgba(255, 255, 255, 0.45); font-size: 11px; font-weight: 500;")
        hero_layout.addWidget(hero_version)

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
        self.brand_logo_label = QLabel()
        self.brand_logo_label.setObjectName("LoginLogo")
        self.brand_logo_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self._set_default_brand_logo()
        panel_layout.addWidget(self.brand_logo_label)

        panel_layout.addSpacing(12)
        caption = QLabel("Sign in to continue")
        caption.setObjectName("LoginCaption")
        panel_layout.addWidget(caption)

        panel_layout.addSpacing(26)

        # ── Company Code ──────────────────────────────────────────
        self.company_code_input = QLineEdit()
        self.company_code_input.setPlaceholderText("Company Code")
        self.company_code_input.setMinimumHeight(42)
        # Prevent autofill
        self.company_code_input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.company_code_input.addAction(
            _load_icon("shield"), QLineEdit.ActionPosition.LeadingPosition
        )
        panel_layout.addWidget(self.company_code_input)

        # ── Verified company details (from the verification API) ───
        # Hidden until a company code is verified, and cleared again the
        # moment the code changes, so one company's details can never be
        # shown alongside another company's code.
        self.company_details = QWidget()
        self.company_details.setObjectName("CompanyDetails")
        self.company_details.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )

        details_layout = QHBoxLayout(self.company_details)
        details_layout.setContentsMargins(10, 8, 10, 8)
        details_layout.setSpacing(10)

        self.company_logo_label = QLabel()
        self.company_logo_label.setFixedSize(30, 30)
        self.company_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        details_layout.addWidget(self.company_logo_label)

        self.company_name_label = QLabel()
        self.company_name_label.setObjectName("CompanyDetailsText")
        self.company_name_label.setWordWrap(True)
        details_layout.addWidget(self.company_name_label, 1)

        self.company_details.setVisible(False)
        panel_layout.addWidget(self.company_details)

        # Container for the step 2 credential fields
        self.credentials_container = QWidget()
        self.credentials_container.setObjectName("CredentialsContainer")
        self.credentials_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        credentials_layout = QVBoxLayout(self.credentials_container)
        credentials_layout.setContentsMargins(0, 0, 0, 0)
        credentials_layout.setSpacing(12)

        # ── Username (Employee ID / Username / Email) ──────────────────────────────────────────────
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Employee ID / Username / Email")
        self.username_input.setMinimumHeight(42)
        # Prevent autofill
        self.username_input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.username_input.addAction(
            _load_icon("user"), QLineEdit.ActionPosition.LeadingPosition
        )
        credentials_layout.addWidget(self.username_input)

        # ── Password (eye icon replaces the old "Show password" box) ──
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setMinimumHeight(42)
        # Prevent autofill
        self.password_input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
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
        credentials_layout.addWidget(self.password_input)

        panel_layout.addWidget(self.credentials_container)
        panel_layout.addSpacing(12)

        self.login_step = 1
        self.credentials_container.setVisible(False)

        # Ensure all input fields are always blank on load
        self.company_code_input.clear()
        self.username_input.clear()
        self.password_input.clear()

        # Connect text changes of company code to reset step
        self.company_code_input.textChanged.connect(self._on_company_code_changed)

        # Error label
        self.error_label = QLabel("")
        self.error_label.setObjectName("LoginError")
        self.error_label.setWordWrap(True)
        panel_layout.addWidget(self.error_label)

        # ── Consent (must be accepted before logging in) ──────────
        panel_layout.addSpacing(14)

        consent_row = QWidget()
        consent_row.setObjectName("LoginConsentRow")
        # The panel behind it is white; without this the row inherits the
        # global window background and shows a grey patch.
        consent_row.setStyleSheet(
            # The box outline lives on the row so the checkbox sits inside it.
            "#LoginConsentRow {"
            " background-color: #f8f9fa;"
            " border: 1px solid #dadce0;"
            " border-radius: 6px; }"
            # The text keeps the notice's appearance without a second border.
            "#LoginConsentText {"
            " background: transparent;"
            " border: none;"
            " color: #5f6368;"
            " font-size: 11px; }"
        )

        consent_layout = QHBoxLayout(consent_row)
        consent_layout.setContentsMargins(12, 8, 12, 8)
        consent_layout.setSpacing(10)

        self.consent_checkbox = QCheckBox()
        self.consent_checkbox.setObjectName("LoginConsentCheckbox")
        self.consent_checkbox.setChecked(False)
        self.consent_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.consent_checkbox.setToolTip("Required to continue")

        # The global QWidget background rule puts QCheckBox into stylesheet
        # rendering, which drops the native tick, so the indicator is styled
        # explicitly. The path is absolute so it also resolves when frozen.
        check_icon = _asset_path(
            os.path.join("assets", "icons", "check.svg")
        ).replace("\\", "/")

        self.consent_checkbox.setStyleSheet(
            "#LoginConsentCheckbox { background: transparent; }"
            "#LoginConsentCheckbox::indicator {"
            " width: 18px; height: 18px;"
            " border: 1px solid #c3ced7;"
            " border-radius: 4px;"
            " background-color: #ffffff; }"
            "#LoginConsentCheckbox::indicator:hover {"
            " border-color: #00a0c6; }"
            "#LoginConsentCheckbox::indicator:checked {"
            " background-color: #00a0c6;"
            " border-color: #00a0c6;"
            f" image: url({check_icon}); }}"
        )
        consent_layout.addWidget(
            self.consent_checkbox,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )

        consent_text = QLabel(CONSENT_TEXT)
        consent_text.setObjectName("LoginConsentText")
        consent_text.setWordWrap(True)
        consent_layout.addWidget(consent_text, 1)

        # Consent only becomes relevant once a company has been verified,
        # so the row stays hidden until then.
        self.consent_row = consent_row
        self.consent_row.setVisible(False)

        panel_layout.addWidget(consent_row)

        # Clear the validation message as soon as the box is ticked.
        self.consent_checkbox.toggled.connect(self._on_consent_toggled)

        # Login button
        panel_layout.addSpacing(10)
        self.login_button = QPushButton("Verify Company" if self.login_step == 1 else "Login")
        self.login_button.setObjectName("LoginButton")
        self.login_button.setMinimumHeight(44)
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self._handle_login)
        panel_layout.addWidget(self.login_button)

        panel_layout.addStretch(1)

        # Footer version & update status row on form panel
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 8, 0, 0)

        from config.settings import APP_VERSION
        self.version_label = QLabel(f"Version {APP_VERSION}")
        self.version_label.setObjectName("LoginVersion")
        self.version_label.setStyleSheet("color: #9aa0a6; font-size: 11px; font-weight: 500;")
        footer_layout.addWidget(self.version_label)
        footer_layout.addStretch()

        self.update_status_label = QLabel("")
        self.update_status_label.setObjectName("LoginUpdateStatus")
        self.update_status_label.setStyleSheet("color: #1a73e8; font-size: 11px; font-weight: 600; text-decoration: underline;")
        self.update_status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_status_label.setVisible(False)
        self.update_status_label.mousePressEvent = self._on_update_status_clicked
        footer_layout.addWidget(self.update_status_label)

        panel_layout.addLayout(footer_layout)

        return panel

    def show_and_clear(self) -> None:
        """Clear fields and show the window again (used for logout)."""
        self.login_step = 1
        self.credentials_container.setVisible(False)
        self.login_button.setText("Verify Company")
        
        # Drop the verified company so the next login starts from scratch.
        self._reset_company_context()

        self.company_code_input.clear()
        self.username_input.clear()
        self.password_input.clear()
        self.consent_checkbox.setChecked(False)
        self.company_code_input.setEnabled(True)
        self.username_input.setEnabled(True)
        self.password_input.setEnabled(True)
        self._set_password_visible(False)
        self.toggle_password_action.setEnabled(True)
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

    def _on_update_status_clicked(self, event: object) -> None:
        """Open update dialog when clicking update status on login screen."""
        try:
            from services.update_service import UpdateService
            service = UpdateService()
            if service.available_version:
                from ui.update_dialog import UpdateDialog
                dialog = UpdateDialog(
                    version=service.available_version,
                    is_force=service.is_force_update,
                    installer_path=service._downloaded_installer,
                    parent=self,
                )
                dialog.exec()
        except Exception as err:
            logger.warning("Could not open update dialog from login screen: %s", err)

    def _on_consent_toggled(self, checked: bool) -> None:
        """Clear the consent validation message once the box is ticked."""

        if checked and self.error_label.text() == CONSENT_REQUIRED_MESSAGE:
            self.error_label.clear()

    def _set_default_brand_logo(self) -> None:
        """Set the default Indovision brand logo above 'Sign in to continue'."""
        if not hasattr(self, "brand_logo_label"):
            return
        logo_path = _asset_path(
            os.path.join("assets", "hrms-logo-01-04-2026-10-31-18-1302918294.jpg")
        )
        if os.path.isfile(logo_path):
            pixmap = QPixmap(logo_path)
            self.brand_logo_label.setPixmap(
                pixmap.scaledToWidth(190, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self.brand_logo_label.setText("indoVISION")

    def _reset_company_context(self) -> None:
        """
        Forget the verified company and everything entered for it.

        Called whenever the Company Code changes so no part of the previous
        company - its base URL, its details, or credentials typed for it -
        can be carried into the next company's login.
        """

        from config.api_config import ApiConfig

        ApiConfig().reset()

        self._verified_company_code = None

        self.login_step = 1
        self.credentials_container.setVisible(False)
        self.login_button.setText("Verify Company")

        # Credentials belong to the company they were typed for.
        self.username_input.clear()
        self.password_input.clear()
        self._set_password_visible(False)

        self.company_details.setVisible(False)
        self.company_logo_label.clear()
        self.company_name_label.clear()

        self.consent_row.setVisible(False)
        self.consent_checkbox.setChecked(False)

        # Reset main brand logo back to the default fallback logo
        self._set_default_brand_logo()

    def _on_company_code_changed(self) -> None:
        """Any edit to the Company Code invalidates a previous verification."""

        if self.login_step == 2 or self._verified_company_code:
            self._reset_company_context()
            self.error_label.clear()

    def _show_company_details(self) -> None:
        """Display the verified company's details returned by the API."""

        from config.api_config import ApiConfig

        api_config = ApiConfig()

        details = api_config.details

        company_id = api_config.company_id

        parts = []

        if company_id:
            parts.append(f"Company ID: {company_id}")

        if api_config.company_code:
            parts.append(f"Code: {api_config.company_code}")

        self.company_name_label.setText("Verified  -  " + "  |  ".join(parts))

        # The logo is part of the details this company returned; it is
        # optional, so a failure to fetch it must not block login.
        self.company_logo_label.clear()

        logo_url = details.get("logo_url") or api_config.logo_url

        if logo_url:
            try:
                import requests

                headers = {"User-Agent": "iHRMS-Monitor/1.0"}
                response = requests.get(str(logo_url), headers=headers, timeout=6)
                response.raise_for_status()

                logo = QPixmap()

                if logo.loadFromData(response.content) and not logo.isNull():
                    ratio = self.devicePixelRatioF() or 1.0

                    # 1. Update badge logo
                    scaled = logo.scaled(
                        round(30 * ratio),
                        round(30 * ratio),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )

                    scaled.setDevicePixelRatio(ratio)

                    self.company_logo_label.setPixmap(scaled)

                    # 2. Update the dynamic company logo above "Sign in to continue"
                    brand_scaled = logo.scaled(
                        190,
                        60,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self.brand_logo_label.setPixmap(brand_scaled)
                    logger.info("Dynamic company logo displayed successfully from %s", logo_url)
                else:
                    self._set_default_brand_logo()

            except Exception:  # noqa: BLE001
                logger.warning(
                    "Could not load the verified company's logo; keeping fallback",
                    exc_info=True,
                )
                self._set_default_brand_logo()
        else:
            self._set_default_brand_logo()

        self.company_details.setVisible(True)

    def _process_company_verification(self, company_code: str) -> None:
        from config.api_config import ApiConfig, ApiConfigError
        api_config = ApiConfig()

        try:
            api_config.load(company_code=company_code, force=True)

            # Only now is this company the active context.
            self._verified_company_code = company_code

            self._show_company_details()

            # Consent applies to signing in, which is now possible.
            self.consent_row.setVisible(True)

            self.login_step = 2
            self.credentials_container.setVisible(True)
            self.username_input.clear()
            self.password_input.clear()
            self.login_button.setText("Login")
            self.login_button.setEnabled(True)
            self.company_code_input.setEnabled(True)
            self.error_label.clear()

            self.username_input.setFocus()

        except ApiConfigError as config_err:
            logger.error("Company verification failed: %s", config_err)

            # Leave no trace of any previously verified company.
            self._reset_company_context()

            self.login_button.setEnabled(True)
            self.company_code_input.setEnabled(True)

            # Surface the message the verification API itself returned.
            self.error_label.setText(str(config_err))

    def _handle_login(self) -> None:
        self.error_label.clear()
        company_code = self.company_code_input.text().strip()

        if self.login_step == 1:
            if not company_code:
                self.error_label.setText("Please enter Company Code.")
                return

            self.login_button.setText("Verifying...")
            self.login_button.setEnabled(False)
            self.company_code_input.setEnabled(False)
            QTimer.singleShot(400, lambda: self._process_company_verification(company_code))

        elif self.login_step == 2:
            # Consent is required before any credentials are sent.
            if not self.consent_checkbox.isChecked():
                self.error_label.setText(CONSENT_REQUIRED_MESSAGE)
                return

            username = self.username_input.text().strip()
            password = self.password_input.text()

            # Simple validation
            if not username or not password:
                self.error_label.setText("Please enter both Employee ID and password.")
                return

            # Show loading/processing state
            self.login_button.setText("Logging in...")
            self.login_button.setEnabled(False)
            self.company_code_input.setEnabled(False)
            self.username_input.setEnabled(False)
            self.password_input.setEnabled(False)
            self.toggle_password_action.setEnabled(False)

            # Simulate brief latency for transition smoothness (like a native desktop processing check)
            QTimer.singleShot(400, lambda: self._process_login(company_code, username, password))

    def _process_login(self, company_code: str, username: str, password: str) -> None:
        import urllib.request
        import urllib.parse
        import json
        import codecs
        from PySide6.QtCore import QSettings

        # Resolve Employee ID back to its username, but only within the same
        # company: an employee code from another company must never be mapped
        # onto this company's user.
        settings = QSettings("Indovision", "iHRMSMonitor")
        saved_emp_id = settings.value("last_employee_id", "")
        saved_uname = settings.value("last_username", "")
        saved_company = settings.value("last_company_code", "")
        
        resolved_username = username
        if (
            saved_emp_id
            and username == saved_emp_id
            and saved_uname
            and str(saved_company) == company_code
        ):
            resolved_username = saved_uname

        # ROT13 encode the user-entered password immediately before API processing
        password = codecs.encode(password, "rot_13")

        # Guarantee no lingering session or token from a previous user exists
        from services.session_service import SessionService
        from services.secure_session import SessionStore
        SessionService().clear()
        try:
            SessionStore().clear_session()
        except Exception:
            pass

        from config.api_config import ApiConfig, ApiConfigError, get_device_id
        from utils.device import get_device_info

        # Use the company context established by verification. It is not
        # re-resolved here: the login must go to exactly the company the user
        # verified and saw confirmed on screen.
        api_config = ApiConfig()

        if (
            not api_config.is_verified
            or self._verified_company_code != company_code
            or api_config.company_code != company_code
        ):
            logger.error(
                "Login attempted without a matching verified company "
                "(entered=%s, verified=%s)",
                company_code,
                api_config.company_code,
            )

            self._reset_company_context()

            self._show_login_error(
                "Please verify the Company Code before signing in."
            )
            return

        api_url = api_config.base_url

        device_info = get_device_info()

        url = f"{api_url}/login/login"
        data = {
            "uname": username,
            "pass": password,
            "imei_number": get_device_id(),
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

                    # Trigger update check if newer version detected
                    if version_json.get("status") == 1:
                        from services.update_service import is_newer_version, UpdateService
                        from config.settings import APP_VERSION
                        server_ver = str(version_json.get("version_code", "")).strip()
                        if is_newer_version(server_ver, APP_VERSION):
                            logger.info("Newer version %s detected on login. Initiating background update.", server_ver)

                            def on_progress(percent: int, down: int, total: int):
                                self.update_status_label.setText(f"Updating ({percent}%)...")
                                self.update_status_label.setVisible(True)

                            def on_completed(path: str, ver: str, force: bool):
                                self.update_status_label.setText(f"Restart to install v{ver}")
                                self.update_status_label.setVisible(True)

                            UpdateService().check_for_updates(
                                api_url=api_url,
                                indo_code=indo_code,
                                api_key=api_key,
                                auto_download=True,
                                on_progress=on_progress,
                                on_completed=on_completed,
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

                device_token = None
                try:
                    # Configure SSL context using certifi CA bundle if available
                    import ssl
                    try:
                        import certifi
                        ssl_context = ssl.create_default_context(cafile=certifi.where())
                    except Exception:
                        ssl_context = ssl.create_default_context()

                    encoded_enroll_data = urllib.parse.urlencode(enroll_data).encode("utf-8")
                    enroll_request = urllib.request.Request(
                        enroll_url,
                        data=encoded_enroll_data,
                        headers={
                            "User-Agent": "iHRMS-Monitor/1.0 (Windows NT 10.0; Win64; x64)",
                            "Content-Type": "application/x-www-form-urlencoded",
                        },
                        method="POST"
                    )
                    
                    with urllib.request.urlopen(enroll_request, timeout=10, context=ssl_context) as enroll_response:
                        enroll_response_body = enroll_response.read().decode("utf-8")
                        
                    enroll_json = json.loads(enroll_response_body)
                    device_token = enroll_json.get("device_token") or enroll_json.get("data", {}).get("device_token")
                except Exception as urllib_err:
                    logger.warning("urllib enrollment attempt encountered: %s; trying requests fallback", urllib_err)
                    try:
                        import requests
                        resp = requests.post(enroll_url, data=enroll_data, timeout=10)
                        if resp.status_code == 200:
                            enroll_json = resp.json()
                            device_token = enroll_json.get("device_token") or enroll_json.get("data", {}).get("device_token")
                        else:
                            logger.error("requests enrollment failed: %s %s", resp.status_code, resp.text)
                    except Exception as req_err:
                        logger.exception("Fallback requests enrollment also failed: %s", req_err)

                if not device_token:
                    logger.error("Device enrollment failed: No device token returned from %s", enroll_url)
                    self._show_login_error("Device enrollment failed. Please check backend server status.")
                    return

                SessionService().device_token = device_token

                full_name = res_json.get("fullName") or res_json.get("username") or username
                user_type = res_json.get("user_type") or "User"
                role_lower = str(user_type).strip().lower()
                tracking_permitted = role_lower not in ("admin", "administrator", "superadmin")

                # Save mapping of Employee ID <-> Username and company code to local settings
                emp_code = (
                    res_json.get("employee_id")
                    or res_json.get("emp_code")
                    or res_json.get("user_id")
                    or res_json.get("id")
                    or res_json.get("indo_code")
                    or username
                )
                uname_from_api = res_json.get("username") or resolved_username
                if emp_code and uname_from_api:
                    settings.setValue("last_employee_id", str(emp_code))
                    settings.setValue("last_username", str(uname_from_api))
                    settings.setValue("last_company_code", str(company_code))

                employee_id = emp_code
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
                    company_code=company_code,
                    device_token=device_token,
                    raw_login_data=res_json,
                )

                # Persist the authenticated session securely for auto-login on restart
                try:
                    from services.secure_session import SessionStore
                    SessionStore().save_session(
                        company_code=company_code,
                        indo_code=indo_code,
                        api_key=api_key,
                        device_token=device_token,
                        username=username,
                        full_name=full_name,
                        user_type=user_type,
                        employee_id=str(employee_id) if employee_id is not None else None,
                        device_info=device_info,
                        tracking_permitted=tracking_permitted,
                        base_url=api_config.base_url,
                        company_id=api_config.company_id,
                    )
                except Exception as save_err:
                    logger.warning("Could not persist session: %s", save_err)

                # Open existing main window and present Dashboard directly
                from ui.main_window import MainWindow

                self.main_window = MainWindow(login_window=self)
                self.main_window.show()
                self.main_window.raise_()
                self.main_window.activateWindow()
                if hasattr(self.main_window, "tray") and self.main_window.tray:
                    self.main_window.tray.show_message(
                        "iHRMS Monitor",
                        "iHRMS Monitor is active.",
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
        self.company_code_input.setEnabled(True)
        self.username_input.setEnabled(True)
        self.password_input.setEnabled(True)
        self.toggle_password_action.setEnabled(True)
