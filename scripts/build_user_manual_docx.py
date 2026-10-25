"""
iHRMS Desktop User Manual (.docx) Generator
Generates a complete, professional, screenshot-based user manual for Windows and macOS.
Follows strict enterprise formatting, numbered figure captions, storage formulas,
and business-level backend configuration explanations (no technical API endpoints or URLs).
"""

import os
import sys
from datetime import datetime

import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(BASE_DIR, "docs")
SCREENSHOTS_DIR = os.path.join(DOCS_DIR, "screenshots")
OUTPUT_FILE = os.path.join(DOCS_DIR, "iHRMS_Desktop_User_Manual.docx")
os.makedirs(DOCS_DIR, exist_ok=True)

# ----------------------------------------------------------------------
# Professional Corporate Color Palette
# ----------------------------------------------------------------------
NAVY_PRIMARY = RGBColor(15, 44, 89)      # #0F2C59 Deep Corporate Navy
ACCENT_BLUE  = RGBColor(37, 99, 235)     # #2563EB Slate Accent Blue
DARK_TEXT    = RGBColor(30, 41, 59)      # #1E293B Slate 800
MUTED_TEXT   = RGBColor(100, 116, 139)   # #64748B Slate 500
SUCCESS_GREEN= RGBColor(22, 163, 74)     # #16A34A Emerald Green
WARNING_AMBER= RGBColor(217, 119, 6)     # #D97706 Amber
BORDER_GRAY  = RGBColor(226, 232, 240)   # #E2E8F0 Light Slate Border

HEX_HEADER_BG = "0F2C59"
HEX_ALT_ROW   = "F8FAFC"
HEX_CALLOUT_BG= "F1F5F9"
HEX_BORDER    = "CBD5E1"


def set_cell_background(cell, fill_hex: str):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)


def set_cell_margins(cell, top=120, bottom=120, left=160, right=160):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    )
    tcPr.append(tcMar)


def set_cell_border(cell, top=None, bottom=None, left=None, right=None):
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>'
        f'<w:top w:val="{top or "none"}" w:sz="4" w:space="0" w:color="{HEX_BORDER}"/>'
        f'<w:left w:val="{left or "none"}" w:sz="4" w:space="0" w:color="{HEX_BORDER}"/>'
        f'<w:bottom w:val="{bottom or "none"}" w:sz="4" w:space="0" w:color="{HEX_BORDER}"/>'
        f'<w:right w:val="{right or "none"}" w:sz="4" w:space="0" w:color="{HEX_BORDER}"/>'
        f'</w:tcBorders>'
    )
    tcPr.append(tcBorders)


def add_cover_page(doc):
    """Create a high-impact corporate cover page."""
    p_top = doc.add_paragraph()
    p_top.paragraph_format.space_before = Pt(36)
    p_top.paragraph_format.space_after = Pt(6)
    r_org = p_top.add_run("INDOVISION ENTERPRISE WORKFORCE SOLUTIONS")
    r_org.font.name = "Segoe UI"
    r_org.font.size = Pt(11)
    r_org.font.bold = True
    r_org.font.color.rgb = ACCENT_BLUE

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(8)
    p_title.paragraph_format.space_after = Pt(8)
    r_title = p_title.add_run("iHRMS Desktop")
    r_title.font.name = "Segoe UI"
    r_title.font.size = Pt(36)
    r_title.font.bold = True
    r_title.font.color.rgb = NAVY_PRIMARY

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_before = Pt(0)
    p_sub.paragraph_format.space_after = Pt(20)
    r_sub = p_sub.add_run("Official User, Administration & Telemetry Manual")
    r_sub.font.name = "Segoe UI"
    r_sub.font.size = Pt(16)
    r_sub.font.color.rgb = MUTED_TEXT

    p_rule = doc.add_paragraph()
    p_rule.paragraph_format.space_after = Pt(36)
    r_rule = p_rule.add_run("―" * 55)
    r_rule.font.color.rgb = ACCENT_BLUE

    p_desc = doc.add_paragraph()
    p_desc.paragraph_format.line_spacing = 1.25
    p_desc.paragraph_format.space_after = Pt(70)
    r_desc = p_desc.add_run(
        "A comprehensive operational guide to the iHRMS Desktop client for Windows and macOS. "
        "Details employee attendance logging, timesheet & KRA management, workstation activity tracking, "
        "workstation lock & display-off state detection, automated screenshot policies, offline buffering, "
        "and enterprise fleet synchronization."
    )
    r_desc.font.name = "Segoe UI"
    r_desc.font.size = Pt(11)
    r_desc.font.color.rgb = DARK_TEXT

    meta_table = doc.add_table(rows=5, cols=2)
    meta_table.alignment = WD_TABLE_ALIGNMENT.LEFT
    meta_table.autofit = False

    meta_items = [
        ("Application Version:", "1.0.0 (Authoritative Release)"),
        ("Target Platforms:", "Windows 10/11 x64, macOS 11.0+ (Universal)"),
        ("Target Audience:", "Employees, Human Resources, IT Operations, Management"),
        ("Publication Date:", "October 2026"),
        ("Document Classification:", "Confidential — Enterprise Operational Standard"),
    ]

    for row_idx, (k, v) in enumerate(meta_items):
        c0 = meta_table.cell(row_idx, 0)
        c1 = meta_table.cell(row_idx, 1)
        c0.width = Inches(2.2)
        c1.width = Inches(4.5)
        
        p0 = c0.paragraphs[0]
        p0.paragraph_format.space_before = Pt(3)
        p0.paragraph_format.space_after = Pt(3)
        r0 = p0.add_run(k)
        r0.font.name = "Segoe UI"
        r0.font.size = Pt(9.5)
        r0.font.bold = True
        r0.font.color.rgb = NAVY_PRIMARY

        p1 = c1.paragraphs[0]
        p1.paragraph_format.space_before = Pt(3)
        p1.paragraph_format.space_after = Pt(3)
        r1 = p1.add_run(v)
        r1.font.name = "Segoe UI"
        r1.font.size = Pt(9.5)
        r1.font.color.rgb = DARK_TEXT
        if "1.0.0" in v:
            r1.font.bold = True
            r1.font.color.rgb = ACCENT_BLUE

    doc.add_page_break()


def add_h1(doc, text: str):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(20)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.font.name = "Segoe UI"
    r.font.size = Pt(16)
    r.font.bold = True
    r.font.color.rgb = NAVY_PRIMARY
    return p


def add_h2(doc, text: str):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.font.name = "Segoe UI"
    r.font.size = Pt(13)
    r.font.bold = True
    r.font.color.rgb = ACCENT_BLUE
    return p


def add_h3(doc, text: str):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(9)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.font.name = "Segoe UI"
    r.font.size = Pt(11)
    r.font.bold = True
    r.font.color.rgb = DARK_TEXT
    return p


def add_p(doc, text: str):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.line_spacing = 1.15
    r = p.add_run(text)
    r.font.name = "Segoe UI"
    r.font.size = Pt(10)
    r.font.color.rgb = DARK_TEXT
    return p


def add_bullet(doc, bold_prefix: str, text: str):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(2.5)
    p.paragraph_format.line_spacing = 1.15

    r_bold = p.add_run(bold_prefix + ": ")
    r_bold.font.name = "Segoe UI"
    r_bold.font.size = Pt(9.5)
    r_bold.font.bold = True
    r_bold.font.color.rgb = DARK_TEXT

    r_text = p.add_run(text)
    r_text.font.name = "Segoe UI"
    r_text.font.size = Pt(9.5)
    r_text.font.color.rgb = DARK_TEXT
    return p


def add_callout(doc, callout_type: str, title: str, text: str):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    cell = table.cell(0, 0)
    cell.width = Inches(6.8)
    set_cell_background(cell, HEX_CALLOUT_BG)
    set_cell_margins(cell, top=100, bottom=100, left=140, right=140)

    color_map = {
        "NOTE": ACCENT_BLUE,
        "TIP": SUCCESS_GREEN,
        "IMPORTANT": NAVY_PRIMARY,
        "WARNING": WARNING_AMBER,
        "PRIVACY": NAVY_PRIMARY,
    }
    c_color = color_map.get(callout_type.upper(), NAVY_PRIMARY)

    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.15

    r_badge = p.add_run(f"[{callout_type.upper()}: {title}] ")
    r_badge.font.name = "Segoe UI"
    r_badge.font.size = Pt(9.5)
    r_badge.font.bold = True
    r_badge.font.color.rgb = c_color

    r_body = p.add_run(text)
    r_body.font.name = "Segoe UI"
    r_body.font.size = Pt(9.5)
    r_body.font.color.rgb = DARK_TEXT

    p_after = doc.add_paragraph()
    p_after.paragraph_format.space_before = Pt(0)
    p_after.paragraph_format.space_after = Pt(4)


def add_styled_table(doc, headers: list[str], rows: list[list[str]], col_widths: list[float] | None = None):
    table = doc.add_table(rows=len(rows) + 1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    for col_idx, title in enumerate(headers):
        cell = table.cell(0, col_idx)
        if col_widths and col_idx < len(col_widths):
            cell.width = Inches(col_widths[col_idx])
        set_cell_background(cell, HEX_HEADER_BG)
        set_cell_margins(cell, top=100, bottom=100, left=120, right=120)
        set_cell_border(cell, bottom="single")
        
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(title)
        run.font.name = "Segoe UI"
        run.font.size = Pt(9)
        run.font.bold = True
        run.font.color.rgb = RGBColor(255, 255, 255)

    for row_idx, row_data in enumerate(rows):
        is_alt = (row_idx % 2 == 1)
        for col_idx, val in enumerate(row_data):
            cell = table.cell(row_idx + 1, col_idx)
            if col_widths and col_idx < len(col_widths):
                cell.width = Inches(col_widths[col_idx])
            if is_alt:
                set_cell_background(cell, HEX_ALT_ROW)
            set_cell_margins(cell, top=80, bottom=80, left=120, right=120)
            set_cell_border(cell, bottom="single")

            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.15
            run = p.add_run(str(val))
            run.font.name = "Segoe UI"
            run.font.size = Pt(9)
            run.font.color.rgb = DARK_TEXT

    p_after = doc.add_paragraph()
    p_after.paragraph_format.space_before = Pt(2)
    p_after.paragraph_format.space_after = Pt(6)


def add_figure(doc, image_filename: str, caption_num: int, caption_title: str, description: str, width_inches: float = 6.2):
    img_path = os.path.join(SCREENSHOTS_DIR, image_filename)
    if not os.path.exists(img_path):
        add_callout(doc, "WARNING", f"Figure {caption_num} Verification Required", f"Screenshot {image_filename} is not found on disk.")
        return

    p_img = doc.add_paragraph()
    p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_img.paragraph_format.space_before = Pt(8)
    p_img.paragraph_format.space_after = Pt(4)
    run_img = p_img.add_run()
    run_img.add_picture(img_path, width=Inches(width_inches))

    p_cap = doc.add_paragraph()
    p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_cap.paragraph_format.space_before = Pt(2)
    p_cap.paragraph_format.space_after = Pt(3)
    p_cap.paragraph_format.keep_with_next = True

    r_num = p_cap.add_run(f"Figure {caption_num}: ")
    r_num.font.name = "Segoe UI"
    r_num.font.size = Pt(9)
    r_num.font.bold = True
    r_num.font.color.rgb = NAVY_PRIMARY

    r_title = p_cap.add_run(caption_title)
    r_title.font.name = "Segoe UI"
    r_title.font.size = Pt(9)
    r_title.font.bold = True
    r_title.font.color.rgb = DARK_TEXT

    p_desc = doc.add_paragraph()
    p_desc.paragraph_format.space_before = Pt(1)
    p_desc.paragraph_format.space_after = Pt(10)
    p_desc.paragraph_format.line_spacing = 1.15
    r_desc = p_desc.add_run(f"Caption Note: {description}")
    r_desc.font.name = "Segoe UI"
    r_desc.font.size = Pt(8.5)
    r_desc.font.italic = True
    r_desc.font.color.rgb = MUTED_TEXT


def build_manual_document():
    doc = docx.Document()

    # Set 0.75-inch margins
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    print("Generating Cover Page...")
    add_cover_page(doc)

    # ------------------------------------------------------------------
    # Table of Contents & Executive Summary
    # ------------------------------------------------------------------
    add_h1(doc, "Table of Contents")
    toc_items = [
        ("Section 1", "Introduction, Purpose & System Architecture"),
        ("Section 2", "System Requirements & Multi-Platform Installation"),
        ("Section 3", "First-Time Setup, Company Verification & Secure Authentication"),
        ("Section 4", "Comprehensive Feature-by-Feature Operational Walkthrough"),
        ("Section 5", "Activity Tracking Engine, Idle Detection & Workstation Lock Lifecycle"),
        ("Section 6", "Screenshot Capture Engine, Compression & Storage Calculations"),
        ("Section 7", "Enterprise Backend Configuration & Policy Administration"),
        ("Section 8", "Synchronization, Offline Resilience & Background Auto-Updates"),
        ("Section 9", "Security Architecture, Employee Privacy & Compliance Guidelines"),
        ("Section 10", "Troubleshooting, FAQs & Platform Differences Matrix"),
    ]
    for sec_num, sec_title in toc_items:
        p_toc = doc.add_paragraph()
        p_toc.paragraph_format.space_before = Pt(2)
        p_toc.paragraph_format.space_after = Pt(3)
        r_num = p_toc.add_run(f"{sec_num}: ")
        r_num.font.name = "Segoe UI"
        r_num.font.size = Pt(10)
        r_num.font.bold = True
        r_num.font.color.rgb = ACCENT_BLUE

        r_title = p_toc.add_run(sec_title)
        r_title.font.name = "Segoe UI"
        r_title.font.size = Pt(10)
        r_title.font.color.rgb = DARK_TEXT

    add_h1(doc, "Executive Summary")
    add_p(doc, 
        "The iHRMS Desktop application (version 1.0.0) is an enterprise-grade desktop productivity agent "
        "designed for organizations utilizing the centralized iHRMS workforce platform. Built on Python and "
        "PySide6 (Qt6), the application provides seamless, automated visibility into employee desktop activity, "
        "timesheet completion, KRA task fulfillment, attendance validation, and periodic visual audit verification."
    )
    add_p(doc,
        "Designed with an offline-first architecture, iHRMS Desktop guarantees 100% data integrity even during prolonged "
        "network outages. Tracking telemetry and compressed screenshots are staged securely in local user storage "
        "and automatically uploaded to company systems once network connectivity is re-established. Following verified "
        "server confirmation, local screenshots are pruned to protect client disk resources. This manual serves as "
        "the authoritative standard operating procedure for employees, administrators, and human resource teams."
    )

    # ------------------------------------------------------------------
    # SECTION 1: Introduction & System Architecture
    # ------------------------------------------------------------------
    add_h1(doc, "1. Introduction, Purpose & System Architecture")
    add_p(doc,
        "iHRMS Desktop bridges modern distributed workplace operations with centralized workforce management. "
        "Traditional HRMS portals record when an employee punches in or requests leave, but fail to provide objective, "
        "verifiable metrics on project time investment, task completion rates, or active focus time. "
        "iHRMS Desktop solves these challenges without imposing cumbersome manual time tracking on employees."
    )
    
    add_h2(doc, "1.1 Key Operational Objectives")
    add_bullet(doc, "Automated Time Tracking", "Eliminates manual timesheet estimation by polling the active foreground application every 5 seconds, accurately recording start time, end time, and active duration.")
    add_bullet(doc, "Intelligent Idle Attribution", "Detects when an employee steps away from their keyboard or mouse and attributes idle duration directly to the last active application upon resumption.")
    add_bullet(doc, "Visual Audit Verification", "Periodically captures lightweight, highly compressed desktop screenshots according to assigned company policy to confirm active work engagement.")
    add_bullet(doc, "Guaranteed Offline Recording", "Ensures mobile or traveling staff continue tracking without interruption during flights or connection drops using local SQLite buffering.")
    add_bullet(doc, "Cryptographic Device Binding", "Locks each telemetry session to an enrolled physical workstation using hardware UUID fingerprints, preventing credential sharing or ghost logins.")
    add_bullet(doc, "Zero-Touch Maintenance", "Automated background update pipeline ensures client endpoints stay synchronized with the latest enterprise releases without IT intervention.")

    add_h2(doc, "1.2 Architectural Component Overview")
    arch_headers = ["Component", "Location", "Primary Responsibility"]
    arch_rows = [
        ["Desktop UI Client", "Local Endpoints (Win/macOS)", "Provides employee dashboard, punch status, attendance calendar, KRA timesheet, and leave quota views."],
        ["Activity Tracker Engine", "Background Worker Thread", "Polls active window title, process ID, and user input every 5 seconds. Manages active/idle state transitions."],
        ["Screenshot Service", "Background Capture Engine", "Captures desktop screen on configured intervals; compresses images exceeding 100 KB using color quantization."],
        ["Local SQLite Database", "%LOCALAPPDATA% / ~/Library", "Stores un-synchronized activity logs, heartbeat records, and pending uploads with zero data loss."],
        ["Sync Service", "Asynchronous Worker", "Periodically delivers batched logs to the central company system and cleans up local screenshots upon server confirmation."],
        ["Network Monitor", "Continuous Listener", "Monitors active network reachability to prevent UI freezing and control synchronization retry timers."],
        ["Central Company System", "Cloud / Enterprise Datacenter", "Authenticates tenant company codes, evaluates employee roles, stores telemetry, and delivers dynamic fleet policies."],
    ]
    add_styled_table(doc, arch_headers, arch_rows, [1.6, 2.0, 3.2])

    # ------------------------------------------------------------------
    # SECTION 2: System Requirements & Installation
    # ------------------------------------------------------------------
    add_h1(doc, "2. System Requirements & Multi-Platform Installation")
    add_p(doc, "iHRMS Desktop is engineered to run seamlessly on both Windows and macOS enterprise workstations.")

    add_h2(doc, "2.1 Hardware and Operating System Requirements")
    req_headers = ["Specification", "Minimum Requirement", "Recommended Specification"]
    req_rows = [
        ["Operating System (Windows)", "Windows 10 x64 (Version 1809+)", "Windows 11 Pro / Enterprise x64 (22H2+)"],
        ["Operating System (macOS)", "macOS 11.0 Big Sur (Intel or Apple Silicon)", "macOS 14.0 Sonoma / macOS 15.0 Sequoia (M-Series)"],
        ["Processor (CPU)", "1.6 GHz Dual-Core (x86_64 or ARM64)", "2.0 GHz+ Quad-Core or Apple Silicon (M1/M2/M3)"],
        ["Memory (RAM)", "4 GB System Memory", "8 GB+ System Memory"],
        ["Local Storage", "150 MB available for application binaries", "500 MB+ available for temporary offline cache buffering"],
        ["Display Resolution", "1280 × 720 minimum resolution", "1920 × 1080 or higher (HiDPI / Retina supported)"],
        ["Network Connectivity", "Periodic internet access for synchronization", "Broadband connection (Wi-Fi or Ethernet)"],
    ]
    add_styled_table(doc, req_headers, req_rows, [2.0, 2.4, 2.4])

    add_h2(doc, "2.2 Windows Installation Guide")
    add_p(doc, 
        "iHRMS Desktop is distributed as a single signed Windows installer package (`iHRMS-Desktop-Setup.exe`) "
        "built using Inno Setup. It installs in per-user mode, allowing employees to install the agent without "
        "requiring local administrative privileges."
    )
    add_bullet(doc, "Step 1: Download Installer", "Obtain the verified `iHRMS-Desktop-Setup.exe` file from your corporate portal or IT department.")
    add_bullet(doc, "Step 2: Run Setup Wizard", "Double-click the installer. The wizard will install the software to `%LOCALAPPDATA%\\Programs\\iHRMS Desktop\\`.")
    add_bullet(doc, "Step 3: Auto-Start Configuration", "The installer automatically registers iHRMS Desktop in the current user's Windows startup registry (`HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`) so it launches automatically on boot.")
    add_bullet(doc, "Step 4: Silent IT Deployment", "System administrators can deploy the application across corporate fleets silently using the command: `iHRMS-Desktop-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`.")

    add_h2(doc, "2.3 macOS Installation Guide & Screen Recording Permission")
    add_p(doc, 
        "On macOS, iHRMS Desktop is distributed as an Apple Universal Disk Image (`iHRMS-Desktop-1.0.0.dmg`) "
        "compatible with both Intel-based Macs and Apple Silicon (M1/M2/M3/M4) devices."
    )
    add_bullet(doc, "Step 1: Mount DMG", "Double-click `iHRMS-Desktop-1.0.0.dmg` to mount the disk image.")
    add_bullet(doc, "Step 2: Install Application", "Drag the `iHRMS Desktop` icon into the `/Applications` folder shortcut.")
    add_bullet(doc, "Step 3: Launch Application", "Open iHRMS Desktop from Launchpad or Finder. macOS Gatekeeper will verify the bundle.")
    
    add_callout(doc, "IMPORTANT", "macOS Screen Recording Permission (TCC Requirement)",
        "Under macOS security architecture (Transparency, Consent, and Control), applications capturing screenshots "
        "require explicit user authorization. Upon first launch, iHRMS Desktop will display an onboarding prompt. "
        "Users must open 'System Settings' -> 'Privacy & Security' -> 'Screen Recording', toggle 'iHRMS Desktop' ON, "
        "and select 'Quit & Reopen'. If permission is withheld, attendance and timesheets will function normally, "
        "but screenshot capture will remain paused."
    )

    # ------------------------------------------------------------------
    # SECTION 3: First-Time Setup & Authentication
    # ------------------------------------------------------------------
    add_h1(doc, "3. First-Time Setup, Company Verification & Authentication")
    add_p(doc,
        "To guarantee multi-tenant security and prevent unauthorized access, iHRMS Desktop employs a two-stage "
        "authentication process: corporate tenant verification followed by employee authentication and hardware binding."
    )

    add_h2(doc, "3.1 Stage 1: Multi-Tenant Company Code Verification")
    add_p(doc,
        "When launching iHRMS Desktop for the first time, users are presented with the Company Code verification screen. "
        "The Company Code (e.g., 'INDOVISION') identifies your organization's unique cloud tenant."
    )
    add_bullet(doc, "Tenant Isolation", "Validating the company code ensures that your endpoint communicates exclusively with your organization's designated cloud environment.")
    add_bullet(doc, "Input Lock", "Upon entering the code and clicking 'Verify Company', the field is validated against the central directory and locked with a green verification indicator.")
    
    add_figure(doc, "fig01_login_company_code.png", 1, "Company Code Verification Step", 
        "Initial launch screen displaying the company code entry field and corporate hero panel. "
        "Clicking 'Verify Company' locks the tenant configuration before displaying credential fields."
    )

    add_h2(doc, "3.2 Stage 2: Employee Authentication & Statutory Consent")
    add_p(doc,
        "Once the company tenant is verified, the interface smoothly expands to reveal employee credential inputs "
        "and the mandatory activity monitoring consent notice."
    )
    add_bullet(doc, "Credential Input", "Enter your assigned Employee ID, corporate email address, or username, followed by your corporate password.")
    add_bullet(doc, "Password Visibility Toggle", "Click the eye icon inside the password field to temporarily unmask characters when typing complex passwords.")
    add_bullet(doc, "Mandatory Monitoring Consent", "In compliance with enterprise privacy standards, users must tick the consent acknowledgment box ('By logging in to iHRMS Desktop, you acknowledge and give your consent to your activity information for iHRMS Desktop productivity monitoring'). The 'Login' button remains disabled until consent is accepted.")
    add_bullet(doc, "Secure Credential Storage", "Credentials and session tokens are never saved in plain text. On Windows, credentials are encrypted in Windows Credential Manager; on macOS, they are stored in the system Keychain.")

    add_figure(doc, "fig02_login_credentials.png", 2, "Employee Authentication & Consent Screen", 
        "Credentials entry showing locked company code, employee identifier, password field with visibility toggle, "
        "statutory tracking consent checkbox, and the activated 'Login' button."
    )

    add_h2(doc, "3.3 Stage 3: Hardware Fingerprinting & Cryptographic Device Binding")
    add_p(doc,
        "During successful authentication, the application automatically extracts a deterministic hardware fingerprint "
        "from the workstation's BIOS/Motherboard UUID (Windows) or IOPlatformUUID (macOS). The workstation is registered "
        "with your corporate profile and issued a scoped device token. This cryptographic binding ensures that activity logs "
        "can only originate from enrolled physical machines, preventing session duplication or unauthorized proxy logins."
    )

    # ------------------------------------------------------------------
    # SECTION 4: Comprehensive Feature Walkthrough
    # ------------------------------------------------------------------
    add_h1(doc, "4. Comprehensive Feature-by-Feature Walkthrough")
    add_p(doc, "This section provides an illustrated walkthrough of every operational screen and dialog in iHRMS Desktop.")

    add_h2(doc, "4.1 Main Application Window & Dashboard Overview")
    add_p(doc,
        "Upon logging in, the user arrives at the primary Dashboard. The window header displays the application brand, "
        "personalized employee greeting, real-time activity status badge, an external shortcut button to open the "
        "central iHRMS web portal, and the Logout button."
    )
    add_bullet(doc, "Today's Time Card", "Displays total Active Time accumulated today in HH:MM:SS format. Includes a direct 'Attendance →' navigation button.")
    add_bullet(doc, "Attendance Card", "Highlights today's punch status (Punched In / Not Punched), System Start time (detected on workstation boot), and first Punch In time.")
    add_bullet(doc, "Status Card", "Shows real-time Network Connectivity (● Online / ● Offline), Installed App Version (v1.0.0 clickable badge), Current Idle Time counter, and Last Sync timestamp.")
    add_bullet(doc, "WorkPulse Toggle Button", "A single, prominent action button displaying 'Paused' when tracking is actively running, and 'Resume' when tracking is paused by the employee.")

    add_figure(doc, "fig03_dashboard_main.png", 3, "Main Application Window & Dashboard Overview", 
        "Primary dashboard interface showing employee greeting ('Welcome, Priya Sharma'), Active Time metric card, "
        "today's attendance summary, live status card with v1.0.0 version badge, and the Timesheet table."
    )

    add_h2(doc, "4.2 Attendance Calendar & Monthly Analytics")
    add_p(doc,
        "Clicking the 'Attendance' tab or the 'Attendance →' button opens the full-page Monthly Attendance Calendar. "
        "The interface uses a clean, two-column enterprise layout designed for immediate scannability."
    )
    add_bullet(doc, "Left Sidebar Analytics", "Features a circular conic-gradient Attendance Ring Gauge displaying monthly attendance percentage (e.g., 91%), attendance rating badge ('Good' / 'Excellent'), and summary statistics counters.")
    add_bullet(doc, "Summary Stat Breakdown", "Counts exact totals for Working Days, Present days, Absent days, Missed Punches, Half Days, Leaves/Holidays, and Week Offs.")
    add_bullet(doc, "Attendance Distribution Bar", "Segmented color bar showing the proportional distribution of attendance statuses across the calendar month.")
    add_bullet(doc, "7-Column Calendar Grid", "Displays the full month from Sunday through Saturday. Each date cell is stamped with a colored status badge: green for Present (P), blue for Week Off (WO), purple for Leave (L), and red for Absent (A).")
    add_bullet(doc, "Date Inspection", "Clicking any calendar date displays punch-in, punch-out, and active duration details for that specific working day.")

    add_figure(doc, "fig04_attendance_calendar.png", 4, "Monthly Attendance Calendar & Analytics Page", 
        "Full-screen attendance view displaying circular attendance progress ring gauge (91%), statistical summary counters, "
        "and interactive monthly calendar grid with color-coded status badges."
    )

    add_h2(doc, "4.3 Timesheet & KRA Task Progress Management")
    add_p(doc,
        "Directly below the top dashboard metric cards sits the Timesheet & KRA table. This table reflects the employee's "
        "assigned Key Result Areas (KRAs) and deliverables for the current working day, loaded dynamically from company systems."
    )
    add_bullet(doc, "Table Columns", "Each row displays: S.No, Task Name & Description, Assigned Target, Task Done Till Now, Weightage (%), and employee Remarks/Comments.")
    add_bullet(doc, "Dynamic Alignment", "Task progress and completion percentages correlate directly with the centralized iHRMS portal, ensuring consistent reporting across desktop and web interfaces.")
    add_bullet(doc, "Save Draft vs Submit", "'Save Draft' allows employees to stage their work progress throughout the day. 'Submit Timesheet' finalizes and locks daily submissions for supervisor evaluation.")

    add_figure(doc, "fig05_timesheet_kra.png", 5, "Timesheet & Assigned KRA Tasks Table", 
        "Detailed view of assigned tasks table displaying task descriptions, target goals, task done till now progress, "
        "weightage allocation, remarks input fields, and submission controls."
    )

    add_h2(doc, "4.4 Daily Ad-Hoc & Additional Tasks Logger")
    add_p(doc,
        "Work often requires handling urgent issues, cross-team assistance, or unplanned deliverables outside pre-assigned KRAs. "
        "The Additional Tasks widget provides a dedicated workflow to document these contributions."
    )
    add_bullet(doc, "Project Selector", "Select the specific corporate client or internal project from the dropdown menu.")
    add_bullet(doc, "Task Title & Description", "Input a concise task headline and detailed narrative of work completed.")
    add_bullet(doc, "Hours Logged", "Specify time spent using the numeric hours spinbox (e.g., 2.5 hours).")
    add_bullet(doc, "Instant Sync", "Clicking 'Save Task' records the entry and links it directly to your daily timesheet record.")

    add_figure(doc, "fig06_additional_tasks.png", 6, "Additional Task & Ad-Hoc Activity Logger", 
        "Daily activity logger form showing project title input, multi-line activity description, hours spent spinbox, "
        "and the 'Save Task' submission button."
    )

    add_h2(doc, "4.5 Leave Balance & Quota Analysis")
    add_p(doc,
        "Employees can view their statutory leave allocations and remaining balances by opening the Leave Balance modal. "
        "The dialog standardizes leave types into 7 fixed statutory enterprise categories."
    )
    add_bullet(doc, "1. Casual Leave (CL)", "Allocated for personal, urgent, or unforeseen short-term matters.")
    add_bullet(doc, "2. Sick Leave (SL)", "Medical and health-related recuperation quota.")
    add_bullet(doc, "3. Comp Off (CO)", "Compensatory days earned by working on scheduled week offs or national holidays.")
    add_bullet(doc, "4. Business Trip (OD)", "Official duty and client travel authorization quota.")
    add_bullet(doc, "5. Leave Without Pay (LWP)", "Unpaid leave taken beyond allotted quotas.")
    add_bullet(doc, "6. Paid / Earned Leave (EL)", "Annual earned privilege leave for vacations and planned absences.")
    add_bullet(doc, "7. Restricted / Floating Holiday (RH)", "Discretionary cultural or regional festival holidays.")
    add_bullet(doc, "Interactive View Toggle", "Switch seamlessly between a modern grouped Bar Chart (Total = Blue, Used = Red, Left = Green) and a structured numeric Table View.")

    add_figure(doc, "fig07_leave_balance.png", 7, "Leave Balance & Quota Analysis Dialog", 
        "Modal dialog showing the 7 fixed statutory leave types, visual bar chart comparison of total quota versus utilized days, "
        "and remaining leave balance indicators."
    )

    add_h2(doc, "4.6 User Preferences & Configurable Settings")
    add_p(doc,
        "The Settings dialog allows employees and system administrators to inspect and customize client operation. "
        "While security policies are enforced remotely, local preferences can be adjusted directly."
    )
    add_bullet(doc, "Start with System", "Toggle whether iHRMS Desktop launches automatically upon workstation startup.")
    add_bullet(doc, "Idle Threshold", "Configurable spinbox (1 to 120 minutes; default 5 minutes) defining inactivity duration before switching to Idle state.")
    add_bullet(doc, "Track Window Titles", "Enables or disables capturing specific application window titles alongside executable names.")
    add_bullet(doc, "Screenshot Interval", "Inspect or select capture frequencies (3 minutes, 5 minutes, 10 minutes, or Custom).")
    add_bullet(doc, "Capture on Switch", "Optional toggle to trigger a screenshot when the user switches between major active applications.")

    add_figure(doc, "fig08_settings_dialog.png", 8, "Settings & Client Preferences Dialog", 
        "Preferences dialog displaying system startup toggle, idle threshold spinbox, window title tracking checkbox, "
        "and screenshot capture interval configuration controls."
    )

    add_h2(doc, "4.7 In-App Software Update Management")
    add_p(doc,
        "iHRMS Desktop incorporates a silent, reliable auto-update mechanism that eliminates the need for manual re-installation "
        "when new versions are released."
    )
    add_bullet(doc, "Automatic Background Checks", "The application queries for updates 2 seconds after startup and every 2 hours thereafter.")
    add_bullet(doc, "Header Alert Notification", "When an update is verified, a prominent '🚀 Update Available' button appears in the window header.")
    add_bullet(doc, "Update Notification Dialog", "Displays the new version number, current version (v1.0.0), download progress bar, and installation options.")
    add_bullet(doc, "One-Click Restart", "Clicking 'Install & Restart' launches a detached installer helper, cleanly exits the running client, installs the update silently, and relaunches the application.")

    add_figure(doc, "fig09_software_update.png", 9, "Software Update Notification Dialog", 
        "Update dialog announcing new verified version availability, displaying download progress, release summary, "
        "and one-click 'Install & Restart' button."
    )

    add_h2(doc, "4.8 User, Device & Fleet Update Verification")
    add_p(doc,
        "To assist IT support and confirm hardware enrollment, clicking the user profile or status card opens the "
        "User & Device dialog."
    )
    add_bullet(doc, "User Identity", "Confirms Employee Name, Employee ID, Username, Email, and Assigned Role.")
    add_bullet(doc, "Workstation Telemetry", "Displays Device Hostname, Operating System build, and Hardware Identifier UUID.")
    add_bullet(doc, "Installed App Version", "Shows `1.0.0 (authoritative build)` in bold blue text, confirming exact running version.")
    add_bullet(doc, "Fleet Update Status", "Shows green 'Update Successful' badge confirming client software integrity.")

    add_figure(doc, "fig10_device_verification.png", 10, "User & Device Fleet Verification Dialog", 
        "Verification dialog detailing employee profile, hardware fingerprint identifier, operating system platform, "
        "authoritative build version (1.0.0), and fleet update status."
    )

    add_h2(doc, "4.9 Version History & Release Notes")
    add_p(doc,
        "Clicking the 'Version: 1.0.0' button on the Status card opens the Release Summary dialog, detailing "
        "enhancements, performance optimizations, and security patches included in the current build."
    )

    add_figure(doc, "fig11_release_notes.png", 11, "Release Summary & Version History Dialog", 
        "Release notes viewer displaying verified version 1.0.0 release date, changelog highlights, and operational notes."
    )

    add_h2(doc, "4.10 System Tray Integration & Background Operation")
    add_p(doc,
        "Closing the main window does not terminate activity tracking. The application minimizes cleanly to the "
        "system notification area (system tray on Windows; menu bar extra on macOS)."
    )
    add_bullet(doc, "Background Execution", "Tracking, idle timers, and screenshot schedules continue operating smoothly while minimized.")
    add_bullet(doc, "Context Menu Quick Actions", "Right-clicking the tray icon provides quick access to: 'Open iHRMS Desktop', 'Status: Tracking Active', 'View Attendance Calendar', 'Check for Updates', 'Open Web Portal', and 'Exit Application'.")

    add_figure(doc, "fig12_system_tray.png", 12, "System Tray Menu & Quick Action Controls", 
        "Desktop system tray context menu providing quick status verification, rapid navigation, and background application controls."
    )

    # ------------------------------------------------------------------
    # SECTION 5: Activity Tracking & State Lifecycle
    # ------------------------------------------------------------------
    add_h1(doc, "5. Activity Tracking Engine, Idle Detection & Workstation Lock Lifecycle")
    add_p(doc,
        "The iHRMS Desktop activity tracking engine operates as an independent, lightweight background worker. "
        "It polls the operating system every 5 seconds to capture active window attributes and monitor user physical input."
    )

    add_h2(doc, "5.1 Telemetry Data Points Collected")
    add_p(doc, "For every foreground application transition, the tracker logs:")
    add_bullet(doc, "Application Executable Name", "The process name of the active foreground program (e.g., `Code.exe`, `chrome.exe`, `excel.exe`).")
    add_bullet(doc, "Window Title", "The title bar text of the foreground window (unless window title tracking is disabled).")
    add_bullet(doc, "Process Identifier (PID)", "The operating system process ID for audit disambiguation.")
    add_bullet(doc, "Start & End Timestamps", "Exact chronological start and conclusion times for the active session.")
    add_bullet(doc, "Active Duration", "Seconds spent actively interacting with the application via mouse or keyboard.")
    add_bullet(doc, "Idle Duration", "Seconds of inactivity attributed to the application before input was resumed.")

    add_h2(doc, "5.2 State Machine & Transition Rules")
    state_headers = ["Workstation State", "Detection Mechanism", "Tracking Behavior", "Screenshot Behavior"]
    state_rows = [
        ["Active", "Keyboard or mouse input detected within idle threshold", "Logs application name, window title, and active duration continuously.", "Screenshots captured according to assigned periodic policy."],
        ["Idle", "Inactivity timer exceeds configured threshold (e.g. 5 min)", "Tracking enters Idle mode. Upon resumption, idle seconds are logged and attributed to the prior application.", "Screenshots are STRICTLY PAUSED during idle state."],
        ["Workstation Locked (Win+L)", "OpenInputDesktop / SwitchDesktop Win32 API check", "Current session immediately concludes. LockApp.exe / LogonUI.exe are excluded from activity logs.", "Screenshots are STRICTLY PAUSED while locked. Zero capture permitted."],
        ["Display-Off / Power Save", "OS power broadcast / display standby event", "Treated as Idle state; no active time accumulated.", "Screenshots are paused."],
        ["Sleep / Hibernate", "OS suspend broadcast event", "Activity tracking pauses completely. Elapsed sleep duration is excluded from work time.", "Screenshots are paused. Tracker resumes cleanly on wake."],
    ]
    add_styled_table(doc, state_headers, state_rows, [1.6, 1.8, 2.0, 1.8])

    add_callout(doc, "PRIVACY", "Verified Workstation Lock & Win+L Protection",
        "Source code verification confirms that workstation lock state is actively detected via native operating system APIs. "
        "When an employee locks their workstation (e.g., via Win + L on Windows or Lock Screen on macOS), the tracker "
        "immediately suspends screenshot capture. Lock screens, login dialogs, and screen savers are never screenshotted."
    )

    # ------------------------------------------------------------------
    # SECTION 6: Screenshot Frequency & Storage Calculations
    # ------------------------------------------------------------------
    add_h1(doc, "6. Screenshot Capture Engine, Compression & Storage Calculations")
    add_p(doc,
        "The screenshot capture service operates in tandem with activity tracking to provide visual audit records "
        "for organizational compliance. This section details how images are captured, compressed, and calculated."
    )

    add_h2(doc, "6.1 Capture Rules and Compression Pipeline")
    add_bullet(doc, "Capture Condition", "Screenshots are captured ONLY when the workstation is in Active state. No screenshots are captured during Idle, Workstation Locked, Display-Off, or Sleep states.")
    add_bullet(doc, "Multi-Monitor Support", "Captures the virtual desktop bounding box encompassing all connected monitors.")
    add_bullet(doc, "Multi-Tier Capture Chain", "Uses high-performance OS capture APIs (PIL ImageGrab -> Win32 BitBlt -> mss fallback) to ensure zero perceptible lag or dropped frames for the employee.")
    add_bullet(doc, "Color Quantization & Compression", 
        "Raw screenshots can consume 2 to 6 MB each. iHRMS Desktop features an integrated compression engine: "
        "any image exceeding 100 KB (`COMPRESS_ABOVE_BYTES = 102400`) is quantized to 256 optimized palette colors (`FASTOCTREE`) "
        "and saved as an optimized PNG. This reduces file size by 75% to 85% (~120 KB to 250 KB) while maintaining razor-sharp text readability."
    )
    add_bullet(doc, "Local Buffering & Pruning Lifecycle",
        "Screenshots are saved locally to `%LOCALAPPDATA%\\Workpulse\\screenshots\\` (Windows) or "
        "`~/Library/Application Support/Workpulse/screenshots/` (macOS). Screenshots are uploaded to the central system "
        "in background batches. Crucially, local screenshot files are deleted ONLY AFTER the central company system "
        "verifies and confirms successful receipt. If network connectivity drops, screenshots remain buffered locally until connectivity is restored."
    )

    add_h2(doc, "6.2 Screenshot Frequency Calculation Formulas")
    add_p(doc,
        "The capture frequency depends on the configured interval `T` (in seconds). Under continuous active operation, "
        "the number of captures is determined using the exact formulas below:"
    )
    add_bullet(doc, "Captures per Hour Formula", "Estimated captures per hour = 3600 / T")
    add_bullet(doc, "Captures in 8 Hours Formula", "Estimated captures in 8 hours = 28800 / T")
    add_p(doc,
        "Note: In iHRMS Desktop, screenshot scheduling operates on exact periodic timer intervals following active state initiation. "
        "If an interval does not divide evenly or if the workstation becomes idle, actual captures will be lower than the theoretical maximum."
    )

    add_h3(doc, "Theoretical Maximum Capture Frequency Table")
    freq_headers = ["Configured Interval (T)", "Seconds (T)", "Theoretical Captures / Hour (3600/T)", "Theoretical Captures / 8 Hours (28800/T)", "Operational Context"]
    freq_rows = [
        ["1 minute", "60 s", "60 captures", "480 captures", "High-frequency audit (testing / specialized roles)"],
        ["3 minutes (Default)", "180 s", "20 captures", "160 captures", "Standard enterprise default configuration"],
        ["5 minutes", "300 s", "12 captures", "96 captures", "Balanced productivity monitoring"],
        ["10 minutes", "600 s", "6 captures", "48 captures", "Lightweight periodic audit"],
        ["15 minutes", "900 s", "4 captures", "32 captures", "Minimal footprint compliance"],
    ]
    add_styled_table(doc, freq_headers, freq_rows, [1.5, 1.0, 1.5, 1.5, 1.7])

    add_h2(doc, "6.3 Storage Consumption Formulas & Multi-Tier Matrix")
    add_p(doc,
        "Storage requirements for client staging and cloud ingestion are calculated using the average screenshot size `S` (in Megabytes):"
    )
    add_bullet(doc, "Storage per Hour Formula", "Estimated storage per hour = captures per hour × S MB")
    add_bullet(doc, "Storage in 8 Hours Formula", "Estimated storage for 8 hours = captures in 8 hours × S MB")

    add_h3(doc, "Comprehensive Storage Estimation Matrix (1 Hour and 8-Hour Workday)")
    add_p(doc,
        "The following table compares storage footprints across standard capture intervals and varying image file sizes. "
        "Measured production averages for iHRMS Desktop quantized PNG screenshots range between 120 KB and 200 KB (~0.15 MB)."
    )

    stor_headers = ["Configured Interval", "Captures (1 Hr / 8 Hr)", "At 100 KB (0.10 MB)", "At 150 KB (0.15 MB - Measured)", "At 250 KB (0.25 MB)", "At 500 KB (0.50 MB)"]
    stor_rows = [
        ["1 minute (60s)", "60 / 480", "6.0 MB / 48.0 MB", "9.0 MB / 72.0 MB", "15.0 MB / 120.0 MB", "30.0 MB / 240.0 MB"],
        ["3 minutes (180s - Default)", "20 / 160", "2.0 MB / 16.0 MB", "3.0 MB / 24.0 MB", "5.0 MB / 40.0 MB", "10.0 MB / 80.0 MB"],
        ["5 minutes (300s)", "12 / 96", "1.2 MB / 9.6 MB", "1.8 MB / 14.4 MB", "3.0 MB / 24.0 MB", "6.0 MB / 48.0 MB"],
        ["10 minutes (600s)", "6 / 48", "0.6 MB / 4.8 MB", "0.9 MB / 7.2 MB", "1.5 MB / 12.0 MB", "3.0 MB / 24.0 MB"],
        ["15 minutes (900s)", "4 / 32", "0.4 MB / 3.2 MB", "0.6 MB / 4.8 MB", "1.0 MB / 8.0 MB", "2.0 MB / 16.0 MB"],
    ]
    add_styled_table(doc, stor_headers, stor_rows, [1.4, 1.1, 1.2, 1.4, 1.2, 1.2])

    add_callout(doc, "TIP", "Local Disk Resource Optimization",
        "Under the default 3-minute interval and measured 150 KB image size, an entire 8-hour workday generates approximately "
        "24.0 MB of compressed image data. Because successfully uploaded screenshots are immediately deleted from local disk, "
        "client storage overhead rarely exceeds 5 to 10 MB under normal network conditions."
    )

    # ------------------------------------------------------------------
    # SECTION 7: Backend Configuration & Enterprise Settings
    # ------------------------------------------------------------------
    add_h1(doc, "7. Enterprise Backend Configuration & Policy Administration")
    add_p(doc,
        "iHRMS Desktop is designed for centralized governance. System administrators can configure and enforce "
        "organizational monitoring policies remotely from the centralized company management system without requiring "
        "manual changes on individual user laptops."
    )

    add_h2(doc, "7.1 Verified Configurable Settings Matrix")
    conf_headers = ["Setting Name", "Purpose & Operational Effect", "Origin / Control", "Default Value", "Effective Timing"]
    conf_rows = [
        ["Activity Sync Interval", "Defines the frequency at which buffered activity logs and screenshots are transmitted to company systems.", "Remote Company System", "300 seconds (5 minutes)", "Takes effect on the next recurring sync cycle without restart."],
        ["Idle Detection Threshold", "Defines continuous user input inactivity duration before workstation state transitions from Active to Idle.", "Remote Policy / Local UI", "300 seconds (5 minutes)", "Applied immediately to running tracker worker thread."],
        ["Screenshot Capture Policy", "Enables or disables automatic periodic visual screenshot recording for the employee or role.", "Remote Company System", "Enabled (Active with screenshots)", "Takes effect on next dynamic configuration sync."],
        ["Screenshot Capture Interval", "Sets the periodic time duration between automated desktop screenshot captures.", "Remote Policy / Local UI", "3 minutes (180 seconds)", "Takes effect immediately upon next timer cycle."],
        ["Capture on Window Switch", "Triggers a screenshot capture whenever the user switches between distinct foreground applications.", "Remote Policy / Local UI", "Disabled (Optional)", "Applied immediately to foreground window listener."],
        ["Start with System", "Configures operating system startup registration to launch iHRMS Desktop automatically on boot.", "Local User Preference", "Enabled (True)", "Takes effect on next system boot / user login."],
        ["Track Window Titles", "Enables recording window title text alongside executable process names for detailed activity context.", "Remote Policy / Local UI", "Enabled (True)", "Applied immediately to tracker poll cycle."],
        ["Tracking Start/Stop Permission", "Enables or disables employee manual pause/resume controls based on organizational role.", "Remote Company System", "Permitted (True)", "Applied dynamically via role-based access control (RBAC)."],
    ]
    add_styled_table(doc, conf_headers, conf_rows, [1.3, 2.1, 1.3, 1.1, 1.4])

    add_h2(doc, "7.2 Dynamic Configuration Synchronization Flow")
    add_p(doc,
        "The application periodically contacts the company management system in the background (every 60 seconds) "
        "to check for updated organizational policies. When an administrator updates an employee's tracking interval, "
        "idle threshold, or permissions in the central console:"
    )
    add_bullet(doc, "Silent Retrieval", "The client downloads the assigned policy in a background worker thread.")
    add_bullet(doc, "In-Memory Update", "The running activity tracker and screenshot worker update their internal timers dynamically.")
    add_bullet(doc, "No Restart Required", "Policy adjustments take effect immediately without interrupting the user or requiring an application restart.")

    # ------------------------------------------------------------------
    # SECTION 8: Synchronization, Offline Resilience & Auto-Updates
    # ------------------------------------------------------------------
    add_h1(doc, "8. Synchronization, Offline Resilience & Background Auto-Updates")
    add_p(doc,
        "Enterprise employees frequently work in transit, on client premises, or in environments with intermittent connectivity. "
        "iHRMS Desktop is engineered with an offline-first architecture to guarantee total operational continuity."
    )

    add_h2(doc, "8.1 Offline Data Buffering & Integrity")
    add_bullet(doc, "Local SQLite Staging", "All session records, window transitions, idle durations, and health telemetry are written immediately to a local SQLite database (`activity_tracker.db`) stored in the employee's writable user profile.")
    add_bullet(doc, "Zero Telemetry Loss", "If the computer is disconnected from the internet for hours or days, activity tracking continues unaffected. The database buffers thousands of session records safely on disk.")
    add_bullet(doc, "Non-Blocking UI", "All network synchronization runs asynchronously in a dedicated worker thread. Network drops or slow connections never cause the dashboard UI to freeze or become unresponsive.")

    add_h2(doc, "8.2 Synchronization Lifecycle & Verified Cleanup")
    add_bullet(doc, "Reachability Monitoring", "A continuous network reachability monitor detects connection restoration passively, switching the Status badge from '● Offline' to '● Online'.")
    add_bullet(doc, "Chronological Batch Uploads", "Buffered records are transmitted in structured chronological batches to ensure accurate historical timeline reconstruction.")
    add_bullet(doc, "Strict Server-Confirmed Cleanup", "Screenshots stored in the local buffer directory are pruned ONLY AFTER the central company system confirms successful receipt and verification. Failed uploads remain queued for automated retry.")

    add_h2(doc, "8.3 Detached Background Auto-Update Pipeline")
    add_bullet(doc, "Fleet Consistency", "To ensure security compliance across the enterprise, iHRMS Desktop checks for verified software updates every 2 hours.")
    add_bullet(doc, "Cryptographic Checksum Verification", "Downloaded installer packages are verified against SHA-256 hashes to guarantee binary integrity before execution.")
    add_bullet(doc, "Detached Execution", "When the employee or administrator initiates an update, a helper process executes the installer silently (`/VERYSILENT /SUPPRESSMSGBOXES`), waits for process termination, applies the update, and relaunches the application with saved session state intact.")

    # ------------------------------------------------------------------
    # SECTION 9: Security, Employee Privacy & Compliance
    # ------------------------------------------------------------------
    add_h1(doc, "9. Security Architecture, Employee Privacy & Compliance")
    add_p(doc,
        "iHRMS Desktop is built to balance enterprise productivity visibility with employee privacy protection. "
        "The application strictly collects objective workplace metrics while safeguarding personal privacy."
    )

    add_h2(doc, "9.1 What the Application Tracks vs What It Does NOT Track")
    priv_headers = ["Monitored Telemetry (Collected)", "Strict Privacy Exclusions (NOT Collected)"]
    priv_rows = [
        ["Active foreground application process name (e.g. excel.exe)", "NO Keystroke Logging: The application NEVER logs keystrokes or words typed."],
        ["Active window title bar text (can be disabled by policy)", "NO Password Capture: Form input fields and password boxes are never recorded."],
        ["Active duration and mouse/keyboard activity presence", "NO Audio or Video Recording: Webcams and microphones are NEVER accessed."],
        ["System boot time, punch in/out timestamps, timesheet data", "NO Personal File Access: Documents, photos, and personal folders are never scanned."],
        ["Periodic desktop screenshots during Active status only", "NO Lock-Screen Screenshots: Screenshots are completely paused when locked (Win+L)."],
        ["Workstation hardware UUID and operating system platform", "NO Personal Browsing Inspection: Private cookies, browsing history, and credentials are never read."],
    ]
    add_styled_table(doc, priv_headers, priv_rows, [3.2, 4.0])

    add_h2(doc, "9.2 Enterprise Security Features")
    add_bullet(doc, "Operating System Credential Vaults", "Authentication tokens are protected using OS-native encryption (Windows Credential Manager DPAPI and macOS Keychain).")
    add_bullet(doc, "Encrypted Transport", "All telemetry, attendance logs, timesheets, and screenshots are transmitted using modern TLS 1.2+ encryption.")
    add_bullet(doc, "Hardware Binding", "Session tokens are cryptographically bound to physical hardware identifiers, preventing replay attacks or unauthorized endpoint impersonation.")

    # ------------------------------------------------------------------
    # SECTION 10: Troubleshooting, FAQs & Platform Differences
    # ------------------------------------------------------------------
    add_h1(doc, "10. Troubleshooting, FAQs & Platform Differences")
    
    add_h2(doc, "10.1 Windows vs macOS Differences Matrix")
    diff_headers = ["Feature / Capability", "Windows 10/11 x64 Implementation", "macOS 11.0+ Implementation"]
    diff_rows = [
        ["Packaging & Installer", "Inno Setup executable installer (`.exe`) with silent `/VERYSILENT` deployment flag.", "Universal Disk Image (`.dmg`) bundle with drag-and-drop `/Applications` install."],
        ["Auto-Start Mechanism", "Windows Run Registry Key: `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`", "macOS Login Items / User LaunchAgent (`~/Library/LaunchAgents`)"],
        ["Idle Detection API", "Win32 `GetLastInputInfo` measuring system-wide physical keyboard and mouse events.", "CoreGraphics / IOHID system idle time queries (`CGEventSourceSecondsSinceLastEventType`)."],
        ["Lock State Detection", "Win32 `OpenInputDesktop` and `SwitchDesktop` detecting secure desktop and `Win + L`.", "Quartz display sleep notification and ScreenSaver / ScreenIsLocked notifications."],
        ["Credential Vault", "Windows Credential Manager (`Windows Vault` / CredRead/CredWrite APIs).", "macOS System Keychain Services (`SecKeychainFindGenericPassword`)."],
        ["OS Permissions Required", "Standard user privileges (no UAC / elevation needed for per-user installation).", "Explicit 'Screen Recording' authorization required under System Settings -> Privacy."],
    ]
    add_styled_table(doc, diff_headers, diff_rows, [1.8, 2.7, 2.7])

    add_h2(doc, "10.2 Frequently Asked Questions (FAQs)")
    add_bullet(doc, "Q: Does iHRMS Desktop track my time when my computer is disconnected from the internet?",
        "A: Yes. iHRMS Desktop features an offline-first architecture. It logs all active time, idle periods, and screenshots into a local encrypted SQLite database. When internet connectivity returns, all buffered data is synchronized automatically without data loss.")

    add_bullet(doc, "Q: What happens when I lock my workstation with Win + L or step away for lunch?",
        "A: When you lock your screen or become inactive past your idle threshold (default 5 minutes), the tracker immediately suspends active time accumulation. Crucially, screenshot capture is completely paused during lock and idle periods. When you unlock and return, tracking resumes cleanly.")

    add_bullet(doc, "Q: Can anyone access my passwords, chat messages, or personal camera?",
        "A: Absolutely not. iHRMS Desktop contains no keyloggers, webcam capture, or microphone listening tools. It only records application process names, window titles, active durations, and periodic desktop screenshots during active work hours.")

    add_bullet(doc, "Q: How do I verify which version of the software is running on my machine?",
        "A: Look at the Status card on the main Dashboard. A prominent blue badge displays 'Version: 1.0.0'. You can also click this badge or open the User & Device dialog to view authoritative build and fleet verification details.")

    add_bullet(doc, "Q: Why is the application showing '● Offline' on my dashboard?",
        "A: The '● Offline' badge indicates that the client cannot reach the company network. Your time and activity are still being recorded safely on local disk. Once connectivity is restored, the indicator turns to '● Online' and syncs pending records automatically.")

    add_bullet(doc, "Q: Why does macOS require 'Screen Recording' permission?",
        "A: Apple macOS security requires user consent for any application that captures screen contents. To enable screenshots, open System Settings -> Privacy & Security -> Screen Recording, toggle 'iHRMS Desktop' ON, and click 'Quit & Reopen'.")

    add_bullet(doc, "Q: What should I do if my timesheet or attendance does not match the web portal?",
        "A: Click the 'iHRMS' button in the top window header to open the web portal. Then click 'Refresh' or switch between tabs to re-sync data. Both desktop and web clients utilize the same centralized database.")

    add_h2(doc, "10.3 Enterprise Support and Helpdesk")
    add_p(doc,
        "If you encounter technical issues, unexpected sync behavior, or require device enrollment resets, "
        "please contact your corporate IT helpdesk or designated iHRMS administrator:"
    )
    add_bullet(doc, "Corporate Helpdesk Email", "support@indovision.in / it-support@yourcompany.com")
    add_bullet(doc, "Enterprise Web Portal Access", "Accessible via the 'iHRMS' top header button or your company intranet portal")
    add_bullet(doc, "Administrative Hours", "Monday through Friday, 09:00 AM – 06:30 PM IST")

    # Document completion and save
    print(f"Saving final user manual document to: {OUTPUT_FILE}")
    doc.save(OUTPUT_FILE)
    print("User manual successfully generated and saved!")


if __name__ == "__main__":
    build_manual_document()
