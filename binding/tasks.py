
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
        debug.info("debouncing function: %s", function)

        @shared_task(name=function.__name__)
        def inner(*args, **kwargs):
            _key = "debounce:{}".format(key(*args, **kwargs))
            if kwargs_key not in kwargs:
                kwargs[kwargs_key] = str(time.time())
                cache.set(_key, kwargs[kwargs_key], timeout=timeout)
                debug.info("debouncing: %s %s", function.__name__, kwargs[kwargs_key])
                inner.apply_async(args, kwargs, countdown=timeout)
            elif cache.get(_key) in [None, kwargs.get(kwargs_key)]:
                kwargs.pop(kwargs_key)
                debug.info("running: %s", function.__name__)
                function(*args, **kwargs)
                cache.delete(_key)
            else:
                debug.info("debounced: %s %s!=%s", function.__name__, cache.get(_key), kwargs.get(kwargs_key))
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
    debug.info("sending page: {}".format(page))
    if page < pages:
        send_message(
            binding,
            dict(
                action="sync",
                payload=binding.object_cache.get_many(
                    keys[page * page_size: (page + 1) * page_size]
                ).values(),
                page=page + 1,
                pages=pages
            ),
            group=group
        )
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
