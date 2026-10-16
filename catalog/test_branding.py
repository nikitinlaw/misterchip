from PIL import Image

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse


class BrandingTests(TestCase):
    def test_branding_is_used_on_every_page(self):
        response = self.client.get(reverse("account_register"), secure=True)
        self.assertContains(response, 'alt="misterchip"')
        self.assertContains(response, 'misterchip-logo')
        self.assertContains(response, 'favicon')
        self.assertNotContains(response, 'class="brand-wordmark"')

    def test_approved_images_are_present(self):
        logo = finders.find("catalog/misterchip-logo.png")
        favicon = finders.find("catalog/favicon.png")
        self.assertIsNotNone(logo)
        self.assertIsNotNone(favicon)
        with Image.open(logo) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreaterEqual(image.size[0], 400)
        with Image.open(favicon) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (128, 128))
