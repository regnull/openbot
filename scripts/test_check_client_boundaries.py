import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    "check_client_boundaries", Path(__file__).with_name("check-client-boundaries.py")
)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class ClientBoundaryCheckerTests(unittest.TestCase):
    def test_transport_is_allowed_in_api_adapters(self):
        self.assertEqual(
            checker.violations_for_text("fetch('/api')", "api/client.ts"), []
        )
        self.assertEqual(
            checker.violations_for_text("new EventSource('/events')", "api/sse.ts"), []
        )

    def test_transport_is_rejected_elsewhere(self):
        violations = checker.violations_for_text("fetch('/api')", "components/Widget.tsx")
        self.assertEqual(len(violations), 1)
        self.assertIn("direct HTTP transport", violations[0])

    def test_dynamic_and_resolved_node_imports_are_rejected(self):
        text = """\
        const fs = import('fs');
        const nodeFs = import('node:fs');
        const resolved = require.resolve('path');
        """
        violations = checker.violations_for_text(text, "components/Widget.tsx")
        self.assertEqual(len(violations), 3)
        self.assertTrue(all("Node/server runtime imports" in item for item in violations))


if __name__ == "__main__":
    unittest.main()
