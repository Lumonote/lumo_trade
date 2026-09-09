#!/usr/bin/env python3
"""Generate Lumo Trade desktop app icons.

The script is intentionally dependency-light: it only needs numpy and Python's
standard library. macOS `.icns` output uses the system `iconutil` when present.
"""

from __future__ import annotations

import argparse
import binascii
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import numpy as np


ICONSET_SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}
ICO_SIZES = (16, 32, 64, 128, 256)
ICNS_TYPES = {
    16: b"icp4",
    32: b"icp5",
    64: b"icp6",
    128: b"ic07",
    256: b"ic08",
    512: b"ic09",
    1024: b"ic10",
}


def hex_color(value: str) -> np.ndarray:
    value = value.lstrip("#")
    return np.array([int(value[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


def smoothstep(edge0: float, edge1: float, value: np.ndarray) -> np.ndarray:
    t = np.clip((value - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def blend(rgb: np.ndarray, color: np.ndarray, alpha: np.ndarray) -> None:
    alpha = np.clip(alpha, 0.0, 1.0).astype(np.float32)
    if color.ndim == 1:
        rgb[:] = rgb * (1.0 - alpha[..., None]) + color * alpha[..., None]
    else:
        rgb[:] = rgb * (1.0 - alpha[..., None]) + color * alpha[..., None]


def add_light(rgb: np.ndarray, color: np.ndarray, alpha: np.ndarray, strength: float = 1.0) -> None:
    rgb[:] = np.clip(rgb + color * np.clip(alpha[..., None] * strength, 0.0, 1.0), 0.0, 1.0)


def line_alpha(
    x: np.ndarray,
    y: np.ndarray,
    start: tuple[float, float],
    end: tuple[float, float],
    width: float,
    feather: float,
) -> np.ndarray:
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    denom = dx * dx + dy * dy
    t = np.clip(((x - x1) * dx + (y - y1) * dy) / denom, 0.0, 1.0)
    px = x1 + t * dx
    py = y1 + t * dy
    dist = np.sqrt((x - px) ** 2 + (y - py) ** 2)
    return 1.0 - smoothstep(width * 0.5, width * 0.5 + feather, dist)


def rounded_rect_alpha(
    x: np.ndarray,
    y: np.ndarray,
    center: tuple[float, float],
    size: tuple[float, float],
    radius: float,
    feather: float,
) -> np.ndarray:
    cx, cy = center
    half_w, half_h = size[0] * 0.5, size[1] * 0.5
    dx = np.abs(x - cx) - half_w + radius
    dy = np.abs(y - cy) - half_h + radius
    outside = np.sqrt(np.maximum(dx, 0.0) ** 2 + np.maximum(dy, 0.0) ** 2)
    inside = np.minimum(np.maximum(dx, dy), 0.0)
    signed_distance = outside + inside - radius
    return 1.0 - smoothstep(0.0, feather, signed_distance)


def circle_alpha(
    x: np.ndarray,
    y: np.ndarray,
    center: tuple[float, float],
    radius: float,
    feather: float,
) -> np.ndarray:
    cx, cy = center
    distance = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
    return 1.0 - smoothstep(radius, radius + feather, distance)


def superellipse_alpha(
    x: np.ndarray,
    y: np.ndarray,
    radius: float,
    exponent: float,
    feather: float,
) -> np.ndarray:
    value = (np.abs(x - 0.5) / radius) ** exponent + (np.abs(y - 0.5) / radius) ** exponent
    return 1.0 - smoothstep(1.0, 1.0 + feather, value)


def make_icon(size: int = 1024, scale: int = 2) -> np.ndarray:
    canvas = size * scale
    axis = (np.arange(canvas, dtype=np.float32) + 0.5) / canvas
    x = np.broadcast_to(axis[None, :], (canvas, canvas))
    y = np.broadcast_to(axis[:, None], (canvas, canvas))

    icon = superellipse_alpha(x, y, radius=0.486, exponent=4.4, feather=0.035)
    inner = superellipse_alpha(x, y, radius=0.462, exponent=4.4, feather=0.03)
    edge = np.clip(icon - inner * 0.86, 0.0, 1.0)

    t = np.clip((x * 0.48 + y * 0.72), 0.0, 1.0)
    bg0 = hex_color("#060913")
    bg1 = hex_color("#101A34")
    bg2 = hex_color("#24133A")
    rgb = bg0 * (1.0 - t[..., None]) + bg1 * t[..., None]

    blue_wash = np.exp(-(((x - 0.76) / 0.46) ** 2 + ((y - 0.24) / 0.35) ** 2))
    violet_wash = np.exp(-(((x - 0.14) / 0.36) ** 2 + ((y - 0.82) / 0.38) ** 2))
    gold_wash = np.exp(-(((x - 0.80) / 0.32) ** 2 + ((y - 0.82) / 0.30) ** 2))
    rgb = rgb * (1.0 - blue_wash[..., None] * 0.30) + hex_color("#173B7D") * blue_wash[..., None] * 0.30
    rgb = rgb * (1.0 - violet_wash[..., None] * 0.18) + bg2 * violet_wash[..., None] * 0.18
    rgb = rgb * (1.0 - gold_wash[..., None] * 0.08) + hex_color("#4B3515") * gold_wash[..., None] * 0.08

    # Subtle data grid: visible enough for depth, quiet enough to stay readable at small sizes.
    grid_x = (np.abs((x * 9.0) % 1.0 - 0.5) < 0.004).astype(np.float32)
    grid_y = (np.abs((y * 9.0) % 1.0 - 0.5) < 0.004).astype(np.float32)
    grid = np.clip((grid_x + grid_y) * 0.026 * icon, 0.0, 0.05)
    blend(rgb, hex_color("#D8E8FF"), grid)

    shine = np.exp(-(((x - 0.26) / 0.45) ** 2 + ((y - 0.12) / 0.22) ** 2)) * 0.15 * icon
    blend(rgb, hex_color("#FFFFFF"), shine)
    blend(rgb, hex_color("#8FC5FF"), edge * 0.54)

    # Low-opacity candlesticks behind the mark.
    candles = [
        (0.55, 0.50, 0.17, 0.08, "#4EA2FF"),
        (0.62, 0.47, 0.21, 0.10, "#D35A6A"),
        (0.69, 0.42, 0.19, 0.09, "#7BB6FF"),
        (0.76, 0.39, 0.24, 0.10, "#4EA2FF"),
    ]
    for cx, cy, wick, body_h, color in candles:
        wick_mask = line_alpha(x, y, (cx, cy - wick * 0.5), (cx, cy + wick * 0.5), 0.010, 0.004)
        body_mask = rounded_rect_alpha(x, y, (cx, cy), (0.046, body_h), 0.009, 0.004)
        candle_alpha = np.clip((wick_mask * 0.45 + body_mask * 0.80) * icon, 0.0, 0.42)
        blend(rgb, hex_color(color), candle_alpha)

    blue_core = hex_color("#45A3FF")
    ice = hex_color("#BFDFFF")
    violet = hex_color("#766CFF")
    white = hex_color("#F5FAFF")
    gold = hex_color("#FFD166")
    blue = hex_color("#247CFF")
    deep_blue = hex_color("#0A2346")

    k_segments = [
        ((0.305, 0.235), (0.305, 0.765), 0.070, ice, white),
        ((0.355, 0.502), (0.700, 0.255), 0.071, blue_core, white),
        ((0.355, 0.502), (0.725, 0.742), 0.071, violet, ice),
    ]
    for start, end, width, color_a, color_b in k_segments:
        glow = line_alpha(x, y, start, end, width * 2.75, 0.060) * icon
        add_light(rgb, color_a, glow, 0.18)

    for start, end, width, color_a, color_b in k_segments:
        body = line_alpha(x, y, start, end, width, 0.012) * icon
        gloss = line_alpha(
            x,
            y,
            (start[0] - 0.010, start[1] - 0.010),
            (end[0] - 0.010, end[1] - 0.010),
            width * 0.42,
            0.010,
        )
        gradient = np.clip((x * 0.45 + (1.0 - y) * 0.55), 0.0, 1.0)
        stroke_color = color_a * (1.0 - gradient[..., None]) + color_b * gradient[..., None]
        blend(rgb, stroke_color, body)
        blend(rgb, white, gloss * body * 0.42)

    # Golden forecast path, kept thin so the K remains the dominant silhouette.
    path = [(0.205, 0.680), (0.390, 0.595), (0.545, 0.635), (0.735, 0.405)]
    for p1, p2 in zip(path, path[1:]):
        glow = line_alpha(x, y, p1, p2, 0.055, 0.030) * icon
        body = line_alpha(x, y, p1, p2, 0.021, 0.006) * icon
        add_light(rgb, gold, glow, 0.12)
        blend(rgb, gold, body)
    for point in path:
        halo = circle_alpha(x, y, point, 0.040, 0.025) * icon
        dot = circle_alpha(x, y, point, 0.020, 0.006) * icon
        add_light(rgb, gold, halo, 0.15)
        blend(rgb, white, dot * 0.76)
        blend(rgb, gold, dot * 0.58)

    # Compact chip detail in the top-right corner for the AI side of the app.
    chip = rounded_rect_alpha(x, y, (0.755, 0.245), (0.150, 0.105), 0.025, 0.006) * icon
    blend(rgb, deep_blue, chip * 0.74)
    blend(rgb, violet, chip * 0.16)
    for dx in (-0.045, 0.0, 0.045):
        pin = line_alpha(x, y, (0.755 + dx, 0.175), (0.755 + dx, 0.205), 0.007, 0.003)
        blend(rgb, blue_core, pin * icon * 0.72)
        pin = line_alpha(x, y, (0.755 + dx, 0.285), (0.755 + dx, 0.315), 0.007, 0.003)
        blend(rgb, blue_core, pin * icon * 0.72)
    core = circle_alpha(x, y, (0.755, 0.245), 0.024, 0.006) * chip
    blend(rgb, white, core * 0.75)
    blend(rgb, blue, core * 0.35)

    alpha = icon[..., None]
    rgba = np.concatenate([np.clip(rgb, 0.0, 1.0), alpha], axis=2)
    rgba_u8 = np.clip(np.rint(rgba * 255.0), 0, 255).astype(np.uint8)
    return area_resize(rgba_u8, size)


def area_resize(image: np.ndarray, target_size: int) -> np.ndarray:
    source_size = image.shape[0]
    if source_size == target_size:
        return image.copy()
    if source_size % target_size != 0:
        raise ValueError(f"{source_size} cannot be evenly resized to {target_size}")
    factor = source_size // target_size
    resized = image.reshape(target_size, factor, target_size, factor, 4).mean(axis=(1, 3))
    return np.clip(np.rint(resized), 0, 255).astype(np.uint8)


def png_bytes(image: np.ndarray) -> bytes:
    height, width, channels = image.shape
    if channels != 4:
        raise ValueError("PNG writer expects RGBA data")

    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    rows = bytearray()
    for row in image:
        rows.append(0)
        rows.extend(row.tobytes())
    payload = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(bytes(rows), level=9)),
            chunk(b"IEND", b""),
        ]
    )
    return payload


def write_png(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(image))


def write_ico(path: Path, images: dict[int, np.ndarray]) -> None:
    png_payloads = {size: png_bytes(image) for size, image in images.items()}
    count = len(png_payloads)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + count * 16
    entries = []
    data = []
    for size in sorted(png_payloads):
        payload = png_payloads[size]
        width = 0 if size >= 256 else size
        height = 0 if size >= 256 else size
        entries.append(struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(payload), offset))
        data.append(payload)
        offset += len(payload)
    path.write_bytes(header + b"".join(entries) + b"".join(data))


def write_icns(path: Path, images: dict[int, np.ndarray]) -> None:
    chunks = []
    for size in sorted(images):
        icon_type = ICNS_TYPES.get(size)
        if not icon_type:
            continue
        payload = png_bytes(images[size])
        chunks.append(icon_type + struct.pack(">I", len(payload) + 8) + payload)
    body = b"".join(chunks)
    path.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)


def normalize_with_sips(path: Path) -> None:
    sips = shutil.which("sips")
    if not sips:
        return
    tmp_path = path.with_suffix(f"{path.suffix}.sips.tmp")
    try:
        subprocess.run(
            [sips, "-s", "format", "png", str(path), "--out", str(tmp_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def generate_assets(project_root: Path) -> None:
    assets_dir = project_root / "assets"
    iconset_dir = assets_dir / "lumo_ai_stock.iconset"
    base = make_icon(size=1024, scale=2)
    high = make_icon(size=2048, scale=1)

    write_png(assets_dir / "lumo_ai_stock.png", base)

    iconset_dir.mkdir(parents=True, exist_ok=True)
    for filename, target_size in ICONSET_SIZES.items():
        png_path = iconset_dir / filename
        write_png(png_path, area_resize(high, target_size))
        normalize_with_sips(png_path)

    write_ico(
        assets_dir / "lumo_ai_stock.ico",
        {size: area_resize(high, size) for size in ICO_SIZES},
    )

    write_icns(
        assets_dir / "lumo_ai_stock.icns",
        {size: area_resize(high, size) for size in ICNS_TYPES},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Lumo Trade app icon assets.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root. Defaults to this script's repository.",
    )
    args = parser.parse_args()
    generate_assets(args.project_root.resolve())


if __name__ == "__main__":
    main()
