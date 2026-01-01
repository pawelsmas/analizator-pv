"""
Unit tests for frontend async jobs (v3.4.0 PR4).

Tests that the bess.js has the required async job functions exported.
"""

import pytest
import os
import re


class TestBessJsAsyncJobFunctions:
    """Tests for async job functions in bess.js."""

    @pytest.fixture
    def bess_js_content(self):
        """Read bess.js content."""
        path = os.path.join(
            os.path.dirname(__file__),
            '..', '..', 'services', 'frontend-bess', 'bess.js'
        )
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_async_report_state_defined(self, bess_js_content):
        """asyncReportState should be defined."""
        assert 'const asyncReportState = {' in bess_js_content

    def test_submit_async_report_job_defined(self, bess_js_content):
        """submitAsyncReportJob function should be defined."""
        assert 'async function submitAsyncReportJob' in bess_js_content

    def test_start_job_polling_defined(self, bess_js_content):
        """startJobPolling function should be defined."""
        assert 'function startJobPolling' in bess_js_content

    def test_stop_job_polling_defined(self, bess_js_content):
        """stopJobPolling function should be defined."""
        assert 'function stopJobPolling' in bess_js_content

    def test_cancel_async_job_defined(self, bess_js_content):
        """cancelAsyncJob function should be defined."""
        assert 'async function cancelAsyncJob' in bess_js_content

    def test_show_async_report_progress_defined(self, bess_js_content):
        """showAsyncReportProgress function should be defined."""
        assert 'function showAsyncReportProgress' in bess_js_content

    def test_hide_async_report_progress_defined(self, bess_js_content):
        """hideAsyncReportProgress function should be defined."""
        assert 'function hideAsyncReportProgress' in bess_js_content

    def test_get_status_message_defined(self, bess_js_content):
        """getStatusMessage function should be defined."""
        assert 'function getStatusMessage' in bess_js_content

    def test_show_job_artifacts_defined(self, bess_js_content):
        """showJobArtifacts function should be defined."""
        assert 'async function showJobArtifacts' in bess_js_content

    def test_format_bytes_defined(self, bess_js_content):
        """formatBytes function should be defined."""
        assert 'function formatBytes' in bess_js_content

    def test_generate_report_async_defined(self, bess_js_content):
        """generateReportAsync function should be defined."""
        assert 'async function generateReportAsync' in bess_js_content


class TestBessJsWindowExports:
    """Tests for window.* exports of async job functions."""

    @pytest.fixture
    def bess_js_content(self):
        """Read bess.js content."""
        path = os.path.join(
            os.path.dirname(__file__),
            '..', '..', 'services', 'frontend-bess', 'bess.js'
        )
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_submit_async_report_job_exported(self, bess_js_content):
        """submitAsyncReportJob should be exported to window."""
        assert 'window.submitAsyncReportJob = submitAsyncReportJob' in bess_js_content

    def test_cancel_async_job_exported(self, bess_js_content):
        """cancelAsyncJob should be exported to window."""
        assert 'window.cancelAsyncJob = cancelAsyncJob' in bess_js_content

    def test_generate_report_async_exported(self, bess_js_content):
        """generateReportAsync should be exported to window."""
        assert 'window.generateReportAsync = generateReportAsync' in bess_js_content

    def test_show_async_report_progress_exported(self, bess_js_content):
        """showAsyncReportProgress should be exported to window."""
        assert 'window.showAsyncReportProgress = showAsyncReportProgress' in bess_js_content

    def test_hide_async_report_progress_exported(self, bess_js_content):
        """hideAsyncReportProgress should be exported to window."""
        assert 'window.hideAsyncReportProgress = hideAsyncReportProgress' in bess_js_content


class TestBessJsApiEndpoints:
    """Tests for correct API endpoint usage."""

    @pytest.fixture
    def bess_js_content(self):
        """Read bess.js content."""
        path = os.path.join(
            os.path.dirname(__file__),
            '..', '..', 'services', 'frontend-bess', 'bess.js'
        )
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_jobs_api_endpoint_used(self, bess_js_content):
        """Should use /api/bess-dispatch/jobs endpoint."""
        assert '/api/bess-dispatch/jobs' in bess_js_content

    def test_jobs_cancel_endpoint_used(self, bess_js_content):
        """Should use /cancel endpoint for cancellation."""
        assert '/cancel' in bess_js_content

    def test_artifacts_endpoint_used(self, bess_js_content):
        """Should use /artifacts endpoint."""
        assert '/artifacts' in bess_js_content


class TestBessJsStatusMessages:
    """Tests for status message handling."""

    @pytest.fixture
    def bess_js_content(self):
        """Read bess.js content."""
        path = os.path.join(
            os.path.dirname(__file__),
            '..', '..', 'services', 'frontend-bess', 'bess.js'
        )
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_queued_status_message(self, bess_js_content):
        """Should have queued status message."""
        assert "queued: 'Waiting in queue..." in bess_js_content

    def test_running_status_message(self, bess_js_content):
        """Should have running status message."""
        assert "running: 'Generating report..." in bess_js_content

    def test_succeeded_status_message(self, bess_js_content):
        """Should have succeeded status message."""
        assert "succeeded: 'Report ready!" in bess_js_content

    def test_failed_status_message(self, bess_js_content):
        """Should have failed status message."""
        assert "failed: 'Generation failed'" in bess_js_content

    def test_cancelled_status_message(self, bess_js_content):
        """Should have cancelled status message."""
        assert "cancelled: 'Cancelled'" in bess_js_content


class TestStylesCssAsyncJobStyles:
    """Tests for async job styles in styles.css."""

    @pytest.fixture
    def styles_content(self):
        """Read styles.css content."""
        path = os.path.join(
            os.path.dirname(__file__),
            '..', '..', 'services', 'frontend-bess', 'styles.css'
        )
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_async_job_progress_class(self, styles_content):
        """Should have .async-job-progress class."""
        assert '.async-job-progress {' in styles_content

    def test_async_job_header_class(self, styles_content):
        """Should have .async-job-header class."""
        assert '.async-job-header {' in styles_content

    def test_async_job_status_class(self, styles_content):
        """Should have .async-job-status class."""
        assert '.async-job-status {' in styles_content

    def test_status_queued_style(self, styles_content):
        """Should have .status-queued style."""
        assert '.async-job-status.status-queued {' in styles_content

    def test_status_running_style(self, styles_content):
        """Should have .status-running style."""
        assert '.async-job-status.status-running {' in styles_content

    def test_status_succeeded_style(self, styles_content):
        """Should have .status-succeeded style."""
        assert '.async-job-status.status-succeeded {' in styles_content

    def test_status_failed_style(self, styles_content):
        """Should have .status-failed style."""
        assert '.async-job-status.status-failed {' in styles_content

    def test_progress_bar_class(self, styles_content):
        """Should have .async-job-progress-bar class."""
        assert '.async-job-progress-bar {' in styles_content

    def test_btn_cancel_style(self, styles_content):
        """Should have .btn-cancel style."""
        assert '.async-job-progress .btn-cancel {' in styles_content

    def test_btn_download_style(self, styles_content):
        """Should have .btn-download style."""
        assert '.async-job-artifacts .btn-download {' in styles_content
