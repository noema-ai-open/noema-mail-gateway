package ai.noema.tvspeed;

/**
 * Process-wide token-bucket download shaper.
 *
 * The previous timeline-reservation shaper allowed many concurrent streaming
 * connections to reserve seconds of future bandwidth at once. On Android TV
 * that can starve small control/DNS/media requests and make apps report that
 * the network is offline even though the tunnel itself is alive.
 *
 * This implementation keeps a bounded burst (about 500 ms) and refills tokens
 * from real elapsed time. No caller can reserve bandwidth far into the future.
 */
final class RateLimiter {
    private static final long NS_PER_SECOND = 1_000_000_000L;
    private static final double BURST_SECONDS = 0.5d;
    private static final double MIN_BURST_BYTES = 16 * 1024.0d;

    private final Object lock = new Object();
    private volatile long bitsPerSecond;
    private double tokensBytes;
    private double capacityBytes;
    private long lastRefillNs;

    RateLimiter(long bitsPerSecond) {
        setBitsPerSecond(bitsPerSecond);
    }

    void setBitsPerSecond(long value) {
        synchronized (lock) {
            bitsPerSecond = Math.max(0L, value);
            lastRefillNs = System.nanoTime();
            if (bitsPerSecond <= 0L) {
                capacityBytes = Double.MAX_VALUE;
                tokensBytes = Double.MAX_VALUE;
            } else {
                double bytesPerSecond = bitsPerSecond / 8.0d;
                capacityBytes = Math.max(MIN_BURST_BYTES, bytesPerSecond * BURST_SECONDS);
                tokensBytes = capacityBytes;
            }
            lock.notifyAll();
        }
    }

    long getBitsPerSecond() {
        return bitsPerSecond;
    }

    void acquire(int byteCount) throws InterruptedException {
        if (byteCount <= 0) return;

        synchronized (lock) {
            while (true) {
                final long bps = bitsPerSecond;
                if (bps <= 0L) return;

                refillLocked(bps);

                // Never require more tokens than the bucket can hold. Large reads
                // are effectively paid for in bounded chunks instead of creating a
                // long reservation queue that starves unrelated connections.
                double required = Math.min((double) byteCount, capacityBytes);
                if (tokensBytes >= required) {
                    tokensBytes -= required;
                    return;
                }

                double missingBytes = required - tokensBytes;
                double bytesPerSecond = bps / 8.0d;
                long waitNs = Math.max(1L,
                        (long) Math.ceil((missingBytes / bytesPerSecond) * NS_PER_SECOND));

                long waitMs = Math.max(1L, waitNs / 1_000_000L);
                lock.wait(Math.min(waitMs, 100L));
            }
        }
    }

    private void refillLocked(long bps) {
        long now = System.nanoTime();
        long elapsedNs = Math.max(0L, now - lastRefillNs);
        lastRefillNs = now;
        if (elapsedNs == 0L) return;

        double bytesPerSecond = bps / 8.0d;
        double refill = bytesPerSecond * (elapsedNs / (double) NS_PER_SECOND);
        tokensBytes = Math.min(capacityBytes, tokensBytes + refill);
    }
}
