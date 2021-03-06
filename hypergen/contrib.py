# coding=utf-8
from __future__ import (absolute_import, division, unicode_literals)
from functools import wraps

try:
    import cPickle as pickle
except ImportError:
    import pickle

from contextlib2 import contextmanager

from django.urls.base import resolve, reverse
from django.conf.urls import url
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http.response import HttpResponseRedirect
from django.core.exceptions import PermissionDenied

from hypergen.core import (context as c, wrap2, default_wrap_elements, loads, command, hypergen, hypergen_response,
    StringWithMeta)
from hypergen.core import *

d = dict
_URLS = {}
NO_PERM_REQUIRED = "__NO_PERM_REQUIRED__"

def register_view_for_url(func, namespace, base_template, url=None):
    def _reverse(*view_args, **view_kwargs):
        return StringWithMeta(reverse("{}:{}".format(namespace, func.__name__), args=view_args, kwargs=view_kwargs),
            d(base_template=base_template))

    func.reverse = _reverse

    module = func.__module__
    if module not in _URLS:
        _URLS[module] = set()

    if url is None:
        url = r"^{}/$".format(func.__name__)

    _URLS[module].add((func, url))

    return func

@contextmanager
def appstate(app_name, appstate_init):
    if app_name is None or appstate_init is None:
        yield
        return

    k = "hypergen_appstate_{}".format(app_name)
    appstate = c.request.session.get(k, None)
    if appstate is not None:
        appstate = pickle.loads(appstate.encode('latin1'))
    else:
        appstate = appstate_init()
    with c(appstate=appstate):
        yield
        c.request.session[k] = pickle.dumps(c.appstate, pickle.HIGHEST_PROTOCOL).decode('latin1')

@contextmanager
def no_base_template(*args, **kwargs):
    yield

@wrap2
def hypergen_response_decorator(func):
    @wraps(func)
    def _(*args, **kwargs):
        return hypergen_response(func(*args, **kwargs))

    return _

@wrap2
def hypergen_view(func, url=None, perm=None, only_one_perm_required=False, base_template=no_base_template,
    base_template_args=None, base_template_kwargs=None, namespace=None, login_url=None, raise_exception=False,
    target_id=None, app_name=None, appstate_init=None, wrap_elements=default_wrap_elements):

    assert perm is not None or perm == NO_PERM_REQUIRED, "perm is required"
    assert target_id is not None, "target_id required"
    assert namespace is not None, "namespace required"

    if base_template_args is None:
        base_template_args = tuple()
    if base_template_kwargs is None:
        base_template_kwargs = {}

    original_func = func

    # Decorate with permission if required
    if perm != NO_PERM_REQUIRED:
        func = hypergen_permission_required(perm, only_one_perm_required=only_one_perm_required, login_url=login_url,
            raise_exception=raise_exception)(func)

    @wraps(func)
    @hypergen_response_decorator  # Convert Httpresponseredirect from permission_required to ajax commands.
    def _(request, *fargs, **fkwargs):
        path = c.request.get_full_path()
        c.base_template = base_template
        func_return = {}

        @appstate(app_name, appstate_init)
        def wrap_base_template(request, *fargs, **fkwargs):
            with base_template(*base_template_args, **base_template_kwargs):
                func_return["value"] = func(request, *fargs, **fkwargs)
                command("history.replaceState", d(callback_url=path), "", path)

        @appstate(app_name, appstate_init)
        def wrap_view_with_hypergen():
            func_return["value"] = func(request, *fargs, **fkwargs)

        if not c.request.is_ajax():
            fkwargs["wrap_elements"] = wrap_elements
            html = hypergen(wrap_base_template, request, *fargs, **fkwargs)
            if func_return["value"] is not None:
                html = func_return["value"]
            return html
        else:
            commands = hypergen(wrap_view_with_hypergen, target_id=target_id, wrap_elements=wrap_elements)
            if func_return["value"] is not None:
                commands = func_return["value"]

            data = loads(c.request.POST["hypergen_data"])
            if not ("meta" in data and "is_popstate" in data["meta"]
                and data["meta"]["is_popstate"]) and type(commands) in (list, tuple):
                commands.append(command("history.pushState", d(callback_url=path), "", path, return_=True))
            return commands

    _ = ensure_csrf_cookie(_)
    _ = register_view_for_url(_, namespace, base_template, url=url)
    _.original_func = original_func

    return _

@wrap2
def hypergen_callback(func, url=None, perm=None, only_one_perm_required=False, namespace=None, target_id=None,
    login_url=None, raise_exception=False, base_template=None, app_name=None, appstate_init=None, view=None,
    wrap_elements=default_wrap_elements):
    assert perm is not None or perm == NO_PERM_REQUIRED, "perm is required"
    assert namespace is not None, "namespace is required"

    original_func = func

    # Decorate with permission if required.
    if perm != NO_PERM_REQUIRED:
        func = hypergen_permission_required(perm, only_one_perm_required=only_one_perm_required, login_url=login_url,
            raise_exception=raise_exception)(func)

    @wraps(func)
    @hypergen_response_decorator  # Convert Httpresponseredirect from permission_required to ajax commands.
    def _(request, *fargs, **fkwargs):
        # The view that loaded the page the callback is on.
        referer_resolver_match = resolve(c.request.META["HTTP_X_PATHNAME"])

        @appstate(app_name, appstate_init)
        def wrap_view_with_hypergen(func_return, args):
            # Run the callback function.
            func_return["value"] = func(request, *args, **fkwargs)
            if type(func_return["value"]) is not HttpResponseRedirect and view is not None:
                # Render from a view.
                # Allow the view to issue commands. Eg. notifications.
                with c(commands=[], at="hypergen"):
                    view.original_func(request, *referer_resolver_match.args, **referer_resolver_match.kwargs)
                    func_return["commands"] = c.hypergen.commands

        assert c.request.method == "POST", "Only POST request are supported"
        assert c.request.is_ajax()
        # Store base_template for partial loading in the <a> class.
        c.base_template = base_template

        args = list(fargs)
        args.extend(loads(request.POST["hypergen_data"])["args"])
        with c(referer_resolver_match=referer_resolver_match):
            func_return = {}
            commands = hypergen(wrap_view_with_hypergen, func_return, args, target_id=target_id,
                wrap_elements=wrap_elements)
            # Commands are either default hypergen commands or commands from callback
            commands = commands if func_return["value"] is None else func_return["value"]
            # Allow view to add commands
            if type(commands) is not HttpResponseRedirect:
                commands.extend(func_return.get("commands", []))
            return commands

    _ = register_view_for_url(_, namespace, base_template, url=url)
    _ = ensure_csrf_cookie(_)
    _.original_func = original_func
    return _

def hypergen_urls(module):
    patterns = []
    for func, url_ in _URLS.get(module.__name__, []):
        patterns.append(url(url_, func, name=func.__name__))

    return patterns

def hypergen_permission_required(perm, login_url=None, raise_exception=False, only_one_perm_required=False):
    """
    Decorator for views that checks whether a user has a particular permission
    enabled, redirecting to the log-in page if necessary.
    If the raise_exception parameter is given the PermissionDenied exception
    is raised.

    Adds only_one_perm_required parameter on top of Djangos permission_required decorater.
    Writes a set of matched perms to the global context at c.hypergen.matched_perms.
    """
    def check_perms(user):
        if isinstance(perm, str):
            perms = (perm,)
        else:
            perms = perm
        # First check if the user has the permission (even anon users)
        if only_one_perm_required is not True:
            if user.has_perms(perms):
                c.hypergen = c.hypergen.set("matched_perms", set(perms))
                return True
        else:
            matched_perms = set()
            for p in perms:
                if user.has_perm(p):
                    matched_perms.add(p)

            if matched_perms:
                c.hypergen = c.hypergen.set("matched_perms", matched_perms)
                return True

        c.hypergen = c.hypergen.set("matched_perms", set())

        # In case the 403 handler should be called raise the exception
        if raise_exception:
            raise PermissionDenied
        # As the last resort, show the login form
        return False

    return user_passes_test(check_perms, login_url=login_url)
