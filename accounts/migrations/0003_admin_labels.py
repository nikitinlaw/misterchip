"""Russian labels for MISTERCHIP administration; no schema changes."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_profile")]
    operations = [
        migrations.AlterModelOptions(name="user", options={"verbose_name":"Пользователь","verbose_name_plural":"Пользователи"}),
        migrations.AlterModelOptions(name="userrole", options={"verbose_name":"Роль пользователя","verbose_name_plural":"Роли пользователей"}),
        migrations.AlterModelOptions(name="profile", options={"verbose_name":"Профиль участника","verbose_name_plural":"Профили участников"}),
    ]
