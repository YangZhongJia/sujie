package sujie.android.capture

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import sujie.android.util.Toasts

/**
 * 屏幕抓取授权中转站。
 *
 * MediaProjection 的授权弹窗只能由 Activity 发起，而悬浮球是 Service。
 * 关键点：这个 Activity 必须待在**自己的任务栈**里（manifest 里 taskAffinity=""），
 * 否则拉起它会把 MainActivity 一起带到前台——用户点球截图，结果整个应用弹出来，
 * 这正是「点一下球却跳进应用」的原因。
 *
 * 授权完成 → 交给 CaptureService → 立刻 finishAndRemoveTask()，用户回到原来的界面。
 */
class ProjectionRequestActivity : Activity() {

    private val requestCode = 0x5A11
    private var captureAfterGrant = false
    private var launched = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        captureAfterGrant = intent.getBooleanExtra(EXTRA_CAPTURE, false)
        if (launched) {
            finishAndRemoveTask()
            return
        }
        launched = true
        val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        startActivityForResult(manager.createScreenCaptureIntent(), requestCode)
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != this.requestCode) {
            finishAndRemoveTask()
            return
        }
        if (resultCode == RESULT_OK && data != null) {
            CaptureService.start(this, resultCode, data)
            if (captureAfterGrant) {
                // 用户点悬浮球的意图就是"现在截图"：授权后立刻补一张
                Thread {
                    Thread.sleep(GRANT_SETTLE_MS)
                    val message = CaptureAndSend.captureAndSend(applicationContext)
                    Toasts.showOnMain(applicationContext, message)
                }.start()
            }
        } else {
            Toasts.showOnMain(applicationContext, "已取消授权：没有授权无法截图")
        }
        finishAndRemoveTask()
    }

    override fun finish() {
        super.finish()
        // 不要动画：这个 Activity 是纯中转，闪现一下反而突兀
        overridePendingTransition(0, 0)
    }

    companion object {
        private const val EXTRA_CAPTURE = "capture_after_grant"
        private const val GRANT_SETTLE_MS = 500L

        fun start(context: Context, captureAfterGrant: Boolean) {
            val intent = Intent(context, ProjectionRequestActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION)
                .putExtra(EXTRA_CAPTURE, captureAfterGrant)
            context.startActivity(intent)
        }
    }
}
