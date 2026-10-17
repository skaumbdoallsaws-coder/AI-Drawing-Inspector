"""Inspect the relocated lounge group with the production 3D renderer."""
import argparse
from tools import verify_private_gym_tv_set as verify
from tools.move_private_gym_lounge_seating import OUT, TV, audit

verify.OUT=OUT
verify.ASSET='asset-gym-additional-tv-unit-gold-bezel'
verify.NEW=TV
verify.OLD=set()
verify.audit=audit
verify.render.OUT=OUT
verify.render.ASSETS=[verify.ASSET,'asset-gym-living-room-1']
verify.render.LIVING='asset-gym-living-room-1'
verify.render.SHOTS=[('gaming',(11,24,-7.5),(11,0,-10.5)),
                     ('seating',(13.5,5,-11),(18,.8,-5.6))]

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop',action='store_true')
    args=parser.parse_args()
    verify.desktop() if args.desktop else verify.render.staged()
