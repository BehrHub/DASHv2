from __future__ import annotations

import base64
from pathlib import Path
import streamlit as st
import re
import unicodedata


SUPPORTED_LOGO_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".svg")
MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

CLIENT_LOGO_FILENAMES = {
    "7-eleven": "711.png",
    "7-11": "711.png",
    "7 eleven": "711.png",
    "atrium village": "atriumvillage.png",
    "baskin robbins": "baskinrobbins.png",
    "baskin-robbins": "baskinrobbins.png",
    "bloomingdale's": "bloomingdales.png",
    "bloomingdales": "bloomingdales.png",
    "catalina": "catalina.png",
    "davis polk": "davispolk.png",
    "davis polk and wardwell": "davispolk.png",
    "davis polk & wardwell": "davispolk.png",
    "dunkin": "dunkin.png",
    "dunkin'": "dunkin.png",
    "food lion": "foodlion.png",
    "giant": "giant.png",
    "giant food": "giant.png",
    "giant food stores": "giant.png",
    "hampton inn": "hamptoninn.png",
    "hampton inn and suites": "hamptoninn.png",
    "hampton inn & suites": "hamptoninn.png",
    "hebrew home gw": "hebrewhomegw.png",
    "hebrew home of greater washington": "hebrewhomegw.png",
    "hilton": "hilton.png",
    "hilton garden inn": "hilton.png",
    "hilton hotels": "hilton.png",
    "homegoods": "homegoods.png",
    "home goods": "homegoods.png",
    "homesense": "homesense.png",
    "home sense": "homesense.png",
    "joint base andrews": "jointbaseandrews.png",
    "macy's": "macys.png",
    "macys": "macys.png",
    "marshalls": "marshalls.png",
    "maryland baptist age home": "marylandbaptistagehome.png",
    "montpelier liquors": "montpelierliquors.png",
    "ncr": "ncr.png",
    "office of md senator angela alsobrooks": "alsobrooks.png",
    "office of md senator chris van hollen": "vanhollen.png",
    "pepsi": "pepsi.png",
    "pepsico": "pepsi.png",
    "rainforest group": "rainforestgroup.png",
    "residential": "residential.png",
    "senator angela alsobrooks": "alsobrooks.png",
    "senator chris van hollen": "vanhollen.png",
    "senator a. alsobrooks": "alsobrooks.png",
    "senator c. van hollen": "vanhollen.png",
    "the rainforest group": "rainforestgroup.png",
    "tj maxx": "tjmaxx.png",
    "t.j. maxx": "tjmaxx.png",
    "tj-maxx": "tjmaxx.png",
    "under armour": "underarmour.png",
    "underarmour": "underarmour.png",
    "united states senate": "senate.png",
    "us senate": "senate.png",
    "usda": "usda.png",
    "verifone": "verifone.png",
    "verizon": "verizon.png",
    "weis": "weis.png",
    "weis markets": "weis.png",
}


def normalize_client_filename(client: object) -> str:
    """Convert a client name to its safe logo filename stem."""
    text = unicodedata.normalize("NFKD", str(client or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"['’]", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


@st.cache_data(show_spinner=False)
def discover_logos(logos_dir: Path) -> tuple[dict[str, Path], dict[str, list[Path]]]:
    """Discover logos, preferring approved Brand Factory assets when present."""
    logos_dir.mkdir(parents=True, exist_ok=True)

    brand_factory_dir = logos_dir.parent / "brand_factory" / "approved"
    candidates: dict[str, list[Path]] = {}

    # 1. Load production logos first as fallback.
    for path in sorted(logos_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_LOGO_EXTENSIONS:
            key = normalize_client_filename(path.stem)
            candidates.setdefault(key, []).append(path)

    # 2. Load Brand Factory approved assets second so they can override production.
    if brand_factory_dir.exists():
        for path in sorted(brand_factory_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_LOGO_EXTENSIONS:
                key = normalize_client_filename(path.stem)
                candidates.setdefault(key, []).insert(0, path)

    extension_priority = {".svg": 0, ".png": 1, ".webp": 2, ".jpg": 3, ".jpeg": 4}

    selected = {
        key: sorted(
            paths,
            key=lambda path: (
                0 if brand_factory_dir in path.parents else 1,
                extension_priority[path.suffix.lower()],
                path.name,
            ),
        )[0]
        for key, paths in candidates.items()
    }

    duplicates = {key: paths for key, paths in candidates.items() if len(paths) > 1}
    return selected, duplicates


def client_logo_filename(client: object) -> str:
    text = str(client or "").strip()
    normalized_text = re.sub(r"\s+", " ", text.casefold())
    return CLIENT_LOGO_FILENAMES.get(normalized_text, f"{normalize_client_filename(text)}.png")


def client_logo_key(client: object) -> str:
    return normalize_client_filename(Path(client_logo_filename(client)).stem)


def resolve_client_logo(client: object, logo_files: dict[str, Path]) -> Path | None:
    mapped_key = client_logo_key(client)
    if mapped_key in logo_files:
        return logo_files[mapped_key]
    fallback_key = normalize_client_filename(client)
    return logo_files.get(fallback_key)


def client_initials(client: object) -> str:
    words = re.findall(r"[A-Za-z0-9]+", str(client or ""))
    if not words:
        return "?"
    return "".join(word[0] for word in words[:2]).upper()


@st.cache_data(show_spinner=False)
def logo_data_uri(path: Path) -> str:
    mime_type = MIME_TYPES[path.suffix.lower()]
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
