from django.core.management.base import BaseCommand, CommandError
from ...binding import Binding


class Command(BaseCommand):
    help = 'Lists all the bindings in use on this system'

    def handle(self, *args, **options):
        for binding in Binding.bindings.pattern("*"):
            self.stdout.write(" - {}".format(binding.name))
        self.stdout.write(self.style.NOTICE('done.'))
