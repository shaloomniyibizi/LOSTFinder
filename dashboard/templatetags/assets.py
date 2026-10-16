
"""Cache-busted URLs for the project's own static files."""

import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static


register = template.Library()


@register.simple_tag
def asset(path):
    """
    Static URL plus ?v=<last modified time>.

    Browsers may keep reusing a cached stylesheet for a while after it
    changes; a new version number makes them fetch the new file at once.
    """
    url = static(path)
    found = finders.find(path)
    if found:
        url += f"?v={int(os.path.getmtime(found))}"
    return url
