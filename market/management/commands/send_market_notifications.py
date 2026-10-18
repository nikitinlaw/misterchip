from django.core.management.base import BaseCommand, CommandError

from market.notifications import retry_pending_notifications


class Command(BaseCommand):
    help = "Повторить отправку ожидающих уведомлений Market без вывода адресов и сообщений."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 500:
            raise CommandError("--limit должен быть от 1 до 500.")
        attempted, sent = retry_pending_notifications(limit=limit)
        self.stdout.write(f"Обработано: {attempted}; отправлено: {sent}; ожидает повтора: {attempted - sent}.")
