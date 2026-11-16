package sujie.android

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import sujie.android.capture.CaptureService
import sujie.android.receiver.ReceiverService
import sujie.core.ClientConfig
import sujie.core.ConfigStore
import sujie.core.Outbox
import sujie.core.ReceiverConfig
import java.io.File

/**
 * 全局容器：配置、待发队列、数据目录。
 *
 * 桌面端把配置放在 %APPDATA%\速截，这里放在应用私有目录，
 * 文件格式与桌面端 client.json / receiver.json 完全一致，可以互相拷贝排查问题。
 */
class AppContainer(private val context: Context) {

    val configDir: File = File(context.filesDir, "config").apply { mkdirs() }
    val cacheDir: File = File(context.cacheDir, "sujie").apply { mkdirs() }
    val receiveRoot: File = File(
        context.getExternalFilesDir(android.os.Environment.DIRECTORY_PICTURES) ?: context.filesDir,
        "速截",
    )
    val outboxDir: File = File(context.filesDir, "outbox").apply { mkdirs() }

    val store = ConfigStore(configDir)
    val outbox = Outbox(outboxDir)

    @Volatile
    var client: ClientConfig = store.loadClient()

    @Volatile
    var receiver: ReceiverConfig = store.loadReceiver()

    fun saveClient(config: ClientConfig = client) {
        client = config
        store.saveClient(config)
    }

    fun saveReceiver(config: ReceiverConfig = receiver) {
        receiver = config
        store.saveReceiver(config)
    }

    companion object {
        const val CHANNEL_SERVICE = "sujie_service"
        const val CHANNEL_RESULT = "sujie_result"

        fun createChannels(context: Context) {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
            val manager = context.getSystemService(NotificationManager::class.java) ?: return
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_SERVICE, "后台服务", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "截屏授权与接收端常驻"
                    setShowBadge(false)
                }
            )
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_RESULT, "发送结果", NotificationManager.IMPORTANCE_DEFAULT)
            )
        }

        fun serviceChannel(context: Context) =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) CHANNEL_SERVICE else null

        fun resultChannel(context: Context) =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) CHANNEL_RESULT else null
    }
}

class SujieApp : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        container = AppContainer(this)
        AppContainer.createChannels(this)
    }

    override fun onTerminate() {
        super.onTerminate()
    }

    companion object {
        lateinit var instance: SujieApp
            private set

        fun container(): AppContainer = instance.container

        /** 进程重启后 Service 仍在跑（START_STICKY），需要重新拉起监听。 */
        fun restartServicesIfNeeded() {
            ReceiverService.restartIfConfigured()
            CaptureService.stopSilently()
        }
    }
}
