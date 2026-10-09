"""플랫폼별 업로더. 모두 upload(...) -> str(결과 링크 또는 ID) 형태."""
import time

import requests

from .. import watchdog


class UploadError(Exception):
    pass


def check(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    err = data.get("error") if isinstance(data, dict) else None
    tiktok_ok = isinstance(err, dict) and err.get("code") == "ok"  # 틱톡은 성공해도 error.code="ok"
    if resp.status_code >= 400 or (err and not tiktok_ok):
        raise UploadError(f"HTTP {resp.status_code}: {str(data or resp.text)[:300]}")
    return data


def wait_until(fn, done, failed, timeout=600, interval=5):
    """fn() 결과가 done 이 될 때까지 대기. failed 면 예외."""
    end = time.time() + timeout
    while time.time() < end:
        watchdog.beat()
        status, detail = fn()
        if status in done:
            return status
        if status in failed:
            raise UploadError(f"처리 실패: {status} {detail or ''}")
        time.sleep(interval)
    raise UploadError("처리 시간이 너무 오래 걸립니다(시간 초과)")
