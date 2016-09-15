from django.core.cache import get_cache
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
    bindings = {}
    model = None
    filters = {}
    excludes = None

    # no promises this will work without cache or db
    cache_name = "default"
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
            self.cache = CacheDict(
                prefix="Binding:" + self.name,
                cache_name=self.cache_name
            )
            self.get_or_start_version()

        if self.model not in self.bindings:
            self.bindings[self.model] = []
        self.bindings[self.model].append(self)
        # print("binding", Binding.bindings)

    def dispose(self):
        home = self.bindings.get(self.model, [])
        if self in home:
            home.remove(self)

    def model_saved(self, instance=None, created=None, **kwargs):
        # print("model saved", instance)
        objects = self._get_queryset()
        if self.model_matches(instance):
            # print("updating", instance)
            objects[instance.id] = instance
            self.updated(objects)
            self.message(created and "create" or "update", instance)
        elif instance.id in objects:
            self.model_deleted(instance, **kwargs)

    def model_deleted(self, instance=None, **kwargs):
        # print("model deleted", instance)
        objects = self._get_queryset()
        contained = instance.id in objects
        if self.model_matches(instance) or contained:

            if contained:
                del objects[instance.id]
                self.updated(objects)

            # print("deleting", instance)
            self.message("delete", instance)

    def model_matches(self, instance):
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
        return self.cache.get("version", None)

    def get_or_start_version(self):
        v = self.cache.get("version")
        if not v:
            v = 1
            self.cache.set("version", v)

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
            # import traceback
            # traceback.print_stack()
            # print("couldn't get version", self.cache.get("version"))
            self.cache.set("version", 1)
            return 1

    def updated(self, objects):
        # print("updating cache", objects)
        self.cache.set("objects", objects)
        self.bump()

    def all(self):
        return self._get_queryset()

    def addListener(self, l):
        if l not in self.listeners:
            self.listeners.append(l)

    def removeListener(self, l):
        if l in self.listeners:
            self.listeners.remove(l)

    def message(self, action, data):
        for listener in self.listeners:
            listener(action, data, binding=self)

    def serialize(self):
        return dict(
            version=self.version,
            last_modified=str(self.last_modified),
        )
