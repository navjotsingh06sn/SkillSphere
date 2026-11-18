import logging
from datetime import datetime, timezone

from app.config import settings

logger = logging.getLogger(__name__)

try:
    import cloudinary
    from cloudinary import api, utils
except ImportError:  # The application still starts before optional Cloudinary setup.
    cloudinary = None
    api = None
    utils = None


class CloudinaryUnavailable(RuntimeError):
    pass


def configure_cloudinary() -> bool:
    values = (settings.cloudinary_cloud_name, settings.cloudinary_api_key, settings.cloudinary_api_secret)
    if not all(value.strip() for value in values):
        logger.warning("Cloudinary credentials are incomplete; video recording uploads are disabled.")
        return False
    if cloudinary is None:
        logger.error("Cloudinary SDK is not installed; install Backend requirements.")
        return False
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name.strip(),
        api_key=settings.cloudinary_api_key.strip(),
        api_secret=settings.cloudinary_api_secret.strip(),
        secure=True,
    )
    return True


def _require_cloudinary():
    if not configure_cloudinary():
        raise CloudinaryUnavailable("Cloudinary video storage is not configured.")


def signed_upload_parameters(public_id: str, timestamp: int) -> str:
    _require_cloudinary()
    params = {"public_id": public_id, "timestamp": timestamp, "type": "authenticated"}
    return utils.api_sign_request(params, settings.cloudinary_api_secret.strip())


def fetch_video_resource(public_id: str) -> dict:
    _require_cloudinary()
    return api.resource(
        public_id, resource_type="video", type="authenticated",
    )


def signed_video_download_url(public_id: str, file_format: str, expires_at: int) -> str:
    _require_cloudinary()
    return utils.private_download_url(
        public_id, file_format,
        resource_type="video",
        type="authenticated",
        expires_at=expires_at,
        attachment=False,
    )


def delete_video_resource(public_id: str) -> dict:
    _require_cloudinary()
    return cloudinary.uploader.destroy(
        public_id, resource_type="video", type="authenticated", invalidate=True,
    )
