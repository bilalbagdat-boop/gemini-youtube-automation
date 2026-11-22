# FILE: src/uploader.py
# Robust YouTube Upload Handler supporting Desktop OAuth and GitHub Actions CI

import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from pathlib import Path

CLIENT_SECRETS_FILE = Path('client_secrets.json')
CREDENTIALS_FILE = Path('credentials.json')
YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]


def sanitize_title(title: str | None, max_length: int = 100) -> str:
    """Return a YouTube-safe title that is non-empty and within the API limit."""
    clean_title = str(title or "").replace("&lt;", "").replace("&gt;", "").replace("<", "").replace(">", "").strip()
    if not clean_title:
        clean_title = "Untitled Video"

    if len(clean_title) > max_length:
        clean_title = clean_title[: max_length - 3].rstrip() + "..."

    return clean_title


def get_authenticated_service():
    """Handles OAuth2 flow and returns an authenticated YouTube service object."""
    credentials = None

    if CREDENTIALS_FILE.exists():
        print("INFO: Found existing credentials file.")
        credentials = Credentials.from_authorized_user_file(str(CREDENTIALS_FILE), YOUTUBE_UPLOAD_SCOPE)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            print("INFO: Refreshing expired credentials...")
            credentials.refresh(Request())
        else:
            print("INFO: Starting new authentication flow...")
            if not CLIENT_SECRETS_FILE.exists():
                raise FileNotFoundError(f"CRITICAL ERROR: {CLIENT_SECRETS_FILE} not found. Please provide client_secrets.json from Google Cloud Console.")

            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), scopes=YOUTUBE_UPLOAD_SCOPE)
            credentials = flow.run_local_server(port=0)

        with open(CREDENTIALS_FILE, 'w') as f:
            f.write(credentials.to_json())
        print(f"INFO: Credentials saved to {CREDENTIALS_FILE}")

    return build('youtube', 'v3', credentials=credentials)


def upload_to_youtube(video_path, title, description, tags, thumbnail_path=None):
    """Uploads a video to YouTube with metadata and optional thumbnail."""
    sanitized_title = sanitize_title(title)
    privacy_status = os.getenv("YOUTUBE_PRIVACY_STATUS", "private")
    category_id = os.getenv("YOUTUBE_CATEGORY_ID", "27")  # 27 = Education

    print(f"⬆️ Uploading '{video_path}' to YouTube ({privacy_status.upper()}) with title: {sanitized_title}")
    try:
        youtube = get_authenticated_service()

        request_body = {
            'snippet': {
                'title': sanitized_title,
                'description': description,
                'tags': [t.strip() for t in tags.split(',') if t.strip()],
                'categoryId': category_id
            },
            'status': {
                'privacyStatus': privacy_status,
                'selfDeclaredMadeForKids': False
            }
        }

        media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)

        request = youtube.videos().insert(
            part=','.join(request_body.keys()),
            body=request_body,
            media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"Uploaded {int(status.progress() * 100)}%.")

        video_id = response.get('id')
        print(f"✅ Video uploaded successfully! Video ID: {video_id}")

        if thumbnail_path and os.path.exists(thumbnail_path):
            print(f"⬆️ Uploading thumbnail '{thumbnail_path}' for video ID: {video_id}...")
            try:
                thumbnail_media = MediaFileUpload(str(thumbnail_path))
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=thumbnail_media
                ).execute()
                print("✅ Thumbnail uploaded successfully!")
            except Exception as e:
                print(f"⚠️ Note: Failed to upload custom thumbnail (channel verification may be required): {e}")
        else:
            print("⚠️ No thumbnail path provided or thumbnail file does not exist. Skipping thumbnail upload.")

        return video_id

    except Exception as e:
        print(f"❌ ERROR: Failed to upload to YouTube. {e}")
        raise
