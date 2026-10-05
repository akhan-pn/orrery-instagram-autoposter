"""Reading due posts from, and writing results back to, the content calendar."""
from __future__ import annotations

import os
from typing import Any

import requests

API = "https://api.airtable.com/v0"
TABLE = "Content Calendar"


def _cfg() -> tuple[str, str]:
    token = os.environ.get("AIRTABLE_TOKEN", "")
    base = os.environ.get("AIRTABLE_BASE_ID", "")
    if not token or not base:
        raise RuntimeError("AIRTABLE_TOKEN and AIRTABLE_BASE_ID are required")
    return token, base


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def due_posts() -> list[dict[str, Any]]:
    """Scheduled posts whose publish time has passed.

    Only "Scheduled" is collected. "Approved" is deliberately excluded so that
    approving a draft can never publish it on its own.
    """
    token, base = _cfg()
    r = requests.get(
        f"{API}/{base}/{requests.utils.quote(TABLE)}",
        headers=_headers(token),
        params={
            "filterByFormula": 'AND({Status}="Scheduled", {Publish Date}<=NOW())',
            "pageSize": 50,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("records", [])


def attachment_urls(fields: dict[str, Any], field: str, expect_type: str | None = None) -> list[str]:
    """Attachment URLs in order.

    Airtable's attachment URLs are short-lived, so they are read at publish time
    and handed straight to the destination rather than cached anywhere.
    """
    urls = []
    for att in fields.get(field) or []:
        if expect_type and att.get("type") != expect_type:
            raise RuntimeError(
                f"{att.get('filename')} is {att.get('type')}, expected {expect_type}"
            )
        urls.append(att["url"])
    return urls


def update(record_id: str, fields: dict[str, Any]) -> None:
    token, base = _cfg()
    r = requests.patch(
        f"{API}/{base}/{requests.utils.quote(TABLE)}/{record_id}",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"fields": fields},
        timeout=30,
    )
    r.raise_for_status()
