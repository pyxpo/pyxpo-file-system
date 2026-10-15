package dev.pyxpo.modules.filesystem

import dev.pyxpo.moduleapi.PxModule
import dev.pyxpo.moduleapi.PxModuleContext
import dev.pyxpo.moduleapi.PxReply
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * HTTP downloads for pyxpo-file-system. File reads and writes run in Python; only the network part is native
 * so it uses the system's certificates and proxy settings.
 */
class FileSystemModule : PxModule() {
    override val name = "FileSystem"

    override fun call(ctx: PxModuleContext, method: String, args: JSONArray, reply: PxReply) {
        if (method != "download") { reply(null, "unknown native call FileSystem.$method"); return }
        val url = args.optString(0)
        val headers = args.optJSONObject(1) ?: JSONObject()
        val dest = args.optString(2)
        if (!(url.startsWith("http://", true) || url.startsWith("https://", true)) || dest.isEmpty()) {
            reply(null, "FileSystem.download needs an http(s) URL and a destination path")
            return
        }
        executor.execute {
            try { reply(download(url, headers, File(dest)), null) }
            catch (e: Throwable) { reply(null, e.message ?: e.toString()) }
        }
    }

    private fun download(start: String, headers: JSONObject, dest: File): Map<String, Any?> {
        var url = URL(start)
        // HttpURLConnection does not follow redirects between http and https, so follow them here.
        repeat(MAX_REDIRECTS + 1) {
            val c = url.openConnection() as HttpURLConnection
            try {
                c.instanceFollowRedirects = false
                c.connectTimeout = 30_000
                c.readTimeout = 60_000
                headers.keys().forEach { k -> c.setRequestProperty(k, headers.optString(k)) }
                val code = c.responseCode
                val location = c.getHeaderField("Location")
                if (code in 300..399 && code != 304 && location != null) {
                    url = URL(url, location)
                    return@repeat
                }
                val body = if (code >= 400) c.errorStream else c.inputStream
                dest.parentFile?.mkdirs()
                dest.outputStream().use { out -> body?.use { it.copyTo(out) } }
                val out = HashMap<String, String>()
                c.headerFields.forEach { (k, v) -> if (k != null && v != null) out[k] = v.joinToString(", ") }
                return mapOf("status" to code, "headers" to out,
                    "mimeType" to c.contentType?.substringBefore(';')?.trim(), "url" to url.toString())
            } finally {
                c.disconnect()
            }
        }
        throw java.io.IOException("too many redirects")
    }

    companion object {
        private const val MAX_REDIRECTS = 5
        private val executor = Executors.newCachedThreadPool { r -> Thread(r, "pyxpo-filesystem") }
    }
}
