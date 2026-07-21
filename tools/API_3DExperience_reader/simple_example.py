#!/usr/bin/env python3
"""Minimal starter for reading information from a 3DEXPERIENCE REST endpoint.

This is intentionally simple and generic. In a real deployment you will usually
need to replace the authentication flow with the one required by your tenant
(SSO, session cookie, OAuth token, etc.).
"""

import argparse
import base64
import os
import sys
import urllib.error
import urllib.request


def build_auth_header(username: str, password: str) -> dict[str, str]:
    if not username or not password:
        return {}
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def read_resource(base_url: str, resource_url: str, username: str, password: str, timeout: int) -> int:
    if not base_url:
        print("A base URL is required. Set THREEDX_BASE_URL or use --base-url.")
        return 2

    if not resource_url:
        print("A resource URL is required. Set THREEDX_RESOURCE_URL or use --resource-url.")
        return 2

    full_url = base_url.rstrip("/") + "/" + resource_url.lstrip("/")
    headers = build_auth_header(username, password)

    print(f"Requesting: {full_url}")
    request = urllib.request.Request(full_url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(f"Status: {response.status}")
            print("Response body:")
            print(body[:4000])
            if len(body) > 4000:
                print("\n[truncated]")
            return 0
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP error {exc.code}")
        print(body[:4000])
        return 1
    except Exception as exc:  # pragma: no cover - network errors vary by environment
        print(f"Request failed: {exc}")
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read information from a 3DEXPERIENCE REST endpoint")
    parser.add_argument("--base-url", default=os.getenv("THREEDX_BASE_URL", ""), help="Base URL for your tenant, for example https://tenant.3dexperience.3ds.com")
    parser.add_argument("--resource-url", default=os.getenv("THREEDX_RESOURCE_URL", "/resources/v1/people/me"), help="Resource path to request")
    parser.add_argument("--username", default=os.getenv("THREEDX_USERNAME", ""), help="Username for the platform")
    parser.add_argument("--password", default=os.getenv("THREEDX_PASSWORD", ""), help="Password or token for the platform")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("THREEDX_TIMEOUT", "20")), help="HTTP timeout in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Print the request details without sending the request")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.dry_run:
        print("Dry run only")
        print(f"Base URL : {args.base_url}")
        print(f"Resource : {args.resource_url}")
        print(f"Username : {args.username or '<not set>'}")
        return 0

    return read_resource(args.base_url, args.resource_url, args.username, args.password, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
