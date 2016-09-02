import time

from django.core.cache import get_cache
from django.db.models.signals import post_delete, post_save
from django.utils import timezone


class CacheDict(object):

    def __init__(self, prefix, cache_name="default", timeout=None):
        self.prefix = prefix
        self.cache = get_cache(cache_name)
        self.timeout = timeout

    def get_key(self, name):
        return "{}:{}".format(self.prefix, name)

    def get(self, name, default=None):
        return self.cache.get(self.get_key(name), default)

    def set(self, name, value):
        self.cache.set(self.get_key(name), value, self.timeout)

    def incr(self, name, amount=1):
        self.cache.incr(self.get_key(name), 1, self.timeout)


class Binding(object):
    model = None
    filters = {}
    excludes = None

    # no promises this will work without cache or db
    cache_name = "default"
    db = True

    def __init__(self, model=None, name=None):
        if model:
            self.model = model
        if not name:
            name = self.model.__name__

        self.name = name

        if self.cache_name:
            self.cache = CacheDict(
                prefix="Binding:" + self.name,
                cache_name=self.cache_name
            )
            self.get_or_start_version()

        post_save.connect(
            self.model_saved,
            sender=self.model,
            weak=False,
            dispatch_uid="binding:{}:save".format(self.name))
        post_delete.connect(
            self.model_deleted,
            sender=self.model,
            weak=False,
            dispatch_uid="binding:{}:delete".format(self.name))

    def dispose(self):
        count = 0
        count += post_save.disconnect(
            sender=self.model,
            dispatch_uid="binding:{}:save".format(self.name))
        count += post_delete.disconnect(
            sender=self.model,
            dispatch_uid="binding:{}:delete".format(self.name))
        # print("disposed (should be 2):", count)

    def model_saved(self, instance=None, created=None, **kwargs):
        # print("model saved", instance)
        objects = self._get_queryset()
        if self.model_matches(instance):
            self.message(created and "create" or "update", instance)
            objects[instance.id] = instance
            self.updated(objects)
        elif instance.id in objects:
            self.model_deleted(instance, **kwargs)

    def model_deleted(self, instance=None, **kwargs):
        objects = self._get_queryset()
        if self.model_matches(instance) or instance.id in objects:
            self.message("delete", instance)

            if instance.id in objects:
                del objects[instance.id]
                self.updated(objects)

    def model_matches(self, instance):
        for key, value in self.get_filters().items():
            if getattr(instance, key, None) != value:
                return False
        return True

    def get_filters(self):
        return self.filters

    def get_excludes(self):
        return self.excludes

    def _get_queryset(self):
        objects = None
        if self.cache:
            objects = self._get_queryset_from_cache()
        if self.db and objects is None:
            objects = dict([
                (o.id, o) for o in self._get_queryset_from_db()
            ])
            self.updated(objects)
        return objects or {}

    @property
    def cache_key(self):
        return self.cache.get_key("objects")

    def _get_queryset_from_cache(self):
        qs = self.cache.get("objects", None)
        # print("cache returned:", qs)
        return qs

    def _get_queryset_from_db(self):
        qs = self.model.objects.filter(**self.get_filters())
        excludes = self.get_excludes()
        if excludes:
            qs = qs.exclude(**excludes)
        # print("getting from db:", qs)
        return qs

    @property
    def version(self):
        return self.cache.get("version", None)

    def get_or_start_version(self):
        v = self.cache.get("version")
        if not v:
            v = 1
            self.cache.set("version", v)
            print("initializing version", self.cache.get_key("version"), v)

        lm = self.cache.get("last-modified")
        if not lm:
            self.cache.set("last-modified", timezone.now())

    @property
    def last_modified(self):
        return self.cache.get("last-modified")

    def bump(self):
        self.cache.set("last-modified", timezone.now())
        try:
            return self.cache.incr("version")
        except ValueError:
            import traceback
            traceback.print_stack()
            print("couldn't get version", self.cache.get("version"))
            self.cache.set("version", 1)
            return 1

    def updated(self, objects):
        # print("updating cache", objects)
        self.cache.set("objects", objects)
        self.bump()

    def all(self):
        return self._get_queryset()

    def message(self, action, data):
        # print()
        # import traceback
        # traceback.print_stack()
        # print()
        # print("!!! base message function", action, data)
        return None
