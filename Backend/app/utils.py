from bson import ObjectId
from fastapi import HTTPException


def parse_object_id(value: str, field_name: str = "id") -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}.")
    return ObjectId(value)


def serialize_document(document: dict | None) -> dict | None:
    if document is None:
        return None
    result = {}
    for key, value in document.items():
        if key == "_id":
            result["id"] = str(value)
        elif isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, list):
            result[key] = [
                str(item) if isinstance(item, ObjectId) else item
                for item in value
            ]
        else:
            result[key] = value
    return result
