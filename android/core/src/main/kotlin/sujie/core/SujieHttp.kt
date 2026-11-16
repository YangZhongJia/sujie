package sujie.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Callable
import java.util.concurrent.Executors

@Serializable
data class PingInfo(
    val ok: Boolean = false,
    val app: String = "",
    val version: String = "",
    val device: String = "",
    val ips: List<String> = emptyList(),
    val ip: String = "",
    @SerialName("http_port") val httpPort: Int = Wire.HTTP_PORT,
    @SerialName("save_dir") val saveDir: String = "",
    @SerialName("max_upload_mb") val maxUploadMb: Int = 0,
    val count: Int = 0,
    val message: String = "",
)

@Serializable
data class UploadReply(
    val ok: Boolean = false,
    val message: String = "",
    val path: String = "",
    val name: String = "",
    val size: Long = 0,
)

sealed class UploadOutcome {
    abstract val message: String

    data class Ok(override val message: String, val remotePath: String) : UploadOutcome()
    data class Failed(override val message: String) : UploadOutcome()

    val isOk: Boolean get() = this is Ok
}

data class SendResult(
    val succeeded: Int,
    val total: Int,
    val failures: List<Pair<ReceiverTarget, String>>,
) {
    val ok: Boolean get() = total > 0 && failures.isEmpty()

    /** 与桌面端一致：只有一个目标时透出具体原因，否则给汇总。 */
    fun summary(): String = when {
        total == 0 -> "尚未配置接收端地址"
        failures.isEmpty() -> "已发送到 $succeeded/$total 个接收端"
        total == 1 -> failures.first().second
        else -> "已发送到 $succeeded/$total 个接收端；${failures.size} 个失败"
    }
}

/** 局域网直连的 HTTP 客户端。字段、头、超时全部对齐 `sujie/uploader.py`。 */
object SujieHttp {
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }
    private const val MAX_PARALLEL_TARGETS = 4

    fun ping(target: ReceiverTarget, timeoutMs: Int = 4000): UploadOutcome {
        val url = URL("http://${target.host}:${target.port}/ping")
        return try {
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
                useCaches = false
                setRequestProperty("User-Agent", Wire.USER_AGENT)
                if (target.token.isNotEmpty()) setRequestProperty(Wire.HEADER_TOKEN, target.token)
            }
            try {
                val code = conn.responseCode
                val body = (if (code in 200..299) conn.inputStream else conn.errorStream)
                    ?.bufferedReader()?.use { it.readText() } ?: ""
                when {
                    code == 401 -> UploadOutcome.Failed(Wire.MSG_TOKEN_INVALID)
                    code !in 200..299 -> UploadOutcome.Failed("HTTP $code: ${conn.responseMessage}")
                    else -> {
                        val info = runCatching { json.decodeFromString<PingInfo>(body) }.getOrNull()
                        UploadOutcome.Ok("连接正常", info?.device.orEmpty())
                    }
                }
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            UploadOutcome.Failed("无法连接 ${target.host}:${target.port} —— ${e.readable()}")
        }
    }

    fun fetchInfo(target: ReceiverTarget, timeoutMs: Int = 4000): PingInfo? {
        val url = URL("http://${target.host}:${target.port}/ping")
        return try {
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
                useCaches = false
                setRequestProperty("User-Agent", Wire.USER_AGENT)
                if (target.token.isNotEmpty()) setRequestProperty(Wire.HEADER_TOKEN, target.token)
            }
            try {
                if (conn.responseCode !in 200..299) return null
                val body = conn.inputStream.bufferedReader().use { it.readText() }
                runCatching { json.decodeFromString<PingInfo>(body) }.getOrNull()
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            null
        }
    }

    /**
     * 流式上传：文件多大都只占一个块的内存（桌面端 `http_upload_file` 的等价实现）。
     * `onProgress(已发送字节, 总字节)` 在调用线程回调。
     */
    fun upload(
        target: ReceiverTarget,
        fileName: String,
        file: File,
        keepName: Boolean = false,
        timeoutMs: Int = 120_000,
        onProgress: ((Long, Long) -> Unit)? = null,
    ): UploadOutcome {
        val total = file.length()
        if (total <= 0L) return UploadOutcome.Failed("文件为空：${file.name}")
        val url = URL("http://${target.host}:${target.port}/upload")
        var conn: HttpURLConnection? = null
        try {
            conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                useCaches = false
                // 分块写文件：不能设固定 Content-Length 后一次 write，否则会整段进内存
                setFixedLengthStreamingMode(total)
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
                setRequestProperty("User-Agent", Wire.USER_AGENT)
                setRequestProperty("Content-Type", "application/octet-stream")
                setRequestProperty(Wire.HEADER_FILE_NAME, Wire.quoteFileName(fileName))
                setRequestProperty(Wire.HEADER_SIZE, total.toString())
                setRequestProperty(Wire.HEADER_STREAM, "1")
                if (keepName) setRequestProperty(Wire.HEADER_KEEP_NAME, "1")
                if (target.token.isNotEmpty()) setRequestProperty(Wire.HEADER_TOKEN, target.token)
            }
            conn.outputStream.use { out ->
                file.inputStream().use { input ->
                    val buffer = ByteArray(Wire.CHUNK_SIZE)
                    var sent = 0L
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        out.write(buffer, 0, read)
                        sent += read
                        onProgress?.invoke(sent, total)
                    }
                }
            }
            val code = conn.responseCode
            val body = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""
            val reply = runCatching { json.decodeFromString<UploadReply>(body) }.getOrNull()
            return when {
                code == 401 -> UploadOutcome.Failed(Wire.MSG_TOKEN_INVALID)
                code == 413 -> UploadOutcome.Failed(reply?.message ?: "文件太大，接收端拒绝接收")
                code !in 200..299 -> UploadOutcome.Failed(
                    "HTTP $code ${reply?.message.orEmpty()}".trim()
                )
                else -> UploadOutcome.Ok(reply?.message ?: Wire.MSG_RECEIVED, reply?.path.orEmpty())
            }
        } catch (e: Exception) {
            // 接收端在 401/413 时故意不回读请求体（不想白读几十 MB）就直接关连接，
            // 客户端往往先看到写失败而不是状态码。回查一次 /ping 把真实原因翻译出来，
            // 与桌面端 uploader.http_upload_file 的做法一致。
            return UploadOutcome.Failed(diagnose(target, total) ?: "上传失败：${e.readable()}")
        } finally {
            conn?.disconnect()
        }
    }

    /** 上传异常后回查接收端，判断到底是密钥不对还是文件太大。 */
    private fun diagnose(target: ReceiverTarget, total: Long): String? {
        val url = URL("http://${target.host}:${target.port}/ping")
        return try {
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                connectTimeout = 3000
                readTimeout = 3000
                useCaches = false
                setRequestProperty("User-Agent", Wire.USER_AGENT)
                if (target.token.isNotEmpty()) setRequestProperty(Wire.HEADER_TOKEN, target.token)
            }
            try {
                if (conn.responseCode == 401) return Wire.MSG_TOKEN_INVALID
                val body = conn.inputStream.bufferedReader().use { it.readText() }
                val limit = runCatching {
                    json.decodeFromString<PingInfo>(body).maxUploadMb
                }.getOrDefault(0)
                if (limit > 0 && total > limit * 1024L * 1024L) {
                    "文件太大：${total / 1048576} MB，接收端上限 $limit MB（可以在接收端设置里调大）"
                } else {
                    null
                }
            } finally {
                conn.disconnect()
            }
        } catch (e: Exception) {
            null
        }
    }

    /** 并行发给所有接收端（上限 4 路），顺序与 targets 一致。 */
    fun sendToAll(
        targets: List<ReceiverTarget>,
        fileName: String,
        file: File,
        keepName: Boolean = false,
        onProgress: ((Long, Long) -> Unit)? = null,
    ): SendResult {
        if (targets.isEmpty()) return SendResult(0, 0, emptyList())
        if (targets.size == 1) {
            val outcome = upload(targets[0], fileName, file, keepName, onProgress = onProgress)
            return if (outcome.isOk) SendResult(1, 1, emptyList())
            else SendResult(0, 1, listOf(targets[0] to outcome.message))
        }
        val pool = Executors.newFixedThreadPool(minOf(targets.size, MAX_PARALLEL_TARGETS))
        try {
            val futures = targets.map { target ->
                pool.submit(Callable { upload(target, fileName, file, keepName) })
            }
            val failures = mutableListOf<Pair<ReceiverTarget, String>>()
            var succeeded = 0
            futures.forEachIndexed { index, future ->
                val outcome = runCatching { future.get() }
                    .getOrElse { UploadOutcome.Failed("上传失败：${it.readable()}") }
                if (outcome.isOk) succeeded++ else failures += targets[index] to outcome.message
            }
            return SendResult(succeeded, targets.size, failures)
        } finally {
            pool.shutdown()
        }
    }

    fun testAll(targets: List<ReceiverTarget>): SendResult {
        if (targets.isEmpty()) return SendResult(0, 0, emptyList())
        val failures = mutableListOf<Pair<ReceiverTarget, String>>()
        var succeeded = 0
        for (target in targets) {
            val outcome = ping(target)
            if (outcome.isOk) succeeded++ else failures += target to outcome.message
        }
        return SendResult(succeeded, targets.size, failures)
    }
}

/** 异常文案：Android 上 `UnknownHostException` 之类直接显示类名用户看不懂。 */
fun Throwable.readable(): String = when (this) {
    is java.net.SocketTimeoutException -> "连接超时"
    is java.net.UnknownHostException -> "找不到主机"
    is java.net.ConnectException -> "连接被拒绝（接收端没启动或端口不对）"
    is java.net.NoRouteToHostException -> "网络不可达"
    is IOException -> message ?: this::class.java.simpleName
    else -> message ?: this::class.java.simpleName
}
