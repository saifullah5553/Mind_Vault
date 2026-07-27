# Publishing setup — the final go-live step

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
3. Do the one-time consent flow to get a **refresh token** with scope
   `https://www.googleapis.com/auth/youtube.upload` (and `.force-ssl` for captions).
   (Google OAuth Playground is the easiest way, or a small local script.)
4. Set:
   ```
   YOUTUBE_CLIENT_ID=...
   YOUTUBE_CLIENT_SECRET=...
   YOUTUBE_REFRESH_TOKEN=...
   ```
Uploads set title/description/tags, category = Education, custom thumbnail, and
the SRT caption track automatically.

## Facebook (Page videos, Graph API)
1. Meta for Developers → app → add your Page.
2. Get a long-lived **Page access token** with `pages_manage_posts`,
   `pages_read_engagement`.
3. Set `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_TOKEN`.

## TikTok (Content Posting API)
1. TikTok for Developers → app → request **Content Posting API** (video.publish).
2. Get a user **access token**. Set `TIKTOK_ACCESS_TOKEN`.
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
