import ipaddress
import re
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048
BLOCKED_HOSTS = {"localhost"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")
TLD_PATTERN = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]+")


def is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global


def validate_destination_url(url: str, *, allow_private: bool = False) -> str:
    if len(url) > MAX_URL_LENGTH:
        raise ValueError("url is too long")

    parts = urlsplit(url)
    allowed_schemas = {"http", "https"} if allow_private else {"https"}
    if parts.scheme not in allowed_schemas:
        raise ValueError("url must use https")
    if parts.username or parts.password:
        raise ValueError("url must not contain credentials")

    host = parts.hostname
    if not host:
        raise ValueError("url must include a host")

    if allow_private:
        return url

    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("url port is invalid") from exc

    if port is not None and not (1 <= port <= 65535):
        raise ValueError("url port is invalid")

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        _validate_hostname(host)
    else:
        if address.version == 6 and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if not address.is_global:
            raise ValueError("url must not point to a private or reserved address")

    return url


def _validate_hostname(host: str) -> None:
    if host in BLOCKED_HOSTS or host.endswith(BLOCKED_SUFFIXES):
        raise ValueError("url must not point to a local or internal host")
    if "." not in host:
        raise ValueError("host must be a fully qualified domain name")
    top_level = host.rsplit(".", 1)[1]
    if not TLD_PATTERN.fullmatch(top_level):
        raise ValueError("host must end with a valid top-level domain")
