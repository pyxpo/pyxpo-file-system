import Foundation

/// HTTP downloads for pyxpo-file-system. File reads and writes run in Python; only the network part is native
/// so it uses the system's certificates, proxy settings and redirects.
final class FileSystemModule: PxModule {
    static let moduleName = "FileSystem"

    required init() {}

    func call(_ ctx: PxModuleContext, _ method: String, _ args: [Any], _ reply: @escaping PxReply) {
        guard method == "download" else { reply(nil, "unknown native call FileSystem.\(method)"); return }
        guard args.count >= 3, let urlString = args[0] as? String, let url = URL(string: urlString),
              let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https",
              let dest = args[2] as? String else {
            reply(nil, "FileSystem.download needs an http(s) URL and a destination path")
            return
        }
        var request = URLRequest(url: url)
        for (k, v) in (args[1] as? [String: Any]) ?? [:] { request.setValue("\(v)", forHTTPHeaderField: k) }
        URLSession.shared.downloadTask(with: request) { tmp, response, error in
            if let error = error { reply(nil, error.localizedDescription); return }
            guard let tmp = tmp, let http = response as? HTTPURLResponse else { reply(nil, "no response"); return }
            // The system deletes `tmp` when this handler returns, so move it now.
            do {
                let to = URL(fileURLWithPath: dest)
                try? FileManager.default.removeItem(at: to)
                try FileManager.default.moveItem(at: tmp, to: to)
            } catch {
                reply(nil, "cannot save download: \(error.localizedDescription)")
                return
            }
            var headers: [String: String] = [:]
            for (k, v) in http.allHeaderFields { headers["\(k)"] = "\(v)" }
            reply([
                "status": http.statusCode,
                "headers": headers,
                "mimeType": http.mimeType ?? NSNull(),
                "url": http.url?.absoluteString ?? urlString,
            ], nil)
        }.resume()
    }
}
