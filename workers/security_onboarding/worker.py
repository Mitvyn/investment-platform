from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from workers.market.client import MarketDataError
from workers.sec.collector import SecCollectorError
from workers.sec.storage import EvidenceStorageError
from workers.security_registry.client import SecurityRegistryError

EXCHANGE_FAMILIES = {
    "NASDAQ": "NASDAQ",
    "NMS": "NASDAQ",
    "NGM": "NASDAQ",
    "NCM": "NASDAQ",
    "NASDAQGS": "NASDAQ",
    "NASDAQGM": "NASDAQ",
    "NASDAQCM": "NASDAQ",
    "NYSE": "NYSE",
    "NYQ": "NYSE",
    "NEWYORKSTOCKEXCHANGE": "NYSE",
    "NYSEAMERICAN": "NYSE_AMERICAN",
    "NYSEMKT": "NYSE_AMERICAN",
    "ASE": "NYSE_AMERICAN",
    "AMEX": "NYSE_AMERICAN",
    "NYSEARCA": "NYSE_ARCA",
    "ARCA": "NYSE_ARCA",
    "PCX": "NYSE_ARCA",
    "CBOEBZX": "CBOE_BZX",
    "BATS": "CBOE_BZX",
}


def _exchange_family(value: object) -> str | None:
    normalized = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    return EXCHANGE_FAMILIES.get(normalized)


def _market_identity_matches(security: Any, market: Any) -> bool:
    security_exchange = _exchange_family(security.primary_listing_exchange)
    market_exchange = _exchange_family(market.exchange)
    return (
        str(market.currency).strip().upper() == "USD"
        and security_exchange is not None
        and security_exchange == market_exchange
    )


@dataclass(frozen=True, slots=True)
class SecurityJobClaim:
    job_id: str
    operator_id: str
    ticker: str
    attempt_id: str
    attempt_number: int
    lease_token: str


class JobStore(Protocol):
    def claim_next(self, worker_id: str) -> SecurityJobClaim | None: ...

    def complete(
        self,
        claim: SecurityJobClaim,
        *,
        security_id: str,
        market_series_id: str,
    ) -> None: ...

    def fail(
        self,
        claim: SecurityJobClaim,
        *,
        stage: str,
        error_code: str,
        retryable: bool,
    ) -> None: ...


class RegistryClient(Protocol):
    def resolve(self, ticker: str, *, operator_id: str) -> Any: ...


class RegistryStore(Protocol):
    def persist(self, security: Any) -> None: ...


class MarketClient(Protocol):
    def fetch_quote(
        self,
        ticker: str,
        *,
        operator_id: str,
        security_id: str,
    ) -> Any: ...


class MarketStore(Protocol):
    def persist(self, market: Any) -> None: ...


class SecurityOnboardingWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        jobs: JobStore,
        registry: RegistryClient,
        registry_store: RegistryStore,
        market: MarketClient,
        market_store: MarketStore,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        self.worker_id = worker_id.strip()
        self.jobs = jobs
        self.registry = registry
        self.registry_store = registry_store
        self.market = market
        self.market_store = market_store

    def _fail_unexpected(self, claim: SecurityJobClaim) -> bool:
        self.jobs.fail(
            claim,
            stage="worker",
            error_code="unexpected_failure",
            retryable=True,
        )
        return True

    def run_once(self) -> bool:
        claim = self.jobs.claim_next(self.worker_id)
        if claim is None:
            return False

        try:
            security = self.registry.resolve(
                claim.ticker,
                operator_id=claim.operator_id,
            )
        except SecCollectorError:
            self.jobs.fail(
                claim,
                stage="security_registry",
                error_code="source_unavailable",
                retryable=True,
            )
            return True
        except SecurityRegistryError:
            self.jobs.fail(
                claim,
                stage="security_registry",
                error_code="identity_not_resolved",
                retryable=False,
            )
            return True
        except Exception:
            return self._fail_unexpected(claim)
        try:
            self.registry_store.persist(security)
        except EvidenceStorageError:
            self.jobs.fail(
                claim,
                stage="persistence",
                error_code="security_persistence_failed",
                retryable=True,
            )
            return True
        except Exception:
            return self._fail_unexpected(claim)
        try:
            market = self.market.fetch_quote(
                claim.ticker,
                operator_id=claim.operator_id,
                security_id=security.security_id,
            )
        except MarketDataError:
            self.jobs.fail(
                claim,
                stage="market_fetch",
                error_code="provider_unavailable",
                retryable=True,
            )
            return True
        except Exception:
            return self._fail_unexpected(claim)
        if not _market_identity_matches(security, market):
            self.jobs.fail(
                claim,
                stage="market_fetch",
                error_code="market_identity_mismatch",
                retryable=False,
            )
            return True
        try:
            self.market_store.persist(market)
        except EvidenceStorageError:
            self.jobs.fail(
                claim,
                stage="persistence",
                error_code="market_persistence_failed",
                retryable=True,
            )
            return True
        except Exception:
            return self._fail_unexpected(claim)
        if market.series_id is None:
            self.jobs.fail(
                claim,
                stage="persistence",
                error_code="market_series_missing",
                retryable=True,
            )
            return True
        self.jobs.complete(
            claim,
            security_id=security.security_id,
            market_series_id=market.series_id,
        )
        return True
