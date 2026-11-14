from django import template

register = template.Library()


@register.filter
def pct(value):
    """0.9123 -> "91.2%"; missing values show a dash."""
    if value is None or value == "":
        return "–"
    return f"{float(value) * 100:.1f}%"


@register.filter
def pct_number(value):
    """0.9123 -> 91.2, for CSS widths."""
    return f"{float(value or 0) * 100:.1f}"
