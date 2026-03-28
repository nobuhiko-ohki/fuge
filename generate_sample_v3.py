#!/usr/bin/env python3
"""
サンプルフーガ MIDI 生成 v3
八分音符・十六分音符対応（サブビートグリッド + RhythmElaborator）
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from harmony_rules_complete import Pitch, NoteEvent
from counterpoint_engine import CounterpointProhibitions
from fugue_structure import Key, Subject, FugueStructure, FugueVoiceType
from fugue_realization import (
    FugueRealizationEngine, VOICE_RANGES, SUBBEATS_PER_BEAT,
)

MOUNT = "/sessions/fervent-vigilant-hypatia/mnt/fuge"


def generate_and_report(name, subject, key, seed=42):
    """1つのフーガを生成してレポート + MIDI出力"""
    print("\n" + "=" * 60)
    print(f"  {name}")
    print("=" * 60)

    # 主題情報
    print(f"調: {key.tonic} {key.mode}")
    print(f"主題音: {' '.join(p.name for p in subject.pitches)}")
    note_strs = []
    dur_names = {1: '16th', 2: '8th', 3: 'd8th', 4: 'qtr', 6: 'd.qtr', 8: 'half'}
    for n in subject.notes:
        dname = dur_names.get(n.duration, f'{n.duration}sb')
        note_strs.append(f"{n.pitch.name}({dname})")
    print(f"主題NoteEvent: {' '.join(note_strs)}")
    print(f"主題長: {subject.get_length()}拍 ({subject.get_length_subbeats()}サブビート)")

    # 構造生成
    fs = FugueStructure(num_voices=3, main_key=key, subject=subject)
    entries = fs.create_exposition(answer_type="auto")
    for e in entries:
        kind = "応答" if e.is_answer else "主題"
        print(f"  {e.voice_type.value}: {kind} @ 拍{e.start_position}")

    # 実現
    engine = FugueRealizationEngine(fs, seed=seed)
    midi_events = engine.realize_exposition()
    print(engine.get_analysis_report())

    # 対位法検証（beat-level）
    print("\n--- 対位法検証（拍レベル）---")
    proh = CounterpointProhibitions()
    violations = 0
    melodies = engine.voice_melodies
    voice_names = [v for v in melodies if any(m is not None for m in melodies[v])]
    for i, v1 in enumerate(voice_names):
        for v2 in list(voice_names)[i+1:]:
            m1, m2 = melodies[v1], melodies[v2]
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

    # 声部一覧（拍レベル）
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

    # サブビートグリッド表示（最初の数拍のみ）
    if hasattr(engine, 'subbeat_grid') and engine.subbeat_grid:
        print("\n--- サブビートグリッド（先頭16サブビート = 4拍）---")
        sb_header = "sb   "
        active_sb_voices = [v for v in engine.subbeat_grid
                            if any(x is not None for x in engine.subbeat_grid[v])]
        for v in active_sb_voices:
            sb_header += f"| {v.value:>8} "
        print(sb_header)
        print("-" * len(sb_header))
        show_sb = min(16, len(list(engine.subbeat_grid.values())[0]))
        for sb in range(show_sb):
            beat_marker = f"[{sb//4}]" if sb % 4 == 0 else "   "
            line = f"{sb:3d}{beat_marker}"
            for v in active_sb_voices:
                g = engine.subbeat_grid[v][sb]
                if g is not None:
                    line += f"| {Pitch(g).name:>8} "
                else:
                    line += f"|{'':>9} "
            print(line)

    # MIDI出力統計
    print("\n--- MIDI出力統計 ---")
    for voice, notes in midi_events.items():
        if not notes:
            continue
        durations = [dur for _, _, dur in notes]
        dur_counts = {}
        for d in durations:
            dur_counts[d] = dur_counts.get(d, 0) + 1
        dur_desc = []
        tick_names = {120: '16th', 240: '8th', 360: 'd8th', 480: 'qtr',
                      720: 'd.qtr', 960: 'half'}
        for ticks, count in sorted(dur_counts.items()):
            tname = tick_names.get(ticks, f'{ticks}t')
            dur_desc.append(f"{tname}×{count}")
        print(f"  {voice.value}: {len(notes)}音 ({', '.join(dur_desc)})")

    return engine, name


# ============================================================
# サンプル1: 四分音符主題（既存互換）+ リズム装飾
# ============================================================
key_c = Key("C", "major")
subject_q = Subject(
    [Pitch(m) for m in [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60]],
    key_c, "四分音符主題"
)

engine1, name1 = generate_and_report(
    "v3a: 四分音符主題 + リズム装飾", subject_q, key_c, seed=42)

# ============================================================
# サンプル2: 混合音価主題（八分音符入り）
# ============================================================
# WTC I Fugue 2 風: 八分音符の走句を含む主題
subject_mixed = Subject([
    NoteEvent(Pitch(60), 4),   # C4 四分
    NoteEvent(Pitch(62), 2),   # D4 八分
    NoteEvent(Pitch(64), 2),   # E4 八分
    NoteEvent(Pitch(65), 4),   # F4 四分
    NoteEvent(Pitch(67), 2),   # G4 八分
    NoteEvent(Pitch(65), 2),   # F4 八分
    NoteEvent(Pitch(64), 2),   # E4 八分
    NoteEvent(Pitch(62), 2),   # D4 八分
    NoteEvent(Pitch(60), 4),   # C4 四分
], key_c, "混合音価主題")

engine2, name2 = generate_and_report(
    "v3b: 混合音価主題（八分音符入り）", subject_mixed, key_c, seed=42)

# ============================================================
# MIDI出力
# ============================================================
import shutil

for engine, tag in [(engine1, "v3a"), (engine2, "v3b")]:
    local = os.path.join(os.path.dirname(__file__), f"sample_fugue_{tag}.mid")
    engine.export_midi(local, tempo=72)
    print(f"\nMIDI出力: {local}")
    mount_path = os.path.join(MOUNT, f"sample_fugue_{tag}.mid")
    try:
        shutil.copy2(local, mount_path)
        print(f"マウントにコピー: {mount_path}")
    except Exception as e:
        print(f"マウントコピー失敗: {e}")

print("\n完了")
