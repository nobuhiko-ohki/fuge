"""フーガサンプル v6: ML学習済み調推移モデルによる調性経路

v5 との差分:
  - MarkovKeyPathStrategy を使用（43曲のバッハ・フーガから学習した転調パターン）
  - デフォルト戦略との比較出力
"""
import sys
import os
import shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from harmony_rules_complete import Pitch
from fugue_structure import Key, Subject, FugueStructure, FugueVoiceType
from fugue_realization import (
    FugueRealizationEngine, SUBBEATS_PER_BEAT,
)
from midi_writer import MIDIWriter
from key_transition_model import KeyTransitionModel, MarkovKeyPathStrategy

note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def chord_symbol(ch):
    root = note_names[ch.root_pc]
    q = ch.quality
    if ch.alteration_type:
        return {'neapolitan': 'bII6', 'italian': 'It+6',
                'german': 'Ger+6', 'french': 'Fr+6'}.get(ch.alteration_type, '?')
    suf = {'major': '', 'minor': 'm', 'diminished': 'dim',
           'dominant7': '7', 'minor7': 'm7', 'major7': 'maj7',
           'half_diminished7': 'm7b5', 'diminished7': 'dim7'}.get(q, '(' + q + ')')
    if ch.has_seventh and '7' not in suf:
        suf += '7'
    sym = root + suf
    if ch.is_secondary_dominant and ch.resolution_target_pc is not None:
        sym = root + '7/' + note_names[ch.resolution_target_pc]
    return sym


def total_beats(full_midi):
    max_tick = 0
    for notes in full_midi.values():
        for tick, midi, dur in notes:
            if tick + dur > max_tick:
                max_tick = tick + dur
    ticks_per_beat = SUBBEATS_PER_BEAT * 120
    return max_tick // ticks_per_beat


def write_midi(full_midi, out_path, tempo=72):
    writer = MIDIWriter(tempo=tempo, ticks_per_beat=480)
    voice_channels = {
        FugueVoiceType.SOPRANO: 0,
        FugueVoiceType.ALTO: 1,
        FugueVoiceType.TENOR: 2,
        FugueVoiceType.BASS: 3,
    }
    for vt, notes in sorted(full_midi.items(), key=lambda x: x[0].value):
        ch = voice_channels.get(vt, 0)
        writer.add_track_from_notes(notes, channel=ch)
    writer.write_file(out_path)


def generate_v6():
    # --- 学習済みモデルの読み込み ---
    model_path = os.path.join(
        os.path.dirname(__file__),
        "corpus", "models", "key_transition.json")

    if not os.path.exists(model_path):
        print(f"学習済みモデルが見つかりません: {model_path}")
        print("先に key_transition_model.py --features ... --output ... を実行してください")
        sys.exit(1)

    model = KeyTransitionModel()
    model.load(model_path)
    print(f"学習済みモデル読み込み: {model.num_sequences}曲, "
          f"{model.num_transitions}遷移, {len(model.states)}状態")

    markov_strategy = MarkovKeyPathStrategy(model, seed=42)
    markov_det_strategy = MarkovKeyPathStrategy(model, deterministic=True)

    # --- 主題定義 ---
    key_c = Key('C', 'major')
    subject = Subject(
        [Pitch(m) for m in [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60]],
        key_c, "v6主題")

    print("=" * 60)
    print("  フーガ v6: ML学習済み調推移モデル統合")
    print("=" * 60)

    # --- (A) デフォルト戦略（v5相当） ---
    print("\n--- (A) デフォルト戦略 ---")
    fs_a = FugueStructure(num_voices=3, main_key=key_c, subject=subject)
    fs_a.create_exposition(answer_type="auto")
    engine_a = FugueRealizationEngine(fs_a, seed=42)

    midi_a = engine_a.realize_fugue(
        episode_motif_length=3,
        episode_steps=4,
        episode_interval=-1,
        coda_beats=8,
    )
    beats_a = total_beats(midi_a)
    print(f"  合計: {beats_a}拍")
    for vt in [FugueVoiceType.SOPRANO, FugueVoiceType.ALTO, FugueVoiceType.BASS]:
        if vt in midi_a:
            print(f"  {vt.value}: {len(midi_a[vt])}ノート")

    # --- (B) Markov確率的戦略 ---
    print("\n--- (B) Markov確率的戦略 ---")
    fs_b = FugueStructure(num_voices=3, main_key=key_c, subject=subject)
    fs_b.create_exposition(answer_type="auto")
    engine_b = FugueRealizationEngine(fs_b, seed=42)

    midi_b = engine_b.realize_fugue(
        key_path_strategy=markov_strategy,
        episode_motif_length=3,
        episode_steps=4,
        episode_interval=-1,
        coda_beats=8,
    )
    beats_b = total_beats(midi_b)
    print(f"  合計: {beats_b}拍")
    for vt in [FugueVoiceType.SOPRANO, FugueVoiceType.ALTO, FugueVoiceType.BASS]:
        if vt in midi_b:
            print(f"  {vt.value}: {len(midi_b[vt])}ノート")

    # --- (C) Markov決定的戦略 ---
    print("\n--- (C) Markov決定的戦略 ---")
    fs_c = FugueStructure(num_voices=3, main_key=key_c, subject=subject)
    fs_c.create_exposition(answer_type="auto")
    engine_c = FugueRealizationEngine(fs_c, seed=42)

    midi_c = engine_c.realize_fugue(
        key_path_strategy=markov_det_strategy,
        episode_motif_length=3,
        episode_steps=4,
        episode_interval=-1,
        coda_beats=8,
    )
    beats_c = total_beats(midi_c)
    print(f"  合計: {beats_c}拍")
    for vt in [FugueVoiceType.SOPRANO, FugueVoiceType.ALTO, FugueVoiceType.BASS]:
        if vt in midi_c:
            print(f"  {vt.value}: {len(midi_c[vt])}ノート")

    # --- 調性経路の比較 ---
    print("\n--- 調性経路の比較 ---")

    # エンジン内部の嬉遊部調性経路を抽出
    for label, engine in [("(A) Default", engine_a),
                          ("(B) Markov-stoch", engine_b),
                          ("(C) Markov-det", engine_c)]:
        if hasattr(engine, '_last_key_paths'):
            for ep_name, kp in engine._last_key_paths.items():
                unique = []
                for i, k in enumerate(kp.beat_keys):
                    if i == 0 or k != kp.beat_keys[i - 1]:
                        unique.append(f"{k.tonic} {k.mode}")
                print(f"  {label} {ep_name}: {' → '.join(unique)}")

    # --- MIDI出力 ---
    base = os.path.dirname(__file__)
    mount = "/sessions/fervent-vigilant-hypatia/mnt/fuge"

    for suffix, midi_data in [("_default", midi_a),
                               ("_markov", midi_b),
                               ("_markov_det", midi_c)]:
        fname = f"sample_fugue_v6{suffix}.mid"
        local_path = os.path.join(base, fname)
        mount_path = os.path.join(mount, fname)
        write_midi(midi_data, local_path)
        os.makedirs(os.path.dirname(mount_path), exist_ok=True)
        shutil.copy2(local_path, mount_path)
        print(f"\nMIDI出力: {mount_path}")


if __name__ == "__main__":
    generate_v6()
