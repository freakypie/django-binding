from django.core.cache import get_cache
from django.utils import timezone


class CacheDict(object):

    def __init__(self, prefix, cache_name="default", timeout=None):
        self.prefix = prefix
        self.cache = get_cache(cache_name)
        self.timeout = timeout
        self.hasExpire = getattr(self.cache, "expire", None)

    def get_key(self, name):
        return "{}:{}".format(self.prefix, name)

    def get(self, name, default=None):
        return self.cache.get(self.get_key(name), default)

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

    def set(self, name, value):
        self.cache.set(self.get_key(name), value, self.timeout)

    def incr(self, name, amount=1):
        self.cache.incr(self.get_key(name), 1, self.timeout)

    def expire(self, name, timeout=0):
        if self.hasExpire:
            self.cache.expire(self.get_key(name), timeout)

    def clear(self):
        self.cache.delete_pattern(self.get_key("*"))


class Binding(object):
    bindings = {}
    model = None
    filters = {}
    excludes = None

    # no promises this will work without cache or db
    cache_name = "default"
    meta_cache = None
    object_cache = None
    db = True
    listeners = None

    def __init__(self, model=None, name=None):
        self.listeners = []

        if model:
            self.model = model
        if not name:
            name = self.model.__name__

        self.name = name

        if self.cache_name:
            self.meta_cache = self.create_meta_cache()
            self.object_cache = self.create_object_cache()
            self.get_or_start_version()
            self.all()

        if self.model not in self.bindings:
            self.bindings[self.model] = []
        self.bindings[self.model].append(self)
        # print("binding", Binding.bindings)

    def create_meta_cache(self):
        return CacheDict(
            prefix="binding:meta:{}".format(self.name),
            cache_name=self.cache_name
        )

    def create_object_cache(self):
        return CacheDict(
            prefix="binding:object:{}".format(self.model.__name__),
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
        # print("model saved", instance)
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
        objects.append(instance.id)
        self.object_cache.set(instance.id, serialized)
        self.meta_cache.set("objects", objects)
        self.bump()
        self.message(created and "create" or "update", serialized)

    def delete_instance(self, objects, instance):
        """ called when a matching model is deleted """
        objects.remove(instance.id)
        self.object_cache.expire(instance.id)
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

    def _get_queryset(self):
        objects = self._get_queryset_from_cache()
        if self.db and objects is None:
            objects = dict([
                (o.id, self.serialize_object(o))
                for o in self._get_queryset_from_db()
            ])
            self.save_many_instances(objects)
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

    def _get_queryset_from_db(self):
        qs = self.model.objects.filter(*self.get_q(), **self.get_filters())
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

    def addListener(self, l):
        if l not in self.listeners:
            self.listeners.append(l)

    def removeListener(self, l):
        if l in self.listeners:
            self.listeners.remove(l)

    def message(self, action, data):
        for listener in self.listeners:
            listener(action, data, binding=self)

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
