#!/usr/bin/env python3
"""
Smoke Tests for PV Optimizer
Checks all backend services health endpoints and frontend availability.

Usage:
    python scripts/smoke_test.py
    python scripts/smoke_test.py --verbose
    python scripts/smoke_test.py --timeout 10
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import httpx
except ImportError:
    print("httpx not installed. Install with: pip install httpx")
    sys.exit(1)


# Service definitions
BACKEND_SERVICES = {
    "data-analysis": {"url": "http://localhost:8001/health", "port": 8001},
    "pv-calculation": {"url": "http://localhost:8002/health", "port": 8002},
    "economics": {"url": "http://localhost:8003/health", "port": 8003},
    "advanced-analytics": {"url": "http://localhost:8004/health", "port": 8004},
    "typical-days": {"url": "http://localhost:8005/health", "port": 8005},
    "energy-prices": {"url": "http://localhost:8010/health", "port": 8010},
    "reports": {"url": "http://localhost:8011/health", "port": 8011},
    "projects-db": {"url": "http://localhost:8012/health", "port": 8012},
    "pvgis-proxy": {"url": "http://localhost:8020/health", "port": 8020},
    "geo-service": {"url": "http://localhost:8021/health", "port": 8021},
}

FRONTEND_SERVICES = {
    "shell": {"url": "http://localhost:80/", "port": 80},
    "admin": {"url": "http://localhost:9001/", "port": 9001},
    "config": {"url": "http://localhost:9002/", "port": 9002},
    "consumption": {"url": "http://localhost:9003/", "port": 9003},
    "production": {"url": "http://localhost:9004/", "port": 9004},
    "comparison": {"url": "http://localhost:9005/", "port": 9005},
    "economics": {"url": "http://localhost:9006/", "port": 9006},
    "settings": {"url": "http://localhost:9007/", "port": 9007},
    "esg": {"url": "http://localhost:9008/", "port": 9008},
    "energy-prices": {"url": "http://localhost:9009/", "port": 9009},
    "reports": {"url": "http://localhost:9010/", "port": 9010},
    "projects": {"url": "http://localhost:9011/", "port": 9011},
    "estimator": {"url": "http://localhost:9012/", "port": 9012},
}


def check_service(name: str, url: str, timeout: float, verbose: bool) -> dict:
    """Check a single service health."""
    start = time.time()
    result = {
        "name": name,
        "url": url,
        "status": "unknown",
        "response_time_ms": 0,
        "error": None,
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url)
            elapsed = (time.time() - start) * 1000

            result["response_time_ms"] = round(elapsed, 1)

            if response.status_code == 200:
                result["status"] = "healthy"
                if verbose:
                    # Try to parse JSON for backend services
                    try:
                        data = response.json()
                        result["details"] = data
                    except Exception:
                        pass
            else:
                result["status"] = "unhealthy"
                result["error"] = f"HTTP {response.status_code}"

    except httpx.ConnectError:
        result["status"] = "offline"
        result["error"] = "Connection refused"
    except httpx.TimeoutException:
        result["status"] = "timeout"
        result["error"] = f"Timeout after {timeout}s"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def run_smoke_tests(timeout: float = 5.0, verbose: bool = False) -> dict:
    """Run all smoke tests in parallel."""
    results = {
        "backend": [],
        "frontend": [],
        "summary": {
            "total": 0,
            "healthy": 0,
            "unhealthy": 0,
            "offline": 0,
        },
    }

    all_services = []

    # Prepare all services
    for name, config in BACKEND_SERVICES.items():
        all_services.append(("backend", name, config["url"]))

    for name, config in FRONTEND_SERVICES.items():
        all_services.append(("frontend", name, config["url"]))

    results["summary"]["total"] = len(all_services)

    # Run checks in parallel
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(check_service, name, url, timeout, verbose): (category, name)
            for category, name, url in all_services
        }

        for future in as_completed(futures):
            category, name = futures[future]
            try:
                result = future.result()
                results[category].append(result)

                if result["status"] == "healthy":
                    results["summary"]["healthy"] += 1
                elif result["status"] == "offline":
                    results["summary"]["offline"] += 1
                else:
                    results["summary"]["unhealthy"] += 1

            except Exception as e:
                results[category].append({
                    "name": name,
                    "status": "error",
                    "error": str(e),
                })
                results["summary"]["unhealthy"] += 1

    return results


def print_results(results: dict, verbose: bool = False):
    """Print results in a readable format."""
    # Status symbols
    STATUS_ICONS = {
        "healthy": "✅",
        "unhealthy": "❌",
        "offline": "⚫",
        "timeout": "⏱️",
        "error": "❌",
        "unknown": "❓",
    }

    print("\n" + "=" * 60)
    print("🔬 PV OPTIMIZER SMOKE TEST RESULTS")
    print("=" * 60)

    # Backend services
    print("\n📦 BACKEND SERVICES:")
    print("-" * 50)
    for svc in sorted(results["backend"], key=lambda x: x["name"]):
        icon = STATUS_ICONS.get(svc["status"], "❓")
        time_str = f"{svc['response_time_ms']}ms" if svc["response_time_ms"] else "-"
        error_str = f" ({svc['error']})" if svc.get("error") else ""
        print(f"  {icon} {svc['name']:<20} {svc['status']:<10} {time_str:>8}{error_str}")

    # Frontend services
    print("\n🌐 FRONTEND SERVICES:")
    print("-" * 50)
    for svc in sorted(results["frontend"], key=lambda x: x["name"]):
        icon = STATUS_ICONS.get(svc["status"], "❓")
        time_str = f"{svc['response_time_ms']}ms" if svc["response_time_ms"] else "-"
        error_str = f" ({svc['error']})" if svc.get("error") else ""
        print(f"  {icon} {svc['name']:<20} {svc['status']:<10} {time_str:>8}{error_str}")

    # Summary
    summary = results["summary"]
    print("\n" + "=" * 60)
    print("📊 SUMMARY:")
    print(f"   Total services:  {summary['total']}")
    print(f"   ✅ Healthy:      {summary['healthy']}")
    print(f"   ❌ Unhealthy:    {summary['unhealthy']}")
    print(f"   ⚫ Offline:      {summary['offline']}")
    print("=" * 60)

    # Overall status
    if summary["healthy"] == summary["total"]:
        print("\n🎉 All services are healthy!")
        return 0
    elif summary["healthy"] > 0:
        print(f"\n⚠️  {summary['healthy']}/{summary['total']} services healthy")
        return 1
    else:
        print("\n💀 No services are responding!")
        return 2


def main():
    parser = argparse.ArgumentParser(description="PV Optimizer Smoke Tests")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("-t", "--timeout", type=float, default=5.0, help="Request timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    print("🔄 Running smoke tests...")
    results = run_smoke_tests(timeout=args.timeout, verbose=args.verbose)

    if args.json:
        import json
        print(json.dumps(results, indent=2))
        return 0 if results["summary"]["healthy"] == results["summary"]["total"] else 1

    return print_results(results, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
