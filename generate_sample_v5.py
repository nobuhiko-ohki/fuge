"""フーガサンプル v5: 完全なフーガ（提示部→嬉遊部1→中間部1→嬉遊部2→中間部2→終止部）"""
import sys
import os
import shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from harmony_rules_complete import Pitch, NoteEvent
from fugue_structure import Key, Subject, FugueStructure, FugueVoiceType
from fugue_realization import (
    FugueRealizationEngine, VOICE_RANGES, SUBBEATS_PER_BEAT,
)
from midi_writer import MIDIWriter

note_names = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']

def chord_symbol(ch):
    root = note_names[ch.root_pc]
    q = ch.quality
    if ch.alteration_type:
        return {'neapolitan':'bII6','italian':'It+6','german':'Ger+6','french':'Fr+6'}.get(ch.alteration_type,'?')
    suf = {'major':'','minor':'m','diminished':'dim','dominant7':'7','minor7':'m7',
           'major7':'maj7','half_diminished7':'m7b5','diminished7':'dim7'}.get(q, '('+q+')')
    if ch.has_seventh and '7' not in suf:
        suf += '7'
    sym = root + suf
    if ch.is_secondary_dominant and ch.resolution_target_pc is not None:
        sym = root + '7/' + note_names[ch.resolution_target_pc]
    return sym


def generate_v5():
    key_c = Key('C', 'major')
    # 主題: C-D-E-F-G-A-G-F-E-D-C（11拍）
    subject = Subject(
        [Pitch(m) for m in [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60]],
        key_c, "v5主題")

    fs = FugueStructure(num_voices=3, main_key=key_c, subject=subject)
    fs.create_exposition(answer_type="auto")
    engine = FugueRealizationEngine(fs, seed=42)

    print("=" * 60)
    print("  フーガ全体の生成")
    print("=" * 60)

    # 調性計画を表示
    mod_plan = fs.get_modulation_plan()
    print(f"\n調性計画:")
    for label, k in mod_plan:
        print(f"  {label}: {k.tonic} {k.mode}")
    print()

    # 全体を一括生成
    full_midi = engine.realize_fugue(
        episode_motif_length=3,
        episode_steps=4,
        episode_interval=-1,
        coda_beats=8,
    )

    # --- セクション別レポート ---
    print("--- セクション構成 ---")

    # 提示部
    if hasattr(engine, 'voice_melodies'):
        expo_beats = len(list(engine.voice_melodies.values())[0])
        print(f"  提示部: {expo_beats}拍")

    # 嬉遊部の和声進行
    if hasattr(engine, 'episode_chord_plan') and engine.episode_chord_plan:
        print(f"  嬉遊部: {len(engine.episode_chord_plan)}拍")

    # 中間部
    if hasattr(engine, 'middle_entry_chord_plan') and engine.middle_entry_chord_plan:
        print(f"  中間部提示: {len(engine.middle_entry_chord_plan)}拍")

    # コーダ
    if hasattr(engine, 'coda_chord_plan') and engine.coda_chord_plan:
        coda_plan = engine.coda_chord_plan
        print(f"  終止部: {len(coda_plan)}拍")
        print(f"    カデンツ: {' → '.join(chord_symbol(c) for c in coda_plan)}")

    # 全体の拍数
    max_tick = 0
    for notes in full_midi.values():
        for tick, midi, dur in notes:
            if tick + dur > max_tick:
                max_tick = tick + dur
    ticks_per_beat = SUBBEATS_PER_BEAT * 120
    total_beats = max_tick // ticks_per_beat
    print(f"\n合計: {total_beats}拍")

    # 声部ごとのノート数
    print("\n--- 声部ノート数 ---")
    for vt in [FugueVoiceType.SOPRANO, FugueVoiceType.ALTO, FugueVoiceType.BASS]:
        if vt in full_midi:
            print(f"  {vt.value}: {len(full_midi[vt])}ノート")

    # MIDI出力
    writer = MIDIWriter(tempo=72, ticks_per_beat=480)
    voice_channels = {
        FugueVoiceType.SOPRANO: 0,
        FugueVoiceType.ALTO: 1,
        FugueVoiceType.TENOR: 2,
        FugueVoiceType.BASS: 3,
    }
    for vt, notes in sorted(full_midi.items(), key=lambda x: x[0].value):
        ch = voice_channels.get(vt, 0)
        writer.add_track_from_notes(notes, channel=ch)

    out_path = os.path.join(os.path.dirname(__file__), "sample_fugue_v5.mid")
    writer.write_file(out_path)
    print(f"\nMIDI出力: {out_path}")

    # マウントにコピー
    mount_path = "/sessions/fervent-vigilant-hypatia/mnt/fuge/sample_fugue_v5.mid"
    os.makedirs(os.path.dirname(mount_path), exist_ok=True)
    shutil.copy2(out_path, mount_path)
    print(f"マウントコピー: {mount_path}")


if __name__ == "__main__":
    generate_v5()
