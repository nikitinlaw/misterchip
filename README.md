# MISTERCHIP — платформа электроники

Первый технический этап проекта: Django + PostgreSQL, одна учётная запись с несколькими бизнес-ролями, каталог конкретных моделей с гибкими характеристиками и отдельный дословный справочник товаров из свидетельства RU № 948080.

**Это каркас разработки, не готовый интернет-магазин.** Продавцы, обзоры, сравнение цен, загрузка драйверов, SaaS/White Label и франшиза будут добавляться по отдельным этапам.

## Источники требований

- [Концепция MISTERCHIP](https://docs.google.com/document/d/1xjwAgzzYmPZRKxpnBPBhZ-iktXcc490ygWrZjSrFcsY/edit)
- [Техническое задание MVP 1.0 и дополнение про настраиваемые характеристики](https://docs.google.com/document/d/1o6F3_QSgGePsQ3BZzBhIgV9V7o_6YyMuHbORzQcOblA/edit)
- [Каталог на основе RU № 948080, 373 позиции](https://docs.google.com/spreadsheets/d/1TDO-Hf232G3d7DMSU23LM7V1yULbVuSg/edit)

## Требования

Python 3.13, PostgreSQL 16+, Docker Compose (опционально). Используется Django 6.1.1 по исходному учебному проекту. Для защиты исходников Django на продакшене обязательны свои секреты и HTTPS.

## Локальный запуск через Docker

```bash
cp .env.example .env
# установите собственный DJANGO_SECRET_KEY в .env
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

Сайт: http://127.0.0.1:8000/ ; админка: http://127.0.0.1:8000/admin/.

Вариант без Docker: установите зависимости `pip install -r requirements.txt`, создайте PostgreSQL с реквизитами .env, затем `python manage.py migrate` и `python manage.py runserver`.

## Справочник из свидетельства

Рядом с кодом **не хранится** выгрузка из пользовательского Google Диска. Загрузите утверждённый файл `MISTERCHIP_catalog_RU948080.xlsx` локально.

```bash
python manage.py import_goods /path/to/MISTERCHIP_catalog_RU948080.xlsx --check-only
python manage.py import_goods /path/to/MISTERCHIP_catalog_RU948080.xlsx
```

Команда проверяет заголовки, 11 допустимых категорий, ровно 373 уникальные позиции 1–373. Исходные наименования сохраняются без изменений. Повторный импорт обновляет существующие записи без дублей.

## Гибкие характеристики

Через Django Admin создайте:
1. Раздел каталога `Category` (если ещё не загружен);
2. Тип товара `ProductType`, например «Оперативная память» или «Резистор»;
3. Глобальное определение характеристики `AttributeDefinition` (тип данных и базовая единица);
4. Связь `ProductTypeAttribute` с нужным типом товара;
5. Конкретную модель `Product` и её значения `ProductAttributeValue`.

Характеристики типов настраиваются в данных, без переписывания модели Python; числовые единицы автоматически нормализуются только для явно предусмотренных совместимых величин. Это начальная реализация: специальный удобный конструктор динамических форм для редакторов — следующий этап.

## Тесты

```bash
python manage.py test
python manage.py check
```

GitHub Actions запускает тесты с PostgreSQL на каждом push и pull request.

## Архитектурные принципы

- `accounts.User` — собственная модель пользователя до первых миграций; `UserRole` поддерживает несколько ролей.
- `TrademarkGood` хранит формулировки 9-го класса МКТУ **отдельно** от реальных моделей `Product`.
- `Category` — 11 широких разделов интерфейса; `ProductType` — внутренний технический тип модели.
- `AttributeDefinition` и `ProductTypeAttribute` — справочник характеристик и настройка набора по типу.
- Продавец и его цена будут отдельными сущностями, общая карточка модели не станет объявлением отдельного продавца.
- Не переносим код дипломного проекта без проверки; исходный репозиторий [Python_Site_FinalProject_Nikitin](https://github.com/nikitinlaw/Python_Site_FinalProject_Nikitin) не изменяется.

## Ограничения текущей стадии

Ещё не реализованы публичные кабинеты и регистрация, редакторская модерация, загрузки изображений, поисковые фильтры, импорт прайсов продавцов, публикации и DIY-проекты. Производственный сервер и регулярные резервные копии не развернуты.
