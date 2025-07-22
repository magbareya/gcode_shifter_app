from pygcode import Line
import os
import hashlib


def shift_gcode(gcode, x_shift=0.0, y_shift=0.0, z_shift=0.0):
    shifted_lines = []

    for raw_line in gcode.split('\n'):
        stripped_line = raw_line.strip()
        if not stripped_line or stripped_line.startswith('('):
            shifted_lines.append(raw_line.rstrip('\n'))
            continue

        try:
            gcode_line = Line(stripped_line)
            new_words = []

            for word in gcode_line.block.words:
                if word.letter == 'X':
                    word.value += x_shift
                elif word.letter == 'Y':
                    word.value += y_shift
                elif word.letter == 'Z':
                    word.value += z_shift

                new_words.append(str(word))

            shifted_lines.append(' '.join(new_words))

        except Exception:
            shifted_lines.append(stripped_line)
    return '\n'.join(shifted_lines)

def get_max_min_xyz(raw_gcode):
        max_x = 0
        max_y = 0
        max_z = 0
        max_i = 0
        max_j = 0
        max_r = 0
        min_x = 1000
        min_y = 1000
        min_z = 1000
        min_i = 1000
        min_j = 1000
        min_r = 1000
        for line in raw_gcode:
            gcode_line = Line(line)
            for word in gcode_line.block.words:
                if word.letter == "X":
                    max_x = max(max_x, word.value)
                    min_x = min(min_x, word.value)
                elif word.letter == "Y":
                    max_y = max(max_y, word.value)
                    min_y = min(min_y, word.value)
                elif word.letter == "Z":
                    max_z = max(max_z, word.value)
                    min_z = min(min_z, word.value)
                elif word.letter == "I":
                    max_i = max(max_i, word.value)
                    min_i = min(min_i, word.value)
                elif word.letter == "J":
                    max_j = max(max_j, word.value)
                    min_j = min(min_j, word.value)
                elif word.letter == "R":
                    max_r = max(max_r, word.value)
                    min_r = min(min_r, word.value)
        return {
            "mid": {'x':(max_x + min_x) / 2, 'y':(max_y + min_y) / 2, 'z':(max_z + min_z) / 2},
            "max": {'x': max_x, 'y': max_y, 'z': max_z, 'i': max_i, 'j': max_j},
            "min": {'x': min_x, 'y': min_y, 'z': min_z, 'i': min_i, 'j': min_j}
        }

def get_hash(content):
    return hashlib.md5(content.encode("utf-8")).hexdigest()


# def set_middle_xyz(self, x_value, y_value, z_value):
#     shift_x = x_value - self.info["Middle X"]
#     shift_y = y_value - self.info["Middle Y"]
#     shift_z = z_value - self.info["Middle Z"]
#     return self.shift_gcode(shift_x, shift_y, shift_z)

# def set_max_x(self, value):
#     shift_x = value - self.info["Max X"]
#     return self._shift_gcode(shift_x, 0, 0)

# def set_max_y(self, value):
#     shift_y = value - self.info["Max Y"]
#     return self._shift_gcode(0, shift_y, 0)

# def set_max_z(self, value):
#     shift_z = value - self.info["Max Z"]
#     return self._shift_gcode(0, 0, shift_z)

# def set_min_x(self, value):
#     shift_x = value - self.info["Min X"]
#     return self._shift_gcode(shift_x, 0, 0)

# def set_min_y(self, value):
#     shift_y = value - self.info["Min Y"]
#     return self._shift_gcode(0, shift_y, 0)

# def set_min_z(self, value):
#     shift_z = value - self.info["Min Z"]
#     return self._shift_gcode(0, 0, shift_z)
