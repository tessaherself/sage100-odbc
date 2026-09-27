"""Read-only access to Sage 100 through the ProvideX ODBC driver.

The reader takes any DB-API connection, so tests pass a fake one and
production passes pyodbc's. It only ever issues SELECT statements.

SQL follows the ProvideX dialect: ODBC date escapes ({d 'YYYY-MM-DD'}),
filters on key columns, and no JOIN keyword (orders and lines are two
key-based reads). Sources:
  https://kb.dataself.com/ds/providex-sql-syntax
  https://stackoverflow.com/questions/77240191
  https://communityhub.sage.com/us/sage100/f/business-object-interface/158904/connection-string-to-silent-odbc-dsn-using-providex-odbc-driver-is-forcing-connection-to-default-to-sotamas90-dsn/412821
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from .models import Customer, Item, SalesOrder, SalesOrderLine

OPEN_STATUSES = ("N", "O")  # new and open; add "H" to include orders on hold
IN_CHUNK = 200  # order numbers per IN (...) list


def connect(
    dsn: str = "SOTAMAS90",
    company: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    connection_string: Optional[str] = None,
):
    """Open a pyodbc connection to Sage 100.

    Pass `connection_string` for a DSN-less connection, e.g.
    "Driver={MAS 90 4.0 ODBC Driver};Company=ABC;UID=JSMITH;PWD=...;Directory=...\\MAS90".
    Sage recreates the SOTAMAS90 DSN on every start, so for unattended use a
    DSN-less string or your own "silent" DSN is the stable choice.
    """
    import pyodbc  # imported here so the package and its tests work without it

    if connection_string is None:
        parts = [f"DSN={dsn}"]
        if company:
            parts.append(f"Company={company.upper()}")
        if user:
            parts.append(f"UID={user.upper()}")
        if password is not None:
            parts.append(f"PWD={password}")
        connection_string = ";".join(parts)
    return pyodbc.connect(connection_string, autocommit=True)


class SageReader:
    """Customers, open sales orders and items from one Sage 100 company."""

    def __init__(self, connection: Any):
        self._conn = connection

    def customers(self, division: Optional[str] = None, updated_since: Optional[dt.date] = None) -> List[Customer]:
        where: List[str] = []
        params: List[Any] = []
        if division is not None:
            where.append("ARDivisionNo = ?")
            params.append(division)
        if updated_since is not None:
            where.append(f"DateUpdated >= {_date_literal(updated_since)}")
        sql = (
            "SELECT ARDivisionNo, CustomerNo, CustomerName, AddressLine1, City, State, ZipCode, "
            "TelephoneNo, EmailAddress, CreditLimit, CurrentBalance, DateUpdated FROM AR_Customer"
            + _where(where)
        )
        return [
            Customer(
                ar_division_no=_s(r["ARDivisionNo"]),
                customer_no=_s(r["CustomerNo"]),
                customer_name=_s(r["CustomerName"]),
                address_line1=_s(r["AddressLine1"]),
                city=_s(r["City"]),
                state=_s(r["State"]),
                zip_code=_s(r["ZipCode"]),
                telephone_no=_s(r["TelephoneNo"]),
                email_address=_s(r["EmailAddress"]),
                credit_limit=_d(r["CreditLimit"]),
                current_balance=_d(r["CurrentBalance"]),
                date_updated=_date(r["DateUpdated"]),
            )
            for r in self._select(sql, params)
        ]

    def open_sales_orders(
        self, statuses: Sequence[str] = OPEN_STATUSES, order_types: Sequence[str] = ("S",)
    ) -> List[SalesOrder]:
        """Orders whose OrderStatus is in `statuses` (default new and open),
        standard orders only unless `order_types` says otherwise, with lines."""
        sql = (
            "SELECT SalesOrderNo, OrderDate, OrderType, OrderStatus, ARDivisionNo, CustomerNo, CustomerPONo "
            "FROM SO_SalesOrderHeader"
            + _where([f"OrderStatus IN ({_marks(statuses)})", f"OrderType IN ({_marks(order_types)})"])
        )
        headers = list(self._select(sql, list(statuses) + list(order_types)))
        lines = self._lines([_s(h["SalesOrderNo"]) for h in headers])
        return [
            SalesOrder(
                sales_order_no=_s(h["SalesOrderNo"]),
                order_date=_date(h["OrderDate"]),
                order_type=_s(h["OrderType"]),
                order_status=_s(h["OrderStatus"]),
                ar_division_no=_s(h["ARDivisionNo"]),
                customer_no=_s(h["CustomerNo"]),
                customer_po_no=_s(h["CustomerPONo"]),
                lines=lines.get(_s(h["SalesOrderNo"]), []),
            )
            for h in headers
        ]

    def items(self, include_inactive: bool = False, updated_since: Optional[dt.date] = None) -> List[Item]:
        where: List[str] = []
        if not include_inactive:
            where.append("InactiveItem <> 'Y'")
        if updated_since is not None:
            where.append(f"DateUpdated >= {_date_literal(updated_since)}")
        sql = (
            "SELECT ItemCode, ItemCodeDesc, ItemType, ProductLine, StandardUnitPrice, StandardUnitCost, "
            "TotalQuantityOnHand, InactiveItem, DateUpdated FROM CI_Item" + _where(where)
        )
        return [
            Item(
                item_code=_s(r["ItemCode"]),
                item_code_desc=_s(r["ItemCodeDesc"]),
                item_type=_s(r["ItemType"]),
                product_line=_s(r["ProductLine"]),
                standard_unit_price=_d(r["StandardUnitPrice"]),
                standard_unit_cost=_d(r["StandardUnitCost"]),
                total_quantity_on_hand=_d(r["TotalQuantityOnHand"]),
                inactive=_s(r["InactiveItem"]) == "Y",
                date_updated=_date(r["DateUpdated"]),
            )
            for r in self._select(sql, [])
        ]

    def _lines(self, order_nos: List[str]) -> Dict[str, List[SalesOrderLine]]:
        out: Dict[str, List[SalesOrderLine]] = {}
        for i in range(0, len(order_nos), IN_CHUNK):
            chunk = order_nos[i : i + IN_CHUNK]
            sql = (
                "SELECT SalesOrderNo, LineKey, ItemCode, ItemCodeDesc, WarehouseCode, QuantityOrdered, "
                f"QuantityShipped, UnitPrice, ExtensionAmt FROM SO_SalesOrderDetail WHERE SalesOrderNo IN ({_marks(chunk)})"
            )
            for r in self._select(sql, chunk):
                out.setdefault(_s(r["SalesOrderNo"]), []).append(
                    SalesOrderLine(
                        line_key=_s(r["LineKey"]),
                        item_code=_s(r["ItemCode"]),
                        item_code_desc=_s(r["ItemCodeDesc"]),
                        warehouse_code=_s(r["WarehouseCode"]),
                        quantity_ordered=_d(r["QuantityOrdered"]),
                        quantity_shipped=_d(r["QuantityShipped"]),
                        unit_price=_d(r["UnitPrice"]),
                        extension_amt=_d(r["ExtensionAmt"]),
                    )
                )
        for rows in out.values():
            rows.sort(key=lambda l: l.line_key)
        return out

    def _select(self, sql: str, params: Iterable[Any]) -> Iterator[Dict[str, Any]]:
        assert sql.lstrip().upper().startswith("SELECT "), "this package is read-only"
        cur = self._conn.cursor()
        try:
            cur.execute(sql, *list(params)) if params else cur.execute(sql)
            names = [d[0] for d in cur.description]
            for row in cur.fetchall():
                yield dict(zip(names, row))
        finally:
            cur.close()


def _where(clauses: List[str]) -> str:
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


def _marks(values: Sequence[Any]) -> str:
    if not values:
        raise ValueError("empty IN list")
    return ", ".join("?" for _ in values)


def _date_literal(d: dt.date) -> str:
    # ProvideX wants an ODBC date escape. isoformat() of a real date object
    # cannot carry anything but digits and dashes, so this is not injectable.
    if not isinstance(d, dt.date):
        raise TypeError("updated_since must be a datetime.date")
    return "{d '" + d.strftime("%Y-%m-%d") + "'}"


def _s(v: Any) -> str:
    return "" if v is None else str(v).rstrip()


def _d(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal(0)
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _date(v: Any) -> Optional[dt.date]:
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])
