"""
Django admin registrations for the Inventory Module.

Split per owning team for the same reason the models are (four teams, one
file, constant conflicts). Importing the submodules here is what runs their
`@admin.register` decorators.

Columns stay dense enough to seed and audit test data without reaching for the
shell or Postman.
"""

from . import catalog, location, stock, vendor  # noqa: F401

__all__ = ["catalog", "location", "stock", "vendor"]
