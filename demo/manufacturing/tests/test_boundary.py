"""Public/private boundary guard for the manufacturing demo.

Fails if any file under demo/manufacturing contains direct references to
private framework implementation modules, private local paths, or internal
implementation names. The public demo must be independently runnable.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

ALLOWED_TOP_LEVEL = {"framework_port", "backend_sim", "app", "tests", "docs", "pack", "data"}
ALLOWED_FILES = {"run_demo.py", "README.md", "PUBLIC_DEMO_MANIFEST.md", "EXPECTED_FLOW.md",
                 ".gitignore"}

FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    ("framework import", re.compile(r"\bgeneral_agent_framework\b")),
    ("framework env var", re.compile(r"\bGAF_FRAMEWORK_PATH\b")),
    ("private directory name", re.compile(r"agent开发文件|通用agent框架")),
    ("private home path", re.compile(r"/Users/ming")),
    ("internal module name", re.compile(
        r"\b(integration_write_store|integration_write_service|integration_service|"
        r"identity_service|identity_runtime|SqliteDataLayer|AgentCore|RuntimeFacade|"
        r"notification_center|notification_contracts|RoleAuthorizationPolicy|"
        r"PermissionSubject|ApprovalDecisionAuthority|ExternalWriteAdmission|"
        r"ExternalWriteDispatcher|ExternalWriteObserver|derive_reconciliation)\b")),
)


class BoundaryGuardTest(unittest.TestCase):
    def test_no_private_references_anywhere(self) -> None:
        offenders: list[str] = []
        self_file = Path(__file__).relative_to(BASE)
        scanned = 0
        for path in sorted(BASE.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(BASE)
            if rel == self_file:
                continue  # the guard contains the forbidden patterns by design
            # Fail on the unknown: any meaningful file outside the allowlist
            # is an offender, so future content cannot silently bypass us.
            meaningful = path.suffix in {".py", ".md", ".json", ".txt", ".html", ".css"}
            in_allowlist = (
                rel.parts[0] in ALLOWED_TOP_LEVEL or rel.name in ALLOWED_FILES
                or rel.parts[0] in {".state", "__pycache__"}  # runtime artefacts
            )
            if not meaningful:
                continue
            if not in_allowlist:
                offenders.append(f"{rel}: unexpected location (not in allowlist)")
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            for label, pattern in FORBIDDEN_PATTERNS:
                if pattern.search(text):
                    offenders.append(f"{rel}: {label}")
        self.assertGreater(scanned, 10, "guard scanned too few files — layout changed?")
        self.assertEqual(offenders, [], "boundary violations:\n" + "\n".join(offenders))

    def test_demo_imports_only_local_packages(self) -> None:
        import ast
        local_roots = {"framework_port", "backend_sim", "app"}
        for path in sorted((BASE / "app").rglob("*.py")) + \
                sorted((BASE / "backend_sim").rglob("*.py")) + \
                sorted((BASE / "framework_port").rglob("*.py")) + \
                [BASE / "run_demo.py"]:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        self.assertIn(
                            root, local_roots | set(sys.stdlib_module_names),
                            f"{path.name}: unexpected import '{alias.name}'",
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 0:
                        continue  # relative import inside the demo
                    root = (node.module or "").split(".")[0]
                    if not root:
                        continue
                    self.assertIn(
                        root, local_roots | set(sys.stdlib_module_names),
                        f"{path.name}: unexpected from-import '{node.module}'",
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
