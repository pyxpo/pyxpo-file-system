# pyxpo-file-system

Files and folders in the app sandbox for pyxpo apps. The API follows expo-file-system (`File`,
`Directory`, `Paths`), and the older function API is in `pyxpo_file_system.legacy`.

This is an optional [pyxpo](https://github.com/ivishalchaubey/pyxpo) native module. Apps that do not
list it carry none of its code, permissions or dependencies.

## Install

```bash
pip install pyxpo-file-system
```

Then link it into your app in `pyproject.toml`:

```toml
[tool.pyxpo]
modules = ["file-system"]
```

and rebuild (`pyxpo run ios`, `pyxpo build android`, ...).

## Use

```python
from pyxpo_file_system import Directory, File, Paths

notes = Directory(Paths.document, "notes")
notes.create(idempotent=True)

f = File(notes, "today.txt")
f.write("hello")
f.text_sync()                # "hello"
await f.text()               # same, async
f.size, f.exists, f.uri

for entry in notes.list():
    print(entry.name)

# Download (native networking on iOS and Android)
img = await File.download_file_async("https://example.com/cat.jpg", Paths.cache)
```

Legacy API:

```python
from pyxpo_file_system import legacy as FileSystem

path = FileSystem.documentDirectory + "a.txt"
await FileSystem.writeAsStringAsync(path, "hi")
await FileSystem.readAsStringAsync(path)
```

Folders: `Paths.document` is kept until the app is removed. `Paths.cache` can be cleared by the system.

Permissions: Android `INTERNET` (for downloads). Info.plist keys: none.

## What is in the package

- `pyxpo_file_system/__init__.py` and `legacy.py`: the Python API.
- `pyxpo_file_system/pyxpo-module.json`: autolink metadata.
- `pyxpo_file_system/ios/`: Swift sources compiled into the iOS app.
- `pyxpo_file_system/android/src/main/`: Kotlin sources and the manifest merged into the Android app.
