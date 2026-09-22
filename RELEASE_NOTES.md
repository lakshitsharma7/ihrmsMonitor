# Workpulse v2.0.2 Release Notes

We are excited to release **Workpulse v2.0.2**, introducing native macOS distribution, enhanced cross-platform auto-updates, resilient TLS CA certificate handling, and secure dynamic HRMS single-sign-on integration.

---

### What's New in v2.0.2

#### 🍎 Native macOS Support
- **Native macOS Application (`Workpulse.app`)**: 64-bit Mach-O executable built with Apple Silicon and Intel compatibility.
- **macOS Disk Image (`Workpulse.dmg`)**: Drag-and-drop installer for effortless installation into `/Applications`.
- **Platform-Native Monitoring**: Idle tracking via macOS `CGEventSourceSecondsSinceLastEventType`, CoreGraphics window title capture, native dock icon integration, and macOS app state lifecycle management.
- **Headless CI Testing Support**: Automated detection of headless environments and offscreen Qt rendering.

#### 🔄 Multi-Platform Auto-Update System
- **Platform-Aware Candidate Resolution**: macOS clients automatically seek `.dmg` packages from backend API responses and fallback to official GitHub Releases; Windows clients continue seamless Inno Setup `.exe` updates.
- **Deep Installer Validation**: Windows executables are verified against DOS `MZ` and PE headers; macOS disk images are verified against Apple UDIF `koly` signatures to prevent corrupt or partial downloads from executing.
- **Detached macOS Updater**: Standalone background shell updater (`updater.sh`) that safely waits for app termination, clears lock files, mounts the DMG, upgrades `/Applications/Workpulse.app`, and relaunches the application.

#### 🔒 Security & TLS CA Certificate Resilience
- **Dynamic CA Bundle Resolution**: Auto-recovers from invalid user paths or stale roaming environment variables (`REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`), guaranteeing uninterrupted HTTPS connections for attendance, leave balances, and tracking sync.
- **Dynamic HRMS Single-Sign-On**: Secure token generation for instant HRMS portal access from the Workpulse dashboard without exposing plain-text credentials in URLs.

#### 🧪 Quality Assurance & CI/CD
- **270+ Automated Tests**: Comprehensive unit and integration test suite passing on both Windows and macOS.
- **Automated Multi-Platform Release Workflow**: Unified GitHub Actions workflow for building, testing, and publishing native Windows and macOS release assets.

---

### Release Assets

| Platform | File | Type | Description |
| :--- | :--- | :--- | :--- |
| **Windows** | `WorkpulseSetup.exe` | Inno Setup Installer | Recommended primary installer for Windows 10/11 |
| **Windows** | `Workpulse.exe` | Standalone Executable | Portable executable for standalone execution |
| **Windows** | `Workpulse-Installer.exe` | Inno Setup Installer | Alternate installer name for legacy update endpoints |
| **Windows** | `iHRMSMonitorSetup.exe` | Inno Setup Installer | Legacy compatibility installer |
| **macOS** | `Workpulse.dmg` | Apple Disk Image | Standard drag-and-drop installer for macOS |

---

### Verification & Checksums

All binaries are built directly from source tag `v2.0.2` on the `feature/activity-tracker` branch.
