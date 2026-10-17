"""Import the user-supplied conference furniture using the established STEP pipeline."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import import_breakroom_assets as importer

importer.OUT=ROOT/'.runtime/conference-import-20261003'
importer.SOURCE=Path(r'C:/Users/might/Downloads/conference room')
importer.CATEGORY='Office & IT'
importer.DESCRIPTION='User-supplied conference furniture; CAD-derived dimensions. Installation and load ratings unverified.'
importer.TAGS=('conference','meeting','office','presentation')
importer.ITEMS=[('conference-screen','40-Inch Presentation Screen','40 inch tv.stp'),
                ('conference-chair','Conference Chair','Chair Assy STEP.STEP'),
                ('conference-table','Conference Table','conference table.STEP')]

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','prepare'])
    parser.add_argument('--rotations',type=Path)
    args=parser.parse_args()
    importer.convert() if args.phase=='convert' else importer.prepare(args.rotations)
