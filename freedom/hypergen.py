# coding=utf-8
from __future__ import (absolute_import, division, unicode_literals)

d = dict

import string, sys, time
from collections import OrderedDict
from types import GeneratorType
from functools import wraps
from copy import deepcopy
import datetime, json

from contextlib2 import ContextDecorator, contextmanager
from pyrsistent import m

from django.urls import reverse_lazy, resolve
from django.conf.urls import url
from django.http.response import HttpResponse, HttpResponseRedirect
from django.utils.encoding import force_text

from freedom.core import context as c, insert, wrap2

### Python 2+3 compatibility ###

def make_string(x):
    if x is not None:
        return force_text(x)
    else:
        return ""

if sys.version_info.major > 2:
    from html import escape
    letters = string.ascii_letters
    unicode = str

    def items(x):
        return x.items()
else:
    from cgi import escape
    letters = string.letters

    def items(x):
        return x.iteritems()

### Rendering ###
def default_wrap_elements(init, self, *children, **attrs):
    return init(self, *children, **attrs)

def hypergen_context(**kwargs):
    return m(into=[], liveview=True, id_counter=base65_counter(),
        id_prefix=(loads(c.request.POST["hypergen_data"])["id_prefix"] if c.request.is_ajax() else ""),
        event_handler_cache={}, target_id=kwargs.get("target_id",
        "__main__"), commands=[], ids=set(), wrap_elements=kwargs.get("wrap_elements", default_wrap_elements))

def hypergen(func, *args, **kwargs):
    a = time.time()
    kwargs = deepcopy(kwargs)
    target_id = kwargs.pop("target_id", "__main__")
    wrap_elements = kwargs.pop("wrap_elements", default_wrap_elements)
    with c(hypergen=hypergen_context(target_id=target_id, wrap_elements=wrap_elements, **kwargs)):
        func(*args, **kwargs)
        html = join_html(c.hypergen.into)
        if c.hypergen.event_handler_cache:
            command("hypergen.setEventHandlerCache", c.hypergen.target_id, c.hypergen.event_handler_cache)
        if not c.request.is_ajax():
            pos = html.find("</head")
            if pos != -1:
                s = "<script>$(() => window.applyCommands(JSON.parse('{}', reviver)))</script>".format(
                    dumps(c.hypergen.commands))
                html = insert(html, s, pos)
            print("Execution time:", time.time() - a)
            return html
        else:
            command("hypergen.morph", c.hypergen.target_id, html)
            print("Execution time:", time.time() - a)
            return c.hypergen.commands

def hypergen_response(html_or_commands_or_http_response):
    value = html_or_commands_or_http_response
    if isinstance(value, HttpResponseRedirect):
        if c.request.is_ajax():
            return HttpResponse(dumps([["hypergen.redirect", value["Location"]]]), status=200,
                content_type='application/json')
        else:
            return value
    elif isinstance(value, HttpResponse):
        if c.request.is_ajax():
            raise Exception("TODO")
        else:
            return value
    elif type(value) in (list, tuple):
        return HttpResponse(dumps(value), status=200, content_type='application/json')
    elif type(value) in (str, unicode):
        return HttpResponse(value)
    else:
        raise Exception("Invalid response value")

def hypergen_as_response(func, *args, **kwargs):
    return hypergen_response(hypergen(func, *args, **kwargs))

def command(javascript_func_path, *args, **kwargs):
    prepend = kwargs.pop("prepend", False)
    return_ = kwargs.pop("return_", False)
    item = [javascript_func_path] + list(args)
    if return_:
        return item
    elif prepend:
        c.hypergen.commands.insert(0, item)
    else:
        c.hypergen.commands.append(item)

### Helpers ###
class LazyAttribute(object):
    def __init__(self, k, v):
        self.k = k
        self.v = v

    def __str__(self):
        if not self.v:
            return ""
        else:
            return ' {}="{}"'.format(t(self.k), t(self.v))

    def __unicode__(self):
        return self.__str__()

def join(*values):
    return "".join(make_string(x) for x in values)

def join_html(html):
    def fmt(html):
        for item in html:
            if issubclass(type(item), base_element):
                yield item.as_string()
            elif callable(item):
                yield item()
            elif type(item) is GeneratorType:
                with c(at="hypergen", into=[]):
                    yield join_html(item)
            else:
                yield item

    return "".join(make_string(x) for x in fmt(html))

def raw(*children):
    c.hypergen.into.extend(children)

def _sort_attrs(attrs):
    # For testing only, subject to change.
    if attrs.pop("_sort_attrs", False):
        attrs = OrderedDict((k, attrs[k]) for k in sorted(attrs.keys()))
        if "style" in attrs and type(attrs["style"]) is dict:
            attrs["style"] = OrderedDict((k, attrs["style"][k]) for k in sorted(attrs["style"].keys()))

    return attrs

def t(s, quote=True):
    return escape(make_string(s), quote=quote)

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

### Actions happening on the frontend  ###

def callback(url_or_view, *cb_args, **kwargs):
    debounce = kwargs.pop("debounce", 0)
    confirm_ = kwargs.pop("confirm", False)
    blocks = kwargs.pop("blocks", False)
    upload_files = kwargs.pop("upload_files", False)
    event_matches = kwargs.pop("event_matches", False)
    clear = kwargs.pop("clear", False)
    assert not kwargs, "Invalid callback kwarg(s): {}".format(repr(kwargs))

    if callable(url_or_view):
        assert hasattr(url_or_view, "reverse") and callable(
            url_or_view.reverse), "Must have a reverse() attribute {}".format(url_or_view)
        url = url_or_view.reverse()
    else:
        url = url_or_view

    def to_html(element, k, v):
        def fix_this(x):
            return element if x is THIS else x

        element.ensure_id()
        cmd = command(
            "hypergen.callback", url, [fix_this(x) for x in cb_args],
            d(debounce=debounce, confirm_=confirm_, blocks=blocks, uploadFiles=upload_files, clear=clear,
            elementId=element.attrs["id_"].v), return_=True)
        cmd_id = id(cmd)

        c.hypergen.event_handler_cache[cmd_id] = cmd

        if event_matches:
            em = ", {}".format(escape(dumps(event_matches)))
        else:
            em = ""
        return [" ", t(k), '="', "e(event, '{}',{}{})".format(c.hypergen.target_id, cmd_id, em), '"']

    return to_html

def call_js(command_path, *cb_args):
    def to_html(element, k, v):
        def fix_this(x):
            return element if x is THIS else x

        element.ensure_id()
        cmd = command(command_path, *[fix_this(x) for x in cb_args], return_=True)
        cmd_id = id(cmd)
        c.hypergen.event_handler_cache[cmd_id] = cmd

        return [" ", t(k), '="', "e(event, '{}',{})".format(c.hypergen.target_id, cmd_id), '"']

    return to_html

### Base dom element ###
class THIS(object):
    pass

NON_SCALARS = set((list, dict, tuple))
DELETED = ""

class base_element(ContextDecorator):
    void = False
    auto_id = False

    def __new__(cls, *args, **kwargs):
        instance = ContextDecorator.__new__(cls)
        setattr(instance, "tag", cls.__name__.rstrip("_"))
        return instance

    def __init__(self, *children, **attrs):
        def init(self, *children, **attrs):
            self.t = attrs.pop("t", t)
            self.children = children
            self.attrs = attrs
            self.attrs["id_"] = LazyAttribute("id", self.attrs.get("id_", None))
            self.i = len(c.hypergen.into)
            self.sep = attrs.pop("sep", "")
            self.js_cb = attrs.pop("js_cb", "hypergen.v.s")

            c.hypergen.into.extend(self.start())
            c.hypergen.into.extend(self.end())
            self.j = len(c.hypergen.into)
            super(base_element, self).__init__()

        assert "hypergen" in c, "Element called outside hypergen context."
        c.hypergen.wrap_elements(init, self, *children, **attrs)

        if self.attrs["id_"].v is not None:
            id_ = self.attrs["id_"].v
            assert id_ not in c.hypergen["ids"], "Duplicate id: {}".format(id_)
            c.hypergen["ids"].add(id_)

    def __enter__(self):
        c.hypergen.into.extend(self.start())
        self.delete()
        return self

    def __exit__(self, *exc):
        if not self.void:
            c.hypergen.into.extend(self.end())

    def as_string(self):
        into = self.start()
        into.extend(self.end())
        s = join_html(into)
        return s

    def delete(self):
        for i in range(self.i, self.j):
            c.hypergen.into[i] = DELETED

    def format_children(self, children, _t=None):
        if _t is None:
            _t = self.t

        into = []
        sep = t(self.sep)

        for x in children:
            if x in ("", None):
                continue
            elif issubclass(type(x), base_element):
                x.delete()
                into.append(x)
            elif type(x) is Component:
                x.delete()
                into.extend(x.into)
            elif type(x) in (list, tuple):
                into.extend(self.format_children(list(x), _t=_t))
            elif type(x) in (GeneratorType,):
                into.append(x)
            elif callable(x):
                into.append(x)
            else:
                into.append(_t(x))
            if sep:
                into.append(sep)
        if sep and children:
            into.pop()

        return into

    def ensure_id(self):
        if self.attrs["id_"].v is None:
            self.attrs["id_"].v = c.hypergen.id_prefix + next(c.hypergen.id_counter)

    def attribute(self, k, v):
        k = t(k).rstrip("_").replace("_", "-")
        if callable(v):
            return v(self, k, v)
        elif type(v) is LazyAttribute:
            return [v]
        elif type(v) is bool:
            if v is True:
                return [" ", k]
            else:
                return []
        elif k == "style" and type(v) in (dict, OrderedDict):
            return [" ", k, '="', ";".join(t(k1.replace("_", "-")) + ":" + t(v1) for k1, v1 in items(v)), '"']
        elif k == "class" and type(v) in (list, tuple, set):
            return [" ", k, '="', t(" ".join(v)), '"']
        else:
            if v is None:
                v = ""
            assert '"' not in v, "How dare you put a \" in my attributes! :)"
            return [" ", k, '="', t(v), '"']

    def start(self):
        into = ["<", self.tag]
        for k, v in items(self.attrs):
            into.extend(self.attribute(k, v))

        if self.void:
            into.append(join(("/")))
        into.append(join('>',))
        into.extend(self.format_children(self.children))
        return into

    def end(self):
        if not self.void:
            return ["</{}>".format(self.tag)]
        else:
            return [""]

class base_element_void(base_element):
    void = True

class Component(object):
    def __init__(self, into, i, j):
        self.into = into
        self.i = i
        self.j = j

    def delete(self):
        for i in range(self.i, self.j):
            c.hypergen.into[i] = DELETED

def component(f):
    @wraps(f)
    def _(*args, **kwargs):
        with c(into=[], at="hypergen"):
            f(*args, **kwargs)
            into = c.hypergen.into
        i = len(c.hypergen.into)
        c.hypergen.into.extend(into)
        j = len(c.hypergen.into)
        return Component(into, i, j)

    return _

### Some special dom elements ###

INPUT_CALLBACK_TYPES = dict(
    checkbox="hypergen.v.c",
    month="hypergen.v.i",
    number="hypergen.v.i",
    range="hypergen.v.f",
    week="hypergen.v.i",
    radio="hypergen.v.r",
    file="hypergen.v.u",
)

class input_(base_element_void):
    void = True

    def __init__(self, *children, **attrs):
        super(input_, self).__init__(*children, **attrs)
        self.js_cb = attrs.pop("js_cb", INPUT_CALLBACK_TYPES.get(attrs.get("type_", "text"), "hypergen.v.s"))

### Special tags ###

def doctype(type_="html"):
    raw("<!DOCTYPE ", type_, ">")

### GENERATED BY build.py ###
# yapf: disable
class a(base_element):
    def __init__(self, *children, **attrs):
        href = attrs.get("href")
        if type(href) is StringWithMeta:
            base_template1 = href.meta.get("base_template", None)
            if base_template1 is not None:
                base_template2 = getattr(c, "base_template", None)
                if base_template1 == base_template2:
                    # Partial loading is possible.
                    attrs["onclick"] = callback(href)

        super(a, self).__init__(*children, **attrs)

class abbr(base_element): pass

class acronym(base_element): pass

class address(base_element): pass

class applet(base_element): pass

class area(base_element_void): pass

class article(base_element): pass

class aside(base_element): pass

class audio(base_element): pass

class b(base_element): pass

class base(base_element_void): pass

class basefont(base_element): pass

class bdi(base_element): pass

class bdo(base_element): pass

class big(base_element): pass

class blockquote(base_element): pass

class body(base_element): pass

class br(base_element_void): pass

class button(base_element): pass

class canvas(base_element): pass

class caption(base_element): pass

class center(base_element): pass

class cite(base_element): pass

class code(base_element): pass

class col(base_element_void): pass

class colgroup(base_element): pass

class data(base_element): pass

class datalist(base_element): pass

class dd(base_element): pass

class del_(base_element): pass

class details(base_element): pass

class dfn(base_element): pass

class dialog(base_element): pass

class dir_(base_element): pass

class div(base_element): pass

class dl(base_element): pass

class dt(base_element): pass

class em(base_element): pass

class embed(base_element_void): pass

class fieldset(base_element): pass

class figcaption(base_element): pass

class figure(base_element): pass

class font(base_element): pass

class footer(base_element): pass

class form(base_element): pass

class frame(base_element): pass

class frameset(base_element): pass

class h1(base_element): pass

class h2(base_element): pass

class h3(base_element): pass

class h4(base_element): pass

class h5(base_element): pass

class h6(base_element): pass

class head(base_element): pass

class header(base_element): pass

class hr(base_element_void): pass

class html(base_element): pass

class i(base_element): pass

class iframe(base_element): pass

class img(base_element_void): pass

class ins(base_element): pass

class kbd(base_element): pass

class label(base_element): pass

class legend(base_element): pass

class li(base_element): pass

class link(base_element):
    def __init__(self, href, rel="stylesheet", type_="text/css", **attrs):
        attrs["href"] = href
        super(link, self).__init__(rel=rel, type_=type_, **attrs)

class main(base_element): pass

class map_(base_element): pass

class mark(base_element): pass

class meta(base_element_void): pass

class meter(base_element): pass

class nav(base_element): pass

class noframes(base_element): pass

class noscript(base_element): pass

class object_(base_element): pass

class ol(base_element): pass

class optgroup(base_element): pass

class option(base_element): pass

class output(base_element): pass

class p(base_element): pass

class param(base_element_void): pass

class picture(base_element): pass

class pre(base_element): pass

class progress(base_element): pass

class q(base_element): pass

class rp(base_element): pass

class rt(base_element): pass

class ruby(base_element): pass

class s(base_element): pass

class samp(base_element): pass

class script(base_element):
    def __init__(self, *children, **attrs):
        attrs["t"] = lambda x: x
        super(script, self).__init__(*children, **attrs)

class section(base_element): pass

class select(base_element): pass

class small(base_element): pass

class source(base_element_void): pass

class span(base_element): pass

class strike(base_element): pass

class strong(base_element): pass

class style(base_element):
    def __init__(self, *children, **attrs):
        attrs["t"] = lambda x: x
        super(style, self).__init__(*children, **attrs)

class sub(base_element): pass

class summary(base_element): pass

class sup(base_element): pass

class svg(base_element): pass

class table(base_element): pass

class tbody(base_element): pass

class td(base_element): pass

class template(base_element): pass

class textarea(base_element): pass

class tfoot(base_element): pass

class th(base_element): pass

class thead(base_element): pass

class time_(base_element): pass

class title(base_element): pass

class tr(base_element): pass

class track(base_element_void): pass

class tt(base_element): pass

class u(base_element): pass

class ul(base_element): pass

class var(base_element): pass

class video(base_element): pass

class wbr(base_element_void): pass
# yapf: enable

# Serialization
def encoder(o):
    assert not hasattr(o, "reverse"), "Should not happen"
    if issubclass(type(o), base_element):
        assert o.attrs.get("id_", False), "Missing id_"
        return ["_", "element_value", [o.js_cb, o.attrs["id_"].v]]
    elif isinstance(o, datetime.datetime):
        assert False, "TODO"
        return ["_", "datetime", o.isoformat()]
    elif isinstance(o, datetime.date):
        assert False, "TODO"
        return ["_", "date", o.isoformat()]
    elif hasattr(o, "__weakref__"):
        # Lazy strings and urls.
        return make_string(o)
    else:
        raise TypeError(repr(o) + " is not JSON serializable")

def dumps(data, default=encoder, indent=None):
    result = json.dumps(data, default=encoder, separators=(',', ':'), indent=indent)

    return result

def loads(data):
    return json.loads(data)

class StringWithMeta(object):
    def __init__(self, value, meta):
        self.value = value
        self.meta = meta

    def __str__(self):
        return self.value

    def __unicode__(self):
        return self.value

    def __iter__(self):
        return iter(self.value)
