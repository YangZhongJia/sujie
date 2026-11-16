package sujie.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime

class WireTest {
    @Test
    fun `magic strings match the desktop protocol byte for byte`() {
        assertEquals("SHOTBRIDGE_DISCOVER", String(Wire.DISCOVER_MAGIC, Charsets.US_ASCII))
        assertEquals("SHOTBRIDGE_REPLY", String(Wire.DISCOVER_REPLY_MAGIC, Charsets.US_ASCII))
        assertEquals(8765, Wire.HTTP_PORT)
        assertEquals(8766, Wire.DISCOVERY_PORT)
        assertEquals("Sujie/1.0", Wire.USER_AGENT)
    }

    @Test
    fun `file name is percent encoded like urllib quote`() {
        // 桌面端用 urllib.parse.quote，空格编成 %20（不是 +），中文按 UTF-8 百分号编码
        assertEquals("shot-1.png", Wire.quoteFileName("shot-1.png"))
        assertEquals("a%20b.png", Wire.quoteFileName("a b.png"))
        assertEquals("%E9%80%9F%E6%88%AA.png", Wire.quoteFileName("速截.png"))
        assertEquals("%E6%8A%A5%E4%BB%B7%E5%8D%95.docx", Wire.quoteFileName("报价单.docx"))
    }

    @Test
    fun `target validation rejects junk like the desktop config does`() {
        assertTrue(runCatching { ReceiverTarget.parse("") }.isFailure)
        assertTrue(runCatching { ReceiverTarget.parse("192.168.1.5 ") }.isFailure.not())
        assertTrue(runCatching { ReceiverTarget.parse("192.168 1.5") }.isFailure)
        assertTrue(runCatching { ReceiverTarget.parse("http://1.2.3.4") }.isFailure)
        assertTrue(runCatching { ReceiverTarget.parse("1.2.3.4", 0) }.isFailure)
        assertTrue(runCatching { ReceiverTarget.parse("1.2.3.4", 70000) }.isFailure)
    }

    @Test
    fun `target id is stable and case insensitive`() {
        assertEquals(TargetId.of("192.168.1.5", 8765), TargetId.of("192.168.1.5", 8765))
        assertEquals(TargetId.of("PC-A", 8765), TargetId.of("pc-a", 8765))
        assertTrue(TargetId.of("192.168.1.5", 8765) != TargetId.of("192.168.1.5", 8766))
        assertEquals(16, TargetId.of("192.168.1.5", 8765).length)
    }
}

class FileNamingTest {
    private val now = LocalDateTime.of(2026, 11, 16, 15, 30, 12)

    @Test
    fun `sanitize mirrors receiver py SAFE_NAME regex`() {
        assertEquals("shot.png", FileNaming.sanitize("shot.png"))
        assertEquals("a_b.png", FileNaming.sanitize("a:b.png"))
        // 桌面端先 os.path.basename，路径部分整段丢弃
        assertEquals("2026.pdf", FileNaming.sanitize("report/2026.pdf"))
        assertEquals("passwd", FileNaming.sanitize("../../etc/passwd"))
        assertEquals("passwd", FileNaming.sanitize("..\\..\\etc\\passwd"))
        assertEquals("中文名字.png", FileNaming.sanitize("中文名字.png"))
        assertEquals("shot.png", FileNaming.sanitize(""))
        assertEquals("shot.png", FileNaming.sanitize("   "))
    }

    @Test
    fun `sanitize truncates at 120 chars`() {
        val long = "a".repeat(200) + ".png"
        assertEquals(120, FileNaming.sanitize(long).length)
    }

    @Test
    fun `timestamp name matches desktop shot-YYYYmmdd-HHMMSS pattern`() {
        assertEquals("shot-20261116-153012.png", FileNaming.timestampName("shot", ".png", now))
        assertEquals("shot-20261116-153012.png", FileNaming.timestampName("", "", now))
    }

    @Test
    fun `keep name stem is capped at 80 chars and falls back to file`() {
        val (stem, ext) = FileNaming.keepNameParts("a".repeat(100) + ".docx")
        assertEquals(80, stem.length)
        assertEquals(".docx", ext)
        // os.path.splitext(".hidden") == (".hidden", "")：点开头的文件没有扩展名
        val (dotFile, noExt) = FileNaming.keepNameParts(".hidden")
        assertEquals(".hidden", dotFile)
        assertEquals("", noExt)
    }

    @Test
    fun `duplicate suffix follows desktop -1 -2 scheme`() {
        assertEquals("a.png", FileNaming.withSuffix("a", ".png", 0))
        assertEquals("a-1.png", FileNaming.withSuffix("a", ".png", 1))
        assertEquals("a-2.png", FileNaming.withSuffix("a", ".png", 2))
    }
}
