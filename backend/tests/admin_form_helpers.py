"""Turn a rendered /control/ change page back into the POST a browser would send."""

from django.forms import MultiWidget


def form_data(form, data=None):
    data = {} if data is None else data
    for name, field in form.fields.items():
        if field.disabled:
            continue
        bound = form[name]
        value = bound.value()
        if isinstance(field.widget, MultiWidget):
            parts = value if isinstance(value, (list, tuple)) else field.widget.decompress(value)
            for index, part in enumerate(parts):
                data[f"{bound.html_name}_{index}"] = "" if part is None else str(part)
        elif isinstance(value, bool):
            if value:
                data[bound.html_name] = "on"
        else:
            data[bound.html_name] = "" if value is None else value
    return data


def page_data(response):
    data = form_data(response.context["adminform"].form)
    for inline in response.context["inline_admin_formsets"]:
        form_data(inline.formset.management_form, data)
        for form in inline.formset.forms:
            form_data(form, data)
    return data
