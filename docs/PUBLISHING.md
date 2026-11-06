# Publishing

**Automation limits.** YouTube and TikTok keep API uploads private until each
platform approves a compliance audit of your app, so for now upload by hand:

```bash
python -m scripts.upload_pack <run_id>
```

That writes `upload_ready/` with the video, thumbnail, captions and paste-ready
title, description and tags for each platform. Documentaries go to YouTube and
Facebook; vertical clips go to every platform (`publishing.long_platforms`,
`publishing.short_platforms`). Read `claims_to_check.txt` in the review folder
before approving anything: automated fact checking is not reliable enough.
 setup — the final go-live step

Everything is built and **dry-run by default**. When you're ready to actually
post, do two things: (1) add each platform's credentials to `.env` / GitHub
Secrets, (2) set `publishing.dry_run: false` in `config/settings.yaml`. Check
readiness any time with:

```bash
python -m scripts.doctor        # shows which platforms are credential-ready
```

New uploads start **private** (`publishing_agent/config.yaml -> first_privacy`)
so you can review before making them public.

---

## YouTube (Data API v3)
1. Google Cloud Console → create a project → enable **YouTube Data API v3**.
2. Create an **OAuth client ID** (Desktop app). Note client id + secret.
3. Do the one-time consent flow to get a **refresh token** with these scopes:
   - `https://www.googleapis.com/auth/youtube.upload` (uploads, thumbnails)
   - `https://www.googleapis.com/auth/youtube.force-ssl` (caption tracks)
   - `https://www.googleapis.com/auth/yt-analytics.readonly` (live analytics, read-only)

   Use `access_type=offline` and `prompt=consent` so Google returns a refresh token.
   (Google OAuth Playground is the easiest way, or a small local script.)

   **Refresh tokens expire after 7 days while the Google Cloud app is in
   "Testing" mode.** For unattended use, set the OAuth consent screen's publishing
   status to "In production" (a personal app with only your own account needs no
   Google verification for these scopes to keep working, but you will see an
   "unverified app" warning once during consent).
4. Set:
   ```
   YOUTUBE_CLIENT_ID=...
   YOUTUBE_CLIENT_SECRET=...
   YOUTUBE_REFRESH_TOKEN=...
   ```
Uploads set title/description/tags, category = Education, custom thumbnail, and
the SRT caption track automatically.

## Facebook (Page videos, Graph API)
1. Meta for Developers: create an app and add your Page. Note the **App ID**.
2. Get a **user access token** and a **Page access token** with `pages_show_list`,
   `pages_read_engagement`, `pages_manage_posts` (Meta's docs also mention
   `publish_video`; check your app dashboard, including whether App Review applies).
3. Set `FACEBOOK_APP_ID`, `FACEBOOK_USER_TOKEN`, `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_TOKEN`.

Uploads are resumable and stay **unpublished** unless privacy is `public`.

## TikTok (Content Posting API)
1. TikTok for Developers → app → request **Content Posting API** (video.publish).
2. Get a user **access token**. Set `TIKTOK_ACCESS_TOKEN`.
3. Until TikTok approves your app's audit, posts are private only and the account
   must be private. The uploader checks the account's limits first.
3. Until your app passes audit, posts are **SELF_ONLY** (private) — expected.

## Instagram (Reels, Graph API)
IG's API does **not** accept a file upload — the mp4 must be at a **public URL**.
1. Connect an IG **Business/Creator** account to your Facebook Page.
2. Set `INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`.
3. Host the produced mp4 somewhere public (e.g. S3/Cloudflare R2/your CDN) and
   set `INSTAGRAM_VIDEO_URL` to it (or wire a host step in the publisher).

---

## What a dry-run produces
For every run, `storage/videos/<run_id>_publish.json` records the exact package
that *would* be posted to each platform — title, description, tags, hashtags,
thumbnail, captions, privacy — so you can review before going live.
