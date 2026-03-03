#!/usr/bin/env python3
"""CLI for triggering disaster recovery resync against the middleware API."""

import argparse
import os
import sys
import time

try:
    import httpx
except ImportError:
    print("httpx is required: pip install httpx")
    sys.exit(1)

DEFAULT_BASE_URL = "http://localhost:8000"


def main():
    parser = argparse.ArgumentParser(
        description="Re-send messages from the middleware backup DB to Odoo.",
        epilog="Example: python resync.py --from-date 2026-02-20T00:00:00Z",
    )
    parser.add_argument(
        "--from-date",
        required=True,
        help="ISO-8601 datetime. Messages from this date onward will be re-sent.",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Optional: limit resync to a single WhatsApp session (instance name).",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MIDDLEWARE_URL", DEFAULT_BASE_URL),
        help=f"Middleware base URL (default: {DEFAULT_BASE_URL} or $MIDDLEWARE_URL).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("MIDDLEWARE_API_KEY"),
        help="Middleware API key (default: $MIDDLEWARE_API_KEY).",
    )
    parser.add_argument(
        "--poll",
        action="store_true",
        help="Poll for job completion after triggering.",
    )
    args = parser.parse_args()

    if not args.api_key:
        print("Error: API key required. Pass --api-key or set $MIDDLEWARE_API_KEY.")
        sys.exit(1)

    headers = {"X-API-Key": args.api_key, "Content-Type": "application/json"}
    payload = {"from_date": args.from_date}
    if args.session:
        payload["session"] = args.session

    url = f"{args.base_url.rstrip('/')}/api/resync"

    print(f"Triggering resync from {args.from_date} ...")
    if args.session:
        print(f"  Session filter: {args.session}")

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=payload, headers=headers)

        if resp.status_code == 202:
            data = resp.json()
            job_id = data["job_id"]
            print(f"  Job accepted: {job_id}")
        else:
            print(f"  Error: HTTP {resp.status_code}")
            print(f"  {resp.text}")
            sys.exit(1)

        if not args.poll:
            print(f"\nCheck status: GET {args.base_url}/api/resync/{job_id}")
            return

        print("\nPolling for completion...")
        status_url = f"{args.base_url.rstrip('/')}/api/resync/{job_id}"
        while True:
            time.sleep(2)
            status_resp = client.get(status_url, headers=headers)
            if status_resp.status_code != 200:
                print(f"  Poll error: HTTP {status_resp.status_code}")
                sys.exit(1)

            status_data = status_resp.json()
            current = status_data.get("status", "unknown")
            processed = status_data.get("processed", 0)
            total = status_data.get("total", 0)
            errors = status_data.get("errors", 0)

            print(f"  {current}: {processed}/{total} processed, {errors} errors", end="\r")

            if current in ("completed", "failed"):
                print()
                break

        if current == "completed":
            print(f"\nResync complete: {processed} messages re-sent, {errors} errors.")
        else:
            print(f"\nResync failed. Check middleware logs for details.")
            sys.exit(1)


if __name__ == "__main__":
    main()
