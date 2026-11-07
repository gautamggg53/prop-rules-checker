from __future__ import annotations

from datetime import datetime, timezone

import pytest

from prop_rules_checker import InputError, detect_format, load_trades
from prop_rules_checker.parsers.common import (
    get_tz,
    parse_datetime,
    parse_number,
    read_text,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 234.56", 1234.56),
        ("1,234.56", 1234.56),
        ("1.234,56", 1234.56),
        ("-1\u00a0250.00", -1250),
        ("(12.50)", -12.5),
        ("\u221242", -42),
        ("$1,000", 1000),
        ("0.10 Lots", 0.1),
        ("2 / 2", 2),
        ("1,5", 1.5),
        ("1,500", 1500),
        ("+3", 3),
        ("12", 12),
        (7, 7.0),
    ],
)
def test_parse_number(text, expected):
    assert parse_number(text) == pytest.approx(expected)


def test_parse_number_decimal_comma_and_errors():
    assert parse_number("1,500", decimal_comma=True) == 1.5
    assert parse_number("", empty=0.0) == 0.0
    with pytest.raises(InputError):
        parse_number("")
    with pytest.raises(InputError):
        parse_number("abc")
    with pytest.raises(InputError):
        parse_number("1.2.3")


def test_parse_datetime_variants():
    tz = get_tz("+02:00")
    assert parse_datetime("2026.03.02 10:00", tz) == datetime(2026, 3, 2, 8, tzinfo=timezone.utc)
    assert parse_datetime("2026-03-02T10:00:00Z", tz).hour == 10
    assert parse_datetime("02/03/2026 10:00:00.5", tz).day == 2  # day-first
    assert parse_datetime("03/02/2026 10:00", tz, fmt="%m/%d/%Y %H:%M").day == 2
    with pytest.raises(InputError):
        parse_datetime("yesterday", tz)
    with pytest.raises(InputError):
        parse_datetime("", tz)
    with pytest.raises(InputError):
        parse_datetime("2026-03-02", tz, fmt="%d.%m.%Y")


def test_get_tz():
    assert get_tz("UTC") is timezone.utc
    assert get_tz("GMT-3:30").utcoffset(None).total_seconds() == -3.5 * 3600
    assert get_tz("Europe/London") is not None
    with pytest.raises(InputError):
        get_tz("Mars/Olympus")


def test_read_text_encodings(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes(b"\xef\xbb\xbfclose_time,pnl\n")
    assert read_text(p).startswith("close_time")
    p.write_bytes("close_time,pnl\n".encode("utf-16-le"))
    assert read_text(p).startswith("close_time")
    p.write_bytes(b"caf\xe9\n")
    assert read_text(p) == "caf\u00e9\n"
    with pytest.raises(InputError):
        read_text(tmp_path / "missing.csv")


@pytest.mark.parametrize(
    ("name", "fmt", "count"),
    [
        ("synthetic_mt4_statement.htm", "mt4", 6),
        ("synthetic_mt5_report.html", "mt5", 4),
        ("synthetic_ctrader_history.csv", "ctrader", 3),
        ("synthetic_tradingview_list_of_trades.csv", "tradingview", 2),
        ("synthetic_tradingview_list_of_trades_legacy.csv", "tradingview", 2),
        ("synthetic_tradingview_paper_balance_history.csv", "tradingview-paper", 3),
        ("synthetic_generic.csv", "generic", 3),
    ],
)
def test_detect_and_load(fixtures, name, fmt, count):
    assert detect_format(read_text(fixtures / name)) == fmt
    history = load_trades(fixtures / name)
    assert history.format == fmt
    assert len(history) == count


def test_mt4_details(fixtures):
    h = load_trades(fixtures / "synthetic_mt4_statement.htm", source_tz="+02:00")
    first = h.trades[0]
    assert (first.id, first.symbol, first.side, first.volume) == ("1000002", "EURUSD", "buy", 1.0)
    assert first.pnl == pytest.approx(413.0)
    assert first.open_time == datetime(2026, 3, 2, 8, 15, tzinfo=timezone.utc)
    swap_trade = h.trades[1]
    assert swap_trade.pnl == pytest.approx(-1250 - 14 - 12.40)
    assert sum(t.pnl for t in h) == pytest.approx(-1454.85)  # matches statement Closed P/L
    assert any("cancelled" in n for n in h.notes)
    assert any("100,000.00" in n for n in h.notes)


def test_mt5_utf16_positions_only(fixtures):
    h = load_trades(fixtures / "synthetic_mt5_report.html")
    assert [t.id for t in h] == ["5001", "5002", "5003", "5004"]
    assert h.trades[1].pnl == pytest.approx(-1127.0)
    assert h.trades[2].pnl == pytest.approx(750 - 10.5 - 9.75)
    assert h.trades[0].volume == 2


def test_mt_csv_variants(tmp_path):
    mt4 = tmp_path / "mt4.csv"
    mt4.write_text(
        "Ticket;Open Time;Type;Size;Item;Price;S / L;T / P;Close Time;Price;"
        "Commission;Taxes;Swap;Profit\n"
        "1;2026.03.02 10:00;buy;0,50;eurusd;1,08;0;0;2026.03.02 11:00;1,09;-3,5;0;0;"
        "50,25\n"
    )
    h = load_trades(mt4)
    assert h.format == "mt4" and h.trades[0].volume == 0.5
    assert h.trades[0].pnl == pytest.approx(46.75)
    mt5 = tmp_path / "mt5.csv"
    mt5.write_text(
        "Time,Position,Symbol,Type,Volume,Price,S / L,T / P,Time,Price,Commission,"
        "Swap,Profit\n2026.03.02 10:00,9,EURUSD,sell,1,1.1,,,2026.03.02 12:00,1.09,"
        "-7,0,100\n"
    )
    h = load_trades(mt5)
    assert h.format == "mt5" and h.trades[0].pnl == 93


def test_mt_errors(tmp_path):
    p = tmp_path / "x.html"
    p.write_text("<html><table><tr><td>Closed Transactions:</td></tr></table></html>")
    with pytest.raises(InputError, match="Closed Transactions"):
        load_trades(p)
    p.write_text("<html><table><tr><td>Positions</td></tr><tr><td>x</td></tr></table></html>")
    with pytest.raises(InputError, match="not a recognised"):
        load_trades(p)
    with pytest.raises(InputError, match="Positions table"):
        load_trades(p, "mt5")


def test_ctrader_header_timezone_and_net(fixtures):
    h = load_trades(fixtures / "synthetic_ctrader_history.csv")
    t = h.trades[0]
    assert t.open_time == datetime(2026, 3, 2, 8, 15, 0, 120000, tzinfo=timezone.utc)
    assert t.pnl == pytest.approx(381.10)
    assert t.volume == 1.0


def test_ctrader_gross_fallback_and_errors(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text(
        "Symbol,Opening Direction,Closing Time,Closing Quantity,Commission,Swap,Gross USD"
        ",Net USD\nEURUSD,Sell,2026-03-02 10:00,10000,-1,-2,10,7\n,,,,,,,Total\n"
    )
    h = load_trades(p)
    assert h.trades[0].pnl == 7 and h.trades[0].side == "sell"
    assert any("Net USD" in n for n in h.notes)
    assert any("Lots" in n for n in h.notes)
    assert h.trades[0].open_time is None
    p.write_text("Symbol,Opening Direction,Closing Time,Gross\nEURUSD,Buy,2026-03-02 10:00,10\n")
    assert load_trades(p).trades[0].pnl == 10
    p.write_text("Symbol,Opening Direction,Opening Time\nEURUSD,Buy,2026-03-02 10:00\n")
    with pytest.raises(InputError, match="Closing time"):
        load_trades(p)
    p.write_text("Symbol,Opening Direction,Closing Time\nEURUSD,Buy,2026-03-02 10:00\n")
    with pytest.raises(InputError, match="Net or Gross"):
        load_trades(p)


def test_tradingview(fixtures):
    h = load_trades(fixtures / "synthetic_tradingview_list_of_trades.csv", symbol="eurusd")
    by_id = {t.id: t for t in h}
    assert set(by_id) == {"1", "2"}  # trade 3 is still open
    assert by_id["2"].side == "sell" and by_id["2"].pnl == -400 and by_id["2"].mae == -650
    assert by_id["1"].symbol == "EURUSD"
    legacy = load_trades(fixtures / "synthetic_tradingview_list_of_trades_legacy.csv")
    assert legacy.trades[0].symbol == "UNKNOWN" and legacy.trades[0].mae == -30
    assert any("--symbol" in n for n in legacy.notes)


def test_tradingview_missing_columns(tmp_path):
    p = tmp_path / "tv.csv"
    p.write_text("Trade #,Type,Price\n1,Entry long,1\n")
    with pytest.raises(InputError, match="Date/Time"):
        load_trades(p)


def test_tradingview_paper(fixtures, tmp_path):
    h = load_trades(fixtures / "synthetic_tradingview_paper_balance_history.csv")
    assert [t.kind for t in h] == ["trade", "adjustment", "trade"]
    assert h.trades[0].symbol == "EURUSD" and h.trades[2].side == "sell"
    assert h.volume_unit == "units"
    p = tmp_path / "paper.csv"
    p.write_text("Time,Balance Before,Balance After,Action\n2026-03-02 10:00,100,90,Something\n")
    assert load_trades(p, "tradingview-paper").trades[0].pnl == -10
    p.write_text("Time,Action\n2026-03-02 10:00,Something\n")
    with pytest.raises(InputError, match="paper"):
        load_trades(p, "tradingview-paper")


def test_generic_variants(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text(
        "Ticket,Instrument,Direction,Lots,Entry_Time,Exit_Time,Profit,Commission,Swap,"
        "Kind\n7,eurusd,short,1,2026-03-02 09:00,2026-03-02 10:00,100,-5,-1,trade\n"
        "8,,,,,2026-03-02 11:00,-3,,,adjustment\n"
    )
    h = load_trades(p, source_tz="Europe/Berlin")
    a, b = h.trades
    assert a.side == "sell" and a.pnl == 94 and a.close_time.hour == 9
    assert b.kind == "adjustment" and b.open_time is None
    p.write_text("close_time,pnl,kind\n2026-03-02 10:00,1,bogus\n")
    with pytest.raises(InputError, match="kind"):
        load_trades(p)
    p.write_text("close_time,pnl\n2026-03-02 10:00,abc\n")
    with pytest.raises(InputError, match="pnl on row 2"):
        load_trades(p)
    p.write_text("open_time,close_time,pnl\n2026-03-02 11:00,2026-03-02 10:00,1\n")
    with pytest.raises(InputError, match="closes before it opens"):
        load_trades(p)
    with pytest.raises(InputError, match="needs at least"):
        p.write_text("close_time,foo\n2026-03-02 10:00,1\n")
        load_trades(p, "generic")


def test_load_errors(tmp_path, fixtures):
    p = tmp_path / "e.csv"
    p.write_text("")
    with pytest.raises(InputError, match="empty"):
        load_trades(p)
    p.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(InputError, match="could not detect"):
        load_trades(p)
    with pytest.raises(InputError, match="unknown format"):
        load_trades(fixtures / "synthetic_generic.csv", "excel")
    with pytest.raises(InputError, match="expects a CSV"):
        load_trades(fixtures / "synthetic_mt4_statement.htm", "ctrader")
    p.write_text("close_time,pnl\n")
    with pytest.raises(InputError, match="no data rows"):
        load_trades(p)
    p.write_text("# only a comment\n")
    with pytest.raises(InputError, match="empty"):
        load_trades(p)
    p.write_text("Time,Position,Symbol,Type,Volume,Price,Time,Price,Profit\n")
    with pytest.raises(InputError, match="no closed trades"):
        load_trades(p)
    h = load_trades(fixtures / "synthetic_generic.csv", symbol="X")
    assert any("--symbol" in n for n in h.notes)


def test_csv_excel_sep_directive_is_honoured_and_dropped(tmp_path):
    from prop_rules_checker.parsers.common import read_csv_rows

    rows, delim = read_csv_rows("sep=;\nclose_time;pnl;symbol\n2024-01-02 10:00;-12,5;EURUSD\n")
    assert delim == ";"
    assert rows == [
        ["close_time", "pnl", "symbol"],
        ["2024-01-02 10:00", "-12,5", "EURUSD"],
    ]
    # Quoted, upper-case and tab variants seen in the wild.
    assert read_csv_rows('"SEP=,"\na,b\n')[0] == [["a", "b"]]
    assert read_csv_rows("sep=\t\na\tb\n") == ([["a", "b"]], "\t")
    # sep= before a comment line, then a real header.
    rows, delim = read_csv_rows("sep=;\n# broker export\nclose_time;pnl\n2024-01-02 10:00;1,5\n")
    assert delim == ";" and rows[0] == ["close_time", "pnl"]
    p = tmp_path / "sep.csv"
    p.write_text("sep=;\nclose_time;pnl\n2026-03-02 10:00;1,500\n")
    assert load_trades(p).trades[0].pnl == 1.5


def test_csv_delimiter_inside_quoted_header_is_ignored():
    from prop_rules_checker.parsers.common import read_csv_rows

    # Two commas inside quotes but only one real delimiter (;).
    text = '"Profit, USD";"Close time, UTC"\n"1,5";2024-01-02\n'
    rows, delim = read_csv_rows(text)
    assert delim == ";"
    assert rows == [["Profit, USD", "Close time, UTC"], ["1,5", "2024-01-02"]]


def test_semicolon_csv_uses_decimal_comma(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("close_time;pnl\n2026-03-02 10:00;1,500\n")
    assert load_trades(p).trades[0].pnl == 1.5
