"""フーガサンプル v7: 和声進行モデル + 対旋律パターンモデル統合

v6 との差分:
  - ChordProgressionModel: バッハのコーパスから学習した和声進行パターン
  - CounterpointPatternModel: バッハの対旋律音程パターン
  - 両モデルの有無で生成結果を比較
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
from bach_harmony_model import ChordProgressionModel, CounterpointPatternModel


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


def count_unique_chords(engine):
    """エンジンが内部で生成した和声計画のユニーク和音数を返す"""
    if hasattr(engine, 'episode_chord_plan') and engine.episode_chord_plan:
        chords = [(c.root_pc, c.quality) for c in engine.episode_chord_plan]
        return len(set(chords))
    return 0


def generate_v7():
    base = os.path.dirname(__file__)
    model_dir = os.path.join(base, "corpus", "models")

    # --- モデル読み込み ---
    key_model = KeyTransitionModel()
    key_model_path = os.path.join(model_dir, "key_transition.json")
    if os.path.exists(key_model_path):
        key_model.load(key_model_path)
        print(f"調推移モデル: {key_model.num_sequences}曲, {key_model.num_transitions}遷移")
    else:
        print("調推移モデルなし")
        key_model = None

    chord_model = ChordProgressionModel()
    chord_model_path = os.path.join(model_dir, "chord_progression.json")
    if os.path.exists(chord_model_path):
        chord_model.load(chord_model_path)
        print(f"和声進行モデル: {chord_model.num_sequences}曲, {chord_model.num_transitions}遷移")
    else:
        print("和声進行モデルなし")
        chord_model = None

    cp_model = CounterpointPatternModel()
    cp_model_path = os.path.join(model_dir, "counterpoint_patterns.json")
    if os.path.exists(cp_model_path):
        cp_model.load(cp_model_path)
        print(f"対旋律モデル: {cp_model.num_patterns}パターン")
    else:
        print("対旋律モデルなし")
        cp_model = None

    # --- 主題定義 ---
    key_c = Key('C', 'major')
    subject = Subject(
        [Pitch(m) for m in [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60]],
        key_c, "v7主題")

    markov_strategy = None
    if key_model:
        markov_strategy = MarkovKeyPathStrategy(key_model, seed=42)

    print("\n" + "=" * 60)
    print("  フーガ v7: 和声進行 + 対旋律パターンモデル統合")
    print("=" * 60)

    configs = [
        ("baseline", "ルールベースのみ", None, None, None),
        ("ml_key", "調推移ML", markov_strategy, None, None),
        ("ml_harmony", "和声進行ML", None, chord_model, None),
        ("ml_counterpoint", "対旋律ML", None, None, cp_model),
        ("ml_full", "全MLモデル統合", markov_strategy, chord_model, cp_model),
    ]

    results = {}
    mount = "/sessions/fervent-vigilant-hypatia/mnt/fuge"

    for tag, label, kps, chm, cpm in configs:
        print(f"\n--- ({tag}) {label} ---")

        fs = FugueStructure(num_voices=3, main_key=key_c, subject=subject)
        fs.create_exposition(answer_type="auto")

        engine = FugueRealizationEngine(
            fs, seed=42,
            chord_model=chm,
            counterpoint_model=cpm,
        )

        midi_data = engine.realize_fugue(
            key_path_strategy=kps,
            episode_motif_length=3,
            episode_steps=4,
            episode_interval=-1,
            coda_beats=8,
        )

        beats = total_beats(midi_data)
        notes_total = sum(len(notes) for notes in midi_data.values())

        print(f"  合計: {beats}拍, {notes_total}ノート")
        for vt in [FugueVoiceType.SOPRANO, FugueVoiceType.ALTO, FugueVoiceType.BASS]:
            if vt in midi_data:
                print(f"  {vt.value}: {len(midi_data[vt])}ノート")

        # 調性経路
        if hasattr(engine, '_last_key_paths'):
            for ep_name, kp in engine._last_key_paths.items():
                unique = []
                for i, k in enumerate(kp.beat_keys):
                    if i == 0 or k != kp.beat_keys[i - 1]:
                        unique.append(f"{k.tonic} {k.mode}")
                print(f"  {ep_name}: {' → '.join(unique)}")

        # MIDI出力
        fname = f"sample_fugue_v7_{tag}.mid"
        local_path = os.path.join(base, fname)
        mount_path = os.path.join(mount, fname)
        write_midi(midi_data, local_path)
        os.makedirs(os.path.dirname(mount_path), exist_ok=True)
        shutil.copy2(local_path, mount_path)
        print(f"  MIDI: {mount_path}")

        results[tag] = {
            "beats": beats, "notes": notes_total,
            "voices": {vt.value: len(notes) for vt, notes in midi_data.items()},
        }

    # --- 比較サマリー ---
    print("\n" + "=" * 60)
    print("  比較サマリー")
    print("=" * 60)
    print(f"{'構成':<20s} {'拍数':>6s} {'総ノート':>8s} {'soprano':>8s} {'alto':>8s} {'bass':>8s}")
    print("-" * 60)
    for tag, label, _, _, _ in configs:
        r = results[tag]
        v = r['voices']
        print(f"{label:<20s} {r['beats']:>6d} {r['notes']:>8d} "
              f"{v.get('soprano', 0):>8d} {v.get('alto', 0):>8d} {v.get('bass', 0):>8d}")


if __name__ == "__main__":
    generate_v7()
