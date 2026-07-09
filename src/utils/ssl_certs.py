"""SSL CA bundle для platform-api2.max.ru (сертификаты Минцифры)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import certifi

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RUSSIAN_CERTS_DIR = _PROJECT_ROOT / "config" / "certs"
_BUNDLE_CACHE = _PROJECT_ROOT / "data" / "certs" / "russian_trusted_ca_bundle.pem"
_RUSSIAN_CERT_NAMES = (
    "russian_trusted_root_ca.cer",
    "russian_trusted_sub_ca.cer",
)


def _load_cert_pem(path: Path) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    raw = path.read_bytes()
    try:
        cert = x509.load_der_x509_certificate(raw)
    except ValueError:
        cert = x509.load_pem_x509_certificate(raw)
    return cert.public_bytes(Encoding.PEM).decode()


def build_russian_ca_bundle(force: bool = False) -> Path | None:
    """Собрать PEM-бандл: certifi + сертификаты Минцифры из config/certs/."""
    cert_paths = [_RUSSIAN_CERTS_DIR / name for name in _RUSSIAN_CERT_NAMES]
    if not all(p.is_file() for p in cert_paths):
        logger.warning(
            "Сертификаты Минцифры не найдены в %s — используется только certifi",
            _RUSSIAN_CERTS_DIR,
        )
        return None

    if _BUNDLE_CACHE.is_file() and not force:
        return _BUNDLE_CACHE

    try:
        russian_pems = [_load_cert_pem(p) for p in cert_paths]
    except Exception as exc:
        logger.error("Не удалось прочитать сертификаты Минцифры: %s", exc)
        return None

    _BUNDLE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    bundle_text = Path(certifi.where()).read_text(encoding="utf-8").rstrip() + "\n"
    bundle_text += "\n".join(russian_pems)
    _BUNDLE_CACHE.write_text(bundle_text, encoding="utf-8")
    logger.debug("CA bundle обновлён: %s", _BUNDLE_CACHE)
    return _BUNDLE_CACHE


@lru_cache(maxsize=1)
def get_max_api_verify() -> str | bool:
    """Путь к CA bundle для httpx или True (только certifi/системные CA)."""
    bundle = build_russian_ca_bundle()
    if bundle is not None:
        return str(bundle)
    return True
