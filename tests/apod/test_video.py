import unittest
from unittest.mock import MagicMock, patch

import application

IMAGE_URL = "https://apod.nasa.gov/apod/image/1510/Trifid_HubbleGendler_960.jpg"
VIDEO_ID = "video_9f2c1b7e4a3d4e8fa1b0c9d8e7f6a5b4"


def _response(status=200, json=None, chunks=(b"img",), headers=None):
    response = MagicMock()
    response.ok = status < 400
    response.status_code = status
    response.is_redirect = 300 <= status < 400
    response.json.return_value = json or {}
    response.iter_content.return_value = list(chunks)
    response.headers = headers or {"Content-Type": "image/jpeg"}
    response.__enter__.return_value = response
    return response


@patch.dict("os.environ", {"AIAND_API_KEY": "test-key"})
class TestVideoRoutes(unittest.TestCase):
    def setUp(self):
        self.client = application.app.test_client()

    @patch.dict("os.environ", {"AIAND_API_KEY": ""})
    def test_missing_key(self):
        res = self.client.post("/v1/video/", json={"image_url": IMAGE_URL})
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.get_json()["code"], "not_configured")

    @patch("apod.video.requests")
    def test_rejects_non_apod_host(self, mock_requests):
        res = self.client.post(
            "/v1/video/", json={"image_url": "https://169.254.169.254/latest"}
        )
        self.assertEqual(res.status_code, 400)
        mock_requests.get.assert_not_called()

    @patch("apod.video.requests")
    def test_rejects_redirect_off_allowlist(self, mock_requests):
        mock_requests.get.return_value = _response(
            status=302, headers={"Location": "http://127.0.0.1/admin"}
        )
        res = self.client.post("/v1/video/", json={"image_url": IMAGE_URL})
        self.assertEqual(res.status_code, 400)
        mock_requests.get.assert_called_once()
        mock_requests.post.assert_not_called()

    @patch("apod.video.requests")
    def test_create_uploads_image_then_creates_job(self, mock_requests):
        mock_requests.get.return_value = _response()
        mock_requests.post.side_effect = [
            _response(json={"id": "file-abc"}),
            _response(
                json={
                    "id": VIDEO_ID,
                    "status": "moderating",
                    "cost": "0.40000000",
                    "currency": "usd",
                }
            ),
        ]
        res = self.client.post(
            "/v1/video/", json={"image_url": IMAGE_URL, "title": "Trifid Nebula"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["id"], VIDEO_ID)

        upload, create = mock_requests.post.call_args_list
        self.assertEqual(upload.kwargs["data"], {"purpose": "vision"})
        self.assertEqual(upload.kwargs["headers"]["Authorization"], "Bearer test-key")
        body = create.kwargs["json"]
        self.assertEqual(
            body["image_reference"], [{"file_id": "file-abc", "role": "first_frame"}]
        )
        self.assertEqual(body["aspect_ratio"], "16:9")
        self.assertIn("Trifid Nebula", body["prompt"])

    @patch("apod.video.requests")
    def test_forwards_agreement_required(self, mock_requests):
        mock_requests.get.return_value = _response()
        mock_requests.post.side_effect = [
            _response(json={"id": "file-abc"}),
            _response(
                status=403,
                json={"error": {"code": "agreement_required", "message": "Agree"}},
            ),
        ]
        res = self.client.post("/v1/video/", json={"image_url": IMAGE_URL})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.get_json()["code"], "agreement_required")

    @patch("apod.video.requests")
    def test_status(self, mock_requests):
        mock_requests.get.return_value = _response(
            json={"id": VIDEO_ID, "status": "in_progress", "error": None}
        )
        res = self.client.get(f"/v1/video/{VIDEO_ID}")
        self.assertEqual(res.get_json()["status"], "in_progress")

    def test_status_rejects_bad_id(self):
        res = self.client.get("/v1/video/not-a-video-id")
        self.assertEqual(res.status_code, 400)

    @patch("apod.video.requests")
    def test_content_streams_mp4(self, mock_requests):
        mock_requests.get.return_value = _response(
            chunks=(b"mp4-", b"bytes"), headers={"Content-Length": "9"}
        )
        res = self.client.get(f"/v1/video/{VIDEO_ID}/content")
        self.assertEqual(res.mimetype, "video/mp4")
        self.assertEqual(res.data, b"mp4-bytes")
