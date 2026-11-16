package sujie.android.ball

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import sujie.android.AppContainer
import sujie.android.MainActivity
import sujie.android.SujieApp
import sujie.android.capture.CaptureAndSend
import sujie.android.capture.ProjectionRequestActivity
import sujie.android.capture.RegionSelectActivity
import sujie.android.util.Notifications
import sujie.android.util.Toasts

/**
 * 桌面悬浮球（Android 版）。
 *
 * 和桌面端一样：常驻屏幕边缘，单击按当前方式截图并发送，长按弹出菜单。
 * 实现手段是 SYSTEM_ALERT_WINDOW 悬浮窗，所以必须先让用户授予「显示在其他应用上层」——
 * 没有这个权限，任何跨应用的悬浮控件都画不出来，这是平台限制，不是取舍。
 */
class FloatingBallService : Service() {

    private lateinit var wm: WindowManager
    private var ball: BallView? = null
    private var ballParams: WindowManager.LayoutParams? = null
    private var menu: View? = null
    private var menuParams: WindowManager.LayoutParams? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val handler = Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("ball", MODE_PRIVATE) }

    @Volatile
    private var busy = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        wm = getSystemService(WindowManager::class.java)
        if (!Settings.canDrawOverlays(this)) {
            stopSelf()
            return
        }
        startForegroundSafely()
        addBall()
        // 抓屏前把球撤下，否则球会被拍进截图里。
        // WindowManager 只能在主线程动，而抓屏在 IO 线程，所以这里 post 回主线程并等它完成。
        CaptureAndSend.registerOverlayHider { hide ->
            val latch = java.util.concurrent.CountDownLatch(1)
            handler.post {
                try {
                    setBallVisible(!hide)
                } finally {
                    latch.countDown()
                }
            }
            latch.await(600, java.util.concurrent.TimeUnit.MILLISECONDS)
        }
        running = true
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_HIDE -> {
                removeBall()
                stopSelf()
                return START_NOT_STICKY
            }
        }
        return START_STICKY
    }

    private fun startForegroundSafely() {
        val notification = Notifications.serviceNotification(
            this, "速截 悬浮球", "单击截图发送，长按打开菜单",
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    // ------------------------------------------------------------ 悬浮球本体

    private fun addBall() {
        if (ball != null) return
        val size = dp(56)
        val view = BallView(this, size)
        val params = WindowManager.LayoutParams(
            size, size,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = prefs.getInt(KEY_X, -1).takeIf { it >= 0 } ?: (screenWidth() - size - dp(16))
            y = prefs.getInt(KEY_Y, -1).takeIf { it >= 0 } ?: (screenHeight() / 3)
        }
        view.onTap = { onBallTap() }
        view.onLongPress = { showMenu() }
        view.positionProvider = { (params.x) to (params.y) }
        view.onMoved = { x, y ->
            params.x = x
            params.y = y
            runCatching { wm.updateViewLayout(view, params) }
        }
        view.onDragFinished = { x, y ->
            prefs.edit().putInt(KEY_X, x).putInt(KEY_Y, y).apply()
        }
        runCatching { wm.addView(view, params) }
        ball = view
        ballParams = params
    }

    private fun removeBall() {
        hideMenu()
        ball?.let { runCatching { wm.removeView(it) } }
        ball = null
        ballParams = null
        running = false
    }

    override fun onDestroy() {
        removeBall()
        scope.cancel()
        super.onDestroy()
    }

    // ---------------------------------------------------------------- 交互

    private fun onBallTap() {
        if (busy) {
            Toasts.show(this, "上一次还没结束…")
            return
        }
        val container = SujieApp.container()
        if (container.client.toTargets().isEmpty()) {
            Toasts.show(this, "先添加一台接收端")
            openMain()
            return
        }
        if (!sujie.android.capture.CaptureService.anyChannelReady()) {
            // 没有抓屏授权：借这个 Activity 走一次系统授权，授权后立刻截一张发出去
            ProjectionRequestActivity.start(this, captureAfterGrant = true)
            return
        }
        busy = true
        setBallBusy(true)
        scope.launch {
            val message = withContext(Dispatchers.IO) {
                CaptureAndSend.captureAndSend(this@FloatingBallService)
            }
            setBallBusy(false)
            busy = false
            Toasts.show(this@FloatingBallService, message)
        }
    }

    private fun showMenu() {
        if (menu != null) {
            hideMenu()
            return
        }
        val container = SujieApp.container()
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#F2FFFFFF"))
            setPadding(dp(6), dp(6), dp(6), dp(6))
        }
        fun addItem(text: String, action: () -> Unit) {
            val item = TextView(this).apply {
                this.text = text
                setTextColor(Color.parseColor("#202124"))
                textSize = 15f
                setPadding(dp(16), dp(12), dp(16), dp(12))
                isClickable = true
                setOnClickListener {
                    hideMenu()
                    action()
                }
            }
            panel.addView(item)
        }
        addItem("截图并发送") { onBallTap() }
        addItem("框选区域发送") { captureRegion() }
        addItem(
            if (sujie.android.receiver.ReceiverService.running) "停止接收端" else "启动接收端",
        ) {
            if (sujie.android.receiver.ReceiverService.running) {
                sujie.android.receiver.ReceiverService.stop(this)
                Toasts.show(this, "接收端已停止")
            } else {
                sujie.android.receiver.ReceiverService.start(this)
                Toasts.show(this, "接收端已启动")
            }
        }
        addItem("打开速截") { openMain() }
        addItem("隐藏悬浮球") { removeBall(); stopSelf() }

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            val ballX = ballParams?.x ?: dp(16)
            val ballY = ballParams?.y ?: dp(200)
            x = (ballX - dp(90)).coerceAtLeast(dp(8))
            y = ballY
        }
        runCatching { wm.addView(panel, params) }.onSuccess {
            menu = panel
            menuParams = params
        }
        // 3 秒后自动收起，避免挡住别的内容
        handler.postDelayed({ hideMenu() }, 4000)
    }

    private fun hideMenu() {
        handler.removeCallbacksAndMessages(null)
        menu?.let { runCatching { wm.removeView(it) } }
        menu = null
        menuParams = null
    }

    private fun captureRegion() {
        if (busy) return
        if (!sujie.android.capture.CaptureService.anyChannelReady()) {
            ProjectionRequestActivity.start(this, captureAfterGrant = false)
            return
        }
        busy = true
        scope.launch {
            val path = withContext(Dispatchers.IO) {
                runCatching {
                    CaptureAndSend.grabToCache(this@FloatingBallService, "region-source")
                }.getOrNull()
            }
            busy = false
            if (path == null) {
                Toasts.show(this@FloatingBallService, "抓取失败，请重新授权屏幕抓取")
                return@launch
            }
            val intent = RegionSelectActivity.intent(this@FloatingBallService, java.io.File(path))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                .putExtra(RegionSelectActivity.EXTRA_SEND, true)
            startActivity(intent)
        }
    }

    private fun openMain() {
        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    private fun setBallVisible(visible: Boolean) {
        if (visible) {
            if (ball == null) addBall()
            ball?.visibility = View.VISIBLE
        } else {
            val view = ball ?: return
            // 置空引用再移除窗口，否则 addBall() 会以为球还在，永远不回来
            ball = null
            ballParams = null
            runCatching { wm.removeViewImmediate(view) }
        }
    }

    private fun setBallBusy(isBusy: Boolean) {
        (ball as? BallView)?.setBusy(isBusy)
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    @Suppress("DEPRECATION")
    private fun screenWidth(): Int = resources.displayMetrics.widthPixels

    @Suppress("DEPRECATION")
    private fun screenHeight(): Int = resources.displayMetrics.heightPixels

    companion object {
        const val ACTION_HIDE = "sujie.ball.HIDE"
        private const val NOTIFICATION_ID = 4301
        private const val KEY_X = "x"
        private const val KEY_Y = "y"

        @Volatile
        var running: Boolean = false
            private set

        fun canDraw(context: Context): Boolean = Settings.canDrawOverlays(context)

        fun start(context: Context): Boolean {
            if (!canDraw(context)) return false
            val intent = Intent(context, FloatingBallService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
            return true
        }

        fun stop(context: Context) {
            context.startService(
                Intent(context, FloatingBallService::class.java).apply { action = ACTION_HIDE }
            )
        }
    }
}
