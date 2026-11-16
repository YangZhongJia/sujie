package sujie.android.capture

import android.content.Context
import android.graphics.Bitmap
import sujie.android.SujieApp
import sujie.core.SujieHttp
import sujie.core.screenshotFileName
import java.io.File
import java.time.LocalDateTime

/**
 * 抓屏 + 发送的共享实现：悬浮球和主界面都走这里，避免两套逻辑各自漂移。
 */
object CaptureAndSend {

    /**
     * 抓屏前隐藏自己的悬浮控件、抓完恢复。
     *
     * 悬浮球是 TYPE_APPLICATION_OVERLAY 窗口，MediaProjection 会把它一起拍进去；
     * 桌面端是抓屏前 hide() + processEvents()，这里同样必须在抓取前真正生效——
     * 只调 View.GONE 不够，窗口层级要等一帧，所以这里显式等待。
     */
    @Volatile
    private var overlayHider: ((Boolean) -> Unit)? = null

    fun registerOverlayHider(hider: ((Boolean) -> Unit)?) {
        overlayHider = hider
    }

    private fun withOverlaysHidden(block: () -> Bitmap): Bitmap {
        val hider = overlayHider
        if (hider != null) {
            hider(true)
            // 给窗口管理器一帧时间把悬浮窗真正撤下
            Thread.sleep(HIDE_SETTLE_MS)
        }
        return try {
            block()
        } finally {
            hider?.invoke(false)
        }
    }

    private const val HIDE_SETTLE_MS = 220L

    /**
     * 抓一帧全屏并发给所有接收端。阻塞调用，必须在 IO 线程执行。
     * 返回给用户看的一句话结果。
     */
    fun captureAndSend(context: Context): String {
        val container = SujieApp.container()
        val targets = container.client.toTargets()
        if (targets.isEmpty()) return "先添加一台接收端"

        val bitmap = try {
            withOverlaysHidden { CaptureService.screenshot() }
        } catch (e: Exception) {
            return e.message ?: "抓取失败，请重新授权屏幕抓取"
        }
        val file = File(container.cacheDir, screenshotFileName(LocalDateTime.now()))
        return try {
            CaptureService.saveBitmap(bitmap, file)
            sendFile(context, file, keepName = false)
        } finally {
            bitmap.recycle()
        }
    }

    /** 只抓屏存到缓存（框选的第一步），返回文件路径。 */
    fun grabToCache(context: Context, prefix: String): String {
        val container = SujieApp.container()
        val bitmap = withOverlaysHidden { CaptureService.screenshot() }
        val file = File(container.cacheDir, "$prefix-${System.currentTimeMillis()}.png")
        try {
            CaptureService.saveBitmap(bitmap, file)
        } finally {
            bitmap.recycle()
        }
        return file.absolutePath
    }

    /** 发送一个已落盘的文件；失败的接收端进待发队列。 */
    fun sendFile(context: Context, file: File, keepName: Boolean): String {
        val container = SujieApp.container()
        val targets = container.client.toTargets()
        if (targets.isEmpty()) return "先添加一台接收端"
        val result = SujieHttp.sendToAll(targets, file.name, file, keepName)
        if (!result.ok) {
            val failed = targets.filter { t -> result.failures.any { it.first.id == t.id } }
            runCatching { container.outbox.add(file, file.name, failed, keepName) }
        }
        return result.summary()
    }
}
