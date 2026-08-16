"""Serializers for the book catalog. **Owner: Team B.**"""

from rest_framework import serializers

from ..models import Book


class BookSerializer(serializers.ModelSerializer):
    """Catalog-level serializer — no stock information."""

    class Meta:
        model = Book
        fields = [
            "id",
            "title",
            "isbn",
            "min_stock",
            "low_selling",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["low_selling", "created_at", "updated_at"]
