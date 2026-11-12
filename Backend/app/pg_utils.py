
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import inspect


def parse_uuid(value: str, field_name: str = "id") -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}.",
        )


def serialize_model(instance):
    if instance is None:
        return None

    mapper = inspect(instance.__class__)

    result = {}

    for column in mapper.columns:
        value = getattr(instance, column.key)

        if isinstance(value, UUID):
            value = str(value)

        result[column.key] = value

    return result
