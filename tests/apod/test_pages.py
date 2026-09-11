import unittest

import application


class TestBirthdayPages(unittest.TestCase):
    def setUp(self):
        self.client = application.app.test_client()

    def test_landing(self):
        res = self.client.get("/birthday")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Reveal my sky", res.data)

    def test_form_submit_redirects_to_sky_page(self):
        res = self.client.get("/birthday?date=2000-05-01")
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res.location.endswith("/birthday/2000-05-01"))

    def test_form_submit_with_bad_date_shows_error(self):
        res = self.client.get("/birthday?date=1990-01-01")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Pick a date between", res.data)

    def test_sky_page(self):
        res = self.client.get("/birthday/2000-05-01")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"May 1, 2000", res.data)
        self.assertIn(b'"2000-05-01"', res.data)

    def test_sky_page_rejects_invalid_dates(self):
        for day in ("not-a-date", "1995-06-15", "2999-01-01"):
            res = self.client.get(f"/birthday/{day}")
            self.assertEqual(res.status_code, 302, day)
            self.assertIn("/birthday?date=", res.location)

    def test_surprise_redirects_to_a_sky_page(self):
        res = self.client.get("/birthday/surprise")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/birthday/", res.location)
        self.assertNotIn("/birthday/surprise", res.location)
