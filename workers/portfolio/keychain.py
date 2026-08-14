from __future__ import annotations

import ctypes
import ctypes.util
import sys
import uuid
from typing import Protocol


KEYCHAIN_SERVICE = "dev.slated.iros.moomoo"
ERR_SEC_ITEM_NOT_FOUND = -25300


class MoomooKeychainError(RuntimeError):
    """Raised when native refresh-token custody fails without exposing data."""


class KeychainBackend(Protocol):
    def store(self, *, service: str, account: str, secret: str) -> None: ...

    def read(self, *, service: str, account: str) -> str | None: ...

    def delete(self, *, service: str, account: str) -> None: ...


class MacOSKeychainBackend:
    """Small native Security.framework adapter; secrets never enter argv."""

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise MoomooKeychainError("macOS Keychain is unavailable")
        security_path = ctypes.util.find_library("Security")
        core_foundation_path = ctypes.util.find_library("CoreFoundation")
        if security_path is None or core_foundation_path is None:
            raise MoomooKeychainError("macOS Keychain framework is unavailable")
        self._security = ctypes.CDLL(security_path)
        self._core_foundation = ctypes.CDLL(core_foundation_path)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        uint32 = ctypes.c_uint32
        void_p = ctypes.c_void_p
        self._security.SecKeychainAddGenericPassword.argtypes = (
            void_p,
            uint32,
            void_p,
            uint32,
            void_p,
            uint32,
            void_p,
            ctypes.POINTER(void_p),
        )
        self._security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        self._security.SecKeychainFindGenericPassword.argtypes = (
            void_p,
            uint32,
            void_p,
            uint32,
            void_p,
            ctypes.POINTER(uint32),
            ctypes.POINTER(void_p),
            ctypes.POINTER(void_p),
        )
        self._security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        self._security.SecKeychainItemModifyAttributesAndData.argtypes = (
            void_p,
            void_p,
            uint32,
            void_p,
        )
        self._security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        self._security.SecKeychainItemDelete.argtypes = (void_p,)
        self._security.SecKeychainItemDelete.restype = ctypes.c_int32
        self._security.SecKeychainItemFreeContent.argtypes = (void_p, void_p)
        self._security.SecKeychainItemFreeContent.restype = ctypes.c_int32
        self._core_foundation.CFRelease.argtypes = (void_p,)
        self._core_foundation.CFRelease.restype = None

    @staticmethod
    def _encoded(value: str) -> tuple[bytes, ctypes.c_void_p]:
        encoded = value.encode("utf-8")
        return encoded, ctypes.cast(ctypes.c_char_p(encoded), ctypes.c_void_p)

    def _find(
        self,
        *,
        service: str,
        account: str,
        include_secret: bool,
    ) -> tuple[int, ctypes.c_void_p, ctypes.c_void_p, int]:
        service_bytes, service_pointer = self._encoded(service)
        account_bytes, account_pointer = self._encoded(account)
        secret_length = ctypes.c_uint32()
        secret_pointer = ctypes.c_void_p()
        item = ctypes.c_void_p()
        status = self._security.SecKeychainFindGenericPassword(
            None,
            len(service_bytes),
            service_pointer,
            len(account_bytes),
            account_pointer,
            ctypes.byref(secret_length) if include_secret else None,
            ctypes.byref(secret_pointer) if include_secret else None,
            ctypes.byref(item),
        )
        return status, item, secret_pointer, secret_length.value

    def store(self, *, service: str, account: str, secret: str) -> None:
        secret_bytes, secret_pointer = self._encoded(secret)
        status, item, _, _ = self._find(
            service=service,
            account=account,
            include_secret=False,
        )
        try:
            if status == 0:
                result = self._security.SecKeychainItemModifyAttributesAndData(
                    item,
                    None,
                    len(secret_bytes),
                    secret_pointer,
                )
            elif status == ERR_SEC_ITEM_NOT_FOUND:
                new_item = ctypes.c_void_p()
                service_bytes, service_pointer = self._encoded(service)
                account_bytes, account_pointer = self._encoded(account)
                try:
                    result = self._security.SecKeychainAddGenericPassword(
                        None,
                        len(service_bytes),
                        service_pointer,
                        len(account_bytes),
                        account_pointer,
                        len(secret_bytes),
                        secret_pointer,
                        ctypes.byref(new_item),
                    )
                finally:
                    if new_item:
                        self._core_foundation.CFRelease(new_item)
            else:
                raise MoomooKeychainError("macOS Keychain lookup failed")
        finally:
            if item:
                self._core_foundation.CFRelease(item)
        if result != 0:
            raise MoomooKeychainError("macOS Keychain store failed")

    def read(self, *, service: str, account: str) -> str | None:
        status, item, content, content_length = self._find(
            service=service,
            account=account,
            include_secret=True,
        )
        try:
            if status == ERR_SEC_ITEM_NOT_FOUND:
                return None
            if status != 0 or not content or content_length == 0:
                raise MoomooKeychainError("macOS Keychain lookup failed")
            return ctypes.string_at(content, content_length).decode("utf-8")
        except UnicodeDecodeError as error:
            raise MoomooKeychainError("macOS Keychain value is invalid") from error
        finally:
            if content:
                self._security.SecKeychainItemFreeContent(None, content)
            if item:
                self._core_foundation.CFRelease(item)

    def delete(self, *, service: str, account: str) -> None:
        status, item, _, _ = self._find(
            service=service,
            account=account,
            include_secret=False,
        )
        try:
            if status == ERR_SEC_ITEM_NOT_FOUND:
                return
            if status != 0 or not item:
                raise MoomooKeychainError("macOS Keychain lookup failed")
            result = self._security.SecKeychainItemDelete(item)
        finally:
            if item:
                self._core_foundation.CFRelease(item)
        if result != 0:
            raise MoomooKeychainError("macOS Keychain delete failed")


class MoomooTokenKeychain:
    def __init__(
        self,
        *,
        operator_id: str,
        backend: KeychainBackend | None = None,
    ) -> None:
        normalized_operator_id = str(uuid.UUID(operator_id))
        self.account = f"{normalized_operator_id}:refresh_token"
        self.backend = backend if backend is not None else MacOSKeychainBackend()

    def store_refresh_token(self, refresh_token: str) -> None:
        if not refresh_token or "\n" in refresh_token or "\r" in refresh_token:
            raise ValueError("Moomoo refresh token is invalid")
        self.backend.store(
            service=KEYCHAIN_SERVICE,
            account=self.account,
            secret=refresh_token,
        )

    def read_refresh_token(self) -> str:
        token = self.backend.read(service=KEYCHAIN_SERVICE, account=self.account)
        if token is None or not token:
            raise MoomooKeychainError("Moomoo refresh token is unavailable")
        return token

    def delete_refresh_token(self) -> None:
        self.backend.delete(service=KEYCHAIN_SERVICE, account=self.account)
