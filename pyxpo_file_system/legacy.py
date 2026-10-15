"""The function API of `expo-file-system/legacy` (`FileSystem.readAsStringAsync` and friends).

    from pyxpo_file_system import legacy as FileSystem

    uri = FileSystem.documentDirectory + "notes.txt"
    await FileSystem.write_as_string_async(uri, "hi")
    info = await FileSystem.get_info_async(uri)   # {"exists": True, "size": 2, "modificationTime": <seconds>, ...}

Takes `file://` URIs (absolute paths work too). Times are in seconds, as in Expo's legacy API.
New code should prefer `File` and `Directory` from `pyxpo_file_system`.
"""
from __future__ import annotations

import asyncio
import base64
import os
import shutil
from typing import Any, Dict, List, Optional

from . import Directory, File, Paths, _download, _md5, _tree_size, file_uri, path_from_uri


class EncodingType:
    UTF8 = "utf8"
    Base64 = "base64"


def __getattr__(name: str) -> Any:
    # Computed on use: the folders depend on the running platform.
    if name in ("documentDirectory", "document_directory"):
        return Paths.document.uri
    if name in ("cacheDirectory", "cache_directory"):
        return Paths.cache.uri
    raise AttributeError(name)


def _get_info(uri: str, md5: bool) -> Dict[str, Any]:
    p = path_from_uri(uri)
    if not os.path.exists(p):
        return {"exists": False, "isDirectory": False, "uri": uri}
    st = os.stat(p)
    is_dir = os.path.isdir(p)
    out: Dict[str, Any] = {"exists": True, "uri": file_uri(p, directory=is_dir), "isDirectory": is_dir,
                           "size": _tree_size(p) if is_dir else st.st_size, "modificationTime": st.st_mtime}
    if md5 and not is_dir:
        out["md5"] = _md5(p)
    return out


async def get_info_async(file_uri_: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`{exists, uri, isDirectory, size, modificationTime, md5?}`; `{exists: False, isDirectory: False, uri}` if missing."""
    return await asyncio.to_thread(_get_info, file_uri_, bool((options or {}).get("md5")))


def _read(uri: str, o: Dict[str, Any]) -> str:
    with open(path_from_uri(uri), "rb") as f:
        if o.get("position") is not None:
            f.seek(int(o["position"]))
        data = f.read(int(o["length"])) if o.get("length") is not None else f.read()
    if (o.get("encoding") or "utf8") == "base64":
        return base64.b64encode(data).decode("ascii")
    return data.decode("utf-8")


async def read_as_string_async(file_uri_: str, options: Optional[Dict[str, Any]] = None) -> str:
    """`options`: `encoding` (`utf8`/`base64`); with base64, `position` and `length` read a byte range."""
    return await asyncio.to_thread(_read, file_uri_, dict(options or {}))


async def write_as_string_async(file_uri_: str, contents: str, options: Optional[Dict[str, Any]] = None) -> None:
    """`options`: `encoding` (`utf8`/`base64`) and `append`."""
    o = dict(options or {})
    await asyncio.to_thread(File(file_uri_).write, contents, {"encoding": o.get("encoding") or "utf8", "append": o.get("append")})


def _delete(uri: str, idempotent: bool) -> None:
    p = path_from_uri(uri)
    if os.path.isdir(p) and not os.path.islink(p):
        shutil.rmtree(p)
    elif os.path.lexists(p):
        os.remove(p)
    elif not idempotent:
        raise FileNotFoundError("location does not exist: %s" % uri)


async def delete_async(file_uri_: str, options: Optional[Dict[str, Any]] = None) -> None:
    """Deletes a file or folder. Raises when missing unless `{"idempotent": True}`."""
    await asyncio.to_thread(_delete, file_uri_, bool((options or {}).get("idempotent")))


def _from_to(options: Dict[str, Any]) -> tuple:
    if "from" not in options or "to" not in options:
        raise ValueError("pass {'from': uri, 'to': uri}")
    return path_from_uri(options["from"]), path_from_uri(options["to"])


def _move(options: Dict[str, Any]) -> None:
    src, dst = _from_to(options)
    if not os.path.exists(src):
        raise FileNotFoundError("location does not exist: %s" % options["from"])
    if os.path.isdir(dst) and not os.path.isdir(src):
        raise IsADirectoryError("a folder exists at %s" % options["to"])
    shutil.move(src, dst)


def _copy(options: Dict[str, Any]) -> None:
    src, dst = _from_to(options)
    if os.path.isdir(src):
        if os.path.commonpath([os.path.realpath(src), os.path.realpath(dst)]) == os.path.realpath(src):
            raise ValueError("cannot copy a folder onto itself or into itself")
        if os.path.exists(dst):
            shutil.rmtree(dst) if os.path.isdir(dst) else os.remove(dst)
        shutil.copytree(src, dst)
    elif os.path.isfile(src):
        shutil.copy2(src, dst)
    else:
        raise FileNotFoundError("location does not exist: %s" % options["from"])


async def move_async(options: Dict[str, Any]) -> None:
    """`{"from": uri, "to": uri}`; replaces an existing file at `to`."""
    await asyncio.to_thread(_move, dict(options))


async def copy_async(options: Dict[str, Any]) -> None:
    """`{"from": uri, "to": uri}`; replaces what is at `to`."""
    await asyncio.to_thread(_copy, dict(options))


async def make_directory_async(file_uri_: str, options: Optional[Dict[str, Any]] = None) -> None:
    """Creates a folder. `{"intermediates": True}` creates parents and does not fail when it exists."""
    inter = bool((options or {}).get("intermediates"))
    await asyncio.to_thread(Directory(file_uri_).create, intermediates=inter, idempotent=inter)


async def read_directory_async(file_uri_: str) -> List[str]:
    """Names of the folder's children."""
    return await asyncio.to_thread(lambda: sorted(os.listdir(path_from_uri(file_uri_))))


async def download_async(uri: str, file_uri_: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Downloads to `file_uri_` (replacing it) whatever the status code, like Expo.
    Returns `{uri, status, headers, mimeType, md5?}`. `options`: `headers`, `md5`."""
    o = dict(options or {})
    dst = path_from_uri(file_uri_)
    if not os.path.isdir(os.path.dirname(dst)):
        raise FileNotFoundError("folder does not exist: %s" % os.path.dirname(dst))
    res = await _download(uri, o.get("headers") or {})
    try:
        shutil.move(res["tempPath"], dst)
    finally:
        if os.path.exists(res["tempPath"]):
            os.remove(res["tempPath"])
    out = {"uri": file_uri(dst), "status": res["status"], "headers": res.get("headers") or {},
           "mimeType": res.get("mimeType")}
    if o.get("md5"):
        out["md5"] = _md5(dst)
    return out


async def get_free_disk_storage_async() -> int:
    return Paths.available_disk_space


async def get_total_disk_capacity_async() -> int:
    return Paths.total_disk_space


getInfoAsync = get_info_async
readAsStringAsync = read_as_string_async
writeAsStringAsync = write_as_string_async
deleteAsync = delete_async
moveAsync = move_async
copyAsync = copy_async
makeDirectoryAsync = make_directory_async
readDirectoryAsync = read_directory_async
downloadAsync = download_async
getFreeDiskStorageAsync = get_free_disk_storage_async
getTotalDiskCapacityAsync = get_total_disk_capacity_async
