#!/usr/bin/env python3
"""
Backfill script for v3.7.0 - Create default projects for existing tenants.

This script:
1. Lists all tenants in the auth database
2. For each tenant, creates a "Default Project" if not exists
3. Adds all existing users as owners of the default project

Usage:
    python scripts/db/backfill_default_project.py [--dry-run] [--tenant-id TENANT_ID]

Options:
    --dry-run       Show what would be done without making changes
    --tenant-id     Only backfill for a specific tenant

Environment:
    AUTH_DB_PATH    Path to auth database (default: /data/auth.sqlite)
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# Add bess-dispatch to path for imports
BESS_DIR = Path(__file__).parent.parent.parent / "services" / "bess-dispatch"
sys.path.insert(0, str(BESS_DIR))

from auth_store import AuthStore, DEFAULT_PROJECT_NAME


def get_all_tenants(db_path: str) -> list:
    """Get all tenant IDs from the database."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM tenants")
        return [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Backfill default projects for existing tenants (v3.7.0)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        help="Only backfill for a specific tenant",
    )
    args = parser.parse_args()

    # Get database path
    db_path = os.getenv("AUTH_DB_PATH", "/data/auth.sqlite")

    if not Path(db_path).exists():
        print(f"ERROR: Database not found at {db_path}")
        print("Set AUTH_DB_PATH environment variable to the correct path")
        sys.exit(1)

    print(f"Using database: {db_path}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("-" * 60)

    # Get tenants to process
    if args.tenant_id:
        tenants = [{"id": args.tenant_id, "name": "specified"}]
    else:
        tenants = get_all_tenants(db_path)

    if not tenants:
        print("No tenants found in database")
        sys.exit(0)

    print(f"Found {len(tenants)} tenant(s) to process")
    print()

    # Initialize store (this also runs migrations)
    store = AuthStore(db_path)

    total_projects = 0
    total_members = 0
    skipped = 0

    for tenant in tenants:
        tenant_id = tenant["id"]
        print(f"Processing tenant: {tenant_id} ({tenant['name']})")

        # Check existing projects
        projects = store.list_projects(tenant_id, include_archived=True)
        has_default = any(p["name"] == DEFAULT_PROJECT_NAME for p in projects)

        if has_default:
            print(f"  - Default project already exists, skipping")
            skipped += 1
            continue

        # Get users for this tenant
        users = store.list_users(tenant_id)
        print(f"  - Found {len(users)} user(s)")

        if args.dry_run:
            print(f"  - Would create '{DEFAULT_PROJECT_NAME}'")
            print(f"  - Would add {len(users)} user(s) as owners")
            total_projects += 1
            total_members += len(users)
        else:
            result = store.backfill_default_project(tenant_id)
            if result["already_existed"]:
                print(f"  - Default project already existed (race condition)")
                skipped += 1
            else:
                print(f"  - Created '{DEFAULT_PROJECT_NAME}' (id: {result['project']['id']})")
                print(f"  - Added {result['members_added']} user(s) as owners")
                total_projects += 1
                total_members += result["members_added"]

        print()

    print("-" * 60)
    print("Summary:")
    print(f"  Projects created: {total_projects}")
    print(f"  Members added: {total_members}")
    print(f"  Tenants skipped: {skipped}")

    if args.dry_run:
        print()
        print("This was a DRY RUN. No changes were made.")
        print("Run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
