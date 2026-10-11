from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserRole
from catalog.models import Category, Product, ProductType
from .models import Article


class EditorialWorkflowTests(TestCase):
    def setUp(self):
        model = get_user_model()
        self.author = model.objects.create_user(
            username="alice", email="alice@example.test", password="StrongPassword123!"
        )
        self.other = model.objects.create_user(
            username="bob", email="bob@example.test", password="StrongPassword123!"
        )
        self.editor = model.objects.create_superuser(
            username="reviewer", email="reviewer@example.test", password="StrongPassword123!"
        )
        UserRole.objects.create(user=self.author, role=UserRole.Role.AUTHOR)
        self.category = Category.objects.create(name="Компьютеры", slug="computers")
        self.kind = ProductType.objects.create(category=self.category, name="Память", slug="ram")
        self.product = Product.objects.create(
            product_type=self.kind, title="DDR5 test module", slug="ddr5-test",
            status=Product.Status.PUBLISHED
        )
        self.hidden_product = Product.objects.create(
            product_type=self.kind, title="HIDDEN PRODUCT", slug="hidden-test",
            status=Product.Status.DRAFT
        )
        self.text = "Проверка архитектуры электронной памяти. " * 9
        self.data = {
            "title": "Как выбрать оперативную память",
            "kind": "guide",
            "summary": "Проверенное руководство по техническим параметрам оперативной памяти.",
            "body": self.text,
            "rights_confirmed": "on",
            "related_products": [str(self.product.pk)],
        }

    def new_draft(self):
        return Article.objects.create(
            title="Тестовая публикация", slug="test-publication", kind=Article.Kind.GUIDE,
            summary="Техническая заметка", body=self.text, author=self.author,
            rights_confirmed=True, status=Article.Status.DRAFT,
        )

    def test_author_creates_draft_with_product_and_not_public(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse("article_create"), self.data, secure=True)
        self.assertEqual(response.status_code, 302)
        article = Article.objects.get(author=self.author)
        self.assertEqual(article.status, Article.Status.DRAFT)
        self.assertEqual(article.related_products.count(), 1)
        self.client.logout()
        listing = self.client.get(reverse("article_list"), secure=True)
        self.assertNotContains(listing, article.title)
        self.assertEqual(self.client.get(reverse("article_detail", args=[article.slug]), secure=True).status_code, 404)

    def test_no_role_cannot_create_or_submit(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse("article_create"), self.data, secure=True)
        self.assertEqual(response.status_code, 403)
        draft = self.new_draft()
        response = self.client.post(reverse("article_submit", args=[draft.pk]), secure=True)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(draft.status, Article.Status.DRAFT)

    def test_untrusted_status_not_bound_from_author_form(self):
        self.client.force_login(self.author)
        forged = {**self.data, "status": "published", "published_at": timezone.now().isoformat()}
        self.client.post(reverse("article_create"), forged, secure=True)
        article = Article.objects.get(author=self.author)
        self.assertEqual(article.status, Article.Status.DRAFT)
        self.assertIsNone(article.published_at)

    def test_moderation_requires_staff_and_submission(self):
        draft = self.new_draft()
        self.client.force_login(self.author)
        response = self.client.post(reverse("article_submit", args=[draft.pk]), secure=True)
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Article.Status.SUBMITTED)
        self.assertIsNotNone(draft.submitted_at)
        self.assertEqual(self.client.get(reverse("article_edit", args=[draft.pk]), secure=True).status_code, 403)
        self.assertEqual(self.client.get(reverse("article_detail", args=[draft.slug]), secure=True).status_code, 404)
        self.client.force_login(self.editor)
        response = self.client.post(reverse("admin:editorial_article_changelist"), {
            "action": "publish_selected", "_selected_action": [str(draft.pk)],
        }, secure=True)
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Article.Status.PUBLISHED)
        self.assertEqual(draft.reviewed_by, self.editor)
        self.assertIsNotNone(draft.published_at)
        self.client.logout()
        self.assertContains(self.client.get(reverse("article_list"), secure=True), draft.title)
        self.assertContains(self.client.get(reverse("article_detail", args=[draft.slug]), secure=True), draft.title)

    def test_draft_and_unconfirmed_article_not_published_by_action(self):
        draft = self.new_draft()
        unconfirmed = Article.objects.create(
            title="Без прав", slug="without-rights", summary="Проверка",
            body=self.text, author=self.author, rights_confirmed=False,
            status=Article.Status.SUBMITTED,
        )
        self.client.force_login(self.editor)
        response = self.client.post(reverse("admin:editorial_article_changelist"), {
            "action": "publish_selected",
            "_selected_action": [str(draft.pk), str(unconfirmed.pk)],
        }, secure=True)
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        unconfirmed.refresh_from_db()
        self.assertEqual(draft.status, Article.Status.DRAFT)
        self.assertEqual(unconfirmed.status, Article.Status.SUBMITTED)

    def test_rejected_article_edit_returns_to_draft(self):
        article = self.new_draft()
        article.status = Article.Status.REJECTED
        article.save()
        self.client.force_login(self.author)
        response = self.client.post(reverse("article_edit", args=[article.pk]), {
            **self.data, "title": "Текст после замечаний",
        }, secure=True)
        self.assertEqual(response.status_code, 302)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.DRAFT)
        self.assertEqual(article.title, "Текст после замечаний")

    def test_published_edit_forbidden_to_author(self):
        article = self.new_draft()
        article.status = Article.Status.PUBLISHED
        article.published_at = timezone.now()
        article.save()
        self.client.force_login(self.author)
        self.assertEqual(self.client.post(
            reverse("article_edit", args=[article.pk]), self.data, secure=True
        ).status_code, 403)
        self.assertEqual(self.client.post(
            reverse("article_submit", args=[article.pk]), secure=True
        ).status_code, 403)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.PUBLISHED)

    def test_body_is_escaped_and_unpublished_product_is_hidden(self):
        article = self.new_draft()
        article.body = "<script>alert('XSS')</script>" + self.text
        article.status = Article.Status.PUBLISHED
        article.published_at = timezone.now()
        article.save()
        article.related_products.add(self.product, self.hidden_product)
        result = self.client.get(reverse("article_detail", args=[article.slug]), secure=True)
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "&lt;script&gt;")
        self.assertNotContains(result, "<script>")
        self.assertContains(result, self.product.title)
        self.assertNotContains(result, self.hidden_product.title)

    def test_csrf_required_to_submit(self):
        article = self.new_draft()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.author)
        response = csrf_client.post(reverse("article_submit", args=[article.pk]), secure=True)
        self.assertEqual(response.status_code, 403)
        article.refresh_from_db()
        self.assertEqual(article.status, Article.Status.DRAFT)

    def test_missing_rights_confirmation_rejected_by_form(self):
        self.client.force_login(self.author)
        data = {**self.data, "rights_confirmed": ""}
        response = self.client.post(reverse("article_create"), data, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Article.objects.exists())
