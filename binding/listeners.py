from django.db.models.signals import post_delete, post_save
from .binding import Binding

###
#  I've discovered that sometimes the signal handlers won't trigger
# if they are manually registered as bindings are created
# i think this is due the multi-process nature of most webservers
# so the one process that it is registered on will get a signal handler
# registered but the others won't.
#
# Thusly they are registered here and divide the work amoung bindings
###


def get_bindings(model):
    return Binding.bindings.pattern(model.__name__ + ":*") or []


# def model_saved(sender=None, instance=None, **kwargs):
#     for binding in get_bindings(sender):
#         binding.model_saved(sender=sender, instance=instance, **kwargs)
#         # print("{}:{} saved".format(sender, instance), binding)
# post_save.connect(model_saved, dispatch_uid="binding-post-save")
#
#
# def model_deleted(sender=None, instance=None, **kwargs):
#     for binding in get_bindings(sender):
#         binding.model_deleted(sender=sender, instance=instance, **kwargs)
#         # print("{}:{} deleted".format(sender.__name__, instance), binding)
# post_delete.connect(model_deleted, dispatch_uid="binding-post-delete")
