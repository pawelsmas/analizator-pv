#!/usr/bin/env python3
"""
API Benchmark Harness (v2.5.0 PR5).

Runs performance benchmarks against the BESS dispatch API endpoints.

Usage:
    python scripts/bench_api.py [--base-url URL] [--iterations N] [--output FILE]

Features:
- Measures response time (p50, p95, p99, max)
- Measures throughput (requests/sec)
- Measures response size
- Outputs results in JSON format
- CI-friendly exit codes

Endpoints tested:
- POST /sizing (standard sizing)
- POST /sizing:batch (batch sizing)
- GET /api/bess-dispatch/limits
- GET /health
"""

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import requests


# Default configuration
DEFAULT_BASE_URL = "http://localhost:8031"
DEFAULT_ITERATIONS = 10


@dataclass
class BenchmarkResult:
    """Result of a single benchmark."""
    endpoint: str
    method: str
    iterations: int
    success_count: int
    failure_count: int
    latencies_ms: List[float]
    response_sizes_bytes: List[int]

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def p50_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return statistics.median(self.latencies_ms)

    @property
    def p95_ms(self) -> float:
        if len(self.latencies_ms) < 2:
            return self.p50_ms
        return statistics.quantiles(self.latencies_ms, n=20)[18]

    @property
    def p99_ms(self) -> float:
        if len(self.latencies_ms) < 10:
            return self.p95_ms
        return statistics.quantiles(self.latencies_ms, n=100)[98]

    @property
    def max_ms(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def min_ms(self) -> float:
        return min(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def avg_response_size_bytes(self) -> float:
        return statistics.mean(self.response_sizes_bytes) if self.response_sizes_bytes else 0.0

    @property
    def requests_per_second(self) -> float:
        if not self.latencies_ms:
            return 0.0
        total_seconds = sum(self.latencies_ms) / 1000.0
        return len(self.latencies_ms) / total_seconds if total_seconds > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "method": self.method,
            "iterations": self.iterations,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 4),
            "latency_ms": {
                "p50": round(self.p50_ms, 2),
                "p95": round(self.p95_ms, 2),
                "p99": round(self.p99_ms, 2),
                "max": round(self.max_ms, 2),
                "min": round(self.min_ms, 2),
                "avg": round(self.avg_ms, 2),
            },
            "response_size_bytes": {
                "avg": round(self.avg_response_size_bytes, 0),
            },
            "throughput": {
                "requests_per_second": round(self.requests_per_second, 2),
            },
        }


def sizing_request_24h() -> Dict[str, Any]:
    """Standard 24h sizing request."""
    return {
        "load_kw": [100] * 24,
        "pv_generation_kw": [0, 0, 0, 0, 0, 0, 50, 200, 500, 800, 1000, 1100,
                            1100, 1000, 800, 500, 200, 50, 0, 0, 0, 0, 0, 0],
        "mode": "pv_surplus",
        "durations_h": [1.0, 2.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


def sizing_request_week() -> Dict[str, Any]:
    """Week (168h) sizing request."""
    return {
        "load_kw": [100] * 168,
        "pv_generation_kw": [50] * 168,
        "mode": "pv_surplus",
        "durations_h": [1.0, 2.0, 4.0],
        "interval_minutes": 60,
        "discount_rate": 0.08,
        "analysis_years": 15,
        "capex_pln_per_kwh": 1800.0,
        "import_price_pln_mwh": 800.0,
    }


def run_benchmark(
    base_url: str,
    endpoint: str,
    method: str,
    iterations: int,
    json_body: Optional[Dict] = None,
    headers: Optional[Dict] = None,
) -> BenchmarkResult:
    """
    Run benchmark for a single endpoint.

    Args:
        base_url: API base URL
        endpoint: Endpoint path
        method: HTTP method (GET, POST)
        iterations: Number of iterations
        json_body: Request body for POST
        headers: Optional request headers

    Returns:
        BenchmarkResult with timing data
    """
    url = f"{base_url}{endpoint}"
    latencies = []
    response_sizes = []
    success_count = 0
    failure_count = 0

    for i in range(iterations):
        try:
            start = time.perf_counter()

            if method.upper() == "POST":
                resp = requests.post(url, json=json_body, headers=headers, timeout=60)
            else:
                resp = requests.get(url, headers=headers, timeout=60)

            elapsed_ms = (time.perf_counter() - start) * 1000

            if resp.status_code < 400:
                success_count += 1
                latencies.append(elapsed_ms)
                response_sizes.append(len(resp.content))
            else:
                failure_count += 1

        except Exception as e:
            failure_count += 1
            print(f"  Error on iteration {i+1}: {e}", file=sys.stderr)

    return BenchmarkResult(
        endpoint=endpoint,
        method=method,
        iterations=iterations,
        success_count=success_count,
        failure_count=failure_count,
        latencies_ms=latencies,
        response_sizes_bytes=response_sizes,
    )


def run_all_benchmarks(base_url: str, iterations: int) -> List[BenchmarkResult]:
    """Run all benchmark scenarios."""
    results = []

    # Health check (baseline)
    print("Benchmarking: GET /health")
    results.append(run_benchmark(
        base_url=base_url,
        endpoint="/health",
        method="GET",
        iterations=iterations,
    ))

    # Limits endpoint
    print("Benchmarking: GET /api/bess-dispatch/limits")
    results.append(run_benchmark(
        base_url=base_url,
        endpoint="/api/bess-dispatch/limits",
        method="GET",
        iterations=iterations,
    ))

    # Standard sizing (24h)
    print("Benchmarking: POST /sizing (24h)")
    results.append(run_benchmark(
        base_url=base_url,
        endpoint="/api/bess-dispatch/sizing",
        method="POST",
        iterations=iterations,
        json_body=sizing_request_24h(),
    ))

    # Week sizing (168h)
    print("Benchmarking: POST /sizing (168h)")
    results.append(run_benchmark(
        base_url=base_url,
        endpoint="/api/bess-dispatch/sizing",
        method="POST",
        iterations=iterations,
        json_body=sizing_request_week(),
    ))

    # Batch sizing
    print("Benchmarking: POST /sizing:batch (3 items)")
    results.append(run_benchmark(
        base_url=base_url,
        endpoint="/api/bess-dispatch/sizing:batch",
        method="POST",
        iterations=max(1, iterations // 2),  # Fewer iterations for batch
        json_body={"items": [sizing_request_24h() for _ in range(3)]},
    ))

    return results


def print_summary(results: List[BenchmarkResult]) -> None:
    """Print human-readable summary."""
    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS")
    print("=" * 70)

    for r in results:
        print(f"\n{r.method} {r.endpoint}")
        print(f"  Iterations: {r.iterations} (success: {r.success_count}, failed: {r.failure_count})")
        print(f"  Latency: p50={r.p50_ms:.1f}ms, p95={r.p95_ms:.1f}ms, p99={r.p99_ms:.1f}ms, max={r.max_ms:.1f}ms")
        print(f"  Avg response: {r.avg_response_size_bytes/1024:.1f} KB")
        print(f"  Throughput: {r.requests_per_second:.1f} req/s")


def main():
    parser = argparse.ArgumentParser(description="API Benchmark Harness")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--iterations", "-n",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"Number of iterations per benchmark (default: {DEFAULT_ITERATIONS})",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output",
    )

    args = parser.parse_args()

    if not args.quiet:
        print(f"Running benchmarks against {args.base_url}")
        print(f"Iterations per benchmark: {args.iterations}")
        print()

    results = run_all_benchmarks(args.base_url, args.iterations)

    if not args.quiet:
        print_summary(results)

    # Build output
    output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": args.base_url,
        "iterations": args.iterations,
        "results": [r.to_dict() for r in results],
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults written to: {args.output}")
    else:
        print("\n" + json.dumps(output, indent=2))

    # Exit with error if any failures
    total_failures = sum(r.failure_count for r in results)
    if total_failures > 0:
        print(f"\nWARNING: {total_failures} failed requests", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
