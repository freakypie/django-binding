import datetime
import time
import unittest

from django.test import TestCase
from django.utils import timezone
from django.utils.http import http_date
from rest_framework.serializers import Serializer
from rest_framework.test import APIRequestFactory
from django.core.cache import cache

from binding_test.models import Product

from ._binding import TestBinding
from ..drf import BoundModelViewSet


class ProductSerializer(Serializer):
    model = Product


class TestBoundModelViewset(BoundModelViewSet):
    model = Product
    serializer_class = ProductSerializer


class BoundModelViewsetTestCase(TestCase):

    def setUp(self):
        cache.clear()
        TestBoundModelViewset.binding = TestBinding()

        self.t1 = Product.objects.create(name="t1", venue="store")
        self.t2 = Product.objects.create(name="t2", venue="store")
        self.t3 = Product.objects.create(name="t3", venue="online")
        self.factory = APIRequestFactory()
        self.viewset = TestBoundModelViewset()
        self.list_view = TestBoundModelViewset.as_view({"get": "list"})
        self.detail_view = TestBoundModelViewset.as_view({"get": "retrieve"})

    def tearDown(self):
        if self.viewset.binding:
            self.viewset.binding.dispose()
        # if self.list_view.binding:
        #     self.viewset.binding.dispose()
        # if self.detail_view.binding:
        #     self.viewset.binding.dispose()

    def api(self, view, method="GET", data={}, headers={}, kwargs={}):
        request = getattr(self.factory, method.lower())(
            "/products/1/",
            data=data,
            **headers
        )
        return view(request, **kwargs)

    def testList(self):
        response = self.api(self.list_view)
        self.assertEqual(response.status_code, 200)

    def testDetail(self):
        response = self.api(self.list_view)
        self.assertEqual(response.status_code, 200)

    def testListNotModified(self):
        dt = timezone.now()

        response = self.api(self.list_view)
        self.assertIsNotNone(response["LAST-MODIFIED"])
        self.assertIsNotNone(response["ETAG"])
        self.assertEqual(response.status_code, 200)

        response = self.api(self.list_view, headers=dict(
            HTTP_IF_MODIFIED_SINCE=http_date(time.mktime(dt.timetuple()))
        ))
        self.assertEqual(response.status_code, 304)

        response = self.api(self.list_view, headers=dict(
            HTTP_IF_NONE_MATCH=str(
                self.viewset.get_binding().version
            )
        ))
        self.assertEqual(response.status_code, 304)

    def testDetailNotModified(self):
        dt = timezone.now()

        response = self.api(self.detail_view, kwargs=dict(pk=1))
        self.assertIsNotNone(response["LAST-MODIFIED"])
        self.assertIsNotNone(response["ETAG"])
        self.assertEqual(response.status_code, 200)

        response = self.api(self.detail_view, kwargs=dict(pk=1), headers=dict(
            HTTP_IF_MODIFIED_SINCE=http_date(time.mktime(dt.timetuple()))
        ))
        self.assertEqual(response.status_code, 304)

        response = self.api(self.detail_view, kwargs=dict(pk=1), headers=dict(
            HTTP_IF_NONE_MATCH=str(
                self.viewset.get_binding().version
            )
        ))
        self.assertEqual(response.status_code, 304)

    def testAdded(self):
        etag = str(self.viewset.get_binding().version)

        Product.objects.create(name="Foo")

        response = self.api(self.list_view, headers=dict(
            HTTP_IF_NONE_MATCH=etag
        ))
        self.assertEqual(response.status_code, 200)

    def testDeleted(self):
        etag = str(self.viewset.get_binding().version)

        self.t1.delete()

        response = self.api(self.list_view, headers=dict(
            HTTP_IF_NONE_MATCH=etag
        ))
        self.assertEqual(response.status_code, 200)

    def testChanged(self):
        etag = str(self.viewset.get_binding().version)

        self.t1.name = "Chocolate"
        self.t1.save()

        response = self.api(self.list_view, headers=dict(
            HTTP_IF_NONE_MATCH=etag
        ))
        self.assertEqual(response.status_code, 200)
