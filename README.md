# Django Binding

Provides server a real time cache for querysets.

A binding will keep a cached queryset and
registers Django signals to update the cache as the models change.

Naturally changes that don't trigger a Django post_save or post_delete will
not cause the cache to be updated.

Also providing binding implementations for:

  - [x] DRF
  - [x] django-node-websockets
  - [ ] django channels


# Getting started

create a binding:

    from binding import Binding

    # bind all active users
    class UserBinding(Binding):
        filters = dict(active=True)

    users = UserBinding()
    users.all()  # will get a cache of the currently active users


# Django Rest Framework

create a BoundModelViewset and it will automatically cache the queryset and
keep it up to date. When Etags/last modified are supported it will return 304
responses for you automatically:

    class ProductSerializer(Serializer):
        model = Product

    class BoundProductViewset(BoundModelViewSet):
        model = Product
        serializer_class = ProductSerializer

You can also specify a custom binding on the ViewSet:

    class ProductBinding(Binding):
        model = Product

        def filters(self):
            return {"active": true}      

    class BoundProductViewset(BoundModelViewSet):
        binding = ProductBinding
        serializer_class = ProductSerializer


# Django Node Websockets

With websockets you can get instant notification of changes to the queryset.

    class ProductBinding(Binding):
        model = Product

    class ProductWebsocketView(BoundWebsocketView):
        event = "products"
        binding = ProductBinding()
        groups = ["products"]  # specify which group to update

Then hook it up to the event of your choice:

    urlpatterns = patterns(
        '',
        url(r'^products', ProductWebsocketView.as_view()),
    )

From the javascript side emit the choosen event to connect,
emit it again with {disconnect: true} to disconnect.

Listen for the same even to get updates

    // listen for updates
    io.on("products", (data) => {
      // data.action: create, update, delete, sync
      //              sync means that it is giving you the full queryset
      // data.payload: the related data
    });

    // connect and sync
    io.emit("products")

    // disconnect
    io.emit("products", {disconnect: true})
