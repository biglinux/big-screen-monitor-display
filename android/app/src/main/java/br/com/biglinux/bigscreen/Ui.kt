package br.com.biglinux.bigscreen

import android.app.AlertDialog
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.os.Build
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView

/** Small widget kit: Material-like look with framework views only (Android 5.0+, light and dark). */
object Ui {
    fun dp(context: Context, value: Int): Int = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP,
        value.toFloat(), context.resources.displayMetrics).toInt()

    fun color(context: Context, id: Int): Int =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) context.getColor(id)
        else @Suppress("DEPRECATION") context.resources.getColor(id)

    fun text(context: Context, value: CharSequence, size: Float = 15f, colorId: Int = R.color.text,
             bold: Boolean = false): TextView = TextView(context).apply {
        text = value
        setTextSize(TypedValue.COMPLEX_UNIT_SP, size)
        setTextColor(color(context, colorId))
        if (bold) typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        setLineSpacing(0f, 1.15f)
    }

    fun title(context: Context, value: CharSequence) = text(context, value, 26f, R.color.text, true)
    fun heading(context: Context, value: CharSequence) = text(context, value, 13f, R.color.accent, true).apply {
        setAllCaps(true)
        letterSpacing = 0.06f
        setPadding(dp(context, 4), dp(context, 20), 0, dp(context, 8))
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) isAccessibilityHeading = true
    }

    fun body(context: Context, value: CharSequence) = text(context, value, 15f, R.color.text_dim)

    fun rounded(context: Context, colorId: Int, radiusDp: Int = 18, strokeId: Int = 0): GradientDrawable =
        GradientDrawable().apply {
            cornerRadius = dp(context, radiusDp).toFloat()
            setColor(color(context, colorId))
            if (strokeId != 0) setStroke(dp(context, 1), color(context, strokeId))
        }

    fun clickable(context: Context, view: View, colorId: Int, radiusDp: Int = 18, strokeId: Int = 0) {
        val shape = rounded(context, colorId, radiusDp, strokeId)
        view.background = RippleDrawable(ColorStateList.valueOf(color(context, R.color.ripple)), shape,
            rounded(context, R.color.text, radiusDp))
        view.isClickable = true
        view.isFocusable = true
    }

    fun button(context: Context, label: CharSequence, primary: Boolean = true, onClick: () -> Unit): Button =
        Button(context).apply {
            text = label
            setAllCaps(false)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            setTextColor(color(context, if (primary) R.color.on_accent else R.color.text))
            minHeight = dp(context, 52)
            stateListAnimator = null
            clickable(context, this, if (primary) R.color.accent else R.color.card, 26,
                if (primary) 0 else R.color.outline)
            setPadding(dp(context, 24), 0, dp(context, 24), 0)
            setOnClickListener { onClick() }
        }

    fun column(context: Context, paddingDp: Int = 0): LinearLayout = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        val p = dp(context, paddingDp)
        setPadding(p, p, p, p)
    }

    fun card(context: Context): LinearLayout = column(context, 16).apply {
        background = rounded(context, R.color.card, 22)
    }

    /** A tappable card: icon, title, subtitle. */
    fun actionCard(context: Context, iconId: Int, title: CharSequence, subtitle: CharSequence,
                   onClick: () -> Unit): LinearLayout = LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        val p = dp(context, 16)
        setPadding(p, p, p, p)
        clickable(context, this, R.color.card, 22)
        contentDescription = "$title. $subtitle"
        addView(ImageView(context).apply {
            setImageResource(iconId)
            setColorFilter(color(context, R.color.accent))
            background = rounded(context, R.color.accent_soft, 16)
            val q = dp(context, 10)
            setPadding(q, q, q, q)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LinearLayout.LayoutParams(dp(context, 48), dp(context, 48)))
        addView(column(context).apply {
            setPadding(dp(context, 16), 0, 0, 0)
            addView(text(context, title, 17f, R.color.text, true))
            addView(body(context, subtitle).apply { textSize = 14f })
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        setOnClickListener { onClick() }
    }

    fun row(context: Context, title: CharSequence, subtitle: CharSequence?, onClick: (() -> Unit)?): LinearLayout =
        column(context).apply {
            val p = dp(context, 14)
            setPadding(dp(context, 16), p, dp(context, 16), p)
            addView(text(context, title, 16f).apply { ellipsize = TextUtils.TruncateAt.END })
            if (!subtitle.isNullOrEmpty()) addView(body(context, subtitle).apply { textSize = 14f })
            if (onClick != null) {
                clickable(context, this, R.color.card, 14)
                setOnClickListener { onClick() }
            }
            minimumHeight = dp(context, 56)
        }

    fun switchRow(context: Context, title: CharSequence, subtitle: CharSequence?, checked: Boolean,
                  onChange: (Boolean) -> Unit): LinearLayout = LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        val p = dp(context, 12)
        setPadding(dp(context, 16), p, dp(context, 12), p)
        minimumHeight = dp(context, 56)
        val toggle = Switch(context).apply {
            isChecked = checked
            contentDescription = title
            setOnCheckedChangeListener { _, value -> onChange(value) }
        }
        addView(column(context).apply {
            addView(text(context, title, 16f))
            if (!subtitle.isNullOrEmpty()) addView(body(context, subtitle).apply { textSize = 14f })
        }, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        addView(toggle)
        clickable(context, this, R.color.card, 14)
        setOnClickListener { toggle.toggle() }
    }

    /** Row opening a single-choice dialog; ``onPick`` gets the chosen value. */
    fun choiceRow(context: Context, title: CharSequence, values: List<String>, labels: List<String>,
                  current: String, onPick: (String) -> Unit): LinearLayout {
        var selected = current
        fun label() = labels.getOrNull(values.indexOf(selected)) ?: labels.first()
        val view = Ui.row(context, title, label(), null)
        clickable(context, view, R.color.card, 14)
        view.setOnClickListener {
            AlertDialog.Builder(context)
                .setTitle(title)
                .setSingleChoiceItems(labels.toTypedArray(), values.indexOf(selected).coerceAtLeast(0)) { dialog, which ->
                    selected = values[which]
                    (view.getChildAt(1) as? TextView)?.text = label()
                    onPick(selected)
                    dialog.dismiss()
                }
                .setNegativeButton(android.R.string.cancel, null)
                .show()
        }
        return view
    }

    fun divider(context: Context): View = View(context).apply {
        setBackgroundColor(color(context, R.color.outline))
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 1)
    }

    fun scroll(context: Context, content: View, maxWidthDp: Int = 640): ScrollView = ScrollView(context).apply {
        isFillViewport = true
        setBackgroundColor(color(context, R.color.background))
        addView(FrameLayout(context).apply {
            addView(content, FrameLayout.LayoutParams(
                minOf(dp(context, maxWidthDp), context.resources.displayMetrics.widthPixels),
                ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER_HORIZONTAL))
        })
    }

    fun spacer(context: Context, heightDp: Int): View = View(context).apply {
        layoutParams = LinearLayout.LayoutParams(1, dp(context, heightDp))
    }

    fun margins(view: View, context: Context, top: Int = 0, bottom: Int = 0): View {
        val params = (view.layoutParams as? LinearLayout.LayoutParams) ?: LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        params.topMargin = dp(context, top)
        params.bottomMargin = dp(context, bottom)
        view.layoutParams = params
        return view
    }
}
