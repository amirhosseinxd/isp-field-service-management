import io
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

ALLOWED_SIZES = (180, 192, 512)   # 180 = iPhone home-screen icon, 192/512 = Android and desktop
TOP_COLOR = (20, 48, 90)          # #14305a, the dark blue of the site header
BOTTOM_COLOR = (31, 69, 128)      # #1f4580, the lighter end of the header gradient
TEXT = 'QGS'


def _font(pixels):
    try:
        return ImageFont.load_default(size=pixels)   # scalable built-in font (Pillow 10.1+)
    except TypeError:
        return ImageFont.load_default()              # very old Pillow: small fixed font


@lru_cache(maxsize=len(ALLOWED_SIZES))
def icon_png(size):
    """Return the icon as PNG bytes. lru_cache means each size is drawn only once per server start."""
    # A vertical blend from TOP_COLOR to BOTTOM_COLOR. The icon fills the whole square on purpose:
    # iOS and Android add their own rounded corners, and a full square also works as a "maskable" icon.
    gradient = Image.linear_gradient('L').resize((size, size))
    image = Image.composite(
        Image.new('RGB', (size, size), BOTTOM_COLOR),
        Image.new('RGB', (size, size), TOP_COLOR),
        gradient,
    )
    draw = ImageDraw.Draw(image)

    # Make the letters about 56% of the icon width. Android may crop the outer edge of
    # maskable icons, so the letters must stay in the middle ("safe zone").
    font = _font(100)
    left, top, right, bottom = draw.textbbox((0, 0), TEXT, font=font)
    if right - left:
        font = _font(max(8, int(100 * size * 0.56 / (right - left))))
    left, top, right, bottom = draw.textbbox((0, 0), TEXT, font=font)
    x = (size - (right - left)) / 2 - left
    y = (size - (bottom - top)) / 2 - top
    draw.text((x, y), TEXT, fill='white', font=font)

    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()