
import logging
import time
from hashlib import md5

from celery import shared_task

from .binding import CacheDict

debug = logging.getLogger("debug")


def key(event, groups):
    return md5("{}.{}".format(event, "*".join(groups))).hexdigest()


class Pending(object):
    queues = CacheDict("Binding-enequeue")


@shared_task
def enqueue(event, groups, binding, packet, delay=0.5):
    ident = key(event, groups)
    queue = Pending.queues.get(ident, [])
    queue.append(packet)
    Pending.queues.set(ident, queue)

    timer = str(time.time())
    Pending.queues.set(ident + ":key", timer)
    debug.error("%s: timer set %s", ident, timer)
    _process_queue.apply_async(
        (timer, event, groups, binding, packet), countdown=delay)


@shared_task
def _process_queue(timer, event, groups, binding, packet, delay=0.1):
    # this should only be run if DNW is installed
    from websockets.utils import get_emitter

    ident = key(event, groups)
    queue = Pending.queues.get(ident, [])
    if len(queue) > 0 and (
        len(queue) > 25 or Pending.queues.get(ident + ":key") == timer
    ):
        debug.error("sending: %s", len(queue))
        get_emitter().To(groups).Emit(event, {
            "events": queue,
            "version": binding['version'],
            "last-modified": binding['last_modified'],
        })
        Pending.queues.set(ident, [])
