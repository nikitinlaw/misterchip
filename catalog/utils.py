"""Public formatting and comparison of typed product specifications."""
from decimal import Decimal


def decimal_text(number):
    if number is None:
        return ""
    return format(number.normalize(), "f") if isinstance(number, Decimal) else str(number)


def value_display(value):
    if value is None:
        return "Нет данных"
    kind = value.attribute.data_type
    if kind == "number":
        return f"{decimal_text(value.number_value)} {value.unit}".strip() if value.number_value is not None else "Нет данных"
    if kind == "integer":
        return str(value.integer_value) if value.integer_value is not None else "Нет данных"
    if kind == "boolean":
        return ("Да" if value.boolean_value else "Нет") if value.boolean_value is not None else "Нет данных"
    return value.text_value or "Нет данных"


def comparison_key(value):
    if value is None:
        return None
    kind = value.attribute.data_type
    if kind == "number":
        return value.normalized_number
    if kind == "integer":
        return value.integer_value
    if kind == "boolean":
        return value.boolean_value
    return value.text_value or None
