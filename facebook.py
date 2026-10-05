"""Posting a multi-photo post to the Orrery Facebook Page.

A Page photo post with several images is not one call: each image is uploaded
to /photos with published=false, which stores it without putting it in the
feed, and the resulting photo ids are then attached to a single /feed post.
Posting the images directly would create one feed story per image instead of
one post with a gallery.

The token has to be a *Page* access token, not the user token that issued it —
a user token is accepted by some endpoints and silently rejected by others.
"""
from __future__ import annotations

import json
import os

import requests

GRAPH = "https://graph.facebook.com/v21.0"


def configured() -> bool:
    return bool(os.environ.get("FB_PAGE_ID") and os.environ.get("FB_PAGE_ACCESS_TOKEN"))


def _token() -> str:
    return os.environ["FB_PAGE_ACCESS_TOKEN"]


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


def _permalink(post_id: str) -> str:
    """The canonical URL, falling back to the id-based one Facebook redirects."""
    try:
        link = _get(post_id, {"fields": "permalink_url"}).get("permalink_url")
    except RuntimeError:
        link = None
    return link or f"https://www.facebook.com/{post_id}"


def publish(image_urls: list[str], caption: str, log=print) -> str:
    """Post the images as one multi-photo Page post. Returns the permalink."""
    if not image_urls:
        raise RuntimeError("no JPEG slides attached")

    page = os.environ["FB_PAGE_ID"]
    attachments: dict[str, str] = {}
    for i, url in enumerate(image_urls):
        photo = _post(f"{page}/photos", {"url": url, "published": "false"})
        if "id" not in photo:
            raise RuntimeError(f"photo upload returned no id: {str(photo)[:300]}")
        # Each attached_media entry has to be its own JSON-encoded string;
        # Graph rejects a plain nested dict in form-encoded data.
        attachments[f"attached_media[{i}]"] = json.dumps({"media_fbid": photo["id"]})
        log(f"      photo {i + 1}/{len(image_urls)}")

    post = _post(f"{page}/feed", {"message": caption, **attachments})
    if "id" not in post:
        raise RuntimeError(f"feed post returned no id: {str(post)[:300]}")
    return _permalink(post["id"])
