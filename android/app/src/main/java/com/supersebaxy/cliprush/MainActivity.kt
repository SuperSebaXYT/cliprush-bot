package com.supersebaxy.cliprush

import android.annotation.SuppressLint
import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.animation.ObjectAnimator
import android.animation.PropertyValuesHolder
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebResourceRequest
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView

class MainActivity : Activity() {
    private lateinit var webView: WebView
    private lateinit var splashView: View
    private val handler = Handler(Looper.getMainLooper())
    private val appUrl = "https://cliprush-bot.streamlit.app/"
    private var splashStartedAt = 0L
    private var splashHidden = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val root = FrameLayout(this)
        root.setBackgroundColor(Color.rgb(8, 7, 17))

        webView = WebView(this).apply {
            setBackgroundColor(Color.rgb(8, 7, 17))
            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.databaseEnabled = true
            settings.loadsImagesAutomatically = true
            settings.setSupportZoom(false)
            webChromeClient = WebChromeClient()
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    // Keep HTTPS redirects and authentication flows inside the WebView.
                    // Opening them externally can interrupt Streamlit's startup.
                    return request.url.scheme != "https" && request.url.scheme != "http"
                }

                override fun onPageCommitVisible(view: WebView, url: String) {
                    super.onPageCommitVisible(view, url)
                    handler.postDelayed({ hideSplash() }, 700)
                }

                override fun onPageFinished(view: WebView, url: String) {
                    super.onPageFinished(view, url)
                    handler.postDelayed({ hideSplash() }, 1200)
                }
            }
        }
        root.addView(webView, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT
        ))

        splashView = createSplash()
        root.addView(splashView, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT
        ))
        setContentView(root)

        splashStartedAt = System.currentTimeMillis()

        // Never leave the branded splash covering the app indefinitely.
        handler.postDelayed({ hideSplash() }, 8000)

        if (savedInstanceState == null) webView.loadUrl(appUrl)
        else webView.restoreState(savedInstanceState)
    }

    private fun createSplash(): View {
        val background = FrameLayout(this).apply {
            setBackgroundColor(Color.rgb(9, 9, 20))
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
        }

        val logo = ImageView(this).apply {
            setImageResource(R.mipmap.ic_launcher)
            scaleType = ImageView.ScaleType.FIT_CENTER
        }
        content.addView(logo, LinearLayout.LayoutParams(dp(116), dp(116)))

        val title = TextView(this).apply {
            text = "CLIPRUSH"
            setTextColor(Color.WHITE)
            textSize = 29f
            letterSpacing = 0.16f
            gravity = Gravity.CENTER
            setPadding(0, dp(18), 0, dp(4))
        }
        content.addView(title)

        val subtitle = TextView(this).apply {
            text = "Your clips. Ready to rush."
            setTextColor(Color.rgb(165, 165, 190))
            textSize = 13f
            gravity = Gravity.CENTER
        }
        content.addView(subtitle)

        val bars = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        val barColors = intArrayOf(
            Color.rgb(139, 92, 246),
            Color.rgb(168, 85, 247),
            Color.rgb(192, 132, 252),
            Color.rgb(34, 211, 238),
            Color.rgb(14, 165, 233),
            Color.rgb(139, 92, 246),
            Color.rgb(168, 85, 247)
        )
        for (i in 0 until 7) {
            val bar = View(this).apply {
                this.background = android.graphics.drawable.GradientDrawable().apply {
                    setColor(barColors[i])
                    cornerRadius = dp(5).toFloat()
                }
                pivotY = dp(22).toFloat()
            }
            val params = LinearLayout.LayoutParams(dp(6), dp(34)).apply {
                leftMargin = dp(5)
                rightMargin = dp(5)
            }
            bars.addView(bar, params)
            ObjectAnimator.ofPropertyValuesHolder(
                bar,
                PropertyValuesHolder.ofFloat("scaleY", 0.28f, 1.0f, 0.28f)
            ).apply {
                duration = 850
                startDelay = i * 105L
                repeatCount = ObjectAnimator.INFINITE
                repeatMode = ObjectAnimator.RESTART
                start()
            }
        }
        val loaderParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT, dp(48)
        ).apply {
            topMargin = dp(28)
        }
        content.addView(bars, loaderParams)

        background.addView(content, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT
        ))
        return background
    }

    private fun checkAppReady() {
        if (splashHidden) return
        handler.postDelayed({
            if (splashHidden || isFinishing) return@postDelayed
            webView.evaluateJavascript(
                "!!(document.querySelector('[data-testid=\\\"stAppViewContainer\\\"]') && document.querySelector('[data-testid=\\\"stAppViewContainer\\\"]').children.length > 0)",
            ) { result ->
                val elapsed = System.currentTimeMillis() - splashStartedAt
                if (result == "true" && elapsed >= 900) {
                    hideSplash()
                } else if (elapsed >= 25000) {
                    hideSplash()
                } else {
                    checkAppReady()
                }
            }
        }, 300)
    }

    private fun hideSplash() {
        if (splashHidden) return
        splashHidden = true
        splashView.animate()
            .alpha(0f)
            .setDuration(250)
            .withEndAction { splashView.visibility = View.GONE }
            .start()
    }

    private fun dp(value: Int): Int =
        (value * resources.displayMetrics.density).toInt()

    override fun onSaveInstanceState(outState: Bundle) {
        webView.saveState(outState)
        super.onSaveInstanceState(outState)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (::webView.isInitialized && webView.canGoBack()) webView.goBack()
        else super.onBackPressed()
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        if (::webView.isInitialized) webView.destroy()
        super.onDestroy()
    }
}
