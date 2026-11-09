# Publishing

Checked against each platform's official documentation on 7 November 2026. These
rules change: YouTube's changed five days before this was written.

| Platform  | Automatic upload                | Private first? | Status in Mind_Vault                         |
|-----------|---------------------------------|----------------|----------------------------------------------|
| YouTube   | Yes, no audit needed            | Yes            | Working. Private test passed 7 Nov 2026      |
| Facebook  | Yes, through your own Meta app  | Must be tested | Ready to test. Never run against a real Page |
| Instagram | Yes, but posts go live at once  | No             | Blocked on purpose until you go public       |
| TikTok    | Private only; audit not open to us | Private only | Schedule it by hand (see below)              |

Secrets go in `.env` (open it in Notepad). Never paste one into a chat.

Three things stay true whichever route you use:

- `publishing.dry_run: true` means nothing leaves the computer.
- Only videos you approve are uploaded, and they start private
  (`agents/publishing_agent/config.yaml`, `first_privacy`).
- A video is refused if its credits record is missing or any licence forbids the use.

Check readiness at any time:

```bash
.venv\Scripts\python -m scripts.doctor
```

## 1. YouTube

Takes about 20 minutes, once.

1. Go to <https://console.cloud.google.com>, signed in as the account that owns the
   channel, and create a project called `Mind_Vault`.
2. **APIs & Services > Library**: enable **YouTube Data API v3**. Enable **YouTube
   Analytics API** too if you want real view numbers in the reports.
3. **Google Auth Platform > Branding**: fill in the app name and your email. Choose
   **External** under **Audience**.
4. **Audience > Test users > Add users**: add the Google account that owns the
   channel. The app stays in "Testing", where the sign-in lasts 7 days, so step 7
   has to be repeated each week. That is fine for testing but not for unattended
   uploads. **Publish app** removes the limit, but Google requires a home page,
   privacy policy and terms of service links for it, on a domain you add under
   **Authorized domains**.
5. **Clients > Create client > Desktop app**. Keep the page open.
6. Add these two lines to `.env`, using the values from that page:

   ```
   YOUTUBE_CLIENT_ID=
   YOUTUBE_CLIENT_SECRET=
   ```

7. Sign in. This opens your browser and saves the token to `.env` without showing it:

   ```bash
   .venv\Scripts\python -m scripts.youtube_auth
   ```

   Google warns that the app is unverified. That is expected for your own app:
   choose **Advanced**, then continue. Pick the Mind_Vault channel, then check that
   the script prints the right channel name.
8. Verify your phone at <https://www.youtube.com/verify>. Custom thumbnails need it.

Upload limits are not a concern: 100 uploads a day, and each video's thumbnail and
captions use 450 of 10,000 daily units.

**YouTube no longer locks API uploads to private.** Google lifted that on
2 November 2026, so a project without an audit can publish publicly. Mind_Vault
always sets the privacy itself, so `first_privacy: private` still applies. If a
request sets no privacy, YouTube now defaults to public, so keep that setting.

### First real test

1. In `config/settings.yaml`, set `publishing.dry_run: false`. Platforms without
   credentials stay in dry run, so this uploads to YouTube only.
2. Approve and upload the 59-second clip:

   ```bash
   .venv\Scripts\python -m scripts.review approve c0d0c0ae0800
   ```

   ```bash
   .venv\Scripts\python -m scripts.publish_approved c0d0c0ae0800
   ```

3. In YouTube Studio, confirm it says **Private** and that the title, description,
   thumbnail and captions are right.

## 2. Facebook Page

1. Create the Page if you don't have one, and be its admin.
2. Go to <https://developers.facebook.com/apps> and create an app of the **Business**
   type. Note the **App ID**.
3. Open **Graph API Explorer**, choose your app, and request `pages_show_list`,
   `pages_read_engagement` and `pages_manage_posts`. Generate a user token.
4. Open **Access Token Debugger** and extend it to a long-lived token. Long-lived
   user tokens last about 60 days, so set a calendar reminder to renew this one.
5. In the Explorer, call `me/accounts` with that token. Copy your Page's `id` and
   `access_token`.
6. Add to `.env`:

   ```
   FACEBOOK_APP_ID=
   FACEBOOK_USER_TOKEN=
   FACEBOOK_PAGE_ID=
   FACEBOOK_PAGE_TOKEN=
   ```

**Test on a spare Page, or before the Page has followers.** Two things can only be
learned from a real upload:

- Mind_Vault sends `published=false`, which Meta documents as controlling whether a
  post about the video is published. Meta also lists extra permissions for
  unpublished videos used in advertising, so check the result on the Page.
- Meta says all permissions need App Review, while developer guides say your own
  Pages only need a role on the app. If the upload is refused, or only you can see
  posts, the app probably has to be switched to **Live**, which needs a privacy
  policy link.

## 3. Instagram

Instagram's API has no private or draft mode, so a publish goes live straight away.
That conflicts with keeping everything private during testing, so **Mind_Vault skips
Instagram unless `first_privacy` is `public`.**

Until then, schedule by hand in **Meta Business Suite**. It's free, needs no app, and
handles the Page and Instagram together. Use the text in `upload_ready/`.

For later: the Instagram account must be a professional account linked to the Page,
and the app needs `instagram_basic`, `instagram_content_publish` and
`pages_read_engagement`. See "Still to build" before using it.

## 4. TikTok

TikTok's API keeps posts private (`SELF_ONLY`) until the app passes an audit, and the
account must be private while posting. Its guidelines list this as **not acceptable**
for the audit: "A utility tool to help upload contents to the account(s) you or your
team manages". That describes Mind_Vault, so don't plan on passing it.

The options, best first:

1. **Schedule in TikTok Studio on the web.** Free and takes a couple of minutes per
   clip. Use the text in `upload_ready/`.
2. **Draft upload through the API.** The video lands in your TikTok inbox and you tap
   to finish it. It needs TikTok to approve the `video.upload` scope, and it isn't
   built yet.
3. **A paid scheduler with its own audited app.** That is the only fully automatic
   route to public TikTok posts. You would be giving the company access to your
   account, and its code and terms need checking first.

Avoid bots that drive the TikTok or Instagram website. They can get an account
restricted, and an account is much harder to replace than a few minutes of work.

## Day to day

1. Autopilot renders videos into `storage/review/` (`docs/AUTOPILOT.md`).
2. Watch the video and read `claims_to_check.txt`. Automated fact checking is not
   reliable enough to skip this.
3. Run `python -m scripts.upload_pack <run_id>`, then commit and push
   `content/credits/`, because every description links there.
4. Approve it, then run `python -m scripts.publish_approved`.
5. Make it public yourself in YouTube Studio and on the Page. Schedule Instagram and
   TikTok by hand from `upload_ready/`.

## Going public automatically

This is a separate decision and is not switched on. It would mean setting
`first_privacy: public` after the private tests pass. Keep
`require_manual_approval: true` so a person still checks each video. The autopilot
refuses to run with both `dry_run` and `require_manual_approval` off.

## Still to build

| Item | Why | When |
|------|-----|------|
| Instagram direct file upload | Today it needs `INSTAGRAM_VIDEO_URL`, one fixed address, so every post would use the same video | Before Instagram goes automatic |
| Instagram wait-for-processing | Publishing right after creating the post can fail while video is processing | Same |
| Facebook vertical clips as Reels | Meta's Reels route has a documented `DRAFT` state, and clips would appear as Reels | When testing Facebook |
| TikTok token refresh | Access tokens last 2 hours, and the uploader reads one fixed token | Only if you use the API route |
| Retry for a platform added later | Once any platform succeeds, a run is marked published and isn't retried elsewhere | Before adding a second API platform |

## What a dry run produces

For every run, `storage/videos/<run_id>_publish.json` records the exact package that
would be posted to each platform, so you can review it first.
