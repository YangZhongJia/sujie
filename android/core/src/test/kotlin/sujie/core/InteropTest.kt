package sujie.core

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.net.HttpURLConnection
import java.net.ServerSocket
import java.net.URL
import java.nio.file.Files
import java.time.LocalDateTime

/** 端到端：Kotlin 客户端 ↔ Kotlin 接收端，走真实 HTTP + 真实 UDP 发现。 */
class InteropTest {
    private lateinit var tmp: File
    private lateinit var store: ReceiveStore
    private lateinit var server: ReceiverServer
    private var port = 0

    @Before
    fun setUp() {
        tmp = Files.createTempDirectory("sujie-interop").toFile()
        port = freePort()
        store = ReceiveStore(File(tmp, "recv"), subdirByDate = false, prefix = "shot")
        server = ReceiverServer(port = port, token = "", store = store).start()
        Thread.sleep(120)
    }

    @After
    fun tearDown() {
        server.stop()
        tmp.deleteRecursively()
    }

    @Test
    fun `ping returns desktop compatible payload`() {
        val target = ReceiverTarget("127.0.0.1", port)
        val outcome = SujieHttp.ping(target)
        assertTrue(outcome.message, outcome.isOk)
        val info = SujieHttp.fetchInfo(target)
        assertNotNull(info)
        assertEquals("速截", info!!.app)
        assertEquals(port, info.httpPort)
        assertEquals(Wire.DEFAULT_MAX_UPLOAD_MB, info.maxUploadMb)
        assertTrue(info.ips.isNotEmpty())
    }

    @Test
    fun `upload writes the exact bytes and returns the desktop reply shape`() {
        val payload = ByteArray(2_500_000) { (it * 31 % 251).toByte() }
        val file = File(tmp, "shot-20261116-153012.png").apply { writeBytes(payload) }
        val target = ReceiverTarget("127.0.0.1", port)

        val outcome = SujieHttp.upload(target, file.name, file)
        assertTrue(outcome.message, outcome.isOk)
        val saved = File((outcome as UploadOutcome.Ok).remotePath)
        assertTrue(saved.isFile)
        assertArrayEqualsBytes(payload, saved.readBytes())
        assertEquals(1, server.receivedCount)
        assertEquals(saved.absolutePath, server.lastReceivedFile)
    }

    @Test
    fun `upload honours keep name for arbitrary files`() {
        val file = File(tmp, "报价单.docx").apply { writeBytes(ByteArray(4096) { 7 }) }
        val outcome = SujieHttp.upload(ReceiverTarget("127.0.0.1", port), "报价单.docx", file, keepName = true)
        assertTrue(outcome.message, outcome.isOk)
        assertEquals("报价单.docx", File((outcome as UploadOutcome.Ok).remotePath).name)
    }

    @Test
    fun `token mismatch surfaces the desktop message`() {
        val guarded = ReceiverServer(
            port = 0, token = "s3cret",
            store = ReceiveStore(File(tmp, "guarded"), subdirByDate = false),
        ).start()
        try {
            val gport = guarded.boundPort
            val target = ReceiverTarget("127.0.0.1", gport, "wrong")
            val outcome = SujieHttp.ping(target)
            assertFalse(outcome.isOk)
            assertEquals(Wire.MSG_TOKEN_INVALID, outcome.message)

            val file = File(tmp, "x.png").apply { writeBytes(ByteArray(16)) }
            val upload = SujieHttp.upload(target, "x.png", file)
            assertFalse(upload.isOk)
            assertEquals(Wire.MSG_TOKEN_INVALID, upload.message)

            val okTarget = ReceiverTarget("127.0.0.1", gport, "s3cret")
            assertTrue(SujieHttp.ping(okTarget).isOk)
            assertTrue(SujieHttp.upload(okTarget, "x.png", file).isOk)
        } finally {
            guarded.stop()
        }
    }

    @Test
    fun `oversized upload is rejected with 413 and the limit in the message`() {
        val limited = ReceiverServer(
            port = 0, token = "",
            store = ReceiveStore(File(tmp, "limited"), subdirByDate = false),
            maxUploadMb = 1,
        ).start()
        try {
            val target = ReceiverTarget("127.0.0.1", limited.boundPort)
            val file = File(tmp, "big.bin").apply { writeBytes(ByteArray(2 * 1024 * 1024)) }
            val outcome = SujieHttp.upload(target, "big.bin", file)
            assertFalse(outcome.isOk)
            assertTrue(outcome.message, outcome.message.contains("文件太大"))
        } finally {
            limited.stop()
        }
    }

    @Test
    fun `duplicate names never overwrite and part files are cleaned up`() {
        val target = ReceiverTarget("127.0.0.1", port)
        val file = File(tmp, "dup.png").apply { writeBytes(ByteArray(32) { 1 }) }
        val first = SujieHttp.upload(target, "dup.png", file, keepName = true) as UploadOutcome.Ok
        val second = SujieHttp.upload(target, "dup.png", file, keepName = true) as UploadOutcome.Ok
        assertTrue(first.remotePath != second.remotePath)
        assertEquals("dup.png", File(first.remotePath).name)
        assertEquals("dup-1.png", File(second.remotePath).name)
        assertEquals(0, File(tmp, "recv").listFiles { f -> f.name.endsWith(".part") }?.size ?: 0)
    }

    @Test
    fun `multi target send reports per target failures`() {
        val file = File(tmp, "multi.png").apply { writeBytes(ByteArray(64)) }
        val deadPort = freePort()
        val result = SujieHttp.sendToAll(
            listOf(ReceiverTarget("127.0.0.1", port), ReceiverTarget("127.0.0.1", deadPort)),
            "multi.png", file,
        )
        assertEquals(1, result.succeeded)
        assertEquals(2, result.total)
        assertEquals(1, result.failures.size)
        assertFalse(result.ok)
        assertTrue(result.summary(), result.summary().contains("1/2"))
    }

    @Test
    fun `subdir by date layout matches desktop`() {
        val dated = ReceiveStore(File(tmp, "dated"), subdirByDate = true)
        val now = LocalDateTime.of(2026, 11, 16, 10, 0, 0)
        val dir = dated.targetDir(now)
        assertEquals("2026-11-16", dir.name)
    }

    @Test
    fun `outbox retries only the targets that failed`() {
        val box = Outbox(File(tmp, "outbox"))
        val file = File(tmp, "q.png").apply { writeBytes(ByteArray(24) { 3 }) }
        val bad = ReceiverTarget("127.0.0.1", freePort())
        val good = ReceiverTarget("127.0.0.1", port)
        box.add(file, "q.png", listOf(bad, good), keepName = false)
        assertEquals(1, box.count())

        // 第一次补发：good 通、bad 不通 → 条目保留，只记着 bad
        assertEquals(0, box.flush { _, target -> target.port == good.port })
        assertEquals(1, box.count())
        assertEquals(listOf(bad.port), box.pending().single().targets.map { it.port })

        // 第二次：bad 恢复 → 送达并清理，且不会重复发给 good
        val sentTo = mutableListOf<Int>()
        val delivered = box.flush { _, target ->
            sentTo += target.port
            true
        }
        assertEquals(1, delivered)
        assertEquals(listOf(bad.port), sentTo)
        assertEquals(0, box.count())
    }

    @Test
    fun `outbox keeps the entry when a target is still unreachable`() {
        val box = Outbox(File(tmp, "outbox2"))
        val file = File(tmp, "q2.png").apply { writeBytes(ByteArray(8)) }
        val bad = ReceiverTarget("127.0.0.1", freePort())
        box.add(file, "q2.png", listOf(bad), keepName = false)
        assertEquals(0, box.flush { _, _ -> false })
        assertEquals(1, box.count())
        val entry = box.pending().single()
        assertEquals("q2.png", entry.originalName)
        assertEquals(bad.port, entry.targets.single().port)
    }

    @Test
    fun `config round trip survives a hand edited file`() {
        val dir = File(tmp, "cfg")
        val storeCfg = ConfigStore(dir)
        val target = ReceiverTarget.parse("192.168.1.9", 8765, "tok", "书房电脑")
        storeCfg.saveClient(ClientConfig(targets = listOf(TargetJson.from(target)), captureMode = "region"))
        val loaded = storeCfg.loadClient()
        assertEquals("region", loaded.captureMode)
        assertEquals(target, loaded.toTargets().single())

        // 未知字段 + BOM 都不能让读取崩掉
        File(dir, "client.json").writeText("\uFEFF" + """{"targets":[],"capture_mode":"screen","future_field":42}""")
        assertEquals("screen", storeCfg.loadClient().captureMode)
        assertEquals(0, storeCfg.loadClient().targets.size)

        File(dir, "client.json").writeText("{ not json")
        assertEquals("editor", storeCfg.loadClient().afterCapture)
    }

    @Test
    fun `discovery finds a local responder`() {
        val responder = DiscoveryResponder {
            mapOf(
                "app" to "速截", "version" to "1.2.0", "device" to "android-tablet",
                "ips" to listOf("127.0.0.1"), "ip" to "127.0.0.1",
                "http_port" to port, "save_dir" to store.targetDir().absolutePath,
                "max_upload_mb" to 2048, "count" to 0,
            )
        }
        assertTrue(responder.start())
        try {
            val devices = Discovery.discover(timeoutMs = 1200)
            val found = devices.firstOrNull { it.device == "android-tablet" }
            assertNotNull("发现结果：$devices", found)
            assertEquals(port, found!!.httpPort)
            assertEquals("1.2.0", found.version)
            val target = found.toTarget()
            assertTrue(SujieHttp.ping(target).isOk)
        } finally {
            responder.stop()
        }
    }

    @Test
    fun `raw http client used by the desktop app is accepted`() {
        // 模拟 desktop 的 http_upload_file：分块 + X-Stream + Content-Length
        val file = File(tmp, "raw.bin").apply { writeBytes(ByteArray(1_300_000) { 9 }) }
        val conn = URL("http://127.0.0.1:$port/upload").openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.doOutput = true
        conn.setFixedLengthStreamingMode(file.length())
        conn.setRequestProperty("Content-Type", "application/octet-stream")
        conn.setRequestProperty("X-File-Name", Wire.quoteFileName(file.name))
        conn.setRequestProperty("X-Size", file.length().toString())
        conn.setRequestProperty("X-Stream", "1")
        conn.outputStream.use { out -> file.inputStream().use { it.copyTo(out) } }
        assertEquals(200, conn.responseCode)
        val body = conn.inputStream.bufferedReader().use { it.readText() }
        assertTrue(body, body.contains("\"ok\": true") || body.contains("\"ok\":true"))
        conn.disconnect()
    }

    private fun freePort(): Int = ServerSocket(0).use { it.localPort }

    private fun assertArrayEqualsBytes(expected: ByteArray, actual: ByteArray) {
        assertEquals(expected.size, actual.size)
        for (i in expected.indices) {
            if (expected[i] != actual[i]) throw AssertionError("byte $i differs")
        }
    }
}
