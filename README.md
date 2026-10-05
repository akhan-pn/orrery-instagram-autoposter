# Orrery social autoposter

Posts Orrery's carousels to **Instagram, LinkedIn and Facebook** from the
**Orrery HQ** Airtable base, on a schedule, for free.

Each record's **Platform** field decides where it goes. Instagram and Facebook
get the JPEG slides; LinkedIn gets the PDF, because a LinkedIn carousel is a
document post. Each is tracked separately in **Post URL**, **LinkedIn URL** and
**Facebook URL**, so a failure on one channel is retried without re-posting to
the others.

A GitHub Actions cron job looks for posts whose **Status** is `Scheduled` and
whose **Publish Date** has passed, pushes them to Instagram as a carousel, then
writes the permalink into **Post URL** and sets **Status** to `Published`.

Running cost: nothing. GitHub Actions, the Instagram Graph API and Airtable's
API are all free at this volume.

## How the scheduling actually works

Instagram's Content Publishing API **cannot schedule**. It posts the moment you
call it. So the schedule is: Airtable holds the intended time, and the cron job
publishes anything already due. A post never goes out early.

GitHub's scheduler is best-effort and commonly runs 5-15 minutes late, so the
cron is set for `04:35 UTC` (10:05 IST) — just *after* the 10:00 slot. Change
the `cron:` line in `.github/workflows/publish.yml` if your posting time moves.

## Setup

### 1. Instagram side

You need an Instagram **Business** or **Creator** account linked to a Facebook
Page. A personal account will not work.

1. Create an app at <https://developers.facebook.com/apps> (type: Business).
2. Add the **Instagram Graph API** product.
3. Leave the app in **Development** mode. Posting to your own account works
   without App Review as long as your user has a role on the app.
4. In Graph API Explorer, grant `instagram_basic`, `instagram_content_publish`
   and `pages_show_list`, then generate a token.
5. Exchange it for a **long-lived** token (60 days):
   ```
   curl -s "https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN"
   ```
6. Find your Instagram user id:
   ```
   curl -s "https://graph.facebook.com/v21.0/me/accounts?access_token=TOKEN"
   curl -s "https://graph.facebook.com/v21.0/PAGE_ID?fields=instagram_business_account&access_token=TOKEN"
   ```
   The `instagram_business_account.id` is your `IG_USER_ID`.

### 2. Airtable side

Create a personal access token at <https://airtable.com/create/tokens> with
`data.records:read` and `data.records:write` scoped to the Orrery HQ base.

### 3. GitHub side

Push this folder to a repo, then add four **Actions secrets**
(Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `AIRTABLE_TOKEN` | the Airtable PAT |
| `AIRTABLE_BASE_ID` | `appbfEP3OQhdnBzYN` |
| `IG_USER_ID` | Instagram Business account id |
| `META_ACCESS_TOKEN` | the long-lived token |

### 4. Test before trusting it

Run the workflow manually (Actions → *Publish due Instagram posts* → Run
workflow) with **dry run ticked**. It prints what it would post without
posting. Only once that looks right, run it with dry run off — and watch the
first real post land before leaving it unattended.

## Using it day to day

1. Set **Publish Date** on a post.
2. Attach the slides to **Media (JPEG)**, in order.
3. Set **Status** to `Scheduled`.

The next cron run picks it up. Anything left as `Approved` is ignored — that is
deliberate, so approving a draft never publishes it by itself.

## Things that will eventually break

- **The Meta token expires every 60 days.** Regenerate it and update the
  secret, or automate the refresh. This is the most likely cause of a silent
  stop.
- **Instagram only accepts JPEG.** The `Media (JPEG)` field exists for that
  reason; the `File` field on Assets holds the PNG originals. The script
  refuses anything that is not `image/jpeg` rather than failing at Meta.
- **Carousels cap at 10 slides**, and Instagram allows **50 posts per 24h**.
- **Airtable attachment URLs expire.** The script reads them at publish time
  and hands them straight to Meta; never cache them.
- **Free Actions minutes**: 2,000/month on private repos. A daily run uses
  about 30. Going to every 30 minutes would use ~1,440 — still under, but
  without much headroom.

## Local run

```
pip install -r requirements.txt
cp .env.example .env     # fill it in
set -a; source .env; set +a
DRY_RUN=1 python publish.py
```


## LinkedIn

`linkedin.py` picks its backend from whichever variables are set, preferring
the unlimited one.

### Direct (free, unlimited)

Needs `LINKEDIN_ORG_URN` and `LINKEDIN_ACCESS_TOKEN`.

Posting *as an organisation* requires the `w_organization_social` scope, which
only comes with LinkedIn's **Community Management API** — an application
LinkedIn has to approve, not a product you can just enable. Apply at
<https://developer.linkedin.com/product-catalog>. Approval is not guaranteed.

Your org URN is `urn:li:organization:<id>`; the id is in your Company Page
admin URL.

### Publora (fallback, 15 posts/month free)

Needs `PUBLORA_API_KEY` and `PUBLORA_LINKEDIN_PLATFORM_ID`.

Publora already holds the company-page connection, so no LinkedIn approval is
involved. Sign up at <https://app.publora.com>, connect the Orrery page, and
copy the platform id (`linkedin-xxxxxxxx`) from Channels.

Use this if the Community Management application is rejected or still pending.

## Facebook

`facebook.py` posts to the Orrery **Page**, reusing the same `Media (JPEG)`
slides Instagram gets — Facebook accepts JPEG and PNG, so no separate render
is needed.

Needs `FB_PAGE_ID` and `FB_PAGE_ACCESS_TOKEN`.

A multi-image Page post is two steps, not one: each image goes to
`/{page-id}/photos` with `published=false`, which stores it without putting it
in the feed, and the returned photo ids are then attached to a single
`/{page-id}/feed` post. Uploading them published would create one feed story
per image instead of one post with a gallery.

The token must be a **Page** access token, not the user token that issued it.
Grant `pages_manage_posts` and `pages_read_engagement`, then read the page's
own token out of `/me/accounts`:

```
curl -s "https://graph.facebook.com/v21.0/me/accounts?access_token=USER_TOKEN"
```

The `id` is `FB_PAGE_ID` and the `access_token` on the same entry is
`FB_PAGE_ACCESS_TOKEN`. The resulting URL is written to **Facebook URL**.

## Files

| File | Does |
|---|---|
| `publish.py` | finds due records, routes them per Platform, writes results back |
| `instagram.py` | carousel via the Meta Graph API |
| `linkedin.py` | document post, direct or via Publora |
| `facebook.py` | multi-photo Page post via the Meta Graph API |
| `airtable_io.py` | reads the calendar, updates records |
