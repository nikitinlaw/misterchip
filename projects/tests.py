from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserRole
from catalog.models import Category, Product, ProductType
from .models import Project, ProjectComponent, ProjectResource


class HardwareProjectTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.developer = user_model.objects.create_user(
            username="dev", email="dev@example.test", password="A1VeryStrongPass!"
        )
        self.reader = user_model.objects.create_user(
            username="reader", email="reader@example.test", password="A1VeryStrongPass!"
        )
        self.editor = user_model.objects.create_superuser(
            username="editor", email="editor@example.test", password="A1VeryStrongPass!"
        )
        UserRole.objects.create(user=self.developer, role=UserRole.Role.DEVELOPER)
        category = Category.objects.create(name="Электроника", slug="electronics")
        kind = ProductType.objects.create(category=category, name="Контроллеры", slug="boards")
        self.product = Product.objects.create(
            product_type=kind, title="Контроллер Arduino", slug="arduino-board",
            status=Product.Status.PUBLISHED,
        )
        self.draft_product = Product.objects.create(
            product_type=kind, title="Скрытый контроллер",
            slug="unpublished-board", status=Product.Status.DRAFT,
        )
        self.description = "Небольшое электронное устройство для практического обучения."
        self.instructions = (
            "1. Подготовить печатную плату и элементы. 2. Выполнить пайку. "
            "3. Проверить питание. 4. Загрузить прошивку. 5. Провести тесты."
        )

    def payload(self, **changes):
        data = {
            "title": "Контроллер с печатным корпусом",
            "summary": "Проверяемый проект с BOM, схемой и корпусом.",
            "description": self.description,
            "assembly_instructions": self.instructions,
            "license_notes": "Лицензия на исходный код устанавливается автором.",
            "rights_confirmed": "on",
            "related_products": [str(self.product.pk)],
            "parts-TOTAL_FORMS": "2",
            "parts-INITIAL_FORMS": "0",
            "parts-MIN_NUM_FORMS": "0",
            "parts-MAX_NUM_FORMS": "50",
            "parts-0-name": "Резистор 1 кОм",
            "parts-0-quantity": "2",
            "parts-0-unit": "pcs",
            "parts-0-note": "SMD",
            "resources-TOTAL_FORMS": "2",
            "resources-INITIAL_FORMS": "0",
            "resources-MIN_NUM_FORMS": "0",
            "resources-MAX_NUM_FORMS": "30",
            "resources-0-kind": "model3d",
            "resources-0-title": "STL-файл корпуса",
            "resources-0-url": "https://example.test/enclosure.stl",
            "resources-0-rights_note": "Собственный проект",
        }
        data.update(changes)
        return data

    def create(self, **changes):
        self.client.force_login(self.developer)
        response = self.client.post(
            reverse("project_create"), self.payload(**changes), secure=True
        )
        self.assertEqual(
            response.status_code, 302,
            msg=f"Project form: {response.context['form'].errors}; "
                f"BOM: {response.context['parts'].errors}; "
                f"Resources: {response.context['resources'].errors}; "
                f"Non-form: {response.context['parts'].non_form_errors()} / "
                f"{response.context['resources'].non_form_errors()}",
        )
        return Project.objects.get(author=self.developer)

    def test_developer_creates_draft_with_bom_and_3d_resource(self):
        p = self.create()
        self.assertEqual(p.status, Project.Status.DRAFT)
        self.assertEqual(p.related_products.count(), 1)
        self.assertEqual(ProjectComponent.objects.get(project=p).quantity, 2)
        self.assertEqual(ProjectResource.objects.get(project=p).kind, "model3d")
        self.assertEqual(self.client.get(reverse("project_detail", args=[p.slug]), secure=True).status_code, 404)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("project_list"), secure=True), p.title)

    def test_reader_without_roles_cannot_create_project(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(
            reverse("project_create"), self.payload(), secure=True,
        ).status_code, 403)
        self.assertFalse(Project.objects.exists())

    def test_forged_status_and_unpublished_product_are_rejected(self):
        self.client.force_login(self.developer)
        forged = self.payload(
            status="published", published_at=timezone.now().isoformat(),
            related_products=[str(self.draft_product.pk)],
        )
        response = self.client.post(reverse("project_create"), forged, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Project.objects.exists())

    def test_form_rejects_unsafe_urls_and_negative_quantities(self):
        self.client.force_login(self.developer)
        response = self.client.post(reverse("project_create"), self.payload(
            **{"resources-0-url": "http://example.test/file.stl", "parts-0-quantity": "-2"}
        ), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Project.objects.exists())
        self.assertContains(response, "HTTPS")

    def test_submission_and_staff_publication(self):
        p = self.create()
        submitted = self.client.post(reverse("project_submit", args=[p.pk]), secure=True)
        self.assertEqual(submitted.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.status, Project.Status.SUBMITTED)
        self.assertIsNotNone(p.submitted_at)
        self.assertEqual(self.client.post(
            reverse("project_edit", args=[p.pk]), self.payload(), secure=True,
        ).status_code, 403)
        self.client.force_login(self.editor)
        approved = self.client.post(reverse("admin:projects_project_changelist"), {
            "action": "publish_projects", "_selected_action": [str(p.pk)],
        }, secure=True)
        self.assertEqual(approved.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.status, Project.Status.PUBLISHED)
        self.assertEqual(p.reviewed_by, self.editor)
        self.client.logout()
        self.assertContains(self.client.get(
            reverse("project_detail", args=[p.slug]), secure=True
        ), "STL-файл корпуса")
        self.assertContains(self.client.get(
            reverse("product_detail", args=[self.product.slug]), secure=True
        ), p.title)
        self.assertContains(self.client.get(
            reverse("public_profile", args=[self.developer.username]), secure=True
        ), p.title)

    def test_cannot_publish_draft_or_unconfirmed_content(self):
        p = self.create()
        p.rights_confirmed = False
        p.status = Project.Status.SUBMITTED
        p.save()
        self.client.force_login(self.editor)
        response = self.client.post(reverse("admin:projects_project_changelist"), {
            "action": "publish_projects", "_selected_action": [str(p.pk)],
        }, secure=True)
        self.assertEqual(response.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.status, Project.Status.SUBMITTED)

    def test_other_user_cannot_edit_or_submit_project(self):
        p = self.create()
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse("project_edit", args=[p.pk]), secure=True).status_code, 404)
        self.assertEqual(self.client.post(reverse("project_submit", args=[p.pk]), secure=True).status_code, 404)

    def test_escaping_and_hidden_component_product(self):
        p = self.create()
        p.description = "<script>alert('not-safe')</script>"
        p.status = Project.Status.PUBLISHED
        p.published_at = timezone.now()
        p.save()
        ProjectComponent.objects.create(
            project=p, name="Деталь вне каталога", quantity=1,
            product=self.draft_product,
        )
        p.related_products.add(self.draft_product)
        response = self.client.get(reverse("project_detail", args=[p.slug]), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>")
        self.assertNotContains(response, self.draft_product.title)

    def test_rejected_can_be_revised_and_submitted(self):
        p = self.create()
        p.status = Project.Status.REJECTED
        p.save()
        self.client.force_login(self.developer)
        response = self.client.post(
            reverse("project_edit", args=[p.pk]),
            self.payload(**{
                "title": "Улучшенный проект",
                "parts-INITIAL_FORMS": "1",
                "parts-0-id": str(p.components.first().pk),
                "resources-INITIAL_FORMS": "1",
                "resources-0-id": str(p.resources.first().pk),
            }), secure=True,
        )
        self.assertEqual(response.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.status, Project.Status.DRAFT)
        self.assertEqual(p.title, "Улучшенный проект")
        self.assertEqual(p.components.count(), 1)
        self.assertEqual(p.resources.count(), 1)

    def test_form_requires_rights_confirmation(self):
        self.client.force_login(self.developer)
        response = self.client.post(reverse("project_create"), self.payload(
            rights_confirmed="",
        ), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Project.objects.exists())
