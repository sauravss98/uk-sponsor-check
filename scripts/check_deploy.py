"""Check a deployed API against the M2 "done when" and the rate-limit IP question.

    python scripts/check_deploy.py https://sponsor-check.onrender.com

1. /healthz answers.
2. Latency of a cached /v1/lookup, measured from this machine (so it includes your network).
3. Whether the rate limit can be dodged with a fake client-IP header, for each header a client
   might forge. Each test sends 61 requests, each claiming a different IP. If none is refused,
   the limiter trusts a header the client controls. A spoofable header gets fresh buckets even
   after the real one is used up, so the tests stay valid when run back to back.

Makes about 145 requests to the URL you give it. Prints measurements only; nothing is stored.
"""

from __future__ import annotations

import statistics
import sys
import time

import httpx

LOOKUP = "/v1/lookup"
NAME = "Starling Bank"
SAMPLES = 20
LIMIT = 60


def main(base: str) -> int:
    base = base.rstrip("/")
    with httpx.Client(timeout=90.0) as client:
        health = client.get(f"{base}/healthz")
        print(f"healthz: {health.status_code} {health.text.strip()}")

        client.get(f"{base}{LOOKUP}", params={"name": NAME})  # wake the host and fill the cache
        timings = []
        for _ in range(SAMPLES):
            start = time.perf_counter()
            resp = client.get(f"{base}{LOOKUP}", params={"name": NAME})
            timings.append((time.perf_counter() - start) * 1000)
            resp.raise_for_status()
        timings.sort()
        p95 = timings[int(len(timings) * 0.95) - 1]
        print(f"cached lookup over {SAMPLES} requests: median {statistics.median(timings):.0f} ms, "
              f"p95 {p95:.0f} ms, max {timings[-1]:.0f} ms")

        spoofable = False
        for header in ("X-Forwarded-For", "CF-Connecting-IP"):
            refused = 0
            for i in range(LIMIT + 1):
                fake_ip = f"198.51.100.{i % 250 + 1}"  # TEST-NET-2, never a real client
                resp = client.get(f"{base}/v1/salary-check", params={"amount": 1},
                                  headers={header: fake_ip})
                refused += resp.status_code == 429
            if refused:
                print(f"rate limit vs fake {header}: {refused} of {LIMIT + 1} refused, so it is "
                      "not trusted.")
            else:
                spoofable = True
                print(f"rate limit vs fake {header}: SPOOFABLE, all {LIMIT + 1} accepted.")
    return 1 if spoofable else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
