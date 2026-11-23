package br.com.biglinux.bigscreen

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Remote access through Tailscale (or another VPN): which addresses the app keeps and tries first. */
class NetTest {
    @Test
    fun tailscaleAddressesAreRecognised() {
        assertTrue(Net.isCgnat("100.109.119.104"))
        assertTrue(Net.isCgnat("100.64.0.1"))
        assertTrue(Net.isCgnat("100.127.255.254"))
        assertFalse(Net.isCgnat("100.63.255.255"))
        assertFalse(Net.isCgnat("100.128.0.1"))
        assertFalse(Net.isCgnat("192.168.0.235"))
        assertFalse(Net.isCgnat("100.100.1"))
        assertFalse(Net.isCgnat("100.100.1.999"))
        assertFalse(Net.isCgnat("pc.tailnet.ts.net"))
    }

    @Test
    fun vpnInterfacesAreRecognised() {
        assertTrue(Net.isVpnInterface("tun0"))
        assertTrue(Net.isVpnInterface("wg0"))
        assertTrue(Net.isVpnInterface("tailscale0"))
        assertFalse(Net.isVpnInterface("wlan0"))
        assertFalse(Net.isVpnInterface("rndis0"))
        assertFalse(Net.isVpnInterface(null))
    }

    @Test
    fun pairedAtHomeTheAppAlsoKeepsTheVpnAddress() {
        // Paired on the home Wi-Fi: the computer announces its LAN and Tailscale addresses.
        val atHome = Net.merge("192.168.0.235", listOf("192.168.0.235", "100.109.119.104"),
            emptyList(), listOf("192.168.0.235"))
        assertEquals(listOf("192.168.0.235", "100.109.119.104"), atHome)
        // Away from home it came in through Tailscale: that one first next time, the LAN still kept.
        val away = Net.merge("100.109.119.104", listOf("192.168.0.235", "100.109.119.104"), atHome, atHome)
        assertEquals(listOf("100.109.119.104", "192.168.0.235"), away)
    }

    @Test
    fun loopbackJunkAndOldAddressesAreDropped() {
        val known = (1..10).map { "10.0.0.$it" }
        val merged = Net.merge("127.0.0.1", listOf("192.168.0.235", "bad address", ""), known, listOf("::1"))
        assertEquals("192.168.0.235", merged.first())
        assertEquals(Net.MAX_ADDRESSES, merged.size)
        assertFalse(merged.any { it.startsWith("127.") || it == "::1" || it.contains(' ') || it.isEmpty() })
        assertEquals(listOf("pc.tailnet.ts.net"), Net.merge("USB", listOf("pc.tailnet.ts.net"), emptyList(), emptyList()))
    }

    @Test
    fun theHomeNetworkGetsAHeadStart() {
        assertEquals(0L, Net.startDelay("192.168.0.235"))
        assertEquals(Net.VPN_HEAD_START_MS, Net.startDelay("100.109.119.104"))
    }
}
