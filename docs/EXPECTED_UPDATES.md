# Expected KPI Updates Policy

This document describes the policy for updating `expected_kpis.json` files in scenario definitions.

## When Expected KPIs May Be Updated

Expected KPI values should only be changed when:

1. **Bug fix in calculation logic** - A bug in the sizing algorithm was fixed, causing KPIs to change correctly
2. **Intentional algorithm improvement** - An algorithm change was made that intentionally affects KPIs
3. **Input data correction** - The scenario's input data was corrected, affecting expected outputs
4. **Tolerance adjustment** - Tolerance values need adjustment based on new understanding

## When Expected KPIs Should NOT Be Updated

Do NOT update expected KPIs when:

1. **Tests are failing unexpectedly** - Investigate root cause first
2. **"Making tests pass"** - Changing expected values just to pass CI is not acceptable
3. **Unknown reason** - If you don't understand why values changed, don't update

## Required Approval Process

Any PR that modifies `expected_kpis.json` files must also update `docs/expected_updates/APPROVAL.md` with:

```markdown
## Change expected KPIs
Date: YYYY-MM-DD
Reason: [Brief explanation of why expected values are changing]
Scenarios:
- [List of affected scenario IDs]
Links:
- PR #[related PR number or issue]
```

## CI Guard

The `scripts/check_expected_updates.py` script runs in CI and will fail the build if:
- Any `expected_kpis.json` file is modified
- AND `docs/expected_updates/APPROVAL.md` is not also modified in the same PR

This prevents silent drift in baseline values.
