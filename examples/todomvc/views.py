# coding = utf-8
# pylint: disable=no-value-for-parameter

from hypergen.contrib import hypergen_view, hypergen_callback, NO_PERM_REQUIRED
from hypergen.core import context as c

from todomvc import templates
from todomvc.models import Item

HYPERGEN_SETTINGS = dict(perm=NO_PERM_REQUIRED, base_template=templates.base, target_id="content",
    namespace="todomvc", app_name="todomvc", appstate_init=lambda: {"edit_item_pk": None})
ALL, ACTIVE, COMPLETED = "", "active", "completed"

@hypergen_view(url=r'^(active|completed|)$', **HYPERGEN_SETTINGS)
def index(request, filtering):
    items = Item.objects.all()
    if filtering == ACTIVE:
        items = items.filter(is_completed=False)
    elif filtering == COMPLETED:
        items = items.filter(is_completed=True)

    all_completed = items and not Item.objects.filter(is_completed=False)

    templates.content(items, filtering, all_completed)

@hypergen_callback(view=index, **HYPERGEN_SETTINGS)
def add(request, description):
    if description is None:
        return [["alert", "Please write something to do"]]

    Item(description=description).save()

@hypergen_callback(view=index, **HYPERGEN_SETTINGS)
def toggle_is_completed(request, pk):
    item = Item.objects.get(pk=pk)
    item.is_completed = not item.is_completed
    item.save()

@hypergen_callback(view=index, **HYPERGEN_SETTINGS)
def delete(request, pk):
    Item.objects.filter(pk=pk).delete()

@hypergen_callback(view=index, **HYPERGEN_SETTINGS)
def clear_completed(request):
    Item.objects.filter(is_completed=True).delete()

@hypergen_callback(view=index, **HYPERGEN_SETTINGS)
def toggle_all(request, is_completed):
    Item.objects.update(is_completed=is_completed)

@hypergen_callback(view=index, **HYPERGEN_SETTINGS)
def start_edit(request, pk):
    c.appstate["edit_item_pk"] = pk

@hypergen_callback(view=index, **HYPERGEN_SETTINGS)
def submit_edit(request, pk, description):
    item = Item.objects.get(pk=pk)
    item.description = description
    item.save()
    c.appstate["edit_item_pk"] = None
