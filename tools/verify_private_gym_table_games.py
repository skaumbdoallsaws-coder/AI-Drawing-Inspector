"""Verify the staged table games with InspectorPro's actual Three.js adapter."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import verify_private_gym_powerlifting as render
from tools.add_private_gym_table_games import OUT,A,P,decision

render.OUT,render.A,render.P=OUT,A,P
replace=decision()['replaceCovered']
fx,fz=(11,-6) if replace else (9,-15.3)
bx,bz=(9,-15.3) if replace else (20.35,-16.2)
render.SHOTS=[
    ('foosball','room',(fx+2.2,2.2,fz+2.6),(fx,.55,fz),['foosball']),
    ('blackjack','room',(bx+1.8,2.2,bz+2.8),(bx,.55,bz),['blackjack']),
    ('organizer','room',(3.4,1.8,-13.8),(.95,1,-15.8),['organizer']),
    ('balls','room',(3.9,1.85,-10.3),(2.65,.78,-11.5),['balls']),
    ('room-overview','room',(14,17,-7),(11,0,-11),['foosball','blackjack','organizer','balls']),
]

if __name__=='__main__':
    render.main()
