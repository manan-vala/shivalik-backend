"""Book catalog viewset. **Owner: Team B.**"""

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from staff_auth.permissions import IsApprovedStaff

from ..models import Book
from ..serializers import BookSerializer
from .stock import BookStockActionsMixin


class BookViewSet(BookStockActionsMixin, viewsets.ModelViewSet):
    """
    Manages the book catalog plus its stock lifecycle.

    CRUD and the catalog schema live here; the ledger reads and stock
    mutations come from `BookStockActionsMixin` in `views/stock.py`:

        * `/books/register/`                       explicit registration alias
        * `/books/inventory/`                       joined ledger rows (deprecated alias)
        * `/books/{id}/stock-in|out/`                stock mutations
        * `/books/{id}/history|in-entries|out-entries/`  the movement log
    """

    queryset = Book.objects.select_related(
        "default_warehouse", "default_section", "default_rack",
    ).all()
    serializer_class = BookSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]
    filterset_fields = ["class_level", "board", "subject"]
    search_fields = ["title", "isbn"]

    # -- Section 4.B.2 : POST /books/register/ ----------------------------
    @action(detail=False, methods=["post"], url_path="register")
    def register(self, request, *args, **kwargs):
        """
        Explicit alias for POST /books/ — kept because the spec lists it.

        Delegates to `create()` rather than reimplementing it (finding `L-7`),
        so any future `perform_create` logic applies to both routes. `create()`
        already returns 201 with the Location header.
        """
        return self.create(request, *args, **kwargs)
