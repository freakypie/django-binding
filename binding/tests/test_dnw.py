import unittest

from django.core.cache import cache
from django.test import TestCase

from binding_test.models import Product

from .. import Binding


class TestBinding(Binding):
    model = Product
    outbox = []

    def message(self, action, data):
        self.outbox.append((action, data))

    # not an override
    def clearMessages(self):
        del self.outbox[:]


class DjangoNodeWebsocketsTestCase(TestCase):
    pass
