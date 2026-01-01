"""
Job Processor for async batch sizing jobs (v1.1.0, v2.3.0 portfolio).

Provides:
- process_job(): Main function to process a job (used by wait=true and worker)
- JobProcessor class for managing job processing lifecycle
- Worker mode for background job processing
- Portfolio aggregation for sizing-batch results (v2.3.0)

This module is shared between inline processing (wait=true) and background worker.
"""

import time
from typing import Any, Callable, Dict, List, Optional

from job_store import (
    get_job,
    mark_running,
    update_progress,
    save_result,
    is_cancelled,
    claim_next_pending_job,
)

# v2.3.0: Portfolio aggregation for sizing-batch results
from portfolio_agg import summarize_items, extract_item_summary_from_result
from models import PortfolioItemSummary


def process_job(
    job_id: str,
    items: List[Dict[str, Any]],
    fail_fast: bool,
    process_item_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Process a batch sizing job.

    Args:
        job_id: Job identifier
        items: List of items to process (each has item_id and request)
        fail_fast: Stop on first error
        process_item_fn: Function to process a single item request

    Returns:
        Result dict with results array and summary
    """
    results = []
    ok_count = 0
    error_count = 0
    start_time = time.time()

    for item in items:
        # Check if job was cancelled
        if is_cancelled(job_id):
            break

        item_id = item.get("item_id", "unknown")
        request = item.get("request", {})

        try:
            response = process_item_fn(request)
            results.append({
                "item_id": item_id,
                "status": "ok",
                "response": response,
                "error": None,
            })
            ok_count += 1

        except Exception as e:
            error_msg = str(e)
            results.append({
                "item_id": item_id,
                "status": "error",
                "response": None,
                "error": error_msg,
            })
            error_count += 1

            if fail_fast:
                break

        # Update progress
        update_progress(job_id, items_done=ok_count + error_count, error_count=error_count)

    processing_time_ms = (time.time() - start_time) * 1000

    # v2.3.0: Aggregate portfolio summary from OK results
    portfolio_items = []
    for result_item in results:
        if result_item["status"] == "ok" and result_item.get("response"):
            item_summary = extract_item_summary_from_result(
                run_id=result_item["item_id"],
                result=result_item["response"],
                label=None,
                tags=None,
            )
            portfolio_items.append(item_summary)

    portfolio_summary = summarize_items(portfolio_items)

    return {
        "results": results,
        "summary": {
            "total_items": len(items),
            "ok_count": ok_count,
            "error_count": error_count,
            "processing_time_ms": processing_time_ms,
        },
        # v2.3.0: Portfolio aggregation
        "portfolio_summary": portfolio_summary.model_dump(),
        "portfolio_items": [item.model_dump() for item in portfolio_items],
    }


class JobProcessor:
    """
    Job processor for background worker mode.

    Usage:
        processor = JobProcessor(process_item_fn=my_sizing_fn)
        processor.run_once()  # Process one job
        processor.run_loop()  # Run continuously
    """

    def __init__(
        self,
        process_item_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
        job_type: str = "sizing_batch",
        poll_interval_seconds: float = 5.0,
    ):
        """
        Initialize job processor.

        Args:
            process_item_fn: Function to process a single item request
            job_type: Job type to claim (default: sizing_batch)
            poll_interval_seconds: Interval between polling for new jobs
        """
        self.process_item_fn = process_item_fn
        self.job_type = job_type
        self.poll_interval_seconds = poll_interval_seconds
        self._running = False

    def run_once(self) -> Optional[str]:
        """
        Claim and process one pending job.

        Returns:
            job_id if processed, None if no pending jobs
        """
        job_id = claim_next_pending_job(self.job_type)
        if not job_id:
            return None

        job = get_job(job_id)
        if not job:
            return None

        # Get items from request
        request = job.get("request", {})
        items = request.get("items", [])
        fail_fast = request.get("fail_fast", False)

        # Process job
        try:
            result = process_job(
                job_id=job_id,
                items=items,
                fail_fast=fail_fast,
                process_item_fn=self.process_item_fn,
            )

            # Check if cancelled during processing
            if is_cancelled(job_id):
                save_result(job_id, result, status="cancelled", message="Job cancelled during processing")
            else:
                # Determine final status
                final_status = "done"
                message = None
                if result["summary"]["error_count"] > 0:
                    message = f"{result['summary']['error_count']} item(s) failed"

                save_result(job_id, result, status=final_status, message=message)

        except Exception as e:
            save_result(
                job_id,
                result={"results": [], "summary": {"total_items": len(items), "ok_count": 0, "error_count": 0, "processing_time_ms": 0}},
                status="failed",
                message=str(e),
            )

        return job_id

    def run_loop(self, max_iterations: Optional[int] = None):
        """
        Run processing loop.

        Args:
            max_iterations: Stop after N iterations (None = run forever)
        """
        self._running = True
        iteration = 0

        while self._running:
            if max_iterations is not None and iteration >= max_iterations:
                break

            job_id = self.run_once()

            if job_id:
                # Job processed, immediately check for more
                iteration += 1
            else:
                # No pending jobs, wait before polling again
                time.sleep(self.poll_interval_seconds)
                iteration += 1

    def stop(self):
        """Stop the processing loop."""
        self._running = False


# -----------------------------------------------------------------------------
# Worker entry point
# -----------------------------------------------------------------------------

def run_worker(process_item_fn: Callable[[Dict[str, Any]], Dict[str, Any]]):
    """
    Run background worker.

    This is the entry point for the worker service.

    Args:
        process_item_fn: Function to process a single sizing request
    """
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("job_worker")

    logger.info("Starting job worker...")

    processor = JobProcessor(
        process_item_fn=process_item_fn,
        job_type="sizing_batch",
        poll_interval_seconds=5.0,
    )

    try:
        processor.run_loop()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker error: {e}")
        raise


if __name__ == "__main__":
    # Example usage - this would be replaced with actual sizing function
    def mock_process_item(request: Dict[str, Any]) -> Dict[str, Any]:
        """Mock sizing function for testing."""
        return {"variants": [], "recommended_variant": "small"}

    run_worker(mock_process_item)
