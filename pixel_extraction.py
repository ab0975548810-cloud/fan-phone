"""Safely extract one 4-connected nontransparent component from an immutable PNG.

This creates derived layers, not recovered original design layers. It does not
authorize an expanded printable region or alter the original artwork.
"""
from collections import deque
import io
import math
from PIL import Image, ImageDraw, ImageChops

MAX_CONNECTED_PIXELS = 1_500_000
MAX_CANVAS_PIXELS = 18_000_000


def select_component(raw, x, y, factor=1):
    if not isinstance(factor, int) or not 1 <= factor <= 32:
        raise ValueError('編輯縮放比例無效')
    if not all(isinstance(n, (float, int)) and math.isfinite(n) for n in (x, y)):
        raise ValueError('選取位置無效')
    image = Image.open(io.BytesIO(raw))
    if image.format != 'PNG' or image.width * image.height > MAX_CANVAS_PIXELS:
        raise ValueError('只支援安全尺寸的 PNG 原生產圖')
    image = image.convert('RGBA')
    width, height = image.size
    px, py = int(x * factor), int(y * factor)
    if not 0 <= px < width or not 0 <= py < height:
        raise ValueError('請點選圖片範圍內的素材')
    alpha = image.getchannel('A').tobytes()
    seed = py * width + px
    if alpha[seed] == 0:
        # Only a very small nearby tolerance; do not silently select an
        # unrelated item from far away in an empty/transparent region.
        best = None
        radius = min(12, factor * 2)
        for dy in range(-radius, radius + 1):
            yy = py + dy
            if yy < 0 or yy >= height:
                continue
            for dx in range(-radius, radius + 1):
                xx = px + dx
                if xx < 0 or xx >= width or dx * dx + dy * dy > radius * radius:
                    continue
                idx = yy * width + xx
                if alpha[idx] and (best is None or dx * dx + dy * dy < best[0]):
                    best = (dx * dx + dy * dy, idx)
        if best is None:
            raise ValueError('這裡是透明背景，請點選貓咪或其他圖案本身')
        seed = best[1]
    # Four-neighbor connected component. Never use RGB colors (antialiased
    # edges differ), and never flood across alpha=0 transparent gaps.
    marked = bytearray(width * height)
    marked[seed] = 1
    queue = deque([seed])
    count = 0
    left = width
    right = top = 0
    bottom = 0
    while queue:
        idx = queue.popleft()
        count += 1
        if count > MAX_CONNECTED_PIXELS:
            raise ValueError('素材連在一起或範圍過大，請改用手動圈選')
        yy, xx = divmod(idx, width)
        left = min(left, xx)
        right = max(right, xx)
        top = min(top, yy) if count > 1 else yy
        bottom = max(bottom, yy)
        if xx > 0:
            ni = idx - 1
            if not marked[ni] and alpha[ni]:
                marked[ni] = 1
                queue.append(ni)
        if xx + 1 < width:
            ni = idx + 1
            if not marked[ni] and alpha[ni]:
                marked[ni] = 1
                queue.append(ni)
        if yy > 0:
            ni = idx - width
            if not marked[ni] and alpha[ni]:
                marked[ni] = 1
                queue.append(ni)
        if yy + 1 < height:
            ni = idx + width
            if not marked[ni] and alpha[ni]:
                marked[ni] = 1
                queue.append(ni)
    if count < 12:
        raise ValueError('選取範圍太小，請點選素材較明顯的位置')
    bounds = (left, top, right + 1, bottom + 1)
    coverage = Image.frombytes('L', (width, height), bytes(marked)).crop(bounds)
    coverage = coverage.point(lambda v: 255 if v else 0)
    original_crop = image.crop(bounds)
    cutout = Image.composite(original_crop, Image.new('RGBA', original_crop.size), coverage)
    erase = Image.new('RGBA', original_crop.size, (255, 0, 255, 0))
    erase.putalpha(coverage)

    def encode(im):
        out = io.BytesIO()
        im.save(out, format='PNG')
        return out.getvalue()
    return {'bounds': list(bounds), 'pixels': count, 'cutout': encode(cutout), 'erase': encode(erase)}


def select_rectangle(raw, corners, factor=1):
    """Manual two-corner crop for touching shapes; hard edges need review."""
    if not isinstance(corners,(list,tuple)) or len(corners)!=4:
        raise ValueError('請先指定框選區域的兩個角落')
    if not isinstance(factor,int) or not 1<=factor<=32 or not all(
        isinstance(v,(int,float)) and math.isfinite(v) for v in corners):
        raise ValueError('框選資料無效')
    image=Image.open(io.BytesIO(raw))
    if image.format!='PNG' or image.width*image.height>MAX_CANVAS_PIXELS:
        raise ValueError('只支援安全尺寸的 PNG 原生產圖')
    image=image.convert('RGBA')
    x1,y1,x2,y2=(int(round(n*factor)) for n in corners)
    left=max(0,min(x1,x2));top=max(0,min(y1,y2))
    right=min(image.width,max(x1,x2));bottom=min(image.height,max(y1,y2))
    if right-left<3 or bottom-top<3 or (right-left)*(bottom-top)>MAX_CONNECTED_PIXELS:
        raise ValueError('框選範圍太小或過大，請縮小範圍')
    crop=image.crop((left,top,right,bottom))
    coverage=crop.getchannel('A').point(lambda n:255 if n else 0)
    return _selected_crop(crop, coverage, (left,top,right,bottom))


def _selected_crop(crop, coverage, bounds):
    left,top,right,bottom = bounds
    count=coverage.histogram()[255]
    if count<12:raise ValueError('框選區域沒有足夠的圖案像素')
    cutout=Image.composite(crop,Image.new('RGBA',crop.size),coverage)
    erase=Image.new('RGBA',crop.size,(255,0,255,0));erase.putalpha(coverage)
    def encode(im):
        out=io.BytesIO();im.save(out,'PNG');return out.getvalue()
    return {'bounds':[left,top,right,bottom],'pixels':count,
            'cutout':encode(cutout),'erase':encode(erase)}


def select_polygon(raw, points, factor=1):
    """Select only painted source pixels inside the operator's contour."""
    if type(factor) is not int or not 1 <= factor <= 32:
        raise ValueError('編輯縮放比例無效')
    if not isinstance(points, list) or not 3 <= len(points) <= 256:
        raise ValueError('圈選需要 3 至 256 個點')
    image = Image.open(io.BytesIO(raw))
    if image.format != 'PNG' or image.width * image.height > MAX_CANVAS_PIXELS:
        raise ValueError('原圖尺寸無效')
    coords = []
    for point in points:
        if not isinstance(point, list) or len(point) != 2 or not all(
                type(v) in (float, int) and math.isfinite(v) for v in point):
            raise ValueError('圈選座標無效')
        x, y = point
        if not (0 <= x <= image.width / factor and 0 <= y <= image.height / factor):
            raise ValueError('請在原圖範圍內圈選')
        coords.append((min(image.width-1, int(x*factor)), min(image.height-1, int(y*factor))))
    if coords[0] == coords[-1]:
        coords.pop()
    if len(set(coords)) != len(coords) or len(coords) < 3:
        raise ValueError('圈選輪廓需要至少三個不同的點')
    area = sum(x1*y2-y1*x2 for (x1,y1),(x2,y2) in zip(coords, coords[1:]+coords[:1]))
    if not area:
        raise ValueError('圈選輪廓沒有面積，請重新沿邊緣點選')
    xs, ys = zip(*coords)
    left, top, right, bottom = min(xs), min(ys), max(xs)+1, max(ys)+1
    if (right-left)*(bottom-top) > MAX_CONNECTED_PIXELS:
        raise ValueError('圈選範圍過大')
    bounds = left, top, right, bottom
    crop = image.crop(bounds).convert('RGBA')
    contour = Image.new('L', crop.size)
    ImageDraw.Draw(contour).polygon([(x-left, y-top) for x,y in coords], fill=255)
    coverage = ImageChops.multiply(contour, crop.getchannel('A').point(lambda a: 255 if a else 0))
    return _selected_crop(crop, coverage, bounds)


def preview(raw, max_edge=1200):
    """Small, transparent, browser-only preview; never used for production."""
    im = Image.open(io.BytesIO(raw))
    if im.format != 'PNG' or im.width * im.height > MAX_CANVAS_PIXELS:
        raise ValueError('原生產圖片格式或尺寸無效')
    im = im.convert('RGBA')
    im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    im.save(out, format='PNG', compress_level=3)
    return out.getvalue()
