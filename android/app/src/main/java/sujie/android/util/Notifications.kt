package sujie.android.util

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import sujie.android.AppContainer
import sujie.android.MainActivity
import sujie.android.R

object Notifications {
    private var nextId = 1000

    fun serviceNotification(context: Context, title: String, text: String): Notification {
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(context, AppContainer.serviceChannel(context))
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(context)
        }
        val content = PendingIntent.getActivity(
            context, 0, Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return builder
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(text)
            .setContentIntent(content)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    /** 结果提示：发成功了给一条，失败了给一条，点开回到主界面。 */
    fun notifyResult(context: Context, title: String, text: String) {
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(context, AppContainer.resultChannel(context))
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(context)
        }
        val content = PendingIntent.getActivity(
            context, 0, Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = builder
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(content)
            .setAutoCancel(true)
            .build()
        context.getSystemService(NotificationManager::class.java)
            ?.notify(nextId++, notification)
    }
}
