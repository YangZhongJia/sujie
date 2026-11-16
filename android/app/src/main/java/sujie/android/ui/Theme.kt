package sujie.android.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * 与桌面端 `sujie/theme.py` 同一套配色，保证两个平台的界面看起来是同一个产品。
 *
 * canvas #F5F5F7 / surface #FFFFFF / text #1D1D1F / secondary #6E6E73
 * line #D2D2D7 / accent #0066CC
 */
object SujieColors {
    val canvas = Color(0xFFF5F5F7)
    val surface = Color(0xFFFFFFFF)
    val text = Color(0xFF1D1D1F)
    val secondary = Color(0xFF6E6E73)
    val line = Color(0xFFD2D2D7)
    val accent = Color(0xFF0066CC)
    val accentSoft = Color(0xFFE8F2FF)
    val destructive = Color(0xFFD70015)
    val ball = Color(0xFFE94F37)
}

private val scheme = lightColorScheme(
    primary = SujieColors.accent,
    onPrimary = Color.White,
    primaryContainer = SujieColors.accentSoft,
    onPrimaryContainer = SujieColors.text,
    background = SujieColors.canvas,
    onBackground = SujieColors.text,
    surface = SujieColors.surface,
    onSurface = SujieColors.text,
    surfaceVariant = SujieColors.surface,
    onSurfaceVariant = SujieColors.secondary,
    outline = SujieColors.line,
    outlineVariant = SujieColors.line,
    error = SujieColors.destructive,
)

private val typography = Typography(
    titleLarge = TextStyle(fontSize = 21.sp, fontWeight = FontWeight.SemiBold, color = SujieColors.text),
    titleMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = SujieColors.text),
    bodyLarge = TextStyle(fontSize = 14.sp, color = SujieColors.text),
    bodyMedium = TextStyle(fontSize = 13.sp, color = SujieColors.text),
    bodySmall = TextStyle(fontSize = 12.sp, color = SujieColors.secondary),
    labelMedium = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Medium, color = SujieColors.secondary),
)

/** 桌面端只有浅色主题，这里固定浅色，保证两端观感一致。 */
@Composable
fun SujieTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = scheme, typography = typography, content = content)
}
