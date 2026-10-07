"""setup.bat 에서 띄우는 계정 연결 메뉴."""
import setup
from sns.config import load_config

ITEMS = [
    ("구글 (폼/시트/드라이브)", "google"),
    ("유튜브 채널", "youtube"),
    ("페이스북 + 인스타", "meta"),
    ("쓰레드", "threads"),
    ("틱톡", "tiktok"),
    ("텔레그램 알림", "telegram"),
    ("연결 상태 점검", "check"),
]

while True:
    print("\n===== 업로드 봇 계정 연결 =====")
    for i, (label, _) in enumerate(ITEMS, 1):
        print(f" {i}. {label}")
    print(" 0. 종료")
    n = input("번호 선택: ").strip()
    if n == "0":
        break
    if not n.isdigit() or not 1 <= int(n) <= len(ITEMS):
        continue
    try:
        setup.COMMANDS[ITEMS[int(n) - 1][1]](load_config())
    except (SystemExit, Exception) as e:
        print(f"\n❗ 오류: {e}")
