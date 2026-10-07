"""업로드 실패 메시지를 보고 '무엇을 하면 되는지' 안내 문구를 만듦."""
import re

from .config import load_tokens

# 토큰 만료·연결 끊김으로 보는 오류 문구
TOKEN_ERR = re.compile(
    r"Session has expired|Error validating access token|OAuthException|['\"]code['\"]:\s*190\b"
    r"|invalid_grant|expired or revoked|access_token_invalid|invalid_token|연결 정보가 없습니다",
    re.I,
)
NETWORK_ERR = re.compile(r"10053|10054|10060|Connection aborted|ConnectionError|timed out|Max retries exceeded", re.I)
QUOTA_ERR = re.compile(r"quotaExceeded|exceeded your quota", re.I)


def _username(section: str, account: str) -> str:
    try:
        name = load_tokens().get(section, {}).get(account, {}).get("username")
    except Exception:
        name = None
    return f"@{name}" if name else f"{account} 계정"


def _token_hint(p: str, account: str) -> str:
    if p == "threads":
        who = _username("threads", account)
        return (
            f"🔑 쓰레드 {account} 연결이 끊겼어요 (토큰 만료). 이렇게 하세요:\n"
            f"1) 크롬에서 threads.com 에 {who} 로 로그인돼 있는지 확인\n"
            f"2) bot\\setup.bat 실행 → 4 → {account} 입력\n"
            f"3) 권한 화면에서 허용 → '로그인 완료' 페이지 주소 전체를 복사해 검은 창에 붙여넣기\n"
            f"4) '✅ 쓰레드 {account} = {who} 연결 완료' 확인 (계정이 다르면 크롬 계정 바꾸고 다시)\n"
            f"5) 시트 결과_쓰레드 칸 지우기 → 다시 올라감 (봇 재시작 필요 없음)"
        )
    if p in ("instagram", "facebook"):
        return (
            f"🔑 페북·인스타 {account} 연결이 끊겼어요 (약 90일마다 만료). 이렇게 하세요:\n"
            "1) developers.facebook.com/tools/explorer 에서 사용자 토큰 새로 받기 (권한 8개, README 참고)\n"
            "2) bot\\setup.bat 실행 → 3 → 복사한 토큰 붙여넣기 → 페이지마다 계정 이름 입력\n"
            "3) 시트 결과_인스타 / 결과_페북 칸 지우기 → 다시 올라감"
        )
    if p == "tiktok":
        return (
            f"🔑 틱톡 {account} 연결이 끊겼어요. 이렇게 하세요:\n"
            f"1) 크롬에서 tiktok.com 에 {account} 계정으로 로그인돼 있는지 확인\n"
            f"2) bot\\setup.bat 실행 → 5 → {account} 입력 → 허용 → 주소 붙여넣기\n"
            "3) 시트 결과_틱톡 칸 지우기 → 다시 올라감"
        )
    if p == "youtube":
        return (
            f"🔑 유튜브 {account} 연결이 끊겼어요. 이렇게 하세요:\n"
            f"1) bot\\setup.bat 실행 → 2 → {account} 입력 → {account} 채널로 로그인\n"
            "2) 시트 결과_유튜브 칸 지우기 → 다시 올라감"
        )
    # 영상 받기·시트 기록 단계 (구글 폼 주인 계정)
    return (
        "🔑 구글(폼/시트/드라이브) 연결이 끊겼어요. 이렇게 하세요:\n"
        "1) bot\\setup.bat 실행 → 1 → 폼을 만든 구글 계정으로 로그인\n"
        "2) 시트의 실패한 결과 칸 지우기 → 다시 올라감"
    )


def for_failure(p: str, account: str, err: str) -> str:
    """p: 플랫폼 키 또는 'google'(준비 단계). 안내가 필요 없으면 빈 문자열."""
    if TOKEN_ERR.search(err):
        return _token_hint(p, account)
    if p == "youtube" and QUOTA_ERR.search(err):
        return "⏳ 유튜브 하루 업로드 한도 초과 → 오후 4~5시 이후 시트 결과_유튜브 칸을 지우면 다시 올라감"
    if NETWORK_ERR.search(err):
        return "🌐 인터넷 연결이 끊겨서 실패했어요 (계정 문제 아님). 자동 재시도를 기다리거나 인터넷(랜선/와이파이)을 확인하세요."
    return ""
