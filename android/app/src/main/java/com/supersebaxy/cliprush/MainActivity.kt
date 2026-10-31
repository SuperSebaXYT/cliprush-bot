package com.supersebaxy.cliprush

import android.os.Bundle
import android.content.Intent
import android.net.Uri
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

private const val REPO = "SuperSebaXYT/cliprush-bot"
private const val BRANCH = "main"
private const val PREFS = "cliprush_secure"
private const val GITHUB_CLIENT_ID = "Ov23liXBoY5Sg5Jooyrh"

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { ClipRushApp() }
    }
}

private object TokenVault {
    private const val alias = "cliprush_github_token_key"
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true).build())
        return generator.generateKey()
    }
    fun save(activity: ComponentActivity, token: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
        val packed = cipher.iv + encrypted
        activity.getSharedPreferences(PREFS, 0).edit()
            .putString("token", Base64.encodeToString(packed, Base64.NO_WRAP)).apply()
    }
    fun read(activity: ComponentActivity): String {
        return try {
            val packed = Base64.decode(activity.getSharedPreferences(PREFS, 0).getString("token", "") ?: "", Base64.NO_WRAP)
            val iv = packed.copyOfRange(0, 12)
            val data = packed.copyOfRange(12, packed.size)
            Cipher.getInstance("AES/GCM/NoPadding").run {
                init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
                String(doFinal(data), Charsets.UTF_8)
            }
        } catch (_: Exception) { "" }
    }
    fun saveRefresh(activity: ComponentActivity, refresh: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.doFinal(refresh.toByteArray(Charsets.UTF_8))
        val packed = cipher.iv + encrypted
        activity.getSharedPreferences(PREFS, 0).edit()
            .putString("refresh_token", Base64.encodeToString(packed, Base64.NO_WRAP)).apply()
    }
    fun readRefresh(activity: ComponentActivity): String {
        return try {
            val packed = Base64.decode(activity.getSharedPreferences(PREFS, 0).getString("refresh_token", "") ?: "", Base64.NO_WRAP)
            val iv = packed.copyOfRange(0, 12)
            val data = packed.copyOfRange(12, packed.size)
            Cipher.getInstance("AES/GCM/NoPadding").run {
                init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
                String(doFinal(data), Charsets.UTF_8)
            }
        } catch (_: Exception) { "" }
    }
    fun clear(activity: ComponentActivity) {
        activity.getSharedPreferences(PREFS, 0).edit().remove("token").remove("refresh_token").apply()
    }
}

private fun api(token: String, method: String, path: String, body: JSONObject? = null): JSONObject {
    val connection = (URL("https://api.github.com/repos/$REPO/$path").openConnection() as HttpURLConnection)
    connection.requestMethod = method
    connection.connectTimeout = 15000
    connection.readTimeout = 20000
    connection.setRequestProperty("Authorization", "Bearer $token")
    connection.setRequestProperty("Accept", "application/vnd.github+json")
    connection.setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
    if (body != null) {
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/json")
        connection.outputStream.use { it.write(body.toString().toByteArray()) }
    }
    val status = connection.responseCode
    val stream = if (status in 200..299) connection.inputStream else connection.errorStream
    val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
    connection.disconnect()
    if (status !in 200..299) throw IllegalStateException("GitHub API $status: ${response.take(220)}")
    return if (response.isBlank()) JSONObject() else JSONObject(response)
}

private fun oauthPost(fields: Map<String, String>): JSONObject {
    val connection = (URL("https://github.com/login/oauth/access_token").openConnection() as HttpURLConnection)
    connection.requestMethod = "POST"
    connection.connectTimeout = 15000
    connection.readTimeout = 20000
    connection.doOutput = true
    connection.setRequestProperty("Accept", "application/json")
    connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
    val body = fields.entries.joinToString("&") {
        java.net.URLEncoder.encode(it.key, "UTF-8") + "=" + java.net.URLEncoder.encode(it.value, "UTF-8")
    }
    connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
    val status = connection.responseCode
    val stream = if (status in 200..299) connection.inputStream else connection.errorStream
    val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
    connection.disconnect()
    if (status !in 200..299) throw IllegalStateException("GitHub OAuth HTTP $status: ${response.take(180)}")
    return JSONObject(response)
}

private fun requestDeviceCode(): JSONObject {
    val connection = (URL("https://github.com/login/device/code").openConnection() as HttpURLConnection)
    connection.requestMethod = "POST"
    connection.connectTimeout = 15000
    connection.readTimeout = 20000
    connection.doOutput = true
    connection.setRequestProperty("Accept", "application/json")
    connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
    val body = "client_id=" + java.net.URLEncoder.encode(GITHUB_CLIENT_ID, "UTF-8") +
        "&scope=" + java.net.URLEncoder.encode("repo", "UTF-8")
    connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
    val status = connection.responseCode
    val stream = if (status in 200..299) connection.inputStream else connection.errorStream
    val response = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
    connection.disconnect()
    if (status !in 200..299) throw IllegalStateException("Nie udało się rozpocząć logowania: HTTP $status")
    val json = JSONObject(response)
    if (json.has("error")) throw IllegalStateException(json.optString("error_description", json.optString("error")))
    return json
}

private fun refreshOAuthToken(refresh: String): JSONObject = oauthPost(mapOf(
    "client_id" to GITHUB_CLIENT_ID,
    "grant_type" to "refresh_token",
    "refresh_token" to refresh
))

private fun readRepoFile(token: String, path: String): Pair<String, String?> {
    return try {
        val obj = api(token, "GET", "contents/$path?ref=$BRANCH")
        val encoded = obj.optString("content").replace("\n", "")
        val content = String(Base64.decode(encoded, Base64.DEFAULT), Charsets.UTF_8)
        content to obj.optString("sha")
    } catch (e: Exception) {
        if (e.message?.contains("404") == true) "" to null else throw e
    }
}

private fun writeRepoFile(token: String, path: String, content: String, sha: String?, message: String) {
    val body = JSONObject().put("message", message)
        .put("content", Base64.encodeToString(content.toByteArray(), Base64.NO_WRAP))
        .put("branch", BRANCH)
    if (sha != null) body.put("sha", sha)
    api(token, "PUT", "contents/$path", body)
}

private val bg = Color(0xFF080711)
private val panel = Color(0xFF151027)
private val purple = Color(0xFFB66CFF)
private val cyan = Color(0xFF28D9F2)
private val white = Color(0xFFF5F1FF)

@Composable
private fun ClipRushApp() {
    val activity = androidx.compose.ui.platform.LocalContext.current as ComponentActivity
    val scope = rememberCoroutineScope()
    var token by remember { mutableStateOf(TokenVault.read(activity)) }
    var connected by remember { mutableStateOf(token.isNotBlank()) }
    var busy by remember { mutableStateOf(token.isNotBlank()) }
    var message by remember { mutableStateOf("") }
    var deviceCode by remember { mutableStateOf("") }
    var userCode by remember { mutableStateOf("") }
    var verificationUri by remember { mutableStateOf("https://github.com/login/device") }
    val uriHandler = androidx.compose.ui.platform.LocalUriHandler.current

    var tab by remember { mutableStateOf(0) }
    var sources by remember { mutableStateOf("") }
    var config by remember { mutableStateOf(JSONObject()) }
    var sourcesSha by remember { mutableStateOf<String?>(null) }
    var configSha by remember { mutableStateOf<String?>(null) }
    var runs by remember { mutableStateOf(listOf<String>()) }

    // Automatyczne logowanie zapisanym tokenem po każdym uruchomieniu aplikacji.
    // Nie usuwamy tokena, jeśli GitHub chwilowo nie odpowiada lub token wygasł.
    LaunchedEffect(Unit) {
        if (token.isNotBlank()) {
            try {
                val savedRefresh = TokenVault.readRefresh(activity)
                if (savedRefresh.isNotBlank()) {
                    val refreshed = withContext(Dispatchers.IO) { refreshOAuthToken(savedRefresh) }
                    val newAccess = refreshed.optString("access_token")
                    val newRefresh = refreshed.optString("refresh_token")
                    if (newAccess.isBlank() || newRefresh.isBlank()) throw IllegalStateException("GitHub nie zwrócił nowego tokena.")
                    token = newAccess
                    TokenVault.save(activity, newAccess)
                    TokenVault.saveRefresh(activity, newRefresh)
                }
                withContext(Dispatchers.IO) {
                    api(token.trim(), "GET", "contents/config.json?ref=$BRANCH")
                }
                taskLoad(token.trim()) { s, ss, c, cs ->
                    sources = s
                    sourcesSha = ss
                    config = c
                    configSha = cs
                }
            } catch (e: Exception) {
                connected = false
                message = "Automatyczne logowanie nie powiodło się: ${e.message ?: "zaloguj się ponownie"}"
            } finally {
                busy = false
            }
        }
    }

    fun task(block: suspend () -> Unit) {
        scope.launch {
            busy = true
            message = ""
            try { block() } catch (e: Exception) { message = e.message ?: "Wystąpił błąd." }
            busy = false
        }
    }

    MaterialTheme(colorScheme = darkColorScheme(
        primary = purple, secondary = cyan, background = bg, surface = panel,
        onPrimary = Color.White, onBackground = white, onSurface = white
    )) {
        Box(Modifier.fillMaxSize().background(Brush.linearGradient(listOf(bg, Color(0xFF170B2B), Color(0xFF071521))))) {
            if (!connected) {
                Column(Modifier.fillMaxSize().padding(26.dp), verticalArrangement = Arrangement.Center) {
                    BrandHeader()
                    Spacer(Modifier.height(28.dp))
                    Text("Połącz GitHub", fontSize = 23.sp, fontWeight = FontWeight.Bold, color = white)
                    Text("Bez wklejania PAT. Zaloguj się bezpiecznie przez kod urządzenia GitHub.", color = Color.LightGray, fontSize = 13.sp)
                    Spacer(Modifier.height(16.dp))
                    ActionButton(if (userCode.isBlank()) "ZALOGUJ PRZEZ GITHUB" else "OTWÓRZ GITHUB I WPISZ KOD", busy) {
                        task {
                            var pollingInterval = 5L
                            if (deviceCode.isBlank()) {
                                val auth = withContext(Dispatchers.IO) { requestDeviceCode() }
                                pollingInterval = auth.optLong("interval", 5L).coerceAtLeast(5L)
                                deviceCode = auth.getString("device_code")
                                userCode = auth.getString("user_code")
                                verificationUri = auth.optString("verification_uri", "https://github.com/login/device")
                                uriHandler.openUri(verificationUri)
                            } else {
                                uriHandler.openUri(verificationUri)
                            }
                            if (deviceCode.isNotBlank()) {
                                var interval = pollingInterval
                                val expiresAt = System.currentTimeMillis() + 15L * 60L * 1000L
                                var authorized = false
                                while (System.currentTimeMillis() < expiresAt && !authorized) {
                                    delay(interval * 1000L)
                                    val result = withContext(Dispatchers.IO) {
                                        oauthPost(mapOf(
                                            "client_id" to GITHUB_CLIENT_ID,
                                            "device_code" to deviceCode,
                                            "grant_type" to "urn:ietf:params:oauth:grant-type:device_code"
                                        ))
                                    }
                                    when (result.optString("error")) {
                                        "authorization_pending" -> Unit
                                        "slow_down" -> interval += 5L
                                        "access_denied" -> throw IllegalStateException("Logowanie zostało anulowane na GitHubie.")
                                        "expired_token", "token_expired" -> throw IllegalStateException("Kod wygasł. Rozpocznij logowanie ponownie.")
                                        "" -> {
                                            val access = result.optString("access_token")
                                            val refresh = result.optString("refresh_token")
                                            if (access.isBlank()) throw IllegalStateException("GitHub nie zwrócił tokena.")
                                            withContext(Dispatchers.IO) {
                                                api(access, "GET", "contents/config.json?ref=$BRANCH")
                                            }
                                            TokenVault.save(activity, access)
                                            if (refresh.isNotBlank()) TokenVault.saveRefresh(activity, refresh)
                                            token = access
                                            connected = true
                                            taskLoad(access) { s, ss, c, cs ->
                                                sources = s; sourcesSha = ss; config = c; configSha = cs
                                            }
                                            authorized = true
                                        }
                                        else -> throw IllegalStateException(result.optString("error_description", result.optString("error")))
                                    }
                                }
                                if (!authorized) throw IllegalStateException("Kod logowania wygasł. Spróbuj ponownie.")
                            }
                        }
                    }
                    if (userCode.isNotBlank()) {
                        Spacer(Modifier.height(14.dp))
                        Text("TWÓJ KOD GITHUB", color = cyan, fontSize = 11.sp, letterSpacing = 2.sp)
                        Text(userCode, color = white, fontSize = 30.sp, fontWeight = FontWeight.Black)
                        Text("Jeśli przeglądarka się nie otworzyła, wejdź na github.com/login/device.", color = Color.LightGray, fontSize = 12.sp)
                    }
                    Text("Dostęp do repozytorium zostanie przyznany dopiero po zatwierdzeniu na GitHubie.", color = Color.Gray, fontSize = 11.sp)
                }
            } else {
                Column(Modifier.fillMaxSize()) {
                    Column(Modifier.padding(horizontal = 20.dp, vertical = 18.dp)) {
                        BrandHeader()
                        Text("AI CLIPPING CONTROL CENTER", color = cyan, fontSize = 10.sp, letterSpacing = 2.sp)
                    }
                    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf("ŹRÓDŁA", "USTAWIENIA", "RUNY").forEachIndexed { i, label ->
                            FilterChip(selected = tab == i, onClick = { tab = i }, label = { Text(label) })
                        }
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = { TokenVault.clear(activity); token = ""; connected = false; deviceCode = ""; userCode = "" }) { Text("WYLOGUJ") }
                    }
                    if (busy) LinearProgressIndicator(Modifier.fillMaxWidth(), color = cyan)
                    LazyColumn(Modifier.weight(1f).padding(horizontal = 18.dp), contentPadding = PaddingValues(vertical = 14.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                        item {
                            when (tab) {
                                0 -> {
                                    Panel("Źródła LIVE / VOD") {
                                        Text("Jeden adres na linię. Dodawaj tylko materiały, do których masz prawa.", color = Color.LightGray, fontSize = 12.sp)
                                        Spacer(Modifier.height(10.dp))
                                        OutlinedTextField(sources, { sources = it }, modifier = Modifier.fillMaxWidth().height(220.dp), placeholder = { Text("https://youtube.com/...") })
                                        Text("Liczba źródeł: ${sources.lines().count { it.trim().isNotEmpty() && !it.trim().startsWith("#") }}", color = cyan)
                                        ActionButton("ZAPISZ ŹRÓDŁA", busy) {
                                            task { withContext(Dispatchers.IO) { writeRepoFile(token, "sources.txt", sources.trimEnd() + "\n", sourcesSha, "Update clipping sources") }; message = "Źródła zapisane."; taskLoad(token) { s, ss, c, cs -> sources=s; sourcesSha=ss; config=c; configSha=cs } }
                                        }
                                    }
                                }
                                1 -> SettingsPanel(config, busy, { updated -> config = updated }) {
                                    updated -> task {
                                        withContext(Dispatchers.IO) { writeRepoFile(token, "config.json", updated.toString(2) + "\n", configSha, "Update clipping settings") }
                                        message = "Ustawienia zapisane."
                                        taskLoad(token) { s, ss, c, cs -> sources=s; sourcesSha=ss; config=c; configSha=cs }
                                    }
                                }
                                else -> {
                                    Panel("Ostatnie uruchomienia") {
                                        ActionButton("ODŚWIEŻ STATUS", busy) {
                                            task { runs = withContext(Dispatchers.IO) {
                                                val result = api(token, "GET", "actions/workflows/clipping.yml/runs?per_page=8")
                                                val arr = result.optJSONArray("workflow_runs") ?: JSONArray()
                                                (0 until arr.length()).map { idx ->
                                                    val r = arr.getJSONObject(idx)
                                                    "${r.optString("name")} · ${r.optString("conclusion", r.optString("status"))} · #${r.optInt("run_number")}"
                                                }
                                            } }
                                        }
                                        runs.forEach { Text(it, color = white, modifier = Modifier.padding(vertical = 7.dp)) }
                                        if (runs.isEmpty()) Text("Naciśnij odśwież, aby pobrać statusy.", color = Color.Gray)
                                    }
                                }
                            }
                        }
                        if (message.isNotBlank()) item { Text(message, color = if (message.contains("zapisane")) cyan else Color(0xFFFF8A9A), fontSize = 13.sp) }
                    }
                    if (tab != 2) {
                        ActionButton("URUCHOM CLIPRUSH", busy) {
                            task { withContext(Dispatchers.IO) {
                                val body = JSONObject().put("ref", BRANCH)
                                val conn = URL("https://api.github.com/repos/$REPO/actions/workflows/clipping.yml/dispatches").openConnection() as HttpURLConnection
                                conn.requestMethod = "POST"; conn.doOutput = true
                                conn.setRequestProperty("Authorization", "Bearer $token")
                                conn.setRequestProperty("Accept", "application/vnd.github+json")
                                conn.setRequestProperty("Content-Type", "application/json")
                                conn.outputStream.use { it.write(body.toString().toByteArray()) }
                                val status = conn.responseCode
                                conn.disconnect()
                                if (status != 204) throw IllegalStateException("Nie udało się uruchomić workflow: HTTP $status")
                            }; message = "Bot został uruchomiony." }
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                }
            }
        }
    }
}

private suspend fun taskLoad(token: String, apply: (String, String?, JSONObject, String?) -> Unit) {
    val data = withContext(Dispatchers.IO) {
        val (s, ss) = readRepoFile(token, "sources.txt")
        val (c, cs) = readRepoFile(token, "config.json")
        Quad(s, ss, JSONObject(c), cs)
    }
    apply(data.a, data.b, data.c, data.d)
}
private data class Quad(val a: String, val b: String?, val c: JSONObject, val d: String?)

@Composable private fun BrandHeader() {
    Column(Modifier.fillMaxWidth().padding(top = 2.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("CLIP", fontSize = 34.sp, fontWeight = FontWeight.Black, letterSpacing = 4.sp, color = white)
            Text("RUSH", fontSize = 34.sp, fontWeight = FontWeight.Black, letterSpacing = 4.sp, color = white)
        }
        Text("YOUR CLIPS. READY TO RUSH.", fontSize = 10.sp, letterSpacing = 2.sp, color = cyan)
    }
}
@Composable private fun Panel(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().background(panel, RoundedCornerShape(20.dp)).padding(17.dp)) {
        Text(title, color = purple, fontWeight = FontWeight.Bold, fontSize = 18.sp)
        Spacer(Modifier.height(12.dp))
        content()
    }
}
@Composable private fun ActionButton(text: String, busy: Boolean, onClick: () -> Unit) {
    Button(onClick = onClick, enabled = !busy, modifier = Modifier.fillMaxWidth().height(52.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF7138D5)),
        shape = RoundedCornerShape(14.dp)) {
        Text(if (busy) "ŁĄCZENIE..." else text, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
    }
}
@Composable private fun SettingsPanel(config: JSONObject, busy: Boolean, onChange: (JSONObject) -> Unit, onSave: (JSONObject) -> Unit) {
    var clips by remember(config) { mutableIntStateOf(config.optInt("clips_per_source", 2)) }
    var duration by remember(config) { mutableIntStateOf(config.optInt("clip_duration_seconds", 35)) }
    var maxSources by remember(config) { mutableIntStateOf(config.optInt("max_sources_per_run", 2)) }
    var auto by remember(config) { mutableStateOf(config.optBoolean("auto_discovery_enabled", true)) }
    var publish by remember(config) { mutableStateOf(config.optBoolean("publish", false)) }
    var privacy by remember(config) { mutableStateOf(config.optString("privacy_status", "private")) }
    var channels by remember(config) { mutableStateOf(config.optJSONArray("discovery_channels")?.let { a -> (0 until a.length()).joinToString("\n") { a.optString(it) } } ?: "") }
    var language by remember(config) { mutableStateOf(config.optString("language", "en")) }
    var whisper by remember(config) { mutableStateOf(config.optString("whisper_model", "small")) }
    Panel("Ustawienia pipeline") {
        Text("Klipy na źródło: $clips", color = white)
        Slider(clips.toFloat(), { clips = it.toInt(); onChange(JSONObject(config.toString()).put("clips_per_source", clips)) }, valueRange = 1f..5f, steps = 3)
        Text("Długość klipu: $duration s", color = white)
        Slider(duration.toFloat(), { duration = it.toInt(); onChange(JSONObject(config.toString()).put("clip_duration_seconds", duration).put("min_clip_seconds", minOf(20,duration)).put("max_clip_seconds", minOf(55,duration))) }, valueRange = 20f..55f, steps = 34)
        Text("Źródła na uruchomienie: $maxSources", color = white)
        Slider(maxSources.toFloat(), { maxSources = it.toInt(); onChange(JSONObject(config.toString()).put("max_sources_per_run", maxSources)) }, valueRange = 1f..5f, steps = 3)
        Row(verticalAlignment = Alignment.CenterVertically) { Text("Automatyczne LIVE / VOD", Modifier.weight(1f), color = white); Switch(auto, { auto=it; onChange(JSONObject(config.toString()).put("auto_discovery_enabled", auto)) }) }
        OutlinedTextField(channels, { channels=it; onChange(JSONObject(config.toString()).put("discovery_channels", JSONArray(it.lines().filter { line -> line.isNotBlank() }))) }, label={Text("Kanały, jeden URL na linię")}, modifier=Modifier.fillMaxWidth(), minLines=3)
        Row(verticalAlignment = Alignment.CenterVertically) { Text("Publikuj automatycznie", Modifier.weight(1f), color = white); Switch(publish, { publish=it; onChange(JSONObject(config.toString()).put("publish", publish)) }) }
        Text("Widoczność publikacji", color = white)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) { listOf("private","unlisted","public").forEach { FilterChip(selected=privacy==it,onClick={privacy=it;onChange(JSONObject(config.toString()).put("privacy_status",it))},label={Text(it)}) } }
        Text("Język", color = white)
        Row { listOf("en","pl","auto").forEach { FilterChip(selected=language==it,onClick={language=it;onChange(JSONObject(config.toString()).put("language",it))},label={Text(it)}) } }
        Text("Whisper", color = white)
        Row { listOf("base","small","medium").forEach { FilterChip(selected=whisper==it,onClick={whisper=it;onChange(JSONObject(config.toString()).put("whisper_model",it))},label={Text(it)}) } }
        ActionButton("ZAPISZ USTAWIENIA", busy) { 
            val updated = JSONObject(config.toString()).put("clips_per_source",clips).put("clip_duration_seconds",duration).put("min_clip_seconds",minOf(20,duration)).put("max_clip_seconds",minOf(55,duration)).put("max_sources_per_run",maxSources).put("auto_discovery_enabled",auto).put("discovery_channels",JSONArray(channels.lines().filter { it.isNotBlank() })).put("publish",publish).put("privacy_status",privacy).put("language",language).put("whisper_model",whisper)
            onSave(updated)
        }
    }
}
