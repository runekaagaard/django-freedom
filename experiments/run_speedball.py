from speedball import speedball

items = [
    {"is_completed": True, "description": "I am the Zohan!"},
    {"is_completed": False, "description": "Who are you!"},
    {"is_completed": True, "description": "I am nice!"},
    {"is_completed": False, "description": "Døne with this!"},]

html = speedball(items)
print(type(html))
print()
print(html)
