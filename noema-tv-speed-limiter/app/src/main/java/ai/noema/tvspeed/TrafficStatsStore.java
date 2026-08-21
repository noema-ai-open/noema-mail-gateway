package ai.noema.tvspeed;

import java.util.concurrent.atomic.AtomicLong;

final class TrafficStatsStore {
    static final AtomicLong DOWN = new AtomicLong();
    static final AtomicLong UP = new AtomicLong();

    private TrafficStatsStore() {}

    static void resetSession() {
        DOWN.set(0L);
        UP.set(0L);
    }
}
