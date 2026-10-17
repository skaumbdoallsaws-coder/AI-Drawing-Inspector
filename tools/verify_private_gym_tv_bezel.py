"""Reuse the complete TV placement checks for its immutable gold-bezel variant."""
import argparse
from tools import verify_private_gym_tv_set as verify
from tools.accent_private_gym_tv_bezel import OUT, ASSET, PLACEMENT, audit

verify.OUT=OUT
verify.ASSET=ASSET
verify.NEW=PLACEMENT
verify.audit=audit
verify.render.OUT=OUT
verify.render.ASSETS=[ASSET]
verify.render.LIVING=ASSET

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop',action='store_true')
    args=parser.parse_args()
    verify.desktop() if args.desktop else verify.render.staged()
