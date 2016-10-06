
import datetime
import logging
import socket
import time

from celery import shared_task

from .binding import CacheDict

debug = logging.getLogger("debug")


def key(event, groups):
    return "{}.{}.1".format(event, "*".join(groups))


class Pending(object):
    queues = CacheDict("Binding-enqueue")


@shared_task
def enqueue(event, groups, binding, packet, delay=2):
    ident = key(event, groups)
    queue = Pending.queues.get(ident, [])
    queue.append(packet)
    Pending.queues.set(ident, queue)

    timer = str(time.time())
    Pending.queues.set(ident + ":key", timer)
    _process_queue.apply_async(
        (timer, event, groups, binding), countdown=delay)


@shared_task
def _process_queue(timer, event, groups, binding):
    # this should only be run if DNW is installed
    from websockets.utils import get_emitter

    ident = key(event, groups)
    queue = Pending.queues.get(ident, [])
    if len(queue) > 0 and (
        len(queue) > 25 or Pending.queues.get(ident + ":key") == timer
    ):
        try:
            get_emitter().To(groups).Emit(event, {
                "events": queue,
                "server": socket.gethostname(),
                "binding": binding['name'],
                "version": binding['version'],
                "last-modified": str(binding['last_modified']),
            })
        finally:
            Pending.queues.set(ident, [])
