#!/usr/bin/env python3
"""Publish due Instagram carousels from the Orrery HQ content calendar.

Reads Airtable for posts whose Status is "Scheduled" and whose Publish Date has
passed, pushes them to Instagram as a carousel, then writes the permalink back
and flips the status to "Published".

Instagram's Content Publishing API has no scheduling of its own: it posts the
moment you call it. The scheduling therefore lives in Airtable's Publish Date
plus whatever cadence the GitHub Actions cron runs at.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

import requests

GRAPH = "https://graph.facebook.com/v21.0"
AIRTABLE = "https://api.airtable.com/v0"
TABLE = "Content Calendar"

AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN", "")
BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")
META_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

# Instagram allows at most 10 items in a carousel.
MAX_SLIDES = 10


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str) -> None:
    log(f"ERROR: {msg}")
    sys.exit(1)


def check_env() -> None:
    missing = [
        name
        for name, val in [
            ("AIRTABLE_TOKEN", AIRTABLE_TOKEN),
            ("AIRTABLE_BASE_ID", BASE_ID),
            ("IG_USER_ID", IG_USER_ID),
            ("META_ACCESS_TOKEN", META_TOKEN),
        ]
        if not val
    ]
    if missing:
        die(f"missing environment variables: {', '.join(missing)}")


def airtable_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}


def due_posts() -> list[dict[str, Any]]:
    """Scheduled posts whose publish time has arrived."""
    formula = 'AND({Status}="Scheduled", {Publish Date}<=NOW())'
    r = requests.get(
        f"{AIRTABLE}/{BASE_ID}/{requests.utils.quote(TABLE)}",
        headers=airtable_headers(),
        params={"filterByFormula": formula, "pageSize": 50},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("records", [])


def slide_urls(fields: dict[str, Any]) -> list[str]:
    """Attachment URLs in slide order.

    Airtable attachment URLs are short-lived, so they are read at publish time
    and handed straight to Meta rather than cached anywhere.
    """
    media = fields.get("Media (JPEG)") or []
    urls = []
    for att in media:
        if att.get("type") != "image/jpeg":
            raise RuntimeError(f"{att.get('filename')} is {att.get('type')}, Instagram needs image/jpeg")
        urls.append(att["url"])
    return urls


def graph_post(path: str, data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data)
    payload["access_token"] = META_TOKEN
    r = requests.post(f"{GRAPH}/{path}", data=payload, timeout=60)
    if not r.ok:
        raise RuntimeError(f"POST {path} -> {r.status_code} {r.text[:400]}")
    return r.json()


def graph_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    q = dict(params)
    q["access_token"] = META_TOKEN
    r = requests.get(f"{GRAPH}/{path}", params=q, timeout=60)
    if not r.ok:
        raise RuntimeError(f"GET {path} -> {r.status_code} {r.text[:400]}")
    return r.json()


def wait_until_ready(container_id: str, timeout_s: int = 300) -> None:
    """Block until a container finishes processing.

    Publishing a container that is still IN_PROGRESS fails, so this must run
    before media_publish.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = graph_get(container_id, {"fields": "status_code,status"})
        code = status.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {container_id} ended as {code}: {status.get('status')}")
        time.sleep(5)
    raise RuntimeError(f"container {container_id} still not FINISHED after {timeout_s}s")


def publish_carousel(urls: list[str], caption: str) -> tuple[str, str]:
    """Create child containers, group them, publish. Returns (media_id, permalink)."""
    children = []
    for i, url in enumerate(urls, 1):
        child = graph_post(IG_USER_ID + "/media", {"image_url": url, "is_carousel_item": "true"})
        children.append(child["id"])
        log(f"    slide {i}/{len(urls)} -> container {child['id']}")

    for cid in children:
        wait_until_ready(cid)

    parent = graph_post(
        IG_USER_ID + "/media",
        {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption},
    )
    wait_until_ready(parent["id"])

    published = graph_post(IG_USER_ID + "/media_publish", {"creation_id": parent["id"]})
    media_id = published["id"]
    permalink = graph_get(media_id, {"fields": "permalink"}).get("permalink", "")
    return media_id, permalink


def mark_published(record_id: str, permalink: str) -> None:
    r = requests.patch(
        f"{AIRTABLE}/{BASE_ID}/{requests.utils.quote(TABLE)}/{record_id}",
        headers={**airtable_headers(), "Content-Type": "application/json"},
        json={"fields": {"Status": "Published", "Post URL": permalink}},
        timeout=30,
    )
    r.raise_for_status()


def main() -> int:
    check_env()
    records = due_posts()
    if not records:
        log("nothing due")
        return 0

    log(f"{len(records)} post(s) due")
    failures = 0
    for rec in records:
        f = rec.get("fields", {})
        title = f.get("Title / Hook", "(untitled)")
        log(f"\n--- {title}")
        try:
            urls = slide_urls(f)
            if not urls:
                raise RuntimeError("no JPEG slides attached")
            if len(urls) > MAX_SLIDES:
                raise RuntimeError(f"{len(urls)} slides, Instagram allows {MAX_SLIDES}")
            caption = f.get("Caption", "") or ""

            if DRY_RUN:
                log(f"    DRY RUN: would post {len(urls)} slides, caption {len(caption)} chars")
                continue

            media_id, permalink = publish_carousel(urls, caption)
            mark_published(rec["id"], permalink)
            log(f"    published {media_id} -> {permalink}")
        except Exception as exc:  # keep going; one bad post shouldn't block the rest
            failures += 1
            log(f"    FAILED: {exc}")

    if failures:
        log(f"\n{failures} post(s) failed")
        return 1
    log("\nall done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
