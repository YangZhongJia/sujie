package sujie.android.util

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.widget.Toast

/** Toast 封装：悬浮球场景经常在非主线程收尾，统一在这里切回主线程。 */
object Toasts {
    private val main = Handler(Looper.getMainLooper())

    fun show(context: Context, text: String) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            Toast.makeText(context.applicationContext, text, Toast.LENGTH_SHORT).show()
        } else {
            showOnMain(context, text)
        }
    }

    fun showOnMain(context: Context, text: String) {
        main.post { Toast.makeText(context.applicationContext, text, Toast.LENGTH_SHORT).show() }
    }
}
