"""
Report Models (v2.4.0)

Data Transfer Objects for report generation.

Defines:
- ReportProfile: client | engineering
- ReportBranding: customizable report header fields
- ReportOptions: profile + branding + notes + max_table_rows
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ReportProfile(str, Enum):
    """
    Report profile determines which sections are included.

    - client: Executive summary, MoneyLedger, Flows, Warnings
    - engineering: All of client + debug_events, invariants, cycle_summary, pricing details
    """
    CLIENT = "client"
    ENGINEERING = "engineering"


class ReportBranding(BaseModel):
    """
    Customizable branding fields for report header.

    All fields are optional and have max length limits.
    """
    report_title: Optional[str] = Field(
        None,
        max_length=120,
        description="Custom report title (max 120 chars)"
    )
    client_name: Optional[str] = Field(
        None,
        max_length=120,
        description="Client/company name (max 120 chars)"
    )
    site_name: Optional[str] = Field(
        None,
        max_length=120,
        description="Site/project name (max 120 chars)"
    )
    prepared_by: Optional[str] = Field(
        None,
        max_length=120,
        description="Report author name (max 120 chars)"
    )
    prepared_for: Optional[str] = Field(
        None,
        max_length=120,
        description="Report recipient name (max 120 chars)"
    )


class ReportOptions(BaseModel):
    """
    Options for report generation.

    These options do NOT affect calculation results - only presentation.
    """
    profile: ReportProfile = Field(
        ReportProfile.CLIENT,
        description="Report profile: 'client' (executive) or 'engineering' (detailed)"
    )
    branding: Optional[ReportBranding] = Field(
        None,
        description="Custom branding for report header"
    )
    notes: Optional[str] = Field(
        None,
        max_length=2000,
        description="Custom notes to include in report (max 2000 chars)"
    )
    max_table_rows: int = Field(
        48,
        ge=12,
        le=240,
        description="Maximum rows to show in preview tables (12-240)"
    )
