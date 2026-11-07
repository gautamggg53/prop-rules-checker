"""Helpers for forgiving number/date parsing and table handling."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta, timezone, tzinfo
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import InputError

_DATE_FORMATS = (
    "%Y.%m.%d %H:%M:%S.%f",
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%d/%m/%Y %H:%M:%S.%f",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d.%m.%Y %H:%M:%S.%f",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%Y-%m-%d",
    "%Y.%m.%d",
)


def get_tz(name: str) -> tzinfo:
    """Return a tzinfo for an IANA name, ``UTC`` or a fixed offset like ``+02:00``."""
    text = (name or "UTC").strip()
    m = re.fullmatch(r"(?:UTC|GMT)?\s*([+-])(\d{1,2})(?::?(\d{2}))?", text, re.IGNORECASE)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0))
        return timezone(sign * delta)
    if text.upper() in ("UTC", "GMT", "Z"):
        return timezone.utc
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InputError(
            f"unknown timezone {name!r} (use an IANA name such as 'Europe/London' "
            "or an offset such as '+02:00')"
        ) from exc


def parse_number(
    text: object, *, field: str = "value", decimal_comma: bool = False, empty: float | None = None
) -> float:
    """Parse numbers as they appear in broker exports.

    Handles currency symbols, ``1 234.56`` and ``1,234.56`` thousands separators,
    ``(12.50)`` and unicode-minus negatives, ``0.10 Lots`` and ``0.1 / 0.1``.
    With ``decimal_comma`` a lone comma is a decimal separator; otherwise a lone
    comma followed by exactly three digits is read as a thousands separator.
    """
    if text is None:
        s = ""
    elif isinstance(text, (int, float)):
        return float(text)
    else:
        s = str(text)
    s = s.strip().replace("\u2212", "-").replace("\u00a0", " ").replace("\u202f", " ")
    if "/" in s:
        s = s.split("/", 1)[0]
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = re.sub(r"[^0-9,.+\- ]", "", s).replace(" ", "")
    if s in ("", "-", "+", ".", ","):
        if empty is not None:
            return empty
        raise InputError(f"expected a number for {field}, got {text!r}")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if decimal_comma or (len(parts) == 2 and len(parts[1]) != 3):
            s = s.replace(",", ".") if len(parts) == 2 else s.replace(",", "")
        else:
            s = s.replace(",", "")
    try:
        value = float(s)
    except ValueError as exc:
        raise InputError(f"expected a number for {field}, got {text!r}") from exc
    return -value if neg else value


def parse_datetime(
    text: str, tz: tzinfo, *, fmt: str | None = None, field: str = "time"
) -> datetime:
    """Parse a timestamp; naive values are interpreted in ``tz``. Returns UTC."""
    s = (text or "").strip()
    if not s:
        raise InputError(f"missing {field}")
    dt: datetime | None = None
    if fmt:
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError as exc:
            raise InputError(f"{field} {s!r} does not match --date-format {fmt!r}") from exc
    else:
        iso = s[:-1] + "+00:00" if s.endswith("Z") else s
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            for f in _DATE_FORMATS:
                try:
                    dt = datetime.strptime(s, f)
                    break
                except ValueError:
                    continue
    if dt is None:
        raise InputError(
            f"could not parse {field} {s!r}; pass --date-format, e.g. '%m/%d/%Y %H:%M'"
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def read_text(path: str | Path) -> str:
    """Read a file, detecting UTF-16 (MT5 reports) and UTF-8 BOMs."""
    p = Path(path)
    try:
        raw = p.read_bytes()
    except FileNotFoundError as exc:
        raise InputError(f"file not found: {p}") from exc
    except OSError as exc:
        raise InputError(f"cannot read {p}: {exc}") from exc
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if len(raw) > 4 and raw[1:4:2] == b"\x00\x00" and raw[0] != 0:
        return raw.decode("utf-16-le")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def looks_like_html(text: str) -> bool:
    head = text[:4096].lower()
    return "<html" in head or "<table" in text[:200000].lower()


_SEP_DIRECTIVE = re.compile(r'^\s*"?sep=(.)"?\s*$', re.IGNORECASE)
_DELIMITERS = (",", ";", "\t")


def _count_delimiters_outside_quotes(line: str) -> dict[str, int]:
    counts = dict.fromkeys(_DELIMITERS, 0)
    quoted = False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch in counts:
            counts[ch] += 1
    return counts


def read_csv_rows(text: str) -> tuple[list[list[str]], str]:
    """Split CSV text into rows, sniffing the delimiter. Lines starting with '#' are comments.

    An Excel ``sep=;`` directive on the first non-comment line is honoured and dropped.
    Otherwise the delimiter is the one that appears most often on the first data line
    outside double quotes, so commas inside quoted header cells are not counted.
    """
    raw_lines = text.splitlines()
    # Drop a leading Excel sep= directive before comment filtering so it never becomes a header.
    delimiter: str | None = None
    if raw_lines:
        first_nonempty = next((ln for ln in raw_lines if ln.strip()), "")
        directive = _SEP_DIRECTIVE.match(first_nonempty)
        if directive:
            delimiter = directive.group(1)
            # Remove the first occurrence of that physical line.
            for i, ln in enumerate(raw_lines):
                if ln.strip():
                    del raw_lines[i]
                    break

    lines = [ln for ln in raw_lines if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        raise InputError("the file is empty")
    if delimiter is None:
        counts = _count_delimiters_outside_quotes(lines[0])
        if any(counts.values()):
            delimiter = max(counts, key=lambda d: counts[d])
        else:
            sample = "\n".join(lines[:20])
            try:
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
            except csv.Error:
                delimiter = ","
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
    rows = [[c.strip() for c in r] for r in rows if any(c.strip() for c in r)]
    return rows, delimiter


def norm(header: str) -> str:
    return re.sub(r"\s+", " ", header.strip().lower())


class _TableExtractor(HTMLParser):
    """Collect every <tr> as a list of cell texts, expanding colspan."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._span = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._finish_row()
            self._row = []
        elif tag in ("td", "th"):
            self._finish_cell()
            if self._row is None:
                self._row = []
            self._cell = []
            span = dict(attrs).get("colspan") or "1"
            self._span = int(span) if span.isdigit() and int(span) > 0 else 1
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._finish_cell()
        elif tag in ("tr", "table"):
            self._finish_row()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def _finish_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._row.append(text)
            self._row.extend([""] * (self._span - 1))
        self._cell = None
        self._span = 1

    def _finish_row(self) -> None:
        self._finish_cell()
        if self._row is not None and any(self._row):
            self.rows.append(self._row)
        self._row = None

    def close(self) -> None:
        super().close()
        self._finish_row()


def html_rows(text: str) -> list[list[str]]:
    parser = _TableExtractor()
    parser.feed(text)
    parser.close()
    return parser.rows
