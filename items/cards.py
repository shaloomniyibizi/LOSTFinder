
"""Data for the report card (templates/items/_report_card.html)."""

from django.templatetags.static import static


FALLBACK_IMAGES = [f"image/item_{n}.jpg" for n in range(1, 7)]


def report_card(item, kind):
    """
    Flatten a lost or found report for the shared report card.

    Items without a photo get a placeholder chosen by their id, so the same
    item shows the same picture on the home page and in the lists.
    """
    is_lost = kind == "lost"

    placeholder = static(FALLBACK_IMAGES[item.pk % len(FALLBACK_IMAGES)])
    image_url = item.image.url if item.image else placeholder

    return {
        "item": item,
        "kind": kind,
        "image_url": image_url,
        # Used if an uploaded photo is missing from storage.
        "placeholder_url": placeholder,
        "report_date": item.date_lost if is_lost else item.date_found,
        "detail_url_name": "lost_item_detail" if is_lost else "found_item_detail",
    }
