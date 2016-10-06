from websockets.utils import get_emitter
from websockets.views import WebsocketMixin

from rest_framework.response import Response
from rest_framework.views import APIView

from .tasks import enqueue
from .binding import Binding


class WebsocketBinding(Binding):
    update_delay = 1
    sync_delay = 0.1
    group = None
    event = None

    def get_user_group(self):
        return self.group

    def serialize_message(self, action, data, binding=None):
        if action == "delete":
            return [{"id": data.id}]
        if action == "update":
            return [data]
        return data.values()

    def message(self, action, data, whom=None):
        if action == "sync":
            print("sending sync message", action, whom, self.event, self.get_user_group())
        else:
            print("sending message", action, data, self.event, self.get_user_group())
        enqueue.delay(
            self.event,
            [whom or self.get_user_group()],
            self.serialize(),
            dict(
                action=action,
                payload=self.serialize_message(action, data),
            ),
            delay=self.update_delay
        )


class BoundWebsocketMixin(WebsocketMixin):
    binding = None

    def get_binding(self):
        return self.binding

    def post(self, request, event=None):
        binding = self.get_binding()

        if self.data.get("disconnect"):
            return Response({
                "event": "__cmd__",
                "leave": [binding.get_user_group()]
            })
        else:
            try:
                version = int(self.data.get("version"))
            except (TypeError, ValueError):
                version = -1

            if not version or version != binding.version:
                binding.message("sync", binding.all(), whom=self.socket_id)

            print("joining group", binding.get_user_group())
            return Response({
                "event": "__cmd__",
                "join": [binding.get_user_group()]
            })


class WebsocketView(BoundWebsocketMixin, APIView):
    pass
