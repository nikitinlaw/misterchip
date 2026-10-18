# MISTERCHIP — версия, почта и восстановление

Код и шаблоны systemd подготовлены для эксплуатационного этапа. Подключение
SMTP, внешнего хранилища и установка root-owned файлов выполняются
администратором на проверенном VPS. Наличие этих файлов в репозитории не
означает, что сервисы уже подключены или таймеры запущены.

## 1. Работающая версия

Из `/home/misterchip-admin/misterchip` на VPS:

```bash
git rev-parse HEAD
docker compose -f compose.staging.yaml ps
docker compose -f compose.staging.yaml exec -T web python manage.py runtime_status
sudo systemctl is-active caddy
```

Git показывает исходники на диске. `runtime_status` показывает SHA образа из
`/app/RELEASE`, созданного при сборке. `unknown` означает сборку без метки версии.
Добавление `--expect-revision <40-символьный-SHA>` завершает команду с ошибкой
при несовпадении с ожидаемым образом.

```bash
curl --fail --silent --show-error --dump-header - https://misterchip.ru/healthz/
```

Успех: HTTP 200, тело `ok`, `X-Misterchip-Revision` с ожидаемым SHA. Endpoint
проверяет PostgreSQL и Redis; доставку email и резервные копии проверяют отдельно.
`runtime_status` выводит только SHA, почтовый режим и булевы признаки настройки.
Пароль, SMTP-логин, host и адрес отправителя не выводятся. Команда не отправляет
письма и не изменяет данные.

На прежнем образе команды/заголовка ещё может не быть. Порядок обновления
установленного helper описан в [STAGING_DEPLOY.md](STAGING_DEPLOY.md).

Перед публичной выкладкой M5.1 в закрытом `.env` обязательно задают
`DJANGO_TRUST_PROXY_CLIENT_IP=1` и устанавливают обновлённый root-owned public
helper. Флаг включают только для Caddy с private/loopback upstream, когда порт
приложения недоступен напрямую извне: приложение принимает единственный валидный
`X-Forwarded-For` только от private/loopback peer. Это позволяет ограничениям по
IP различать посетителей за прокси. По умолчанию доверие выключено; отдельный
закрытый стенд не требует включения. `runtime_status` показывает только булево
`trusted_client_ip`. Старый установленный helper флаг не задаёт и не проверяет;
обновление Git само по себе его не заменяет.

## 2. SMTP

Нужны параметры выбранного провайдера: SMTP-host, порт, TLS-режим, подтверждённый
адрес отправителя, логин и секрет почтового приложения. Их вводят только
в закрытый `.env` на VPS.

| Параметр | Значение |
|---|---|
| `DJANGO_EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST` | SMTP-host провайдера |
| `EMAIL_PORT` | Порт провайдера, обычно 587 для STARTTLS |
| `EMAIL_USE_TLS` | `1` для STARTTLS, иначе `0` |
| `EMAIL_USE_SSL` | `1` для implicit TLS (часто порт 465), иначе `0` |
| `EMAIL_HOST_USER` | Логин почтового приложения |
| `EMAIL_HOST_PASSWORD` | Секрет почтового приложения |
| `DEFAULT_FROM_EMAIL` | Имя и подтверждённый адрес отправителя |
| `PUBLIC_SITE_URL` | `https://misterchip.ru` |

Одновременно включать TLS и SSL нельзя. Проверка текущей реализации требует
шифрованное соединение и заполненные учётные данные; анонимный внутренний SMTP
relay в этот этап не входит.

Изменённый `.env` подхватывается при пересоздании контейнера. Обычный `restart`
переменные окружения не обновляет. Public deploy helper проверит настройки
перед переключением приложения. После развёртывания:

```bash
docker compose -f compose.staging.yaml exec -T web python manage.py runtime_status --require-smtp
```

`mail.configuration_ready=true` подтверждает заполнение и согласованность
параметров. `delivery_verified=false` сообщает, что этот read-only вызов доставку
не проверял. Завершение подключения подтверждает отдельный согласованный тест
на собственном адресе: подтверждение email, сброс пароля, уведомление Market.
Проверяются получение, правильный HTTPS-домен ссылки и поведение при ошибке
провайдера.

Файловая почта прежнего пилота продолжает запускаться, но `--require-smtp`
считает её неготовой. Файл с письмом не подтверждает доставку адресату.

## 3. Повторная отправка уведомлений Market

Ожидающие записи старше одной минуты повторяет команда:

```bash
docker compose -f compose.staging.yaml exec -T web python manage.py send_market_notifications --limit 50
```

Wrapper `ops/notifications.sh` проверяет SMTP, берёт `flock`, затем обрабатывает
очередь. Второй запуск не пересекается с первым. Таймер запускает обработку
через минуту после завершения предыдущей; вывод wrapper содержит только статус.

После проверки SMTP на VPS:

```bash
sudo install -o root -g root -m 0755 ops/notifications.sh /usr/local/sbin/misterchip-notifications
sudo install -o root -g root -m 0644 ops/systemd/misterchip-notifications.service /etc/systemd/system/
sudo install -o root -g root -m 0644 ops/systemd/misterchip-notifications.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start misterchip-notifications.service
sudo systemctl enable --now misterchip-notifications.timer
```

Read-only контроль: `systemctl status misterchip-notifications.service` и
`systemctl list-timers misterchip-notifications.timer`. Установка и включение
таймера — отдельное действие на сервере; подготовка кода его не выполняет.

## 4. Независимые резервные копии PostgreSQL

`ops/backup.py` использует стандартную библиотеку Python, Docker Compose и
restic. Архив хранится в приватном bucket независимого S3-compatible сервиса
через HTTPS; restic шифрует данные до загрузки. CLI отклоняет локальные пути,
loopback, известный IP VPS, HTTP и URL с встроенными учётными данными. Для
DNS-имени отдельно проверяется принадлежность независимому хранилищу.

Копия содержит PostgreSQL custom-format dump и manifest с датой, major-версией
PostgreSQL, SHA образа, размером и SHA-256 дампа.

Код восстанавливается из Git. `.env`, SSH-ключи, SMTP-секреты, тестовые письма
и локальные media-файлы в этот архив не включены. С появлением локальных
пользовательских загрузок нужен отдельный backup этих файлов. Для восстановления
БД можно создать новый закрытый `.env` с действующими ключами; исходные секреты
не нужны внутри PostgreSQL dump.

### Первичная подготовка

Установить restic из подходящего официального пакета, проверить `restic version`.
Docker и Python 3 уже требуются проекту. CLI рассчитан на PostgreSQL 16, как
`compose.staging.yaml`.

Из каталога проверенного коммита:

```bash
sudo install -d -o root -g root -m 0700 /etc/misterchip /var/lib/misterchip-ops
sudo install -o root -g root -m 0755 ops/backup.py /usr/local/sbin/misterchip-backup
```

Создать `/etc/misterchip/backup.env` из `ops/backup.env.example`, только если
файла ещё нет. Владелец `root:root`, права `0600`. Существующую конфигурацию
сохранять. Формат — буквальные строки `KEY=VALUE`, парные кавычки допускаются;
подстановки shell не выполняются.

Нужны:

- `RESTIC_REPOSITORY=s3:https://<endpoint>/<private-bucket>/misterchip`;
- `AWS_ACCESS_KEY_ID` и `AWS_SECRET_ACCESS_KEY` для этого bucket;
- `AWS_DEFAULT_REGION`, если его требует провайдер;
- `RESTIC_PASSWORD_FILE=/etc/misterchip/restic-password`.

Bucket и credentials создаются у выбранного провайдера. Пароль restic хранится
в root-only файле и отдельно от VPS в менеджере паролей. При повторной установке
пароль существующего репозитория не заменяется. Потеря этого пароля делает
зашифрованные копии недоступными.

Команда создаёт пароль только при отсутствии файла и не печатает его:

```bash
sudo python3 - <<'PY'
import os
import secrets

path = "/etc/misterchip/restic-password"
try:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print("Existing repository password preserved.")
else:
    with os.fdopen(descriptor, "w") as stream:
        stream.write(secrets.token_urlsafe(48) + "\n")
    print("Repository password created without displaying it.")
PY
```

Для нового пустого репозитория выполнить один раз:

```bash
sudo /usr/local/sbin/misterchip-backup init
sudo /usr/local/sbin/misterchip-backup backup
sudo /usr/local/sbin/misterchip-backup restore-check
sudo /usr/local/sbin/misterchip-backup status
```

`init` — явная отдельная операция; ошибка соединения не создаёт новый репозиторий
автоматически. `backup_uploaded` появляется только после успешного `pg_dump`,
чтения TOC архива и полного успешного ответа restic с точным snapshot ID.
Код restic 3 (частичная копия) считается ошибкой.

### Проверка восстановления

`restore-check` скачивает точный снимок из внешнего хранилища, проверяет tar
и SHA-256, затем запускает временный `postgres:16`:

- `--network none`, без опубликованных портов и без сети приложения;
- отдельная новая БД `misterchip_restore_check`;
- `pg_restore --exit-on-error --no-owner --no-privileges`;
- проверка восстановленной таблицы миграций;
- удаление только созданного этим вызовом контейнера с проверкой ID и метки.

Имя работающего контейнера и адрес боевой БД команда в качестве restore target
не принимает. PostgreSQL image должен уже присутствовать: используется
`--pull=never`. Временная БД ограничена 768 МБ RAM; на диске нужно место для
bundle, дампа и восстановленной базы. Временные файлы закрыты и удаляются
после операции.

Отметка восстановления записывается после завершения `pg_restore`, проверки
схемы и удаления временного контейнера. Проверка конкретной старой копии:

```bash
sudo /usr/local/sbin/misterchip-backup restore-check --snapshot <полный-64-символьный-snapshot-ID>
```

Без `--snapshot` берётся точный ID последней успешной загрузки из локального
маркера. После потери VPS ID выбирается в репозитории restic и передаётся явно.
Read-only `status` показывает даты/возраст последней загрузки и проверки, не
подключаясь к хранилищу и не выводя его URL или секреты.

Этот CLI выполняет backup и проверку восстановления. Переключение приложения
на восстановленную БД — отдельная операция: готовится новая БД/инстанс,
проверяется совместимость версии приложения и затем меняется подключение.
Автоматического стирания работающей БД этот набор не содержит.

### Регулярный запуск

После успешной первой внешней копии и восстановления:

```bash
sudo install -o root -g root -m 0644 ops/systemd/misterchip-backup.service /etc/systemd/system/
sudo install -o root -g root -m 0644 ops/systemd/misterchip-backup.timer /etc/systemd/system/
sudo install -o root -g root -m 0644 ops/systemd/misterchip-restore-check.service /etc/systemd/system/
sudo install -o root -g root -m 0644 ops/systemd/misterchip-restore-check.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now misterchip-backup.timer misterchip-restore-check.timer
```

Backup — ежедневно после 03:30 МСК; restore drill — по воскресеньям после
04:30 МСК. Случайная задержка — до 20 минут. `Persistent=true` позволяет
догнать пропущенный запуск после включения сервера. Общий lock исключает
одновременный backup и restore-check. Новые root-owned deploy helpers берут тот
же lock, поэтому плановый дамп не пересекается с их миграциями; изменения БД
вручную за пределами этих команд нужно согласовывать отдельно.

Read-only контроль:

```bash
sudo /usr/local/sbin/misterchip-backup status
sudo systemctl list-timers misterchip-backup.timer misterchip-restore-check.timer
sudo systemctl status misterchip-backup.service misterchip-restore-check.service
```

Цель эксплуатации: backup младше 48 часов, успешный restore drill младше 8 дней.
Ошибка возвращает ненулевой код и короткое имя этапа; дочерние логи, SQL,
URL хранилища и credentials не печатаются. Уведомления об ошибках и квоте
подключаются к выбранному каналу мониторинга. Автоматическое удаление снимков
здесь не включено; retention настраивается после первого успешного восстановления.

## 5. Критерии завершения

1. SHA репозитория, образа и HTTP-заголовка согласованы.
2. Реальная почта доставляет согласованные тесты; ссылки ведут на HTTPS-домен.
3. Очередь Market повторяет pending записи; её таймер активен.
4. Независимый зашифрованный snapshot успешно восстановлен в изоляции.
5. Таймеры работают, даты копии/проверки доступны без чтения секретов.

## Официальные технические источники

- [Django 6.1: SMTP и отправка email](https://docs.djangoproject.com/en/6.1/topics/email/).
  Существующие `EMAIL_*` настройки поддерживаются; отдельная миграция на
  `MAILERS` в этот этап не включена.
- [PostgreSQL 16: pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html).
- [restic: backup, stdin, коды завершения](https://restic.readthedocs.io/en/stable/040_backup.html).
- [restic: восстановление](https://restic.readthedocs.io/en/stable/050_restore.html).
