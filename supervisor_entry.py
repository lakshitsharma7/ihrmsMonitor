"""Entry point for iHRMS Desktop Supervisor standalone executable."""
from __future__ import annotations

import sys
from system.supervisor import main

if __name__ == "__main__":
    sys.exit(main())
