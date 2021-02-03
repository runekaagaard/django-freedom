# coding=utf-8
from __future__ import (absolute_import, division, unicode_literals)

import string, sys
from threading import local
from collections import OrderedDict
from functools import wraps
from copy import deepcopy
from types import GeneratorType

from contextlib2 import ContextDecorator
from django.urls.base import reverse_lazy
from django.http.response import HttpResponse

import freedom
from freedom.utils import insert
from freedom.core import context as c

### Python 2+3 compatibility ###

if sys.version_info.major > 2:
    from html import escape
    letters = string.ascii_letters

    def items(x):
        return x.items()
else:
    from cgi import escape
    letters = string.letters
    str = unicode

    def items(x):
        return x.iteritems()


### Rendering ###
def hypergen_context(**kwargs):
    from freedom.core import namespace as ns
    return ns(
        into=[],
        liveview=True,
        id_counter=base65_counter(),
        id_prefix=(freedom.loads(c.request.body)["id_prefix"]
                   if c.request.is_ajax() else ""),
        event_handler_cache={},
        target_id=kwargs.pop("target_id", "__main__"),
        commands=[], )


def hypergen(func, *args, **kwargs):
    with c(hypergen=hypergen_context(**kwargs)):
        func(*args, **kwargs)
        html = join_html(c.hypergen.into)
        if c.hypergen.event_handler_cache:
            c.hypergen.commands.append([
                "./freedom", ["setEventHandlerCache"],
                [c.hypergen.target_id, c.hypergen.event_handler_cache]
            ])
        if not c.request.is_ajax():
            pos = html.find("</head")
            if pos != -1:
                s = '<script>window.applyCommands({})</script>'.format(
                    freedom.dumps(c.hypergen.commands))
                html = insert(html, s, pos)

            return HttpResponse(html)
        else:
            c.hypergen.commands.append(
                ["./freedom", ["morph"], [c.hypergen.target_id, html]])

            return c.hypergen.commands


### Helpers ###


def join(*values):
    return "".join(str(x) for x in values)


def join_html(html):
    def fmt(html):
        for item in html:
            if issubclass(type(item), base_element):
                yield str(item)
            elif callable(item):
                yield str(item())
            else:
                yield str(item)

    return "".join(fmt(html))


def raw(*children):
    c.hypergen.into.extend(children)


def _sort_attrs(attrs):
    # For testing only, subject to change.
    if attrs.pop("_sort_attrs", False):
        attrs = OrderedDict((k, attrs[k]) for k in sorted(attrs.keys()))
        if "style" in attrs and type(attrs["style"]) is dict:
            attrs["style"] = OrderedDict(
                (k, attrs["style"][k]) for k in sorted(attrs["style"].keys()))

    return attrs


def t(s, quote=True):
    return escape(str(s), quote=quote)


def base65_counter():
    # THX: https://stackoverflow.com/a/49710563/164449
    abc = letters + string.digits + "-_:"
    base = len(abc)
    i = -1
    while True:
        i += 1
        num = i
        output = abc[num % base]  # rightmost digit

        while num >= base:
            num //= base  # move to next digit to the left
            output = abc[num % base] + output  # this digit

        yield output


### Django ###


def callback(func):
    """
    Makes a function a callback for django.
    """
    if "is_test" in c:
        func.hypergen_callback_url = "/path/to/{}/".format(func.__name__)
    else:
        func.hypergen_callback_url = reverse_lazy(
            "freedom:callback",
            args=[".".join((func.__module__, func.__name__))])

    func.hypergen_is_callback = True

    return func


### Base dom element ###
class THIS(object):
    pass


NON_SCALARS = set((list, dict, tuple))
DELETED = ""


class base_element(ContextDecorator):
    js_cb = "H.cbs.s"
    void = False
    auto_id = False

    def __new__(cls, *args, **kwargs):
        instance = ContextDecorator.__new__(cls)
        setattr(instance, "tag", cls.__name__.rstrip("_"))
        return instance

    def __init__(self, *children, **attrs):
        assert "hypergen" in c, "Missing global context: hypergen"
        self.children = children
        self.attrs = attrs
        self.i = len(c.hypergen.into)
        self.sep = attrs.pop("sep", "")
        self.auto_id = self.has_any_liveview_attribute()

        for child in children:
            if issubclass(type(child), base_element):
                c.hypergen.into[child.i] = DELETED
        c.hypergen.into.append(lambda: join_html((self.start(), self.end())))
        super(base_element, self).__init__()

    def __enter__(self):
        c.hypergen.into.append(lambda: self.start())
        c.hypergen.into[self.i] = DELETED
        return self

    def __exit__(self, *exc):
        if not self.void:
            c.hypergen.into.append(lambda: self.end())

    def __str__(self):
        return join_html((self.start(), self.end()))

    def __unicode__(self):
        return self.__str__()

    def format_children(self, children):
        into = []
        sep = t(self.sep)

        for x in children:
            if x in ("", None):
                continue
            elif issubclass(type(x), base_element):
                into.append(str(x))
            elif type(x) in (list, tuple, GeneratorType):
                into.extend(self.format_children(list(x)))
            elif callable(x):
                into.append(x)
            else:
                into.append(t(x))
            if sep:
                into.append(sep)
        if sep and children:
            into.pop()

        return into

    def liveview_attribute(self, args):
        func = args[0]
        assert callable(func), (
            "First callback argument must be a callable, got "
            "{}.".format(repr(func)))
        args = args[1:]

        args2 = []
        for arg in args:
            if type(arg) in NON_SCALARS:
                c.hypergen.event_handler_cache[id(arg)] = arg
                args2.append(
                    freedom.quote("H.e['{}'][{}]".format(
                        c.hypergen.target_id, id(arg))))
            else:
                args2.append(arg)

        print "AAAAAAAAAAAAAAAAAAA", args2
        return "H.cb({})".format(
            freedom.dumps(
                [func.hypergen_callback_url] + list(args2),
                unquote=True,
                escape=True,
                this=self))

    def has_any_liveview_attribute(self):
        return any(self.is_liveview_attribute(*x) for x in items(self.attrs))

    def is_liveview_attribute(self, k, v):
        return c.hypergen.liveview is True and k.startswith("on") and type(
            v) in (list, tuple)

    def attribute(self, k, v):
        k = t(k).rstrip("_").replace("_", "-")
        if self.is_liveview_attribute(k, v):
            return join(" ", k, '="', self.liveview_attribute(v), '"')
        elif type(v) is bool:
            if v is True:
                return join((" ", k))
        elif k == "style" and type(v) in (dict, OrderedDict):
            return join((" ", k, '="', ";".join(
                t(k1) + ":" + t(v1) for k1, v1 in items(v)), '"'))
        else:
            return join(" ", k, '="', t(v), '"')

    def start(self):
        if self.auto_id and "id_" not in self.attrs:
            self.attrs[
                "id_"] = c.hypergen.id_prefix + next(c.hypergen.id_counter)

        into = ["<", self.tag]
        for k, v in items(self.attrs):
            into.append(self.attribute(k, v))

        if self.void:
            into.append(join(("/")))
        into.append(join('>', ))
        into.extend(self.format_children(self.children))

        return join_html(into)

    def end(self):
        if not self.void:
            return "</{}>".format(self.tag)
        else:
            return ""


### Some special dom elements ###

INPUT_CALLBACK_TYPES = dict(
    checkbox="H.cbs.c",
    month="H.cbs.i",
    number="H.cbs.i",
    range="H.cbs.f",
    week="H.cbs.i")


class input_(base_element):
    void = True

    def __init__(self, *children, **attrs):
        self.js_cb = INPUT_CALLBACK_TYPES.get(
            attrs.get("type_", "text"), "H.cbs.s")
        super(input_, self).__init__(*children, **attrs)

    void = True


### Special tags ###


def doctype(type_="html"):
    raw("<!DOCTYPE ", type_, ">")


### TEMPLATE-ELEMENT ###


class div(base_element):
    pass


div.r = div
div.c = div
div.d = div


### TEMPLATE-ELEMENT ###
### TEMPLATE-VOID-ELEMENT ###
class link(base_element):
    void = True


link.r = link
### TEMPLATE-VOID-ELEMENT ###

### RENDERED-ELEMENTS ###

### RENDERED-VOID-ELEMENTS ###
