import sys
import time

from django.core.cache import cache
from django.test import TestCase

from binding_test.models import Product

from ._binding import TestBinding
from ..binding import CacheDict, CacheArray


class CacheDictTestCase(TestCase):

    def testPatternSpeed(self):
        a = CacheDict("a")
        b = CacheArray("b")

        # when there are a lot of unrelated keys:
        # slow slow slow
        for x in range(20000):
            cache.set("c:{}".format(x), x)

        for x in range(100):
            a.set(x, x)
            b.add(x, x)

        start = time.time()
        for x in range(1):
            a.pattern("11*")
        print("cache A:", time.time() - start)

        start = time.time()
        for x in range(1):
            b.members("11")
        print("cache B:", time.time() - start)

        start = time.time()
        for x in range(1):
            [
                a.cache.get(key)
                for key in a.cache.iter_keys(a.get_key("11*"))
            ]
        print("cache C:", time.time() - start)



class BindingTestCase(TestCase):

    def setUp(self):
        cache.clear()
        self.t1 = Product.objects.create(name="t1", venue="store")
        self.t2 = Product.objects.create(name="t2", venue="store")
        self.t3 = Product.objects.create(name="t3", venue="online")

        TestBinding.bindings.clear()
        self.binding = TestBinding()
        self.binding.clearMessages()

    def tearDown(self):
        self.binding.filters = {}

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
        self.binding.clear()
        dataset = self.binding.all()
        for item in [self.t1, self.t2]:
            self.assertIn(item.id, dataset)
        self.assertEqual(len(dataset), 2)
        self.assertEqual(self.binding.version, 1)

    def testFilteredAdd(self):
        self.binding.filters = dict(venue="store")
        self.binding.register()
        self.binding.clear()
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
        self.binding.register()
        self.binding.clear()
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
        self.binding.register()
        self.binding.clear()
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
        self.binding.register()
        self.binding.clear()
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
        self.binding.register()
        self.binding.clear()
        self.binding.all()

        self.assertEqual(len(self.binding.outbox), 0)

        # render queryset to cache and verify size
        self.assertEqual(len(self.binding.all().keys()), 2)

        # change an object that should now be ignored
        self.t1.venue = "online"
        self.t1.save()

        self.assertEqual(len(self.binding.outbox), 1)
        self.assertEqual(len(self.binding.all().keys()), 1)
