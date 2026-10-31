"""Local image handling: validate, re-encode and resize uploads with Pillow.

Every upload is fully decoded and re-saved as a fresh JPEG, which strips
metadata (including GPS data) and discards anything that is not really an image.
"""
import uuid
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
SIZES = {"thumb": (520, 80), "medium": (1100, 86), "large": (2000, 88)}  # max side, quality
Image.MAX_IMAGE_PIXELS = 50_000_000


class ImageError(ValueError):
    """Raised with a message that is safe to show to the artist."""


def paintings_dir(media_root):
    path = Path(media_root) / "paintings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_painting_image(file_storage, media_root):
    """Validate and store an uploaded image. Returns (image_key, width, height)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(file_storage.stream)
            if img.format not in ALLOWED_FORMATS:
                raise ImageError("Upload a JPEG, PNG or WebP image.")
            img.load()
    except ImageError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning, OSError, SyntaxError, ValueError):
        raise ImageError("That file could not be read as an image. Upload a JPEG, PNG or WebP.")

    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))
        img = background
    else:
        img = img.convert("RGB")

    width, height = img.size
    if min(width, height) < 200:
        raise ImageError("The image is too small. Use one at least 200 pixels on its shortest side.")

    key = uuid.uuid4().hex
    folder = paintings_dir(media_root)
    for name, (max_side, quality) in SIZES.items():
        version = img.copy()
        version.thumbnail((max_side, max_side), Image.LANCZOS)  # never enlarges
        version.save(folder / f"{key}_{name}.jpg", "JPEG",
                     quality=quality, optimize=True, progressive=True)
    return key, width, height


def delete_painting_files(media_root, key):
    folder = paintings_dir(media_root)
    for name in SIZES:
        try:
            (folder / f"{key}_{name}.jpg").unlink()
        except FileNotFoundError:
            pass
