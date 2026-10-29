import sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def main():
    if len(sys.argv) < 2:
        print("Usage: python auth_youtube.py client_secret.json")
        raise SystemExit(2)
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    Path("token.json").write_text(credentials.to_json(), encoding="utf-8")
    print("Saved token.json. Store its contents as GitHub Secret YOUTUBE_TOKEN_JSON. Keep it private.")

if __name__ == "__main__":
    main()
