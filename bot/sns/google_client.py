"""구글 로그인(폼 주인 계정: 드라이브/시트, 채널별: 유튜브)과 드라이브 도우미."""
import io
import re
from contextlib import contextmanager
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from .config import GOOGLE_CLIENT_PATH, load_tokens, update_token

OWNER_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def login(scopes) -> Credentials:
    if not GOOGLE_CLIENT_PATH.exists():
        raise SystemExit(f"구글 OAuth JSON 파일을 {GOOGLE_CLIENT_PATH} 에 넣어주세요.")
    flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CLIENT_PATH), scopes)
    return flow.run_local_server(port=0, prompt="consent", access_type="offline")


def load_creds(key: str, scopes) -> Credentials:
    info = load_tokens().get("google", {}).get(key)
    if not info:
        raise RuntimeError(f"구글 로그인 정보({key})가 없습니다. setup 을 먼저 실행하세요.")
    creds = Credentials.from_authorized_user_info(info, scopes)
    if not creds.valid:
        creds.refresh(Request())
    return creds


def save_creds(key: str, creds: Credentials) -> None:
    import json

    update_token("google", key, json.loads(creds.to_json()))


def owner_services():
    creds = load_creds("owner", OWNER_SCOPES)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return drive, sheets


def youtube_service(account: str):
    creds = load_creds(f"youtube_{account}", YOUTUBE_SCOPES)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def file_id_from_url(value: str) -> str:
    m = re.search(r"(?:id=|/d/)([A-Za-z0-9_-]{10,})", value or "")
    if not m:
        raise ValueError(f"영상 링크에서 파일 ID 를 찾지 못했습니다: {value!r}")
    return m.group(1)


def download(drive, file_id: str, dest_dir: Path) -> Path:
    meta = drive.files().get(fileId=file_id, fields="name,mimeType,size").execute()
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "_", meta["name"])
    path = dest_dir / f"{file_id}_{safe}"
    req = drive.files().get_media(fileId=file_id)
    with io.FileIO(path, "wb") as fh:
        dl = MediaIoBaseDownload(fh, req, chunksize=16 * 1024 * 1024)
        done = False
        while not done:
            _, done = dl.next_chunk()
    return path


def download_image_jpeg(drive, file_id: str, dest_dir: Path) -> Path:
    """썸네일 이미지를 받아 JPEG 로 변환 (인스타·페북 커버는 JPEG 가 가장 안전)."""
    from PIL import Image

    raw = download(drive, file_id, dest_dir)
    jpg = raw.with_name(raw.stem + "_cover.jpg")
    with Image.open(raw) as im:
        im.convert("RGB").save(jpg, "JPEG", quality=92)
    if raw != jpg:
        raw.unlink(missing_ok=True)
    return jpg


@contextmanager
def public_image(drive, path):
    """인스타 커버처럼 '공개 URL'이 필요할 때: 드라이브에 잠깐 올려 링크 공개 → 끝나면 삭제."""
    if not path:
        yield None
        return
    f = drive.files().create(
        body={"name": path.name}, media_body=MediaFileUpload(str(path), mimetype="image/jpeg"), fields="id"
    ).execute()
    try:
        drive.permissions().create(fileId=f["id"], body={"type": "anyone", "role": "reader"}).execute()
        yield f"https://drive.usercontent.google.com/download?id={f['id']}&export=download&confirm=t"
    finally:
        try:
            drive.files().delete(fileId=f["id"]).execute()
        except Exception:
            pass


def cleanup(drive, file_id: str, mode: str) -> None:
    """업로드 끝난 원본 영상 정리. delete = 영구 삭제(용량 바로 확보), trash = 휴지통."""
    if mode == "delete":
        drive.files().delete(fileId=file_id).execute()
    elif mode == "trash":
        drive.files().update(fileId=file_id, body={"trashed": True}).execute()


class PublicLink:
    """쓰레드처럼 '공개 URL'이 필요한 플랫폼용: 업로드 동안만 드라이브 파일을 링크 공개로 열어둠."""

    def __init__(self, drive, file_id: str):
        self.drive, self.file_id, self.perm_id = drive, file_id, None

    def __enter__(self) -> str:
        perm = self.drive.permissions().create(
            fileId=self.file_id, body={"type": "anyone", "role": "reader"}, fields="id"
        ).execute()
        self.perm_id = perm["id"]
        return f"https://drive.usercontent.google.com/download?id={self.file_id}&export=download&confirm=t"

    def __exit__(self, *exc):
        if self.perm_id:
            try:
                self.drive.permissions().delete(fileId=self.file_id, permissionId=self.perm_id).execute()
            except Exception:
                pass
