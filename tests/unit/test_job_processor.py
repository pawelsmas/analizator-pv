"""
Unit tests for job_processor module.

Tests:
- process_job(): Main processing function
- JobProcessor class: Background processing
"""

import pytest
import os
import sys
import tempfile
import sqlite3
from unittest.mock import MagicMock, patch

# Add bess-dispatch to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../services/bess-dispatch'))

from job_processor import process_job, JobProcessor


class TestProcessJob:
    """Tests for process_job function."""

    def test_process_job_success(self):
        """process_job returns ok results for successful items."""
        mock_fn = MagicMock(return_value={"variants": []})

        with patch('job_processor.is_cancelled', return_value=False):
            with patch('job_processor.update_progress'):
                result = process_job(
                    job_id="test-job-1",
                    items=[
                        {"item_id": "A", "request": {"load_kw": [100]}},
                        {"item_id": "B", "request": {"load_kw": [200]}},
                    ],
                    fail_fast=False,
                    process_item_fn=mock_fn,
                )

        assert result["summary"]["total_items"] == 2
        assert result["summary"]["ok_count"] == 2
        assert result["summary"]["error_count"] == 0
        assert len(result["results"]) == 2
        assert result["results"][0]["status"] == "ok"
        assert result["results"][1]["status"] == "ok"

    def test_process_job_with_error(self):
        """process_job returns error results for failed items."""
        def failing_fn(request):
            if request.get("load_kw") == [100]:
                raise ValueError("Invalid load")
            return {"variants": []}

        with patch('job_processor.is_cancelled', return_value=False):
            with patch('job_processor.update_progress'):
                result = process_job(
                    job_id="test-job-2",
                    items=[
                        {"item_id": "A", "request": {"load_kw": [100]}},
                        {"item_id": "B", "request": {"load_kw": [200]}},
                    ],
                    fail_fast=False,
                    process_item_fn=failing_fn,
                )

        assert result["summary"]["total_items"] == 2
        assert result["summary"]["ok_count"] == 1
        assert result["summary"]["error_count"] == 1
        assert result["results"][0]["status"] == "error"
        assert "Invalid load" in result["results"][0]["error"]
        assert result["results"][1]["status"] == "ok"

    def test_process_job_fail_fast(self):
        """process_job stops on first error when fail_fast=True."""
        def failing_fn(request):
            if request.get("load_kw") == [100]:
                raise ValueError("Invalid load")
            return {"variants": []}

        with patch('job_processor.is_cancelled', return_value=False):
            with patch('job_processor.update_progress'):
                result = process_job(
                    job_id="test-job-3",
                    items=[
                        {"item_id": "A", "request": {"load_kw": [100]}},
                        {"item_id": "B", "request": {"load_kw": [200]}},
                    ],
                    fail_fast=True,
                    process_item_fn=failing_fn,
                )

        # Should stop after first error
        assert result["summary"]["total_items"] == 2
        assert result["summary"]["ok_count"] == 0
        assert result["summary"]["error_count"] == 1
        assert len(result["results"]) == 1

    def test_process_job_cancelled(self):
        """process_job stops when job is cancelled."""
        mock_fn = MagicMock(return_value={"variants": []})

        # Simulate cancellation after first item
        cancel_calls = [False, True]
        def is_cancelled_side_effect(job_id):
            return cancel_calls.pop(0) if cancel_calls else True

        with patch('job_processor.is_cancelled', side_effect=is_cancelled_side_effect):
            with patch('job_processor.update_progress'):
                result = process_job(
                    job_id="test-job-4",
                    items=[
                        {"item_id": "A", "request": {"load_kw": [100]}},
                        {"item_id": "B", "request": {"load_kw": [200]}},
                    ],
                    fail_fast=False,
                    process_item_fn=mock_fn,
                )

        # Should stop after first item due to cancellation
        assert len(result["results"]) == 1
        assert result["summary"]["ok_count"] == 1

    def test_process_job_has_processing_time(self):
        """process_job includes processing_time_ms in summary."""
        mock_fn = MagicMock(return_value={"variants": []})

        with patch('job_processor.is_cancelled', return_value=False):
            with patch('job_processor.update_progress'):
                result = process_job(
                    job_id="test-job-5",
                    items=[{"item_id": "A", "request": {"load_kw": [100]}}],
                    fail_fast=False,
                    process_item_fn=mock_fn,
                )

        assert "processing_time_ms" in result["summary"]
        assert result["summary"]["processing_time_ms"] >= 0


class TestJobProcessor:
    """Tests for JobProcessor class."""

    def test_job_processor_init(self):
        """JobProcessor initializes with correct defaults."""
        mock_fn = MagicMock()
        processor = JobProcessor(process_item_fn=mock_fn)

        assert processor.job_type == "sizing_batch"
        assert processor.poll_interval_seconds == 5.0
        assert processor._running == False

    def test_job_processor_run_once_no_jobs(self):
        """JobProcessor.run_once returns None when no pending jobs."""
        mock_fn = MagicMock()
        processor = JobProcessor(process_item_fn=mock_fn)

        with patch('job_processor.claim_next_pending_job', return_value=None):
            result = processor.run_once()

        assert result is None

    def test_job_processor_stop(self):
        """JobProcessor.stop sets _running to False."""
        mock_fn = MagicMock()
        processor = JobProcessor(process_item_fn=mock_fn)
        processor._running = True

        processor.stop()

        assert processor._running == False


class TestProcessJobUpdateProgress:
    """Tests for progress update behavior."""

    def test_progress_updated_after_each_item(self):
        """update_progress called after each item."""
        mock_fn = MagicMock(return_value={"variants": []})
        update_calls = []

        def track_update(job_id, items_done, error_count):
            update_calls.append((job_id, items_done, error_count))

        with patch('job_processor.is_cancelled', return_value=False):
            with patch('job_processor.update_progress', side_effect=track_update):
                process_job(
                    job_id="test-job-progress",
                    items=[
                        {"item_id": "A", "request": {}},
                        {"item_id": "B", "request": {}},
                        {"item_id": "C", "request": {}},
                    ],
                    fail_fast=False,
                    process_item_fn=mock_fn,
                )

        assert len(update_calls) == 3
        assert update_calls[0] == ("test-job-progress", 1, 0)
        assert update_calls[1] == ("test-job-progress", 2, 0)
        assert update_calls[2] == ("test-job-progress", 3, 0)
