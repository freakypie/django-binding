from django import apps


class BindingAppConfig(apps.AppConfig):
    name = "binding"

    def ready(self):
        from . import listeners
