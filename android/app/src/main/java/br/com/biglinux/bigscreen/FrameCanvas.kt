package br.com.biglinux.bigscreen

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import android.os.SystemClock

/**
 * The picture the computer sends: rectangles are decoded into [work] as they
 * arrive (session thread); PRESENT copies the changed area into [front],
 * which the view draws (UI thread) - a half-received frame is never shown.
 * Buffers are reused while the size stays the same.
 */
class FrameCanvas {
    private val lock = Any()
    private var work: Bitmap? = null
    private var workCanvas: Canvas? = null
    private var front: Bitmap? = null
    private var frontCanvas: Canvas? = null
    private val dirty = Rect()
    private val fill = Paint()
    private var pixels = IntArray(0)
    private var decodeStart = 0L
    @Volatile var width = 0
        private set
    @Volatile var height = 0
        private set
    @Volatile var hasFrame = false
        private set

    /** Session thread. */
    fun apply(payload: ByteArray) {
        val header = Bsdp.rectHeader(payload)
        if (decodeStart == 0L) decodeStart = SystemClock.elapsedRealtime()
        ensure(header.canvasW, header.canvasH)
        val canvas = workCanvas ?: return
        val bitmap = work ?: return
        when (header.format) {
            Bsdp.FMT_FILL -> {
                fill.color = Bsdp.fillColor(payload, Bsdp.RECT_HEADER)
                canvas.drawRect(header.x.toFloat(), header.y.toFloat(), (header.x + header.w).toFloat(),
                    (header.y + header.h).toFloat(), fill)
            }
            Bsdp.FMT_RGB_ZLIB -> {
                val count = header.w * header.h
                if (pixels.size < count) pixels = IntArray(count)
                Bsdp.inflateRgb(payload, Bsdp.RECT_HEADER, header.w, header.h, pixels)
                bitmap.setPixels(pixels, 0, header.w, header.x, header.y, header.w, header.h)
            }
            Bsdp.FMT_JPEG, Bsdp.FMT_PNG, Bsdp.FMT_WEBP -> {
                val options = BitmapFactory.Options()
                options.inPreferredConfig = Bitmap.Config.ARGB_8888
                val part = BitmapFactory.decodeByteArray(payload, Bsdp.RECT_HEADER, payload.size - Bsdp.RECT_HEADER,
                    options) ?: throw Bsdp.ProtocolException("undecodable picture")
                canvas.drawBitmap(part, header.x.toFloat(), header.y.toFloat(), null)
                part.recycle()
            }
            else -> throw Bsdp.ProtocolException("unknown picture format ${header.format}")
        }
        dirty.union(header.x, header.y, header.x + header.w, header.y + header.h)
    }

    /** Session thread: show what was decoded since the last PRESENT. Returns the decoding time (ms). */
    fun present(): Int {
        val took = if (decodeStart == 0L) 0 else (SystemClock.elapsedRealtime() - decodeStart).toInt()
        decodeStart = 0L
        val source = work ?: return took
        synchronized(lock) {
            val target = frontCanvas
            if (target != null && !dirty.isEmpty) target.drawBitmap(source, dirty, dirty, null)
            hasFrame = true
        }
        dirty.setEmpty()
        return took
    }

    /** UI thread: draw the last presented frame into [dest]. */
    fun draw(canvas: Canvas, dest: Rect, paint: Paint): Boolean {
        synchronized(lock) {
            val bitmap = front ?: return false
            if (!hasFrame) return false
            canvas.drawBitmap(bitmap, null, dest, paint)
            return true
        }
    }

    fun clear() {
        synchronized(lock) {
            hasFrame = false
        }
    }

    private fun ensure(w: Int, h: Int) {
        if (w == width && h == height && work != null) return
        synchronized(lock) {
            work?.recycle()
            front?.recycle()
            val newWork = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
            val newFront = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
            work = newWork
            workCanvas = Canvas(newWork)
            front = newFront
            frontCanvas = Canvas(newFront)
            width = w
            height = h
            hasFrame = false
        }
        dirty.setEmpty()
    }

    fun release() {
        synchronized(lock) {
            work?.recycle()
            front?.recycle()
            work = null
            front = null
            workCanvas = null
            frontCanvas = null
            width = 0
            height = 0
            hasFrame = false
        }
    }
}
