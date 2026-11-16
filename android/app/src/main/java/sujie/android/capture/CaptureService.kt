package sujie.android.capture

import android.app.Activity
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.util.DisplayMetrics
import android.view.WindowManager
import sujie.android.util.Notifications
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * 屏幕抓取服务。
 *
 * Android 没有 Windows 的 BitBlt：全屏抓取只能走 MediaProjection，而系统强制要求
 * 用户点一次「立即开始」——这是平台的安全约束，任何应用（包括微信共享屏幕）都绕不过。
 *
 * 能做的是「只授权一次」，关键在两点：
 * 1. 一个 MediaProjection 只调用一次 createVirtualDisplay（Android 14 起这是硬性限制，
 *    第二次调用会直接抛 SecurityException）；
 * 2. 保留 VirtualDisplay 和 ImageReader 常驻，每次截图只是从常驻的 ImageReader 取最新帧。
 *
 * 旧实现每次截图都新建 VirtualDisplay，于是第一次成功、之后必然失败，只能反复弹授权框——
 * 这就是「每点一次球就弹一次提示框」的根因。
 */
class CaptureService : Service() {

    private var projection: MediaProjection? = null
    private var projectionCallback: MediaProjection.Callback? = null
    private var captureThread: HandlerThread? = null
    private var captureHandler: Handler? = null

    // 常驻抓取管线：只建一次
    private var reader: ImageReader? = null
    private var display: VirtualDisplay? = null
    private var displayWidth = 0
    private var displayHeight = 0
    private var displayDpi = 0

    /** 本次抓取请求：listener 收到帧后填入并放行。 */
    private val pendingLatch = AtomicReference<CountDownLatch?>(null)
    private val pendingFrame = AtomicReference<Bitmap?>(null)
    private val pipelineLock = Any()

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        captureThread = HandlerThread("sujie-capture").also { it.start() }
        captureHandler = Handler(captureThread!!.looper)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                startForegroundSafely()
                val code = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
                val data = if (Build.VERSION.SDK_INT >= 33) {
                    intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra(EXTRA_RESULT_DATA)
                }
                if (code == Activity.RESULT_OK && data != null) {
                    attachProjection(code, data)
                } else {
                    stopSelf()
                }
            }
            ACTION_STOP -> stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun startForegroundSafely() {
        val notification = Notifications.serviceNotification(
            this, "速截", "屏幕抓取已就绪，点悬浮球即可截图",
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun attachProjection(resultCode: Int, data: Intent) {
        releasePipeline()
        releaseProjection()
        val manager = getSystemService(MediaProjectionManager::class.java) ?: run {
            stopSelf()
            return
        }
        val created = try {
            manager.getMediaProjection(resultCode, data)
        } catch (e: Exception) {
            null
        } ?: run {
            stopSelf()
            return
        }
        val callback = object : MediaProjection.Callback() {
            override fun onStop() {
                // 用户从系统通知里停止投屏，或系统回收：状态必须同步清掉，
                // 否则下次点球会以为还能抓，静默失败。
                clearProjectionState()
                stopSelf()
            }
        }
        created.registerCallback(callback, Handler(Looper.getMainLooper()))
        projection = created
        projectionCallback = callback
        current = this
        // 立刻把管线建好，第一张截图不用再等
        val metrics = displayMetrics()
        runCatching { ensurePipeline(metrics.widthPixels, metrics.heightPixels, metrics.densityDpi) }
    }

    // ------------------------------------------------------------ 抓取管线

    /**
     * 建立（或按新尺寸重建）常驻 VirtualDisplay + ImageReader。
     * 同一 MediaProjection 只能 createVirtualDisplay 一次，所以尺寸变化时用 resize 而不是重建。
     */
    private fun ensurePipeline(width: Int, height: Int, dpi: Int) {
        synchronized(pipelineLock) {
            val proj = projection ?: throw IllegalStateException("还没有获得屏幕抓取授权")
            if (display != null && width == displayWidth && height == displayHeight) return

            if (display == null) {
                val newReader = newReader(width, height)
                display = proj.createVirtualDisplay(
                    "sujie-capture", width, height, dpi,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                    newReader.surface, null, captureHandler,
                ) ?: throw IllegalStateException("创建虚拟屏幕失败")
                reader = newReader
            } else {
                // 旋转 / 分屏导致尺寸变化：只换 reader + resize，绝不重建 display
                val old = reader
                val newReader = newReader(width, height)
                runCatching { display?.resize(width, height, dpi) }
                runCatching { display?.surface = newReader.surface }
                reader = newReader
                runCatching { old?.close() }
            }
            displayWidth = width
            displayHeight = height
            displayDpi = dpi
        }
    }

    private fun newReader(width: Int, height: Int): ImageReader {
        val newReader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        newReader.setOnImageAvailableListener({ r ->
            val image = try {
                r.acquireLatestImage()
            } catch (e: Exception) {
                null
            } ?: return@setOnImageAvailableListener
            try {
                val latch = pendingLatch.get()
                // 只在有人要图时做像素转换，平时只负责把队列排空、保持帧新鲜
                if (latch != null) {
                    pendingFrame.set(image.toBitmap(width, height))
                    latch.countDown()
                }
            } finally {
                image.close()
            }
        }, captureHandler)
        return newReader
    }

    /** 抓一帧全屏。阻塞调用，必须在后台线程使用。 */
    private fun grab(): Bitmap {
        if (projection == null) throw IllegalStateException("请先授权屏幕抓取")
        val metrics = displayMetrics()
        ensurePipeline(metrics.widthPixels, metrics.heightPixels, metrics.densityDpi)

        val latch = CountDownLatch(1)
        pendingFrame.set(null)
        pendingLatch.set(latch)
        try {
            // 3 秒兜底：正常 100~300ms 就能拿到一帧
            if (!latch.await(3, TimeUnit.SECONDS)) {
                throw IllegalStateException("抓取超时，请重新授权屏幕抓取")
            }
            return pendingFrame.get() ?: throw IllegalStateException("抓取失败：没有拿到图像")
        } finally {
            pendingLatch.set(null)
            pendingFrame.set(null)
        }
    }

    private fun displayMetrics(): DisplayMetrics {
        val wm = getSystemService(WindowManager::class.java)
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        wm?.defaultDisplay?.getRealMetrics(metrics)
        if (metrics.widthPixels == 0 || metrics.heightPixels == 0) {
            @Suppress("DEPRECATION")
            wm?.defaultDisplay?.getMetrics(metrics)
        }
        if (metrics.densityDpi == 0) metrics.densityDpi = resources.displayMetrics.densityDpi
        return metrics
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        // 旋转后第一次截图会走到 ensurePipeline，这里只做预热，失败不影响
        val metrics = displayMetrics()
        runCatching { ensurePipeline(metrics.widthPixels, metrics.heightPixels, metrics.densityDpi) }
    }

    // ------------------------------------------------------------ 生命周期

    private fun releasePipeline() {
        synchronized(pipelineLock) {
            runCatching { display?.release() }
            display = null
            runCatching { reader?.close() }
            reader = null
            displayWidth = 0
            displayHeight = 0
        }
    }

    private fun releaseProjection() {
        projectionCallback?.let { cb -> runCatching { projection?.unregisterCallback(cb) } }
        projectionCallback = null
        runCatching { projection?.stop() }
        projection = null
    }

    private fun clearProjectionState() {
        releasePipeline()
        projection = null
        projectionCallback = null
        if (current === this) current = null
    }

    override fun onDestroy() {
        releasePipeline()
        releaseProjection()
        if (current === this) current = null
        captureThread?.quitSafely()
        captureThread = null
        captureHandler = null
        super.onDestroy()
    }

    companion object {
        const val ACTION_START = "sujie.capture.START"
        const val ACTION_STOP = "sujie.capture.STOP"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        private const val NOTIFICATION_ID = 4101

        @Volatile
        private var current: CaptureService? = null

        val isReady: Boolean get() = current?.projection != null

        fun start(context: Context, resultCode: Int, data: Intent) {
            val intent = Intent(context, CaptureService::class.java).apply {
                action = ACTION_START
                putExtra(EXTRA_RESULT_CODE, resultCode)
                putExtra(EXTRA_RESULT_DATA, data)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.startService(Intent(context, CaptureService::class.java).apply { action = ACTION_STOP })
            current = null
        }

        fun stopSilently() {
            current = null
        }

        /**
         * 阻塞抓一帧。调用方负责放到 IO 线程。
         *
         * 优先走无障碍服务：已启用时完全静默，不弹系统框；
         * 没启用才回退到 MediaProjection（那条路每次新建会话都要用户点确认）。
         */
        fun screenshot(): Bitmap {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R &&
                SujieAccessibilityService.available
            ) {
                return SujieAccessibilityService.grab()
            }
            val service = current ?: throw IllegalStateException(
                "还没有获得截图权限。请在速截里开启「无障碍截图」，或授权一次屏幕抓取"
            )
            return service.grab()
        }

        /** 当前是否有任何一条可用的截图通道。 */
        fun anyChannelReady(): Boolean {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R &&
                SujieAccessibilityService.available
            ) {
                return true
            }
            return current?.projection != null
        }

        fun saveBitmap(bitmap: Bitmap, file: java.io.File) {
            file.parentFile?.mkdirs()
            file.outputStream().use { out ->
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
            }
        }
    }
}

/** ImageReader 的 RGBA 帧 → Bitmap。行尾可能有 padding，必须逐行拷。 */
private fun android.media.Image.toBitmap(targetWidth: Int, targetHeight: Int): Bitmap {
    val plane = planes[0]
    val buffer = plane.buffer
    val pixelStride = plane.pixelStride
    val rowStride = plane.rowStride
    val rowPadding = rowStride - pixelStride * targetWidth
    val widthWithPadding = targetWidth + rowPadding / pixelStride
    val padded = Bitmap.createBitmap(widthWithPadding, targetHeight, Bitmap.Config.ARGB_8888)
    padded.copyPixelsFromBuffer(buffer)
    val result = if (widthWithPadding == targetWidth) {
        padded
    } else {
        Bitmap.createBitmap(padded, 0, 0, targetWidth, targetHeight).also { padded.recycle() }
    }
    return result
}
