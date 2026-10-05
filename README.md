# hundred-odbc

Read Sage 100 (formerly MAS 90 / MAS 200) from Python through the ProvideX ODBC
driver that ships with Sage 100, and get typed records back: customers, open
sales orders with their lines, and items. Read-only by design: it only runs
`SELECT`. To write to Sage 100, use the Business Object Interface.

Install from GitHub (not on PyPI yet):

```
pip install "hundred-odbc[odbc] @ git+https://github.com/tessaherself/sage100-odbc"
```

## Use

Runs on Windows, on a machine that has the "MAS 90 4.0 ODBC Driver" with the
same bitness as your Python (Sage 100 2026 is 64-bit only).

```python
import datetime as dt
from hundred_odbc import SageReader, connect

conn = connect(company="ABC", user="JSMITH", password="...")   # DSN=SOTAMAS90
# or, for unattended jobs (Sage recreates SOTAMAS90 on every start):
# conn = connect(connection_string=r"Driver={MAS 90 4.0 ODBC Driver};Company=ABC;"
#                r"UID=JSMITH;PWD=...;Directory=C:\Sage\Sage 100 Standard\MAS90;StripTrailingSpaces=1")

sage = SageReader(conn)
for c in sage.customers(updated_since=dt.date(2026, 9, 1)):
    print(c.id, c.customer_name, c.current_balance)

for order in sage.open_sales_orders():            # OrderStatus N or O, standard orders
    print(order.sales_order_no, order.customer_id, [l.item_code for l in order.lines])

stock = {i.item_code: i.total_quantity_on_hand for i in sage.items()}
```

| Method | Table(s) | Filters |
|---|---|---|
| `customers()` | `AR_Customer` | `division`, `updated_since` |
| `open_sales_orders()` | `SO_SalesOrderHeader`, `SO_SalesOrderDetail` | `statuses` (default `N`, `O`), `order_types` (default `S`) |
| `items()` | `CI_Item` | `include_inactive`, `updated_since` |

Field names are the Sage 100 column names in snake_case (`CustomerNo` becomes
`customer_no`). Money and quantities are `Decimal`, dates are `datetime.date`,
fixed-width text is right-trimmed.

## Test

No Sage 100 and no pyodbc needed; the tests use a fake DB-API connection.

```
python3 -m unittest discover -s tests -v
```

## Sources

Table and column names: Sage 100 "File Layouts and Program Information"
([AR_Customer](https://help-sage100.na.sage.com/2018/FLOR/Content/File_Layouts/Accounts_Receivable/AR_Customer.htm),
[SO_SalesOrderHeader](https://help-sage100.na.sage.com/2018/FLOR/Content/File_Layouts/Sales_Order/SO_SalesOrderHeader.htm),
[SO_SalesOrderDetail](https://help-sage100.na.sage.com/2018/FLOR/Content/File_Layouts/Sales_Order/SO_SalesOrderDetail.htm),
[CI_Item](https://help-sage100.na.sage.com/2018/FLOR/Content/File_Layouts/Common_Information/CI_Item.htm)).
SQL dialect: [ProvideX SQL syntax notes](https://kb.dataself.com/ds/providex-sql-syntax).

## Need writes, or no Windows box?

[Hundred](https://hundredapi.com/for-odbc-users.html?utm_source=sage100-odbc&utm_medium=readme&utm_campaign=g6-package) is a planned hosted REST API for Sage 100, with reads and writes through Sage's own business logic. It is not built yet; this package is the part that exists today. [This package vs. the planned API, and early access](https://hundredapi.com/for-odbc-users.html?utm_source=sage100-odbc&utm_medium=readme&utm_campaign=g6-package).

## License

MIT. Not affiliated with, endorsed or sponsored by The Sage Group plc.
