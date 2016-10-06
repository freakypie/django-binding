from django.db.models.signals import post_delete, post_save

from binding.listeners import model_deleted, model_saved
from binding_test.models import Product

from .. import Binding


class TestBinding(Binding):
    model = Product
    outbox = []

    def __init__(self, *args, **kwargs):
        post_save.connect(model_saved, sender=Product)
        post_delete.connect(model_deleted, sender=Product)
        super(TestBinding, self).__init__(*args, **kwargs)

    def message(self, action, data):
        super(TestBinding, self).message(action, data)
        self.outbox.append((action, data))

    # not an override
    def clearMessages(self):
        del self.outbox[:]
