# AI Clipping Bot + ClipRush Mobile

Mobile-first control panel for managing the clipping pipeline from a phone.

## What it does
- Maintains authorized source URLs in `sources.txt`.
- Edits clipping and YouTube publishing settings in `config.json`.
- Triggers the GitHub Actions workflow from the mobile dashboard.
- Shows recent workflow runs and their status.
- The processing engine downloads authorized VODs, transcribes audio, selects candidate windows, renders vertical clips, and can upload them to YouTube.

## Important limitations
- Use only VODs you have permission to download, edit, and republish. Public availability is not permission.
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
