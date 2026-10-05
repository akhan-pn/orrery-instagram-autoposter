"""Posting a carousel to a LinkedIn company page.

LinkedIn renders a carousel as a *document post*, so the per-post PDF is what
gets uploaded here — not the JPEG slides Instagram wants.

Two backends, chosen by which environment variables are present:

  direct   LINKEDIN_ORG_URN + LINKEDIN_ACCESS_TOKEN
           Posts straight to LinkedIn. Free and unlimited, but posting as an
           organization needs the `w_organization_social` scope, which comes
           from LinkedIn's Community Management API — an application they have
           to approve, not a switch you flip.

  publora  PUBLORA_API_KEY + PUBLORA_LINKEDIN_PLATFORM_ID
           Goes through Publora, which already holds the company-page
           connection. No LinkedIn approval needed. Free tier is 15 posts a
           month, so it is a fallback rather than the default.
"""
from __future__ import annotations

import os
from typing import Any

import requests

REST = "https://api.linkedin.com/rest"
PUBLORA = "https://api.publora.com/api/v1"
# LinkedIn requires an explicit API version; it is a date, bumped periodically.
LINKEDIN_VERSION = "202408"


def backend() -> str | None:
    """Which backend is configured, preferring the unlimited one."""
    if os.environ.get("LINKEDIN_ORG_URN") and os.environ.get("LINKEDIN_ACCESS_TOKEN"):
        return "direct"
    if os.environ.get("PUBLORA_API_KEY") and os.environ.get("PUBLORA_LINKEDIN_PLATFORM_ID"):
        return "publora"
    return None


# --------------------------------------------------------------------------
# direct
# --------------------------------------------------------------------------

def _li_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _upload_document(pdf_bytes: bytes, owner: str) -> str:
    """Register a document, PUT the bytes, return its URN."""
    init = requests.post(
        f"{REST}/documents?action=initializeUpload",
        headers={**_li_headers(), "Content-Type": "application/json"},
        json={"initializeUploadRequest": {"owner": owner}},
        timeout=60,
    )
    if not init.ok:
        raise RuntimeError(f"initializeUpload -> {init.status_code} {init.text[:300]}")
    value = init.json()["value"]

    put = requests.put(
        value["uploadUrl"],
        headers={"Authorization": f"Bearer {os.environ['LINKEDIN_ACCESS_TOKEN']}"},
        data=pdf_bytes,
        timeout=180,
    )
    if not put.ok:
        raise RuntimeError(f"document upload -> {put.status_code} {put.text[:300]}")
    return value["document"]


def _post_direct(pdf_bytes: bytes, caption: str, title: str) -> str:
    owner = os.environ["LINKEDIN_ORG_URN"]
    doc_urn = _upload_document(pdf_bytes, owner)

    body = {
        "author": owner,
        "commentary": caption,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "content": {"media": {"id": doc_urn, "title": title[:100]}},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    r = requests.post(
        f"{REST}/posts",
        headers={**_li_headers(), "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"create post -> {r.status_code} {r.text[:300]}")

    urn = r.headers.get("x-restli-id", "")
    return f"https://www.linkedin.com/feed/update/{urn}/" if urn else ""


# --------------------------------------------------------------------------
# publora
# --------------------------------------------------------------------------

def _post_publora(pdf_url: str, caption: str) -> str:
    r = requests.post(
        f"{PUBLORA}/create-post",
        headers={
            "x-publora-key": os.environ["PUBLORA_API_KEY"],
            "Content-Type": "application/json",
        },
        json={
            "content": caption,
            "platforms": [os.environ["PUBLORA_LINKEDIN_PLATFORM_ID"]],
            "mediaUrls": [pdf_url],
            # Publora treats a missing scheduledTime as "save as draft", so the
            # publish time is sent explicitly even though it is immediate.
            "scheduledTime": _now_iso(),
        },
        timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"publora create-post -> {r.status_code} {r.text[:300]}")
    data = r.json()
    return data.get("postUrl") or data.get("id", "") or "posted via publora"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------

def publish(pdf_url: str, caption: str, title: str) -> str:
    """Post the PDF as a LinkedIn document post. Returns the post URL."""
    which = backend()
    if which is None:
        raise RuntimeError(
            "no LinkedIn backend configured: set LINKEDIN_ORG_URN + "
            "LINKEDIN_ACCESS_TOKEN, or PUBLORA_API_KEY + PUBLORA_LINKEDIN_PLATFORM_ID"
        )
    if which == "publora":
        # Publora fetches the media itself, so the URL is handed over as-is.
        return _post_publora(pdf_url, caption)

    pdf = requests.get(pdf_url, timeout=120)
    if not pdf.ok:
        raise RuntimeError(f"could not fetch PDF from Airtable -> {pdf.status_code}")
    return _post_direct(pdf.content, caption, title)
