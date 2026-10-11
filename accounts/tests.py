from django.test import TestCase
from .models import User, UserRole


class UserRoleTests(TestCase):
    def test_multiple_roles_can_coexist(self):
        user = User.objects.create_user(username="maker", email="maker@example.test", password="testpass123A!")
        for role in [UserRole.Role.AUTHOR, UserRole.Role.DEVELOPER, UserRole.Role.SELLER]:
            UserRole.objects.create(user=user, role=role)
        self.assertEqual(user.business_roles.count(), 3)

    def test_email_is_unique(self):
        User.objects.create_user(username="one", email="same@example.test", password="strong123X!")
        with self.assertRaises(Exception):
            User.objects.create_user(username="two", email="same@example.test", password="strong123X!")
