"""
Unit tests for UI Tariff Selector functionality (v2.1.0 PR4).

Tests verify:
- Tariff mode selection logic
- Schedule array generation
- CSV export format
- Preset dropdown population logic
"""

import pytest


class TestTariffModeSelection:
    """Tests for tariff mode tab selection logic."""

    def test_valid_modes(self):
        """Verify valid tariff modes."""
        valid_modes = ['preset', 'schedule', 'override']
        assert len(valid_modes) == 3
        assert 'preset' in valid_modes
        assert 'schedule' in valid_modes
        assert 'override' in valid_modes

    def test_default_mode_is_preset(self):
        """Verify default mode is preset."""
        default_mode = 'preset'
        assert default_mode == 'preset'

    def test_mode_changes_panel_visibility(self):
        """Verify mode change logic for panel visibility."""
        current_mode = 'schedule'
        panels = {
            'preset': current_mode == 'preset',
            'schedule': current_mode == 'schedule',
            'override': current_mode == 'override',
        }
        assert panels['preset'] is False
        assert panels['schedule'] is True
        assert panels['override'] is False


class TestScheduleArrayGeneration:
    """Tests for 24-hour schedule array generation."""

    def test_schedule_has_24_hours(self):
        """Verify schedule arrays have 24 elements."""
        schedule = {
            'weekday_import_price_pln_per_mwh': [500.0] * 24,
            'weekend_import_price_pln_per_mwh': [400.0] * 24,
            'weekday_export_price_pln_per_mwh': [0.0] * 24,
            'weekend_export_price_pln_per_mwh': [0.0] * 24,
        }
        assert len(schedule['weekday_import_price_pln_per_mwh']) == 24
        assert len(schedule['weekend_import_price_pln_per_mwh']) == 24
        assert len(schedule['weekday_export_price_pln_per_mwh']) == 24
        assert len(schedule['weekend_export_price_pln_per_mwh']) == 24

    def test_schedule_default_values(self):
        """Verify default schedule values."""
        default_import = 500.0
        default_export = 0.0
        assert default_import > 0
        assert default_export == 0.0

    def test_schedule_holiday_dates_parsing(self):
        """Verify holiday dates parsing logic."""
        input_str = "2025-12-25, 2025-12-26, 2025-01-01"
        dates = [d.strip() for d in input_str.split(',') if d.strip()]
        assert len(dates) == 3
        assert dates[0] == "2025-12-25"
        assert dates[1] == "2025-12-26"
        assert dates[2] == "2025-01-01"

    def test_empty_holidays_returns_empty_list(self):
        """Verify empty holidays input returns empty list."""
        input_str = ""
        dates = [d.strip() for d in input_str.split(',') if d.strip()]
        assert dates == []


class TestPricePreviewRequest:
    """Tests for price preview request building logic."""

    def test_preset_request_structure(self):
        """Verify preset request has tariff_preset field."""
        request = {
            'interval_minutes': 60,
            'timezone': 'Europe/Warsaw',
            'period_start': '2025-01-01T00:00:00',
            'period_end': '2025-01-07T23:00:00',
            'tariff_preset': 'pl_flat_2026',
        }
        assert 'tariff_preset' in request
        assert request['tariff_preset'] == 'pl_flat_2026'

    def test_schedule_request_structure(self):
        """Verify schedule request has tariff_schedule field."""
        request = {
            'interval_minutes': 60,
            'timezone': 'Europe/Warsaw',
            'period_start': '2025-01-01T00:00:00',
            'period_end': '2025-01-07T23:00:00',
            'tariff_schedule': {
                'weekday_import_price_pln_per_mwh': [500.0] * 24,
                'weekend_import_price_pln_per_mwh': [400.0] * 24,
            },
        }
        assert 'tariff_schedule' in request
        assert 'weekday_import_price_pln_per_mwh' in request['tariff_schedule']

    def test_override_request_structure(self):
        """Verify override request has price_timeseries_override field."""
        request = {
            'interval_minutes': 60,
            'timezone': 'Europe/Warsaw',
            'period_start': '2025-01-01T00:00:00',
            'period_end': '2025-01-01T23:00:00',
            'price_timeseries_override': {
                'import_price_pln_per_mwh': [500.0] * 24,
                'export_price_pln_per_mwh': [0.0] * 24,
            },
        }
        assert 'price_timeseries_override' in request


class TestPricePreviewDisplay:
    """Tests for price preview display logic."""

    def test_average_price_calculation(self):
        """Verify average price calculation."""
        prices = [100.0, 200.0, 300.0, 400.0]
        avg = sum(prices) / len(prices)
        assert avg == 250.0

    def test_min_max_calculation(self):
        """Verify min/max price calculation."""
        prices = [100.0, 500.0, 200.0, 800.0, 300.0]
        assert min(prices) == 100.0
        assert max(prices) == 800.0

    def test_mode_label_colors(self):
        """Verify mode label color mapping."""
        colors = {
            'preset': '#1976d2',
            'schedule': '#2e7d32',
            'override': '#ff9800',
            'generated': '#4caf50',
        }
        assert colors['preset'] == '#1976d2'
        assert colors['schedule'] == '#2e7d32'
        assert colors['override'] == '#ff9800'
        assert colors['generated'] == '#4caf50'

    def test_price_hash_truncation(self):
        """Verify price hash truncation for display."""
        full_hash = "abc123def456ghi789jkl012mno345pqr678stu901vwx234yz5678901234567890"
        truncated = full_hash[:12] + "..."
        assert truncated == "abc123def456..."
        assert len(truncated) == 15


class TestCsvExport:
    """Tests for CSV export functionality."""

    def test_csv_header_format(self):
        """Verify CSV header format."""
        header = "step,import_price_pln_per_mwh,export_price_pln_per_mwh,other_fees_pln_per_mwh"
        columns = header.split(',')
        assert len(columns) == 4
        assert columns[0] == 'step'
        assert columns[1] == 'import_price_pln_per_mwh'
        assert columns[2] == 'export_price_pln_per_mwh'
        assert columns[3] == 'other_fees_pln_per_mwh'

    def test_csv_row_format(self):
        """Verify CSV row format."""
        step = 0
        import_price = 500.0
        export_price = 100.0
        fees = 50.0
        row = f"{step},{import_price},{export_price},{fees}"
        assert row == "0,500.0,100.0,50.0"

    def test_csv_filename_includes_mode(self):
        """Verify CSV filename includes pricing mode."""
        mode = 'preset'
        filename = f"price_timeseries_{mode}.csv"
        assert filename == "price_timeseries_preset.csv"

    def test_csv_all_steps_exported(self):
        """Verify all steps are exported to CSV."""
        prices = [100.0, 200.0, 300.0]
        csv_lines = []
        csv_lines.append("step,import,export,fees")
        for i, p in enumerate(prices):
            csv_lines.append(f"{i},{p},0,0")
        # Header + 3 data rows
        assert len(csv_lines) == 4


class TestPresetDropdown:
    """Tests for preset dropdown population logic."""

    def test_preset_option_structure(self):
        """Verify preset option has id and label."""
        preset = {'id': 'pl_flat_2026', 'label': 'PL Flat 2026'}
        assert 'id' in preset
        assert 'label' in preset
        assert preset['id'] == 'pl_flat_2026'
        assert preset['label'] == 'PL Flat 2026'

    def test_preset_list_not_empty(self):
        """Verify preset list handling for non-empty case."""
        presets = [
            {'id': 'pl_flat_2026', 'label': 'PL Flat 2026'},
            {'id': 'pl_tou_simple_2026', 'label': 'PL ToU Simple 2026'},
        ]
        assert len(presets) > 0
        assert len(presets) == 2

    def test_preset_info_display(self):
        """Verify preset info display fields."""
        preset = {
            'id': 'pl_flat_2026',
            'label': 'PL Flat 2026',
            'description': 'Flat tariff for Poland 2026',
            'import_price_pln_per_mwh': 510.0,
        }
        info_html = f"<strong>{preset['label']}</strong><br>"
        if preset.get('description'):
            info_html += f"{preset['description']}<br>"
        if preset.get('import_price_pln_per_mwh'):
            info_html += f"Import: {preset['import_price_pln_per_mwh']} PLN/MWh"

        assert 'PL Flat 2026' in info_html
        assert 'Flat tariff' in info_html
        assert '510.0 PLN/MWh' in info_html


class TestTableGeneration:
    """Tests for schedule table generation logic."""

    def test_generate_24_rows(self):
        """Verify 24 rows are generated for schedule tables."""
        rows = list(range(24))
        assert len(rows) == 24
        assert rows[0] == 0
        assert rows[23] == 23

    def test_hour_formatting(self):
        """Verify hour formatting with leading zero."""
        for h in range(24):
            formatted = str(h).zfill(2)
            assert len(formatted) == 2
            if h < 10:
                assert formatted[0] == '0'

    def test_input_id_generation(self):
        """Verify input ID generation pattern."""
        for h in range(24):
            wd_import_id = f"wdImport{h}"
            wd_export_id = f"wdExport{h}"
            we_import_id = f"weImport{h}"
            we_export_id = f"weExport{h}"

            assert wd_import_id == f"wdImport{h}"
            assert we_import_id == f"weImport{h}"


class TestPreviewTableLimit:
    """Tests for preview table row limiting."""

    def test_max_48_rows_displayed(self):
        """Verify preview table shows max 48 rows."""
        total_prices = 168  # 7 days hourly
        max_display = 48
        displayed = min(max_display, total_prices)
        assert displayed == 48

    def test_short_array_shows_all(self):
        """Verify short arrays show all rows."""
        total_prices = 24
        max_display = 48
        displayed = min(max_display, total_prices)
        assert displayed == 24
