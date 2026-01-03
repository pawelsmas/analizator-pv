"""
Unit tests for variant space helper (v4.5.0 PR2).

Tests:
- Grid size computation
- Grid size validation
- Power candidate generation
- Variant name/label generation
- Full variant space generation
- CAPEX filtering
"""

import sys
from pathlib import Path
import pytest

# Add services/bess-dispatch to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "bess-dispatch"))


class TestComputeGridSize:
    """Tests for compute_grid_size function."""

    def test_compute_grid_size_basic(self):
        """Basic grid size computation."""
        from variant_space_helper import compute_grid_size

        # 3 powers x 2 durations = 6
        result = compute_grid_size(
            power_candidates=[50.0, 100.0, 150.0],
            duration_candidates=[1.0, 2.0]
        )
        assert result == 6

    def test_compute_grid_size_single_power(self):
        """Grid with single power."""
        from variant_space_helper import compute_grid_size

        result = compute_grid_size(
            power_candidates=[100.0],
            duration_candidates=[1.0, 2.0, 4.0]
        )
        assert result == 3

    def test_compute_grid_size_single_duration(self):
        """Grid with single duration."""
        from variant_space_helper import compute_grid_size

        result = compute_grid_size(
            power_candidates=[50.0, 100.0, 150.0, 200.0],
            duration_candidates=[2.0]
        )
        assert result == 4

    def test_compute_grid_size_empty(self):
        """Empty grid."""
        from variant_space_helper import compute_grid_size

        result = compute_grid_size(
            power_candidates=[],
            duration_candidates=[1.0]
        )
        assert result == 0


class TestValidateGridSize:
    """Tests for validate_grid_size function."""

    def test_valid_grid_size(self):
        """Grid within limits is valid."""
        from variant_space_helper import validate_grid_size

        is_valid, error = validate_grid_size(
            power_candidates=[50.0, 100.0],
            duration_candidates=[1.0, 2.0],
            max_variants=60
        )
        assert is_valid is True
        assert error is None

    def test_grid_size_at_limit(self):
        """Grid at exact limit is valid."""
        from variant_space_helper import validate_grid_size

        is_valid, error = validate_grid_size(
            power_candidates=[10.0, 20.0, 30.0],  # 3
            duration_candidates=[1.0, 2.0],  # 2
            max_variants=6  # 3 x 2 = 6
        )
        assert is_valid is True
        assert error is None

    def test_grid_exceeds_limit(self):
        """Grid exceeding limit returns error."""
        from variant_space_helper import validate_grid_size

        is_valid, error = validate_grid_size(
            power_candidates=[10.0 * i for i in range(1, 11)],  # 10
            duration_candidates=[1.0, 2.0, 3.0, 4.0],  # 4
            max_variants=30  # 10 x 4 = 40 > 30
        )
        assert is_valid is False
        assert "exceeds max_variants" in error
        assert "40" in error  # actual size
        assert "30" in error  # limit

    def test_empty_grid_is_invalid(self):
        """Empty grid returns error."""
        from variant_space_helper import validate_grid_size

        is_valid, error = validate_grid_size(
            power_candidates=[],
            duration_candidates=[1.0],
            max_variants=60
        )
        assert is_valid is False
        assert "empty" in error.lower()


class TestGeneratePowerCandidates:
    """Tests for generate_power_candidates function."""

    def test_generate_power_candidates_basic(self):
        """Generate power candidates with linspace."""
        from variant_space_helper import generate_power_candidates

        result = generate_power_candidates(p_min=50.0, p_max=150.0, power_steps=5)

        assert len(result) == 5
        assert result[0] == 50.0
        assert result[-1] == 150.0

    def test_generate_single_step(self):
        """Single step returns endpoints."""
        from variant_space_helper import generate_power_candidates

        result = generate_power_candidates(p_min=50.0, p_max=150.0, power_steps=1)

        assert len(result) == 2
        assert 50.0 in result
        assert 150.0 in result

    def test_generate_equal_min_max(self):
        """When min equals max, returns single value."""
        from variant_space_helper import generate_power_candidates

        result = generate_power_candidates(p_min=100.0, p_max=100.0, power_steps=5)

        assert len(result) == 1
        assert result[0] == 100.0


class TestVariantNaming:
    """Tests for variant name/label generation."""

    def test_get_variant_name(self):
        """Variant name format is correct."""
        from variant_space_helper import get_variant_name

        name = get_variant_name(power_kw=100.0, duration_h=2.0)
        assert name == "100kW_2.0h"

    def test_get_variant_label_standard_duration(self):
        """Standard durations get proper labels."""
        from variant_space_helper import get_variant_label

        label = get_variant_label(power_kw=100.0, duration_h=2.0)
        assert "Medium" in label
        assert "2h" in label
        assert "100kW" in label

    def test_get_variant_label_custom_duration(self):
        """Non-standard durations get custom label."""
        from variant_space_helper import get_variant_label

        label = get_variant_label(power_kw=100.0, duration_h=3.0)
        assert "Custom" in label
        assert "3.0h" in label

    def test_get_variant_enum_standard(self):
        """Standard durations map to correct enums."""
        from variant_space_helper import get_variant_enum
        from models import SizingVariant

        assert get_variant_enum(1.0) == SizingVariant.SMALL
        assert get_variant_enum(2.0) == SizingVariant.MEDIUM
        assert get_variant_enum(4.0) == SizingVariant.LARGE

    def test_get_variant_enum_non_standard(self):
        """Non-standard durations map to closest enum."""
        from variant_space_helper import get_variant_enum
        from models import SizingVariant

        assert get_variant_enum(0.5) == SizingVariant.SMALL
        assert get_variant_enum(1.5) == SizingVariant.SMALL
        assert get_variant_enum(2.5) == SizingVariant.MEDIUM
        assert get_variant_enum(5.0) == SizingVariant.LARGE


class TestGenerateVariantSpace:
    """Tests for generate_variant_space function."""

    def test_generate_from_min_max(self):
        """Generate variant space from min/max power."""
        from variant_space_helper import generate_variant_space

        variants, names, metadata = generate_variant_space(
            p_min=50.0,
            p_max=150.0,
            power_steps=3,
            default_durations=[1.0, 2.0]
        )

        # 3 powers x 2 durations = 6 variants
        assert len(variants) == 6
        assert len(names) == 6
        assert metadata["grid_size"] == 6
        assert metadata["power_count"] == 3
        assert metadata["duration_count"] == 2

    def test_generate_from_variant_space_config(self):
        """Generate from explicit VariantSpace configuration."""
        from variant_space_helper import generate_variant_space
        from models import VariantSpace

        config = VariantSpace(
            power_kw_candidates=[50.0, 100.0],
            duration_h_candidates=[1.0, 2.0, 4.0],
            max_variants=60
        )

        variants, names, metadata = generate_variant_space(
            variant_space_config=config
        )

        # 2 powers x 3 durations = 6 variants
        assert len(variants) == 6
        assert metadata["is_explicit_power"] is True

    def test_generate_raises_on_exceeds_limit(self):
        """Raises error when grid exceeds max_variants.

        Note: VariantSpace model validates at construction time,
        so ValidationError is raised from Pydantic, not ValueError.
        """
        from variant_space_helper import generate_variant_space
        from models import VariantSpace
        from pydantic import ValidationError

        # Model should reject construction when grid exceeds limit
        with pytest.raises(ValidationError) as exc_info:
            VariantSpace(
                power_kw_candidates=[i * 10.0 for i in range(1, 11)],  # 10
                duration_h_candidates=[1.0, 2.0, 4.0, 6.0, 8.0],  # 5
                max_variants=40  # 10 x 5 = 50 > 40
            )

        assert "exceeds max_variants" in str(exc_info.value)

    def test_generate_raises_without_power_spec(self):
        """Raises ValueError when no power specification provided."""
        from variant_space_helper import generate_variant_space

        with pytest.raises(ValueError) as exc_info:
            generate_variant_space(default_durations=[1.0])

        assert "power" in str(exc_info.value).lower()

    def test_variants_contain_all_combinations(self):
        """All power x duration combinations are included."""
        from variant_space_helper import generate_variant_space

        variants, _, _ = generate_variant_space(
            p_min=50.0,
            p_max=100.0,
            power_steps=2,
            default_durations=[1.0, 2.0]
        )

        # Should have: (50, 1), (100, 1), (50, 2), (100, 2)
        variant_set = set(variants)
        assert (50.0, 1.0) in variant_set
        assert (100.0, 1.0) in variant_set
        assert (50.0, 2.0) in variant_set
        assert (100.0, 2.0) in variant_set


class TestGetVariantInfoForResult:
    """Tests for get_variant_info_for_result function."""

    def test_info_has_all_fields(self):
        """Variant info contains all required fields."""
        from variant_space_helper import get_variant_info_for_result

        info = get_variant_info_for_result(power_kw=100.0, duration_h=2.0)

        assert "variant" in info
        assert "variant_label" in info
        assert "variant_name" in info
        assert "duration_h" in info

    def test_info_duration_matches(self):
        """Duration in info matches input."""
        from variant_space_helper import get_variant_info_for_result

        info = get_variant_info_for_result(power_kw=100.0, duration_h=4.0)

        assert info["duration_h"] == 4.0


class TestFilterVariantsByConstraint:
    """Tests for filter_variants_by_constraint function."""

    def test_filter_by_capex(self):
        """Filter removes variants exceeding CAPEX."""
        from variant_space_helper import filter_variants_by_constraint

        variants = [
            (50.0, 1.0),   # 50 kWh -> 100k PLN
            (100.0, 2.0),  # 200 kWh -> 400k PLN
            (200.0, 4.0),  # 800 kWh -> 1600k PLN
        ]

        filtered = filter_variants_by_constraint(
            variants=variants,
            max_capex_pln=500000,  # 500k PLN
            capex_per_kwh=2000.0
        )

        # Only first two should pass
        assert len(filtered) == 2
        assert (50.0, 1.0) in filtered
        assert (100.0, 2.0) in filtered
        assert (200.0, 4.0) not in filtered

    def test_no_filter_without_constraint(self):
        """No filtering when max_capex is None."""
        from variant_space_helper import filter_variants_by_constraint

        variants = [
            (100.0, 1.0),
            (200.0, 2.0),
            (300.0, 4.0),
        ]

        filtered = filter_variants_by_constraint(
            variants=variants,
            max_capex_pln=None
        )

        assert len(filtered) == 3
