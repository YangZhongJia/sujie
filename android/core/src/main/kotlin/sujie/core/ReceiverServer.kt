package sujie.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.BufferedInputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.OutputStream
import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.time.LocalDateTime
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/** 接收端落盘策略：与 `receiver.py` 的 `target_dir()` / `_save_stream()` 对齐。 */
class ReceiveStore(
    private val rootDir: File,
    private val subdirByDate: Boolean = true,
    private val prefix: String = "shot",
    /** 落盘完成后的回调（Android 用它把文件发布进系统图库）。 */
    private val onSaved: ((File) -> Unit)? = null,
) {
    fun targetDir(now: LocalDateTime = LocalDateTime.now()): File =
        if (subdirByDate) File(rootDir, now.format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd")))
        else rootDir

    /**
     * 把请求体写到最终文件。先写 `.part` 再改名，避免半截文件被当成成品；
     * 重名检查在锁内做，与桌面端 `_NAMING_LOCK` 等价。
     */
    fun save(
        sanitized: String,
        length: Long,
        keepName: Boolean,
        body: java.io.InputStream,
        now: LocalDateTime = LocalDateTime.now(),
    ): Pair<File, Long> {
        val dir = targetDir(now)
        if (!dir.exists() && !dir.mkdirs()) throw IOException("无法创建目录：${dir.absolutePath}")
        val ext = FileNaming.extensionOf(sanitized).ifEmpty { ".png" }
        // .part 名每请求唯一：并发上传时两个线程绝不能写同一个临时文件
        val stamp = now.format(java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"))
        val part = File(dir, "$prefix-$stamp-${UUID.randomUUID().toString().take(8)}.part")
        var written = 0L
        try {
            FileOutputStream(part).use { out ->
                val buffer = ByteArray(Wire.CHUNK_SIZE)
                var remaining = length
                while (remaining > 0) {
                    val read = body.read(buffer, 0, minOf(buffer.size.toLong(), remaining).toInt())
                    if (read < 0) break
                    out.write(buffer, 0, read)
                    written += read
                    remaining -= read
                }
            }
            if (written != length) throw IOException("接收不完整（$written/$length 字节）")
            val candidate = synchronized(NAMING_LOCK) { uniqueName(dir, sanitized, ext, keepName, now) }
            if (!part.renameTo(candidate)) {
                part.copyTo(candidate, overwrite = true)
                part.delete()
            }
            // 回调失败不能影响"已收下"这个事实
            runCatching { onSaved?.invoke(candidate) }
            return candidate to written
        } catch (e: IOException) {
            part.delete()
            throw e
        }
    }

    private fun uniqueName(dir: File, sanitized: String, ext: String, keepName: Boolean, now: LocalDateTime): File {
        val stem = if (keepName) FileNaming.keepNameParts(sanitized).first
        else FileNaming.timestampName(prefix, ext, now).removeSuffix(ext)
        var index = 0
        while (true) {
            val file = File(dir, FileNaming.withSuffix(stem, ext, index))
            if (!file.exists()) return file
            index++
        }
    }

    private companion object {
        val NAMING_LOCK = Any()
    }
}

/**
 * 最小 HTTP 接收端，只实现桌面端客户端用到的两个路由：
 * `GET /ping`、`POST /upload`。行为（401/413/400/落盘/JSON 响应）逐条对齐 `receiver.py`。
 */
class ReceiverServer(
    private val port: Int,
    private val token: String,
    private val store: ReceiveStore,
    private val maxUploadMb: Int = Wire.DEFAULT_MAX_UPLOAD_MB,
    /** 设备名：桌面端按它做发现去重，必须唯一可辨（Android 传 Build.MODEL）。 */
    private val deviceName: String = defaultHostName(),
    private val info: () -> Map<String, Any?> = { emptyMap() },
) {
    private val json = Json { ignoreUnknownKeys = true }
    private var server: ServerSocket? = null
    private var acceptThread: Thread? = null
    private val pool = Executors.newCachedThreadPool()

    /** 实际绑定的端口（传 0 时由系统分配，测试和"自动选端口"都靠它）。 */
    var boundPort: Int = port
        private set
    private val received = AtomicInteger(0)
    private val lastFile = java.util.concurrent.atomic.AtomicReference("")
    private val lastTime = java.util.concurrent.atomic.AtomicReference("")

    val receivedCount: Int get() = received.get()
    val lastReceivedFile: String get() = lastFile.get()
    val lastReceivedTime: String get() = lastTime.get()

    fun start(): ReceiverServer {
        val socket = ServerSocket()
        socket.reuseAddress = true
        socket.bind(InetSocketAddress("0.0.0.0", port))
        boundPort = socket.localPort
        server = socket
        acceptThread = Thread({
            while (!socket.isClosed) {
                val client = try {
                    socket.accept()
                } catch (e: IOException) {
                    break
                }
                pool.execute { handle(client) }
            }
        }, "sujie-http").apply {
            isDaemon = true
            start()
        }
        return this
    }

    fun stop() {
        try {
            server?.close()
        } catch (_: IOException) {
        }
        server = null
        pool.shutdownNow()
        acceptThread = null
    }

    private fun handle(client: Socket) {
        client.use { socket ->
            socket.soTimeout = 30_000
            val input = BufferedInputStream(socket.getInputStream())
            val output = socket.getOutputStream()
            try {
                val requestLine = readLine(input) ?: return
                val parts = requestLine.split(' ')
                if (parts.size < 2) return
                val method = parts[0].uppercase()
                val path = parts[1].substringBefore('?').trimEnd('/').ifEmpty { "/" }

                val headers = LinkedHashMap<String, String>()
                while (true) {
                    val line = readLine(input) ?: break
                    if (line.isEmpty()) break
                    val colon = line.indexOf(':')
                    if (colon <= 0) continue
                    headers[line.substring(0, colon).trim().lowercase()] = line.substring(colon + 1).trim()
                    if (headers.size > 64) break
                }

                if (!authorized(headers)) {
                    respondJson(output, 401, mapOf("ok" to false, "message" to "token 无效"))
                    return
                }
                when {
                    method == "GET" && path in setOf("/", "/ping", "/health") ->
                        respondJson(output, 200, buildInfo())
                    method == "POST" && path == "/upload" ->
                        handleUpload(input, output, headers)
                    else -> respondJson(output, 404, mapOf("ok" to false, "message" to "not found"))
                }
            } catch (e: IOException) {
                // 客户端中途断开：不写日志，不影响其他请求
            }
        }
    }

    private fun handleUpload(input: BufferedInputStream, output: OutputStream, headers: Map<String, String>) {
        val length = headers["content-length"]?.toLongOrNull() ?: 0L
        if (length <= 0) {
            respondJson(output, 400, mapOf("ok" to false, "message" to "空请求体"))
            return
        }
        if (maxUploadMb > 0 && length > maxUploadMb * 1024L * 1024L) {
            respondJson(
                output, 413,
                mapOf("ok" to false, "message" to "文件太大（上限 $maxUploadMb MB），可在接收端设置里调整"),
            )
            return
        }
        val rawName = java.net.URLDecoder.decode(headers[Wire.HEADER_FILE_NAME.lowercase()] ?: "", "UTF-8")
        val name = FileNaming.sanitize(rawName, "shot.png")
        val keepName = headers[Wire.HEADER_KEEP_NAME.lowercase()] == "1"
        val saved = try {
            store.save(name, length, keepName, input)
        } catch (e: IOException) {
            respondJson(output, 500, mapOf("ok" to false, "message" to "写入失败：${e.message}"))
            return
        }
        received.incrementAndGet()
        lastFile.set(saved.first.absolutePath)
        lastTime.set(LocalDateTime.now().format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")))
        respondJson(
            output, 200,
            mapOf(
                "ok" to true,
                "message" to Wire.MSG_RECEIVED,
                "path" to saved.first.absolutePath,
                "name" to saved.first.name,
                "size" to saved.second,
            ),
        )
    }

    private fun authorized(headers: Map<String, String>): Boolean {
        if (token.isBlank()) return true
        return headers[Wire.HEADER_TOKEN.lowercase()] == token
    }

    private fun buildInfo(): Map<String, Any?> = buildMap {
        put("ok", true)
        put("app", Wire.APP_NAME)
        put("version", Wire.VERSION)
        put("device", deviceName)
        put("ips", localIpv4Addresses())
        put("ip", localIpv4Addresses().firstOrNull() ?: "127.0.0.1")
        put("http_port", port)
        put("save_dir", store.targetDir().absolutePath)
        put("max_upload_mb", maxUploadMb)
        put("count", received.get())
        putAll(info())
    }

    private fun respondJson(output: OutputStream, code: Int, payload: Map<String, Any?>) {
        val body = buildJsonObject { payload.forEach { (k, v) -> putJson(k, v) } }.toString().toByteArray(Charsets.UTF_8)
        val head = buildString {
            append("HTTP/1.1 $code ${statusText(code)}\r\n")
            append("Content-Type: application/json; charset=utf-8\r\n")
            append("Content-Length: ${body.size}\r\n")
            append("Connection: close\r\n")
            append("\r\n")
        }
        try {
            output.write(head.toByteArray(Charsets.US_ASCII))
            output.write(body)
            output.flush()
        } catch (_: IOException) {
        }
    }

    private fun statusText(code: Int) = when (code) {
        200 -> "OK"
        400 -> "Bad Request"
        401 -> "Unauthorized"
        404 -> "Not Found"
        413 -> "Payload Too Large"
        500 -> "Internal Server Error"
        else -> "Status"
    }
}

private fun kotlinx.serialization.json.JsonObjectBuilder.putJson(key: String, value: Any?) {
    when (value) {
        null -> put(key, kotlinx.serialization.json.JsonNull)
        is Boolean -> put(key, value)
        is Int -> put(key, value)
        is Long -> put(key, value)
        is Number -> put(key, value.toDouble())
        is List<*> -> put(
            key,
            kotlinx.serialization.json.JsonArray(value.map { kotlinx.serialization.json.JsonPrimitive(it.toString()) })
        )
        else -> put(key, value.toString())
    }
}

private fun readLine(input: BufferedInputStream): String? {
    val buffer = StringBuilder()
    while (true) {
        val b = input.read()
        if (b < 0) return if (buffer.isEmpty()) null else buffer.toString()
        if (b == '\n'.code) return buffer.toString().trimEnd('\r')
        buffer.append(b.toChar())
        if (buffer.length > 8192) return buffer.toString()
    }
}

fun localIpv4Addresses(): List<String> = try {
    NetworkInterface.getNetworkInterfaces().toList()
        .filter { runCatching { it.isUp && !it.isLoopback }.getOrDefault(false) }
        .flatMap { nic -> nic.inetAddresses.toList() }
        .filterIsInstance<Inet4Address>()
        .filter { !it.isLoopbackAddress }
        .map { it.hostAddress ?: "" }
        .filter { it.isNotEmpty() }
} catch (e: Exception) {
    emptyList()
}

private fun defaultHostName(): String = try {
    InetAddress.getLocalHost().hostName
} catch (e: Exception) {
    "android"
}

private fun kotlinx.serialization.json.JsonObject.raw(key: String): String? =
    (this[key] as? kotlinx.serialization.json.JsonPrimitive)?.jsonPrimitive?.content
