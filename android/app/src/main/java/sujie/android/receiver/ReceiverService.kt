package sujie.android.receiver

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import sujie.android.AppContainer
import sujie.android.SujieApp
import sujie.android.util.Gallery
import sujie.android.util.Notifications
import sujie.core.DiscoveryResponder
import sujie.core.ReceiveStore
import sujie.core.ReceiverServer
import java.io.File

/**
 * 接收端常驻服务：在平板上跑 HTTP 服务（TCP 8765）+ 设备发现应答（UDP 8766），
 * 让其他电脑 / 平板把它当成一台普通接收端。
 *
 * 必须前台服务：Android 8 起后台进程随时会被冻结，服务一停端口就断，
 * 桌面端那边会表现为"能扫到但发不过来"。
 */
class ReceiverService : Service() {

    private var server: ReceiverServer? = null
    private var responder: DiscoveryResponder? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> start()
            ACTION_STOP -> {
                stopServer()
                stopSelf()
            }
            else -> start()
        }
        return START_STICKY
    }

    private fun start() {
        val container = SujieApp.container()
        val config = container.receiver
        startForegroundSafely(container)

        stopServer()
        val store = ReceiveStore(
            rootDir = resolveRoot(container),
            subdirByDate = config.subdirByDate,
            prefix = config.filenamePrefix.ifBlank { "shot" },
            onSaved = { file ->
                if (config.saveToGallery) Gallery.publish(this, file)
            },
        )
        val httpServer = try {
            ReceiverServer(
                port = config.port,
                token = config.token,
                store = store,
                maxUploadMb = config.maxUploadMb,
                deviceName = deviceName(),
            ) {
                mapOf("platform" to "android")
            }.start()
        } catch (e: Exception) {
            Notifications.notifyResult(
                this, "接收端启动失败",
                "无法监听端口 ${config.port}：${e.message ?: e.javaClass.simpleName}\n请换一个端口再试。",
            )
            stopSelf()
            return
        }

        // 收到的文件如果要求进系统图库，包一层 store：落盘后顺手 publish
        server = httpServer
        responder = DiscoveryResponder {
            mapOf(
                "app" to sujie.core.Wire.APP_NAME,
                "version" to sujie.core.Wire.VERSION,
                "device" to deviceName(),
                "ips" to sujie.core.localIpv4Addresses(),
                "ip" to (sujie.core.localIpv4Addresses().firstOrNull() ?: "127.0.0.1"),
                "http_port" to config.port,
                "save_dir" to store.targetDir().absolutePath,
                "max_upload_mb" to config.maxUploadMb,
                "count" to httpServer.receivedCount,
            )
        }.also { it.start() }

        running = true
    }

    private fun resolveRoot(container: AppContainer): File {
        val configured = container.receiver.saveDir
        val dir = if (configured.isBlank()) container.receiveRoot else File(configured)
        dir.mkdirs()
        return dir
    }

    private fun startForegroundSafely(container: AppContainer) {
        val config = container.receiver
        val notification = Notifications.serviceNotification(
            this,
            "速截 接收端",
            "端口 ${config.port} · 保存到 ${resolveRoot(container).name}",
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun stopServer() {
        try {
            responder?.stop()
        } catch (_: Exception) {
        }
        responder = null
        try {
            server?.stop()
        } catch (_: Exception) {
        }
        server = null
        running = false
    }

    override fun onDestroy() {
        stopServer()
        super.onDestroy()
    }

    private fun deviceName(): String =
        (Build.MODEL ?: "android").replace(' ', '-')

    companion object {
        const val ACTION_START = "sujie.receiver.START"
        const val ACTION_STOP = "sujie.receiver.STOP"
        private const val NOTIFICATION_ID = 4201

        @Volatile
        var running: Boolean = false
            private set

        fun start(context: Context) {
            val intent = Intent(context, ReceiverService::class.java).apply { action = ACTION_START }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.startService(Intent(context, ReceiverService::class.java).apply { action = ACTION_STOP })
        }

        /** 进程被系统重启后按配置恢复监听，不让"接收端"静默消失。 */
        fun restartIfConfigured() {
            val container = SujieApp.container()
            if (container.receiver.port > 0 && container.client.serveInBackground) {
                runCatching { start(SujieApp.instance) }
            }
        }
    }
}
