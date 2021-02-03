from __future__ import print_function

import logging
import time
import traceback
import six

from django.core.cache import caches
from django.utils import timezone
from django_redis import get_redis_connection

debug = logging.getLogger("debug")


class CacheBase(object):

    def __init__(self, prefix, cache_name="default", timeout=None):
        self.con = get_redis_connection(cache_name)
        self.prefix = prefix
        self.cache = caches[cache_name]
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
            retval[key.rsplit(":")[-1]] = value
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

    def set_add(self, key, *value):
        key = self.get_key(key)
        retval = self.con.sadd(key, *value)
        if self.timeout:
            self.con.expire(key, self.timeout)
        else:
            self.con.persist(key)
        return retval

    def set_remove(self, key, value):
        return self.con.srem(self.get_key(key), value)

    def set_exists(self, key, value):
        return self.con.sismember(self.get_key(key), value)

    def set_length(self, key):
        return self.con.scard(self.get_key(key))

    def set_all(self, key):
        return self.con.smembers(self.get_key(key))

    def set_clear(self, key):
        return self.con.delete(self.get_key(key))


class CacheArray(CacheBase):

    def __init__(self, prefix, cache_name="default", timeout=None):
        super(CacheArray, self).__init__(prefix, cache_name, timeout)
        self.array_key = self.get_key("set")

    def add(self, key, value, timeout=None):
        key = self.get_key(key)
        self.con.sadd(self.array_key, key)
        self.cache.set(key, value, timeout=timeout or self.timeout)

    def remove(self, key):
        key = self.get_key(key)
        self.con.srem(self.array_key, key)
        self.cache.delete(key)

    def members(self, prefix=""):
        if prefix:
            prefix = self.get_key(prefix)
        members = self.con.smembers(self.array_key)
        keys = [m.decode("utf-8") for m in members if m.decode("utf-8").startswith(prefix)]
        retval = self.cache.get_many(keys).values()

        # extend key life
        # for key in keys:
        #     self.cache.expire(key, self.timeout)

        return retval

    def clear(self):
        members = self.con.smembers(self.array_key)
        for key in members:
            self.cache.delete(key)
            self.con.srem(self.array_key, key)


class Binding(object):
    bindings = CacheArray("binding-list", timeout=4 * 60 * 60)
    model = None
    filters = None
    excludes = None

    # no promises this will work without cache or db
    cache_name = "default"
    meta_cache = None
    object_cache = None
    db = True
    _version = None

    @classmethod
    def clear_all(self, objects=False):
        self.reset_all(objects)
        Binding.bindings.clear()

    @classmethod
    def reset_all(self, objects=False):
        for binding in Binding.bindings.members():
            binding.clear(objects)

    @classmethod
    def get(self, model, name):
        return self.bindings.get(
            "{}:{}".format(model.__name__, name))

    def _unload(self, value):
        n = value
        if isinstance(value, six.binary_type):
            n = value.decode("utf8")
        elif isinstance(value, dict):
            n = {}
            for key in value:
                if isinstance(key, six.binary_type):
                    n[key.decode("utf8")] = self._unload(value[key])
                else:
                    n[key] = self._unload(value[key])
        elif isinstance(value, list):
            n = []
            for v in value:
                if isinstance(v, six.binary_type):
                    n.append(v.decode("utf8"))
                else:
                    n.append(v)
        return n

    def __getstate__(self):
        odict = self.__dict__.copy()
        for key in ['_version', 'bindings', 'meta_cache', 'object_cache']:
            if key in odict:
                del odict[key]
        return odict

    def __setstate__(self, data):
        if six.PY3:
            data = self._unload(data)
        self.__dict__.update(data)
        self.meta_cache = self.create_meta_cache()
        self.object_cache = self.create_object_cache()

    def __init__(self, model=None, name=None):
        if not self.filters:
            self.filters = {}
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

        # redis matches from the first part of the string
        # so we take redis's results and do a direct comparison
        matches = [
            b
            for b in self.bindings.members(self.bindings_key)
            if b.bindings_key == self.bindings_key
        ]
        if len(matches) == 0:
            self.bindings.add(self.bindings_key, self)
            self.refresh()

    def create_meta_cache(self):
        return CacheDict(
            prefix="binding:meta:2:{}".format(self.name),
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
        self.meta_cache.set_clear("objects")
        if objects:
            self.object_cache.clear()

    def get_lookup_field(self):
        return 'id'

    def get_instance_key(self, instance):
        return str(getattr(instance, self.get_lookup_field()))

    def model_saved(self, instance=None, created=None, **kwargs):
        """ save hook called when by signal """
        if self.model_matches(instance):
            self.save_instance(instance, created)
        elif self.meta_cache.set_exists("objects", self.get_instance_key(instance)):
            self.delete_instance(instance)

    def model_deleted(self, instance=None, **kwargs):
        """ delete hook called when by signal """
        self.delete_instance(instance)

    def save_instance(self, instance, created):
        """ called when a matching model is saved """
        serialized = self.serialize_object(instance)
        self.object_cache.set(str(self.get_instance_key(instance)), serialized)
        self.meta_cache.set_add("objects", self.get_instance_key(instance))
        self.bump()
        self.message(created and "create" or "update", serialized)

    def delete_instance(self, instance):
        """ called when a matching model is deleted """
        # self.object_cache.expire(self.get_instance_key(instance))
        if self.meta_cache.set_remove("objects", self.get_instance_key(instance)):
            self.bump()
            self.message("delete", instance)

    def save_many_instances(self, instances):
        """ called when the binding is first attached """
        self.object_cache.set_many(instances)

        changed = False
        for pk in instances.keys():
            changed = self.meta_cache.set_add("objects", pk) or changed

        if changed:
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
        objects = self.meta_cache.set_all("objects") or []
        objects = [k.decode() for k in objects]
        remove_these = set(objects) - set([self.get_instance_key(o) for o in db_objects])
        added = removed = 0

        # ensure that all objects are in the list that should be
        for obj in db_objects:
            key = self.get_instance_key(obj)
            shared = self.object_cache.get(key)
            if key not in objects or not shared:
                # print("  - saving", obj)
                self.save_instance(obj, False)
                added += 1
                if timeout:
                    time.sleep(timeout)

        # remove objects from the list that shouldn't be
        for key in remove_these:
            try:
                lookup = self.get_lookup_field()
                obj = self.model.objects.get(**{lookup: key})
            except self.model.DoesNotExist:
                obj = self.model(**{lookup: key})
            # print("  - delete", obj)
            self.delete_instance(obj)
            removed += 1
            if timeout:
                time.sleep(timeout)
        return added, removed

    def _get_queryset(self):
        objects = self._get_queryset_from_cache()
        if self.db and objects is None:
            db_objects = self._get_queryset_from_db()
            keys = [self.get_instance_key(o) for o in db_objects]
            objects = self.object_cache.get_many(keys)
            new_objects = {}
            for o in db_objects:
                key = self.get_instance_key(o)
                if key not in objects:
                    objects[key] = self.serialize_object(o)
                    new_objects[key] = objects[key]
            self.object_cache.set_many(new_objects)
            if len(objects.keys()):
                self.meta_cache.set_add("objects", *objects.keys())
            self.bump()
        return objects or {}

    @property
    def cache_key(self):
        return self.meta_cache.get_key("objects")

    def _get_queryset_from_cache(self):
        keys = self.meta_cache.set_all("objects") or None
        if keys is not None:
            keys = [k.decode("utf8") for k in keys]
            qs = self.object_cache.get_many(keys)
            # print("cache returned:", keys, qs)
            return qs
        return None

    def get_queryset(self):
        qs = self.model.objects.filter(*self.get_q(), **self.get_filters())
        excludes = self.get_excludes()
        if excludes:
            qs = qs.exclude(**excludes)
        return qs

    def _get_queryset_from_db(self):
        qs = self.get_queryset()
        # print(
        #     "getting from db:", self.cache_key, qs, "filters",
        #     self.get_filters(), self.get_excludes()
        # )
        return qs

    @property
    def version(self):
        if not self._version:
            self._version = self.meta_cache.get("version", None)
        return self._version

    def get_or_start_version(self):
        v = self.version
        if not v:
            v = 0
            self.meta_cache.set("version", v)
            self._version = None
            self.all()

        lm = self.last_modified
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
        self._version = None
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
        return self.meta_cache.set_all("objects") or []
