"""Validate optional local author photos before asking Streamlit to render them."""
from io import BytesIO
from PIL import Image, UnidentifiedImageError


def validate_photo(payload: bytes) -> bytes:
    if len(payload) > 20 * 1024 * 1024:
        raise ValueError("Размер фотографии превышает 20 МБ.")
    try:
        with Image.open(BytesIO(payload)) as image:
            if image.format not in {"PNG", "JPEG"}:
                raise ValueError("Выберите изображение PNG или JPEG.")
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("Файл не является исправным изображением PNG или JPEG.") from exc
    return payload
