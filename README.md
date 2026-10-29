# pyxpo-file-system

Files and folders in the app's private sandbox, for [pyxpo](https://github.com/pyxpo/pyxpo) apps written in Python.
The API follows [expo-file-system](https://docs.expo.dev/versions/latest/sdk/filesystem/) (SDK 54): `File`,
`Directory` and `Paths`, plus the older function API in `pyxpo_file_system.legacy`. Reads and writes are plain Python
file I/O. Only downloads go through native code (URLSession on iOS, HttpURLConnection on Android), so they use the
system certificates and proxy.

<p align="center">
  <img src="https://raw.githubusercontent.com/pyxpo/pyxpo-file-system/main/docs/images/hero.png" width="820" alt="A note written, read back and listed from the app's documents folder on Android and iOS">
</p>

```python
from pyxpo_file_system import File, Paths

f = File(Paths.document, "notes.txt")
f.write("hello")
f.text_sync()          # "hello"
```

## Features

- **`File`:** write, read (text, bytes, base64), append, copy, move, rename, delete, `md5`, size, MIME type, random access.
- **`Directory`:** create, list, copy, move, rename, delete, total size.
- **`Paths`:** the `document` and `cache` folders, free and total disk space, path string helpers.
- **Downloads** with native networking and optional headers. The server's file name is kept.
- **Plain paths:** `file.path` works with `open()`, `sqlite3`, Pillow and any other Python library.
- **Legacy API:** `readAsStringAsync`, `getInfoAsync`, `downloadAsync` and friends, for code ported from Expo.
- **camelCase too:** `textSync`, `downloadFileAsync`, `listAsRecords`.

## Contents

| If you are... | Start here |
| --- | --- |
| Saving a file | [Quick start](#quick-start) |
| Choosing where to save | [Folders](#folders) |
| Reading and writing | [Files](#files) |
| Making folders and listing | [Directories](#directories) |
| Fetching a file from the internet | [Downloads](#downloads) |
| Porting Expo code | [Legacy API](#legacy-api) |
| Exact names | [API reference](#api-reference) · [Errors](#errors) |
| A real use | [Recipe: cache downloaded images](#recipe-cache-downloaded-images) |
| Stuck | [Testing](#testing) · [Troubleshooting](#troubleshooting) · [FAQ](#faq) |

## Platform support

| Target | What works |
| --- | --- |
| Android, API 24+ | Everything. `Paths.document` is the app's `filesDir`. Needs `INTERNET` for downloads (added for you). |
| iOS 15+ | Everything. `Paths.document` is `Documents`, `Paths.cache` is `Library/Caches`. |
| Desktop window and tests | Files work. Folders are `.pyxpo-data/documents` and `.pyxpo-data/cache` in the working folder. Downloads use `urllib`. |
| Web page | Not supported: a page has no file system. |

Requires Python 3.9+ and `pyxpo>=0.1.0a1`.

## Install

```sh
pip install pyxpo-file-system
```

```toml
[tool.pyxpo]
modules = ["file-system"]
```

Rebuild the app. There are no plugin options and no permission texts.

## Quick start

```python
from pyxpo import Button, Text, View, component, use_async, use_state
from pyxpo_file_system import Directory, File, Paths


@component
def Notes():
    taps, set_taps = use_state(0)
    names, set_names = use_state([])
    text, set_text = use_state("")

    async def run():
        notes = Directory(Paths.document, "notes")
        notes.create(idempotent=True)
        f = File(notes, "today.txt")
        if taps > 0:
            f.write("saved %d times\n" % taps)
        if f.exists:
            set_text(await f.text())
        set_names([e.name for e in notes.list()])

    use_async(run, [taps])

    return View(
        Text(text or "(no note yet)"),
        Text(", ".join(names)),
        Button("Save", lambda: set_taps(taps + 1)),
    )
```

> **Tip:** creating a `File` or `Directory` object touches nothing on disk. `await f.text()` reads off the UI thread; `f.text_sync()`
> blocks. A button that is `lambda: some_coroutine()` would never be awaited, so bump a counter and let `use_async` do the work.

<p align="center">
  <img src="https://raw.githubusercontent.com/pyxpo/pyxpo-file-system/main/docs/images/notes.png" width="720" alt="File details: uri, exists, size, text, md5 and the folder listing">
</p>

## Folders

| Folder | Use it for |
| --- | --- |
| `Paths.document` | Data the user created. Kept until the app is removed (backed up on iOS). |
| `Paths.cache` | Things you can re-create. The system may delete them when space is low. |

```python
Paths.available_disk_space, Paths.total_disk_space      # bytes
Paths.join(Paths.document, "a", "b.txt")                # a URI when the first part is a URI or entry
Paths.basename("/x/photo.png", ".png")                  # "photo"
Paths.extname("/x/photo.png")                           # ".png"
Paths.info(Paths.document, "a")                         # {"exists": ..., "isDirectory": ...}
```

Paths can be given as `File(Paths.document, "a", "b.txt")`, `File("file:///.../b.txt")`, or `File("/absolute/path")`. Relative
paths are refused: start from `Paths.document` or `Paths.cache`.

## Files

```python
f = File(Paths.document, "data.bin")
f.write("text")                         # replaces. Also bytes
f.write("more", append=True)
f.write("aGk=", encoding="base64")      # decodes the base64 string
f.text_sync(); f.bytes_sync(); f.base64_sync()     # and awaitable text(), bytes(), base64()
f.size, f.exists, f.md5, f.type, f.extension       # type is a MIME guess: "image/png"
f.modification_time                                # milliseconds
f.info(md5=True)                                   # {"exists", "uri", "size", "modificationTime", "creationTime", "md5"}
f.copy(Directory(Paths.cache))                     # into a folder, or to a File path
f.move(Directory(Paths.document, "old"))           # f now points at the new place
f.rename("new.bin")
f.delete()
with f.open() as h:                                # random access
    h.offset = 4
    chunk = h.read_bytes(16)
    h.write_bytes(b"xy")
```

`write` needs the folder to exist. `create(intermediates=True)` makes missing folders; `create(overwrite=True)` replaces.
Copy and move refuse to overwrite an existing target.

## Directories

```python
d = Directory(Paths.cache, "images")
d.create(intermediates=True, idempotent=True)     # idempotent: fine if it exists. overwrite: empties it
for e in d.list():                                # files and folders sorted by name
    print(e.name, isinstance(e, Directory))
d.list_as_records()                               # [{"uri": ..., "isDirectory": bool}]
f = d.create_file("a.txt")                        # or create_file("a", "image/png") for ".png"
sub = d.create_directory("thumbs")
d.size                                            # total bytes, recursive
d.info()                                          # {"exists", "uri", "size", "files", ...}
d.copy(Directory(Paths.document)); d.move(...); d.rename("pics"); d.delete()
```

`delete()` removes everything inside. A folder cannot be copied or moved into itself.

## Downloads

```python
f = await File.download_file_async("https://example.com/cat.jpg", Paths.cache)    # keeps the server's name
g = await File.download_file_async(url, File(Paths.cache, "x.jpg"), {"idempotent": True, "headers": {"Authorization": "Bearer ..."}})
```

A `Directory` destination keeps the file name from `Content-Disposition`, or the last part of the URL, and adds an extension from
the MIME type if it has none. A non-2xx status raises `RuntimeError`. An existing target raises unless `idempotent`.

## Legacy API

```python
from pyxpo_file_system import legacy as FileSystem

uri = FileSystem.documentDirectory + "a.txt"
await FileSystem.write_as_string_async(uri, "hi")
await FileSystem.read_as_string_async(uri)
info = await FileSystem.get_info_async(uri, {"md5": True})        # modificationTime in seconds
await FileSystem.make_directory_async(FileSystem.documentDirectory + "x/y", {"intermediates": True})
await FileSystem.delete_async(uri, {"idempotent": True})
```

New code should prefer `File` and `Directory`.

## Errors

| Error | When | What to do |
| --- | --- | --- |
| `FileNotFoundError` | Reading, copying or deleting a missing file. Writing into a missing folder. | Create the folder first. |
| `FileExistsError` | Create, copy or move onto an existing target. | Pass `overwrite=True` or `idempotent=True`, or pick another name. |
| `IsADirectoryError` | A folder is where a file should be. | Check with `Paths.info`. |
| `ValueError` | A relative path, a bad name, a non-http(s) download URL, a folder copied into itself. | Start from `Paths.document` or `Paths.cache`. |
| `RuntimeError` | A download answered with a non-2xx status. The message holds the status. | Check the URL and headers. |
| `UnicodeDecodeError` | `text()` of a binary file. | Use `bytes()` or `base64()`. |
| `ModuleNotLinkedError` | Download on a phone build without the module. | Add `"file-system"` to `modules` and rebuild. |

## Config

None. See [Folders](#folders) for where files go.

## Web and desktop

On the desktop window and in tests, `Paths.document` is `.pyxpo-data/documents` and `Paths.cache` is `.pyxpo-data/cache`
inside the working folder, and downloads use Python's `urllib`. On the web page there is no file system.

## Recipe: cache downloaded images

```python
from pyxpo import Image, Text, component, use_async, use_state
from pyxpo_file_system import Directory, File, Paths


async def cached(url):
    folder = Directory(Paths.cache, "img")
    folder.create(intermediates=True, idempotent=True)
    name = Paths.basename(url) or "image"
    target = File(folder, name)
    if not target.exists:
        target = await File.download_file_async(url, target)
    return target


@component
def Picture(url):
    path, set_path = use_state(None)

    async def run():
        f = await cached(url)
        set_path(f.uri)

    use_async(run, [url])
    return Image(source=path) if path else Text("Loading...")
```

## Production checklist

- [ ] User data goes in `Paths.document`, re-creatable data in `Paths.cache`.
- [ ] Folders are created with `intermediates=True, idempotent=True` before writing.
- [ ] Downloads handle `RuntimeError` (bad status) and network errors.
- [ ] Big files are read with `bytes()` or `open()`, not held as text.
- [ ] Secrets go to `pyxpo-secure-store`, not to files.
- [ ] Old cache files are deleted by your code. The system only cleans when it must.

## Testing

Everything but downloads is plain file I/O, so tests run on the desktop. Point the folders at a temp dir by changing the working folder:

```python
import pytest

from pyxpo_file_system import Directory, File, Paths


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_write_read_list():
    notes = Directory(Paths.document, "notes")
    notes.create(intermediates=True, idempotent=True)
    f = File(notes, "a.txt")
    f.write("hi")
    assert f.text_sync() == "hi"
    assert f.size == 2
    assert [e.name for e in notes.list()] == ["a.txt"]


def test_copy_refuses_existing():
    d = Directory(Paths.cache, "x")
    d.create(intermediates=True)
    a = File(d, "a.txt")
    a.write("1")
    a.copy(File(d, "b.txt"))
    with pytest.raises(FileExistsError):
        a.copy(File(d, "b.txt"))


def test_write_needs_folder():
    with pytest.raises(FileNotFoundError):
        File(Paths.document, "missing", "a.txt").write("x")
```

To test download code, monkeypatch `pyxpo_file_system._download` with an async function that writes a temp file and returns `{"tempPath": ..., "status": 200, "headers": {}, "mimeType": "text/plain", "url": url}`.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `ValueError: need an absolute path` | Relative path. Start from `Paths.document`. |
| `FileNotFoundError: folder does not exist` on write | Create the folder first. |
| Files vanish | They were in `Paths.cache`. Use `Paths.document`. |
| Download raises `RuntimeError` with a status | The server answered with an error. Check the URL and headers. |
| Download fails offline | No network. Catch the error. |
| Works on the desktop, not on the phone | Rebuild with the module in `modules`. |

## FAQ

**Can other apps read my files?** No. The sandbox is private to your app.

**Can I use `open()`?** Yes: `open(f.path)`.

**Is there a file picker?** Not here. See `pyxpo-image-picker` for photos.

**Does the web page work?** No.

## API reference

### `File(*parts)`

| Member | Notes |
| --- | --- |
| `path`, `uri`, `name`, `extension`, `parent_directory` | Properties. |
| `exists`, `size`, `md5`, `type`, `modification_time`, `creation_time` | Properties. `None` when the file is missing. |
| `text_sync()`, `bytes_sync()`, `base64_sync()` | Blocking reads. |
| `text()`, `bytes()`, `base64()` | Awaitable reads. |
| `write(content, options=None, *, encoding, append)` | `str` or `bytes`. Encoding `utf8` or `base64`. |
| `create(options=None, *, intermediates, overwrite)` | Empty file. |
| `copy(dest)`, `move(dest)`, `rename(name)`, `delete()` | |
| `info(options=None, *, md5)` | Dict. |
| `open()` | `FileHandle`: `offset`, `size`, `read_bytes(n)`, `write_bytes(b)`, `close()`. |
| `File.download_file_async(url, destination, options=None)` | Returns the `File`. |

### `Directory(*parts)`

`path`, `uri`, `name`, `parent_directory`, `exists`, `size`, `create(options=None, *, intermediates, overwrite, idempotent)`,
`delete()`, `list()`, `list_as_records()`, `create_file(name, mime_type=None)`, `create_directory(name)`, `copy(dest)`, `move(dest)`,
`rename(name)`, `info()`.

### `Paths`

`document`, `cache`, `available_disk_space`, `total_disk_space`, `join(*parts)`, `dirname(p)`, `basename(p, ext=None)`,
`extname(p)`, `info(*parts)`. Helpers: `file_uri(path, directory=False)`, `path_from_uri(uri)`.

### `legacy`

`documentDirectory`, `cacheDirectory`, `EncodingType`, and `get_info_async`, `read_as_string_async`, `write_as_string_async`,
`delete_async`, `move_async`, `copy_async`, `make_directory_async`, `read_directory_async`, `download_async`,
`get_free_disk_storage_async`, `get_total_disk_capacity_async` (camelCase names also work).

## License

MIT
