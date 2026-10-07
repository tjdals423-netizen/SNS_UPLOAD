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
        self.headers = values[0]
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
