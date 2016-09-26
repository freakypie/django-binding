import sys
import time
import unittest

from django.core.cache import cache
from django.test import TestCase

from binding_test.models import Product

from .. import Binding


class TestBinding(Binding):
    model = Product
    outbox = []

    def message(self, action, data):
        super(TestBinding, self).message(action, data)
        self.outbox.append((action, data))

    # not an override
    def clearMessages(self):
        del self.outbox[:]


class BindingTestCase(TestCase):

    def setUp(self):
        cache.clear()
        self.t1 = Product.objects.create(name="t1", venue="store")
        self.t2 = Product.objects.create(name="t2", venue="store")
        self.t3 = Product.objects.create(name="t3", venue="online")

        self.binding = TestBinding()
        self.binding.clearMessages()

    def tearDown(self):
        self.binding.filters = {}
        Binding.bindings = {}

    def testLargeSetReadWrite(self):
        start = time.time()
        for x in range(100):
            Product.objects.create(
                name="t-{}".format(x), venue="online"
            )
            self.binding.all()
        d = time.time() - start
        sys.stdout.write(" [RW: {:.4}s] - ".format(d))

    def testLargeSetWrite(self):
        start = time.time()
        for x in range(100):
            Product.objects.create(
                name="t-{}".format(x), venue="online"
            )
        d = time.time() - start
        sys.stdout.write(" [W: {:.4}s] - ".format(d))

    def testLargeSetRead(self):
        for x in range(100):
            Product.objects.create(
                name="t-{}".format(x), venue="online"
            )
        start = time.time()
        for x in range(100):
            self.binding.all()
        d = time.time() - start
        sys.stdout.write(" [R: {:.4}s] - ".format(d))

    def testInitialPayload(self):
        # send all objects as they are now page by page
        dataset = self.binding.all()
        for item in [self.t1, self.t2, self.t3]:
            self.assertIn(item.id, dataset)
        self.assertEqual(len(dataset), 3)

    def testLastModifiedUpdated(self):
        dt = self.binding.last_modified
        Product.objects.create(name="t4", venue="online")
        self.assertNotEqual(dt, self.binding.last_modified)

    def testAddSignal(self):
        self.assertEqual(len(self.binding.outbox), 0)
        Product.objects.create(name="t4", venue="online")
        self.assertEqual(len(self.binding.outbox), 1)

    def testDeleteSignal(self):
        self.assertEqual(len(self.binding.outbox), 0)
        self.assertEqual(self.binding.version, 1)
        self.assertEqual(len(self.binding.all().values()), 3)
        self.t3.delete()
        self.assertEqual(self.binding.version, 2)
        self.assertEqual(len(self.binding.outbox), 1)

    def testChangeSignal(self):
        self.assertEqual(len(self.binding.outbox), 0)
        self.t3.name = "Awesome sauce"
        self.t3.save()
        self.assertEqual(len(self.binding.outbox), 1)

    def testDeltaPayload(self):
        # send changes since a given date
        pass

    def testFilteredInitialPayload(self):
        # filter `all`
        self.binding.filters = dict(venue="store")
        self.binding.cache.clear()
        dataset = self.binding.all()
        for item in [self.t1, self.t2]:
            self.assertIn(item.id, dataset)
        self.assertEqual(len(dataset), 2)
        self.assertEqual(self.binding.version, 1)

    def testFilteredAdd(self):
        self.binding.filters = dict(venue="store")
        self.binding.cache.clear()
        self.binding.all()

        self.assertEqual(len(self.binding.outbox), 0)

        # change an object that the binding should ignore
        Product.objects.create(name="t4", venue="garbage")
        self.assertEqual(len(self.binding.outbox), 0)

        # change an object that shouldn't be ignored
        Product.objects.create(name="t4", venue="store")
        self.assertEqual(len(self.binding.outbox), 1)

    def testFilteredChange(self):
        self.binding.filters = dict(venue="store")
        self.binding.cache.clear()
        self.binding.all()

        self.assertEqual(len(self.binding.outbox), 0)

        # change an object that the binding should ignore
        self.t3.name = "Foolish child"
        self.t3.save()
        self.assertEqual(len(self.binding.outbox), 0)

        # change an object that shouldn't be ignored
        self.t1.name = "Chocolate"
        self.t1.save()
        self.assertEqual(len(self.binding.outbox), 1)

    def testFilteredDelete(self):

        # delete object that the binding should ignore
        self.binding.filters = dict(venue="store")
        self.binding.cache.clear()
        self.binding.all()

        self.assertEqual(len(self.binding.outbox), 0)

        # delete an object that the binding should ignore
        self.t3.delete()
        self.assertEqual(len(self.binding.outbox), 0)

        # delete an object that shouldn't be ignored
        self.t1.delete()
        self.assertEqual(len(self.binding.outbox), 1)

    def testFilteredin(self):
        # delete object that the binding should ignore
        self.binding.filters = dict(venue="store")
        self.binding.cache.clear()
        self.binding.all()

        self.assertEqual(len(self.binding.outbox), 0)

        # render queryset to cache and verify size
        self.assertEqual(len(self.binding.all().keys()), 2)

        # change an object that was ignored
        self.t3.venue = "store"
        self.t3.save()

        self.assertEqual(len(self.binding.outbox), 1)
        self.assertEqual(len(self.binding.all().keys()), 3)

    def testFilteredOut(self):
        # delete object that the binding should ignore
        self.binding.filters = dict(venue="store")
        self.binding.cache.clear()
        self.binding.all()

        self.assertEqual(len(self.binding.outbox), 0)

        # render queryset to cache and verify size
        self.assertEqual(len(self.binding.all().keys()), 2)

        # change an object that should now be ignored
        self.t1.venue = "online"
        self.t1.save()

        self.assertEqual(len(self.binding.outbox), 1)
        self.assertEqual(len(self.binding.all().keys()), 1)

    def testDoubleRegisterListener(self):

        def listener(action, data):
            pass

        self.binding.addListener(listener)
        self.binding.addListener(listener)
        self.assertEqual(len(self.binding.listeners), 1)

    def testDoubleRemoveListener(self):

        def listener(action, data, **kwargs):
            pass

        self.binding.addListener(listener)
        self.binding.removeListener(listener)
        self.binding.removeListener(listener)  # no error
        self.assertEqual(len(self.binding.listeners), 0)

    def testDoubleListenerStatic(self):

        class Foo:
            @classmethod
            def listener(action, data, **kwargs):
                pass

        self.binding.addListener(Foo().listener)
        self.binding.addListener(Foo().listener)
        self.assertEqual(len(self.binding.listeners), 1)
        self.binding.removeListener(Foo().listener)
        self.binding.removeListener(Foo().listener)  # no error
        self.assertEqual(len(self.binding.listeners), 0)

    def testListener(self):
        self.listened = 0

        def listener(action, data, **kwargs):
            self.listened += 1
        self.binding.addListener(listener)

        Product.objects.create(name="t4", venue="garbage")
        self.t2.venue = "store"
        self.t2.save()
        self.t3.delete()

        self.assertEqual(self.listened, 3)
