#!/usr/bin/env python3
"""Publish due posts from the Orrery HQ content calendar.

Picks up records whose Status is "Scheduled" and whose Publish Date has passed,
sends each to every channel named in its Platform field, then records the
resulting URLs. Status only becomes "Published" once every targeted channel has
actually gone out.

Neither Instagram nor a LinkedIn document post can be scheduled through the
API, so the schedule lives in Airtable and the cron publishes whatever is
already due. Nothing ever goes out early.
"""
from __future__ import annotations

import os
import sys

import airtable_io
import instagram
import linkedin

DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")


def log(msg: str = "") -> None:
    print(msg, flush=True)


def platforms_for(fields: dict) -> list[str]:
    value = fields.get("Platform") or []
    if isinstance(value, str):
        value = [value]
    return [str(v) for v in value]


def handle(record: dict) -> tuple[int, int]:
    """Publish one record everywhere it still needs to go. Returns (sent, failed)."""
    fields = record.get("fields", {})
    title = fields.get("Title / Hook", "(untitled)")
    caption = fields.get("Caption", "") or ""
    targets = platforms_for(fields)

    log(f"\n--- {title}")
    if not targets:
        log("    no Platform set, skipping")
        return 0, 0

    writes: dict[str, str] = {}
    sent = failed = 0
    outstanding = 0

    # Instagram -------------------------------------------------------------
    if "Instagram" in targets:
        if fields.get("Post URL"):
            log("    Instagram: already posted")
        elif not instagram.configured():
            log("    Instagram: SKIPPED, IG_USER_ID / META_ACCESS_TOKEN not set")
            outstanding += 1
        else:
            try:
                urls = airtable_io.attachment_urls(fields, "Media (JPEG)", "image/jpeg")
                if DRY_RUN:
                    log(f"    Instagram: DRY RUN, {len(urls)} slides, caption {len(caption)} chars")
                    outstanding += 1
                else:
                    link = instagram.publish(urls, caption, log=log)
                    writes["Post URL"] = link
                    log(f"    Instagram: {link}")
                    sent += 1
            except Exception as exc:
                log(f"    Instagram FAILED: {exc}")
                failed += 1
                outstanding += 1

    # LinkedIn --------------------------------------------------------------
    if "LinkedIn" in targets:
        if fields.get("LinkedIn URL"):
            log("    LinkedIn: already posted")
        elif linkedin.backend() is None:
            log("    LinkedIn: SKIPPED, no backend configured")
            outstanding += 1
        else:
            try:
                pdfs = airtable_io.attachment_urls(fields, "Media (PDF)", "application/pdf")
                if not pdfs:
                    raise RuntimeError("no PDF attached in Media (PDF)")
                if DRY_RUN:
                    log(f"    LinkedIn: DRY RUN via {linkedin.backend()}, 1 PDF")
                    outstanding += 1
                else:
                    link = linkedin.publish(pdfs[0], caption, title)
                    writes["LinkedIn URL"] = link
                    log(f"    LinkedIn: {link}")
                    sent += 1
            except Exception as exc:
                log(f"    LinkedIn FAILED: {exc}")
                failed += 1
                outstanding += 1

    unknown = [t for t in targets if t not in ("Instagram", "LinkedIn")]
    if unknown:
        log(f"    no publisher for: {', '.join(unknown)}")
        outstanding += len(unknown)

    # Only close the record once nothing is left outstanding, so a partial
    # success is retried on the next run instead of being marked done.
    if writes and outstanding == 0:
        writes["Status"] = "Published"
    if writes and not DRY_RUN:
        airtable_io.update(record["id"], writes)

    return sent, failed


def main() -> int:
    try:
        records = airtable_io.due_posts()
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 1

    if not records:
        log("nothing due")
        return 0

    log(f"{len(records)} post(s) due" + (" [DRY RUN]" if DRY_RUN else ""))
    total_sent = total_failed = 0
    for rec in records:
        s, f = handle(rec)
        total_sent += s
        total_failed += f

    log(f"\npublished {total_sent}, failed {total_failed}")
    return 1 if total_failed else 0


if __name__ == "__main__":
    sys.exit(main())
