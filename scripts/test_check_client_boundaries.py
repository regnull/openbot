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

    def test_transport_aliases_are_rejected_elsewhere(self):
        text = """\
        window.fetch('/api');
        globalThis.fetch('/api');
        new window.EventSource('/events');
        """
        violations = checker.violations_for_text(text, "components/Widget.tsx")
        self.assertEqual(len(violations), 3)
        self.assertTrue(all("transport" in item for item in violations))

    def test_dynamic_and_resolved_node_imports_are_rejected(self):
        text = """\
        const fs = import( "fs" );
        const nodeFs = import( "node:fs" );
        const resolved = require.resolve( "path" );
        const crypto = require( "crypto" );
        const tls = from "node:tls";
        """
        violations = checker.violations_for_text(text, "components/Widget.tsx")
        self.assertEqual(len(violations), 5)
        self.assertTrue(all("Node/server runtime imports" in item for item in violations))

    def test_common_server_modules_are_rejected(self):
        text = "\n".join(f'import "{module}";' for module in (
            "crypto", "http", "https", "os", "url", "worker_threads"
        ))
        violations = checker.violations_for_text(text, "components/Widget.tsx")
        self.assertEqual(len(violations), 6)


    def test_static_import_forms_are_rejected(self):
        text = """\
        import fs from "fs";
        import * as path from "node:path";
        import { createHash } from "crypto";
        import "worker_threads";
        """
        violations = checker.violations_for_text(text, "components/Widget.tsx")
        self.assertEqual(len(violations), 4)
        self.assertTrue(all("Node/server runtime imports" in item for item in violations))

    def test_client_imports_remain_allowed(self):
        text = """\
        import React from "react";
        import * as api from "./api";
        import { useState } from "react";
        """
        self.assertEqual(checker.violations_for_text(text, "components/Widget.tsx"), [])


if __name__ == "__main__":
    unittest.main()
