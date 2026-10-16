"""Russian labels for MISTERCHIP administration; no schema changes."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("projects", "0001_initial")]
    operations = [
        migrations.AlterModelOptions(name="project", options={"verbose_name":"DIY-проект","verbose_name_plural":"DIY-проекты","ordering":["-published_at","-created_at"]}),
        migrations.AlterModelOptions(name="projectcomponent", options={"verbose_name":"Компонент проекта","verbose_name_plural":"Компоненты проектов","ordering":["sort_order","pk"]}),
        migrations.AlterModelOptions(name="projectresource", options={"verbose_name":"Технический ресурс","verbose_name_plural":"Технические ресурсы","ordering":["kind","pk"]}),
    ]
