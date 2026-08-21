package ai.noema.tvspeed;

import android.net.Network;
import android.net.VpnService;
import android.util.Log;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Minimal local SOCKS5 server used as the direct-to-internet egress for HEV tun2socks.
 * Remote sockets are protected from the Android VPN and, when available, explicitly
 * created on the selected physical network. TCP CONNECT and UDP ASSOCIATE are supported.
 */
final class LocalSocksServer implements AutoCloseable {
    private static final String TAG = "NoemaSocks";
    private static final int BUF = 32 * 1024;
    private static final int MAX_UDP = 64 * 1024;

    private final VpnService vpnService;
    private final RateLimiter downloadLimiter;
    private final Network physicalNetwork;
    private final ExecutorService pool = Executors.newCachedThreadPool();
    private final Set<Socket> tcpSockets = ConcurrentHashMap.newKeySet();
    private final Set<DatagramSocket> udpSockets = ConcurrentHashMap.newKeySet();

    private volatile boolean running;
    private ServerSocket server;
    private final int requestedPort;
    private volatile int boundPort;

    LocalSocksServer(VpnService vpnService, RateLimiter downloadLimiter, int port, Network physicalNetwork) {
        this.vpnService = vpnService;
        this.downloadLimiter = downloadLimiter;
        this.requestedPort = port;
        this.physicalNetwork = physicalNetwork;
    }

    int getPort() {
        return boundPort;
    }

    void start() throws IOException {
        server = new ServerSocket();
        server.setReuseAddress(true);
        server.bind(new InetSocketAddress(loopback4(), requestedPort));
        boundPort = server.getLocalPort();
        running = true;
        pool.execute(this::acceptLoop);
    }

    private void acceptLoop() {
        while (running) {
            try {
                Socket client = server.accept();
                Diagnostics.SOCKS_ACCEPTED.incrementAndGet();
                client.setTcpNoDelay(true);
                tcpSockets.add(client);
                pool.execute(() -> handleClient(client));
            } catch (SocketException e) {
                if (running) {
                    Diagnostics.error("SOCKS accept: " + e.getMessage());
                    Log.e(TAG, "SOCKS accept failed", e);
                }
            } catch (IOException e) {
                if (running) {
                    Diagnostics.error("SOCKS accept: " + e.getMessage());
                    Log.e(TAG, "SOCKS accept failed", e);
                }
            }
        }
    }

    private void handleClient(Socket client) {
        try (Socket c = client;
             InputStream rawIn = new BufferedInputStream(c.getInputStream());
             OutputStream rawOut = new BufferedOutputStream(c.getOutputStream())) {

            int version = readU8(rawIn);
            if (version != 5) throw new IOException("Unsupported SOCKS version: " + version);
            int nMethods = readU8(rawIn);
            byte[] methods = readFully(rawIn, nMethods);

            int selected = contains(methods, (byte) 0x00) ? 0x00 : (contains(methods, (byte) 0x02) ? 0x02 : 0xff);
            rawOut.write(new byte[]{0x05, (byte) selected});
            rawOut.flush();
            if (selected == 0xff) return;

            if (selected == 0x02) {
                int authVer = readU8(rawIn);
                if (authVer != 1) throw new IOException("Unsupported auth version");
                int ulen = readU8(rawIn);
                readFully(rawIn, ulen);
                int plen = readU8(rawIn);
                readFully(rawIn, plen);
                rawOut.write(new byte[]{0x01, 0x00});
                rawOut.flush();
            }

            int reqVer = readU8(rawIn);
            int cmd = readU8(rawIn);
            readU8(rawIn); // RSV
            int atyp = readU8(rawIn);
            if (reqVer != 5) throw new IOException("Bad request version");
            Address target = readAddress(rawIn, atyp);
            int port = readU16(rawIn);

            if (cmd == 0x01) {
                handleConnect(rawIn, rawOut, target, port);
            } else if (cmd == 0x03) {
                handleUdpAssociate(rawIn, rawOut);
            } else {
                writeReply(rawOut, 0x07, loopback4(), 0);
            }
        } catch (EOFException ignored) {
        } catch (Exception e) {
            if (running) {
                Diagnostics.error("SOCKS client: " + e.getMessage());
                Log.w(TAG, "SOCKS client closed: " + e.getMessage());
            }
        } finally {
            tcpSockets.remove(client);
        }
    }

    private void handleConnect(InputStream clientIn, OutputStream clientOut,
                               Address target, int port) throws IOException {
        InetAddress remoteAddress;
        try {
            remoteAddress = target.resolve(physicalNetwork);
        } catch (IOException e) {
            Diagnostics.TCP_CONNECT_FAIL.incrementAndGet();
            Diagnostics.error("DNS/resolve TCP target: " + e.getMessage());
            writeReply(clientOut, 0x04, loopback4(), 0);
            return;
        }

        Socket remote;
        try {
            if (physicalNetwork != null) {
                // Android 9 creates java.net.Socket file descriptors lazily. Calling
                // VpnService.protect() on a plain new Socket() can therefore return false.
                // A Network-bound SocketFactory materializes the socket and associates it
                // with the real Wi-Fi network before we protect it from the VPN route.
                remote = physicalNetwork.getSocketFactory().createSocket();
            } else {
                remote = new Socket();
                // Force creation of the underlying file descriptor before protect().
                remote.bind(new InetSocketAddress(0));
            }
        } catch (IOException e) {
            Diagnostics.TCP_CONNECT_FAIL.incrementAndGet();
            Diagnostics.error("Create TCP socket: " + e.getMessage());
            writeReply(clientOut, 0x01, loopback4(), 0);
            return;
        }

        if (!vpnService.protect(remote)) {
            Diagnostics.TCP_CONNECT_FAIL.incrementAndGet();
            Diagnostics.error("VpnService.protect(TCP) returned false after socket init");
            remote.close();
            writeReply(clientOut, 0x01, loopback4(), 0);
            return;
        }

        tcpSockets.add(remote);
        try {
            remote.setTcpNoDelay(true);
            remote.connect(new InetSocketAddress(remoteAddress, port), 15_000);
            Diagnostics.TCP_CONNECT_OK.incrementAndGet();
            InetSocketAddress local = (InetSocketAddress) remote.getLocalSocketAddress();
            writeReply(clientOut, 0x00, local.getAddress(), local.getPort());

            InputStream remoteIn = new BufferedInputStream(remote.getInputStream());
            OutputStream remoteOut = new BufferedOutputStream(remote.getOutputStream());

            Thread up = new Thread(() -> relayUpload(clientIn, remoteOut, remote), "noema-up");
            up.setDaemon(true);
            up.start();
            relayDownload(remoteIn, clientOut);
        } catch (IOException e) {
            Diagnostics.TCP_CONNECT_FAIL.incrementAndGet();
            Diagnostics.error("TCP " + remoteAddress.getHostAddress() + ":" + port + " " + e.getMessage());
            Log.d(TAG, "TCP connect failed: " + remoteAddress + ":" + port + " " + e.getMessage());
            try { writeReply(clientOut, 0x05, loopback4(), 0); } catch (Exception ignored) {}
        } finally {
            tcpSockets.remove(remote);
            closeQuietly(remote);
        }
    }

    private void relayUpload(InputStream in, OutputStream out, Socket remote) {
        byte[] buf = new byte[BUF];
        try {
            int n;
            while (running && (n = in.read(buf)) >= 0) {
                if (n == 0) continue;
                out.write(buf, 0, n);
                out.flush();
                TrafficStatsStore.UP.addAndGet(n);
            }
        } catch (IOException ignored) {
        } finally {
            try { remote.shutdownOutput(); } catch (Exception ignored) {}
        }
    }

    private void relayDownload(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[BUF];
        try {
            int n;
            while (running && (n = in.read(buf)) >= 0) {
                if (n == 0) continue;
                try {
                    downloadLimiter.acquire(n);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return;
                }
                out.write(buf, 0, n);
                out.flush();
                TrafficStatsStore.DOWN.addAndGet(n);
            }
        } catch (SocketException ignored) {
        }
    }

    private void handleUdpAssociate(InputStream controlIn, OutputStream controlOut) throws IOException {
        DatagramSocket clientSide = new DatagramSocket(new InetSocketAddress(loopback4(), 0));
        DatagramSocket internetSide = new DatagramSocket();
        if (!vpnService.protect(internetSide)) {
            Diagnostics.error("VpnService.protect(UDP) returned false");
            clientSide.close();
            internetSide.close();
            writeReply(controlOut, 0x01, loopback4(), 0);
            return;
        }
        if (physicalNetwork != null) {
            physicalNetwork.bindSocket(internetSide);
        }
        udpSockets.add(clientSide);
        udpSockets.add(internetSide);
        clientSide.setSoTimeout(0);
        internetSide.setSoTimeout(0);
        writeReply(controlOut, 0x00, loopback4(), clientSide.getLocalPort());
        Diagnostics.UDP_ASSOC.incrementAndGet();

        final InetSocketAddress[] lastClient = new InetSocketAddress[1];

        Thread outbound = new Thread(() -> {
            byte[] buf = new byte[MAX_UDP];
            while (running && !clientSide.isClosed()) {
                try {
                    DatagramPacket packet = new DatagramPacket(buf, buf.length);
                    clientSide.receive(packet);
                    lastClient[0] = new InetSocketAddress(packet.getAddress(), packet.getPort());
                    SocksUdpDatagram d = parseUdp(packet.getData(), packet.getOffset(), packet.getLength());
                    InetAddress dst = d.address.resolve(physicalNetwork);
                    DatagramPacket out = new DatagramPacket(d.payload, d.payload.length, dst, d.port);
                    internetSide.send(out);
                    Diagnostics.UDP_OUT.incrementAndGet();
                    TrafficStatsStore.UP.addAndGet(d.payload.length);
                } catch (Exception e) {
                    if (running && !clientSide.isClosed()) {
                        Diagnostics.error("UDP out: " + e.getMessage());
                        Log.d(TAG, "UDP upload relay ended: " + e.getMessage());
                    }
                    break;
                }
            }
        }, "noema-udp-up");
        outbound.setDaemon(true);
        outbound.start();

        Thread inbound = new Thread(() -> {
            byte[] buf = new byte[MAX_UDP];
            while (running && !internetSide.isClosed()) {
                try {
                    DatagramPacket packet = new DatagramPacket(buf, buf.length);
                    internetSide.receive(packet);
                    Diagnostics.UDP_IN.incrementAndGet();
                    InetSocketAddress clientAddr = lastClient[0];
                    if (clientAddr == null) continue;
                    byte[] wrapped = wrapUdp(packet.getAddress(), packet.getPort(), packet.getData(), packet.getOffset(), packet.getLength());
                    try {
                        downloadLimiter.acquire(packet.getLength());
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        break;
                    }
                    clientSide.send(new DatagramPacket(wrapped, wrapped.length, clientAddr));
                    TrafficStatsStore.DOWN.addAndGet(packet.getLength());
                } catch (Exception e) {
                    if (running && !internetSide.isClosed()) {
                        Diagnostics.error("UDP in: " + e.getMessage());
                        Log.d(TAG, "UDP download relay ended: " + e.getMessage());
                    }
                    break;
                }
            }
        }, "noema-udp-down");
        inbound.setDaemon(true);
        inbound.start();

        try {
            while (running && controlIn.read() != -1) {
                // RFC 1928: the UDP association lives as long as this TCP connection.
            }
        } finally {
            clientSide.close();
            internetSide.close();
            udpSockets.remove(clientSide);
            udpSockets.remove(internetSide);
        }
    }

    private static SocksUdpDatagram parseUdp(byte[] data, int off, int len) throws IOException {
        int p = off;
        if (len < 4 || data[p] != 0 || data[p + 1] != 0) throw new IOException("Bad UDP header");
        if (data[p + 2] != 0) throw new IOException("Fragmented UDP not supported");
        int atyp = data[p + 3] & 0xff;
        p += 4;
        Address address;
        if (atyp == 1) {
            ensure(p + 4 <= off + len);
            address = Address.ofBytes(Arrays.copyOfRange(data, p, p + 4));
            p += 4;
        } else if (atyp == 4) {
            ensure(p + 16 <= off + len);
            address = Address.ofBytes(Arrays.copyOfRange(data, p, p + 16));
            p += 16;
        } else if (atyp == 3) {
            ensure(p + 1 <= off + len);
            int n = data[p++] & 0xff;
            ensure(p + n <= off + len);
            address = Address.ofHost(new String(data, p, n, StandardCharsets.ISO_8859_1));
            p += n;
        } else {
            throw new IOException("Unknown UDP ATYP");
        }
        ensure(p + 2 <= off + len);
        int port = ((data[p] & 0xff) << 8) | (data[p + 1] & 0xff);
        p += 2;
        ensure(p <= off + len);
        byte[] payload = Arrays.copyOfRange(data, p, off + len);
        return new SocksUdpDatagram(address, port, payload);
    }

    private static byte[] wrapUdp(InetAddress address, int port, byte[] data, int off, int len) {
        byte[] addr = address.getAddress();
        int atyp = addr.length == 16 ? 4 : 1;
        byte[] out = new byte[4 + addr.length + 2 + len];
        out[0] = 0; out[1] = 0; out[2] = 0; out[3] = (byte) atyp;
        System.arraycopy(addr, 0, out, 4, addr.length);
        int p = 4 + addr.length;
        out[p++] = (byte) ((port >>> 8) & 0xff);
        out[p++] = (byte) (port & 0xff);
        System.arraycopy(data, off, out, p, len);
        return out;
    }

    private static void ensure(boolean ok) throws IOException {
        if (!ok) throw new IOException("Truncated SOCKS UDP packet");
    }

    private static boolean contains(byte[] a, byte v) {
        for (byte b : a) if (b == v) return true;
        return false;
    }

    private static int readU8(InputStream in) throws IOException {
        int v = in.read();
        if (v < 0) throw new EOFException();
        return v;
    }

    private static int readU16(InputStream in) throws IOException {
        return (readU8(in) << 8) | readU8(in);
    }

    private static byte[] readFully(InputStream in, int n) throws IOException {
        byte[] out = new byte[n];
        int p = 0;
        while (p < n) {
            int r = in.read(out, p, n - p);
            if (r < 0) throw new EOFException();
            p += r;
        }
        return out;
    }

    private static Address readAddress(InputStream in, int atyp) throws IOException {
        if (atyp == 1) return Address.ofBytes(readFully(in, 4));
        if (atyp == 4) return Address.ofBytes(readFully(in, 16));
        if (atyp == 3) {
            int n = readU8(in);
            return Address.ofHost(new String(readFully(in, n), StandardCharsets.ISO_8859_1));
        }
        throw new IOException("Unknown ATYP " + atyp);
    }

    private static void writeReply(OutputStream out, int rep, InetAddress addr, int port) throws IOException {
        byte[] a = addr == null ? new byte[]{0,0,0,0} : addr.getAddress();
        int atyp = a.length == 16 ? 4 : 1;
        out.write(5);
        out.write(rep);
        out.write(0);
        out.write(atyp);
        out.write(a);
        out.write((port >>> 8) & 0xff);
        out.write(port & 0xff);
        out.flush();
    }

    @Override public void close() {
        running = false;
        try { if (server != null) server.close(); } catch (IOException ignored) {}
        for (Socket s : tcpSockets) closeQuietly(s);
        for (DatagramSocket s : udpSockets) s.close();
        tcpSockets.clear();
        udpSockets.clear();
        pool.shutdownNow();
    }

    private static InetAddress loopback4() {
        try { return InetAddress.getByName("127.0.0.1"); }
        catch (Exception e) { return InetAddress.getLoopbackAddress(); }
    }

    private static void closeQuietly(Socket s) {
        try { s.close(); } catch (Exception ignored) {}
    }

    private static final class Address {
        final String host;
        final byte[] literal;
        private Address(String host, byte[] literal) { this.host = host; this.literal = literal; }
        static Address ofHost(String host) { return new Address(host, null); }
        static Address ofBytes(byte[] bytes) { return new Address(null, bytes); }
        InetAddress resolve(Network network) throws IOException {
            if (literal != null) return InetAddress.getByAddress(literal);
            if (network != null) return network.getByName(host);
            return InetAddress.getByName(host);
        }
    }

    private static final class SocksUdpDatagram {
        final Address address;
        final int port;
        final byte[] payload;
        SocksUdpDatagram(Address address, int port, byte[] payload) {
            this.address = address; this.port = port; this.payload = payload;
        }
    }
}
