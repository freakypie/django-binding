from __future__ import print_function

import time

from django.core.cache import get_cache
from django.utils import timezone
from django_redis import get_redis_connection


class CacheBase(object):

    def __init__(self, prefix, cache_name="default", timeout=None):
        self.prefix = prefix
        self.cache = get_cache(cache_name)
        self.timeout = timeout

    def get_key(self, name):
        return "{}:{}".format(self.prefix, name)

    def strip_key(self, key):
        return key[len(self.prefix):]

    def get(self, name, default=None):
        return self.cache.get(self.get_key(name), default)

    def set(self, name, value, timeout=None):
        self.cache.set(self.get_key(name), value, timeout or self.timeout)


class CacheDict(CacheBase):

    def get_many(self, keys, default=None):
        many = self.cache.get_many([
            self.get_key(key) for key in keys
        ])
        retval = {}
        for key, value in many.items():
            retval[int(key.rsplit(":")[-1])] = value
        return retval

    def set_many(self, objects, timeout=None):
        sending = {}
        for key, value in objects.items():
            sending[self.get_key(key)] = value
        self.cache.set_many(sending, timeout)

    def incr(self, name, amount=1):
        self.cache.incr(self.get_key(name), 1, self.timeout)

    def expire(self, name, timeout=0):
        self.cache.expire(self.get_key(name), timeout)

    def clear(self):
        self.cache.delete_pattern(self.get_key("*"))

    def pattern(self, p):
        p = self.get_key(p)
        keys = self.cache.keys(p)
        return self.cache.get_many(keys).values()


class CacheArray(CacheBase):

    def __init__(self, prefix, cache_name="default", timeout=None):
        super(CacheArray, self).__init__(prefix, cache_name, timeout)
        self.con = get_redis_connection(cache_name)
        self.array_key = self.get_key("set")

    def add(self, key, value, timeout=None):
        key = self.get_key(key)
        self.con.sadd(self.array_key, key)
        self.cache.set(key, value)

    def remove(self, key, value):
        key = self.get_key(key)
        self.con.srem(self.array_key, key)
        self.cache.delete(key)

    def members(self, prefix=""):
        if prefix:
            prefix = self.get_key(prefix)
        members = self.con.smembers(self.array_key)
        retval = self.cache.get_many(
            [m for m in members if m.startswith(prefix)]).values()
        return retval

    def clear(self):
        members = self.con.smembers(self.array_key)
        for key in members:
            self.cache.delete(key)
            self.con.srem(self.array_key, key)


class Binding(object):
    bindings = CacheArray("binding-list")
    model = None
    filters = {}
    excludes = None

    # no promises this will work without cache or db
    cache_name = "default"
    meta_cache = None
    object_cache = None
    db = True

    @classmethod
    def clear_all(self):
        self.reset_all()
        Binding.bindings.clear()

    @classmethod
    def reset_all(self):
        for binding in Binding.bindings.members():
            binding.clear()

    @classmethod
    def get(self, model, name):
        return self.bindings.get(
            "{}:{}".format(model.__name__, name))

    def __getstate__(self):
        odict = self.__dict__.copy()
        for key in ['bindings', 'meta_cache', 'object_cache']:
            if key in odict:
                del odict[key]
        return odict

    def __setstate__(self, data):
        self.__dict__.update(data)
        self.meta_cache = self.create_meta_cache()
        self.object_cache = self.create_object_cache()

    def __init__(self, model=None, name=None):

        if model:
            self.model = model
        if not name:
            name = self.model.__name__

        self.name = name
        self.meta_cache = self.create_meta_cache()
        self.object_cache = self.create_object_cache()
        self.get_or_start_version()
        self.bindings_key = "{}:{}".format(self.model.__name__, self.name)
        self.register()

    def register(self):
        self.bindings.add(self.bindings_key, self)

    def create_meta_cache(self):
        return CacheDict(
            prefix="binding:meta:{}".format(self.name),
            cache_name=self.cache_name
        )

    def create_object_cache(self):
        return CacheDict(
            prefix="binding:object:{}".format(
                self.model.__name__),
            cache_name=self.cache_name
        )

    def dispose(self):
        home = self.bindings.get(self.model, [])
        if self in home:
            home.remove(self)

    def clear(self, objects=False):
        self.meta_cache.clear()
        if objects:
            self.object_cache.clear()

    def model_saved(self, instance=None, created=None, **kwargs):
        """ save hook called when by signal """
        objects = self.keys()
        if self.model_matches(instance):
            self.save_instance(objects, instance, created)
        elif instance.id in objects:
            self.delete_instance(objects, instance)

    def model_deleted(self, instance=None, **kwargs):
        """ delete hook called when by signal """
        objects = self.keys()
        contained = instance.id in objects
        # print("model deleted", instance)
        if contained:
            self.delete_instance(objects, instance)

    def save_instance(self, objects, instance, created):
        """ called when a matching model is saved """
        serialized = self.serialize_object(instance)
        if instance.id not in objects:
            objects.append(instance.id)
        self.object_cache.set(instance.id, serialized)
        self.meta_cache.set("objects", list(set(objects)))
        self.bump()
        self.message(created and "create" or "update", serialized)

    def delete_instance(self, objects, instance):
        """ called when a matching model is deleted """
        objects.remove(instance.id)
        # self.object_cache.expire(instance.id)
        self.meta_cache.set("objects", objects)
        self.bump()
        self.message("delete", instance)

    def save_many_instances(self, instances):
        """ called when the binding is first attached """
        self.object_cache.set_many(instances)
        self.meta_cache.set("objects", instances.keys())
        self.bump()

    def model_matches(self, instance):
        """ called to determine if the model is part of the queryset """
        for key, value in self.get_filters().items():
            if getattr(instance, key, None) != value:
                return False
        return True

    def get_q(self):
        return tuple()

    def get_filters(self):
        return self.filters

    def get_excludes(self):
        return self.excludes

    def refresh(self, timeout=0):
        db_objects = self._get_queryset_from_db()
        objects = self.meta_cache.get("objects")
        remove_these = set(objects) - set([o.pk for o in db_objects])
        added = removed = 0

        # ensure that all objects are in the list that should be
        for obj in db_objects:
            if obj.pk not in objects:
                self.save_instance(objects, obj, False)
                added += 1
                if timeout: time.sleep(timeout)

        # remove objects from the list that shouldn't be
        for pk in remove_these:
            try:
                obj = self.model.objects.get(pk=pk)
            except self.model.DoesNotExist:
                obj = self.model(pk=pk)
            self.delete_instance(objects, obj)
            removed += 1
            if timeout: time.sleep(timeout)
        return added, removed

    def _get_queryset(self):
        objects = self._get_queryset_from_cache()
        if self.db and objects is None:
            db_objects = self._get_queryset_from_db()
            keys = [o.id for o in db_objects]
            objects = self.object_cache.get_many(keys)
            new_objects = {}
            for o in db_objects:
                if o.id not in objects:
                    objects[o.id] = self.serialize_object(o)
                    new_objects[o.id] = objects[o.id]
            self.object_cache.set_many(new_objects)
            self.meta_cache.set("objects", objects.keys())
            self.bump()
        return objects or {}

    @property
    def cache_key(self):
        return self.meta_cache.get_key("objects")

    def _get_queryset_from_cache(self):
        keys = self.meta_cache.get("objects", None)
        if keys is not None:
            qs = self.object_cache.get_many(keys)
            # print("cache returned:", keys, qs)
            return qs
        return None

    def get_queryset(self):
        return self.model.objects.filter(*self.get_q(), **self.get_filters())

    def _get_queryset_from_db(self):
        qs = self.get_queryset()
        excludes = self.get_excludes()
        if excludes:
            qs = qs.exclude(**excludes)
        # print(
        #     "getting from db:", self.cache_key, qs, "filters",
        #     self.get_filters(), self.get_excludes()
        # )
        return qs

    @property
    def version(self):
        return self.meta_cache.get("version", None)

    def get_or_start_version(self):
        v = self.meta_cache.get("version")
        if not v:
            v = 0
            self.meta_cache.set("version", v)
            self.all()

        lm = self.meta_cache.get("last-modified")
        if not lm:
            self.meta_cache.set("last-modified", timezone.now())

    @property
    def last_modified(self):
        return self.meta_cache.get("last-modified")

    def bump(self):
        # print("\n")
        # import traceback
        # traceback.print_stack()
        # print("*" * 20)
        # print("bumping version", self.version)

        self.meta_cache.set("last-modified", timezone.now())
        try:
            return self.meta_cache.incr("version")
        except ValueError:
            # import traceback
            # traceback.print_stack()
            # print("couldn't get version", self.meta_cache.get("version"))
            self.meta_cache.set("version", 1)
            return 1

    def message(self, action, data, **kwargs):
        pass

    def serialize_object(self, obj):
        return obj

    def serialize(self):
        return dict(
            name=self.name,
            version=self.version,
            last_modified=str(self.last_modified),
        )

    # queryset operations
    def all(self):
        return self._get_queryset()

    def keys(self):
        return self.meta_cache.get("objects") or []
