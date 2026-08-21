package ai.noema.tvspeed;

/**
 * Process-wide download shaper. Every relay reserves a slice of the same
 * timeline so parallel TCP/UDP flows share one aggregate bandwidth ceiling.
 */
final class RateLimiter {
    private final Object lock = new Object();
    private volatile long bitsPerSecond;
    private long nextSlotNs;

    RateLimiter(long bitsPerSecond) {
        setBitsPerSecond(bitsPerSecond);
    }

    void setBitsPerSecond(long value) {
        bitsPerSecond = Math.max(0L, value);
        synchronized (lock) {
            nextSlotNs = System.nanoTime();
        }
    }

    long getBitsPerSecond() {
        return bitsPerSecond;
    }

    void acquire(int byteCount) throws InterruptedException {
        final long bps = bitsPerSecond;
        if (bps <= 0 || byteCount <= 0) return;

        final long now = System.nanoTime();
        final long durationNs = Math.max(1L, (long) Math.ceil((byteCount * 8.0d * 1_000_000_000.0d) / bps));
        final long waitNs;
        synchronized (lock) {
            long start = Math.max(now, nextSlotNs);
            waitNs = Math.max(0L, start - now);
            nextSlotNs = start + durationNs;
        }

        if (waitNs > 0) {
            long ms = waitNs / 1_000_000L;
            int ns = (int) (waitNs % 1_000_000L);
            Thread.sleep(ms, ns);
        }
    }
}
