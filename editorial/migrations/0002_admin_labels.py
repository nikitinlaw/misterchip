"""Russian labels for MISTERCHIP administration; no schema changes."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("editorial", "0001_initial")]
    operations = [
        migrations.AlterModelOptions(name="article", options={"verbose_name":"Публикация","verbose_name_plural":"Публикации","ordering":["-published_at","-created_at"]}),
    ]
