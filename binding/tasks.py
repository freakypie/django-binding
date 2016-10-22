
import datetime
import logging
import math
import socket
import time

from celery import shared_task
from django.core.cache import cache

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
                cache.set(_key, kwargs[kwargs_key], timeout=timeout*2)
                inner.apply_async(args, kwargs, countdown=timeout)
            elif cache.get(_key) == kwargs.get(kwargs_key):
                kwargs.pop(kwargs_key)
                function(*args, **kwargs)
        return inner
    return outer


def debounced_model_saved_key(binding, instance_id, **kwargs):
    return "{}:{}".format(binding.name, instance_id)


@debounce(timeout=1.0, key=debounced_model_saved_key)
def debounced_model_saved(binding, instance_id):
    binding.model_saved(instance=binding.model.objects.get(id=instance_id))


@shared_task
def send_sync(binding, group=None, sleep_interval=0.1, page_size=100):

    if cache.add("sync-{}".format(group), 1, 5 * 60):
        keys = binding.keys()
        count = len(keys)
        pages = int(math.ceil(count / float(page_size)))
        for page in range(pages):
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
            if sleep_interval:
                time.sleep(sleep_interval)
        time.sleep(sleep_interval)
        send_message(
            binding,
            dict(
                action="sync",
                payload="ok",
                pages=pages
            ),
            group=group
        )
    else:
        send_message(
            binding,
            dict(
                action="sync",
                payload="ok"
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
