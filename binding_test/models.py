from django.db import models


class Product(models.Model):
    name = models.CharField(max_length=255)
    venue = models.CharField(max_length=255, choices=(
        ("website", "Website"),
        ("store", "Store"),
    ))
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
