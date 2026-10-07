"""
Temporary Test Trigger Script for Workpulse Error Reporting Verification.

Executes a live test of ErrorReportService.trigger_test_error():
1. Dispatches the SAME test error via support email (SMTP) and the Workpulse report_error API.
2. Displays the exact dynamically generated test error details.
3. Displays the API request payload and live server response.
4. Displays the support email result.
5. Verifies deduplication suppresses duplicate reports.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is in python path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.error_report_service import ErrorReportService


def main() -> None:
    print("=" * 70)
    print("WORKPULSE ERROR REPORTING INTEGRATION TEST")
    print("=" * 70)
    
    service = ErrorReportService()

    # Step 1: Trigger first live test error
    print("\n[1/3] Triggering live test error across SMTP and API...")
    result_first = service.trigger_test_error(synchronous=True)

    print("\n------------------------------------------------------------")
    print("1. TEST ERROR GENERATED (DYNAMIC DETAILS)")
    print("------------------------------------------------------------")
    print(json.dumps(result_first["test_error"], indent=2, default=str))

    print("\n------------------------------------------------------------")
    print("2. API REQUEST PAYLOAD (POST /hrms_api/ci4/api/workpulse/report_error)")
    print("------------------------------------------------------------")
    # Pretty print error_payload inside request if it is a JSON string
    req = dict(result_first.get("api_request_payload") or {})
    if isinstance(req.get("error_payload"), str):
        try:
            req["error_payload_parsed"] = json.loads(req["error_payload"])
        except Exception:
            pass
    print(json.dumps(req, indent=2, default=str))

    print("\n------------------------------------------------------------")
    print("3. LIVE API RESPONSE")
    print("------------------------------------------------------------")
    print(json.dumps(result_first.get("api_response") or {}, indent=2, default=str))

    print("\n------------------------------------------------------------")
    print("4. SUPPORT EMAIL RESULT")
    print("------------------------------------------------------------")
    print(f"Email Delivered via SMTP: {result_first.get('email_result')}")

    print("\n------------------------------------------------------------")
    print("5. DUAL-CHANNEL DELIVERY CONFIRMATION")
    print("------------------------------------------------------------")
    print(f"Both Channels Working: {result_first.get('both_working')}")

    # Step 2: Trigger immediate duplicate test to verify deduplication
    print("\n[2/3] Triggering immediate duplicate test error to verify deduplication...")
    result_dup = service.trigger_test_error(synchronous=True)

    print("\n------------------------------------------------------------")
    print("DEDUPLICATION VERIFICATION")
    print("------------------------------------------------------------")
    print(f"Status: {result_dup.get('status')}")
    print(f"Duplicate Suppressed: {result_dup.get('duplicate_suppressed')}")
    print(f"Message: {result_dup.get('message')}")

    print("\n=" * 70)
    if result_first.get("both_working") and result_dup.get("duplicate_suppressed"):
        print("ALL VERIFICATION CHECKS PASSED SUCCESSFULLY")
    else:
        print("VERIFICATION CHECKS COMPLETED WITH WARNINGS")
    print("=" * 70)


if __name__ == "__main__":
    main()
