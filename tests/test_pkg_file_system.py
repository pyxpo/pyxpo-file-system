"""pyxpo-file-system: expo-file-system's File/Directory/Paths API and the legacy function API."""
import asyncio
import hashlib
import http.server
import os
import threading

import pytest

from pyxpo.module_testing import FakeBridge

from pyxpo_file_system import Directory, File, Paths
from pyxpo_file_system import legacy as FileSystem


@pytest.fixture
def root(tmp_path):
    return Directory(str(tmp_path))


def run(coro):
    return asyncio.run(coro)


def test_uris_and_names(root):
    f = File(root, "a b", "ü.tar.gz")
    assert f.uri == "file://" + root.path + "/a%20b/%C3%BC.tar.gz"
    assert File(f.uri) == f and str(f) == f.uri
    assert f.name == "ü.tar.gz" and f.extension == ".gz" and f.parent_directory == Directory(root, "a b")
    assert Directory(root, "x").uri.endswith("/x/")
    assert File(root.uri, "y.txt").path == os.path.join(root.path, "y.txt")
    assert f.parentDirectory == f.parent_directory
    with pytest.raises(ValueError):
        File("relative.txt")
    with pytest.raises(ValueError):
        File("https://example.com/a")


def test_write_read_text_bytes_base64(root):
    f = File(root, "t.txt")
    assert not f.exists and f.size is None and f.md5 is None
    f.write("héllo")
    assert f.exists and f.text_sync() == "héllo" and f.textSync() == "héllo"
    assert run(f.text()) == "héllo"
    f.write(" world", append=True)
    assert f.text_sync() == "héllo world"
    f.write("AAEC/w==", {"encoding": "base64"})
    assert f.bytes_sync() == b"\x00\x01\x02\xff" and run(f.bytes()) == b"\x00\x01\x02\xff"
    assert f.base64_sync() == "AAEC/w==" and run(f.base64()) == "AAEC/w=="
    f.write(b"raw")
    assert f.size == 3 and f.md5 == hashlib.md5(b"raw").hexdigest()
    assert f.type == "text/plain" and isinstance(f.modification_time, int) and f.modificationTime > 10 ** 12
    with pytest.raises(FileNotFoundError):
        File(root, "missing", "x.txt").write("x")
    with pytest.raises(TypeError):
        f.write(5)


def test_create_delete_copy_move_rename(root):
    f = File(root, "deep", "a.txt")
    with pytest.raises(FileNotFoundError):
        f.create()
    f.create(intermediates=True)
    with pytest.raises(FileExistsError):
        f.create()
    f.write("1")
    f.create({"overwrite": True})
    assert f.text_sync() == ""
    f.write("data")
    d = Directory(root, "out")
    d.create()
    f.copy(d)
    assert File(d, "a.txt").text_sync() == "data"
    with pytest.raises(FileExistsError):
        f.copy(d)
    f.copy(File(root, "b.txt"))
    f.move(Directory(root))
    assert f == File(root, "a.txt") and f.exists and not File(root, "deep", "a.txt").exists
    f.rename("c.txt")
    assert f.name == "c.txt" and f.exists
    with pytest.raises(FileExistsError):
        f.rename("b.txt")
    with pytest.raises(ValueError):
        f.rename("../x")
    f.delete()
    assert not f.exists
    with pytest.raises(FileNotFoundError):
        f.delete()


def test_info_and_handle(root):
    f = File(root, "h.bin")
    assert f.info() == {"exists": False, "uri": f.uri}
    f.write(b"0123456789")
    i = f.info(md5=True)
    assert i["exists"] and i["size"] == 10 and i["md5"] == hashlib.md5(b"0123456789").hexdigest() and "modificationTime" in i
    with f.open() as h:
        assert h.size == 10 and h.offset == 0
        assert h.readBytes(3) == b"012" and h.offset == 3
        h.offset = 8
        h.write_bytes(b"AB")
        assert h.size == 10
    assert h.offset is None
    assert f.bytes_sync() == b"01234567AB"


def test_directories(root):
    d = Directory(root, "a", "b")
    with pytest.raises(FileNotFoundError):
        d.create()
    d.create(intermediates=True)
    with pytest.raises(FileExistsError):
        d.create()
    d.create(idempotent=True)
    d.create_file("x.txt", None).write("12345")
    d.createDirectory("sub")
    img = d.create_file("pic", "image/png")
    assert img.name == "pic.png"
    assert [e.name for e in d.list()] == ["pic.png", "sub", "x.txt"]
    assert isinstance(d.list()[1], Directory) and isinstance(d.list()[2], File)
    assert d.listAsRecords()[1] == {"uri": Directory(d, "sub").uri, "isDirectory": True}
    assert d.size == 5 and d.info()["files"] == ["pic.png", "sub", "x.txt"] and d.info()["size"] == 5
    d.create(overwrite=True)
    assert d.list() == []
    d.rename("c")
    assert d.name == "c" and d.exists
    d.copy(Directory(root, "copy"))
    assert Directory(root, "copy").exists
    with pytest.raises(ValueError):
        Directory(root, "a").move(Directory(root, "a", "c"))
    with pytest.raises(ValueError):
        Directory(root, "a").copy(Directory(root, "a", "c"))
    with pytest.raises(ValueError):
        asyncio.run(FileSystem.copyAsync({"from": Directory(root, "a").uri, "to": Directory(root, "a").uri}))
    assert d.exists
    d.delete()
    assert not d.exists and d.size is None and d.info() == {"exists": False, "uri": d.uri}


def test_paths(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert Paths.document.path == str(tmp_path / ".pyxpo-data" / "documents") and Paths.document.exists
    assert Paths.cache.exists
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)
    monkeypatch.setenv("HOME", "/h")
    monkeypatch.setenv("TMPDIR", "/h-cache")
    import pyxpo_file_system as m
    monkeypatch.setattr(m.sys, "platform", "ios")
    assert Paths.document.path == "/h/Documents" and Paths.cache.path == "/h/Library/Caches"
    monkeypatch.setattr(m.sys, "platform", "android")
    assert Paths.document.path == "/h" and Paths.cache.path == "/h-cache"
    monkeypatch.setattr(m.sys, "platform", "darwin")
    assert Paths.available_disk_space > 0 and Paths.totalDiskSpace >= Paths.availableDiskSpace
    assert Paths.join("/a", "b", "c.txt") == "/a/b/c.txt"
    assert Paths.join("file:///a/", "b c") == "file:///a/b%20c"
    assert Paths.basename("/a/b.txt", ".txt") == "b" and Paths.extname("/a/b.txt") == ".txt" and Paths.dirname("/a/b") == "/a"
    assert Paths.info(str(tmp_path)) == {"exists": True, "isDirectory": True}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/missing":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"nope")
            return
        body = ("hello " + (self.headers.get("X-Token") or "")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        if self.path == "/named":
            self.send_header("Content-Disposition", 'attachment; filename="report.txt"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    s = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:%d" % s.server_address[1]
    s.shutdown()


def test_download_on_desktop(root, server, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    f = run(File.download_file_async(server + "/files/a.txt", root, {"headers": {"X-Token": "t1"}}))
    assert f == File(root, "a.txt") and f.text_sync() == "hello t1"
    named = run(File.downloadFileAsync(server + "/named", root))
    assert named.name == "report.txt"
    with pytest.raises(FileExistsError):
        run(File.download_file_async(server + "/files/a.txt", root))
    run(File.download_file_async(server + "/files/a.txt", f, {"idempotent": True, "headers": {"X-Token": "t2"}}))
    assert f.text_sync() == "hello t2"
    with pytest.raises(RuntimeError, match="404"):
        run(File.download_file_async(server + "/missing", root))
    assert not File(root, "missing").exists
    assert [n for n in os.listdir(Paths.cache.path) if n.startswith(".pyxpo-download")] == []
    with pytest.raises(ValueError):
        run(File.download_file_async("ftp://x/y", root))


def test_download_goes_native_on_device(root, monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path / "cache"))
    import pyxpo_file_system as m
    monkeypatch.setattr(m.sys, "platform", "android")

    def native(url, headers, dest):
        with open(dest, "wb") as out:
            out.write(b"PNG")
        return {"status": 200, "headers": {"Content-Type": "image/png"}, "mimeType": "image/png", "url": url}

    with FakeBridge("android") as fb:
        fb.on("FileSystem", "download", native)
        f = run(File.download_file_async("https://x.test/pics/", root))
        assert fb.calls[0][2][:2] == ("https://x.test/pics/", {})
    assert f.name == "pics.png" and f.bytes_sync() == b"PNG"
    assert os.listdir(str(tmp_path / "cache")) == []


def test_legacy_api(root, server, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert FileSystem.documentDirectory.startswith("file://") and FileSystem.documentDirectory.endswith("/documents/")
    root = Directory(root, "w")
    root.create()
    base = root.uri
    u = base + "n.txt"
    run(FileSystem.write_as_string_async(u, "hi"))
    run(FileSystem.writeAsStringAsync(u, " there", {"append": True}))
    assert run(FileSystem.read_as_string_async(u)) == "hi there"
    assert run(FileSystem.readAsStringAsync(u, {"encoding": FileSystem.EncodingType.Base64, "position": 3, "length": 5})) == "dGhlcmU="
    info = run(FileSystem.get_info_async(u, {"md5": True}))
    assert info["exists"] and not info["isDirectory"] and info["size"] == 8 and info["modificationTime"] < 10 ** 11
    assert info["md5"] == hashlib.md5(b"hi there").hexdigest()
    assert run(FileSystem.getInfoAsync(base + "nope")) == {"exists": False, "isDirectory": False, "uri": base + "nope"}
    run(FileSystem.make_directory_async(base + "x/y", {"intermediates": True}))
    run(FileSystem.make_directory_async(base + "x/y", {"intermediates": True}))
    run(FileSystem.copy_async({"from": u, "to": base + "x/y/n.txt"}))
    run(FileSystem.moveAsync({"from": u, "to": base + "m.txt"}))
    assert run(FileSystem.read_directory_async(base)) == ["m.txt", "x"]
    run(FileSystem.copyAsync({"from": base + "x", "to": base + "x2"}))
    assert run(FileSystem.readDirectoryAsync(base + "x2/y")) == ["n.txt"]
    run(FileSystem.delete_async(base + "x"))
    with pytest.raises(FileNotFoundError):
        run(FileSystem.deleteAsync(base + "x"))
    run(FileSystem.deleteAsync(base + "x", {"idempotent": True}))
    r = run(FileSystem.download_async(server + "/missing", base + "d.txt"))
    assert r["status"] == 404 and r["uri"] == base + "d.txt" and File(root, "d.txt").text_sync() == "nope"
    r = run(FileSystem.downloadAsync(server + "/ok", base + "d.txt", {"md5": True}))
    assert r["status"] == 200 and r["mimeType"] == "text/plain" and r["md5"] == hashlib.md5(b"hello ").hexdigest()
    assert run(FileSystem.getFreeDiskStorageAsync()) > 0 and run(FileSystem.get_total_disk_capacity_async()) > 0


def test_documents_and_caches_on_mac_catalyst(monkeypatch):
    import pyxpo_file_system as fs
    monkeypatch.setenv("HOME", "/h")
    monkeypatch.setattr(fs.sys, "platform", "darwin")
    monkeypatch.setenv("PYXPO_TARGET", "ios")
    assert fs._documents() == "/h/Documents"
    assert fs._caches() == "/h/Library/Caches"
