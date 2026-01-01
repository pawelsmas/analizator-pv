"""
Unit tests for RC check script (v2.6.0 PR5).

Tests verify:
- Check functions exist and are callable
- Color constants are defined
- Helper functions work correctly
- Command execution works
"""

import pytest
import sys
from pathlib import Path


# Add scripts/rc to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts" / "rc"))


class TestColors:
    """Tests for color constants."""

    def test_colors_has_green(self):
        """Colors should have GREEN."""
        from rc_check import Colors
        assert hasattr(Colors, "GREEN")
        assert Colors.GREEN != ""

    def test_colors_has_red(self):
        """Colors should have RED."""
        from rc_check import Colors
        assert hasattr(Colors, "RED")
        assert Colors.RED != ""

    def test_colors_has_reset(self):
        """Colors should have RESET."""
        from rc_check import Colors
        assert hasattr(Colors, "RESET")
        assert Colors.RESET != ""

    def test_colors_has_bold(self):
        """Colors should have BOLD."""
        from rc_check import Colors
        assert hasattr(Colors, "BOLD")


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_print_header_exists(self):
        """print_header should exist."""
        from rc_check import print_header
        assert callable(print_header)

    def test_print_result_exists(self):
        """print_result should exist."""
        from rc_check import print_result
        assert callable(print_result)

    def test_run_command_exists(self):
        """run_command should exist."""
        from rc_check import run_command
        assert callable(run_command)

    def test_run_command_returns_tuple(self):
        """run_command should return (bool, str)."""
        from rc_check import run_command
        result = run_command([sys.executable, "--version"])
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_run_command_success(self):
        """run_command should return True for successful command."""
        from rc_check import run_command
        success, output = run_command([sys.executable, "--version"])
        assert success is True
        assert "Python" in output

    def test_run_command_failure(self):
        """run_command should return False for failed command."""
        from rc_check import run_command
        success, output = run_command([sys.executable, "-c", "import sys; sys.exit(1)"])
        assert success is False


class TestCheckFunctions:
    """Tests for check functions."""

    def test_check_backend_running_exists(self):
        """check_backend_running should exist."""
        from rc_check import check_backend_running
        assert callable(check_backend_running)

    def test_check_backend_running_returns_bool(self):
        """check_backend_running should return bool."""
        from rc_check import check_backend_running
        result = check_backend_running()
        assert isinstance(result, bool)

    def test_run_unit_tests_exists(self):
        """run_unit_tests should exist."""
        from rc_check import run_unit_tests
        assert callable(run_unit_tests)

    def test_run_smoke_tests_exists(self):
        """run_smoke_tests should exist."""
        from rc_check import run_smoke_tests
        assert callable(run_smoke_tests)

    def test_run_contract_tests_exists(self):
        """run_contract_tests should exist."""
        from rc_check import run_contract_tests
        assert callable(run_contract_tests)

    def test_run_contract_drift_check_exists(self):
        """run_contract_drift_check should exist."""
        from rc_check import run_contract_drift_check
        assert callable(run_contract_drift_check)

    def test_run_scenario_freeze_check_exists(self):
        """run_scenario_freeze_check should exist."""
        from rc_check import run_scenario_freeze_check
        assert callable(run_scenario_freeze_check)

    def test_check_deprecations_registry_exists(self):
        """check_deprecations_registry should exist."""
        from rc_check import check_deprecations_registry
        assert callable(check_deprecations_registry)


class TestDeprecationsCheck:
    """Tests for deprecations registry check."""

    def test_deprecations_check_finds_file(self):
        """check_deprecations_registry should find deprecations.json."""
        from rc_check import check_deprecations_registry
        project_root = Path(__file__).parent.parent.parent
        success, message = check_deprecations_registry(project_root)
        # Should pass if file exists
        assert success is True

    def test_deprecations_check_counts_items(self):
        """check_deprecations_registry should count items."""
        from rc_check import check_deprecations_registry
        project_root = Path(__file__).parent.parent.parent
        success, message = check_deprecations_registry(project_root)
        if success:
            assert "deprecations tracked" in message


class TestMain:
    """Tests for main function."""

    def test_main_exists(self):
        """main should exist."""
        from rc_check import main
        assert callable(main)


class TestCommandTimeout:
    """Tests for command timeout handling."""

    def test_run_command_respects_timeout(self):
        """run_command should respect timeout."""
        from rc_check import run_command
        # Quick command should succeed
        success, output = run_command(
            [sys.executable, "-c", "print('hello')"],
            timeout=5
        )
        assert success is True


class TestProjectRoot:
    """Tests for project root detection."""

    def test_can_find_project_root(self):
        """Should be able to find project root."""
        from rc_check import Path
        # The rc_check.py is in scripts/rc, so parent.parent.parent is root
        script_path = Path(__file__).parent.parent.parent / "scripts" / "rc" / "rc_check.py"
        assert script_path.exists()

    def test_project_root_has_tests_dir(self):
        """Project root should have tests directory."""
        project_root = Path(__file__).parent.parent.parent
        assert (project_root / "tests").is_dir()

    def test_project_root_has_scripts_dir(self):
        """Project root should have scripts directory."""
        project_root = Path(__file__).parent.parent.parent
        assert (project_root / "scripts").is_dir()
