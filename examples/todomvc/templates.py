# coding=utf-8

from django.templatetags.static import static
from hypergen.core import *
from hypergen.core import callback as cb, context as c
from contextlib import contextmanager

@contextmanager
def base():
    with html(lang="en"):
        with head():
            meta(charset="utf-8")
            meta(name="viewport", content="width=device-width, initial-scale=1")
            title("Hypergen • TodoMVC")
            script(src=static("hypergen/hypergen.min.js"))
            link(static("todomvc.css"))
        with body():
            with div(id_="content"):
                yield
            with footer(class_="info"):
                p("Double-click to edit a todo")
                p(a("Django Hypergen", href="https://github.com/runekaagaard/django-hypergen"))
                p(a("TodoMVC", href="http://todomvc.com"))

@component
def todo_item(item):
    from todomvc.views import toggle_is_completed, delete, start_edit, submit_edit
    is_editing = item.pk == c.appstate["edit_item_pk"]
    classes = []
    if item.is_completed:
        classes.append("completed")
    if is_editing:
        classes.append("editing")

    with li(class_=classes):
        if not is_editing:
            with div(class_="view"):
                input_(class_="toggle", type_="checkbox", checked=item.is_completed,
                    onclick=cb(toggle_is_completed, item.pk))
                label(item.description, ondblclick=cb(start_edit, item.pk))
                button(class_="destroy", onclick=cb(delete, item.pk))
        else:
            input_(id_="edit-item", class_="edit", autofocus=True, value=item.description,
                onkeyup=cb(submit_edit, item.pk, THIS,
                event_matches={"key": "Enter"}), onblur=cb(submit_edit, item.pk, THIS))

def content(items, filtering, all_completed):
    from todomvc.views import ALL, ACTIVE, COMPLETED, index, add, clear_completed, toggle_all
    with section(class_="todoapp"):
        with header(class_="header"):
            h1("todos")
            input_(id_="new-todo", class_="new-todo", placeholder="What needs to be done?",
                autofocus=not c.appstate["edit_item_pk"], onkeyup=cb(add, THIS, event_matches={"key": "Enter"},
                clear=True))

        if filtering == ALL and not items:
            return

        with section(class_="main"):
            input_(id_="toggle-all", class_="toggle-all", type_="checkbox", checked=all_completed,
                onclick=cb(toggle_all, not all_completed))
            label("Mark all as complete", for_="toggle-all")

        ul([todo_item(item) for item in items], class_="todo-list")

        with footer(class_="footer"):
            span(strong(len(items), "items" if len(items) > 1 else "item", sep=" "), class_="todo-count")

            with ul(class_="filters"):
                li(a("All", class_="selected" if filtering == ALL else "", href=index.reverse(ALL)))
                li(a("Active", class_="selected" if filtering == ACTIVE else "", href=index.reverse(ACTIVE)))
                li(a("Completed", class_="selected" if filtering == COMPLETED else "", href=index.reverse(COMPLETED)))

            if items.filter(is_completed=True):
                button("Clear completed", class_="clear-completed", onclick=cb(clear_completed))
