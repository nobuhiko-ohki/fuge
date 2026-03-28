#!/usr/bin/env python3
"""
サンプルフーガ MIDI 生成 v2
和声分析→DP最適化による対位法的提示部
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from harmony_rules_complete import Pitch
from counterpoint_engine import CounterpointProhibitions
from fugue_structure import Key, Subject, FugueStructure
from fugue_realization import FugueRealizationEngine, VOICE_RANGES

# ============================================================
# 主題定義
# ============================================================
key_c = Key("C", "major")
subject = Subject(
    [Pitch(m) for m in [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60]],
    key_c, "主題"
)

print("=" * 60)
print("Prout準拠 3声フーガ提示部 v2（和声分析＋対位法DP）")
print("=" * 60)
print(f"主題: {' '.join(p.name for p in subject.pitches)}")
print(f"調: {key_c.tonic} {key_c.mode}")

# ============================================================
# 構造生成
# ============================================================
fs = FugueStructure(num_voices=3, main_key=key_c, subject=subject)
entries = fs.create_exposition(answer_type="auto")

for e in entries:
    kind = "応答" if e.is_answer else "主題"
    print(f"  {e.voice_type.value}: {kind} @ 拍{e.start_position}")

# ============================================================
# 実現エンジン
# ============================================================
engine = FugueRealizationEngine(fs, seed=42)
midi_events = engine.realize_exposition()

# レポート
print(engine.get_analysis_report())

# ============================================================
# 対位法検証
# ============================================================
print("\n--- 対位法検証 ---")
proh = CounterpointProhibitions()
violations = 0
melodies = engine.voice_melodies
voice_names = [v for v in melodies if any(m is not None for m in melodies[v])]

for i, v1 in enumerate(voice_names):
    for v2 in list(voice_names)[i+1:]:
        m1 = melodies[v1]
        m2 = melodies[v2]
        for beat in range(1, len(m1)):
            if any(x is None for x in [m1[beat-1], m1[beat], m2[beat-1], m2[beat]]):
                continue
            ok, msg = proh.check_parallel_perfect(
                m1[beat-1], m1[beat], m2[beat-1], m2[beat])
            if not ok:
                violations += 1
                print(f"  ✗ 拍{beat} {v1.value}-{v2.value}: {msg}")

if violations == 0:
    print("  並行5/8度違反: なし")
else:
    print(f"  並行5/8度違反: {violations}箇所")

# ============================================================
# 声部表示（ピアノロール風）
# ============================================================
print("\n--- 声部一覧（拍ごと）---")
total = len(list(melodies.values())[0])
header = "拍  "
for v in voice_names:
    header += f"| {v.value:>8} "
print(header)
print("-" * len(header))

for beat in range(total):
    line = f"{beat:3d} "
    for v in voice_names:
        m = melodies[v][beat]
        if m is not None:
            line += f"| {Pitch(m).name:>8} "
        else:
            line += f"|{'':>9} "
    print(line)

# ============================================================
# MIDI出力
# ============================================================
output = os.path.join(os.path.dirname(__file__), "sample_fugue_v2.mid")
engine.export_midi(output, tempo=72)
print(f"\nMIDI出力: {output}")

# マウントにもコピー
mount_path = "/sessions/fervent-vigilant-hypatia/mnt/fuge/sample_fugue_v2.mid"
try:
    import shutil
    shutil.copy2(output, mount_path)
    print(f"マウントにコピー: {mount_path}")
except Exception as e:
    print(f"マウントコピー失敗: {e}")
