# Django Binding

Provides server a real time cache for querysets.

A binding will keep a cached queryset and
registers Django signals to update the cache as the models change.

Naturally changes that don't trigger a Django post_save or post_delete will
not cause the cache to be updated.

Also providing binding implementations for:

- [x] DRF
- [ ] django-node-websockets
- [ ] django channels


# Getting started

create a binding:

    from binding import Binding

    # bind all active users
    class UserBinding(Binding):
        filters = dict(active=True)

    users = UserBinding()
    users.all()  # will get a cache of the currently active users
