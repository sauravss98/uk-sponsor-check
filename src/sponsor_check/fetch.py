"""Download the latest register CSV from GOV.UK.

The CSV's URL changes with every publication (it embeds a media hash and the date),
so we discover it each time: first via the GOV.UK Content API (structured JSON),
falling back to scanning the publication page's HTML.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

PUBLICATION_PATH = "/government/publications/register-of-licensed-sponsors-workers"
CONTENT_API = f"https://www.gov.uk/api/content{PUBLICATION_PATH}"
PUBLICATION_PAGE = f"https://www.gov.uk{PUBLICATION_PATH}"

_CSV_LINK = re.compile(r"https://assets\.publishing\.service\.gov\.uk/[^\s\"'<>)]+?\.csv")
_HEADERS = {"User-Agent": "sponsor-check (+https://github.com/sauravss98/sponsor-check)"}


class RegisterNotFound(RuntimeError):
    pass


def _csv_urls_in(obj) -> list[str]:
    """Recursively collect CSV asset URLs from a Content API payload."""
    found: list[str] = []
    if isinstance(obj, dict):
        for value in obj.values():
            found.extend(_csv_urls_in(value))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_csv_urls_in(value))
    elif isinstance(obj, str):
        found.extend(_CSV_LINK.findall(obj))
    return found


def find_csv_url(client: httpx.Client) -> str:
    try:
        resp = client.get(CONTENT_API)
        resp.raise_for_status()
        urls = _csv_urls_in(resp.json())
        if urls:
            return urls[0]
    except (httpx.HTTPError, ValueError):
        pass  # fall through to HTML scraping

    resp = client.get(PUBLICATION_PAGE)
    resp.raise_for_status()
    urls = _CSV_LINK.findall(resp.text)
    if not urls:
        raise RegisterNotFound("Could not find the register CSV link on GOV.UK.")
    return urls[0]


def download_register(dest: Path, timeout: float = 60.0) -> str:
    """Download the current register to `dest`. Returns the source URL."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=_HEADERS, timeout=timeout, follow_redirects=True) as client:
        url = find_csv_url(client)
        tmp = dest.with_suffix(".part")
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
        tmp.replace(dest)  # atomic swap so a failed download never corrupts the old file
    return url
