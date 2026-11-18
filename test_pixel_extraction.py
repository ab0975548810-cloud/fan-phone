"""Regression for component extraction; no real customer art or vendor calls."""
import io
import unittest
from PIL import Image, ImageDraw
from pixel_extraction import select_component, select_rectangle, preview
from pixel_order_designs import compose


def png(im):
    b=io.BytesIO()
    im.save(b,'PNG',dpi=(720,720))
    return b.getvalue()


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.im=Image.new('RGBA',(210,150),(0,0,0,0))
        d=ImageDraw.Draw(self.im)
        d.ellipse((12,18,70,89),fill=(60,60,60,255))
        d.ellipse((115,30,185,105),fill=(255,200,20,255))
        self.raw=png(self.im)

    def test_independent_object_exact_alpha_and_original_unchanged(self):
        before=bytes(self.raw)
        cut=select_component(self.raw,25,35,1)
        self.assertEqual(cut['bounds'],[12,18,71,90])
        subject=Image.open(io.BytesIO(cut['cutout'])).convert('RGBA')
        mask=Image.open(io.BytesIO(cut['erase'])).convert('RGBA')
        self.assertEqual(subject.getpixel((29,34)),self.im.getpixel((41,52)))
        self.assertEqual(mask.getpixel((29,34))[3],255)
        self.assertEqual(subject.getpixel((0,0))[3],0)
        self.assertEqual(mask.getpixel((0,0))[3],0)
        self.assertEqual(self.raw,before)
        egg=select_component(self.raw,155,60,1)
        self.assertEqual(egg['bounds'],[115,30,186,106])
        self.assertNotEqual(cut['bounds'],egg['bounds'])

    def test_manual_crop_is_bounded_to_selected_box(self):
        result=select_rectangle(self.raw,[10,15,80,100],1)
        self.assertEqual(result['bounds'],[10,15,80,100])
        piece=Image.open(io.BytesIO(result['cutout'])).convert('RGBA')
        erase=Image.open(io.BytesIO(result['erase'])).convert('RGBA')
        self.assertEqual(piece.getpixel((40,40)),self.im.getpixel((50,55)))
        self.assertEqual(erase.getpixel((40,40))[3],255)
        self.assertEqual(piece.getpixel((0,0))[3],0)
        with self.assertRaisesRegex(ValueError,'過大'):
            select_rectangle(self.raw,[0,0,2,2],1)

    def test_transparent_and_invalid_points_fail_safe(self):
        with self.assertRaisesRegex(ValueError,'透明背景'):
            select_component(self.raw,100,140,1)
        with self.assertRaisesRegex(ValueError,'範圍'):
            select_component(self.raw,-5,1,1)
        with self.assertRaisesRegex(ValueError,'比例'):
            select_component(self.raw,25,25,99)

    def test_preview_downsamples_without_modifying_v1(self):
        im=Image.new('RGBA',(2030,4241),(0,0,0,0))
        raw=png(im)
        resized=Image.open(io.BytesIO(preview(raw)))
        self.assertLessEqual(max(resized.size),1200)
        self.assertEqual(len(raw),len(png(im)))

    def test_erase_then_overlay_keeps_moved_component_on_overlap(self):
        im=Image.new('RGBA',(72,144),(20,90,140,255))
        original=png(im)
        erase=Image.new('RGBA',im.size)
        ImageDraw.Draw(erase).rectangle((10,20,21,29),fill=(255,255,255,255))
        overlay=Image.new('RGBA',im.size)
        ImageDraw.Draw(overlay).rectangle((18,22,27,32),fill=(200,0,0,255))
        output,_=compose(original,png(overlay),png(erase))
        result=Image.open(io.BytesIO(output)).convert('RGBA')
        self.assertEqual(result.getpixel((12,24))[3],0)
        self.assertEqual(result.getpixel((19,24)),(200,0,0,255))
        self.assertEqual(result.getpixel((50,100)),(20,90,140,255))


if __name__=='__main__':
    unittest.main()
