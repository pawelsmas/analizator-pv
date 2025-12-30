"""
Background worker for processing async batch sizing jobs (v1.1.0).

This worker polls the job store for pending jobs and processes them.
Can be run as a separate service via docker-compose.

Usage:
    python worker.py

Environment Variables:
    JOB_STORE_PATH: Path to SQLite database
    JOB_STORE_ENABLED: Enable/disable job store (default: true)
    WORKER_POLL_INTERVAL: Seconds between polling (default: 5)
"""

import logging
import os
import sys
from typing import Any, Dict

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
    logger.info("Starting BESS sizing worker...")
    logger.info(f"Poll interval: {WORKER_POLL_INTERVAL}s")

    processor = JobProcessor(
        process_item_fn=process_sizing_request,
        job_type="sizing_batch",
        poll_interval_seconds=WORKER_POLL_INTERVAL,
    )

    try:
        logger.info("Worker started, waiting for jobs...")
        processor.run_loop()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
        processor.stop()
    except Exception as e:
        logger.error(f"Worker error: {e}")
        raise


if __name__ == "__main__":
    main()
