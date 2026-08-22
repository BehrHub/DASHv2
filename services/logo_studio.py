from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw

TILE_SIZE = 96
DEFAULT_PROFILE = {"scale": 0.78, "x": 0, "y": 0}


def list_raw_logos(raw_dir: Path) -> list[str]:
    """Files sitting in the staging folder, ready to be calibrated."""
    if not raw_dir.exists():
        return []
    return sorted(
        p.name for p in raw_dir.iterdir()
        if p.suffix.lower() in (".png", ".jpg", ".jpeg") and not p.name.startswith(".")
    )


def load_profiles(profiles_path: Path) -> dict:
    if not profiles_path.exists():
        return {"_defaults": dict(DEFAULT_PROFILE)}
    return json.loads(profiles_path.read_text())


def save_profiles(profiles_path: Path, profiles: dict) -> None:
    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    profiles_path.write_text(json.dumps(profiles, indent=2) + "\n")


def _rounded_white_tile(tile_size: int) -> Image.Image:
    """White rounded-square backing with a soft dark border, matching
    the existing 27 calibrated logos exactly (reverse-engineered from
    their actual pixels: pure white fill, ~1-2px soft anti-aliased dark
    edge). Supersampled 4x then downsampled for a smooth, non-jagged
    border — PIL's ImageDraw has no native anti-aliasing.
    """
    ss = 4
    big = Image.new("RGBA", (tile_size * ss, tile_size * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    radius = int(tile_size * ss * 0.16)
    inset = ss  # keep the border fully inside the canvas
    draw.rounded_rectangle(
        [inset, inset, tile_size * ss - inset, tile_size * ss - inset],
        radius=radius,
        fill=(255, 255, 255, 255),
        outline=(60, 65, 75, 90),
        width=ss * 2,
    )
    return big.resize((tile_size, tile_size), Image.LANCZOS)


def render_calibrated_tile(
    raw_path: Path, scale: float, x: int, y: int, tile_size: int = TILE_SIZE
) -> Image.Image:
    """Reproduces the original Logo Factory's scale/x/y convention:
    trim the raw logo to its actual content (so `scale` means the same
    thing regardless of how much blank margin the source file happens
    to have), resize so its larger dimension is `scale * tile_size`,
    then paste it centered + (x, y) onto a white rounded-square tile.
    """
    raw = Image.open(raw_path).convert("RGBA")
    bbox = raw.getbbox()
    content = raw.crop(bbox) if bbox else raw

    target_dim = max(1, round(scale * tile_size))
    w, h = content.size
    if w >= h:
        new_w, new_h = target_dim, max(1, round(h * target_dim / w))
    else:
        new_h, new_w = target_dim, max(1, round(w * target_dim / h))
    resized = content.resize((new_w, new_h), Image.LANCZOS)

    tile = _rounded_white_tile(tile_size)
    paste_x = (tile_size - new_w) // 2 + x
    paste_y = (tile_size - new_h) // 2 + y
    tile.alpha_composite(resized, (paste_x, paste_y))
    return tile


@st.cache_data(show_spinner=False)
def _cached_preview(raw_path_str: str, scale: float, x: int, y: int, mtime: float) -> bytes:
    """mtime busts the cache automatically if the raw source file itself
    changes (e.g. someone re-uploads a replacement), without needing an
    explicit .clear() call for that case specifically."""
    import io

    tile = render_calibrated_tile(Path(raw_path_str), scale, x, y)
    buf = io.BytesIO()
    tile.save(buf, format="PNG")
    return buf.getvalue()


def preview_png_bytes(raw_path: Path, scale: float, x: int, y: int) -> bytes:
    return _cached_preview(str(raw_path), scale, x, y, raw_path.stat().st_mtime)
