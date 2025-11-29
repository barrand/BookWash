import 'dart:collection';
import 'dart:async';

/// Simple sliding-window rate limiter (requests per minute) with optional jitter.
class SimpleRateLimiter {
  final int maxRequestsPerMinute;
  final Duration window;
  final bool enableJitter;
  final Queue<DateTime> _timestamps = Queue<DateTime>();

  SimpleRateLimiter({
    required this.maxRequestsPerMinute,
    this.window = const Duration(minutes: 1),
    this.enableJitter = true,
  });

  /// Acquire a slot before making a request.
  /// Waits until a slot is available if the limit has been reached.
  Future<void> acquire() async {
    final now = DateTime.now();
    // Drop timestamps older than the window
    while (_timestamps.isNotEmpty &&
        now.difference(_timestamps.first) > window) {
      _timestamps.removeFirst();
    }
    if (_timestamps.length < maxRequestsPerMinute) {
      _timestamps.add(now);
      return;
    }
    // Need to wait until earliest timestamp exits window
    final earliest = _timestamps.first;
    final wait = earliest.add(window).difference(now);
    final adjusted = enableJitter ? _addJitter(wait) : wait;
    if (adjusted > Duration.zero) {
      await Future.delayed(adjusted);
    }
    // Retry after waiting
    await acquire();
  }

  Duration _addJitter(Duration base) {
    if (base <= Duration.zero) return Duration.zero;
    final millis = base.inMilliseconds;
    final jitterRange = (millis * 0.1).toInt(); // ±10%
    final delta =
        (DateTime.now().microsecondsSinceEpoch % (jitterRange * 200)) -
        jitterRange * 100;
    return Duration(
      milliseconds: (millis + delta ~/ 100).clamp(0, millis + jitterRange),
    );
  }
}
