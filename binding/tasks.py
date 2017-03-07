
import datetime
import logging
import math
import socket
import time

from celery import shared_task
from django.core.cache import cache
from .listeners import get_bindings

debug = logging.getLogger("debug")


def debounce_key(*args, **kwargs):
    return "x"


def debounce(timeout=0.5, key=debounce_key, kwargs_key="_ident"):

    def outer(function):
        # debug.debug("debouncing function: %s", function)

        @shared_task(name=function.__name__)
        def inner(*args, **kwargs):
            _key = "debounce:{}".format(key(*args, **kwargs))
            if kwargs_key not in kwargs:
                kwargs[kwargs_key] = str(time.time())
                cache.set(_key, kwargs[kwargs_key], timeout=timeout)
                # debug.debug("debouncing: %s %s", function.__name__, kwargs[kwargs_key])
                inner.apply_async(args, kwargs, countdown=timeout)
            elif cache.get(_key) in [None, kwargs.get(kwargs_key)]:
                kwargs.pop(kwargs_key)
                # debug.info("running: %s", function.__name__)
                function(*args, **kwargs)
                cache.delete(_key)
            # else:
                # debug.debug("debounced: %s %s!=%s", function.__name__, cache.get(_key), kwargs.get(kwargs_key))
        return inner
    return outer


def model_saved_key(sender, instance_id, **kwargs):
    return "{}:{}".format(sender.__name__, instance_id)


@debounce(timeout=0.5, key=model_saved_key)
def model_saved(sender, instance_id):
    instance = sender.objects.get(id=instance_id)
    for binding in get_bindings(sender):
        binding.model_saved(sender=sender, instance=instance)


def send_sync_key(binding, group=None, **kwargs):
    return "sync-{}".format(group)


@debounce(timeout=0.5, key=send_sync_key)
def send_sync(binding, group=None, page=1, sleep_interval=0.1, page_size=100):
    if not page:
        page = 1
    keys = binding.keys()
    count = len(keys)
    pages = int(math.ceil(count / float(page_size)))
    page = page - 1
    debug.info("sending page: {}/{}".format(page, pages))
    if page < pages:
        page_keys = keys[page * page_size: (page + 1) * page_size]
        page_objects = binding.object_cache.get_many(page_keys)

        try:
            send_message(
                binding,
                dict(
                    action="sync",
                    payload=page_objects.values(),
                    page=page + 1,
                    pages=pages
                ),
                group=group
            )
        except TypeError:
            # if msgpack throws a type error, something is not json`able
            # clear objects force them to recache
            page_objects = []

        # fix missing objects
        # in case the cache is damaged
        for key in page_keys:
            if key not in page_objects:
                debug.error("key missing %s", key)
                try:
                    obj = binding.model.objects.get(pk=key)
                    if binding.model_matches(obj):
                        binding.save_instance(keys, obj, False)
                    else:
                        binding.delete_instance(keys, obj)
                except binding.model.DoesNotExist:
                    obj = binding.model(pk=key)
                    binding.delete_instance(keys, obj)

    else:
        send_message(
            binding,
            dict(
                action="sync",
                payload="ok",
                pages=pages
            ),
            group=group
        )


def send_message(binding, packet, group=None):
    # this should only be run if DNW is installed
    from websockets.utils import get_emitter

    if not group:
        group = binding.get_user_group()

    get_emitter().To([group]).Emit(binding.event, {
        "events": [packet],
        "server": socket.gethostname(),
        "binding": binding.name,
        "version": binding.version,
        "last-modified": str(binding.last_modified),
    })

enqueue = send_message
