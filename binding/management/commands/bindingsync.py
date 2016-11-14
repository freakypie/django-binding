from django.core.management.base import BaseCommand, CommandError
from ...binding import Binding


class Command(BaseCommand):
    help = 'Resets all the bindings and send out new versions'

    def handle(self, *args, **options):
        for binding in Binding.bindings.pattern("*"):
            self.stdout.write(" - {}".format(binding.name))
            binding.refresh()
        self.stdout.write(self.style.NOTICE('done.'))
