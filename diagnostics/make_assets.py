"""Create 56 numbered 8x8 tiles. Only Python stdlib is needed."""
from pathlib import Path
DIGITS = ('111101101101111','010110010010111','111001111100111',
          '111001111001111','101101111001001','111100111001111',
          '111100111101111','111001010010010','111101111101111','111101111001111')


def tiles():
    data = bytearray()
    for y in range(8):
        for col in range(56):
            for x in range(8):
                color = 16 + col
                if x == 0: color = 2  # distinct first pixel: red
                if x == 7: color = 4  # last pixel: blue
                if y == 0: color = 3  # first row: green
                if y == 7: color = 6  # last row: cyan
                if 1 <= y <= 5 and x in (1, 2, 3, 4, 5, 6):
                    digit = col // 10 if x < 4 else col % 10
                    dx = x - (1 if x < 4 else 4)
                    color = 255 if DIGITS[digit][(y-1)*3+dx] == '1' else 0
                data.append(color)
    return data


def palettes():
    data = bytearray()
    fixed = {0: (0, 0, 0), 2: (255, 0, 0), 3: (0, 255, 0),
             4: (0, 0, 255), 6: (0, 255, 255), 255: (255, 255, 255)}
    for index in range(256):
        for group in range(8):
            rgb = fixed.get(index, ((index * 5) & 255,
                                   (index * 3 + group * 48) & 255,
                                   (index * 7 + group * 64) & 255))
            data.extend((*rgb, 0))
    return data


if __name__ == '__main__':
    dest = Path(__file__).parent / 'build'
    dest.mkdir(exist_ok=True)
    (dest / 'tiles.bin').write_bytes(tiles())
    (dest / 'palettes.bin').write_bytes(palettes())
