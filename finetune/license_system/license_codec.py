"""Pure Lumo Trade device-bound license encoding shared by every client."""

from __future__ import annotations

import hashlib
import re


LICENSE_PREFIX = "LUMO"
LICENSE_SALT = "KRONOS_DEVICE_SALT_2024"
LICENSE_TYPE = "PERMANENT"
LICENSE_CODE_PATTERN = re.compile(
    rf"^{LICENSE_PREFIX}-[A-Z0-9]{{5}}-[A-Z0-9]{{5}}-[A-Z0-9]{{5}}-[A-Z0-9]{{5}}$"
)


def generate_device_license(device_id: str, license_type: str = LICENSE_TYPE) -> str:
    normalized_device_id = str(device_id or "").strip().upper()
    normalized_type = str(license_type or LICENSE_TYPE).strip().upper()
    device_hash = hashlib.sha256(
        f"{normalized_device_id}{LICENSE_SALT}{normalized_type}".encode()
    ).hexdigest()
    segment1 = device_hash[:4].upper() + "D"
    segment2 = device_hash[4:9].upper()
    segment3 = device_hash[9:14].upper()
    checksum = hashlib.md5(f"{segment1}{segment2}{segment3}".encode()).hexdigest()[:5].upper()
    return f"{LICENSE_PREFIX}-{segment1}-{segment2}-{segment3}-{checksum}"


def verify_device_license(
    license_code: str,
    device_id: str,
    license_type: str = LICENSE_TYPE,
) -> bool:
    code = str(license_code or "").strip().upper()
    if not LICENSE_CODE_PATTERN.fullmatch(code):
        return False
    if not code.split("-")[1].endswith("D"):
        return False
    return code == generate_device_license(device_id, license_type)
