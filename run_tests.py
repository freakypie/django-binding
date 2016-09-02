import sys

import django
from django.conf import settings
from django.test.runner import DiscoverRunner

settings.configure(
    DEBUG=True,
    USE_TZ=True,
    DATABASES={
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
        }
    },
    # ROOT_URLCONF='binding.urls',
    INSTALLED_APPS=(
        'django.contrib.auth',
        'django.contrib.contenttypes',
        'django.contrib.sessions',
        'django.contrib.admin',
        'binding',
        'binding_test',
    ),
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'django-binding',
        }
    }
)

django.setup()
test_runner = DiscoverRunner(verbosity=1, fail_fast=True, failfast=True)

failures = test_runner.run_tests(['binding'], failfast=True)
if failures:
    sys.exit(failures)
