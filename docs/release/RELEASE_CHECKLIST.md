# Release Checklist

This checklist ensures consistent, high-quality releases for the BESS Dispatch service.

## Pre-Release (RC Phase)

### 1. Code Freeze
- [ ] All features for the release are merged to main
- [ ] No pending PRs with breaking changes
- [ ] All CI checks passing on main

### 2. Contract Freeze
- [ ] Run `python scripts/contracts/export_contracts.py --check`
- [ ] No drift from documented contracts
- [ ] Update contract schemas if intentional changes: `--version vX.Y.Z`

### 3. Scenario Freeze
- [ ] Run `python scripts/check_scenario_updates.py`
- [ ] All scenario changes approved in `docs/scenario_updates/APPROVAL.md`
- [ ] Baseline validation passes: `make validate-pack PACK=baseline`

### 4. Deprecations
- [ ] Review `docs/api/deprecations.json`
- [ ] All deprecated fields have removal dates
- [ ] No fields past their removal version

### 5. RC Validation
- [ ] Create RC tag: `git tag vX.Y.Z-rc1`
- [ ] Push tag: `git push origin vX.Y.Z-rc1`
- [ ] RC workflow completes successfully
- [ ] Download and verify RC artifacts

### 6. Local Testing
- [ ] Run `make rc` - all checks pass
- [ ] Start environment: `make dev-up`
- [ ] Run demo: `make demo`
- [ ] Verify API docs: http://localhost:8031/docs
- [ ] Check deprecations endpoint: http://localhost:8031/api/bess-dispatch/deprecations

## Release

### 7. Version Coherence
- [ ] `GET /version` returns correct version
- [ ] Contract schemas match version
- [ ] Deprecations registry up to date

### 8. Documentation
- [ ] CHANGELOG updated
- [ ] README updated if needed
- [ ] LOCAL_DEV.md accurate

### 9. Create Release
- [ ] Create release tag: `git tag vX.Y.Z`
- [ ] Push tag: `git push origin vX.Y.Z`
- [ ] Create GitHub release with notes
- [ ] Attach release artifacts

### 10. Post-Release
- [ ] Verify release artifacts downloadable
- [ ] Docker image available
- [ ] Announce release (if applicable)
- [ ] Update version for next development cycle

## Emergency Hotfix

For critical fixes that can't wait for next release:

1. Create hotfix branch from release tag: `git checkout -b hotfix/vX.Y.Z vX.Y.Z`
2. Apply minimal fix
3. Run `make rc` to validate
4. Create patch release tag: `git tag vX.Y.Z+1`
5. Cherry-pick to main if applicable

## Rollback

If a release has critical issues:

1. Revert to previous release tag
2. Rebuild from that tag
3. Deploy previous version
4. Create hotfix release with fix

## Version Format

- Major (X): Breaking changes
- Minor (Y): New features, backwards compatible
- Patch (Z): Bug fixes, backwards compatible
- RC: Release candidates (vX.Y.Z-rc1, vX.Y.Z-rc2, ...)

## Contacts

- Release Manager: [TBD]
- On-call: [TBD]
