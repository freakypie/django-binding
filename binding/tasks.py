
import datetime
import logging
import socket
import time
import math

from django.core.cache import cache
from celery import shared_task

debug = logging.getLogger("debug")


@shared_task
def send_sync(binding, group=None, sleep_interval=0.01, page_size=100):
    if True:  # cache.add("sync-{}".format(group), 1, 5 * 60):
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
