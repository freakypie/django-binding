import hashlib
import time

from django.http import HttpResponse, Http404
from django.utils import timezone
from django.views.decorators.http import condition
from rest_framework.serializers import Serializer
from rest_framework.viewsets import ModelViewSet

from . import Binding


class BindingMixin(object):
    binding = None

    def get_binding(self):
        if self.binding:
            return self.binding
        elif self.model:
            self.binding = Binding(model=self.model)
            return self.binding
        raise Exception("No binding found on view")

    def get_queryset(self):
        return self.get_binding().all().values()

    def conditional(self, func):
        return condition(
            last_modified_func=self.last_modified_func,
            etag_func=self.get_etag
        )(func)

    def last_modified_func(self, request, pk=None):
        return self.get_binding().last_modified

    def get_etag(self, request, pk=None):
        return str(self.get_binding().version)

    def get_object(self):
        self.object = self.get_binding().all().get(self.kwargs['pk'])
        if not self.object:
            raise Http404()
        return self.object

    def retrieve(self, request, *args, **kwargs):
        return self.conditional(
            super(BindingMixin, self).retrieve
        )(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        return self.conditional(
            super(BindingMixin, self).list
        )(request, *args, **kwargs)


class BoundModelViewSet(BindingMixin, ModelViewSet):
    pass
