#!/usr/bin/env python3
"""Verify public frontend build metadata without credentials or response-body logging."""

import argparse
from http.client import HTTPException
import json
import re
import secrets
import signal
import time
from urllib.error import URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


MAX_BYTES = 1024
MAX_ATTEMPTS = 24
REQUEST_TIMEOUT = 8
RETRY_DELAY = 10


class RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validated_url(value):
    # Validate before urlsplit, which otherwise silently strips some control characters.
    if not value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or "?" in value
        or "#" in value
        or "\\" in value
        or parts.port == 0
    ):
        raise ValueError
    # The operator-controlled repository variable identifies the trusted public origin.
    return urlunsplit(("https", parts.netloc, parts.path.rstrip("/") + "/deployment.json", "", ""))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def request_expired(_signum, _frame):
    raise TimeoutError


def check_once(opener, endpoint, revision):
    request = Request(
        endpoint + "?verification=" + secrets.token_hex(16),
        headers={"Accept": "application/json", "Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
    )
    # Socket timeouts alone permit a slowly streamed body to outlive the retry budget.
    signal.setitimer(signal.ITIMER_REAL, REQUEST_TIMEOUT)
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
            if response.status != 200:
                return "HTTP status was not 200"
            if response.headers.get_content_type() != "application/json":
                return "response was not JSON metadata"
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > MAX_BYTES):
                return "metadata exceeded the size limit"
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            return "metadata exceeded the size limit"
        document = json.loads(body.decode("utf-8"), object_pairs_hook=unique_object)
        if not isinstance(document, dict) or set(document) != {"revision"}:
            return "metadata schema was invalid"
        if document["revision"] != revision:
            return "revision did not match the released commit"
        return None
    except (OSError, URLError, HTTPException, ValueError, UnicodeError):
        return "request failed or metadata was invalid"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", args.expected_revision):
            raise ValueError
        endpoint = validated_url(args.url)
    except ValueError:
        print("Frontend verification failed: invalid revision or HTTPS URL configuration.")
        return 1
    signal.signal(signal.SIGALRM, request_expired)
    opener = build_opener(ProxyHandler({}), RefuseRedirects())
    for attempt in range(1, MAX_ATTEMPTS + 1):
        problem = check_once(opener, endpoint, args.expected_revision)
        if problem is None:
            print("Frontend deployment verified at the released revision.")
            return 0
        print(f"Frontend verification attempt {attempt}/{MAX_ATTEMPTS}: {problem}.", flush=True)
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_DELAY)
    print("Frontend verification failed: rollout retry budget exhausted.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
