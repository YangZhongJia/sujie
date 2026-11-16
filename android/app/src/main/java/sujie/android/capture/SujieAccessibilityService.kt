package sujie.android.capture

import android.accessibilityservice.AccessibilityService
import android.graphics.Bitmap
import android.os.Build
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import androidx.annotation.RequiresApi
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * 免弹窗截图：无障碍服务的 `takeScreenshot()`。
 *
 * 对比 MediaProjection：后者每次新开会话都必须弹系统「立即开始」确认框，
 * 而 `AccessibilityService.takeScreenshot()` 只要用户在系统设置里**启用一次**无障碍服务，
 * 之后截图完全静默——这才是截图工具该有的体验。
 *
 * 代价：需要用户去「设置 → 无障碍」里打开一次，这是平台要求，无法用代码代劳。
 * 所以两条路都保留：启用了无障碍就静默截图，没启用则回退到 MediaProjection。
 */
@RequiresApi(Build.VERSION_CODES.R)
class SujieAccessibilityService : AccessibilityService() {

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // 纯截图用，不监听任何界面事件
    }

    override fun onInterrupt() {
        // 不需要响应中断
    }

    override fun onUnbind(intent: android.content.Intent?): Boolean {
        if (instance === this) instance = null
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        super.onDestroy()
    }

    /** 同步抓一帧。阻塞调用，必须在后台线程使用。 */
    fun grabBlocking(): Bitmap {
        val latch = CountDownLatch(1)
        val holder = AtomicReference<Bitmap?>(null)
        val error = AtomicReference<String?>(null)
        val executor = Executors.newSingleThreadExecutor()
        try {
            takeScreenshot(
                Display.DEFAULT_DISPLAY,
                executor,
                object : TakeScreenshotCallback {
                    override fun onSuccess(screenshot: ScreenshotResult) {
                        try {
                            val hardware = screenshot.hardwareBuffer
                            val bitmap = Bitmap.wrapHardwareBuffer(hardware, screenshot.colorSpace)
                            // wrapHardwareBuffer 返回的是硬件位图，硬件缓冲释放后内容就没了，
                            // 必须立刻软拷贝一份。
                            holder.set(bitmap?.copy(Bitmap.Config.ARGB_8888, false))
                        } catch (e: Exception) {
                            error.set(e.message ?: "解码截图失败")
                        } finally {
                            runCatching { screenshot.hardwareBuffer.close() }
                            latch.countDown()
                        }
                    }

                    override fun onFailure(errorCode: Int) {
                        error.set(
                            when (errorCode) {
                                ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT ->
                                    "截图太频繁，请等一秒再试"
                                ERROR_TAKE_SCREENSHOT_INVALID_DISPLAY -> "显示设备无效"
                                ERROR_TAKE_SCREENSHOT_NO_ACCESSIBILITY_ACCESS -> "无障碍权限已失效"
                                else -> "截图失败（错误码 $errorCode）"
                            }
                        )
                        latch.countDown()
                    }
                },
            )
            if (!latch.await(3, TimeUnit.SECONDS)) {
                throw IllegalStateException("截图超时，请重新开启无障碍服务")
            }
            error.get()?.let { throw IllegalStateException(it) }
            return holder.get() ?: throw IllegalStateException("截图失败：没有拿到图像")
        } finally {
            executor.shutdown()
        }
    }

    companion object {
        @Volatile
        private var instance: SujieAccessibilityService? = null

        /** 无障碍服务是否已启用（决定用哪条截图路径）。 */
        val available: Boolean get() = instance != null

        fun grab(): Bitmap {
            val service = instance ?: throw IllegalStateException("无障碍服务未启用")
            return service.grabBlocking()
        }
    }
}
