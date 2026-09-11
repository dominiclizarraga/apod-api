"""
Thin client for the aiand Videos API (https://docs.aiand.com/api/videos/).

Turns an APOD image into a short clip: the image is downloaded server-side,
uploaded to the Files API, and used as the first frame of a video job.
"""

import os
import re
from urllib.parse import urljoin, urlparse

import requests

DEFAULT_BASE_URL = "https://api.aiand.com"
DEFAULT_MODEL = "minimaxai/minimax-h3"
SECONDS = 5
ASPECT_RATIO = "16:9"
MAX_PROMPT_CHARS = 7000
# The engine rejects frame images of 30 MiB or more.
MAX_IMAGE_BYTES = 30 * 1024 * 1024
TIMEOUT = 30
MAX_REDIRECTS = 3

# Only fetch images from hosts that apod.utility produces, so this service
# can't be used to make arbitrary outbound requests.
ALLOWED_IMAGE_HOSTS = {"apod.nasa.gov", "img.youtube.com", "i.vimeocdn.com"}
VIDEO_ID_RE = re.compile(r"^video_[A-Za-z0-9]+$")


class VideoAPIError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _api_key():
    key = os.environ.get("AIAND_API_KEY", "").strip()
    if not key:
        raise VideoAPIError(
            503, "not_configured", "Video generation is not configured (AIAND_API_KEY)."
        )
    return key


def _url(path):
    return os.environ.get("AIAND_BASE_URL", DEFAULT_BASE_URL).rstrip("/") + path


def _headers():
    return {"Authorization": f"Bearer {_api_key()}"}


def _raise_for_error(response):
    if response.ok:
        return
    try:
        error = response.json().get("error") or {}
    except ValueError:
        error = {}
    if isinstance(error, str):
        error = {"message": error}
    raise VideoAPIError(
        response.status_code,
        error.get("code") or "upstream_error",
        error.get("message") or f"Video API returned {response.status_code}.",
    )


def validate_video_id(video_id):
    if not VIDEO_ID_RE.match(video_id or ""):
        raise VideoAPIError(400, "invalid_request_error", "Invalid video id.")


def build_prompt(title):
    subject = (title or "the night sky").strip()
    prompt = (
        f"Slow cinematic camera push-in on this astronomy photograph of {subject}. "
        "Subtle, natural motion: drifting stars, glowing gas, shimmering light. "
        "Keep the composition faithful to the image."
    )
    return prompt[:MAX_PROMPT_CHARS]


def _check_image_url(url):
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_IMAGE_HOSTS:
        raise VideoAPIError(
            400, "invalid_request_error", "Only APOD images can be animated."
        )
    return parsed


def _get_image(image_url):
    # Follow redirects by hand so every hop is re-checked against the allowlist.
    url = image_url
    for _ in range(MAX_REDIRECTS + 1):
        _check_image_url(url)
        response = requests.get(
            url, stream=True, timeout=TIMEOUT, allow_redirects=False
        )
        if not response.is_redirect:
            return response
        url = urljoin(url, response.headers.get("Location", ""))
        response.close()
    raise VideoAPIError(502, "image_unavailable", "Too many redirects for image.")


def _download_image(image_url):
    parsed = _check_image_url(image_url)

    with _get_image(image_url) as response:
        if not response.ok:
            raise VideoAPIError(
                502, "image_unavailable", "Could not download the APOD image."
            )
        chunks, size = [], 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size >= MAX_IMAGE_BYTES:
                raise VideoAPIError(
                    400, "invalid_request_error", "Image is too large to animate."
                )
            chunks.append(chunk)
        content_type = response.headers.get("Content-Type", "image/jpeg")

    filename = os.path.basename(parsed.path) or "apod.jpg"
    return filename, b"".join(chunks), content_type


def upload_image(image_url):
    headers = _headers()
    filename, data, content_type = _download_image(image_url)
    response = requests.post(
        _url("/v1/files"),
        headers=headers,
        data={"purpose": "vision"},
        files={"file": (filename, data, content_type)},
        timeout=TIMEOUT,
    )
    _raise_for_error(response)
    return response.json()["id"]


def create_job(file_id, title):
    response = requests.post(
        _url("/v1/videos"),
        headers=_headers(),
        json={
            "model": os.environ.get("AIAND_VIDEO_MODEL", DEFAULT_MODEL),
            "prompt": build_prompt(title),
            "seconds": SECONDS,
            "aspect_ratio": ASPECT_RATIO,
            "image_reference": [{"file_id": file_id, "role": "first_frame"}],
        },
        timeout=TIMEOUT,
    )
    _raise_for_error(response)
    return response.json()


def get_job(video_id):
    validate_video_id(video_id)
    response = requests.get(
        _url(f"/v1/videos/{video_id}"), headers=_headers(), timeout=TIMEOUT
    )
    _raise_for_error(response)
    return response.json()


def open_content(video_id):
    """Return a streaming response for the finished MP4. Caller must close it."""
    validate_video_id(video_id)
    response = requests.get(
        _url(f"/v1/videos/{video_id}/content"),
        headers=_headers(),
        stream=True,
        timeout=TIMEOUT,
    )
    try:
        _raise_for_error(response)
    except VideoAPIError:
        response.close()
        raise
    return response
