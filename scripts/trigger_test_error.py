"""
Verification and Test Script for iHRMS Desktop Error Reporting.

Verifies all requirements:
1. Local Python development -> No support email sent for normal development errors or test runs.
   Local error logging is preserved in error_reports.log.
2. Production packaged build (Windows EXE) -> Real errors send support email + report_error API.
3. Deduplication -> Suppresses duplicate errors within cooldown window.
4. Existing production error reporting continues working.
"""

from __future__ import annotations

import json
import os
import sys
import unittest.mock
from pathlib import Path

# Ensure project root is in python path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.error_report_service import ErrorReportService
from utils.paths import get_log_file_path


def main() -> None:
    print("=" * 75)
    print("iHRMS DESKTOP ERROR REPORTING VERIFICATION & VALIDATION SUITE")
    print("=" * 75)

    service = ErrorReportService()

    # -------------------------------------------------------------
    # 1. VERIFY LOCAL PYTHON DEVELOPMENT (NORMAL ERROR)
    # -------------------------------------------------------------
    print("\n[CHECK 1/4] Verifying normal developer error in local Python run...")
    print(f"Current Runtime: Frozen={getattr(sys, 'frozen', False)} (is_production_build={service.is_production_build()})")

    # Record log file size before normal error
    log_file = get_log_file_path().parent / "error_reports.log"
    size_before = log_file.stat().st_size if log_file.exists() else 0

    # Reset last results
    service._last_smtp_result = None
    service._last_api_response = None

    # Trigger normal development error
    service.report_error(
        error_type="DEV_RUNTIME_EXCEPTION",
        error_message="Developer local test exception while debugging",
        extra_context={"developer_test": True},
    )

    # Allow background thread a moment if running async
    import time
    time.sleep(0.5)

    # Confirm NO support email was sent
    check1_no_email = service._last_smtp_result is not True
    # Confirm NO production API was sent
    check1_no_api = service._last_api_response is None or service._last_api_response.get("status") == "skipped_dev"
    # Confirm local log received the error
    size_after = log_file.stat().st_size if log_file.exists() else 0
    check1_logged_locally = size_after > size_before

    print(f"  - Support Email Sent: {service._last_smtp_result is True} (Expected: False - Suppressed in Dev)")
    print(f"  - Production API Sent: {service._last_api_response.get('status_code', 0) in (200, 201) if service._last_api_response else False} (Expected: False - Suppressed in Dev)")
    print(f"  - Written to Local Log ({log_file.name}): {check1_logged_locally} (Expected: True)")
    
    passed_check1 = check1_no_email and check1_no_api and check1_logged_locally
    print(f"  -> CHECK 1 RESULT: {'PASSED' if passed_check1 else 'FAILED'}")

    # -------------------------------------------------------------
    # 2. VERIFY INTENTIONAL TEST ERROR IN DEV RUN (API ACTIVE, EMAIL SUPPRESSED)
    # -------------------------------------------------------------
    print("\n[CHECK 2/4] Verifying intentional test error trigger in developer run...")
    test_result = service.trigger_test_error(
        synchronous=True,
        force_email=False,
        force_api=True,
        clear_cooldown=True,
    )

    check2_email_status = test_result.get("email_status")
    check2_api_status = test_result.get("api_response", {}).get("status_code") in (200, 201)
    print(f"  - Email Status: {check2_email_status} (Expected: 'skipped_in_dev')")
    print(f"  - API Status Code: {test_result.get('api_response', {}).get('status_code')} (Expected: 200/201)")
    print(f"  - Both Working (Dev Policy Satisfied): {test_result.get('both_working')}")

    passed_check2 = check2_email_status == "skipped_in_dev" and check2_api_status and test_result.get("both_working")
    print(f"  -> CHECK 2 RESULT: {'PASSED' if passed_check2 else 'FAILED'}")

    # -------------------------------------------------------------
    # 3. VERIFY DEDUPLICATION COOLDOWN
    # -------------------------------------------------------------
    print("\n[CHECK 3/4] Verifying deduplication suppresses duplicate reports...")
    dup_result = service.trigger_test_error(synchronous=True, clear_cooldown=False)

    check3_dup_suppressed = dup_result.get("duplicate_suppressed") is True
    print(f"  - Duplicate Suppressed: {check3_dup_suppressed} (Expected: True)")
    print(f"  - Message: {dup_result.get('message')}")

    passed_check3 = check3_dup_suppressed
    print(f"  -> CHECK 3 RESULT: {'PASSED' if passed_check3 else 'FAILED'}")

    # -------------------------------------------------------------
    # 4. VERIFY PRODUCTION PACKAGED BUILD BEHAVIOR (SIMULATED OR EXECUTABLE)
    # -------------------------------------------------------------
    print("\n[CHECK 4/4] Verifying production packaged environment behavior...")
    # In production build (sys.frozen = True), real error dispatches BOTH support email and API
    with unittest.mock.patch.object(sys, "frozen", True, create=True):
        print(f"  - Simulated Runtime: is_production_build={service.is_production_build()}")
        prod_result = service.trigger_test_error(
            synchronous=True,
            force_email=False,  # Automatically enabled in production build!
            force_api=True,
            clear_cooldown=True,
        )

        prod_email_sent = prod_result.get("email_status") == "sent" and prod_result.get("email_result") is True
        prod_api_sent = prod_result.get("api_response", {}).get("status_code") in (200, 201)
        prod_both = prod_result.get("both_working") is True

        print(f"  - Production Support Email Sent (SMTP): {prod_email_sent} (Expected: True)")
        print(f"  - Production API Response Code: {prod_result.get('api_response', {}).get('status_code')} (Expected: 200/201)")
        print(f"  - Dynamic Details Included: exception={prod_result['test_error']['exception_type']}, file={prod_result['test_error']['file']}, line={prod_result['test_error']['line']}")
        print(f"  - Both Working: {prod_both}")

        passed_check4 = prod_email_sent and prod_api_sent and prod_both
        print(f"  -> CHECK 4 RESULT: {'PASSED' if passed_check4 else 'FAILED'}")

    # -------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------
    print("\n" + "=" * 75)
    all_passed = passed_check1 and passed_check2 and passed_check3 and passed_check4
    if all_passed:
        print("ALL 4 VERIFICATION CHECKS PASSED PERFECTLY!")
    else:
        print("ONE OR MORE CHECKS RETURNED UNEXPECTED RESULTS.")
    print("=" * 75)


if __name__ == "__main__":
    main()
