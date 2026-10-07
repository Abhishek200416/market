"""Render an original brand mark for the user's broker app registration."""
from pathlib import Path
from PIL import Image, ImageDraw

image = Image.new('RGB', (512, 512), '#17212b')
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((24, 24, 488, 488), radius=50, outline='#91bfd3', width=7)
for x, top, bottom in ((135, 252, 351), (249, 202, 300), (363, 140, 234)):
    draw.line((x, top-27, x, bottom+27), fill='#d2e8ef', width=10)
    draw.rounded_rectangle((x-23, top, x+23, bottom), radius=5, fill='#91bfd3')
draw.line((106, 407, 406, 407), fill='#5e7d91', width=7)
output = Path(__file__).resolve().parents[1] / 'frontend/public/edge-india-logo.png'
image.save(output)
print(f'Original app logo written: {output}')