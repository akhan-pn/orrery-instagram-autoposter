"""Posting a carousel to an Instagram Business account.

Instagram's Content Publishing API takes JPEG only, and builds a carousel in
three steps: a container per slide, a container grouping them, then publish.
Each container has to finish processing before it can be used.
"""
from __future__ import annotations

import os
import time

import requests

GRAPH = "https://graph.facebook.com/v21.0"
MAX_SLIDES = 10


def configured() -> bool:
    return bool(os.environ.get("IG_USER_ID") and os.environ.get("META_ACCESS_TOKEN"))


def _token() -> str:
    return os.environ["META_ACCESS_TOKEN"]


def _post(path: str, data: dict) -> dict:
    r = requests.post(f"{GRAPH}/{path}", data={**data, "access_token": _token()}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"POST {path} -> {r.status_code} {r.text[:300]}")
    return r.json()


def _get(path: str, params: dict) -> dict:
    r = requests.get(f"{GRAPH}/{path}", params={**params, "access_token": _token()}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"GET {path} -> {r.status_code} {r.text[:300]}")
    return r.json()


def _wait_ready(container_id: str, timeout_s: int = 300) -> None:
    """Publishing a container that is still processing fails, so block first."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = _get(container_id, {"fields": "status_code,status"})
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {container_id} ended as {code}: {st.get('status')}")
        time.sleep(5)
    raise RuntimeError(f"container {container_id} not FINISHED after {timeout_s}s")


def publish(image_urls: list[str], caption: str, log=print) -> str:
    """Post the slides as a carousel. Returns the permalink."""
    if not image_urls:
        raise RuntimeError("no JPEG slides attached")
    if len(image_urls) > MAX_SLIDES:
        raise RuntimeError(f"{len(image_urls)} slides, Instagram allows {MAX_SLIDES}")

    ig = os.environ["IG_USER_ID"]
    children = []
    for i, url in enumerate(image_urls, 1):
        child = _post(f"{ig}/media", {"image_url": url, "is_carousel_item": "true"})
        children.append(child["id"])
        log(f"      slide {i}/{len(image_urls)}")

    for cid in children:
        _wait_ready(cid)

    parent = _post(
        f"{ig}/media",
        {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption},
    )
    _wait_ready(parent["id"])

    published = _post(f"{ig}/media_publish", {"creation_id": parent["id"]})
    return _get(published["id"], {"fields": "permalink"}).get("permalink", "")
