package sujie.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.util.concurrent.atomic.AtomicBoolean

/** 一台被发现的接收端（`discovery.discover()` 的返回值）。 */
data class DiscoveredDevice(
    val device: String,
    val ip: String,
    val httpPort: Int,
    val version: String,
    val saveDir: String,
    val ips: List<String>,
    val maxUploadMb: Int,
) {
    fun toTarget(token: String = ""): ReceiverTarget =
        ReceiverTarget(ip, httpPort, token, device)
}

/**
 * UDP 广播发现，与 `sujie/discovery.py` 同协议：
 * 发 `SHOTBRIDGE_DISCOVER` 到 8766，接收端回 `SHOTBRIDGE_REPLY` + JSON。
 *
 * 除了受限广播 255.255.255.255，还会按网卡子网地址广播一次：
 * 部分 Android 机型 / AP 隔离策略会丢受限广播，但子网广播能到。
 */
object Discovery {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }

    fun discover(timeoutMs: Long = 1600, extraAddresses: List<String> = emptyList()): List<DiscoveredDevice> {
        val found = LinkedHashMap<String, DiscoveredDevice>()
        DatagramSocket().use { socket ->
            socket.broadcast = true
            socket.soTimeout = 200
            val packet = DatagramPacket(Wire.DISCOVER_MAGIC, Wire.DISCOVER_MAGIC.size)
            val addresses = buildList {
                add("255.255.255.255")
                addAll(subnetBroadcasts())
                addAll(extraAddresses)
                add("127.0.0.1")
            }.distinct()
            for (addr in addresses) {
                try {
                    packet.address = InetAddress.getByName(addr)
                    packet.port = Wire.DISCOVERY_PORT
                    socket.send(packet)
                } catch (_: IOException) {
                }
            }
            val deadline = System.currentTimeMillis() + timeoutMs
            val buffer = ByteArray(4096)
            while (System.currentTimeMillis() < deadline) {
                val incoming = DatagramPacket(buffer, buffer.size)
                try {
                    socket.receive(incoming)
                } catch (_: java.net.SocketTimeoutException) {
                    continue
                } catch (_: IOException) {
                    break
                }
                val data = incoming.data.copyOfRange(0, incoming.length)
                if (!data.hasPrefix(Wire.DISCOVER_REPLY_MAGIC)) continue
                val payload = String(data, Wire.DISCOVER_REPLY_MAGIC.size, data.size - Wire.DISCOVER_REPLY_MAGIC.size, Charsets.UTF_8)
                val obj = runCatching { json.parseToJsonElement(payload) as? JsonObject }.getOrNull() ?: continue
                val device = obj.string("device").ifBlank { incoming.address.hostAddress ?: "" }
                val sourceIp = incoming.address.hostAddress ?: device
                val ips = (obj["ips"]?.let { runCatching { json.decodeFromString<List<String>>(it.toString()) }.getOrNull() })
                    ?: listOf(sourceIp)
                found[device] = DiscoveredDevice(
                    device = device,
                    ip = sourceIp,
                    httpPort = obj.int("http_port") ?: Wire.HTTP_PORT,
                    version = obj.string("version"),
                    saveDir = obj.string("save_dir"),
                    ips = ips,
                    maxUploadMb = obj.int("max_upload_mb") ?: 0,
                )
            }
        }
        return found.values.toList()
    }

    private fun subnetBroadcasts(): List<String> = try {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { runCatching { it.isUp && !it.isLoopback }.getOrDefault(false) }
            .flatMap { it.interfaceAddresses }
            .mapNotNull { it.broadcast?.hostAddress }
    } catch (e: Exception) {
        emptyList()
    }
}

/** 接收端：应答发现请求（`DiscoveryResponder` 的等价实现）。 */
class DiscoveryResponder(private val infoProvider: () -> Map<String, Any?>) {
    private val running = AtomicBoolean(false)
    private var socket: DatagramSocket? = null
    private var thread: Thread? = null

    fun start(): Boolean {
        if (!running.compareAndSet(false, true)) return true
        return try {
            val sock = DatagramSocket(null)
            sock.reuseAddress = true
            sock.broadcast = true
            sock.soTimeout = 1000
            sock.bind(InetSocketAddress(Wire.DISCOVERY_PORT))
            socket = sock
            thread = Thread({
                val buffer = ByteArray(1024)
                while (running.get()) {
                    val packet = DatagramPacket(buffer, buffer.size)
                    try {
                        sock.receive(packet)
                    } catch (_: java.net.SocketTimeoutException) {
                        continue
                    } catch (_: IOException) {
                        break
                    }
                    val data = packet.data.copyOfRange(0, packet.length)
                    if (!data.hasPrefix(Wire.DISCOVER_MAGIC)) continue
                    val payload = runCatching {
                        buildJsonObject { infoProvider().forEach { (k, v) -> putJsonValue(k, v) } }.toString()
                    }.getOrNull() ?: continue
                    val reply = Wire.DISCOVER_REPLY_MAGIC + payload.toByteArray(Charsets.UTF_8)
                    try {
                        sock.send(DatagramPacket(reply, reply.size, packet.address, packet.port))
                    } catch (_: IOException) {
                    }
                }
            }, "sujie-discovery").apply {
                isDaemon = true
                start()
            }
            true
        } catch (e: IOException) {
            running.set(false)
            false
        }
    }

    fun stop() {
        running.set(false)
        try {
            socket?.close()
        } catch (_: Exception) {
        }
        socket = null
        thread = null
    }
}

private fun ByteArray.hasPrefix(prefix: ByteArray): Boolean {
    if (size < prefix.size) return false
    for (i in prefix.indices) {
        if (this[i] != prefix[i]) return false
    }
    return true
}

private fun kotlinx.serialization.json.JsonObject.string(key: String): String =
    runCatching { this[key]?.jsonPrimitive?.content ?: "" }.getOrDefault("")

private fun kotlinx.serialization.json.JsonObject.int(key: String): Int? =
    runCatching { this[key]?.jsonPrimitive?.content?.toIntOrNull() }.getOrNull()

private fun kotlinx.serialization.json.JsonObjectBuilder.putJsonValue(key: String, value: Any?) {
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
