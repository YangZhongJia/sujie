package sujie.android.ball

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View

/**
 * 悬浮球绘制，逐条对齐桌面端 `balloon.FloatingBall.paintEvent`：
 *
 * - 外圈：白色描边（不录制时 alpha 220，宽 2px 缩放）
 * - 主体：径向渐变，中心 #E94F37 提亮 40%，边缘压暗 15%
 * - 图标：白色圆角矩形机身 + 白色圆形镜头（机身 44%×32%，镜头 34%×34%）
 *
 * 桌面端是 QPainter 直接画的，这里用 Canvas 复刻同一套几何比例，
 * 所以平板上的球和 Windows 上的球看起来是同一个东西。
 */
class BallView(context: Context, private val sizePx: Int) : View(context) {
    var onTap: (() -> Unit)? = null
    var onLongPress: (() -> Unit)? = null
    var onMoved: ((Int, Int) -> Unit)? = null
    var onDragFinished: ((Int, Int) -> Unit)? = null
    /** 当前悬浮窗坐标（由 WindowManager.LayoutParams 提供）。 */
    var positionProvider: (() -> Pair<Int, Int>)? = null

    private var accent = Color.parseColor("#E94F37")
    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
    }
    private val bodyPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val iconStroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        color = Color.WHITE
        strokeWidth = maxOf(1.5f, sizePx / 22f)
    }
    private val iconFill = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.WHITE
    }
    private val oval = RectF()

    private var downX = 0f
    private var downY = 0f
    private var startX = 0
    private var startY = 0
    private var dragging = false
    private var longPressFired = false
    private var busy = false
    /** 手指是否仍按在球上。窗口失焦（例如系统授权弹窗抢走焦点）时必须复位。 */
    private var pressed = false
    private val longPress = Runnable {
        // 只有"手指还在球上"才弹菜单：系统对话框抢走触摸后，这里不能误触发
        if (pressed && !dragging) {
            longPressFired = true
            performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
            onLongPress?.invoke()
        }
    }

    fun cancelPress() {
        pressed = false
        removeCallbacks(longPress)
        alpha = if (busy) 0.55f else 1f
    }

    override fun onWindowFocusChanged(hasWindowFocus: Boolean) {
        super.onWindowFocusChanged(hasWindowFocus)
        if (!hasWindowFocus) cancelPress()
    }

    init {
        isClickable = true
    }

    fun setBusy(value: Boolean) {
        busy = value
        alpha = if (value) 0.55f else 1f
        invalidate()
    }

    fun setAccent(color: Int) {
        accent = color
        invalidate()
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        val size = minOf(w, h).toFloat()
        bodyPaint.shader = RadialGradient(
            size * 0.35f, size * 0.30f, size * 0.8f,
            intArrayOf(lighten(accent, 1.4f), darken(accent, 1.15f)),
            floatArrayOf(0f, 1f),
            Shader.TileMode.CLAMP,
        )
    }

    override fun onDraw(canvas: Canvas) {
        val size = minOf(width, height).toFloat()
        // 桌面端所有尺寸都是按 52px 的球写死的，这里等比放大，
        // 否则描边宽度会跟着涨、内缩量却不涨，外圈就会被 View 边界切掉四周。
        val k = size / 52f

        // 外圈：描边中心内缩 1.5k（描边 2k 时外沿离边界还有 0.5k），
        // 抗锯齿不会把圆环切掉。桌面端画在 1px 处是紧贴边界的，Android 需要留这一点余量。
        ringPaint.color = Color.argb(220, 255, 255, 255)
        ringPaint.strokeWidth = 2f * k
        oval.set(1.5f * k, 1.5f * k, size - 1.5f * k, size - 1.5f * k)
        canvas.drawOval(oval, ringPaint)

        // 主体：内缩 3k
        oval.set(3f * k, 3f * k, size - 3f * k, size - 3f * k)
        canvas.drawOval(oval, bodyPaint)

        // 相机机身：44% × 32%，居中略下移 3%
        iconStroke.strokeWidth = maxOf(1.5f, k * 2f)
        val iconW = size * 0.44f
        val iconH = size * 0.32f
        val x = (size - iconW) / 2f
        val y = (size - iconH) / 2f + size * 0.03f
        val radius = 3f * k
        oval.set(x, y, x + iconW, y + iconH)
        canvas.drawRoundRect(oval, radius, radius, iconStroke)

        // 镜头：直径 = 机身宽 34%，位于机身内 33%/20%
        val lens = iconW * 0.34f
        val lx = x + iconW * 0.33f
        val ly = y + iconH * 0.20f
        oval.set(lx, ly, lx + lens, ly + lens)
        canvas.drawOval(oval, iconFill)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = event.rawX
                downY = event.rawY
                val origin = positionProvider?.invoke() ?: (0 to 0)
                startX = origin.first
                startY = origin.second
                dragging = false
                longPressFired = false
                pressed = true
                alpha = 0.75f
                postDelayed(longPress, 500)
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = event.rawX - downX
                val dy = event.rawY - downY
                if (!dragging && (kotlin.math.abs(dx) > 12f || kotlin.math.abs(dy) > 12f)) {
                    dragging = true
                    removeCallbacks(longPress)
                }
                if (dragging) onMoved?.invoke((startX + dx).toInt(), (startY + dy).toInt())
                return true
            }
            MotionEvent.ACTION_UP -> {
                pressed = false
                removeCallbacks(longPress)
                alpha = if (busy) 0.55f else 1f
                if (dragging) {
                    val current = positionProvider?.invoke() ?: (startX to startY)
                    onDragFinished?.invoke(current.first, current.second)
                } else if (!longPressFired) {
                    onTap?.invoke()
                }
                dragging = false
                return true
            }
            MotionEvent.ACTION_CANCEL -> {
                pressed = false
                removeCallbacks(longPress)
                alpha = if (busy) 0.55f else 1f
                dragging = false
                return true
            }
        }
        return super.onTouchEvent(event)
    }

    private fun lighten(color: Int, factor: Float): Int = Color.rgb(
        (Color.red(color) * factor).toInt().coerceAtMost(255),
        (Color.green(color) * factor).toInt().coerceAtMost(255),
        (Color.blue(color) * factor).toInt().coerceAtMost(255),
    )

    private fun darken(color: Int, factor: Float): Int = Color.rgb(
        (Color.red(color) / factor).toInt(),
        (Color.green(color) / factor).toInt(),
        (Color.blue(color) / factor).toInt(),
    )
}
