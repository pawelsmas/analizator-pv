"""
Prometheus metrics for metadata operations (v1.3.0).

Tracks:
- PATCH metadata operations (runs and jobs)
- List filters (tag, free-text search)
- Metadata field updates (label, tags, notes)
"""

from prometheus_client import Counter, Histogram


# -----------------------------------------------------------------------------
# Counters - Run Metadata
# -----------------------------------------------------------------------------

RUN_METADATA_PATCH_TOTAL = Counter(
    "bess_run_metadata_patch_total",
    "Total PATCH operations on run metadata",
    ["has_label", "has_tags", "has_notes"],
)

RUN_METADATA_PATCH_ERRORS_TOTAL = Counter(
    "bess_run_metadata_patch_errors_total",
    "Total PATCH errors (404/422/503)",
    ["error_type"],
)


# -----------------------------------------------------------------------------
# Counters - Job Metadata
# -----------------------------------------------------------------------------

JOB_METADATA_PATCH_TOTAL = Counter(
    "bess_job_metadata_patch_total",
    "Total PATCH operations on job metadata",
    ["has_label", "has_tags", "has_notes"],
)

JOB_METADATA_PATCH_ERRORS_TOTAL = Counter(
    "bess_job_metadata_patch_errors_total",
    "Total PATCH errors (404/422/503)",
    ["error_type"],
)


# -----------------------------------------------------------------------------
# Counters - List Filters
# -----------------------------------------------------------------------------

RUN_LIST_TAG_FILTER_TOTAL = Counter(
    "bess_run_list_tag_filter_total",
    "Total run list requests with tag filter",
)

RUN_LIST_SEARCH_TOTAL = Counter(
    "bess_run_list_search_total",
    "Total run list requests with free-text search (q parameter)",
)

RUN_LIST_SORT_TOTAL = Counter(
    "bess_run_list_sort_total",
    "Total run list requests with explicit sort order",
    ["sort_order"],
)


# -----------------------------------------------------------------------------
# Histograms
# -----------------------------------------------------------------------------

RUN_METADATA_TAGS_COUNT = Histogram(
    "bess_run_metadata_tags_count",
    "Number of tags per PATCH operation",
    buckets=[0, 1, 2, 3, 5, 10, 15, 20],
)

JOB_METADATA_TAGS_COUNT = Histogram(
    "bess_job_metadata_tags_count",
    "Number of tags per PATCH operation",
    buckets=[0, 1, 2, 3, 5, 10, 15, 20],
)

RUN_METADATA_NOTES_LENGTH = Histogram(
    "bess_run_metadata_notes_length",
    "Length of notes in PATCH operations",
    buckets=[0, 50, 100, 200, 500, 1000, 2000],
)

JOB_METADATA_NOTES_LENGTH = Histogram(
    "bess_job_metadata_notes_length",
    "Length of notes in PATCH operations",
    buckets=[0, 50, 100, 200, 500, 1000, 2000],
)


# -----------------------------------------------------------------------------
# Helper Functions - Run Metadata
# -----------------------------------------------------------------------------

def record_run_metadata_patch(
    has_label: bool,
    has_tags: bool,
    has_notes: bool,
    tags_count: int = 0,
    notes_length: int = 0,
) -> None:
    """Record a successful PATCH operation on run metadata."""
    RUN_METADATA_PATCH_TOTAL.labels(
        has_label="true" if has_label else "false",
        has_tags="true" if has_tags else "false",
        has_notes="true" if has_notes else "false",
    ).inc()

    if has_tags:
        RUN_METADATA_TAGS_COUNT.observe(tags_count)

    if has_notes:
        RUN_METADATA_NOTES_LENGTH.observe(notes_length)


def record_run_metadata_patch_error(error_type: str) -> None:
    """Record a PATCH error on run metadata."""
    RUN_METADATA_PATCH_ERRORS_TOTAL.labels(error_type=error_type).inc()


# -----------------------------------------------------------------------------
# Helper Functions - Job Metadata
# -----------------------------------------------------------------------------

def record_job_metadata_patch(
    has_label: bool,
    has_tags: bool,
    has_notes: bool,
    tags_count: int = 0,
    notes_length: int = 0,
) -> None:
    """Record a successful PATCH operation on job metadata."""
    JOB_METADATA_PATCH_TOTAL.labels(
        has_label="true" if has_label else "false",
        has_tags="true" if has_tags else "false",
        has_notes="true" if has_notes else "false",
    ).inc()

    if has_tags:
        JOB_METADATA_TAGS_COUNT.observe(tags_count)

    if has_notes:
        JOB_METADATA_NOTES_LENGTH.observe(notes_length)


def record_job_metadata_patch_error(error_type: str) -> None:
    """Record a PATCH error on job metadata."""
    JOB_METADATA_PATCH_ERRORS_TOTAL.labels(error_type=error_type).inc()


# -----------------------------------------------------------------------------
# Helper Functions - List Filters
# -----------------------------------------------------------------------------

def record_run_list_tag_filter() -> None:
    """Record a run list request with tag filter."""
    RUN_LIST_TAG_FILTER_TOTAL.inc()


def record_run_list_search() -> None:
    """Record a run list request with free-text search."""
    RUN_LIST_SEARCH_TOTAL.inc()


def record_run_list_sort(sort_order: str) -> None:
    """Record a run list request with explicit sort order."""
    RUN_LIST_SORT_TOTAL.labels(sort_order=sort_order).inc()
