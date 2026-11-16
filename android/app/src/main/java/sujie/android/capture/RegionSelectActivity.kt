package sujie.android.capture

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.sp
import sujie.android.util.Toasts
import java.io.File

/**
 * 手动框选区域：把整屏截图铺满屏幕，手指拖出矩形，松手裁切返回。
 *
 * 用透明 Activity 而不是系统悬浮窗，是为了不额外申请「显示在其他应用上层」权限——
 * 平板用户几乎不会给这个权限，一旦拒绝功能就废了。
 */
class RegionSelectActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val path = intent.getStringExtra(EXTRA_SOURCE)
        val bitmap = path?.let { runCatching { BitmapFactory.decodeFile(it) }.getOrNull() }
        if (bitmap == null) {
            setResult(RESULT_CANCELED)
            finish()
            return
        }
        val image = bitmap.asImageBitmap()

        setContent {
            MaterialTheme {
                var container by remember { mutableStateOf(IntSize.Zero) }
                var start by remember { mutableStateOf<Offset?>(null) }
                var end by remember { mutableStateOf<Offset?>(null) }

                Box(
                    Modifier
                        .fillMaxSize()
                        .background(Color.Black)
                        .onSizeChanged { container = it }
                        .pointerInput(Unit) {
                            detectDragGestures(
                                onDragStart = { start = it; end = it },
                                onDragEnd = {
                                    val s = start
                                    val e = end
                                    if (s != null && e != null) {
                                        finishWithCrop(bitmap, s, e, container)
                                    } else {
                                        setResult(RESULT_CANCELED)
                                        finish()
                                    }
                                },
                                onDragCancel = {
                                    setResult(RESULT_CANCELED)
                                    finish()
                                },
                            ) { change, _ -> end = change.position }
                        },
                ) {
                    Canvas(Modifier.fillMaxSize()) {
                        drawImage(
                            image,
                            dstOffset = IntOffset.Zero,
                            dstSize = IntSize(size.width.toInt(), size.height.toInt()),
                        )
                        val s = start
                        val e = end
                        if (s != null && e != null) {
                            val rect = Rect(
                                minOf(s.x, e.x), minOf(s.y, e.y),
                                maxOf(s.x, e.x), maxOf(s.y, e.y),
                            )
                            // 选区外压暗，选区本身透出原图
                            drawRect(Color.Black.copy(alpha = 0.55f), size = size)
                            drawImage(
                                image,
                                srcOffset = IntOffset(
                                    (rect.left / size.width * image.width).toInt(),
                                    (rect.top / size.height * image.height).toInt(),
                                ),
                                srcSize = IntSize(
                                    (rect.width / size.width * image.width).toInt().coerceAtLeast(1),
                                    (rect.height / size.height * image.height).toInt().coerceAtLeast(1),
                                ),
                                dstOffset = IntOffset(rect.left.toInt(), rect.top.toInt()),
                                dstSize = IntSize(rect.width.toInt().coerceAtLeast(1), rect.height.toInt().coerceAtLeast(1)),
                            )
                            drawRect(
                                Color(0xFFE94F37),
                                topLeft = Offset(rect.left, rect.top),
                                size = androidx.compose.ui.geometry.Size(rect.width, rect.height),
                                style = androidx.compose.ui.graphics.drawscope.Stroke(width = 3f),
                            )
                        }
                    }
                    Text(
                        "拖动框选要发送的区域，松手完成",
                        color = Color.White,
                        fontSize = 15.sp,
                        modifier = Modifier.fillMaxSize().let { it },
                    )
                }
            }
        }
    }

    private fun finishWithCrop(bitmap: Bitmap, start: Offset, end: Offset, container: IntSize) {
        if (container.width == 0 || container.height == 0) {
            setResult(RESULT_CANCELED)
            finish()
            return
        }
        val scaleX = bitmap.width.toFloat() / container.width
        val scaleY = bitmap.height.toFloat() / container.height
        val left = (minOf(start.x, end.x) * scaleX).toInt().coerceIn(0, bitmap.width - 1)
        val top = (minOf(start.y, end.y) * scaleY).toInt().coerceIn(0, bitmap.height - 1)
        val right = (maxOf(start.x, end.x) * scaleX).toInt().coerceIn(left + 1, bitmap.width)
        val bottom = (maxOf(start.y, end.y) * scaleY).toInt().coerceIn(top + 1, bitmap.height)
        if (right - left < 8 || bottom - top < 8) {
            // 误触：给个最小尺寸，避免产出 1×1 的废图
            setResult(RESULT_CANCELED)
            finish()
            return
        }
        val cropped = Bitmap.createBitmap(bitmap, left, top, right - left, bottom - top)
        val out = File(cacheDir, "region-${System.currentTimeMillis()}.png")
        CaptureService.saveBitmap(cropped, out)
        cropped.recycle()
        setResult(RESULT_OK, Intent().putExtra(EXTRA_OUTPUT, out.absolutePath))
        finish()

        if (intent.getBooleanExtra(EXTRA_SEND, false)) {
            // 悬浮球框选：选完直接发，不再要求用户回主界面点一次
            Thread {
                val message = CaptureAndSend.sendFile(applicationContext, out, keepName = false)
                Toasts.showOnMain(applicationContext, message)
            }.start()
        }
    }

    companion object {
        const val EXTRA_SOURCE = "source"
        const val EXTRA_OUTPUT = "output"
        const val EXTRA_SEND = "send"

        fun intent(context: Context, source: File): Intent =
            Intent(context, RegionSelectActivity::class.java)
                .putExtra(EXTRA_SOURCE, source.absolutePath)
    }
}
