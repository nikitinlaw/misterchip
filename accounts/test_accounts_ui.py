from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Profile, UserRole


class AccountFlowTests(TestCase):
    def test_register_and_login_with_two_roles(self):
        response = self.client.post(reverse("account_register"), {
            "username": "maker", "email": "Maker@Example.Test",
            "password1": "StrongPass987654!", "password2": "StrongPass987654!",
            "roles": ["author", "developer"],
        }, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("account_dashboard"))
        user = get_user_model().objects.get(username="maker")
        self.assertEqual(user.email, "maker@example.test")
        self.assertTrue(Profile.objects.filter(user=user).exists())
        self.assertEqual(set(user.business_roles.values_list("role", flat=True)), {"buyer", "author", "developer"})
        self.assertEqual(str(int("_auth_user_id" in self.client.session)), "1")

    def test_duplicate_email_case_insensitive(self):
        get_user_model().objects.create_user(
            username="first", email="taken@example.test", password="A1SecurePassword!"
        )
        response = self.client.post(reverse("account_register"), {
            "username": "second", "email": "TAKEN@example.test",
            "password1": "StrongPass987654!", "password2": "StrongPass987654!",
        }, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="second").exists())

    def test_public_user_cannot_grant_editor_or_seller(self):
        user = get_user_model().objects.create_user(
            username="maker", email="maker@example.test", password="A1SecurePassword!"
        )
        self.client.force_login(user)
        response = self.client.post(reverse("account_dashboard"), {
            "display_name": "Maker",
            "roles": ["author", "seller", "editor", "manufacturer"],
        }, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(user.business_roles.filter(role__in=["seller", "editor", "manufacturer"]).exists())
        self.assertFalse(user.is_staff)

    def test_profile_update_preserves_privileged_roles_and_hides_email(self):
        user = get_user_model().objects.create_user(
            username="author", email="author@example.test", password="A1SecurePassword!"
        )
        UserRole.objects.create(user=user, role="seller")  # granted by staff
        UserRole.objects.create(user=user, role="author")
        self.client.force_login(user)
        response = self.client.post(reverse("account_dashboard"), {
            "first_name": "Иван", "display_name": "Мастер",
            "bio": "Разработка электроники", "roles": ["author", "developer"],
        }, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("account_dashboard"))
        self.assertTrue(user.business_roles.filter(role="seller").exists())
        self.assertTrue(user.business_roles.filter(role="developer").exists())
        public = self.client.get(reverse("public_profile", args=["author"]), secure=True)
        self.assertContains(public, "Мастер")
        self.assertNotContains(public, "author@example.test")

    def test_login_logout_post_and_private_dashboard(self):
        user = get_user_model().objects.create_user(
            username="author", email="author@example.test", password="A1SecurePassword!"
        )
        self.assertEqual(self.client.get(reverse("account_dashboard"), secure=True).status_code, 302)
        logged_in = self.client.post(reverse("login"), {
            "username": "author", "password": "A1SecurePassword!"
        }, secure=True)
        self.assertEqual(logged_in.status_code, 302)
        self.assertEqual(logged_in["Location"], reverse("account_dashboard"))
        self.assertEqual(self.client.get(reverse("account_dashboard"), secure=True).status_code, 200)
        self.assertEqual(self.client.get(reverse("logout"), secure=True).status_code, 405)
        logout = self.client.post(reverse("logout"), secure=True)
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(logout["Location"], reverse("home"))
