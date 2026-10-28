"""Login screen for the iHRMS Desktop application."""

from __future__ import annotations

import os
import sys
from typing import Any

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
from ui.keyboard_navigation import KeyboardNavigationEventFilter
from utils.logger import get_logger

logger = get_logger(__name__)

# Selling points shown on the dark hero panel: (icon name, text).
HERO_BULLETS = (
    ("chart", "Manage attendance, KRA and productivity"),
    ("shield", "Secure, role-based access"),
)


CONSENT_REQUIRED_MESSAGE = "Please accept the consent to continue."

CONSENT_TEXT = (
    "By logging in to iHRMS Desktop, you acknowledge and give your consent to "
    "your activity information for  iHRMS Desktop productivity monitoring."
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


class _LoginErrorLabel(QLabel):
    """Error label that automatically hides and collapses to 0 height when empty."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setVisible(bool(text and text.strip()))

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self.setVisible(bool(text and text.strip()))

    def clear(self) -> None:
        super().clear()
        self.setVisible(False)


class LoginWindow(QMainWindow):
    """Secure, offline login screen for iHRMS Monitor."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("iHRMS Desktop - Login")
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
        self._update_dialog = None
        self.update_status_label = None

        # Company Code starts blank and nothing is verified yet.
        self._verified_company_code = None

        KeyboardNavigationEventFilter.install(self)
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────
    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("LoginBackground")
        layout = QHBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Card split into a dark hero panel and the white form panel
        card = QFrame(central)
        card.setObjectName("LoginCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setFixedSize(780, 545)
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addWidget(self._build_hero_panel(card))
        card_layout.addWidget(self._build_form_panel(card))

        layout.addWidget(card)
        self.setCentralWidget(central)

    def _build_hero_panel(self, parent: QWidget | None = None) -> QWidget:
        """Dark branded panel: app mark, tagline and three bullet points."""
        hero = QFrame(parent)
        hero.setObjectName("LoginHero")
        hero.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hero.setFixedWidth(320)

        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(32, 40, 32, 32)
        hero_layout.setSpacing(0)

        # Hero illustration / App Icon (big iHRMS star logo)
        icon_label = QLabel(hero)
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

        brand_name = QLabel("iHRMS Desktop", hero)
        brand_name.setObjectName("LoginBrandName")
        brand_name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        hero_layout.addWidget(brand_name)

        hero_layout.addSpacing(6)
        tagline = QLabel("Smart Workspace Productivity Monitoring", hero)
        tagline.setObjectName("LoginTagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        hero_layout.addWidget(tagline)

        hero_layout.addSpacing(26)
        rule = QFrame(hero)
        rule.setObjectName("LoginHeroRule")
        rule.setFixedHeight(1)
        hero_layout.addWidget(rule)
        hero_layout.addSpacing(24)

        for icon_name, text in HERO_BULLETS:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            row.addWidget(_icon_label(icon_name, 18), 0, Qt.AlignmentFlag.AlignTop)
            bullet = QLabel(text, hero)
            bullet.setObjectName("LoginBullet")
            bullet.setWordWrap(True)
            row.addWidget(bullet, 1)
            hero_layout.addLayout(row)
            hero_layout.addSpacing(18)

        hero_layout.addStretch(1)

        # Application version display on hero panel
        from config.settings import get_running_app_version
        self.hero_version_label = QLabel(f"Version {get_running_app_version()}", hero)
        self.hero_version_label.setObjectName("LoginHeroVersion")
        self.hero_version_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.hero_version_label.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 500;")
        hero_layout.addWidget(self.hero_version_label)

        return hero

    def set_version(self, version: str) -> None:
        """Update the version displayed on the hero panel."""
        clean_v = str(version or "").strip()
        if clean_v.lower().startswith("version"):
            clean_v = clean_v[7:].strip()
        if clean_v.startswith("v") or clean_v.startswith("V"):
            clean_v = clean_v[1:].strip()
        if hasattr(self, "hero_version_label") and self.hero_version_label:
            self.hero_version_label.setText(f"Version {clean_v}")

    def _build_form_panel(self, parent: QWidget | None = None) -> QWidget:
        """White panel holding the brand logo and the credential form."""
        panel = QFrame(parent)
        panel.setObjectName("LoginFormPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(46, 40, 46, 26)
        panel_layout.setSpacing(0)

        # ── Brand logo (Centered) ──────────────────────────────────
        self.brand_logo_label = QLabel(panel)
        self.brand_logo_label.setObjectName("LoginLogo")
        self.brand_logo_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self._set_default_brand_logo()
        panel_layout.addWidget(self.brand_logo_label)

        panel_layout.addSpacing(20)
        caption = QLabel("Enter Company code & Sign in to continue", panel)
        caption.setObjectName("LoginCaption")
        panel_layout.addWidget(caption)

        panel_layout.addSpacing(26)

        # ── Company Code ──────────────────────────────────────────
        self.company_code_input = QLineEdit(panel)
        self.company_code_input.setObjectName("CompanyCodeInput")
        self.company_code_input.setPlaceholderText("Enter Company Code")
        self.company_code_input.setMinimumHeight(42)
        # Prevent autofill
        self.company_code_input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.company_code_input.addAction(
            _load_icon("building"), QLineEdit.ActionPosition.LeadingPosition
        )
        self.company_code_check_action = self.company_code_input.addAction(
            _load_icon("check-verified"), QLineEdit.ActionPosition.TrailingPosition
        )
        self.company_code_check_action.setVisible(False)
        panel_layout.addWidget(self.company_code_input)

        # ── Verified company details (from the verification API) ───
        # Hidden until a company code is verified, and cleared again the
        # moment the code changes, so one company's details can never be
        # shown alongside another company's code.
        self.company_details = QWidget(panel)
        self.company_details.setObjectName("CompanyDetails")
        self.company_details.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )

        details_layout = QHBoxLayout(self.company_details)
        details_layout.setContentsMargins(10, 8, 10, 8)
        details_layout.setSpacing(10)

        self.company_logo_label = QLabel(self.company_details)
        self.company_logo_label.setFixedSize(30, 30)
        self.company_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        details_layout.addWidget(self.company_logo_label)

        self.company_name_label = QLabel(self.company_details)
        self.company_name_label.setObjectName("CompanyDetailsText")
        self.company_name_label.setWordWrap(True)
        details_layout.addWidget(self.company_name_label, 1)

        self.company_details.setVisible(False)
        panel_layout.addWidget(self.company_details)

        # Container for the step 2 credential fields
        self.credentials_container = QWidget(panel)
        self.credentials_container.setObjectName("CredentialsContainer")
        self.credentials_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        credentials_layout = QVBoxLayout(self.credentials_container)
        credentials_layout.setContentsMargins(0, 8, 0, 8)
        credentials_layout.setSpacing(12)

        # ── Username (Employee ID / Username / Email) ──────────────────────────────────────────────
        self.username_input = QLineEdit(self.credentials_container)
        self.username_input.setPlaceholderText("Employee ID / Username / Email")
        self.username_input.setMinimumHeight(42)
        # Prevent autofill
        self.username_input.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.username_input.addAction(
            _load_icon("user"), QLineEdit.ActionPosition.LeadingPosition
        )
        credentials_layout.addWidget(self.username_input)

        # ── Password (eye icon replaces the old "Show password" box) ──
        self.password_input = QLineEdit(self.credentials_container)
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

        self.login_step = 1
        self.credentials_container.setVisible(False)

        # Ensure login fields start strictly empty on launch
        self.company_code_input.clear()
        self.username_input.clear()
        self.password_input.clear()

        # Connect text changes of company code to reset step
        self.company_code_input.textChanged.connect(self._on_company_code_changed)

        # Error label (auto-collapses to 0 height when empty)
        self.error_label = _LoginErrorLabel("", panel)
        self.error_label.setObjectName("LoginError")
        self.error_label.setWordWrap(True)
        panel_layout.addWidget(self.error_label)

        # ── Consent (must be accepted before logging in) ──────────
        consent_row = QWidget(panel)
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
        consent_text.setCursor(Qt.CursorShape.PointingHandCursor)

        def _on_consent_label_clicked(_event):
            self.consent_checkbox.toggle()

        consent_text.mousePressEvent = _on_consent_label_clicked
        consent_row.setCursor(Qt.CursorShape.PointingHandCursor)
        consent_row.mousePressEvent = _on_consent_label_clicked
        consent_layout.addWidget(consent_text, 1)

        # Consent only becomes relevant once a company has been verified,
        # so the row stays hidden until then.
        self.consent_row = consent_row
        self.consent_row.setVisible(False)

        panel_layout.addWidget(consent_row)

        # Clear the validation message as soon as the box is ticked.
        self.consent_checkbox.toggled.connect(self._on_consent_toggled)

        # Login button
        panel_layout.addSpacing(14)
        self.login_button = QPushButton("Verify Company" if self.login_step == 1 else "Login")
        self.login_button.setObjectName("LoginButton")
        self.login_button.setMinimumHeight(44)
        self.login_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_button.clicked.connect(self._handle_login)
        panel_layout.addWidget(self.login_button)

        # Connect Enter on inputs to handle login/verify
        self.company_code_input.returnPressed.connect(self._handle_login)
        self.username_input.returnPressed.connect(self._handle_login)
        self.password_input.returnPressed.connect(self._handle_login)

        # Tab order
        QWidget.setTabOrder(self.company_code_input, self.username_input)
        QWidget.setTabOrder(self.username_input, self.password_input)
        QWidget.setTabOrder(self.password_input, self.consent_checkbox)
        QWidget.setTabOrder(self.consent_checkbox, self.login_button)

        panel_layout.addStretch(1)

        return panel

    def show_and_clear(self, error_message: str | None = None, keep_company_code: bool = False) -> None:
        """Clear fields and show the window again (used for logout or session revocation)."""
        self.login_step = 1
        self.credentials_container.setVisible(False)
        self.login_button.setText("Verify Company")
        
        last_cc = None
        if keep_company_code:
            try:
                from services.secure_session import SessionStore
                last_cc = SessionStore().get_last_company_code()
            except Exception:
                pass

        # Drop the verified company so the next login starts from scratch.
        self._reset_company_context()

        if keep_company_code and last_cc:
            self.company_code_input.setText(last_cc)
        else:
            self.company_code_input.clear()

        self.username_input.clear()
        self.password_input.clear()
        self.consent_checkbox.setChecked(False)
        self.company_code_check_action.setVisible(False)
        self.company_code_input.setReadOnly(False)
        self.company_code_input.setEnabled(True)
        self.username_input.setEnabled(True)
        self.password_input.setEnabled(True)
        self._set_password_visible(False)
        self.toggle_password_action.setEnabled(True)
        self.login_button.setEnabled(True)
        
        if error_message:
            self.error_label.setText(str(error_message))
        else:
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

    def _show_update_dialog(
        self,
        version: str = "",
        is_force: bool = False,
        installer_path: str | None = None,
        worker: object | None = None,
    ) -> None:
        """Silent update mode: No-op to avoid popup interruptions."""
        logger.debug("Silent update mode active; suppressing login update dialog popup.")
        return

    def _on_update_status_clicked(self, event: object = None) -> None:
        """Silent update mode: Suppress manual popup."""
        logger.debug("Silent update mode active; suppressing update popup.")
        return

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

        if hasattr(self, "company_code_check_action"):
            self.company_code_check_action.setVisible(False)
        if hasattr(self, "company_code_input"):
            self.company_code_input.setReadOnly(False)

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

        logger.info("Processing company verification in UI: company_code=%s", company_code)
        try:
            api_config.load(company_code=company_code, force=True)

            # Only now is this company the active context.
            self._verified_company_code = company_code

            self._show_company_details()

            # Show verification check mark on the right side of Company Code field
            self.company_code_check_action.setVisible(True)

            # Lock Company Code field so it cannot be edited/changed once verified
            self.company_code_input.setReadOnly(True)
            self.company_code_input.setEnabled(True)

            # Consent applies to signing in, which is now possible.
            self.consent_row.setVisible(True)

            self.login_step = 2
            self.credentials_container.setVisible(True)
            self.username_input.clear()
            self.password_input.clear()
            self.login_button.setText("Login")
            self.login_button.setEnabled(True)

            # If the config was loaded from offline cache, show a soft warning so
            # the user knows they are working with saved (potentially stale) data.
            if getattr(api_config, "_loaded_from_cache", False):
                self.error_label.setStyleSheet("color: #f59e0b;")  # amber
                self.error_label.setText(
                    "\u26a0\ufe0f Offline mode: verification server unreachable. "
                    "Using saved configuration."
                )
            else:
                self.error_label.clear()
                self.error_label.setStyleSheet("")

            self.username_input.setFocus()

        except ApiConfigError as config_err:
            logger.error("Company verification failed: code=%s, validation_failure_reason=%s", company_code, config_err)

            # Leave no trace of any previously verified company.
            self._reset_company_context()

            self.company_code_check_action.setVisible(False)
            self.company_code_input.setReadOnly(False)
            self.login_button.setEnabled(True)
            self.company_code_input.setEnabled(True)
            self.error_label.setStyleSheet("")

            # Surface the message the verification API itself returned.
            self.error_label.setText(str(config_err))
        except Exception as unexp_err:
            logger.exception("Unexpected error verifying company code: %s", unexp_err)
            self._reset_company_context()
            self.company_code_check_action.setVisible(False)
            self.company_code_input.setReadOnly(False)
            self.login_button.setEnabled(True)
            self.company_code_input.setEnabled(True)
            self.error_label.setStyleSheet("")
            self.error_label.setText("Verification service error. Please check your connection and try again.")

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
        SessionService().clear()

        from config.api_config import ApiConfig, ApiConfigError, get_device_id
        from utils.device import get_device_info

        # Use the company context established by verification. It is not
        # re-resolved here: the login must go to exactly the company the user
        # verified and saw confirmed on screen.
        api_config = ApiConfig()

        norm_entered = str(company_code or "").strip().upper()
        norm_verified = str(self._verified_company_code or "").strip().upper()
        norm_configured = str(api_config.company_code or "").strip().upper()

        # If configuration context in memory was unverified or lost, re-adopt if company code matches
        if (not api_config.is_verified or norm_configured != norm_entered) and norm_entered:
            if norm_verified == norm_entered or self.login_step == 2:
                try:
                    logger.info("Re-confirming company configuration for '%s' prior to login", company_code)
                    api_config.load(company_code=company_code, force=False)
                    self._verified_company_code = company_code
                    norm_verified = str(self._verified_company_code or "").strip().upper()
                    norm_configured = str(api_config.company_code or "").strip().upper()
                except Exception as load_err:
                    logger.warning("Could not re-resolve company configuration for '%s': %s", company_code, load_err)

        if (
            not api_config.is_verified
            or norm_verified != norm_entered
            or norm_configured != norm_entered
        ):
            logger.error(
                "Login validation failure: company not verified "
                "(entered=%s, verified=%s, configured=%s)",
                company_code,
                self._verified_company_code,
                api_config.company_code,
            )

            self._reset_company_context()

            self._show_login_error(
                "Please verify the Company Code before signing in."
            )
            return

        api_url = api_config.base_url
        url = api_config.login_url

        parsed_login = urllib.parse.urlparse(url)
        logger.info(
            "Login API request [START]: host=%s path=%s company_code=%s",
            parsed_login.netloc,
            parsed_login.path,
            company_code,
        )

        from utils.device import get_device_info, get_dynamic_os_type

        device_info = get_device_info()
        _os_type = device_info.get("os_type") or get_dynamic_os_type()
        _device_detail = device_info.get("device_detail") or "PC"

        req_headers = {
            "User-Agent": "iHRMS-Monitor/1.0 (Windows NT 10.0; Win64; x64)",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/plain, */*",
        }

        # Build the login payload exactly as the API requires:
        #   uname        – the username entered by the user
        #   pass         – the encoded password
        #   imei_number  – always an empty string (desktop has no IMEI)
        #   device_detail – dynamic machine description (e.g. 'Dell Inc. Latitude 7490')
        #   os_type      – dynamic operating-system value ('window' on Windows)
        data = {
            "uname": username,
            "pass": password,
            "imei_number": "",
            "device_detail": _device_detail,
            "os_type": _os_type,
        }

        logger.debug(
            "Login request fields: uname=%s, imei_number='', device_detail=%s, os_type=%s",
            username,
            _device_detail,
            _os_type,
        )

        res_json = None
        used_device_id = ""

        try:
            # Perform HTTP POST via requests first (handles certificates and proxies automatically)
            try:
                import requests
                resp = requests.post(url, data=data, headers=req_headers, timeout=15)
                try:
                    res_json = resp.json()
                except Exception:
                    res_json = json.loads(resp.text)
            except Exception as req_exc:
                logger.debug("requests login attempt failed (%s); trying urllib with SSL context", req_exc)
                # Fallback to urllib with certifi SSL context
                import ssl
                try:
                    import certifi
                    ssl_context = ssl.create_default_context(cafile=certifi.where())
                except Exception:
                    ssl_context = ssl.create_default_context()

                encoded_data = urllib.parse.urlencode(data).encode("utf-8")
                req = urllib.request.Request(url, data=encoded_data, headers=req_headers, method="POST")
                with urllib.request.urlopen(req, timeout=15, context=ssl_context) as response:
                    res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body)

            res_status = res_json.get("status") if isinstance(res_json, dict) else "unknown"
            logger.info(
                "Login API response: host=%s path=%s status=%s",
                parsed_login.netloc,
                parsed_login.path,
                res_status,
            )

            if res_json and res_json.get("status") == 2:
                logger.info(
                    "User %s logged in successfully via API "
                    "(imei_number='', device_detail=%s, os_type=%s)",
                    username, _device_detail, _os_type,
                )

                # Nothing to persist for device identifier when imei_number is always empty.

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
                
                # ----------------------------------------------
                # App Controller Version Check & Silent Background Update
                # ----------------------------------------------
                try:
                    from services.update_service import fetch_app_controller_update_info, is_newer_version, UpdateService
                    from services.update_state import UpdateStateManager
                    from config.settings import get_running_app_version

                    server_ver, file_name, dl_url, is_force = fetch_app_controller_update_info(
                        company_code=company_code,
                        api_url=api_url,
                        indo_code=indo_code,
                        api_key=api_key,
                    )

                    if server_ver and is_newer_version(server_ver, get_running_app_version()):
                        allowed, loop_reason = UpdateStateManager().should_attempt_update(server_ver)
                        if not allowed:
                            logger.info("Login screen update loop guard: %s", loop_reason)
                        else:
                            logger.info("Newer version %s detected on login. Initiating silent background update pipeline.", server_ver)

                            def on_ready_to_install(installer_path: str):
                                logger.info("Login screen update ready to install: %s", installer_path)
                                from services.update_service import install_update_and_restart
                                install_update_and_restart(installer_path, target_version=server_ver, exit_process=True)

                            UpdateService().start_pipeline(
                                api_url=api_url,
                                indo_code=indo_code,
                                api_key=api_key,
                                on_ready_to_install=on_ready_to_install,
                            )
                except Exception as version_err:
                    logger.warning("Version check failed on login: %s", version_err)

                # ----------------------------------------------
                # Device Enrollment
                # ----------------------------------------------
                enroll_url = api_config.enroll_device_url

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
                    try:
                        from services.error_report_service import ErrorReportService
                        ErrorReportService().report_error(
                            error_type="DEVICE_ENROLLMENT_ERROR",
                            error_message=f"Device enrollment failed: No device token returned from {enroll_url}",
                            extra_context={"endpoint": enroll_url, "username": username},
                        )
                    except Exception:
                        pass
                    self._show_login_error("Device enrollment failed. Please check backend server status.")
                    return

                SessionService().device_token = device_token
                try:
                    from config.screenshot_config import apply_api_screenshot_config
                    if isinstance(enroll_json, dict):
                        apply_api_screenshot_config(enroll_json)
                except Exception as cfg_err:
                    logger.debug("Could not apply screenshot config from device enrollment: %s", cfg_err)

                try:
                    from services.sync_service import SyncService
                    if isinstance(enroll_json, dict):
                        SyncService().apply_settings_payload(enroll_json)
                except Exception as sync_cfg_err:
                    logger.debug("Could not apply sync settings from device enrollment: %s", sync_cfg_err)

                login_data = res_json.get("data", {}) if isinstance(res_json.get("data"), dict) else {}
                full_name = (
                    res_json.get("fullName")
                    or res_json.get("full_name")
                    or res_json.get("name")
                    or res_json.get("employee_name")
                    or res_json.get("emp_name")
                    or res_json.get("employeeName")
                    or login_data.get("fullName")
                    or login_data.get("full_name")
                    or login_data.get("name")
                    or login_data.get("employee_name")
                    or login_data.get("emp_name")
                    or login_data.get("employeeName")
                    or res_json.get("username")
                    or login_data.get("username")
                    or username
                )
                user_type = res_json.get("user_type") or "User"
                role_lower = str(user_type).strip().lower()
                workpulse_permitted = role_lower not in ("admin", "administrator", "superadmin")


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

                def _parse_bool_permission(val: Any) -> bool | None:
                    if val is None:
                        return None
                    if isinstance(val, bool):
                        return val
                    if isinstance(val, (int, float)):
                        return bool(val)
                    if isinstance(val, str):
                        s = val.strip().lower()
                        if s in ("true", "1", "yes", "t", "y", "enable", "enabled"):
                            return True
                        if s in ("false", "0", "no", "f", "n", "disable", "disabled"):
                            return False
                    return None

                def _extract_permission(data: dict, keys: list[str]) -> bool | None:
                    for k in keys:
                        if k in data and data[k] is not None:
                            res = _parse_bool_permission(data[k])
                            if res is not None:
                                return res
                    return None

                candidates = [
                    res_json,
                    res_json.get("data", {}) if isinstance(res_json.get("data"), dict) else {},
                    res_json.get("permissions", {}) if isinstance(res_json.get("permissions"), dict) else {},
                    res_json.get("settings", {}) if isinstance(res_json.get("settings"), dict) else {},
                    enroll_json if isinstance(enroll_json, dict) else {},
                    enroll_json.get("data", {}) if isinstance(enroll_json, dict) and isinstance(enroll_json.get("data"), dict) else {},
                ]

                allow_logout = True
                for c in candidates:
                    perm = _extract_permission(c, ["allow_logout", "logout_permitted", "can_logout", "allow_user_logout", "enable_logout"])
                    if perm is not None:
                        allow_logout = perm
                        break

                allow_user_device = True
                for c in candidates:
                    perm = _extract_permission(c, [
                        "allow_user_device",
                        "allow_user_device_info",
                        "allow_device_info",
                        "allow_device",
                        "allow_user_device_modal",
                        "allow_user_info",
                        "show_user_device",
                        "user_device_allowed",
                        "user_device_permitted",
                        "user_device_enabled",
                        "device_info_enabled",
                        "can_view_user_device",
                    ])
                    if perm is not None:
                        allow_user_device = perm
                        break

                # Dynamic workpulse permission from backend candidates
                for c in candidates:
                    perm = _extract_permission(c, [
                        "workpulse_enabled",
                        "workpulse_permitted",
                        "allow_workpulse",
                        "is_workpulse_enabled",
                        "enable_workpulse",
                    ])
                    if perm is not None:
                        workpulse_permitted = perm
                        break

                # Dynamic Start/Stop Activity Tracking permission from backend candidates
                allow_start_stop_activity_tracking = True
                for c in candidates:
                    pair_found = False
                    for start_k, stop_k in [
                        ("start", "stop"),
                        ("allow_start", "allow_stop"),
                        ("can_start", "can_stop"),
                        ("start_tracking", "stop_tracking"),
                        ("allow_start_tracking", "allow_stop_tracking"),
                    ]:
                        if start_k in c and stop_k in c and c[start_k] is not None and c[stop_k] is not None:
                            ps = _parse_bool_permission(c[start_k])
                            pst = _parse_bool_permission(c[stop_k])
                            if ps is False and pst is False:
                                allow_start_stop_activity_tracking = False
                                pair_found = True
                                break
                            elif ps is True or pst is True:
                                allow_start_stop_activity_tracking = True
                                pair_found = True
                                break
                    if pair_found:
                        break
                    perm = _extract_permission(c, [
                        "allow_start_stop_activity_tracking",
                        "allow_start_stop_activity_workpulse",
                        "allow_start_stop_tracking",
                        "allow_start_stop",
                    ])
                    if perm is not None:
                        allow_start_stop_activity_tracking = perm
                        break

                employee_id = emp_code
                email_val = (
                    res_json.get("email")
                    or res_json.get("user_email")
                    or res_json.get("userEmail")
                    or login_data.get("email")
                    or login_data.get("user_email")
                    or login_data.get("userEmail")
                    or (username if "@" in str(username) else None)
                )

                SessionService().login(
                    username,
                    role=user_type,
                    full_name=full_name,
                    user_type=user_type,
                    workpulse_permitted=workpulse_permitted,
                    allow_user_device=allow_user_device,
                    allow_logout=allow_logout,
                    allow_start_stop_activity_tracking=allow_start_stop_activity_tracking,
                    indo_code=indo_code,
                    api_key=api_key,
                    employee_id=(
                        str(employee_id)
                        if employee_id is not None
                        else None
                    ),
                    company_code=company_code,
                    company_id=api_config.company_id,
                    base_url=api_config.base_url,
                    portal_url=api_config.portal_url,
                    logo_url=api_config.logo_url,
                    email=email_val,
                    device_token=device_token,
                    raw_login_data=res_json,
                    session_credential=password,
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
                        workpulse_permitted=workpulse_permitted,
                        base_url=api_config.base_url,
                        portal_url=api_config.portal_url,
                        logo_url=api_config.logo_url,
                        email=email_val,
                        company_id=api_config.company_id,
                        allow_user_device=allow_user_device,
                        allow_logout=allow_logout,
                        allow_start_stop_activity_tracking=allow_start_stop_activity_tracking,
                        workpulse_manually_stopped=False,
                    )
                except Exception as save_err:
                    logger.warning("Could not persist session: %s", save_err)

                # Query workpulse/get_settings immediately so server-side DB permissions are adopted
                try:
                    from services.sync_service import SyncService
                    SyncService().fetch_settings()
                except Exception as sync_settings_err:
                    logger.debug("Could not fetch initial settings on login: %s", sync_settings_err)

                # Record device enrollment in DeviceRegistryService
                try:
                    from services.device_registry_service import DeviceRegistryService
                    DeviceRegistryService().record_heartbeat(
                        device_identifier=device_info.get("device_identifier"),
                        hostname=device_info.get("hostname"),
                        employee_id=str(employee_id) if employee_id is not None else None,
                        username=username,
                        device_token=device_token,
                    )
                except Exception as reg_err:
                    logger.debug("Could not record device enrollment in registry: %s", reg_err)

                # Open existing main window and present Dashboard directly
                from ui.main_window import MainWindow

                self.main_window = MainWindow(login_window=self)
                self.main_window.show()
                self.main_window.raise_()
                self.main_window.activateWindow()
                if hasattr(self.main_window, "tray") and self.main_window.tray:
                    self.main_window.tray.show_message(
                        "iHRMS Desktop",
                        "iHRMS Desktop is active.",
                    )

                # Hide login window
                self.hide()
            else:
                msg = res_json.get("message") if res_json else "Invalid username or password."
                if isinstance(msg, dict):
                    msg = " ".join(str(v) for v in msg.values())
                logger.warning(
                    "Login rejected by API: status=%s, reason=%s",
                    res_json.get("status") if res_json else "None",
                    msg,
                )
                self._show_login_error(str(msg) if msg else "Invalid username or password.")
                
        except Exception as exc:
            logger.exception("Error calling external login API")
            endpoint_url = url if "url" in locals() and url else (f"{api_config.base_url}/login/login" if hasattr(api_config, 'base_url') and api_config.base_url else "unknown")
            try:
                from services.error_report_service import ErrorReportService
                ErrorReportService().report_error(
                    error_type="LOGIN_API_ERROR",
                    error_message=f"Error calling external login API: {exc}",
                    exc=exc,
                    extra_context={"endpoint": endpoint_url, "company_code": company_code},
                )
            except Exception:
                pass

            import urllib.error
            import socket
            err_str = str(exc).strip()
            
            # Identify true network/connection errors vs runtime exceptions
            is_network_err = (
                isinstance(exc, (urllib.error.URLError, socket.error, TimeoutError, ConnectionError))
                or "requests.exceptions" in str(type(exc))
                or any(keyword in err_str.lower() for keyword in ["connection", "timed out", "getaddrinfo", "nodename", "refused", "unreachable"])
            )

            if is_network_err:
                if err_detail := err_str:
                    self._show_login_error(f"Could not connect to authentication server ({err_detail}). Please check your connection.")
                else:
                    self._show_login_error("Could not connect to authentication server. Please check your network connection.")
            else:
                self._show_login_error(f"Login error: {err_str}" if err_str else "Login failed due to an unexpected error. Please try again.")

    def _show_login_error(self, message: str = "Invalid username or password.") -> None:
        self.error_label.setText(message)
        self.login_button.setText("Login")
        self.login_button.setEnabled(True)
        self.company_code_input.setEnabled(True)
        self.username_input.setEnabled(True)
        self.password_input.setEnabled(True)
        self.toggle_password_action.setEnabled(True)

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            from services.secure_session import SessionStore
            SessionStore().set_clean_shutdown(True)
        except Exception:
            pass
        super().closeEvent(event)
        # If user closes login window without an active session, cleanly quit application
        if not getattr(self, "main_window", None):
            from services.session_service import SessionService
            if SessionService().current_user is None:
                from PySide6.QtWidgets import QApplication
                app_inst = QApplication.instance()
                if app_inst:
                    app_inst.quit()


