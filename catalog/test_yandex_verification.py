"""Verification of the publicly rendered Yandex Webmaster ownership token."""
from django.test import TestCase


class YandexVerificationTests(TestCase):
    TOKEN = '<meta name="yandex-verification" content="10e74506a1dcf479">'

    def test_verification_metatag_present_once_inside_head_on_public_pages(self):
        for url in ("/", "/catalog/search/", "/account/login/"):
            with self.subTest(url=url):
                response = self.client.get(url, secure=True)
                self.assertEqual(response.status_code, 200)
                content = response.content.decode("utf-8")
                head = content.split("</head>", 1)[0]
                self.assertIn(self.TOKEN, head)
                self.assertEqual(content.count('name="yandex-verification"'), 1)

    def test_yandex_html_file_remains_available(self):
        response = self.client.get("/yandex_10e74506a1dcf479.html", secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Verification: 10e74506a1dcf479")
