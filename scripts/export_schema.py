#!/usr/bin/env python3
"""
Export Pydantic models to JSON Schema files.

Usage:
    python scripts/export_schema.py

Outputs:
    docs/contracts/bess_sizing_request.schema.json
    docs/contracts/bess_sizing_response.schema.json
    docs/contracts/bess_dispatch_request.schema.json
    docs/contracts/bess_dispatch_response.schema.json
"""

import json
import sys
from pathlib import Path

# Add bess-dispatch to path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "bess-dispatch"))

from models import (
    SizingRequest,
    SizingResult,
    DispatchRequest,
    DispatchResult,
    SizingVariantResult,
    SavingsBreakdown,
    PeriodInfo,
    ArbitrageConfig,
)


def export_schema(model, output_path: Path):
    """Export Pydantic model to JSON Schema file."""
    schema = model.model_json_schema()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"  Exported: {output_path}")


def main():
    output_dir = Path(__file__).parent.parent / "docs" / "contracts"
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Exporting JSON Schemas...")

    # Main API schemas
    export_schema(SizingRequest, output_dir / "bess_sizing_request.schema.json")
    export_schema(SizingResult, output_dir / "bess_sizing_response.schema.json")
    export_schema(DispatchRequest, output_dir / "bess_dispatch_request.schema.json")
    export_schema(DispatchResult, output_dir / "bess_dispatch_response.schema.json")

    # Component schemas (for documentation)
    export_schema(SizingVariantResult, output_dir / "sizing_variant.schema.json")
    export_schema(SavingsBreakdown, output_dir / "savings_breakdown.schema.json")
    export_schema(PeriodInfo, output_dir / "period_info.schema.json")
    export_schema(ArbitrageConfig, output_dir / "arbitrage_config.schema.json")

    print(f"\nAll schemas exported to: {output_dir}")


if __name__ == "__main__":
    main()
