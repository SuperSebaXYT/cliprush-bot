# AI Clipping Bot + ClipRush Mobile

Mobile-first control panel for managing the clipping pipeline from a phone.

## What it does
- Automatically discovers recent VODs from configured YouTube channels, or uses URLs in `sources.txt`.
- Stores processed video IDs in `processed_videos.json` to avoid selecting the same discovered VOD repeatedly.
- Edits clipping and YouTube publishing settings in `config.json`.
- Triggers the GitHub Actions workflow from the mobile dashboard.
- Shows recent workflow runs and their status.
- The processing engine discovers recent VODs (when enabled), downloads them, transcribes audio, selects candidate windows, renders vertical clips, and can upload them to YouTube.

## Automatic VOD discovery
- Enabled by default for IShowSpeed, Kai Cenat and CaseOh channel video pages.
- Scans up to 30 recent entries per channel, ignores live/upcoming broadcasts and VODs shorter than 10 minutes, and defaults to VODs from the last 30 days.
- Processes up to `max_sources_per_run` VODs each run and stores processed IDs in `processed_videos.json`. GitHub Actions commits changes to that file after a run.
- These channel URLs are defaults, not a guarantee that every channel page will be available to yt-dlp. Check the Actions log for discovery warnings.

## Important limitations
- Use only VODs you have permission to download, edit, and republish. Automatic discovery does not grant copyright permission; public availability is not permission.
- The first version selects moments using transcript heuristics, not a sophisticated semantic/video understanding model.
- Start with `publish: false` and `privacy_status: private`, inspect output artifacts, then enable publishing only after testing and confirming rights.
- GitHub-hosted runners have runtime/storage limits; long VODs may fail or time out.
- YouTube API upload quotas and OAuth authorization apply.

## Set up the repo (phone-only)
1. Create a GitHub repository, e.g. `cliprush-bot`.
2. Upload all files in this project into the repository root, including `.github/workflows/clipping.yml`.
3. In GitHub Settings -> Secrets and variables -> Actions, add `YOUTUBE_TOKEN_JSON` containing the OAuth `token.json` contents. The token must have the `youtube.upload` scope.
4. Deploy `app.py` on Streamlit Community Cloud from this repository. Set the app's main file to `app.py`.
5. In Streamlit app Settings -> Secrets, add:
   - `GITHUB_TOKEN = "github_pat_..."` (fine-grained token for this repository with Contents: Read and write, Actions: Read and write)
   - `GITHUB_REPO = "YOUR_GITHUB_USERNAME/cliprush-bot"`
   - `GITHUB_BRANCH = "main"`
6. Open the Streamlit app on your phone. Add authorized VOD URLs and configure settings.
7. Keep publishing disabled until the workflow succeeds and the generated clips look correct.

## YouTube OAuth from a phone
OAuth token creation can be awkward on a phone. Use Google's OAuth client setup and `auth_youtube.py` where possible, or complete the one-time authorization on a trusted computer if the provider's flow requires it. Never paste client secrets or tokens into chat or commit them to the repository.

## Security
The GitHub token is stored in Streamlit Cloud Secrets, not in browser controls or source code. Never put it in `app.py`, `config.json`, or a public repository. Use a fine-grained token limited to this one repository and revoke it if exposed.


### Live stream support

Automatic discovery checks each configured channel’s live, streams, and videos tabs. Active live streams are prioritized and recorded for a bounded 8-minute sample using Streamlink; ordinary VODs are downloaded with yt-dlp. The GitHub Actions schedule checks every 30 minutes. Upcoming streams are skipped.
