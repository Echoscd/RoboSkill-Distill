"""Shared camera geometry and depth decoding. See builtin/device/templates/*/DEVICE.md#use."""

import array
import math
import sys


def distort(distortion, x, y):
    if distortion["model"] == "none":
        return x, y
    if distortion["model"] != "opencv_brown_conrady":
        raise ValueError(f'unsupported distortion model: {distortion["model"]}')
    k1, k2, p1, p2, k3 = (distortion[key] for key in ("k1", "k2", "p1", "p2", "k3"))
    r2 = x*x + y*y
    radial = 1 + r2 * (k1 + r2 * (k2 + r2*k3))
    return x*radial + 2*p1*x*y + p2*(r2 + 2*x*x), y*radial + p1*(r2 + 2*y*y) + 2*p2*x*y


def ray(stream, u, v):
    p, d = stream["projection"], stream["distortion"]
    yd = (v - p["cy"]) / p["fy"]
    xd = (u - p["cx"] - p["skew"] * yd) / p["fx"]
    if d["model"] == "none":
        return [xd, yd, 1.0]
    x, y = xd, yd
    for _ in range(30):
        px, py = distort(d, x, y)
        ex, ey = px-xd, py-yd
        if math.hypot(ex, ey) < 1e-10:
            return [x, y, 1.0]
        h = 1e-6
        hx, hy = distort(d, x+h, y)
        vx, vy = distort(d, x, y+h)
        a, b, c, e = (hx-px)/h, (vx-px)/h, (hy-py)/h, (vy-py)/h
        det = a*e-b*c
        if abs(det) < 1e-12:
            raise ValueError("singular camera distortion")
        x, y = x-(e*ex-b*ey)/det, y-(a*ey-c*ex)/det
    raise ValueError("camera distortion inversion did not converge")


def project(stream, point):
    x, y = distort(stream["distortion"], point[0]/point[2], point[1]/point[2])
    p = stream["projection"]
    return p["fx"]*x + p["skew"]*y + p["cx"], p["fy"]*y + p["cy"]


def fov(stream):
    width, height = stream["width"], stream["height"]
    def angle(a, b):
        cosine = sum(x*y for x, y in zip(a, b)) / (math.hypot(*a)*math.hypot(*b))
        return math.degrees(math.acos(max(-1, min(1, cosine))))
    return {
        "horizontal_deg": angle(ray(stream, -0.5, (height-1)/2), ray(stream, width-0.5, (height-1)/2)),
        "vertical_deg": angle(ray(stream, (width-1)/2, -0.5), ray(stream, (width-1)/2, height-0.5)),
    }


def read_depth(path, meta):
    if meta["pixel_format"] != "uint16" or meta["image_format"] != "pgm16_be":
        raise ValueError("unsupported depth encoding")
    with open(path, "rb") as handle:
        raw = handle.read()
    tokens, i = [], 0
    while len(tokens) < 4 and i < len(raw):
        if raw[i:i+1].isspace():
            i += 1
            continue
        if raw[i:i+1] == b"#":
            while i < len(raw) and raw[i:i+1] != b"\n":
                i += 1
            continue
        j = i
        while i < len(raw) and not raw[i:i+1].isspace():
            i += 1
        tokens.append(raw[j:i])
    if len(tokens) != 4 or tokens[0] != b"P5" or tokens[3] != b"65535" or i >= len(raw):
        raise ValueError("expected PGM P5 with maxval 65535")
    width, height = int(tokens[1]), int(tokens[2])
    if (width, height) != (meta["width"], meta["height"]):
        raise ValueError("depth dimensions differ from the profile")
    start = i + (2 if raw[i:i+2] == b"\r\n" else 1)
    if len(raw)-start != width*height*2:
        raise ValueError("depth payload size differs from its dimensions")
    pixels = array.array("H")
    pixels.frombytes(raw[start:])
    if sys.byteorder == "little":
        pixels.byteswap()
    return width, height, pixels
