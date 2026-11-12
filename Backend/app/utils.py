
from datetime import date, datetime
from uuid import UUID

from bson import ObjectId
from fastapi import HTTPException


def parse_uuid(value: str, field_name: str = "id") -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}.",
        )


def parse_object_id(value: str, field_name: str = "id"):
    text = str(value)
    if len(text) == 24 and all(char in "0123456789abcdefABCDEF" for char in text):
        try:
            return ObjectId(text)
        except Exception:
            pass
    return parse_uuid(value, field_name)


def serialize_value(value):
    if isinstance(value, ObjectId):
        return str(value)

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            ("id" if key == "_id" else key): serialize_value(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [serialize_value(item) for item in value]

    return value


def serialize_model(model, exclude: set[str] | None = None) -> dict:
    if model is None:
        return {}

    excluded = exclude or set()

    result = {}
    for column in model.__table__.columns:
        key = column.name

        if key in excluded:
            continue

        result[key] = serialize_value(getattr(model, key))

    if "id" in result:
        result["id"] = str(result["id"])

    return result


def serialize_document(document, exclude: set[str] | None = None):
    if document is None:
        return None

    if hasattr(document, "__table__"):
        return serialize_model(document, exclude)

    if isinstance(document, dict):
        serialized = {}
        for key, value in document.items():
            if exclude is not None and key in exclude:
                continue
            serialized_key = "id" if key == "_id" else key
            serialized[serialized_key] = serialize_value(value)
        return serialized

    return serialize_value(document)
