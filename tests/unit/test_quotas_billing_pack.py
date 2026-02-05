"""
Unit tests for quotas_billing scenario pack.

Tests verify:
- Pack file exists and is valid YAML
- All scenarios are listed
- Request/expected files exist for key scenarios
"""

import os
import pytest
import yaml

PACK_PATH = os.path.join(
    os.path.dirname(__file__),
    '..',
    '..',
    'docs',
    'scenarios',
    'packs',
    'quotas_billing.yml'
)

REQUESTS_PATH = os.path.join(
    os.path.dirname(__file__),
    '..',
    '..',
    'docs',
    'scenarios',
    'requests',
    'quotas'
)

EXPECTED_PATH = os.path.join(
    os.path.dirname(__file__),
    '..',
    '..',
    'docs',
    'scenarios',
    'expected',
    'quotas'
)


class TestPackFile:
    """Tests for pack file structure."""

    def test_pack_file_exists(self):
        """Pack file should exist."""
        assert os.path.exists(PACK_PATH)

    def test_pack_is_valid_yaml(self):
        """Pack file should be valid YAML."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert data is not None

    def test_pack_has_name(self):
        """Pack should have name."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'name' in data
        assert data['name'] == 'quotas_billing'

    def test_pack_has_description(self):
        """Pack should have description."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'description' in data
        assert len(data['description']) > 0

    def test_pack_has_scenarios(self):
        """Pack should have scenarios list."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'scenarios' in data
        assert isinstance(data['scenarios'], list)

    def test_pack_has_minimum_scenarios(self):
        """Pack should have at least 20 scenarios."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert len(data['scenarios']) >= 20


class TestPlanManagementScenarios:
    """Tests for plan management scenarios."""

    def test_list_plans_scenario_exists(self):
        """Should have list_plans scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_list_available_plans' in data['scenarios']

    def test_get_plan_details_scenario_exists(self):
        """Should have get_plan_details scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_get_plan_details' in data['scenarios']

    def test_plan_limits_structure_scenario_exists(self):
        """Should have plan_limits_structure scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_plan_limits_structure' in data['scenarios']


class TestQuotaEnforcementScenarios:
    """Tests for quota enforcement scenarios."""

    def test_jobs_per_day_allowed_scenario_exists(self):
        """Should have jobs_per_day_allowed scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_jobs_per_day_allowed' in data['scenarios']

    def test_jobs_per_day_denied_scenario_exists(self):
        """Should have jobs_per_day_denied scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_jobs_per_day_denied' in data['scenarios']

    def test_429_response_structure_scenario_exists(self):
        """Should have 429_response_structure scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_429_response_structure' in data['scenarios']

    def test_retry_after_header_scenario_exists(self):
        """Should have retry_after_header scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_retry_after_header' in data['scenarios']


class TestProjectOverrideScenarios:
    """Tests for project override scenarios."""

    def test_override_get_scenario_exists(self):
        """Should have override_get scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_project_override_get' in data['scenarios']

    def test_override_set_scenario_exists(self):
        """Should have override_set scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_project_override_set' in data['scenarios']

    def test_override_takes_precedence_scenario_exists(self):
        """Should have override_takes_precedence scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_override_takes_precedence' in data['scenarios']

    def test_zero_override_unlimited_scenario_exists(self):
        """Should have zero_override_unlimited scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_zero_override_unlimited' in data['scenarios']


class TestUsageTrackingScenarios:
    """Tests for usage tracking scenarios."""

    def test_usage_tenant_summary_scenario_exists(self):
        """Should have usage_tenant_summary scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_usage_tenant_summary' in data['scenarios']

    def test_usage_project_summary_scenario_exists(self):
        """Should have usage_project_summary scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_usage_project_summary' in data['scenarios']

    def test_usage_export_csv_scenario_exists(self):
        """Should have usage_export_csv scenario."""
        with open(PACK_PATH, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert 'quotas_usage_export_csv' in data['scenarios']


class TestRequestFiles:
    """Tests for request files."""

    def test_requests_directory_exists(self):
        """Requests directory should exist."""
        assert os.path.exists(REQUESTS_PATH)

    def test_list_plans_request_exists(self):
        """Should have list_plans request file."""
        path = os.path.join(REQUESTS_PATH, 'quotas_list_available_plans.json')
        assert os.path.exists(path)

    def test_jobs_denied_request_exists(self):
        """Should have jobs_denied request file."""
        path = os.path.join(REQUESTS_PATH, 'quotas_jobs_per_day_denied.json')
        assert os.path.exists(path)

    def test_override_precedence_request_exists(self):
        """Should have override_precedence request file."""
        path = os.path.join(REQUESTS_PATH, 'quotas_override_takes_precedence.json')
        assert os.path.exists(path)

    def test_usage_summary_request_exists(self):
        """Should have usage_summary request file."""
        path = os.path.join(REQUESTS_PATH, 'quotas_usage_tenant_summary.json')
        assert os.path.exists(path)

    def test_429_structure_request_exists(self):
        """Should have 429_structure request file."""
        path = os.path.join(REQUESTS_PATH, 'quotas_429_response_structure.json')
        assert os.path.exists(path)

    def test_zero_unlimited_request_exists(self):
        """Should have zero_unlimited request file."""
        path = os.path.join(REQUESTS_PATH, 'quotas_zero_override_unlimited.json')
        assert os.path.exists(path)


class TestExpectedFiles:
    """Tests for expected files."""

    def test_expected_directory_exists(self):
        """Expected directory should exist."""
        assert os.path.exists(EXPECTED_PATH)

    def test_list_plans_expected_exists(self):
        """Should have list_plans expected file."""
        path = os.path.join(EXPECTED_PATH, 'quotas_list_available_plans.json')
        assert os.path.exists(path)

    def test_jobs_denied_expected_exists(self):
        """Should have jobs_denied expected file."""
        path = os.path.join(EXPECTED_PATH, 'quotas_jobs_per_day_denied.json')
        assert os.path.exists(path)

    def test_override_precedence_expected_exists(self):
        """Should have override_precedence expected file."""
        path = os.path.join(EXPECTED_PATH, 'quotas_override_takes_precedence.json')
        assert os.path.exists(path)

    def test_usage_summary_expected_exists(self):
        """Should have usage_summary expected file."""
        path = os.path.join(EXPECTED_PATH, 'quotas_usage_tenant_summary.json')
        assert os.path.exists(path)

    def test_429_structure_expected_exists(self):
        """Should have 429_structure expected file."""
        path = os.path.join(EXPECTED_PATH, 'quotas_429_response_structure.json')
        assert os.path.exists(path)

    def test_zero_unlimited_expected_exists(self):
        """Should have zero_unlimited expected file."""
        path = os.path.join(EXPECTED_PATH, 'quotas_zero_override_unlimited.json')
        assert os.path.exists(path)


class TestExpectedFileStructure:
    """Tests for expected file structure."""

    def test_429_expected_has_status(self):
        """429 expected should have status 429."""
        import json
        path = os.path.join(EXPECTED_PATH, 'quotas_429_response_structure.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['status'] == 429

    def test_429_expected_has_assertions(self):
        """429 expected should have assertions."""
        import json
        path = os.path.join(EXPECTED_PATH, 'quotas_429_response_structure.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert 'assertions' in data
        assert len(data['assertions']) >= 5

    def test_list_plans_expected_has_status_200(self):
        """List plans expected should have status 200."""
        import json
        path = os.path.join(EXPECTED_PATH, 'quotas_list_available_plans.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data['status'] == 200

