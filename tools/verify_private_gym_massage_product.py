"""Verify the recovery chair in the production renderer and optional desktop."""
import argparse
from tools import verify_private_gym_tv_set as verify
from tools.place_private_gym_massage_product import OUT, APEX, PLACEMENT, audit

verify.OUT=OUT
verify.ASSET=APEX
verify.NEW=PLACEMENT
verify.OLD=set()
verify.audit=audit
verify.render.OUT=OUT
verify.render.ASSETS=[APEX,APEX]
verify.render.LIVING=APEX
verify.render.SHOTS=[('gaming',(58.5,2.3,6.6),(55.7,.7,4.5)),
                     ('room',(57,12,6),(57,0,4.5))]

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop',action='store_true')
    args=parser.parse_args()
    verify.desktop() if args.desktop else verify.render.staged()
