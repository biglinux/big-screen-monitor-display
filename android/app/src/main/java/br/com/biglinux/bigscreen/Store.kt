package br.com.biglinux.bigscreen

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import org.json.JSONArray
import org.json.JSONObject
import java.security.KeyStore
import java.security.SecureRandom
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** A computer this phone paired with. The token never leaves this app (and is encrypted at rest). */
data class Computer(
    val serverId: String,
    var name: String,
    var fingerprint: String,          // base64url SHA-256 of the computer's certificate (pinned)
    var addresses: List<String>,
    var port: Int,
    var lastSeen: Long = 0L,
    var lastTransport: String = "",
    var displayId: String = "",
) {
    fun toJson(): JSONObject = JSONObject()
        .put("server_id", serverId).put("name", name).put("fp", fingerprint)
        .put("addresses", JSONArray(addresses)).put("port", port).put("last_seen", lastSeen)
        .put("last_transport", lastTransport).put("display_id", displayId)

    companion object {
        fun fromJson(obj: JSONObject): Computer? {
            val id = obj.optString("server_id")
            if (id.length != 32) return null
            val list = obj.optJSONArray("addresses") ?: JSONArray()
            return Computer(id, obj.optString("name", "Linux"), obj.optString("fp"),
                (0 until list.length()).map { list.optString(it) }.filter { it.isNotEmpty() },
                obj.optInt("port", DEFAULT_PORT), obj.optLong("last_seen"), obj.optString("last_transport"),
                obj.optString("display_id"))
        }
    }
}

const val DEFAULT_PORT = 7717

/** Settings, the installation id and the paired computers. */
class Store(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("bsmd", Context.MODE_PRIVATE)
    private val box = SecureBox()

    /** Random id of this installation (no IMEI, serial or account: nothing that identifies the person). */
    val deviceId: String
        get() {
            prefs.getString("device_id", null)?.let { return it }
            val id = UUID.randomUUID().toString()
            prefs.edit().putString("device_id", id).apply()
            return id
        }

    var deviceName: String
        get() = prefs.getString("device_name", null) ?: defaultName()
        set(value) = prefs.edit().putString("device_name", value.take(40)).apply()

    private fun defaultName(): String {
        val model = Build.MODEL ?: "Android"
        val maker = Build.MANUFACTURER ?: ""
        return if (model.lowercase().startsWith(maker.lowercase())) model else "$maker $model".trim()
    }

    // ------------------------------------------------------------ local options
    fun bool(key: String, default: Boolean) = prefs.getBoolean(key, default)
    fun setBool(key: String, value: Boolean) = prefs.edit().putBoolean(key, value).apply()
    fun string(key: String, default: String) = prefs.getString(key, default) ?: default
    fun setString(key: String, value: String) = prefs.edit().putString(key, value).apply()

    var lastServer: String
        get() = prefs.getString("last_server", "") ?: ""
        set(value) = prefs.edit().putString("last_server", value).apply()

    // ------------------------------------------------------------ computers
    fun computers(): List<Computer> {
        val array = try {
            JSONArray(prefs.getString("computers", "[]"))
        } catch (error: Exception) {
            JSONArray()
        }
        return (0 until array.length()).mapNotNull { array.optJSONObject(it)?.let(Computer::fromJson) }
            .sortedByDescending { it.lastSeen }
    }

    fun computer(serverId: String): Computer? = computers().firstOrNull { it.serverId == serverId }

    fun save(computer: Computer) {
        val list = computers().filter { it.serverId != computer.serverId } + computer
        prefs.edit().putString("computers", JSONArray(list.map { it.toJson() }).toString()).apply()
    }

    fun forget(serverId: String) {
        val list = computers().filter { it.serverId != serverId }
        prefs.edit().putString("computers", JSONArray(list.map { it.toJson() }).toString())
            .remove("token_$serverId").apply()
        if (lastServer == serverId) lastServer = ""
    }

    fun token(serverId: String): ByteArray? = prefs.getString("token_$serverId", null)?.let { box.open(it) }

    fun setToken(serverId: String, token: ByteArray) {
        prefs.edit().putString("token_$serverId", box.seal(token)).apply()
    }
}

/**
 * AES-GCM with a key that never leaves the Android Keystore (Android 6.0+).
 * Android 5.x has no app-usable symmetric Keystore keys: there the token is
 * kept in the app's private storage only (documented limitation).
 */
class SecureBox {
    private val alias = "bsmd-token-key"

    private fun key(): SecretKey? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return null
        return try {
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            (store.getKey(alias, null) as? SecretKey) ?: KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
                init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256).build())
            }.generateKey()
        } catch (error: Exception) {
            null
        }
    }

    fun seal(data: ByteArray): String {
        val key = key() ?: return "p:" + B64.encode(data)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key)
        return "k:" + B64.encode(cipher.iv) + ":" + B64.encode(cipher.doFinal(data))
    }

    fun open(text: String): ByteArray? = try {
        when {
            text.startsWith("p:") -> B64.decode(text.substring(2))
            text.startsWith("k:") -> {
                val parts = text.substring(2).split(":")
                val key = key() ?: return null
                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, B64.decode(parts[0])))
                cipher.doFinal(B64.decode(parts[1]))
            }
            else -> null
        }
    } catch (error: Exception) {
        null
    }

    companion object {
        fun nonce(size: Int = 24): ByteArray = ByteArray(size).also { SecureRandom().nextBytes(it) }
    }
}
