"""Change one misconfiguration value at a time; never replace an admission guard."""
import sys
from importlib import import_module
from types import FunctionType, SimpleNamespace

from .cases import declaration, imported, matched, url_pattern


def impostor(*args, **kwargs):
    raise AssertionError("A misconfigured declaration reached dispatch")


def clone(function, *, globals_dict=None, closure=None):
    copied = FunctionType(
        function.__code__, function.__globals__ if globals_dict is None else globals_dict,
        function.__name__, function.__defaults__,
        function.__closure__ if closure is None else closure,
    )
    copied.__dict__.update(function.__dict__)
    copied.__qualname__, copied.__module__ = function.__qualname__, function.__module__
    copied.__kwdefaults__ = function.__kwdefaults__
    return copied


def cell(value):
    return (lambda: value).__closure__[0]


def callback_drift(callback, kind):
    if kind == "wrong-callback-class":
        from rest_framework.views import APIView

        return APIView.as_view()
    if kind == "borrowed-metadata":
        # A foreign function with all public DRF metadata is still not the callback.
        copied = FunctionType(impostor.__code__, impostor.__globals__)
        copied.__dict__.update(callback.__dict__)
        copied.__module__, copied.__qualname__ = callback.__module__, callback.__qualname__
        return copied
    if kind == "callback-globals":
        return clone(callback, globals_dict=dict(callback.__globals__))
    copied = clone(callback)
    if kind == "defaults":
        copied.__defaults__ = ("substituted",)
    elif kind == "kwdefaults":
        copied.__kwdefaults__ = {"substituted": True}
    elif kind == "initkwargs":
        copied.initkwargs = {"http_method_names": ["get"]}
    elif kind == "view-initkwargs":
        copied.view_initkwargs = {"http_method_names": ["get"]}
    elif kind == "missing-wrapper":
        del copied.__wrapped__
    elif kind == "closure":
        # Preserve code, globals and borrowed class metadata, but change the actual
        # Django callback's captured class. Repoint the CSRF wrapper to that core.
        core = callback.__wrapped__
        cells = tuple(cell(object) if item.cell_contents is callback.cls else item
                      for item in core.__closure__)
        assert any(a is not b for a, b in zip(cells, core.__closure__))
        wrong_core = clone(core, closure=cells)
        copied = clone(callback, closure=tuple(
            cell(wrong_core) if item.cell_contents is core else item
            for item in callback.__closure__
        ))
        copied.__wrapped__ = wrong_core
    else:
        raise AssertionError(kind)
    return copied


def class_drift(patch, route, kind):
    canonical, alias, _ = declaration(route)
    view = imported(canonical)
    module, name = canonical.rsplit(".", 1)
    if kind == "canonical-class":
        patch.setattr(import_module(module), name, object)
    elif kind == "url-alias":
        module, name = alias.rsplit(".", 1)
        patch.setattr(import_module(module), name, object)
    elif kind == "post-function":
        replacement = FunctionType(impostor.__code__, view.post.__globals__)
        replacement.__module__, replacement.__qualname__ = module, view.post.__qualname__
        patch.setattr(view, "post", replacement)
    elif kind == "post-globals":
        patch.setattr(view, "post", clone(view.post, globals_dict=dict(view.post.__globals__)))
    elif kind == "import-failure":
        patch.setitem(sys.modules, module, None)
    else:
        raise AssertionError(kind)


def binding_drift(patch, route, expression, owner_path, kind):
    post = imported(declaration(route)[0]).post
    module, leaf = owner_path.rsplit(".", 1)
    owner_module = import_module(module)
    if kind == "missing-service":
        patch.delattr(owner_module, leaf)
    elif kind == "noncallable-service":
        patch.setattr(owner_module, leaf, None)
    elif kind == "canonical-service":
        patch.setattr(owner_module, leaf, impostor)
    elif kind in {"consumed-alias", "missing-consumed-alias"}:
        parts = expression.split(".")
        if len(parts) == 2:
            barrel = post.__globals__[parts[0]]
            if kind == "consumed-alias":
                patch.setattr(barrel, parts[1], impostor)
            else:
                patch.delattr(barrel, parts[1])
        elif kind == "consumed-alias":
            patch.setitem(post.__globals__, expression, impostor)
        else:
            patch.delitem(post.__globals__, expression)
    else:
        raise AssertionError(kind)


def replace_callback(patch, route, kind):
    patch.setattr(url_pattern(route), "callback", callback_drift(matched(route).func, kind))


def replace_barrel(patch):
    post = imported(declaration("asset-generate")[0]).post
    service = post.__globals__["services"].generate_assets_with_qr
    patch.setitem(post.__globals__, "services", SimpleNamespace(generate_assets_with_qr=service))
