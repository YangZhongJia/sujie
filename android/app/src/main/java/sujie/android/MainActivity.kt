package sujie.android

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import sujie.android.ui.SujieColors
import sujie.android.ui.SujieTheme
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import sujie.android.capture.CaptureService
import sujie.android.capture.SujieAccessibilityService
import sujie.android.receiver.ReceiverService
import sujie.android.ball.FloatingBallService
import sujie.android.util.Gallery
import sujie.android.util.Notifications
import sujie.core.DiscoveredDevice
import sujie.core.Discovery
import sujie.core.ReceiverConfig
import sujie.core.ReceiverTarget
import sujie.core.SendResult
import sujie.core.SujieHttp
import sujie.core.TargetJson
import sujie.core.screenshotFileName
import java.io.File
import java.time.LocalDateTime

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(Modifier.fillMaxSize()) {
                    SujieScreen()
                }
            }
        }
    }
}

/** 界面状态与动作。所有网络/IO 都在 IO 线程，UI 只读 StateFlow。 */
class SujieViewModel : ViewModel() {
    private val container = SujieApp.container()

    private val _targets = MutableStateFlow(container.client.toTargets())
    val targets: StateFlow<List<ReceiverTarget>> = _targets.asStateFlow()

    private val _receiver = MutableStateFlow(container.receiver)
    val receiver: StateFlow<ReceiverConfig> = _receiver.asStateFlow()

    private val _status = MutableStateFlow("")
    val status: StateFlow<String> = _status.asStateFlow()

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy.asStateFlow()

    private val _discovered = MutableStateFlow<List<DiscoveredDevice>>(emptyList())
    val discovered: StateFlow<List<DiscoveredDevice>> = _discovered.asStateFlow()

    private val _history = MutableStateFlow(container.outbox.count())
    val outboxCount: StateFlow<Int> = _history.asStateFlow()

    private val _ballOn = MutableStateFlow(FloatingBallService.running)
    val ballOn: StateFlow<Boolean> = _ballOn.asStateFlow()

    @Volatile
    var lastScreenshot: File? = null
        private set

    fun addTarget(raw: String, token: String, onError: (String) -> Unit) {
        val parsed = parseHostPort(raw)
        val target = runCatching { ReceiverTarget.parse(parsed.first, parsed.second, token) }
            .getOrElse { onError(it.message ?: "地址无效"); return }
        if (_targets.value.any { it.host == target.host && it.port == target.port }) {
            onError("这台接收端已经在列表里了")
            return
        }
        val updated = _targets.value + target
        persistTargets(updated)
        _status.value = "已添加 ${target.label}"
    }

    fun addDiscovered(device: DiscoveredDevice, token: String) {
        val target = device.toTarget(token)
        if (_targets.value.any { it.host == target.host && it.port == target.port }) return
        persistTargets(_targets.value + target)
        _status.value = "已添加 ${target.label}"
    }

    fun removeTarget(target: ReceiverTarget) {
        persistTargets(_targets.value - target)
    }

    private fun persistTargets(targets: List<ReceiverTarget>) {
        _targets.value = targets
        container.saveClient(container.client.copy(targets = targets.map { TargetJson.from(it) }))
    }

    fun scan(onDone: (Int) -> Unit) {
        viewModelScopeLaunch {
            _busy.value = true
            _status.value = "正在扫描局域网…"
            val found = withContext(Dispatchers.IO) { Discovery.discover(timeoutMs = 1800) }
            _discovered.value = found
            _busy.value = false
            _status.value = if (found.isEmpty()) "没有发现设备（检查是否同一 WiFi / 网段）" else "发现 ${found.size} 台设备"
            onDone(found.size)
        }
    }

    fun testTargets() {
        val list = _targets.value
        if (list.isEmpty()) {
            _status.value = "还没有配置接收端"
            return
        }
        viewModelScopeLaunch {
            _busy.value = true
            val result = withContext(Dispatchers.IO) { SujieHttp.testAll(list) }
            _busy.value = false
            _status.value = describe(result)
        }
    }

    /** 抓屏 → 存临时 PNG → 发送。返回是否成功启动。 */
    fun captureAndSend(onNeedPermission: () -> Unit, onResult: (String) -> Unit) {
        val list = _targets.value
        if (list.isEmpty()) {
            _status.value = "先添加一台接收端"
            return
        }
        if (!CaptureService.anyChannelReady()) {
            _status.value = "需要授权屏幕抓取"
            onNeedPermission()
            return
        }
        viewModelScopeLaunch {
            _busy.value = true
            _status.value = "正在抓取屏幕…"
            val file = withContext(Dispatchers.IO) {
                runCatching {
                    val bitmap = CaptureService.screenshot()
                    val out = File(container.cacheDir, screenshotFileName(LocalDateTime.now()))
                    CaptureService.saveBitmap(bitmap, out)
                    bitmap.recycle()
                    out
                }.getOrNull()
            }
            if (file == null) {
                _busy.value = false
                _status.value = "抓取失败，请重新授权屏幕抓取"
                onResult("抓取失败")
                return@viewModelScopeLaunch
            }
            lastScreenshot = file
            sendFile(file, keepName = false, list)
            onResult("已发送")
        }
    }

    fun sendFile(file: File, keepName: Boolean, list: List<ReceiverTarget> = _targets.value) {
        if (list.isEmpty()) {
            _status.value = "先添加一台接收端"
            return
        }
        viewModelScopeLaunch {
            _busy.value = true
            _status.value = "正在发送 ${file.name}…"
            val result = withContext(Dispatchers.IO) {
                SujieHttp.sendToAll(list, file.name, file, keepName)
            }
            if (!result.ok) {
                withContext(Dispatchers.IO) {
                    runCatching { container.outbox.add(file, file.name, list.drop(result.succeeded), keepName) }
                }
            }
            _history.value = container.outbox.count()
            _busy.value = false
            _status.value = describe(result)
            Notifications.notifyResult(
                SujieApp.instance,
                if (result.ok) "已发送" else "发送未完全成功",
                describe(result),
            )
        }
    }

    fun retryOutbox() {
        viewModelScopeLaunch {
            _busy.value = true
            val delivered = withContext(Dispatchers.IO) {
                container.outbox.flush { entry, target ->
                    SujieHttp.upload(target, entry.originalName, entry.file, entry.keepName).isOk
                }
            }
            _history.value = container.outbox.count()
            _busy.value = false
            _status.value = if (delivered > 0) "补发成功 $delivered 个" else "暂时还发不出去"
        }
    }

    fun updateReceiver(config: ReceiverConfig, restart: Boolean) {
        container.saveReceiver(config)
        _receiver.value = config
        if (restart) {
            if (ReceiverService.running) {
                ReceiverService.stop(SujieApp.instance)
                ReceiverService.start(SujieApp.instance)
            }
            _status.value = "接收端设置已保存"
        }
    }

    fun startReceiver() {
        ReceiverService.start(SujieApp.instance)
        _status.value = "接收端已启动"
    }

    fun stopReceiver() {
        ReceiverService.stop(SujieApp.instance)
        _status.value = "接收端已停止"
    }

    fun setStatus(text: String) {
        _status.value = text
    }

    fun showBall(onNeedsPermission: () -> Unit) {
        if (!FloatingBallService.canDraw(SujieApp.instance)) {
            onNeedsPermission()
            return
        }
        FloatingBallService.start(SujieApp.instance)
        _ballOn.value = true
        _status.value = "悬浮球已显示，拖到顺手的位置即可"
    }

    fun hideBall() {
        FloatingBallService.stop(SujieApp.instance)
        _ballOn.value = false
        _status.value = "悬浮球已隐藏"
    }

    fun refreshBallState() {
        _ballOn.value = FloatingBallService.running
    }

    private fun describe(result: SendResult): String = result.summary()

    private fun parseHostPort(raw: String): Pair<String, Int> {
        val text = raw.trim()
        val colon = text.lastIndexOf(':')
        if (colon > 0) {
            val port = text.substring(colon + 1).toIntOrNull()
            if (port != null) return text.substring(0, colon) to port
        }
        return text to 8765
    }

    private fun viewModelScopeLaunch(block: suspend () -> Unit) {
        // 必须挂在 ViewModel 的 scope 上：自建 CoroutineScope 会随界面重建泄漏，
        // 且 Activity 销毁后仍会回调 UI 状态。
        viewModelScope.launch { block() }
    }
}


@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SujieScreen(vm: SujieViewModel = viewModel()) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val targets by vm.targets.collectAsStateWithLifecycle()
    val receiver by vm.receiver.collectAsStateWithLifecycle()
    val status by vm.status.collectAsStateWithLifecycle()
    val busy by vm.busy.collectAsStateWithLifecycle()
    val discovered by vm.discovered.collectAsStateWithLifecycle()
    val outboxCount by vm.outboxCount.collectAsStateWithLifecycle()
    val ballOn by vm.ballOn.collectAsStateWithLifecycle()

    val snackbar = remember { SnackbarHostState() }
    var newAddress by remember { mutableStateOf("") }
    var newToken by remember { mutableStateOf("") }

    val projectionManager = remember {
        context.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
    }
    val projectionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val data = result.data
        if (result.resultCode == Activity.RESULT_OK && data != null) {
            CaptureService.start(context, result.resultCode, data)
            vm.setStatus("屏幕抓取已授权")
        } else {
            vm.setStatus("已取消授权：没有授权就无法截图")
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        vm.setStatus(if (granted) "通知权限已授予" else "没有通知权限，后台状态只能进应用查看")
    }

    val overlayLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) {
        vm.refreshBallState()
        if (FloatingBallService.canDraw(context)) {
            vm.showBall { }
            vm.setStatus("悬浮球已显示")
        } else {
            vm.setStatus("没有悬浮窗权限，无法显示悬浮球")
        }
    }

    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        }
        // 首次进入就把球放出来：用户装这个应用就是为了点球截图
        vm.refreshBallState()
        if (!FloatingBallService.running && FloatingBallService.canDraw(context)) {
            vm.showBall { }
        }
    }

    val requestBall: () -> Unit = {
        overlayLauncher.launch(
            Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:${context.packageName}"),
            )
        )
    }

    SujieTheme {
        Scaffold(
            containerColor = SujieColors.canvas,
            topBar = {
                TopAppBar(
                    title = { Text("速截", style = MaterialTheme.typography.titleLarge) },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = SujieColors.canvas,
                        titleContentColor = SujieColors.text,
                    ),
                )
            },
            snackbarHost = { SnackbarHost(snackbar) },
        ) { padding ->
            Column(
                Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                // ---- 悬浮球：主操作入口，和桌面端一样是"一颗球"
                SectionCard {
                    SectionTitle("桌面悬浮球")
                    Hint(
                        if (ballOn) "在屏幕上：单击截图并发送，长按弹出菜单，拖动换位置"
                        else "开启后在任何界面都能一键截图发送",
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        PrimaryButton(
                            text = if (ballOn) "悬浮球已开启" else "显示悬浮球",
                            enabled = !ballOn,
                            onClick = { vm.showBall(requestBall) },
                        )
                        SecondaryButton("隐藏", enabled = ballOn, onClick = { vm.hideBall() })
                    }
                }

                // ---- 截图通道：无障碍优先（静默），MediaProjection 兜底（每次弹框）
                SectionCard {
                    SectionTitle("截图权限")
                    val accessible = SujieAccessibilityService.available
                    Hint(
                        when {
                            accessible -> "已启用无障碍截图：点悬浮球直接截图，不再弹任何系统框"
                            CaptureService.isReady -> "当前走屏幕录制授权：每次截图都会弹系统确认框"
                            else -> "还没启用截图权限，点悬浮球会要求先授权"
                        },
                    )
                    if (!accessible) {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            PrimaryButton("开启静默截图", enabled = true) {
                                // 无障碍服务只能由用户在系统设置里开启，应用无法代劳
                                context.startActivity(
                                    Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
                                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                )
                            }
                            SecondaryButton("用屏幕录制授权", enabled = !busy) {
                                projectionLauncher.launch(projectionManager.createScreenCaptureIntent())
                            }
                        }
                        Hint("无障碍截图只需在系统设置里开启一次；屏幕录制授权每次截图都要点「立即开始」。")
                    }
                }

                // ---- 手动截图（球不方便时用；长按球也能进同样入口）
                if (CaptureService.anyChannelReady()) {
                    SectionCard {
                        SectionTitle("截图并发送")
                        Hint("和点悬浮球一样：抓一帧当前屏幕，发给所有接收端")
                        PrimaryButton(
                            text = "截图并发送",
                            enabled = !busy,
                            onClick = {
                                vm.captureAndSend(
                                    onNeedPermission = {
                                        projectionLauncher.launch(projectionManager.createScreenCaptureIntent())
                                    },
                                    onResult = { msg -> scope.launch { snackbar.showSnackbar(msg) } },
                                )
                            },
                        )
                    }
                }

                // ---- 接收端列表
                SectionCard {
                    SectionTitle("接收端（${targets.size}）")
                    if (targets.isEmpty()) {
                        Hint("还没有接收端。扫描局域网，或手动填 IP。")
                    }
                    targets.forEach { target ->
                        Row(
                            Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(target.label, style = MaterialTheme.typography.bodyLarge)
                                Text(
                                    "${target.host}:${target.port}",
                                    style = MaterialTheme.typography.bodySmall,
                                )
                            }
                            SecondaryButton("移除", enabled = true) { vm.removeTarget(target) }
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        OutlinedTextField(
                            value = newAddress,
                            onValueChange = { newAddress = it },
                            label = { Text("IP 或 IP:端口") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = newToken,
                            onValueChange = { newToken = it },
                            label = { Text("密钥") },
                            singleLine = true,
                            modifier = Modifier.width(130.dp),
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        PrimaryButton(
                            text = "添加",
                            enabled = newAddress.isNotBlank() && !busy,
                            onClick = {
                                vm.addTarget(newAddress, newToken) { err ->
                                    scope.launch { snackbar.showSnackbar(err) }
                                }
                                newAddress = ""
                            },
                        )
                        SecondaryButton("扫描局域网", enabled = !busy) { vm.scan { } }
                        SecondaryButton(
                            "测试连接",
                            enabled = targets.isNotEmpty() && !busy,
                        ) { vm.testTargets() }
                    }
                    if (discovered.isNotEmpty()) {
                        Divider(color = SujieColors.line)
                        Text("扫描到", style = MaterialTheme.typography.labelMedium)
                        discovered.forEach { device ->
                            Row(
                                Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Column(Modifier.weight(1f)) {
                                    Text(device.device, style = MaterialTheme.typography.bodyLarge)
                                    Text(
                                        "${device.ip}:${device.httpPort} · v${device.version}",
                                        style = MaterialTheme.typography.bodySmall,
                                    )
                                }
                                SecondaryButton("添加", enabled = true) {
                                    vm.addDiscovered(device, newToken)
                                }
                            }
                        }
                    }
                    if (outboxCount > 0) {
                        Divider(color = SujieColors.line)
                        Row(
                            Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text("待发队列：$outboxCount 个", style = MaterialTheme.typography.bodyMedium)
                            SecondaryButton("立即补发", enabled = !busy) { vm.retryOutbox() }
                        }
                    }
                }

                // ---- 接收端（本机）
                SectionCard {
                    SectionTitle("作为接收端")
                    Hint(
                        if (ReceiverService.running) "运行中：端口 ${receiver.port}，其他电脑可以发到这里"
                        else "启动后本机也能接收其他电脑的截图",
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        PrimaryButton("启动接收", enabled = true) { vm.startReceiver() }
                        SecondaryButton("停止", enabled = true) { vm.stopReceiver() }
                    }
                    ToggleRow(
                        "按日期分文件夹",
                        receiver.subdirByDate,
                    ) { vm.updateReceiver(receiver.copy(subdirByDate = it), restart = true) }
                    ToggleRow(
                        "同时存入系统图库",
                        receiver.saveToGallery,
                    ) { vm.updateReceiver(receiver.copy(saveToGallery = it), restart = false) }
                    Hint("保存目录：${receiver.saveDir.ifBlank { "应用图片目录/速截" }}")
                }

                if (status.isNotBlank()) {
                    Text(
                        status,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(bottom = 24.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun SectionCard(content: @Composable ColumnScope.() -> Unit) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = SujieColors.surface,
        border = BorderStroke(1.dp, SujieColors.line),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            content = content,
        )
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleMedium)
}

@Composable
private fun Hint(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun PrimaryButton(text: String, enabled: Boolean = true, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(8.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = SujieColors.accent,
            contentColor = Color.White,
            disabledContainerColor = SujieColors.canvas,
            disabledContentColor = Color(0xFFA1A1A6),
        ),
        modifier = Modifier.height(38.dp),
    ) { Text(text, fontWeight = FontWeight.SemiBold) }
}

@Composable
private fun SecondaryButton(text: String, enabled: Boolean = true, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(8.dp),
        border = BorderStroke(1.dp, SujieColors.line),
        colors = ButtonDefaults.outlinedButtonColors(
            containerColor = SujieColors.surface,
            contentColor = SujieColors.text,
            disabledContentColor = Color(0xFFA1A1A6),
        ),
        modifier = Modifier.height(38.dp),
    ) { Text(text) }
}

@Composable
private fun ToggleRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Switch(
            checked = checked,
            onCheckedChange = onChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = Color.White,
                checkedTrackColor = SujieColors.accent,
                uncheckedThumbColor = Color.White,
                uncheckedTrackColor = Color(0xFFC7C7CC),
                uncheckedBorderColor = Color(0xFFC7C7CC),
            ),
        )
    }
}
