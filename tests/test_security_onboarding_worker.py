from __future__ import annotations

import unittest
from dataclasses import dataclass

from workers.security_onboarding.worker import (
    SecurityJobClaim,
    SecurityOnboardingWorker,
)
from workers.market.client import MarketDataError
from workers.sec.storage import EvidenceStorageError
from workers.sec.collector import SecCollectorError
from workers.security_registry.client import SecurityRegistryError


@dataclass(frozen=True)
class SecurityFake:
    operator_id: str
    security_id: str
    ticker: str
    primary_listing_exchange: str = "Nasdaq"


@dataclass(frozen=True)
class MarketFake:
    series_id: str | None
    exchange: str = "NMS"
    currency: str = "USD"


class JobStoreFake:
    def __init__(self, claim: SecurityJobClaim) -> None:
        self.claim = claim
        self.completed: list[tuple[SecurityJobClaim, str, str]] = []
        self.failed: list[tuple[SecurityJobClaim, str, str, bool]] = []

    def claim_next(self, worker_id: str) -> SecurityJobClaim | None:
        self.worker_id = worker_id
        return self.claim

    def complete(
        self,
        claim: SecurityJobClaim,
        *,
        security_id: str,
        market_series_id: str,
    ) -> None:
        self.completed.append((claim, security_id, market_series_id))

    def fail(
        self,
        claim: SecurityJobClaim,
        *,
        stage: str,
        error_code: str,
        retryable: bool,
    ) -> None:
        self.failed.append((claim, stage, error_code, retryable))


class RegistryClientFake:
    def resolve(self, ticker: str, *, operator_id: str) -> SecurityFake:
        self.request = (ticker, operator_id)
        return SecurityFake(
            operator_id=operator_id,
            security_id="22222222-2222-4222-8222-222222222222",
            ticker=ticker,
        )


class RegistryStoreFake:
    def persist(self, security: SecurityFake) -> None:
        self.persisted = security


class FailingRegistryStoreFake:
    def persist(self, security: SecurityFake) -> None:
        raise EvidenceStorageError("could not reach evidence store")


class MarketClientFake:
    def fetch_quote(
        self,
        ticker: str,
        *,
        operator_id: str,
        security_id: str,
    ) -> MarketFake:
        self.request = (ticker, operator_id, security_id)
        return MarketFake(series_id="33333333-3333-4333-8333-333333333333")


class MarketStoreFake:
    def persist(self, market: MarketFake) -> None:
        self.persisted = market


class MissingSeriesMarketFake:
    def fetch_quote(
        self,
        ticker: str,
        *,
        operator_id: str,
        security_id: str,
    ) -> MarketFake:
        return MarketFake(series_id=None)


class MismatchedMarketIdentityFake:
    def fetch_quote(
        self,
        ticker: str,
        *,
        operator_id: str,
        security_id: str,
    ) -> MarketFake:
        return MarketFake(
            series_id="33333333-3333-4333-8333-333333333333",
            exchange="NYQ",
            currency="USD",
        )


class NonUsdMarketIdentityFake:
    def fetch_quote(
        self,
        ticker: str,
        *,
        operator_id: str,
        security_id: str,
    ) -> MarketFake:
        return MarketFake(
            series_id="33333333-3333-4333-8333-333333333333",
            exchange="NMS",
            currency="EUR",
        )


class OtcRegistryClientFake:
    def resolve(self, ticker: str, *, operator_id: str) -> SecurityFake:
        return SecurityFake(
            operator_id=operator_id,
            security_id="22222222-2222-4222-8222-222222222222",
            ticker=ticker,
            primary_listing_exchange="OTC",
        )


class OtcMarketIdentityFake:
    def fetch_quote(
        self,
        ticker: str,
        *,
        operator_id: str,
        security_id: str,
    ) -> MarketFake:
        return MarketFake(
            series_id="33333333-3333-4333-8333-333333333333",
            exchange="OTC",
            currency="USD",
        )


class UnavailableMarketFake:
    def fetch_quote(
        self,
        ticker: str,
        *,
        operator_id: str,
        security_id: str,
    ) -> MarketFake:
        raise MarketDataError("could not read Yahoo Finance history")


class MissingTickerRegistryFake:
    def resolve(self, ticker: str, *, operator_id: str) -> SecurityFake:
        raise SecurityRegistryError(
            "SEC security registry must contain exactly one ticker match"
        )


class UnavailableRegistryFake:
    def resolve(self, ticker: str, *, operator_id: str) -> SecurityFake:
        raise SecCollectorError("could not reach SEC")


class CrashingRegistryFake:
    def resolve(self, ticker: str, *, operator_id: str) -> SecurityFake:
        raise RuntimeError("unexpected implementation failure")


class SecurityOnboardingWorkerTests(unittest.TestCase):
    def test_claimed_job_registers_security_and_market_series_before_completion(
        self,
    ) -> None:
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="CRSP",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )
        jobs = JobStoreFake(claim)
        registry = RegistryClientFake()
        registry_store = RegistryStoreFake()
        market = MarketClientFake()
        market_store = MarketStoreFake()
        worker = SecurityOnboardingWorker(
            worker_id="iro-worker-1",
            jobs=jobs,
            registry=registry,
            registry_store=registry_store,
            market=market,
            market_store=market_store,
        )

        processed = worker.run_once()

        self.assertTrue(processed)
        self.assertEqual(jobs.worker_id, "iro-worker-1")
        self.assertEqual(registry.request, ("CRSP", claim.operator_id))
        self.assertEqual(
            market.request,
            ("CRSP", claim.operator_id, registry_store.persisted.security_id),
        )
        self.assertEqual(
            jobs.completed,
            [
                (
                    claim,
                    "22222222-2222-4222-8222-222222222222",
                    "33333333-3333-4333-8333-333333333333",
                )
            ],
        )

    def test_unknown_ticker_fails_without_market_collection(self) -> None:
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="NOPE",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )
        jobs = JobStoreFake(claim)
        market = MarketClientFake()
        worker = SecurityOnboardingWorker(
            worker_id="iro-worker-1",
            jobs=jobs,
            registry=MissingTickerRegistryFake(),
            registry_store=RegistryStoreFake(),
            market=market,
            market_store=MarketStoreFake(),
        )

        processed = worker.run_once()

        self.assertTrue(processed)
        self.assertFalse(hasattr(market, "request"))
        self.assertEqual(
            jobs.failed,
            [(claim, "security_registry", "identity_not_resolved", False)],
        )
        self.assertEqual(jobs.completed, [])

    def test_market_failure_is_retryable_only_after_security_persists(self) -> None:
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="CRSP",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )
        jobs = JobStoreFake(claim)
        registry_store = RegistryStoreFake()
        worker = SecurityOnboardingWorker(
            worker_id="iro-worker-1",
            jobs=jobs,
            registry=RegistryClientFake(),
            registry_store=registry_store,
            market=UnavailableMarketFake(),
            market_store=MarketStoreFake(),
        )

        processed = worker.run_once()

        self.assertTrue(processed)
        self.assertEqual(registry_store.persisted.security_id, "22222222-2222-4222-8222-222222222222")
        self.assertEqual(
            jobs.failed,
            [(claim, "market_fetch", "provider_unavailable", True)],
        )
        self.assertEqual(jobs.completed, [])

    def test_registry_persistence_failure_does_not_start_market_collection(
        self,
    ) -> None:
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="CRSP",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )
        jobs = JobStoreFake(claim)
        market = MarketClientFake()
        worker = SecurityOnboardingWorker(
            worker_id="iro-worker-1",
            jobs=jobs,
            registry=RegistryClientFake(),
            registry_store=FailingRegistryStoreFake(),
            market=market,
            market_store=MarketStoreFake(),
        )

        processed = worker.run_once()

        self.assertTrue(processed)
        self.assertFalse(hasattr(market, "request"))
        self.assertEqual(
            jobs.failed,
            [(claim, "persistence", "security_persistence_failed", True)],
        )

    def test_missing_persisted_market_series_is_a_bounded_retryable_failure(
        self,
    ) -> None:
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="CRSP",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )
        jobs = JobStoreFake(claim)
        worker = SecurityOnboardingWorker(
            worker_id="iro-worker-1",
            jobs=jobs,
            registry=RegistryClientFake(),
            registry_store=RegistryStoreFake(),
            market=MissingSeriesMarketFake(),
            market_store=MarketStoreFake(),
        )

        self.assertTrue(worker.run_once())
        self.assertEqual(
            jobs.failed,
            [(claim, "persistence", "market_series_missing", True)],
        )
        self.assertEqual(jobs.completed, [])

    def test_cross_venue_market_identity_fails_before_persistence(
        self,
    ) -> None:
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="CRSP",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )
        jobs = JobStoreFake(claim)
        market_store = MarketStoreFake()
        worker = SecurityOnboardingWorker(
            worker_id="iro-worker-1",
            jobs=jobs,
            registry=RegistryClientFake(),
            registry_store=RegistryStoreFake(),
            market=MismatchedMarketIdentityFake(),
            market_store=market_store,
        )

        self.assertTrue(worker.run_once())
        self.assertFalse(hasattr(market_store, "persisted"))
        self.assertEqual(
            jobs.failed,
            [(claim, "market_fetch", "market_identity_mismatch", False)],
        )

    def test_non_usd_market_identity_fails_before_persistence(self) -> None:
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="CRSP",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )
        jobs = JobStoreFake(claim)
        market_store = MarketStoreFake()
        worker = SecurityOnboardingWorker(
            worker_id="iro-worker-1",
            jobs=jobs,
            registry=RegistryClientFake(),
            registry_store=RegistryStoreFake(),
            market=NonUsdMarketIdentityFake(),
            market_store=market_store,
        )

        self.assertTrue(worker.run_once())
        self.assertFalse(hasattr(market_store, "persisted"))
        self.assertEqual(
            jobs.failed,
            [(claim, "market_fetch", "market_identity_mismatch", False)],
        )

    def test_unrecognized_matching_market_venue_fails_closed(self) -> None:
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="CRSP",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )
        jobs = JobStoreFake(claim)
        market_store = MarketStoreFake()
        worker = SecurityOnboardingWorker(
            worker_id="iro-worker-1",
            jobs=jobs,
            registry=OtcRegistryClientFake(),
            registry_store=RegistryStoreFake(),
            market=OtcMarketIdentityFake(),
            market_store=market_store,
        )

        self.assertTrue(worker.run_once())
        self.assertFalse(hasattr(market_store, "persisted"))
        self.assertEqual(
            jobs.failed,
            [(claim, "market_fetch", "market_identity_mismatch", False)],
        )

    def test_sec_transport_failure_is_retryable(self) -> None:
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="CRSP",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )
        jobs = JobStoreFake(claim)
        worker = SecurityOnboardingWorker(
            worker_id="iro-worker-1",
            jobs=jobs,
            registry=UnavailableRegistryFake(),
            registry_store=RegistryStoreFake(),
            market=MarketClientFake(),
            market_store=MarketStoreFake(),
        )

        self.assertTrue(worker.run_once())
        self.assertEqual(
            jobs.failed,
            [(claim, "security_registry", "source_unavailable", True)],
        )

    def test_unexpected_claim_processing_failure_is_bounded_and_retryable(
        self,
    ) -> None:
        claim = SecurityJobClaim(
            job_id="11111111-1111-4111-8111-111111111111",
            operator_id="027d7f1b-d928-48d9-b6c8-f10d3c7ba792",
            ticker="CRSP",
            attempt_id="44444444-4444-4444-8444-444444444444",
            attempt_number=1,
            lease_token="55555555-5555-4555-8555-555555555555",
        )
        jobs = JobStoreFake(claim)
        worker = SecurityOnboardingWorker(
            worker_id="iro-worker-1",
            jobs=jobs,
            registry=CrashingRegistryFake(),
            registry_store=RegistryStoreFake(),
            market=MarketClientFake(),
            market_store=MarketStoreFake(),
        )

        self.assertTrue(worker.run_once())
        self.assertEqual(
            jobs.failed,
            [(claim, "worker", "unexpected_failure", True)],
        )


if __name__ == "__main__":
    unittest.main()
