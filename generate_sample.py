#!/usr/bin/env python3
"""
サンプルフーガ MIDI 生成スクリプト
Prout "Fugue" (1891) 準拠の3声フーガ

BWV 846（平均律クラヴィーア曲集 第1巻 第1番 ハ長調）の
主題を参考にした簡潔な主題による3声フーガの提示部＋エピソード＋中間提示を生成。
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from harmony_rules_complete import Pitch
from fugue_structure import (
    Key, Subject, FugueStructure, FugueVoiceType,
    Codetta, Episode, AnswerType,
)
from midi_writer import MIDIWriter, Voice

# ============================================================
# 主題定義（ハ長調、Prout Ch.I-II準拠）
# ============================================================
#
# 主題: C4-D4-E4-F4-G4-A4-G4-F4-E4-D4-C4
# 音階的上行→下行のアーチ型旋律。
# Prout: 「明確な調性感を持ち、強い旋律的輪郭を有すること」

subject_pitches = [
    Pitch(60),  # C4
    Pitch(62),  # D4
    Pitch(64),  # E4
    Pitch(65),  # F4
    Pitch(67),  # G4
    Pitch(69),  # A4
    Pitch(67),  # G4
    Pitch(65),  # F4
    Pitch(64),  # E4
    Pitch(62),  # D4
    Pitch(60),  # C4
]

key_c = Key("C", "major")
subject = Subject(subject_pitches, key_c, name="主題")

print("=" * 60)
print("Prout準拠 3声フーガ サンプル生成")
print("=" * 60)
print(f"\n主題: {' - '.join(p.name for p in subject.pitches)}")
print(f"調: {key_c.tonic} {key_c.mode}")
print(f"音符数: {subject.get_length()}")

# ============================================================
# 調的応答判定（Prout Ch.III）
# ============================================================
needs_tonal = subject.needs_tonal_answer()
answer_type_str = "tonal" if needs_tonal else "real"
print(f"\n応答タイプ自動判定: {answer_type_str}")

answer = subject.get_answer(answer_type_str)
print(f"応答: {' - '.join(p.name for p in answer.pitches)}")

# ============================================================
# フーガ構造生成（Prout Ch.I-X 統合）
# ============================================================
fugue = FugueStructure(num_voices=3, main_key=key_c, subject=subject)

# --- 提示部 (Prout Ch.I §1-3) ---
entries = fugue.create_exposition(answer_type="auto")
print(f"\n--- 提示部 ---")
for e in entries:
    kind = "応答" if e.is_answer else "主題"
    print(f"  {e.voice_type.value}: {kind} @ position {e.start_position}")
    print(f"    音列: {' - '.join(p.name for p in e.subject.pitches)}")

# --- コデッタ確認 ---
if fugue.codettas:
    print(f"\nコデッタ: {len(fugue.codettas)}個")
    for i, c in enumerate(fugue.codettas):
        print(f"  #{i+1}: {' - '.join(p.name for p in c.pitches)}")

# --- エピソード (Prout Ch.VII) ---
expo_end = fugue.sections[-1][2] if fugue.sections else subject.get_length() * 3
episode = fugue.create_episode(
    start_position=expo_end,
    motif_length=3,
    sequence_steps=3,
    step_interval=-2,
)
ep_pitches = episode.generate_pitches()
print(f"\n--- エピソード ---")
print(f"  動機: {' - '.join(p.name for p in episode.motif_pitches)}")
print(f"  反復: {episode.sequence_steps}回")
print(f"  音列: {' - '.join(p.name for p in ep_pitches)}")

# --- 中間提示 (Prout Ch.IX) ---
ep_end = expo_end + episode.get_total_length()
mid_key = key_c.get_relative_key()  # イ短調
mid_entry = fugue.add_middle_entry(start_position=ep_end, target_key=mid_key)
print(f"\n--- 中間提示 ---")
print(f"  調: {mid_key.tonic} {mid_key.mode}")
print(f"  音列: {' - '.join(p.name for p in mid_entry.subject.pitches)}")

# --- ストレット (Prout Ch.VIII) ---
stretto_start = ep_end + subject.get_length()
feasible, errors = fugue.check_stretto_feasibility(overlap_distance=3)
print(f"\n--- ストレット実現可能性 (overlap=3) ---")
print(f"  可能: {feasible}")
if errors:
    for e in errors:
        print(f"  問題: {e}")

if feasible:
    fugue.add_stretto(start_position=stretto_start, overlap_distance=3)
    print(f"  ストレット追加: position {stretto_start}")

# --- 調性計画 (Prout Ch.IX) ---
plan = fugue.get_modulation_plan()
print(f"\n--- 調性計画 ---")
for label, k in plan:
    print(f"  {label}: {k.tonic} {k.mode}")

# --- 構造サマリー ---
print(f"\n{fugue.get_section_info()}")

# ============================================================
# MIDI生成
# ============================================================
print("\n" + "=" * 60)
print("MIDI 生成")
print("=" * 60)

midi = MIDIWriter(tempo=72, ticks_per_beat=480)
ticks_per_note = 480  # 四分音符1つ分

# 声部ごとにMIDIトラックを構成
# 声部割り当て: Alto(提示部Entry1) → Soprano(Entry2) → Bass(Entry3) → Episode → Middle Entry → Stretto

# まず各声部の音符データを時間軸上に配置
voice_notes = {
    'soprano': [],
    'alto': [],
    'bass': [],
}

# 提示部エントリの配置
for entry in entries:
    voice_name = entry.voice_type.value
    start_tick = entry.start_position * ticks_per_note
    for i, p in enumerate(entry.subject.pitches):
        note_start = start_tick + i * ticks_per_note
        voice_notes[voice_name].append((note_start, p.midi, ticks_per_note))

# エピソード: アルト声部に配置
ep_start_tick = expo_end * ticks_per_note
for i, p in enumerate(ep_pitches):
    note_start = ep_start_tick + i * ticks_per_note
    voice_notes['alto'].append((note_start, p.midi, ticks_per_note))

# 中間提示: ソプラノ声部に配置
mid_start_tick = ep_end * ticks_per_note
for i, p in enumerate(mid_entry.subject.pitches):
    note_start = mid_start_tick + i * ticks_per_note
    voice_notes['soprano'].append((note_start, p.midi, ticks_per_note))

# ストレットが追加された場合
if feasible:
    stretto_entries = [e for e in fugue.entries if e.start_position >= stretto_start]
    for entry in stretto_entries:
        voice_name = entry.voice_type.value
        start_tick = entry.start_position * ticks_per_note
        for i, p in enumerate(entry.subject.pitches):
            note_start = start_tick + i * ticks_per_note
            voice_notes[voice_name].append((note_start, p.midi, ticks_per_note))

# 各声部をMIDIトラックとして追加
channel_map = {'soprano': 0, 'alto': 1, 'bass': 2}
for voice_name in ['soprano', 'alto', 'bass']:
    notes = voice_notes[voice_name]
    if notes:
        midi.add_track_from_notes(notes, channel=channel_map[voice_name])
        print(f"  {voice_name}: {len(notes)} 音符")

# ファイル書き出し
output_path = os.path.join(os.path.dirname(__file__), "sample_fugue.mid")
midi.write_file(output_path)
print(f"\n✓ MIDI生成完了: {output_path}")

# 各声部の音域確認
print("\n--- 音域チェック ---")
for voice_name in ['soprano', 'alto', 'bass']:
    notes = voice_notes[voice_name]
    if notes:
        midi_vals = [n[1] for n in notes]
        low = min(midi_vals)
        high = max(midi_vals)
        print(f"  {voice_name}: {Pitch(low).name} - {Pitch(high).name} (MIDI {low}-{high})")

# 総音符数と総小節数
total_notes = sum(len(v) for v in voice_notes.values())
total_ticks = max(n[0] + n[2] for v in voice_notes.values() for n in v) if total_notes > 0 else 0
total_beats = total_ticks / ticks_per_note
print(f"\n総音符数: {total_notes}")
print(f"総拍数: {total_beats}")
print(f"推定小節数: {total_beats / 4:.1f} (4/4拍子)")
print(f"テンポ: 72 BPM")
print(f"推定演奏時間: {total_beats / 72 * 60:.1f} 秒")
