"""브라우저 로그인 → callback.html 에 표시된 주소를 붙여넣어 code 를 받는 공통 흐름."""
import secrets
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse


def ask_code(auth_base: str, params: dict) -> str:
    state = secrets.token_urlsafe(16)
    url = f"{auth_base}?{urlencode({**params, 'state': state})}"
    print("\n브라우저에서 로그인 창을 엽니다. 안 열리면 아래 주소를 직접 여세요:\n")
    print(url + "\n")
    webbrowser.open(url)
    pasted = input("로그인 후 '로그인 완료' 페이지에 나온 주소 전체를 붙여넣고 Enter: ").strip()
    qs = parse_qs(urlparse(pasted).query)
    if "error" in qs:
        raise SystemExit(f"로그인이 취소되었거나 실패했습니다: {qs.get('error_description', qs['error'])}")
    if qs.get("state", [None])[0] != state:
        raise SystemExit("주소가 이번 로그인과 맞지 않습니다. 처음부터 다시 해주세요.")
    code = qs.get("code", [""])[0]
    if not code:
        raise SystemExit("주소에 code 값이 없습니다. 주소 전체를 복사했는지 확인해 주세요.")
    return code.split("#")[0]


def choose_account(labels) -> str:
    labels = list(labels)
    while True:
        ans = input(f"어느 계정에 연결할까요? ({'/'.join(labels)}): ").strip().upper()
        if ans in labels:
            return ans
