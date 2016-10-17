from websockets.views import WebsocketMixin

from rest_framework.response import Response
from rest_framework.views import APIView

from .tasks import send_message, send_sync
from .binding import Binding


class WebsocketBinding(Binding):
    update_delay = 1
    sync_delay = 0.1
    page_size = 25
    group = None
    event = None

    def get_user_group(self):
        return self.group

    def serialize_message(self, action, data):
        if action == "delete":
            return [{"id": data.id}]
        if action == "update":
            return [data]
        return data.values()

    def message(self, action, data, whom=None):
        if action == "ok":
            send_message(
                self,
                dict(action="sync", payload="ok"),
                whom
            )
        elif action == "sync":
            send_sync.delay(
                self,
                group=whom,
                page_size=self.page_size,
                sleep_interval=self.sync_delay)
        else:
            send_message(
                self,
                dict(
                    action=action,
                    payload=self.serialize_message(action, data)
                ),
                whom
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
                binding.message("sync", None, whom=self.socket_id)
            else:
                binding.message("ok", None, whom=self.socket_id)

            return Response({
                "event": "__cmd__",
                "join": [binding.get_user_group()]
            })


class WebsocketView(BoundWebsocketMixin, APIView):
    pass
