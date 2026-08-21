import time
from typing import Dict, Tuple
import logging

logger = logging.getLogger("server.rate_limiter")

class SecurityRateLimiter:
    """
    In-memory rate limiter to block brute-force authentication attacks.
    Tracks failed attempts per IP address.
    """
    def __init__(self, max_failures: int = 5, lockout_seconds: int = 300):
        self.max_failures = max_failures
        self.lockout_seconds = lockout_seconds
        # ip -> (failure_count, lockout_until_timestamp)
        self._ip_failures: Dict[str, Tuple[int, float]] = {}

    def is_ip_blocked(self, ip_address: str) -> bool:
        now = time.time()
        if ip_address in self._ip_failures:
            count, lockout_until = self._ip_failures[ip_address]
            if now < lockout_until:
                return True
            elif now >= lockout_until and lockout_until > 0:
                # Lockout expired, reset counter
                del self._ip_failures[ip_address]
        return False

    def record_failure(self, ip_address: str):
        now = time.time()
        count, lockout_until = self._ip_failures.get(ip_address, (0, 0.0))
        count += 1
        
        if count >= self.max_failures:
            lockout_until = now + self.lockout_seconds
            logger.warning(
                f"[SECURITY ALERT] IP {ip_address} blocked for {self.lockout_seconds}s "
                f"after {count} failed auth attempts."
            )
        
        self._ip_failures[ip_address] = (count, lockout_until)

    def record_success(self, ip_address: str):
        """Reset failures on successful authentication."""
        if ip_address in self._ip_failures:
            del self._ip_failures[ip_address]

rate_limiter = SecurityRateLimiter()
