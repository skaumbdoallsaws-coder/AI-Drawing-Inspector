"""Render and verify the conference bezel without altering any editor content."""
import argparse
from io import BytesIO
from tools import verify_private_gym_tv_set as verify
from tools.accent_private_gym_conference_bezel import OUT, ASSET, PLACEMENT, audit

verify.OUT=OUT
verify.ASSET=ASSET
verify.NEW=PLACEMENT
verify.OLD=set()
verify.audit=audit
verify.render.OUT=OUT
verify.render.ASSETS=[ASSET]
verify.render.LIVING=ASSET
verify.render.SHOTS=[('gaming',(27.8,2.5,-5.1),(26,1.5,-10.85)),
                     ('screen',(26,1.85,-8.8),(26,1.585,-10.86425))]


def validate_capture(shown):
    image=verify.render.Image.open(BytesIO(shown)).convert('RGB')
    # These views deliberately contain very few colors. Check the centered
    # screen region for both gold trim and black display, not scene complexity.
    w,h=image.size
    pixels=list(image.crop((w*.3,h*.3,w*.7,h*.7)).getdata())
    assert sum(r>90 and .55*r<g<.9*r and b<.65*g for r,g,b in pixels)>10
    assert sum(max(p)<25 for p in pixels)>30
    assert len(set(pixels))>20


verify.render.validate_capture=validate_capture

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop',action='store_true')
    args=parser.parse_args()
    verify.desktop() if args.desktop else verify.render.staged()
