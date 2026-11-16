package sujie.core

import java.net.URLEncoder
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * 与桌面端 `sujie/discovery.py`、`sujie/receiver.py`、`sujie/uploader.py` 完全一致的线协议常量。
 *
 * 协议是既成事实：桌面端已经在用，Android 端必须逐字节兼容，
 * 所以这里的魔数、端口、头名一律照抄，不做"更优雅"的重命名。
 */
object Wire {
    const val APP_NAME = "速截"
    const val VERSION = "1.2.0"

    const val HTTP_PORT = 8765
    const val DISCOVERY_PORT = 8766

    val DISCOVER_MAGIC = "SHOTBRIDGE_DISCOVER".toByteArray(Charsets.US_ASCII)
    val DISCOVER_REPLY_MAGIC = "SHOTBRIDGE_REPLY".toByteArray(Charsets.US_ASCII)

    const val USER_AGENT = "Sujie/1.0"

    // 请求头（见 uploader.http_upload / http_upload_file）
    const val HEADER_FILE_NAME = "X-File-Name"
    const val HEADER_SIZE = "X-Size"
    const val HEADER_STREAM = "X-Stream"
    const val HEADER_KEEP_NAME = "X-Keep-Name"
    const val HEADER_TOKEN = "X-Token"

    const val CHUNK_SIZE = 1024 * 1024

    /** 与桌面端一致：单文件默认上限 2048 MB，0 表示不限制。 */
    const val DEFAULT_MAX_UPLOAD_MB = 2048

    const val MSG_TOKEN_INVALID = "密钥不匹配（接收端要求 token）"
    const val MSG_RECEIVED = "接收成功"

    fun quoteFileName(name: String): String = URLEncoder.encode(name, "UTF-8").replace("+", "%20")
}

/** 一台接收端。与 `config.receiver_target()` 的字段一一对应，便于两端配置互相拷贝。 */
data class ReceiverTarget(
    val host: String,
    val port: Int = Wire.HTTP_PORT,
    val token: String = "",
    val name: String = "",
) {
    val label: String get() = name.ifBlank { "$host:$port" }
    val id: String get() = TargetId.of(host, port)

    companion object {
        fun parse(host: String, port: Int = Wire.HTTP_PORT, token: String = "", name: String = ""): ReceiverTarget {
            val trimmed = host.trim()
            require(trimmed.isNotEmpty()) { "接收端地址无效" }
            require(trimmed.none { it.isWhitespace() } && '/' !in trimmed) { "接收端地址无效" }
            require(port in 1..65535) { "接收端端口必须在 1 到 65535 之间" }
            return ReceiverTarget(trimmed, port, token.trim(), name.trim())
        }
    }
}

/** 目标 id：桌面端用 sha256("host:port")[:16]，这里保持同构（host 小写）。 */
object TargetId {
    fun of(host: String, port: Int): String {
        val raw = "${host.lowercase(Locale.ROOT)}:$port"
        val digest = java.security.MessageDigest.getInstance("SHA-256").digest(raw.toByteArray(Charsets.UTF_8))
        return digest.take(8).joinToString("") { "%02x".format(it) }
    }
}

/**
 * 接收端落盘命名规则，逐条对齐 `receiver.py` 的 `sanitize_filename` 与 `_save_stream`：
 * - 只保留 `[A-Za-z0-9._\-一-鿿 ]`，其余变 `_`，截断 120 字符；
 * - 不保留原名时用 `前缀-YYYYmmdd-HHMMSS.ext`；
 * - 保留原名时 stem 截断 80 字符。
 */
object FileNaming {
    private val SAFE = Regex("[^A-Za-z0-9._\\-\\u4e00-\\u9fff ]")
    private val STAMP = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss")

    fun sanitize(name: String, fallback: String = "shot.png"): String {
        // 与 os.path.basename 一致：Windows 版接收端把 / 和 \ 都当分隔符
        val base = name.substringAfterLast('/').substringAfterLast('\\').trim()
        val cleaned = SAFE.replace(base, "_")
        if (cleaned.isEmpty()) return fallback
        return cleaned.take(120)
    }

    /** 保留原名（「发送文件」场景）时的 stem/ext。 */
    fun keepNameParts(sanitized: String): Pair<String, String> {
        val dot = sanitized.lastIndexOf('.')
        val stem = if (dot > 0) sanitized.substring(0, dot) else sanitized
        val ext = if (dot > 0) sanitized.substring(dot) else ""
        return (stem.take(80).ifEmpty { "file" }) to ext
    }

    /** 时间戳命名：`shot-20261116-153012.png`。 */
    fun timestampName(prefix: String, extension: String, now: LocalDateTime): String {
        val ext = extension.ifEmpty { ".png" }
        return "${prefix.ifEmpty { "shot" }}-${STAMP.format(now)}$ext"
    }

    /** 重名加后缀：`a.png` → `a-1.png` → `a-2.png`。 */
    fun withSuffix(stem: String, ext: String, index: Int): String =
        if (index <= 0) "$stem$ext" else "$stem-$index$ext"

    fun extensionOf(sanitized: String): String {
        val dot = sanitized.lastIndexOf('.')
        return if (dot > 0) sanitized.substring(dot) else ""
    }
}
