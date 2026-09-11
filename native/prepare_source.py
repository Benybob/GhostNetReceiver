"""Create the auditable receive-only translation unit from pinned upstream source."""
from pathlib import Path
import shutil
import sys

root=Path(__file__).resolve().parent
source=Path(sys.argv[1]).resolve()
paths=['JS8_Mode/JS8.cpp','JS8_Mode/JS8.h','JS8_Mode/DecodedText.cpp','JS8_Mode/DecodedText.h',
       'JS8_Mode/FrequencyTracker.cpp','JS8_Mode/FrequencyTracker.h','JS8_Mode/whitening_processor.h',
       'JS8_Mode/ldpc_feedback.h','JS8_Mode/soft_combiner.h','JS8_Include/commons.h',
       'JS8_Main/Varicode.cpp','JS8_Main/Varicode.h','JS8_JSC/JSC.cpp','JS8_JSC/JSC.h',
       'JS8_JSC/JSC_list.cpp','JS8_JSC/JSC_map.cpp']
for relative in paths:
    dest=root/'upstream'/relative
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source/relative,dest)
for name in ('Eigen','CRCpp'):
    shutil.copytree(source/'vendor'/name,root/'upstream'/'vendor'/name,dirs_exist_ok=True)
original=(source/'JS8_Mode'/'JS8.cpp').read_text(encoding='utf-8')
marker='/******************************************************************************/\n// Worker\n'
if original.count(marker)!=1:
    raise RuntimeError('Upstream layout changed; review extraction boundary.')
receive=original.split(marker)[0]
encoding_marker='namespace JS8 {\n// JS8 originally used'
# The numeric encoder is also used by the receiver for signal subtraction.
# Retain that math, but no transmitter/audio-output controls or GUI worker.
encoding=original[original.index('namespace JS8 {',original.index('// Public Interface - Encoding')):]
(root/'engine.cpp').write_text(receive+encoding+(root/'wrapper.cpp.inc').read_text(encoding='utf-8'),encoding='utf-8')
print('Prepared receive-only library; GUI worker and transmitter controls excluded.')
