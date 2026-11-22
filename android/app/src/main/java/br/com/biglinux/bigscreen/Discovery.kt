package br.com.biglinux.bigscreen

import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException

/** A computer that answered on the local network. */
data class Found(
    val serverId: String,
    val name: String,
    val address: String,
    val port: Int,
    val fingerprint: String,
    val pairingOpen: Boolean,
)

/**
 * Finds computers running Big Screen Monitor Display on the local network:
 * a UDP request to the broadcast addresses (and to known computers) on the
 * port after the TLS one; each computer answers with its name, id, port and
 * certificate fingerprint. No mDNS daemon is needed on the computer.
 * Run off the main thread.
 */
object Discovery {
    private val REQUEST = "BSMD?1".toByteArray(Charsets.US_ASCII)
    private val REPLY = "BSMD!1".toByteArray(Charsets.US_ASCII)

    fun scan(known: List<Computer>, timeoutMs: Int = 1500, port: Int = DEFAULT_PORT): List<Found> {
        val found = LinkedHashMap<String, Found>()
        val nonce = Bsdp.hex(SecureBox.nonce(6))
        val payload = REQUEST + nonce.toByteArray(Charsets.US_ASCII)
        DatagramSocket().use { socket ->
            socket.broadcast = true
            socket.soTimeout = 250
            val targets = LinkedHashSet<Pair<InetAddress, Int>>()
            for (address in broadcastAddresses()) targets.add(address to port + 1)
            for (computer in known) {
                for (address in computer.addresses) {
                    try {
                        targets.add(InetAddress.getByName(address) to computer.port + 1)
                    } catch (error: Exception) {
                        // an address that no longer resolves
                    }
                }
            }
            val deadline = System.currentTimeMillis() + timeoutMs
            var nextSend = 0L
            val buffer = ByteArray(2048)
            while (System.currentTimeMillis() < deadline) {
                val now = System.currentTimeMillis()
                if (now >= nextSend) {             // twice: one datagram may be lost on Wi-Fi
                    for ((address, targetPort) in targets) {
                        try {
                            socket.send(DatagramPacket(payload, payload.size, address, targetPort))
                        } catch (error: Exception) {
                            // unreachable network: try the others
                        }
                    }
                    nextSend = now + 600
                }
                val packet = DatagramPacket(buffer, buffer.size)
                try {
                    socket.receive(packet)
                } catch (timeout: SocketTimeoutException) {
                    continue
                }
                parse(packet)?.let { if (!found.containsKey(it.serverId)) found[it.serverId] = it }   // putIfAbsent: API 24
            }
        }
        return found.values.toList()
    }

    private fun parse(packet: DatagramPacket): Found? {
        val data = packet.data.copyOfRange(packet.offset, packet.offset + packet.length)
        if (data.size < REPLY.size || !data.copyOfRange(0, REPLY.size).contentEquals(REPLY)) return null
        return try {
            val obj = JSONObject(String(data, REPLY.size, data.size - REPLY.size, Charsets.UTF_8))
            val id = obj.optString("server_id")
            if (obj.optInt("proto") != Bsdp.VERSION || id.length != 32) return null
            Found(id, obj.optString("name", "Linux").take(40), packet.address.hostAddress ?: return null,
                obj.optInt("port", DEFAULT_PORT), obj.optString("fp"), obj.optBoolean("pairing"))
        } catch (error: Exception) {
            null
        }
    }

    private fun broadcastAddresses(): List<InetAddress> {
        val out = ArrayList<InetAddress>()
        try {
            out.add(InetAddress.getByName("255.255.255.255"))
            val interfaces = NetworkInterface.getNetworkInterfaces() ?: return out
            for (nif in interfaces) {
                if (!nif.isUp || nif.isLoopback) continue
                for (address in nif.interfaceAddresses) {
                    if (address.address is Inet4Address) address.broadcast?.let { out.add(it) }
                }
            }
        } catch (error: Exception) {
            // no network at all
        }
        return out
    }
}
