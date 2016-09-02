#!/bin/bash
echo $PATh
rerun --ignore ".tox" --ignore "django_binding.egg-info" --ignore "MANIFEST" --verbose "tox -e py34"
