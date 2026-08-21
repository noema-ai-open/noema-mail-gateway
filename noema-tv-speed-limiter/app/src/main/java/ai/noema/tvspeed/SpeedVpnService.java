package ai.noema.tvspeed;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.VpnService;
import android.os.Build;
import android.os.ParcelFileDescriptor;
import android.util.Log;

import com.wgtunnel.hevtunnel.HevTunnelConfig;
import com.wgtunnel.hevtunnel.TProxyService;

import java.io.File;
import java.io.IOException;

public final class SpeedVpnService extends VpnService {
    public static final String ACTION_SET_PROFILE = "ai.noema.tvspeed.SET_PROFILE";
    public static final String EXTRA_MBIT = "mbit";
    public static final String PREFS = "noema_speed";
    public static final String PREF_ACTIVE_MBIT = "active_mbit";

    private static final String TAG = "NoemaSpeedVpn";
    private static final String CHANNEL_ID = "noema_speed_channel";
    private static final int NOTIFICATION_ID = 7312;
    private static final int SOCKS_PORT = 10808;
    private static final int MTU = 1500;
    private static final String IPV4 = "198.18.0.1";
    private static final String IPV6 = "fd00::1";

    private static volatile boolean running;
    private static volatile int activeMbit;
    private static final RateLimiter DOWNLOAD_LIMITER = new RateLimiter(0);

    private ParcelFileDescriptor tunFd;
    private LocalSocksServer socksServer;
    private Thread hevStartThread;

    public static boolean isRunning() { return running; }
    public static int getActiveMbit() { return activeMbit; }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || !ACTION_SET_PROFILE.equals(intent.getAction())) {
            return START_NOT_STICKY;
        }

        int mbit = Math.max(0, intent.getIntExtra(EXTRA_MBIT, 0));
        if (mbit == 0) {
            stopLimiter();
            stopSelf();
            return START_NOT_STICKY;
        }

        activeMbit = mbit;
        DOWNLOAD_LIMITER.setBitsPerSecond(mbit * 1_000_000L);
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putInt(PREF_ACTIVE_MBIT, mbit).apply();

        if (!running) {
            try {
                startLimiter();
            } catch (Exception e) {
                Log.e(TAG, "Failed to start limiter", e);
                stopLimiter();
                stopSelf();
            }
        } else {
            startForeground(NOTIFICATION_ID, buildNotification());
        }
        return START_STICKY;
    }

    private synchronized void startLimiter() throws IOException {
        if (running) return;
        TrafficStatsStore.resetSession();
        startForeground(NOTIFICATION_ID, buildNotification());

        socksServer = new LocalSocksServer(this, DOWNLOAD_LIMITER, SOCKS_PORT);
        socksServer.start();

        Builder builder = new Builder()
                .setSession("NOEMA TV Speed Limiter")
                .setMtu(MTU)
                .setBlocking(true)
                .addAddress(IPV4, 32)
                .addAddress(IPV6, 128)
                .addRoute("0.0.0.0", 0)
                .addRoute("::", 0)
                .addDnsServer("1.1.1.1")
                .addDnsServer("2606:4700:4700::1111");

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            builder.setMetered(true);
        }

        tunFd = builder.establish();
        if (tunFd == null) throw new IOException("Android did not establish VPN TUN");

        HevTunnelConfig config = new HevTunnelConfig(
                MTU,
                IPV4,
                IPV6,
                "127.0.0.1",
                socksServer.getPort(),
                "",
                ""
        );
        File configFile = TProxyService.INSTANCE.createHevTunnelConfig(config, getCacheDir());
        int fd = tunFd.getFd();

        hevStartThread = new Thread(() -> {
            try {
                boolean ok = TProxyService.TProxyStartService(configFile.getAbsolutePath(), fd);
                if (!ok) Log.e(TAG, "HEV tunnel returned failure");
            } catch (Throwable t) {
                Log.e(TAG, "HEV tunnel crashed", t);
            }
        }, "noema-hev");
        hevStartThread.setDaemon(true);
        hevStartThread.start();

        running = true;
    }

    private synchronized void stopLimiter() {
        running = false;
        activeMbit = 0;
        DOWNLOAD_LIMITER.setBitsPerSecond(0);
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putInt(PREF_ACTIVE_MBIT, 0).apply();

        try { TProxyService.TProxyStopService(); } catch (Throwable ignored) {}
        if (socksServer != null) {
            try { socksServer.close(); } catch (Exception ignored) {}
            socksServer = null;
        }
        if (tunFd != null) {
            try { tunFd.close(); } catch (IOException ignored) {}
            tunFd = null;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) stopForeground(STOP_FOREGROUND_REMOVE);
        else stopForeground(true);
    }

    @Override
    public void onDestroy() {
        stopLimiter();
        super.onDestroy();
    }

    @Override
    public void onRevoke() {
        stopLimiter();
        stopSelf();
        super.onRevoke();
    }

    private Notification buildNotification() {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(
                this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0)
        );
        String text = activeMbit > 0 ? "Download limited to " + activeMbit + " Mbit/s" : "Full speed";
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        return b.setSmallIcon(android.R.drawable.stat_sys_download_done)
                .setContentTitle("NOEMA TV Speed Limiter")
                .setContentText(text)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = getSystemService(NotificationManager.class);
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL_ID,
                    "NOEMA Speed Limiter",
                    NotificationManager.IMPORTANCE_LOW
            );
            ch.setDescription("Shows when bandwidth limiting is active");
            nm.createNotificationChannel(ch);
        }
    }
}
