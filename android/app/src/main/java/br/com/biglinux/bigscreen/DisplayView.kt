package br.com.biglinux.bigscreen

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View

/**
 * Shows the computer's frame scaled to fit (aspect kept, centred, filtered)
 * and turns touches into frame coordinates. One finger only: the theme's
 * touch interface on the computer recognises taps, holds and swipes.
 * Two fingers open the app's own menu instead (nothing is sent).
 */
class DisplayView(context: Context) : View(context) {
    interface Listener {
        fun onTouch(kind: Int, x: Int, y: Int)
        fun onViewSize(w: Int, h: Int)
        fun onAppMenu()
        fun onAnyTouch()
    }

    var listener: Listener? = null
    var canvas = FrameCanvas()          // the activity hands its own in
    var touchEnabled = true
    var shiftX = 0
    var shiftY = 0
    private val dest = Rect()
    private val paint = Paint(Paint.FILTER_BITMAP_FLAG or Paint.ANTI_ALIAS_FLAG)
    private var tracking = false
    private var lastMove = 0L
    private var multi = false

    init {
        setBackgroundColor(Color.BLACK)
        isFocusable = true
        contentDescription = context.getString(R.string.display_description)
    }

    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        if (w > 0 && h > 0) listener?.onViewSize(w, h)
    }

    private fun layoutDest(): Boolean {
        val cw = canvas.width
        val ch = canvas.height
        if (cw <= 0 || ch <= 0 || width <= 0 || height <= 0) return false
        val scale = minOf(width.toFloat() / cw, height.toFloat() / ch)
        val w = (cw * scale).toInt()
        val h = (ch * scale).toInt()
        val left = (width - w) / 2 + shiftX
        val top = (height - h) / 2 + shiftY
        dest.set(left, top, left + w, top + h)
        return true
    }

    override fun onDraw(c: Canvas) {
        super.onDraw(c)
        if (layoutDest()) canvas.draw(c, dest, paint)
    }

    @SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(event: MotionEvent): Boolean {
        listener?.onAnyTouch()
        when (event.actionMasked) {
            MotionEvent.ACTION_POINTER_DOWN -> {
                if (tracking) send(Bsdp.TOUCH_CANCEL, event)
                tracking = false
                multi = true
                return true
            }
            MotionEvent.ACTION_DOWN -> {
                multi = false
                if (!touchEnabled || !layoutDest()) return true
                tracking = true
                send(Bsdp.TOUCH_DOWN, event)
            }
            MotionEvent.ACTION_MOVE -> if (tracking) {
                val now = SystemClock.uptimeMillis()
                if (now - lastMove >= 16) {
                    lastMove = now
                    send(Bsdp.TOUCH_MOVE, event)
                }
            }
            MotionEvent.ACTION_UP -> {
                if (tracking) send(Bsdp.TOUCH_UP, event)
                tracking = false
                if (multi) listener?.onAppMenu()
                multi = false
            }
            MotionEvent.ACTION_CANCEL -> {
                if (tracking) send(Bsdp.TOUCH_CANCEL, event)
                tracking = false
                multi = false
            }
        }
        return true
    }

    private fun send(kind: Int, event: MotionEvent) {
        if (dest.width() <= 0 || dest.height() <= 0) return
        val x = ((event.getX(0) - dest.left) * canvas.width / dest.width()).toInt().coerceIn(0, canvas.width - 1)
        val y = ((event.getY(0) - dest.top) * canvas.height / dest.height()).toInt().coerceIn(0, canvas.height - 1)
        listener?.onTouch(kind, x, y)
    }
}
