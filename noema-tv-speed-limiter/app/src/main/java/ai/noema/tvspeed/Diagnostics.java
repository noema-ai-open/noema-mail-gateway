package ai.noema.tvspeed;

import java.util.concurrent.atomic.AtomicLong;

/** Lightweight in-app diagnostics so Android TV can be debugged without ADB. */
final class Diagnostics {
    static final AtomicLong SOCKS_ACCEPTED = new AtomicLong();
    static final AtomicLong TCP_CONNECT_OK = new AtomicLong();
    static final AtomicLong TCP_CONNECT_FAIL = new AtomicLong();
    static final AtomicLong UDP_ASSOC = new AtomicLong();
    static final AtomicLong UDP_OUT = new AtomicLong();
    static final AtomicLong UDP_IN = new AtomicLong();

    private static volatile String physical = "not selected";
    private static volatile String dns = "not set";
    private static volatile String socks = "stopped";
    private static volatile String tun = "down";
    private static volatile String hev = "down";
    private static volatile String lastError = "none";

    private Diagnostics() {}

    static void resetSession() {
        SOCKS_ACCEPTED.set(0);
        TCP_CONNECT_OK.set(0);
        TCP_CONNECT_FAIL.set(0);
        UDP_ASSOC.set(0);
        UDP_OUT.set(0);
        UDP_IN.set(0);
        physical = "not selected";
        dns = "not set";
        socks = "stopped";
        tun = "down";
        hev = "down";
        lastError = "none";
    }

    static void physical(String value) { physical = safe(value); }
    static void dns(String value) { dns = safe(value); }
    static void socks(String value) { socks = safe(value); }
    static void tun(String value) { tun = safe(value); }
    static void hev(String value) { hev = safe(value); }
    static void error(String value) { lastError = safe(value); }

    static String snapshot() {
        return "Android: " + android.os.Build.VERSION.RELEASE + " / API " + android.os.Build.VERSION.SDK_INT +
                "\nPhysical: " + physical +
                "\nDNS: " + dns +
                "\nSOCKS: " + socks +
                "\nTUN: " + tun +
                "\nHEV: " + hev +
                "\nSOCKS accepted: " + SOCKS_ACCEPTED.get() +
                "\nTCP connect OK/fail: " + TCP_CONNECT_OK.get() + "/" + TCP_CONNECT_FAIL.get() +
                "\nUDP associations: " + UDP_ASSOC.get() +
                "\nUDP packets out/in: " + UDP_OUT.get() + "/" + UDP_IN.get() +
                "\nTraffic down/up: " + TrafficStatsStore.DOWN.get() + "/" + TrafficStatsStore.UP.get() + " bytes" +
                "\nLast error: " + lastError;
    }

    private static String safe(String value) {
        return value == null || value.isEmpty() ? "none" : value;
    }
}
