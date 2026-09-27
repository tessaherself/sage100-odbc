"""Read Sage 100 through its ODBC driver and get typed records back."""
from .models import Customer, Item, SalesOrder, SalesOrderLine
from .reader import SageReader, connect

__all__ = ["connect", "SageReader", "Customer", "SalesOrder", "SalesOrderLine", "Item"]
__version__ = "0.1.0"
