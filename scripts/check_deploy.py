"""Check a deployed API against the M2 "done when" and the rate-limit IP question.

    python scripts/check_deploy.py https://sponsor-check.onrender.com

1. /healthz answers.
2. Latency of a cached /v1/lookup, measured from this machine (so it includes your network).
3. Whether the rate limit can be dodged by sending a fake X-Forwarded-For. It sends 61 requests,
   each claiming a different client IP. If none is refused, the limiter is trusting a header the
   client controls. This uses up your own rate-limit budget for a minute.

Makes about 85 requests to the URL you give it. Prints measurements only; nothing is stored.
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

        refused = 0
        for i in range(LIMIT + 1):
            fake_ip = f"198.51.100.{i % 250 + 1}"  # TEST-NET-2, never a real client
            resp = client.get(f"{base}/v1/salary-check", params={"amount": 1},
                              headers={"X-Forwarded-For": fake_ip})
            refused += resp.status_code == 429
        if refused:
            print(f"rate limit: {refused} of {LIMIT + 1} refused despite fake X-Forwarded-For "
                  "values, so the limiter is not trusting the client's header.")
        else:
            print(f"rate limit: SPOOFABLE. {LIMIT + 1} requests with fake X-Forwarded-For values "
                  "were all accepted.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
