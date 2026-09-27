"""Runs without Sage 100 and without pyodbc: a fake DB-API connection answers
each SELECT from canned rows keyed by table name, and records what ran."""
import datetime as dt
import re
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hundred_odbc import SageReader, connect  # noqa: E402
from hundred_odbc import reader as reader_mod  # noqa: E402


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self._rows = []

    def execute(self, sql, *params):
        self.conn.executed.append((sql, params))
        table = re.search(r"\bFROM\s+(\w+)", sql).group(1)
        cols, rows = self.conn.tables[table]
        if table == "SO_SalesOrderDetail":  # honour the IN list, like the driver would
            rows = [r for r in rows if r[0] in params]
        self.description = [(c, None, None, None, None, None, None) for c in cols]
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def close(self):
        self.conn.closed_cursors += 1


class FakeConnection:
    def __init__(self, tables):
        self.tables = tables
        self.executed = []
        self.closed_cursors = 0

    def cursor(self):
        return FakeCursor(self)


CUSTOMER_COLS = ["ARDivisionNo", "CustomerNo", "CustomerName", "AddressLine1", "City", "State", "ZipCode",
                 "TelephoneNo", "EmailAddress", "CreditLimit", "CurrentBalance", "DateUpdated"]
HEADER_COLS = ["SalesOrderNo", "OrderDate", "OrderType", "OrderStatus", "ARDivisionNo", "CustomerNo", "CustomerPONo"]
DETAIL_COLS = ["SalesOrderNo", "LineKey", "ItemCode", "ItemCodeDesc", "WarehouseCode", "QuantityOrdered",
               "QuantityShipped", "UnitPrice", "ExtensionAmt"]
ITEM_COLS = ["ItemCode", "ItemCodeDesc", "ItemType", "ProductLine", "StandardUnitPrice", "StandardUnitCost",
             "TotalQuantityOnHand", "InactiveItem", "DateUpdated"]


def tables():
    return {
        "AR_Customer": (CUSTOMER_COLS, [
            ("01", "AVNET   ", "Avnet Industries      ", "2131 Seventh Street", "Irvine", "CA", "92614",
             "(949) 555-0177", "ap@avnet.example", Decimal("25000.00"), 4812.4, dt.date(2026, 9, 22)),
        ]),
        "SO_SalesOrderHeader": (HEADER_COLS, [
            ("0001042", dt.datetime(2026, 9, 24), "S", "O", "01", "AVNET", "SHOP-5511"),
            ("0001043", dt.date(2026, 9, 27), "S", "N", "02", "BAYPOINT", ""),
        ]),
        "SO_SalesOrderDetail": (DETAIL_COLS, [
            ("0001042", "000002", "6655", "Stapler", "000", 1, 0, 19.95, 19.95),
            ("0001042", "000001", "1001-HON-H252", "Chair", "000", 4, 1, Decimal("129.50"), Decimal("518.00")),
            ("0001043", "000001", "2481-5-50", "Desk", "EST", 2, 0, 400, 800),
            ("0009999", "000001", "IGNORED", "Not asked for", "000", 1, 0, 1, 1),
        ]),
        "CI_Item": (ITEM_COLS, [
            ("1001-HON-H252", "HON Chair", "1", "FURN", Decimal("129.50"), Decimal("71.20"), 42, "N", None),
            ("OLD-1", "Retired", "1", "MISC", 0, 0, 0, "Y", "2019-01-02"),
        ]),
    }


class CustomerTests(unittest.TestCase):
    def test_maps_fields_strips_padding_and_types_money(self):
        conn = FakeConnection(tables())
        [c] = SageReader(conn).customers()
        self.assertEqual(c.id, "01-AVNET")
        self.assertEqual(c.customer_name, "Avnet Industries")
        self.assertEqual(c.credit_limit, Decimal("25000.00"))
        self.assertEqual(c.current_balance, Decimal("4812.4"))
        self.assertIsInstance(c.current_balance, Decimal)
        self.assertEqual(c.date_updated, dt.date(2026, 9, 22))

    def test_filters_use_a_parameter_and_an_odbc_date_escape(self):
        conn = FakeConnection(tables())
        SageReader(conn).customers(division="01", updated_since=dt.date(2026, 9, 20))
        sql, params = conn.executed[0]
        self.assertIn("FROM AR_Customer WHERE ARDivisionNo = ? AND DateUpdated >= {d '2026-09-20'}", sql)
        self.assertEqual(params, ("01",))

    def test_updated_since_rejects_strings(self):
        with self.assertRaises(TypeError):
            SageReader(FakeConnection(tables())).customers(updated_since="2026-01-01' OR 1=1 --")


class SalesOrderTests(unittest.TestCase):
    def test_open_orders_with_lines_in_line_key_order(self):
        conn = FakeConnection(tables())
        orders = SageReader(conn).open_sales_orders()
        self.assertEqual([o.sales_order_no for o in orders], ["0001042", "0001043"])
        first = orders[0]
        self.assertEqual(first.customer_id, "01-AVNET")
        self.assertEqual(first.status, "open")
        self.assertEqual(first.order_date, dt.date(2026, 9, 24))
        self.assertEqual([l.line_key for l in first.lines], ["000001", "000002"])
        self.assertEqual(first.lines[0].extension_amt, Decimal("518.00"))
        self.assertEqual(orders[1].status, "new")
        self.assertEqual(len(orders[1].lines), 1)

    def test_status_and_type_filters_are_parameters(self):
        conn = FakeConnection(tables())
        SageReader(conn).open_sales_orders(statuses=("N", "O", "H"))
        sql, params = conn.executed[0]
        self.assertIn("WHERE OrderStatus IN (?, ?, ?) AND OrderType IN (?)", sql)
        self.assertEqual(params, ("N", "O", "H", "S"))

    def test_detail_reads_only_the_orders_found_and_chunks_the_in_list(self):
        conn = FakeConnection(tables())
        old = reader_mod.IN_CHUNK
        reader_mod.IN_CHUNK = 1
        try:
            SageReader(conn).open_sales_orders()
        finally:
            reader_mod.IN_CHUNK = old
        detail = [(s, p) for s, p in conn.executed if "SO_SalesOrderDetail" in s]
        self.assertEqual([p for _, p in detail], [("0001042",), ("0001043",)])

    def test_no_orders_means_no_detail_query(self):
        t = tables()
        t["SO_SalesOrderHeader"] = (HEADER_COLS, [])
        conn = FakeConnection(t)
        self.assertEqual(SageReader(conn).open_sales_orders(), [])
        self.assertFalse(any("SO_SalesOrderDetail" in s for s, _ in conn.executed))


class ItemTests(unittest.TestCase):
    def test_active_filter_and_mapping(self):
        conn = FakeConnection(tables())
        items = SageReader(conn).items()
        self.assertIn("WHERE InactiveItem <> 'Y'", conn.executed[0][0])
        chair = items[0]
        self.assertEqual(chair.standard_unit_price, Decimal("129.50"))
        self.assertEqual(chair.total_quantity_on_hand, Decimal(42))
        self.assertFalse(chair.inactive)
        self.assertIsNone(chair.date_updated)
        self.assertTrue(items[1].inactive)
        self.assertEqual(items[1].date_updated, dt.date(2019, 1, 2))

    def test_include_inactive_drops_the_filter(self):
        conn = FakeConnection(tables())
        SageReader(conn).items(include_inactive=True)
        self.assertNotIn("WHERE", conn.executed[0][0])


class SafetyTests(unittest.TestCase):
    def test_every_statement_is_a_select_and_every_cursor_is_closed(self):
        conn = FakeConnection(tables())
        r = SageReader(conn)
        r.customers(), r.open_sales_orders(), r.items()
        self.assertTrue(conn.executed)
        for sql, _ in conn.executed:
            self.assertTrue(sql.startswith("SELECT "), sql)
        self.assertEqual(conn.closed_cursors, len(conn.executed))


class ConnectTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        fake = types.ModuleType("pyodbc")
        fake.connect = lambda s, **kw: self.calls.append((s, kw)) or "conn"
        self._old = sys.modules.get("pyodbc")
        sys.modules["pyodbc"] = fake

    def tearDown(self):
        if self._old is None:
            sys.modules.pop("pyodbc", None)
        else:
            sys.modules["pyodbc"] = self._old

    def test_dsn_string_upper_cases_company_and_user(self):
        self.assertEqual(connect(company="abc", user="jsmith", password="pw"), "conn")
        self.assertEqual(self.calls, [("DSN=SOTAMAS90;Company=ABC;UID=JSMITH;PWD=pw", {"autocommit": True})])

    def test_connection_string_is_passed_through(self):
        s = "Driver={MAS 90 4.0 ODBC Driver};Company=ABC;UID=X;PWD=y;Directory=C:\\Sage\\MAS90"
        connect(connection_string=s)
        self.assertEqual(self.calls[0][0], s)


if __name__ == "__main__":
    unittest.main()
