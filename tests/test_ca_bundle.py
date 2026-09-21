"""Unit tests for TLS/SSL CA certificate bundle resolution and HTTPS verification."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.paths import get_ca_bundle_path, init_ca_bundle


class TestCaBundleResolution(unittest.TestCase):
    def test_get_ca_bundle_path_source_mode(self):
        """Verify CA bundle is found in source mode."""
        ca_path = get_ca_bundle_path()
        self.assertIsNotNone(ca_path)
        self.assertTrue(os.path.isfile(ca_path))
        self.assertTrue(ca_path.endswith(".pem"))

    def test_init_ca_bundle_sets_environment(self):
        """Verify init_ca_bundle configures requests and urllib3 environment variables."""
        ca_path = init_ca_bundle()
        self.assertIsNotNone(ca_path)
        self.assertEqual(os.environ.get("REQUESTS_CA_BUNDLE"), ca_path)
        self.assertEqual(os.environ.get("SSL_CERT_FILE"), ca_path)

    def test_get_ca_bundle_path_frozen_simulation(self):
        """Verify get_ca_bundle_path locates bundled cacert.pem in simulated frozen runtime."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_internal = Path(tmpdir) / "_internal" / "certifi"
            tmp_internal.mkdir(parents=True)
            mock_cacert = tmp_internal / "cacert.pem"
            mock_cacert.write_text("MOCK CA CERT BUNDLE", encoding="utf-8")

            with patch("sys.frozen", True, create=True), \
                 patch("sys.executable", str(Path(tmpdir) / "Workpulse.exe")), \
                 patch("sys._MEIPASS", str(Path(tmpdir) / "_internal"), create=True):
                resolved = get_ca_bundle_path()
                self.assertIsNotNone(resolved)
                self.assertEqual(Path(resolved).resolve(), mock_cacert.resolve())


if __name__ == "__main__":
    unittest.main()
