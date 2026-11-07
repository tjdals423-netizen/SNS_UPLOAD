"""폼 응답 시트 읽기/결과 쓰기."""
from dataclasses import dataclass, field

from .config import PLATFORM_KO, PLATFORMS

STATUS_COL = "상태"
RESULT_COLS = {p: f"결과_{PLATFORM_KO[p]}" for p in PLATFORMS}


def col_letter(idx: int) -> str:
    """0-based 열 번호 → A1 표기 열 이름."""
    s, n = "", idx + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


@dataclass
class Row:
    number: int                       # 시트의 실제 행 번호(1-based)
    values: dict = field(default_factory=dict)


class Sheet:
    def __init__(self, sheets_service, cfg: dict):
        self.svc = sheets_service.spreadsheets()
        self.sid = cfg["sheet"]["spreadsheet_id"]
        self.ws = cfg["sheet"].get("worksheet") or self._first_tab()
        self.headers: list[str] = []

    def _first_tab(self) -> str:
        meta = self.svc.get(spreadsheetId=self.sid, fields="sheets.properties.title").execute()
        return meta["sheets"][0]["properties"]["title"]

    def _rng(self, a1: str) -> str:
        return f"'{self.ws}'!{a1}"

    def read(self) -> list[Row]:
        data = self.svc.values().get(spreadsheetId=self.sid, range=self._rng("A1:ZZ")).execute()
        values = data.get("values", [])
        if not values:
            return []
        self.headers = [h.strip() for h in values[0]]
        self._ensure_columns()
        rows = []
        for i, raw in enumerate(values[1:], start=2):
            rows.append(Row(i, {h: (raw[j] if j < len(raw) else "") for j, h in enumerate(self.headers)}))
        return rows

    def _ensure_columns(self) -> None:
        missing = [c for c in [STATUS_COL, *RESULT_COLS.values()] if c not in self.headers]
        if not missing:
            return
        start = len(self.headers)
        self.svc.values().update(
            spreadsheetId=self.sid,
            range=self._rng(f"{col_letter(start)}1"),
            valueInputOption="RAW",
            body={"values": [missing]},
        ).execute()
        self.headers += missing

    def write(self, row: Row, header: str, value: str) -> None:
        idx = self.headers.index(header)
        self.svc.values().update(
            spreadsheetId=self.sid,
            range=self._rng(f"{col_letter(idx)}{row.number}"),
            valueInputOption="RAW",
            body={"values": [[value]]},
        ).execute()
        row.values[header] = value

    def append(self, values: dict) -> int:
        """폼 응답처럼 맨 아래에 한 줄 추가 (텔레그램 /upload 용). 같은 이름의 열이 여러 개면 모두 채움."""
        rows = self.read()   # 늘 새로 읽음: 그 사이 폼 응답이 들어왔을 수 있음
        line = [values.get(h, "") for h in self.headers]
        # values().append 는 폼 응답 시트에서 '표 끝'을 폼 응답 끝으로 봐서, 웹으로 넣은 줄을 다음 웹 줄이
        # 계속 덮어썼음 (실측 2026-11-07: 82행에 EVA·민아살림·은조네키친·예쁜살림이 차례로 덮임). 그래서
        # 실제로 채워진 마지막 줄 바로 아래에 직접 씀.
        last = max((r.number for r in rows if any(str(x).strip() for x in r.values.values())), default=1)
        self.svc.values().update(
            spreadsheetId=self.sid,
            range=self._rng(f"A{last + 1}"),
            valueInputOption="RAW",
            body={"values": [line]},
        ).execute()
        return last + 1
