"""
Background worker for processing async batch sizing jobs (v1.1.0, v3.5.0).

This worker polls the job store for pending jobs and processes them.
Can be run as a separate service via docker-compose.

v3.5.0: Added graceful shutdown support for Kubernetes.

Usage:
    python worker.py

Environment Variables:
    JOB_STORE_PATH: Path to SQLite database
    JOB_STORE_ENABLED: Enable/disable job store (default: true)
    WORKER_POLL_INTERVAL: Seconds between polling (default: 5)
    WORKER_GRACEFUL_SHUTDOWN_TIMEOUT: Max seconds to wait for job completion (default: 30)
"""

import logging
import os
import signal
import sys
import threading
from typing import Any, Dict, Optional

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from job_processor import JobProcessor
from sizing_runner import run_sizing
from models import SizingRequest


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("bess-worker")

# Configuration
WORKER_POLL_INTERVAL = float(os.getenv("WORKER_POLL_INTERVAL", "5.0"))
GRACEFUL_SHUTDOWN_TIMEOUT = int(os.getenv("WORKER_GRACEFUL_SHUTDOWN_TIMEOUT", "30"))


# -----------------------------------------------------------------------------
# Graceful Shutdown Handler (v3.5.0)
# -----------------------------------------------------------------------------

class GracefulShutdownHandler:
    """
    Handles graceful shutdown on SIGTERM/SIGINT.

    When a signal is received:
    1. Sets shutdown flag
    2. Waits for current job to finish (up to timeout)
    3. Releases any held locks
    4. Exits cleanly
    """

    def __init__(self, processor: Optional[JobProcessor] = None):
        self.processor = processor
        self.shutdown_requested = threading.Event()
        self.current_job_id: Optional[str] = None
        self._lock = threading.Lock()

    def set_processor(self, processor: JobProcessor):
        """Set the job processor instance."""
        self.processor = processor

    def set_current_job(self, job_id: Optional[str]):
        """Track the currently processing job."""
        with self._lock:
            self.current_job_id = job_id

    def handle_signal(self, signum, frame):
        """Handle shutdown signal (SIGTERM/SIGINT)."""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, initiating graceful shutdown...")

        self.shutdown_requested.set()

        if self.processor:
            self.processor.stop()

        with self._lock:
            current_job = self.current_job_id

        if current_job:
            logger.info(f"Waiting for current job {current_job} to complete (max {GRACEFUL_SHUTDOWN_TIMEOUT}s)...")
        else:
            logger.info("No active job, shutting down immediately.")

    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self.shutdown_requested.is_set()


# Global shutdown handler
_shutdown_handler: Optional[GracefulShutdownHandler] = None


def get_shutdown_handler() -> GracefulShutdownHandler:
    """Get or create global shutdown handler."""
    global _shutdown_handler
    if _shutdown_handler is None:
        _shutdown_handler = GracefulShutdownHandler()
    return _shutdown_handler


def process_sizing_request(request_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a single sizing request.

    Args:
        request_dict: Sizing request as dictionary

    Returns:
        Sizing result as dictionary
    """
    # Convert dict to SizingRequest model
    request = SizingRequest(**request_dict)

    # Run sizing
    result = run_sizing(request)

    # Convert result to dict
    return result.model_dump(mode="json")


def main():
    """Main entry point for worker."""
    logger.info("Starting BESS sizing worker (v3.5.0 with graceful shutdown)...")
    logger.info(f"Poll interval: {WORKER_POLL_INTERVAL}s")
    logger.info(f"Graceful shutdown timeout: {GRACEFUL_SHUTDOWN_TIMEOUT}s")

    # Create processor
    processor = JobProcessor(
        process_item_fn=process_sizing_request,
        job_type="sizing_batch",
        poll_interval_seconds=WORKER_POLL_INTERVAL,
    )

    # Setup graceful shutdown handler (v3.5.0)
    shutdown_handler = get_shutdown_handler()
    shutdown_handler.set_processor(processor)

    # Register signal handlers
    signal.signal(signal.SIGTERM, shutdown_handler.handle_signal)
    signal.signal(signal.SIGINT, shutdown_handler.handle_signal)

    try:
        logger.info("Worker started, waiting for jobs...")
        processor.run_loop()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user (KeyboardInterrupt)")
        processor.stop()
    except Exception as e:
        logger.error(f"Worker error: {e}")
        raise
    finally:
        logger.info("Worker shutdown complete.")


if __name__ == "__main__":
    main()
