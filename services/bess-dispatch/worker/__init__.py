"""
Worker module for distributed job processing (v3.4.0).

This module provides the worker process that claims and executes jobs
from the job_queue table.
"""

from .worker import claim_next_job, process_one_job, run_loop

__all__ = ["claim_next_job", "process_one_job", "run_loop"]
