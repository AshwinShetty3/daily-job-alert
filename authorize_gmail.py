"""Run ON YOUR COMPUTER once; never commit credentials or token files."""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

if __name__ == "__main__":
    flow = InstalledAppFlow.from_client_secrets_file(
        "credentials.json", ["https://www.googleapis.com/auth/gmail.modify"]
    )
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not credentials.refresh_token:
        raise RuntimeError("No refresh token. Revoke the previous app grant and authorize again.")
    Path("token.json").write_text(credentials.to_json(), encoding="utf-8")
    print("Saved token.json. Store its contents as GMAIL_TOKEN_JSON; do not commit it.")
