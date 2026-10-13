"""HRMS Web Portal auto-login and navigation service.

Enables seamless, dynamic auto-login to the iHRMS Web Portal when a user
clicks the Dashboard HRMS button, using the active authenticated session details.
"""

from __future__ import annotations

import html
import json
import os
import tempfile
import threading
import time
import webbrowser
from typing import Any, Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from config.api_config import ApiConfig
from services.session_service import SessionService
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_PORTAL_URL = "https://ihrms.indovisionservices.in"


def _schedule_file_cleanup(file_path: str, delay_seconds: float = 6.0) -> None:
    """Delete a temporary file after a short delay in a daemon background thread."""
    def _cleanup():
        time.sleep(delay_seconds)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                logger.debug("Cleaned up temporary auto-login file: %s", file_path)
        except Exception as exc:
            logger.debug("Could not remove temp auto-login file %s: %s", file_path, exc)

    thread = threading.Thread(target=_cleanup, daemon=True)
    thread.start()


class HrmsPortalService:
    """Service to handle dynamic HRMS Web Portal navigation with auto-login."""

    _instance: Optional[HrmsPortalService] = None

    def __new__(cls) -> HrmsPortalService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_resolved_portal_url(self) -> str:
        """Dynamically resolve the verified company's HRMS portal URL."""
        api_cfg = ApiConfig()
        details = api_cfg.details or {}

        # 1. AppController portal_url
        portal_url = str(details.get("portal_url") or "").strip()
        if portal_url:
            return portal_url.rstrip("/") + "/"

        # 2. Derive from verified base_url if available
        if api_cfg.is_verified:
            base_url = api_cfg.base_url
            # e.g., 'https://softdev.indovisionservices.in/ihrms84/hrms_api/ci4/api' -> 'https://softdev.indovisionservices.in/ihrms84/'
            if "/hrms_api" in base_url:
                derived = base_url.split("/hrms_api")[0].rstrip("/") + "/"
                return derived

        return DEFAULT_PORTAL_URL.rstrip("/") + "/"

    def generate_autologin_html(
        self,
        portal_url: str,
        username: str | dict[str, Any] = "",
        password: str = "",
        **extra_params: Any,
    ) -> str:
        """
        Build an auto-authenticating HTML bridge that submits the user's dynamic
        authenticated details to the portal's check-user endpoint and redirects to the Dashboard.
        """
        portal_url_clean = portal_url.rstrip("/") + "/"
        check_user_url = f"{portal_url_clean}ajax/check-user.php"
        login_fallback_url = f"{portal_url_clean}login.php"

        if isinstance(username, dict):
            auth_dict = dict(username)
            auth_dict.update(extra_params)
        else:
            auth_dict = {"user_name": str(username), "password": str(password), **extra_params}

        # Determine user display name for the connecting card
        disp_name = (
            auth_dict.get("full_name")
            or auth_dict.get("user_name")
            or auth_dict.get("username")
            or auth_dict.get("employee_code")
            or auth_dict.get("indo_code")
            or "User"
        )
        safe_disp_uname = html.escape(str(disp_name))

        safe_portal_url = json.dumps(portal_url_clean)
        safe_check_url = json.dumps(check_user_url)
        safe_fallback_url = json.dumps(login_fallback_url)
        safe_auth_json = json.dumps(auth_dict)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>iHRMS Portal - Connecting...</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      background-color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      color: #1e293b;
    }}
    .card {{
      background: #ffffff;
      padding: 32px 40px;
      border-radius: 12px;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.08), 0 8px 10px -6px rgba(0, 0, 0, 0.04);
      text-align: center;
      max-width: 400px;
      width: 100%;
    }}
    .spinner {{
      width: 44px;
      height: 44px;
      border: 3px solid #e2e8f0;
      border-top: 3px solid #1a73e8;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin: 0 auto 20px auto;
    }}
    @keyframes spin {{
      0% {{ transform: rotate(0deg); }}
      100% {{ transform: rotate(360deg); }}
    }}
    h2 {{
      font-size: 18px;
      font-weight: 600;
      margin: 0 0 8px 0;
      color: #0f172a;
    }}
    p {{
      font-size: 14px;
      color: #64748b;
      margin: 0;
    }}
    .user-pill {{
      display: inline-block;
      margin-top: 12px;
      background: #eff6ff;
      color: #1a73e8;
      font-size: 12px;
      font-weight: 600;
      padding: 4px 12px;
      border-radius: 9999px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="spinner"></div>
    <h2>Connecting to iHRMS Portal</h2>
    <p>Signing in automatically...</p>
    <div class="user-pill">{safe_disp_uname}</div>
  </div>

  <script>
    (function() {{
      const portalUrl = {safe_portal_url};
      const checkUrl = {safe_check_url};
      const fallbackUrl = {safe_fallback_url};
      const authData = {safe_auth_json};

      function redirectTo(url) {{
        window.location.replace(url);
      }}

      try {{
        const params = new URLSearchParams();
        for (const [key, val] of Object.entries(authData)) {{
          if (val !== null && val !== undefined && val !== '') {{
            params.append(key, String(val));
          }}
        }}
        if (!params.has('remember_me')) {{
          params.append('remember_me', '1');
        }}

        fetch(checkUrl, {{
          method: 'POST',
          headers: {{
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
          }},
          body: params.toString()
        }})
        .then(function(resp) {{
          return resp.json();
        }})
        .then(function(data) {{
          if (data && data.status !== 'Error' && data.redirect_url) {{
            let target = data.redirect_url;
            if (!target.startsWith('http://') && !target.startsWith('https://')) {{
              target = portalUrl + target.replace(/^\\/+/, '');
            }}
            redirectTo(target);
          }} else {{
            redirectTo(fallbackUrl);
          }}
        }})
        .catch(function(err) {{
          console.warn('Auto-login request failed, redirecting to login page', err);
          redirectTo(fallbackUrl);
        }});
      }} catch (e) {{
        redirectTo(fallbackUrl);
      }}
    }})();
  </script>
</body>
</html>"""
        return html_content

    def open_portal_with_autologin(self) -> bool:
        """
        Open the Workpulse / HRMS Web Portal in the user's default browser with dynamic authentication.

        If the user is authenticated and session details are available,
        a secure temporary auto-login bridge is launched and immediately cleaned up.
        Otherwise, the portal URL is opened directly.

        Returns:
            bool: True if the portal URL or bridge was successfully launched.
        """
        portal_url = self.get_resolved_portal_url()
        creds = SessionService().get_portal_credentials()

        if creds and (creds.get("user_name") or creds.get("username") or creds.get("employee_id") or creds.get("indo_code")):
            # Safe logging: log non-sensitive parameter names and values, omit passwords/secrets
            safe_log_data = {
                k: v for k, v in creds.items()
                if k.lower() not in {"password", "pwd", "secret", "api_key", "key", "token", "session_credential", "device_token"}
                and v
            }
            logger.info("Initiating HRMS portal authentication for user details: %s -> %s", safe_log_data, portal_url)

            try:
                html_code = self.generate_autologin_html(
                    portal_url=portal_url,
                    username=creds,
                )

                fd, temp_path = tempfile.mkstemp(prefix="ihrms_portal_login_", suffix=".html")
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(html_code)

                # Schedule cleanup so temp file is removed shortly after launch
                _schedule_file_cleanup(temp_path, delay_seconds=8.0)

                url = QUrl.fromLocalFile(temp_path)
                opened = QDesktopServices.openUrl(url)
                if not opened:
                    webbrowser.open(f"file:///{temp_path.replace(os.sep, '/')}")
                return True

            except Exception as exc:
                logger.warning("Auto-login bridge generation failed: %s; falling back to direct URL", exc)

        # Fallback to direct portal URL
        logger.info("Opening HRMS portal directly (no auto-login credentials available): %s", portal_url)
        try:
            opened = QDesktopServices.openUrl(QUrl(portal_url))
            if not opened:
                webbrowser.open(portal_url)
            return True
        except Exception as exc:
            logger.warning("QDesktopServices.openUrl failed: %s; falling back to webbrowser", exc)
            webbrowser.open(portal_url)
            return True
