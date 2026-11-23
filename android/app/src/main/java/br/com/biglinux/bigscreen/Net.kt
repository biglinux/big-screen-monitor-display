package br.com.biglinux.bigscreen

/**
 * Address rules of the network connection (plain JVM, unit-tested): which addresses of a computer
 * to remember and in which order to try them, and what counts as a VPN (Tailscale and the like).
 */
object Net {
    /** Addresses kept per computer: its home network(s), its VPN address and the one that last worked. */
    const val MAX_ADDRESSES = 8

    /** VPN addresses start this much later, so at home the direct network wins the race. */
    const val VPN_HEAD_START_MS = 300L

    private val VPN_INTERFACES = listOf("tun", "tap", "wg", "ppp", "ipsec", "tailscale", "zt")

    /** 100.64.0.0/10: the addresses Tailscale, Headscale and NetBird give each device. */
    fun isCgnat(address: String): Boolean {
        val parts = address.split(".")
        if (parts.size != 4) return false
        val first = parts[0].toIntOrNull() ?: return false
        val second = parts[1].toIntOrNull() ?: return false
        return first == 100 && second in 64..127 && parts.drop(2).all { (it.toIntOrNull() ?: -1) in 0..255 }
    }

    /** The phone's side of a VPN (Android names the Tailscale/WireGuard/OpenVPN interface tun0). */
    fun isVpnInterface(name: String?): Boolean = name != null && VPN_INTERFACES.any { name.startsWith(it) }

    /** A host name or an IP address as typed or announced: nothing else is ever stored. */
    fun isHost(text: String): Boolean = text.isNotEmpty() && text.length <= 253 &&
        text.all { it.isLetterOrDigit() || it == '.' || it == '-' || it == ':' || it == '%' }

    private fun isLoopback(address: String): Boolean =
        address.startsWith("127.") || address == "::1" || address.equals("localhost", ignoreCase = true)

    /**
     * The addresses to remember for a computer, best first: the one that just worked, then the
     * ones the computer announced in WELCOME (home network first, then its VPN address), then the
     * ones known before. Loopback (adb reverse) is never kept; stale addresses fall off the end.
     */
    fun merge(current: String?, announced: List<String>, known: List<String>, given: List<String>): List<String> {
        val out = LinkedHashSet<String>()
        if (current != null && current != "USB") out.add(current)
        out.addAll(announced)
        out.addAll(known)
        out.addAll(given)
        return out.filter { isHost(it) && !isLoopback(it) }.take(MAX_ADDRESSES)
    }

    /** When to start connecting to [address]: at once on the local network, a little later through a VPN. */
    fun startDelay(address: String): Long = if (isCgnat(address)) VPN_HEAD_START_MS else 0L
}
