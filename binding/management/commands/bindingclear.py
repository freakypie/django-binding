from django.core.management.base import BaseCommand, CommandError
from ...binding import Binding


class Command(BaseCommand):
    help = 'Resets all the bindings and send out new versions'

    def handle(self, *args, **options):
        Binding.clear_all()
        self.stdout.write(self.style.NOTICE('done.'))
