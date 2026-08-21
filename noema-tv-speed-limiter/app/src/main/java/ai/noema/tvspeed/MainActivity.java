package ai.noema.tvspeed;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.VpnService;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.Locale;

public final class MainActivity extends Activity {
    private static final int VPN_REQUEST = 4102;
    private int pendingMbit;
    private TextView status;
    private TextView stats;
    private final Handler handler = new Handler(Looper.getMainLooper());

    private final Runnable ticker = new Runnable() {
        @Override public void run() {
            refresh();
            handler.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        setContentView(buildUi());
    }

    @Override protected void onResume() {
        super.onResume();
        handler.removeCallbacks(ticker);
        ticker.run();
    }

    @Override protected void onPause() {
        handler.removeCallbacks(ticker);
        super.onPause();
    }

    private View buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(dp(48), dp(28), dp(48), dp(28));
        root.setBackgroundColor(Color.rgb(10, 13, 18));

        TextView title = text("NOEMA TV Speed Limiter", 34, true);
        title.setGravity(Gravity.CENTER);
        root.addView(title, lpMatchWrap());

        TextView sub = text("Travel bandwidth profiles for Android TV", 18, false);
        sub.setTextColor(Color.rgb(170, 184, 201));
        sub.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams subLp = lpMatchWrap();
        subLp.bottomMargin = dp(22);
        root.addView(sub, subLp);

        status = text("", 22, true);
        status.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams stLp = lpMatchWrap();
        stLp.bottomMargin = dp(10);
        root.addView(status, stLp);

        stats = text("", 17, false);
        stats.setTextColor(Color.rgb(170, 184, 201));
        stats.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams statsLp = lpMatchWrap();
        statsLp.bottomMargin = dp(26);
        root.addView(stats, statsLp);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER);
        addProfileButton(row, "2 Mbit/s\nSaver", 2);
        addProfileButton(row, "4 Mbit/s\nBalanced", 4);
        addProfileButton(row, "6 Mbit/s\nComfort", 6);
        addProfileButton(row, "Full Speed\nHome", 0);
        root.addView(row, lpMatchWrap());

        Button debug = new Button(this);
        debug.setText("Diagnostics");
        debug.setTextSize(16);
        debug.setAllCaps(false);
        debug.setTextColor(Color.WHITE);
        debug.setFocusable(true);
        debug.setBackground(buttonBg(false));
        debug.setOnFocusChangeListener((v, focused) -> v.setBackground(buttonBg(focused)));
        debug.setOnClickListener(v -> showDiagnostics());
        LinearLayout.LayoutParams debugLp = new LinearLayout.LayoutParams(dp(220), dp(64));
        debugLp.topMargin = dp(22);
        root.addView(debug, debugLp);

        TextView note = text("Limits aggregate download traffic on this device. Upload remains unrestricted.", 14, false);
        note.setTextColor(Color.rgb(130, 145, 160));
        note.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams noteLp = lpMatchWrap();
        noteLp.topMargin = dp(16);
        root.addView(note, noteLp);

        return root;
    }

    private void addProfileButton(LinearLayout row, String label, int mbit) {
        Button b = new Button(this);
        b.setText(label);
        b.setTextSize(18);
        b.setAllCaps(false);
        b.setTextColor(Color.WHITE);
        b.setGravity(Gravity.CENTER);
        b.setPadding(dp(16), dp(16), dp(16), dp(16));
        b.setFocusable(true);
        b.setFocusableInTouchMode(true);
        b.setBackground(buttonBg(false));
        b.setOnFocusChangeListener((v, focused) -> {
            v.setBackground(buttonBg(focused));
            v.setScaleX(focused ? 1.06f : 1.0f);
            v.setScaleY(focused ? 1.06f : 1.0f);
        });
        b.setOnClickListener(v -> chooseProfile(mbit));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(170), dp(95));
        lp.setMargins(dp(6), 0, dp(6), 0);
        row.addView(b, lp);
    }

    private GradientDrawable buttonBg(boolean focused) {
        GradientDrawable g = new GradientDrawable();
        g.setCornerRadius(dp(14));
        g.setColor(focused ? Color.rgb(38, 111, 210) : Color.rgb(31, 38, 49));
        g.setStroke(dp(2), focused ? Color.WHITE : Color.rgb(70, 83, 100));
        return g;
    }

    private void chooseProfile(int mbit) {
        if (mbit == 0) {
            sendProfile(0);
            return;
        }
        Intent prepare = VpnService.prepare(this);
        if (prepare != null) {
            pendingMbit = mbit;
            startActivityForResult(prepare, VPN_REQUEST);
        } else {
            sendProfile(mbit);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == VPN_REQUEST && resultCode == RESULT_OK && pendingMbit > 0) {
            sendProfile(pendingMbit);
        }
    }

    private void sendProfile(int mbit) {
        Intent i = new Intent(this, SpeedVpnService.class)
                .setAction(SpeedVpnService.ACTION_SET_PROFILE)
                .putExtra(SpeedVpnService.EXTRA_MBIT, mbit);
        if (mbit == 0) {
            startService(i);
        } else if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(i);
        } else {
            startService(i);
        }
        handler.postDelayed(this::refresh, 250);
    }

    private void showDiagnostics() {
        TextView body = new TextView(this);
        body.setText(Diagnostics.snapshot());
        body.setTextSize(16);
        body.setTextColor(Color.WHITE);
        body.setPadding(dp(24), dp(14), dp(24), dp(14));
        body.setTextIsSelectable(true);
        new AlertDialog.Builder(this)
                .setTitle("NOEMA Diagnostics")
                .setView(body)
                .setPositiveButton("Close", null)
                .show();
    }

    private void refresh() {
        SharedPreferences p = getSharedPreferences(SpeedVpnService.PREFS, MODE_PRIVATE);
        int mbit = SpeedVpnService.isRunning() ? SpeedVpnService.getActiveMbit() : p.getInt(SpeedVpnService.PREF_ACTIVE_MBIT, 0);
        if (!SpeedVpnService.isRunning()) mbit = 0;
        status.setText(mbit > 0 ? "ACTIVE: " + mbit + " Mbit/s download" : "FULL SPEED");
        status.setTextColor(mbit > 0 ? Color.rgb(92, 186, 255) : Color.rgb(122, 225, 157));
        stats.setText(String.format(Locale.US,
                "Session: %.2f GB down  |  %.2f GB up",
                TrafficStatsStore.DOWN.get() / 1_000_000_000.0,
                TrafficStatsStore.UP.get() / 1_000_000_000.0));
    }

    private TextView text(String s, int sp, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(Color.WHITE);
        if (bold) t.setTypeface(t.getTypeface(), android.graphics.Typeface.BOLD);
        return t;
    }

    private LinearLayout.LayoutParams lpMatchWrap() {
        return new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
