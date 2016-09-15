from websockets.utils import get_emitter
from websockets.views import WebsocketMixin

from rest_framework.response import Response
from rest_framework.views import APIView

from .tasks import enqueue


class BoundWebsocketMixin(WebsocketMixin):
    event = None
    binding = None
    groups = []

    def get_binding(self):
        return self.binding

    def get_user_group(self):
        return self.groups[0]

    def post(self, request, event=None):

        if self.data.get("disconnect"):
            return Response({
                "event": "__cmd__",
                "leave": [self.get_user_group()]
            })
        else:
            # ensure that we are connected
            # with the outgoing messages of our bidning
            binding = self.get_binding()
            binding.addListener(self.message)

            try:
                version = int(self.data.get("version"))
            except (TypeError, ValueError):
                version = -1

            print("should sync? {} {}".format(version, binding.version))
            if not version or version != binding.version:
                enqueue.delay(
                    self.event,
                    [self.socket_id],
                    binding.serialize(),
                    dict(
                        action="sync",
                        payload=self.serialize(binding.all())
                    )
                )

            return Response({
                "event": "__cmd__",
                "join": [self.get_user_group()]
            })

    @classmethod
    def serialize(self, data):
        return data

    @classmethod
    def message(self, action, data, binding=None):
        binding = binding and binding.serialize() or None
        enqueue.delay(self.event, self.groups, binding, {
            "action": action,
            "payload": self.serialize({data.pk: data}),
        })


class WebsocketView(BoundWebsocketMixin, APIView):
    pass
