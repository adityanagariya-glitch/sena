"""Circuit breaker: prevent cascading failures from service outages.

State machine: CLOSED (normal) → OPEN (failing) → HALF_OPEN (testing) → CLOSED

Tracks failures per service and temporarily stops calls when threshold exceeded.
"""
import logging
import time
from typing import Dict, Optional
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"          # Normal operation
    OPEN = "open"              # Too many failures, reject calls
    HALF_OPEN = "half_open"    # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5          # Failures before opening
    recovery_timeout: float = 60        # Seconds before attempting recovery
    half_open_max_calls: int = 1        # Max calls in HALF_OPEN state


@dataclass
class CircuitBreakerState:
    """Mutable state for a circuit breaker."""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    last_state_change: datetime = field(default_factory=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"CircuitBreakerState({self.state.value}, "
            f"failures={self.failure_count}, successes={self.success_count})"
        )


# Per-service circuit breakers: {service_name: CircuitBreakerState}
_circuit_breakers: Dict[str, CircuitBreakerState] = {}


def get_circuit_breaker(
    service_name: str, config: Optional[CircuitBreakerConfig] = None
) -> CircuitBreakerState:
    """Get or create circuit breaker for service.

    Args:
        service_name: Service identifier (staff, policy)
        config: Configuration (used only on first call)

    Returns:
        CircuitBreakerState
    """
    if service_name not in _circuit_breakers:
        _circuit_breakers[service_name] = CircuitBreakerState()
    return _circuit_breakers[service_name]


async def record_success(service_name: str) -> None:
    """Record successful call to service.

    Args:
        service_name: Service name
    """
    cb = get_circuit_breaker(service_name)
    cb.success_count += 1
    cb.failure_count = 0

    # If in HALF_OPEN, transition to CLOSED
    if cb.state == CircuitState.HALF_OPEN:
        cb.state = CircuitState.CLOSED
        cb.last_state_change = datetime.utcnow()
        logger.info(f"Circuit breaker for {service_name} CLOSED (recovered)")


async def record_failure(
    service_name: str, config: Optional[CircuitBreakerConfig] = None
) -> None:
    """Record failed call to service.

    Args:
        service_name: Service name
        config: Configuration with failure_threshold
    """
    config = config or CircuitBreakerConfig()
    cb = get_circuit_breaker(service_name, config)
    cb.failure_count += 1
    cb.last_failure_time = time.time()

    # Open circuit if threshold exceeded
    if cb.failure_count >= config.failure_threshold and cb.state == CircuitState.CLOSED:
        cb.state = CircuitState.OPEN
        cb.last_state_change = datetime.utcnow()
        logger.warning(
            f"Circuit breaker for {service_name} OPEN "
            f"({cb.failure_count} failures)"
        )


async def can_call(
    service_name: str, config: Optional[CircuitBreakerConfig] = None
) -> bool:
    """Check if call to service is allowed.

    Returns True if:
      - CLOSED (normal)
      - HALF_OPEN (testing recovery)

    Returns False if:
      - OPEN and timeout hasn't elapsed

    Args:
        service_name: Service name
        config: Configuration with recovery_timeout

    Returns:
        True if call is allowed
    """
    config = config or CircuitBreakerConfig()
    cb = get_circuit_breaker(service_name, config)

    if cb.state == CircuitState.CLOSED:
        return True

    if cb.state == CircuitState.OPEN:
        # Check if recovery timeout elapsed
        if cb.last_failure_time and (
            time.time() - cb.last_failure_time >= config.recovery_timeout
        ):
            cb.state = CircuitState.HALF_OPEN
            cb.success_count = 0
            cb.last_state_change = datetime.utcnow()
            logger.info(f"Circuit breaker for {service_name} HALF_OPEN (testing)")
            return True
        return False

    if cb.state == CircuitState.HALF_OPEN:
        # Allow limited calls in HALF_OPEN
        return cb.success_count < config.half_open_max_calls

    return False


async def get_status(service_name: str) -> Dict:
    """Get circuit breaker status for service.

    Args:
        service_name: Service name

    Returns:
        Status dict (state, failures, successes, last_change)
    """
    cb = get_circuit_breaker(service_name)
    return {
        "service": service_name,
        "state": cb.state.value,
        "failures": cb.failure_count,
        "successes": cb.success_count,
        "last_state_change": cb.last_state_change.isoformat(),
    }
