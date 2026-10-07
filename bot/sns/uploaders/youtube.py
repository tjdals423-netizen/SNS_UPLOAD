from googleapiclient.http import MediaFileUpload

from ..google_client import youtube_service


def upload(cfg: dict, account: str, path, title: str) -> str:
    yt = youtube_service(account)
    body = {
        "snippet": {
            "title": title,
            "description": "",
            "categoryId": str(cfg.get("youtube", {}).get("category_id", "22")),
        },
        "status": {
            "privacyStatus": cfg.get("youtube", {}).get("privacy", "private"),
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(path), chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return f"https://youtu.be/{resp['id']}"
