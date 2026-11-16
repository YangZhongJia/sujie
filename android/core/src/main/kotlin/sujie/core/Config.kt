package sujie.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.io.IOException
import java.time.LocalDateTime

/**
 * 配置模型：字段名与桌面端 `sujie/config.py` 的 client.json / receiver.json 保持一致，
 * 这样两边的配置文件可以互相拷着用，排查问题时也不会出现"两个同名不同义"的字段。
 */
@Serializable
data class ClientConfig(
    val targets: List<TargetJson> = emptyList(),
    @SerialName("capture_mode") val captureMode: String = "screen",
    @SerialName("after_capture") val afterCapture: String = "editor",
    @SerialName("retry_enabled") val retryEnabled: Boolean = true,
    @SerialName("retry_interval") val retryInterval: Int = 60,
    @SerialName("notify_on_send") val notifyOnSend: Boolean = true,
    @SerialName("history_limit") val historyLimit: Int = 200,
    // Android 特有：启动后是否常驻前台服务（接收端模式）
    @SerialName("serve_in_background") val serveInBackground: Boolean = true,
) {
    fun toTargets(): List<ReceiverTarget> = targets.mapNotNull { it.toTarget() }
}

@Serializable
data class TargetJson(
    val id: String = "",
    val name: String = "",
    val host: String = "",
    val port: Int = Wire.HTTP_PORT,
    val token: String = "",
) {
    fun toTarget(): ReceiverTarget? = runCatching {
        ReceiverTarget.parse(host, port, token, name).also { if (id.isNotBlank()) Unit }
    }.getOrNull()

    companion object {
        fun from(target: ReceiverTarget): TargetJson =
            TargetJson(target.id, target.name, target.host, target.port, target.token)
    }
}

@Serializable
data class ReceiverConfig(
    @SerialName("save_dir") val saveDir: String = "",
    val port: Int = Wire.HTTP_PORT,
    val token: String = "",
    @SerialName("subdir_by_date") val subdirByDate: Boolean = true,
    @SerialName("filename_prefix") val filenamePrefix: String = "shot",
    @SerialName("max_upload_mb") val maxUploadMb: Int = Wire.DEFAULT_MAX_UPLOAD_MB,
    // Android 特有：自动保存到系统相册，方便直接在图库里看到
    @SerialName("save_to_gallery") val saveToGallery: Boolean = true,
)

/** 极简 JSON 配置读写：原子写入，坏文件不崩（回退默认值），与桌面端行为一致。 */
class ConfigStore(private val dir: File) {
    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
        prettyPrint = true
    }

    val clientFile: File get() = File(dir, "client.json")
    val receiverFile: File get() = File(dir, "receiver.json")

    fun loadClient(): ClientConfig = read(clientFile) ?: ClientConfig()
    fun saveClient(config: ClientConfig) = write(clientFile, json.encodeToString(ClientConfig.serializer(), config))

    fun loadReceiver(): ReceiverConfig = read(receiverFile) ?: ReceiverConfig()
    fun saveReceiver(config: ReceiverConfig) =
        write(receiverFile, json.encodeToString(ReceiverConfig.serializer(), config))

    private inline fun <reified T> read(file: File): T? {
        if (!file.isFile) return null
        return try {
            val text = file.readText(Charsets.UTF_8).removePrefix("\uFEFF")
            if (text.isBlank()) null else json.decodeFromString<T>(text)
        } catch (e: Exception) {
            null
        }
    }

    private fun write(file: File, text: String) {
        if (!dir.exists() && !dir.mkdirs()) throw IOException("无法创建配置目录：${dir.absolutePath}")
        val tmp = File(dir, "${file.name}.tmp")
        tmp.writeText(text, Charsets.UTF_8)
        if (!tmp.renameTo(file)) {
            tmp.copyTo(file, overwrite = true)
            tmp.delete()
        }
    }
}

/**
 * 离线待发队列，对齐 `uploader.Outbox`：
 * 发送失败的文件落盘 + `.meta`（记录尚未成功的接收端），恢复连接后只补发失败目标。
 * 条目上限 200，超限淘汰最旧的。
 */
class Outbox(private val dir: File, private val maxItems: Int = 200) {
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    @Serializable
    data class Meta(
        val filename: String = "",
        val targets: List<TargetJson> = emptyList(),
        val keepName: Boolean = false,
    )

    data class Entry(
        val file: File,
        val originalName: String,
        val targets: List<ReceiverTarget>,
        val keepName: Boolean,
    )

    fun count(): Int = mediaFiles().size

    fun add(source: File, originalName: String, targets: List<ReceiverTarget>, keepName: Boolean): File {
        if (!dir.exists()) dir.mkdirs()
        val safe = FileNaming.sanitize(originalName, "shot.png")
        var target = File(dir, safe)
        val stem = safe.substringBeforeLast('.', safe)
        val ext = FileNaming.extensionOf(safe)
        var index = 1
        while (target.exists()) {
            target = File(dir, "$stem-$index$ext")
            index++
        }
        source.copyTo(target, overwrite = true)
        writeMeta(target, Meta(originalName, targets.map { TargetJson.from(it) }, keepName))
        evictOld()
        return target
    }

    fun pending(): List<Entry> = mediaFiles().mapNotNull { file ->
        val meta = readMeta(file) ?: Meta(file.name, emptyList(), false)
        Entry(
            file = file,
            originalName = meta.filename.ifBlank { file.name },
            targets = meta.targets.mapNotNull { it.toTarget() },
            keepName = meta.keepName,
        )
    }

    fun remove(file: File) {
        file.delete()
        metaFile(file).delete()
    }

    /**
     * 补发：每个条目只发给还没成功的接收端。返回完全送达并清理掉的条目数。
     * `send` 返回 true 表示该目标成功。
     */
    fun flush(send: (Entry, ReceiverTarget) -> Boolean): Int {
        var delivered = 0
        for (entry in pending()) {
            if (entry.targets.isEmpty()) continue
            val remaining = entry.targets.filterNot { send(entry, it) }
            if (remaining.isEmpty()) {
                remove(entry.file)
                delivered++
            } else {
                writeMeta(entry.file, Meta(entry.originalName, remaining.map { TargetJson.from(it) }, entry.keepName))
            }
        }
        return delivered
    }

    private fun mediaFiles(): List<File> = try {
        dir.listFiles { f -> f.isFile && f.name.lowercase().let { n -> MEDIA.any { n.endsWith(it) } } }
            ?.sortedBy { it.lastModified() } ?: emptyList()
    } catch (e: Exception) {
        emptyList()
    }

    private fun evictOld() {
        val files = mediaFiles()
        val excess = files.size - maxItems
        if (excess <= 0) return
        files.take(excess).forEach { remove(it) }
    }

    private fun metaFile(file: File) = File(dir, file.name + ".meta")

    private fun writeMeta(file: File, meta: Meta) {
        try {
            metaFile(file).writeText(json.encodeToString(Meta.serializer(), meta), Charsets.UTF_8)
        } catch (_: IOException) {
        }
    }

    private fun readMeta(file: File): Meta? = try {
        val m = metaFile(file)
        if (!m.isFile) null else json.decodeFromString(Meta.serializer(), m.readText(Charsets.UTF_8))
    } catch (e: Exception) {
        null
    }

    private companion object {
        val MEDIA = listOf(".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mkv", ".mov", ".avi")
    }
}

/** 截图的落盘命名：`shot-20261116-153012.png`，与桌面端 `_encode_pil` 同构。 */
fun screenshotFileName(now: LocalDateTime = LocalDateTime.now()): String =
    FileNaming.timestampName("shot", ".png", now)
