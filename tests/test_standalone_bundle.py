"""Packaging contract: frozen app uses its own renderer, without Git or system Node."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from render import standalone_bridge


class StandaloneBundleTests(unittest.TestCase):
    def test_frozen_renderer_resolves_from_app_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "renderer-runtime"
            (runtime / "standalone-renderer").mkdir(parents=True)
            node = runtime / "node"
            cli = runtime / "standalone-renderer" / "cli.js"
            node.write_bytes(b"placeholder")
            cli.write_text("/* packaged renderer */")
            with patch.object(standalone_bridge.sys, "frozen", True, create=True):
                with patch.object(standalone_bridge.sys, "_MEIPASS", str(root), create=True):
                    with patch.object(standalone_bridge.shutil, "which",
                                      side_effect=AssertionError("must not inspect external tools")):
                        self.assertEqual(standalone_bridge.ensure_renderer(), cli)
                        self.assertEqual(standalone_bridge._bundled_runtime(), (node, cli))

    def test_incomplete_frozen_bundle_fails_instead_of_fetching(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(standalone_bridge.sys, "frozen", True, create=True):
                with patch.object(standalone_bridge.sys, "_MEIPASS", tmp, create=True):
                    with self.assertRaisesRegex(RuntimeError, "missing its bundled"):
                        standalone_bridge.ensure_renderer()


if __name__ == "__main__":
    unittest.main()
