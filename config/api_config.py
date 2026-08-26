"""Centralized API configuration, resolved from the fixed Company Code.

Everything about *where* the backend lives is resolved at runtime from a
single fixed value: the Company Code (``controller_id``). That code is the
only hardcoded API value in the project - it is posted to the App Controller
endpoint, which returns the company's real API base URL and company id:

    POST <APP_CONTROLLER_URL>
    controller_id=<COMPANY_CONTROLLER_ID>

    {
        "response": "Success",
        "status": 200,
        "data": {
            "fk_company_id": "1",
            "base_url": "https://.../hrms_api/ci4/api/",
            "logo_url": "https://.../logo.png",
            ...
        }
    }

Every other module asks this module for the base URL instead of holding its
own copy, so the backend can be moved by changing the Company Code alone.

The Company Code is intentionally NOT user-editable: it is a build-time
constant, not a preference, and is deliberately absent from
``SettingsService`` / the settings UI.
"""

from __future__ import annotations

import os
import threading

import requests

from utils.logger import get_logger


logger = get_logger(__name__)


# ==================================================================
# FIXED COMPANY CONFIGURATION
#
# The ONLY hardcoded API values in the project. Do not make these
# user-editable and do not read runtime values from here.
# ==================================================================

COMPANY_CONTROLLER_ID = "IVSA1C1R092025"

APP_CONTROLLER_URL = (
    "https://info.indovisionservices.in/dev/v15/hrms_api/v7/api"
    "/appcontroller/appcontroller"
)

# How long to wait for the App Controller bootstrap call.
APP_CONTROLLER_TIMEOUT_SECONDS = 15


class ApiConfigError(RuntimeError):
    """Raised when the API configuration could not be resolved."""


class ApiConfig:
    """
    Resolves and caches the backend configuration for this company.

    The App Controller is called once per process; the resolved values are
    cached because they are deployment configuration, not runtime data.
    """

    _instance: ApiConfig | None = None
    _lock = threading.Lock()

    def __new__(cls) -> ApiConfig:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._base_url = None
            cls._instance._company_id = None
            cls._instance._logo_url = None
        return cls._instance

    # --------------------------------------------------------------
    # BOOTSTRAP
    # --------------------------------------------------------------

    def load(
        self,
        *,
        force: bool = False,
    ) -> None:
        """
        Resolve the API configuration from the fixed Company Code.

        Safe to call repeatedly: the result is cached unless ``force``
        is set. Raises ApiConfigError if the configuration cannot be
        resolved and has never been resolved before.
        """

        with self._lock:

            if self._base_url and not force:
                return

            # An explicit API_URL override keeps the existing operational
            # escape hatch working (used by dev/staging deployments).
            override = os.environ.get("API_URL")

            if override:
                self._base_url = override.rstrip("/")

                logger.info(
                    "API base URL taken from API_URL override: %s",
                    self._base_url,
                )

                return

            logger.info(
                "Resolving API configuration for company code %s",
                COMPANY_CONTROLLER_ID,
            )

            try:
                response = requests.post(
                    APP_CONTROLLER_URL,
                    data={
                        "controller_id": COMPANY_CONTROLLER_ID,
                    },
                    timeout=APP_CONTROLLER_TIMEOUT_SECONDS,
                )

                response.raise_for_status()

                payload = response.json()

            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "App Controller request failed: %s",
                    exc,
                )

                if self._base_url:
                    # Keep serving the previously resolved configuration.
                    return

                raise ApiConfigError(
                    "Could not reach the configuration service."
                ) from exc

            data = payload.get("data") or {}

            base_url = str(
                data.get("base_url") or ""
            ).strip()

            if not base_url:
                if self._base_url:
                    return

                raise ApiConfigError(
                    "Configuration service returned no base_url."
                )

            self._base_url = base_url.rstrip("/")

            company_id = data.get("fk_company_id")

            self._company_id = (
                str(company_id)
                if company_id is not None
                else None
            )

            logo_url = data.get("logo_url")

            self._logo_url = (
                str(logo_url)
                if logo_url
                else None
            )

            logger.info(
                "API configuration resolved: base_url=%s, company_id=%s",
                self._base_url,
                self._company_id,
            )

    # --------------------------------------------------------------
    # RESOLVED VALUES
    # --------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """Return the company's API base URL, resolving it if needed."""

        if not self._base_url:
            self.load()

        return self._base_url or ""

    @property
    def company_id(self) -> str | None:
        """Company id returned by the App Controller."""

        if not self._base_url:
            self.load()

        return self._company_id

    @property
    def logo_url(self) -> str | None:
        """Company logo URL returned by the App Controller."""

        if not self._base_url:
            self.load()

        return self._logo_url

    def endpoint(
        self,
        path: str,
    ) -> str:
        """
        Build a full URL for an API path.

        Example:

            ApiConfig().endpoint("tracking/enroll_device")
        """

        return f"{self.base_url}/{path.lstrip('/')}"
