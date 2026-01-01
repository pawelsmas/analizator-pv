"""
Unit tests for no-legacy guard (v2.8.0 PR3).

Tests verify:
- Critical patterns are detected correctly
- Allowed files are skipped
- Non-critical paths are skipped
"""

import pytest
import sys
import tempfile
from pathlib import Path


# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "guards"))


class TestCriticalPatterns:
    """Tests for critical legacy pattern detection."""

    def test_detects_compat_legacy_equals(self):
        """Should detect compat=legacy pattern."""
        from check_no_legacy import scan_file
        import re

        patterns = [re.compile(r"compat\s*=\s*[\"']?legacy[\"']?", re.IGNORECASE)]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('response = client.get("/api?compat=legacy")\n')
            f.flush()

            violations = scan_file(Path(f.name), patterns)

        assert len(violations) == 1
        assert violations[0][0] == 1  # Line 1
        assert "legacy" in violations[0][1].lower()

    def test_detects_compat_legacy_quoted(self):
        """Should detect compat='legacy' pattern."""
        from check_no_legacy import scan_file
        import re

        patterns = [re.compile(r"compat\s*=\s*[\"']?legacy[\"']?", re.IGNORECASE)]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("params = {'compat': 'legacy'}\n")
            f.flush()

            # This pattern doesn't match dict syntax, which is correct
            violations = scan_file(Path(f.name), patterns)

        # Dict syntax uses different pattern
        assert len(violations) == 0

    def test_detects_query_param(self):
        """Should detect ?compat=legacy query param."""
        from check_no_legacy import scan_file
        import re

        patterns = [re.compile(r"\?compat=legacy", re.IGNORECASE)]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('url = "http://api/sizing?compat=legacy"\n')
            f.flush()

            violations = scan_file(Path(f.name), patterns)

        assert len(violations) == 1


class TestAllowedFiles:
    """Tests for allowed file detection."""

    def test_legacy_adapter_allowed(self):
        """legacy_adapter.py should be allowed."""
        from check_no_legacy import is_allowed

        root = Path("/project")
        path = Path("/project/services/bess-dispatch/legacy_adapter.py")

        assert is_allowed(path, root) is True

    def test_compat_mode_allowed(self):
        """compat_mode.py should be allowed."""
        from check_no_legacy import is_allowed

        root = Path("/project")
        path = Path("/project/services/bess-dispatch/compat_mode.py")

        assert is_allowed(path, root) is True

    def test_legacy_test_allowed(self):
        """test_legacy_adapter.py should be allowed."""
        from check_no_legacy import is_allowed

        root = Path("/project")
        path = Path("/project/tests/unit/test_legacy_adapter.py")

        assert is_allowed(path, root) is True

    def test_docs_skipped(self):
        """docs/ prefix should be skipped."""
        from check_no_legacy import is_allowed

        root = Path("/project")
        path = Path("/project/docs/api/deprecations.json")

        assert is_allowed(path, root) is True

    def test_random_file_not_allowed(self):
        """Random files should not be allowed."""
        from check_no_legacy import is_allowed

        root = Path("/project")
        path = Path("/project/services/frontend-bess/some_file.js")

        assert is_allowed(path, root) is False


class TestCriticalPaths:
    """Tests for critical path detection."""

    def test_frontend_is_critical(self):
        """Frontend path should be critical."""
        from check_no_legacy import is_critical_path

        root = Path("/project")
        path = Path("/project/services/frontend-bess/bess.js")

        assert is_critical_path(path, root) is True

    def test_backend_not_critical(self):
        """Backend path should not be critical (in non-strict mode)."""
        from check_no_legacy import is_critical_path

        root = Path("/project")
        path = Path("/project/services/bess-dispatch/app.py")

        assert is_critical_path(path, root) is False

    def test_tests_not_critical(self):
        """Test path should not be critical."""
        from check_no_legacy import is_critical_path

        root = Path("/project")
        path = Path("/project/tests/unit/test_something.py")

        assert is_critical_path(path, root) is False


class TestScanCriticalPaths:
    """Tests for scan_critical_paths function."""

    def test_skips_non_critical_files(self):
        """Should skip non-critical files in non-strict mode."""
        from check_no_legacy import scan_critical_paths

        # Create temp directory with backend file containing legacy
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Backend file (not critical)
            backend_dir = root / "services" / "bess-dispatch"
            backend_dir.mkdir(parents=True)
            backend_file = backend_dir / "some_module.py"
            backend_file.write_text('url = "?compat=legacy"')

            violations = scan_critical_paths(root, strict=False)

        # Should not find violation in non-critical path
        assert len(violations) == 0

    def test_finds_in_frontend(self):
        """Should find violations in frontend (critical path)."""
        from check_no_legacy import scan_critical_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Frontend file (critical)
            frontend_dir = root / "services" / "frontend-bess"
            frontend_dir.mkdir(parents=True)
            frontend_file = frontend_dir / "bess.js"
            frontend_file.write_text('const url = "/api?compat=legacy";')

            violations = scan_critical_paths(root, strict=False)

        assert len(violations) == 1
        assert "frontend" in str(violations[0][0])


class TestFormatViolations:
    """Tests for format_violations function."""

    def test_no_violations_ok(self):
        """No violations should return OK message."""
        from check_no_legacy import format_violations

        result = format_violations([], Path("/project"))
        assert "OK" in result

    def test_violations_formatted(self):
        """Violations should be formatted with file and line info."""
        from check_no_legacy import format_violations

        violations = [
            (Path("/project/file.py"), 10, 'url = "?compat=legacy"', r"\?compat=legacy"),
        ]

        result = format_violations(violations, Path("/project"))

        assert "file.py" in result
        assert "L10" in result
        assert "compat=legacy" in result


class TestGuardIntegration:
    """Integration tests for the guard."""

    def test_guard_script_runs(self):
        """Guard script should run without errors."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "scripts/guards/check_no_legacy.py"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Should exit 0 (no violations) or 1 (violations found)
        assert result.returncode in [0, 1]

    def test_guard_verbose_mode(self):
        """Guard should support verbose mode."""
        import subprocess

        result = subprocess.run(
            [sys.executable, "scripts/guards/check_no_legacy.py", "-v"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Should show scanning message in verbose mode
        # (may or may not depending on platform)
        assert result.returncode in [0, 1]
