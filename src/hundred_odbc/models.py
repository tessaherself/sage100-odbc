"""Typed records for the Sage 100 tables this package reads.

Field names are the Sage 100 column names in snake_case. Column names and
code values come from Sage's "File Layouts and Program Information" help:
  AR_Customer          https://help-sage100.na.sage.com/2018/FLOR/Content/File_Layouts/Accounts_Receivable/AR_Customer.htm
  SO_SalesOrderHeader  https://help-sage100.na.sage.com/2018/FLOR/Content/File_Layouts/Sales_Order/SO_SalesOrderHeader.htm
  SO_SalesOrderDetail  https://help-sage100.na.sage.com/2018/FLOR/Content/File_Layouts/Sales_Order/SO_SalesOrderDetail.htm
  CI_Item              https://help-sage100.na.sage.com/2018/FLOR/Content/File_Layouts/Common_Information/CI_Item.htm
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional

# SO_SalesOrderHeader.OrderStatus
ORDER_STATUS = {"N": "new", "O": "open", "H": "hold", "C": "closed"}
# SO_SalesOrderHeader.OrderType
ORDER_TYPE = {"S": "standard", "B": "back order", "M": "master", "R": "repeating", "Q": "quote", "P": "prospect"}


@dataclass(frozen=True)
class Customer:
    """One row of AR_Customer. Key: ARDivisionNo + CustomerNo."""

    ar_division_no: str
    customer_no: str
    customer_name: str
    address_line1: str
    city: str
    state: str
    zip_code: str
    telephone_no: str
    email_address: str
    credit_limit: Decimal
    current_balance: Decimal
    date_updated: Optional[date]

    @property
    def id(self) -> str:
        """The customer as Sage users write it, e.g. "01-AVNET"."""
        return f"{self.ar_division_no}-{self.customer_no}"


@dataclass(frozen=True)
class SalesOrderLine:
    """One row of SO_SalesOrderDetail. Key: SalesOrderNo + LineKey."""

    line_key: str
    item_code: str
    item_code_desc: str
    warehouse_code: str
    quantity_ordered: Decimal
    quantity_shipped: Decimal
    unit_price: Decimal
    extension_amt: Decimal


@dataclass(frozen=True)
class SalesOrder:
    """One row of SO_SalesOrderHeader plus its detail lines."""

    sales_order_no: str
    order_date: Optional[date]
    order_type: str
    order_status: str
    ar_division_no: str
    customer_no: str
    customer_po_no: str
    lines: List[SalesOrderLine] = field(default_factory=list)

    @property
    def customer_id(self) -> str:
        return f"{self.ar_division_no}-{self.customer_no}"

    @property
    def status(self) -> str:
        return ORDER_STATUS.get(self.order_status, self.order_status)


@dataclass(frozen=True)
class Item:
    """One row of CI_Item. Key: ItemCode."""

    item_code: str
    item_code_desc: str
    item_type: str
    product_line: str
    standard_unit_price: Decimal
    standard_unit_cost: Decimal
    total_quantity_on_hand: Decimal
    inactive: bool
    date_updated: Optional[date]
