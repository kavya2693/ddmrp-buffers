"""Turn the repo's light matplotlib charts into the dark panels used in the video.

Inverts each image, rotates hue by 180 degrees (so colours keep their hue), blends it onto the
video background (#0b1722), crops the panels used on slide 06 and upscales 2x. No data is redrawn.

Usage: python3 darkmap.py <repo>/outputs <demo>/assets
Needs: numpy, Pillow, matplotlib.
"""

import sys

import numpy as np
from matplotlib.colors import hsv_to_rgb, rgb_to_hsv
from PIL import Image

src, out = sys.argv[1].rstrip("/") + "/", sys.argv[2].rstrip("/") + "/"
BG = np.array([0x0B, 0x17, 0x22]) / 255


def dark(path: str) -> Image.Image:
    im = np.asarray(Image.open(path).convert("RGB")).astype(float) / 255
    hsv = rgb_to_hsv(1 - im)
    hsv[..., 0] = (hsv[..., 0] + 0.5) % 1.0
    d = BG + hsv_to_rgb(hsv) * (1 - BG)
    return Image.fromarray((d * 255).clip(0, 255).astype(np.uint8))


# crop boxes (left, top, right, bottom) in the PNGs written by ddmrp_buffers/charts.py
CROPS = {
    "buffer_chart.png": {"buffer-local.png": (0, 8, 1300, 396), "buffer-import.png": (0, 402, 1300, 792)},
    "frontier.png": {"frontier.png": (0, 40, 975, 598)},
}
for name, boxes in CROPS.items():
    img = dark(src + name)
    for dst, box in boxes.items():
        c = img.crop(box)
        c = c.resize((c.width * 2, c.height * 2), Image.LANCZOS)
        c.save(out + dst)
        print(out + dst, c.size)
