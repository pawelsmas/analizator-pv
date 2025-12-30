"""
Contract tests for v1.2.0 SSE job progress streaming endpoint.

Tests verify:
- SSE endpoint returns text/event-stream content type
- Completed jobs return single done/error/cancelled event
- Event format follows SSE specification
- Query parameters (poll_interval, timeout) are validated
"""
import json
import time

import pytest
import requests

from ._api import post_json


# API paths
JOBS_BATCH_PATH = "/api/bess-dispatch/jobs/sizing-batch"
BASE_URL = "http://localhost:8031"


def get_events_url(job_id: str, **params) -> str:
    """Build SSE events URL with optional query params."""
    url = f"{BASE_URL}/api/bess-dispatch/jobs/{job_id}/events"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"
    return url


def create_completed_job():
    """Create a job that completes immediately (wait=true)."""
    payload = {
        "batch_id": f"sse_test_{int(time.time() * 1000)}",
        "wait": True,
        "items": [
            {
                "item_id": "test_item",
                "request": {
                    "load_kw": [50, 60, 70, 80, 90, 100] * 4,
                    "pv_generation_kw": [0, 0, 0, 5, 20, 40] * 4,
                    "energy_price_pln_kwh": 0.8,
                    "mode": "stacked",
                    "peak_limit_kw": 80,
                },
            }
        ],
    }
    return post_json(JOBS_BATCH_PATH, payload)


def parse_sse_events(response_text: str) -> list:
    """Parse SSE text into list of (event_type, data) tuples."""
    events = []
    current_event = None
    current_data = None

    for line in response_text.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            current_data = line[6:].strip()
        elif line == "" and current_event and current_data:
            events.append((current_event, json.loads(current_data)))
            current_event = None
            current_data = None

    return events


class TestSSEEndpointPresence:
    """Test SSE endpoint exists and returns proper content type."""

    def test_events_endpoint_exists(self):
        """Verify SSE endpoint exists."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"]), stream=True)

        assert response.status_code == 200

    def test_returns_event_stream_content_type(self):
        """Verify Content-Type is text/event-stream."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"]), stream=True)

        assert "text/event-stream" in response.headers.get("Content-Type", "")

    def test_returns_cache_control_no_cache(self):
        """Verify Cache-Control is no-cache for SSE."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"]), stream=True)

        assert "no-cache" in response.headers.get("Cache-Control", "")


class TestSSENotFound:
    """Test SSE endpoint 404 behavior."""

    def test_nonexistent_job_returns_404(self):
        """Verify 404 for non-existent job."""
        response = requests.get(get_events_url("nonexistent-job-id"))

        assert response.status_code == 404


class TestSSECompletedJob:
    """Test SSE behavior for already completed jobs."""

    def test_done_job_returns_done_event(self):
        """Verify done job returns single done event."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"]))

        events = parse_sse_events(response.text)
        assert len(events) >= 1

        # Find done event
        done_events = [e for e in events if e[0] == "done"]
        assert len(done_events) == 1

    def test_done_event_has_items_done(self):
        """Verify done event has items_done field."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"]))

        events = parse_sse_events(response.text)
        done_event = next((e for e in events if e[0] == "done"), None)

        assert done_event is not None
        assert "items_done" in done_event[1]
        assert done_event[1]["items_done"] >= 0

    def test_done_event_has_items_total(self):
        """Verify done event has items_total field."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"]))

        events = parse_sse_events(response.text)
        done_event = next((e for e in events if e[0] == "done"), None)

        assert done_event is not None
        assert "items_total" in done_event[1]

    def test_done_event_has_error_count(self):
        """Verify done event has error_count field."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"]))

        events = parse_sse_events(response.text)
        done_event = next((e for e in events if e[0] == "done"), None)

        assert done_event is not None
        assert "error_count" in done_event[1]

    def test_done_event_has_processing_time_ms(self):
        """Verify done event has processing_time_ms field."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"]))

        events = parse_sse_events(response.text)
        done_event = next((e for e in events if e[0] == "done"), None)

        assert done_event is not None
        assert "processing_time_ms" in done_event[1]


class TestSSEEventFormat:
    """Test SSE event format follows specification."""

    def test_event_format_has_event_line(self):
        """Verify events have event: line."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"]))

        assert "event: done" in response.text or "event: status" in response.text

    def test_event_format_has_data_line(self):
        """Verify events have data: line."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"]))

        assert "data: " in response.text

    def test_event_data_is_valid_json(self):
        """Verify event data is valid JSON."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"]))

        events = parse_sse_events(response.text)
        assert len(events) >= 1

        for event_type, event_data in events:
            assert isinstance(event_data, dict)


class TestSSEQueryParameters:
    """Test SSE query parameter validation."""

    def test_poll_interval_too_low(self):
        """Verify poll_interval validation (min 0.1)."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"], poll_interval=0.01))

        # Should return 422 for invalid parameter
        assert response.status_code == 422

    def test_poll_interval_too_high(self):
        """Verify poll_interval validation (max 5.0)."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"], poll_interval=10.0))

        # Should return 422 for invalid parameter
        assert response.status_code == 422

    def test_valid_poll_interval_accepted(self):
        """Verify valid poll_interval is accepted."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"], poll_interval=1.0))

        assert response.status_code == 200

    def test_timeout_too_low(self):
        """Verify timeout validation (min 1.0)."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"], timeout=0.1))

        # Should return 422 for invalid parameter
        assert response.status_code == 422

    def test_valid_timeout_accepted(self):
        """Verify valid timeout is accepted."""
        job = create_completed_job()
        response = requests.get(get_events_url(job["job_id"], timeout=30.0))

        assert response.status_code == 200
