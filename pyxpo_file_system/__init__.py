"""Files and folders in the app's sandbox: the expo-file-system (SDK 54) `File`, `Directory` and `Paths` API.

    from pyxpo_file_system import File, Directory, Paths

    f = File(Paths.document, "notes.txt")
    f.write("hello")
    f.text_sync()                      # "hello"
    await f.text()                     # same, off the UI thread
    d = Directory(Paths.cache, "img")
    d.create(idempotent=True)
    img = await File.download_file_async("https://example.com/a.png", d)

Reads and writes are plain Python file I/O and run on any thread. Only downloads go through native code
(URLSession on iOS, HttpURLConnection on Android) so they use the system's certificates and proxy.
Every method also has its Expo camelCase name (`textSync`, `downloadFileAsync`, `listAsRecords`, ...).
The older function API lives in `pyxpo_file_system.legacy` (`expo-file-system/legacy`).
"""
from __future__ import annotations

import asyncio
import base64 as _b64
import hashlib
import mimetypes
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote, unquote, urlparse

from pyxpo.module_api import call, platform, require_linked

__version__ = "0.1.0"

__all__ = ["File", "Directory", "Paths", "FileHandle", "file_uri", "path_from_uri"]


# paths and URIs

def file_uri(path: Union[str, os.PathLike], directory: bool = False) -> str:
    """`/a b/c` becomes `file:///a%20b/c` (with a trailing slash for a directory, as Expo writes them)."""
    p = os.path.abspath(os.fspath(path))
    if directory and not p.endswith("/"):
        p += "/"
    return "file://" + quote(p, safe="/:@!$&'()*+,;=-._~")


def path_from_uri(uri: str) -> str:
    """Accepts a `file://` URI or an absolute path and returns the absolute path."""
    if uri.startswith("file:"):
        u = urlparse(uri)
        if u.netloc not in ("", "localhost"):
            raise ValueError("not a local file URI: %r" % uri)
        p = unquote(u.path)
    elif "://" in uri:
        raise ValueError("only file:// URIs and absolute paths are supported, got %r" % uri)
    else:
        p = uri
    if not os.path.isabs(p):
        raise ValueError("need an absolute path or file:// URI, got %r (start from Paths.document or Paths.cache)" % uri)
    return os.path.normpath(p)


def _join(parts: tuple) -> str:
    if not parts:
        raise ValueError("File/Directory needs a path or URI")
    first, rest = parts[0], parts[1:]
    base = first._path if isinstance(first, (File, Directory)) else path_from_uri(os.fspath(first))
    for p in rest:
        if isinstance(p, (File, Directory)):
            p = p._path
        p = os.fspath(p)
        if p.startswith("file:"):
            p = path_from_uri(p)
        base = os.path.join(base, p.lstrip("/")) if p else base
    return os.path.normpath(base)


def _home() -> str:
    return os.environ.get("HOME") or os.path.expanduser("~")


def _documents() -> str:
    if sys.platform == "ios":
        return os.path.join(_home(), "Documents")
    if sys.platform == "android":
        return _home()  # the app's filesDir
    return os.path.join(os.getcwd(), ".pyxpo-data", "documents")


def _caches() -> str:
    if sys.platform == "ios":
        return os.path.join(_home(), "Library", "Caches")
    if sys.platform == "android":
        return os.environ.get("TMPDIR") or os.path.join(os.path.dirname(_home()), "cache")
    return os.path.join(os.getcwd(), ".pyxpo-data", "cache")


def _times(st: os.stat_result) -> Dict[str, Optional[int]]:
    born = getattr(st, "st_birthtime", None)
    return {"modificationTime": int(st.st_mtime * 1000), "creationTime": int(born * 1000) if born else None}


def _md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for n in files:
            try:
                total += os.lstat(os.path.join(root, n)).st_size
            except OSError:
                pass
    return total


class _Entry:
    _path: str

    @property
    def path(self) -> str:
        """Absolute path (pass this to `open()` or other Python libraries)."""
        return self._path

    @property
    def name(self) -> str:
        return os.path.basename(self._path)

    @property
    def parent_directory(self) -> "Directory":
        return Directory(os.path.dirname(self._path) or "/")

    def __fspath__(self) -> str:
        return self._path

    def __eq__(self, other: object) -> bool:
        return type(other) is type(self) and other._path == self._path  # type: ignore[attr-defined]

    def __hash__(self) -> int:
        return hash((type(self).__name__, self._path))

    def __str__(self) -> str:
        return self.uri  # type: ignore[attr-defined]

    def __repr__(self) -> str:
        return "%s(%r)" % (type(self).__name__, self.uri)  # type: ignore[attr-defined]

    def _target(self, destination: Union["File", "Directory", str]) -> str:
        """Where copy/move puts this entry: inside `destination` when it is (or names) an existing directory."""
        if isinstance(destination, Directory):
            return os.path.join(destination._path, self.name)
        dest = destination._path if isinstance(destination, File) else path_from_uri(os.fspath(destination))
        return os.path.join(dest, self.name) if os.path.isdir(dest) else dest


class FileHandle:
    """Random access to a file's bytes (`file.open()`). Use as a context manager or call `close()`."""

    def __init__(self, path: str) -> None:
        self._f = open(path, "r+b")

    @property
    def offset(self) -> Optional[int]:
        return None if self._f.closed else self._f.tell()

    @offset.setter
    def offset(self, value: int) -> None:
        self._f.seek(int(value))

    @property
    def size(self) -> Optional[int]:
        return None if self._f.closed else os.fstat(self._f.fileno()).st_size

    def read_bytes(self, length: int) -> bytes:
        return self._f.read(int(length))

    def write_bytes(self, data: bytes) -> None:
        self._f.write(bytes(data))
        self._f.flush()

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> "FileHandle":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    readBytes = read_bytes
    writeBytes = write_bytes


class File(_Entry):
    """A file path. Creating the object touches nothing on disk.

    `File(Paths.document, "a", "b.txt")`, `File("file:///.../b.txt")` or `File("/abs/path")`."""

    def __init__(self, *uris: Union[str, os.PathLike, "File", "Directory"]) -> None:
        self._path = _join(uris)

    @property
    def uri(self) -> str:
        return file_uri(self._path)

    @property
    def extension(self) -> str:
        """`.txt` (with the dot), or `""`."""
        return os.path.splitext(self._path)[1]

    @property
    def exists(self) -> bool:
        return os.path.isfile(self._path)

    @property
    def size(self) -> Optional[int]:
        try:
            return os.stat(self._path).st_size
        except OSError:
            return None

    @property
    def md5(self) -> Optional[str]:
        return _md5(self._path) if self.exists else None

    @property
    def modification_time(self) -> Optional[int]:
        """Milliseconds since 1970, or None when the file does not exist."""
        try:
            return _times(os.stat(self._path))["modificationTime"]
        except OSError:
            return None

    @property
    def creation_time(self) -> Optional[int]:
        try:
            return _times(os.stat(self._path))["creationTime"]
        except OSError:
            return None

    @property
    def type(self) -> Optional[str]:
        """MIME type guessed from the extension (`image/png`), or None."""
        return mimetypes.guess_type(self.name)[0]

    # reading

    def text_sync(self) -> str:
        with open(self._path, encoding="utf-8") as f:
            return f.read()

    def bytes_sync(self) -> bytes:
        with open(self._path, "rb") as f:
            return f.read()

    def base64_sync(self) -> str:
        return _b64.b64encode(self.bytes_sync()).decode("ascii")

    async def text(self) -> str:
        return await asyncio.to_thread(self.text_sync)

    async def bytes(self) -> bytes:
        return await asyncio.to_thread(self.bytes_sync)

    async def base64(self) -> str:
        return await asyncio.to_thread(self.base64_sync)

    # writing

    def write(self, content: Union[str, bytes, bytearray, memoryview], options: Optional[Dict[str, Any]] = None,
              *, encoding: Optional[str] = None, append: Optional[bool] = None) -> None:
        """Writes `content` (creates the file, replaces it unless `append`). `encoding`: `utf8` (default) or
        `base64` (the string is base64 data to decode). Bytes are written as they are."""
        o = dict(options or {})
        enc = encoding or o.get("encoding") or "utf8"
        app = bool(append if append is not None else o.get("append"))
        if isinstance(content, str):
            if enc == "base64":
                data = _b64.b64decode(content, validate=True)
            elif enc in ("utf8", "utf-8"):
                data = content.encode("utf-8")
            else:
                raise ValueError("encoding must be 'utf8' or 'base64', got %r" % enc)
        elif isinstance(content, (bytes, bytearray, memoryview)):
            data = bytes(content)
        else:
            raise TypeError("write() takes str or bytes, got %s" % type(content).__name__)
        if not os.path.isdir(os.path.dirname(self._path)):
            raise FileNotFoundError("folder does not exist: %s (create it first)" % os.path.dirname(self._path))
        with open(self._path, "ab" if app else "wb") as f:
            f.write(data)

    def create(self, options: Optional[Dict[str, Any]] = None, *, intermediates: Optional[bool] = None,
               overwrite: Optional[bool] = None) -> None:
        """Creates an empty file. Raises if it exists unless `overwrite`; `intermediates` creates missing folders."""
        o = dict(options or {})
        inter = bool(intermediates if intermediates is not None else o.get("intermediates"))
        over = bool(overwrite if overwrite is not None else o.get("overwrite"))
        if os.path.isdir(self._path):
            raise IsADirectoryError("a folder exists at %s" % self._path)
        if os.path.exists(self._path) and not over:
            raise FileExistsError("file already exists: %s" % self._path)
        parent = os.path.dirname(self._path)
        if inter:
            os.makedirs(parent, exist_ok=True)
        elif not os.path.isdir(parent):
            raise FileNotFoundError("folder does not exist: %s (pass intermediates=True)" % parent)
        open(self._path, "wb").close()

    def delete(self) -> None:
        if not self.exists:
            raise FileNotFoundError("file does not exist: %s" % self._path)
        os.remove(self._path)

    def copy(self, destination: Union["File", "Directory", str]) -> None:
        """Copies to `destination` (a File, or a Directory to copy into). Raises if the target exists."""
        if not self.exists:
            raise FileNotFoundError("file does not exist: %s" % self._path)
        target = self._target(destination)
        if os.path.exists(target):
            raise FileExistsError("destination already exists: %s" % target)
        shutil.copy2(self._path, target)

    def move(self, destination: Union["File", "Directory", str]) -> None:
        """Moves to `destination`; this object then points at the new place."""
        if not self.exists:
            raise FileNotFoundError("file does not exist: %s" % self._path)
        target = self._target(destination)
        if os.path.exists(target):
            raise FileExistsError("destination already exists: %s" % target)
        shutil.move(self._path, target)
        self._path = os.path.normpath(target)

    def rename(self, new_name: str) -> None:
        if not new_name or "/" in new_name or new_name in (".", ".."):
            raise ValueError("bad file name %r" % new_name)
        self.move(File(os.path.dirname(self._path), new_name))

    def info(self, options: Optional[Dict[str, Any]] = None, *, md5: Optional[bool] = None) -> Dict[str, Any]:
        """`{exists, uri, size, modificationTime, creationTime, md5?}` (times in milliseconds)."""
        want_md5 = bool(md5 if md5 is not None else (options or {}).get("md5"))
        try:
            st = os.stat(self._path)
        except OSError:
            return {"exists": False, "uri": self.uri}
        if not os.path.isfile(self._path):
            return {"exists": False, "uri": self.uri}
        out: Dict[str, Any] = {"exists": True, "uri": self.uri, "size": st.st_size, **_times(st)}
        if want_md5:
            out["md5"] = _md5(self._path)
        return out

    def open(self) -> FileHandle:
        if not self.exists:
            raise FileNotFoundError("file does not exist: %s" % self._path)
        return FileHandle(self._path)

    # downloads

    @staticmethod
    async def download_file_async(url: str, destination: Union["File", "Directory", str],
                                  options: Optional[Dict[str, Any]] = None) -> "File":
        """Downloads `url` into `destination` and returns the File. A Directory destination keeps the server's
        file name (Content-Disposition, else the URL's last part). Raises on a non-2xx status, and when the
        target file exists unless `{"idempotent": True}` (then it is replaced). `options["headers"]`: request headers."""
        o = dict(options or {})
        res = await _download(url, o.get("headers") or {})
        try:
            if not 200 <= res["status"] < 300:
                raise RuntimeError("download failed with HTTP status %s: %s" % (res["status"], url))
            if isinstance(destination, Directory) or (not isinstance(destination, File)
                                                      and os.path.isdir(path_from_uri(os.fspath(destination)))):
                folder = destination._path if isinstance(destination, Directory) else path_from_uri(os.fspath(destination))
                target = File(folder, _download_name(res, url))
            else:
                target = destination if isinstance(destination, File) else File(destination)
            if not os.path.isdir(os.path.dirname(target._path)):
                raise FileNotFoundError("folder does not exist: %s" % os.path.dirname(target._path))
            if os.path.exists(target._path):
                if not o.get("idempotent"):
                    raise FileExistsError("destination already exists: %s (pass idempotent=True to replace)" % target._path)
                if os.path.isdir(target._path):
                    raise IsADirectoryError("a folder exists at %s" % target._path)
            shutil.move(res["tempPath"], target._path)
            return File(target._path)
        finally:
            if os.path.exists(res["tempPath"]):
                os.remove(res["tempPath"])

    # Expo names
    textSync = text_sync
    bytesSync = bytes_sync
    base64Sync = base64_sync
    downloadFileAsync = download_file_async
    modificationTime = modification_time
    creationTime = creation_time
    parentDirectory = _Entry.parent_directory


class Directory(_Entry):
    """A folder path. `Directory(Paths.cache, "images")`. Creating the object touches nothing on disk."""

    def __init__(self, *uris: Union[str, os.PathLike, "File", "Directory"]) -> None:
        self._path = _join(uris)

    @property
    def uri(self) -> str:
        return file_uri(self._path, directory=True)

    @property
    def exists(self) -> bool:
        return os.path.isdir(self._path)

    @property
    def size(self) -> Optional[int]:
        """Total bytes of all files inside (recursive), or None when the folder does not exist."""
        return _tree_size(self._path) if self.exists else None

    def create(self, options: Optional[Dict[str, Any]] = None, *, intermediates: Optional[bool] = None,
               overwrite: Optional[bool] = None, idempotent: Optional[bool] = None) -> None:
        """Creates the folder. If it exists: no-op with `idempotent`, emptied with `overwrite`, else raises."""
        o = dict(options or {})
        inter = bool(intermediates if intermediates is not None else o.get("intermediates"))
        over = bool(overwrite if overwrite is not None else o.get("overwrite"))
        idem = bool(idempotent if idempotent is not None else o.get("idempotent"))
        if os.path.isfile(self._path):
            raise FileExistsError("a file exists at %s" % self._path)
        if os.path.isdir(self._path):
            if idem:
                return
            if not over:
                raise FileExistsError("folder already exists: %s" % self._path)
            shutil.rmtree(self._path)
        if inter:
            os.makedirs(self._path, exist_ok=True)
        else:
            os.mkdir(self._path)

    def delete(self) -> None:
        """Deletes the folder and everything inside."""
        if not self.exists:
            raise FileNotFoundError("folder does not exist: %s" % self._path)
        shutil.rmtree(self._path)

    def list(self) -> List[Union[File, "Directory"]]:
        """Direct children, folders and files, sorted by name."""
        out: List[Union[File, Directory]] = []
        for n in sorted(os.listdir(self._path)):
            p = os.path.join(self._path, n)
            out.append(Directory(p) if os.path.isdir(p) else File(p))
        return out

    def list_as_records(self) -> List[Dict[str, Any]]:
        """`[{"uri": ..., "isDirectory": bool}]` without building objects."""
        return [{"uri": e.uri, "isDirectory": isinstance(e, Directory)} for e in self.list()]

    def create_file(self, name: str, mime_type: Optional[str] = None) -> File:
        """Creates an empty file in this folder. `mime_type` adds its extension when `name` has none."""
        if not name or "/" in name:
            raise ValueError("bad file name %r" % name)
        if mime_type and not os.path.splitext(name)[1]:
            name += mimetypes.guess_extension(mime_type) or ""
        f = File(self._path, name)
        f.create()
        return f

    def create_directory(self, name: str) -> "Directory":
        if not name or "/" in name:
            raise ValueError("bad folder name %r" % name)
        d = Directory(self._path, name)
        d.create()
        return d

    def copy(self, destination: Union["Directory", str]) -> None:
        """Copies the folder into `destination` (or to it, when it does not exist yet)."""
        if not self.exists:
            raise FileNotFoundError("folder does not exist: %s" % self._path)
        target = self._target(destination)
        if os.path.exists(target):
            raise FileExistsError("destination already exists: %s" % target)
        if os.path.commonpath([os.path.realpath(target), os.path.realpath(self._path)]) == os.path.realpath(self._path):
            raise ValueError("cannot copy a folder into itself")
        shutil.copytree(self._path, target)

    def move(self, destination: Union["Directory", str]) -> None:
        if not self.exists:
            raise FileNotFoundError("folder does not exist: %s" % self._path)
        target = self._target(destination)
        if os.path.exists(target):
            raise FileExistsError("destination already exists: %s" % target)
        if os.path.commonpath([target, self._path]) == self._path:
            raise ValueError("cannot move a folder into itself")
        shutil.move(self._path, target)
        self._path = os.path.normpath(target)

    def rename(self, new_name: str) -> None:
        if not new_name or "/" in new_name or new_name in (".", ".."):
            raise ValueError("bad folder name %r" % new_name)
        target = os.path.join(os.path.dirname(self._path), new_name)
        if os.path.exists(target):
            raise FileExistsError("destination already exists: %s" % target)
        os.rename(self._path, target)
        self._path = target

    def _target(self, destination: Union[File, "Directory", str]) -> str:
        dest = destination._path if isinstance(destination, (File, Directory)) else path_from_uri(os.fspath(destination))
        return os.path.join(dest, self.name) if os.path.isdir(dest) else dest

    def info(self) -> Dict[str, Any]:
        """`{exists, uri, size, files, modificationTime, creationTime}` (`files`: child names)."""
        if not self.exists:
            return {"exists": False, "uri": self.uri}
        st = os.stat(self._path)
        return {"exists": True, "uri": self.uri, "size": _tree_size(self._path),
                "files": sorted(os.listdir(self._path)), **_times(st)}

    listAsRecords = list_as_records
    createFile = create_file
    createDirectory = create_directory
    parentDirectory = _Entry.parent_directory


class _Paths:
    """`Paths.document`, `Paths.cache`, disk space and path string helpers."""

    @property
    def document(self) -> Directory:
        """Kept until the app is deleted; backed up on iOS."""
        p = _documents()
        os.makedirs(p, exist_ok=True)
        return Directory(p)

    @property
    def cache(self) -> Directory:
        """The OS may delete files here when space runs low."""
        p = _caches()
        os.makedirs(p, exist_ok=True)
        return Directory(p)

    @property
    def available_disk_space(self) -> int:
        st = os.statvfs(_documents() if os.path.isdir(_documents()) else os.getcwd())
        return st.f_bavail * st.f_frsize

    @property
    def total_disk_space(self) -> int:
        st = os.statvfs(_documents() if os.path.isdir(_documents()) else os.getcwd())
        return st.f_blocks * st.f_frsize

    @staticmethod
    def join(*parts: Union[str, File, Directory]) -> str:
        """Joins into a URI when the first part is a URI or entry, else into a path."""
        first = parts[0] if parts else ""
        joined = _join(parts)
        if isinstance(first, (File, Directory)) or str(first).startswith("file:"):
            return file_uri(joined)
        return joined

    @staticmethod
    def dirname(path: Union[str, File, Directory]) -> str:
        p = path._path if isinstance(path, (File, Directory)) else str(path)
        return os.path.dirname(p.rstrip("/"))

    @staticmethod
    def basename(path: Union[str, File, Directory], ext: Optional[str] = None) -> str:
        p = path._path if isinstance(path, (File, Directory)) else str(path)
        b = unquote(os.path.basename(p.rstrip("/")))
        return b[: -len(ext)] if ext and b.endswith(ext) else b

    @staticmethod
    def extname(path: Union[str, File, Directory]) -> str:
        p = path._path if isinstance(path, (File, Directory)) else str(path)
        return os.path.splitext(p.rstrip("/"))[1]

    @staticmethod
    def info(*uris: Union[str, File, Directory]) -> Dict[str, Any]:
        """`{exists, isDirectory}` for a path that may be a file or a folder."""
        p = _join(uris)
        return {"exists": os.path.exists(p), "isDirectory": os.path.isdir(p) if os.path.exists(p) else None}

    availableDiskSpace = available_disk_space
    totalDiskSpace = total_disk_space


Paths = _Paths()


# downloads

def _header(headers: Dict[str, str], name: str) -> Optional[str]:
    for k, v in (headers or {}).items():
        if k.lower() == name:
            return v
    return None


def _download_name(res: Dict[str, Any], url: str) -> str:
    name = ""
    cd = _header(res.get("headers") or {}, "content-disposition") or ""
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", cd) or re.search(r'filename\s*=\s*"?([^";]+)"?', cd)
    if m:
        name = unquote(m.group(1).strip())
    if not name:
        name = unquote(urlparse(res.get("url") or url).path.rstrip("/").rsplit("/", 1)[-1])
    name = os.path.basename(name.replace("\\", "/")).strip()
    if name in ("", ".", ".."):
        name = "download"
    if not os.path.splitext(name)[1] and res.get("mimeType"):
        name += mimetypes.guess_extension(str(res["mimeType"]).split(";")[0].strip()) or ""
    return name


async def _download(url: str, headers: Dict[str, Any]) -> Dict[str, Any]:
    """Downloads into a temporary file in the cache folder. Returns `{tempPath, status, headers, mimeType, url}`."""
    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        raise ValueError("download needs an http(s) URL, got %r" % (url,))
    hdrs = {str(k): str(v) for k, v in dict(headers or {}).items()}
    tmp = os.path.join(_caches(), ".pyxpo-download-%s" % uuid.uuid4().hex)
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    try:
        if platform() == "desktop":
            res = await asyncio.to_thread(_desktop_download, url, hdrs, tmp)
        else:
            require_linked("FileSystem", "file-system", package="pyxpo-file-system")
            res = dict(await call("FileSystem", "download", url, hdrs, tmp, reply=True) or {})
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    res["tempPath"] = tmp
    res["status"] = int(res.get("status") or 0)
    return res


def _desktop_download(url: str, headers: Dict[str, str], tmp: str) -> Dict[str, Any]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        resp = e
    with resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
        hdrs = dict(resp.headers.items())
        return {"status": resp.status if hasattr(resp, "status") else resp.code, "headers": hdrs,
                "mimeType": (resp.headers.get_content_type() if resp.headers.get("content-type") else None),
                "url": resp.geturl()}


for _cls in (File, Directory, _Paths):
    for _name, _val in list(vars(_cls).items()):
        if not _name.startswith("_") and "_" in _name and isinstance(_val, property):
            _head, *_rest = _name.split("_")
            setattr(_cls, _head + "".join(w[:1].upper() + w[1:] for w in _rest), _val)
