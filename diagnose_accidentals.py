"""臨時記号周辺の不自然さを診断するスクリプト"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from harmony_rules_complete import Pitch
from fugue_structure import Key, Subject, FugueStructure, FugueVoiceType
from fugue_realization import FugueRealizationEngine, SUBBEATS_PER_BEAT
from fugue_quality_checker import FugueQualityChecker
from bach_harmony_model import ChordProgressionModel, CounterpointPatternModel
from key_transition_model import KeyTransitionModel, MarkovKeyPathStrategy

NOTE_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']

def midi_to_name(m):
    if m is None: return '---'
    return f"{NOTE_NAMES[m % 12]}{m // 12 - 1}"

def main():
    BASE = os.path.dirname(__file__)
    MODEL_DIR = os.path.join(BASE, "corpus", "models")

    chord_model = ChordProgressionModel()
    cp_model = CounterpointPatternModel()
    key_model = KeyTransitionModel()
    for path, model in [
        ("chord_progression.json", chord_model),
        ("counterpoint_patterns.json", cp_model),
        ("key_transition.json", key_model),
    ]:
        p = os.path.join(MODEL_DIR, path)
        if os.path.exists(p):
            model.load(p)

    markov = MarkovKeyPathStrategy(key_model, seed=77) if key_model.num_transitions > 0 else None

    SAMPLES = [
        {"name": "C_major_3v", "key": Key('C', 'major'),
         "pitches": [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60]},
        {"name": "D_minor_3v", "key": Key('D', 'minor'),
         "pitches": [62, 64, 65, 67, 69, 67, 65, 64, 62]},
        {"name": "G_major_3v", "key": Key('G', 'major'),
         "pitches": [67, 69, 71, 72, 74, 72, 71, 69, 67]},
    ]

    for sample in SAMPLES:
        print(f"\n{'='*70}")
        print(f"  {sample['name']}")
        print(f"{'='*70}")

        key = sample["key"]
        pitches = [Pitch(m) for m in sample["pitches"]]
        subject = Subject(pitches, key, f"{sample['name']}主題")
        structure = FugueStructure(num_voices=3, main_key=key, subject=subject)

        engine = FugueRealizationEngine(
            structure, chord_model=chord_model, counterpoint_model=cp_model)
        full_midi = engine.realize_fugue(key_path_strategy=markov)

        gct = getattr(engine, 'global_chord_tones', None)

        expo_len = getattr(structure, "exposition_length", "?")
        print(f"  Main key: {key}")
        print(f"  Exposition length: {expo_len} beats")

        if hasattr(engine, '_last_key_paths'):
            for ep_name, kp in engine._last_key_paths.items():
                keys_str = [str(k) for k in kp.beat_keys] if hasattr(kp, "beat_keys") else [str(kp)]
                print(f"  {ep_name} key path: {keys_str}")

        # episode_chord_plan の内容を表示
        if hasattr(engine, 'episode_chord_plan') and engine.episode_chord_plan:
            print(f"  Episode chord plan ({len(engine.episode_chord_plan)} beats):")
            for i, ch in enumerate(engine.episode_chord_plan):
                print(f"    ep_beat {i}: root_pc={ch.root_pc} quality={ch.quality} tones={sorted(ch.tones)}")

        # 拍ごとのピッチマップを構築
        max_tick = 0
        for notes in full_midi.values():
            for t, m, d in notes:
                if t + d > max_tick:
                    max_tick = t + d
        tpb = SUBBEATS_PER_BEAT * 120
        total_beats = max_tick // tpb + 1

        beat_pitches = {}
        for vt, notes in full_midi.items():
            for tick, midi_val, dur in notes:
                beat = tick // tpb
                if beat not in beat_pitches:
                    beat_pitches[beat] = {}
                if vt not in beat_pitches[beat]:
                    beat_pitches[beat][vt] = midi_val
                elif tick % tpb == 0:
                    beat_pitches[beat][vt] = midi_val

        # 品質チェック
        checker = FugueQualityChecker(full_midi, key, beat_chord_tones=gct)
        report = checker.run_all()

        warn_beats = set()
        for v in report.violations:
            warn_beats.add(v.beat)

        display_beats = set()
        for b in warn_beats:
            for offset in range(-3, 4):
                if 0 <= b + offset < total_beats:
                    display_beats.add(b + offset)

        if not display_beats:
            print("  No violations found!")
            continue

        print(f"\n  Beat-by-beat (warning areas ±3):")
        print(f"  {'Beat':>5} {'Meas':>7} {'Sop':>6} {'Alto':>6} {'Bass':>6}  ChordTones            Notes")
        print(f"  {'-'*75}")

        for beat in sorted(display_beats):
            measure = beat // 4 + 1
            beat_in_m = beat % 4 + 1
            marker = "**" if beat in warn_beats else "  "

            bp = beat_pitches.get(beat, {})
            sop = midi_to_name(bp.get(FugueVoiceType.SOPRANO))
            alto = midi_to_name(bp.get(FugueVoiceType.ALTO))
            bass = midi_to_name(bp.get(FugueVoiceType.BASS))

            ct_str = ""
            if gct and beat in gct:
                ct_pcs = sorted(gct[beat])
                ct_str = ",".join(NOTE_NAMES[pc] for pc in ct_pcs)

            nct_info = ""
            for vt_label, vt_enum in [("S", FugueVoiceType.SOPRANO), ("A", FugueVoiceType.ALTO), ("B", FugueVoiceType.BASS)]:
                if vt_enum in bp and gct and beat in gct:
                    pc = bp[vt_enum] % 12
                    if pc not in gct[beat]:
                        nct_info += f" {vt_label}:NCT({NOTE_NAMES[pc]})"

            print(f"  {beat:>5} m{measure:>2}.{beat_in_m} {marker} {sop:>6} {alto:>6} {bass:>6}  [{ct_str:<20}] {nct_info}")

        print(f"\n  Violations detail:")
        for v in report.violations:
            print(f"    m{v.measure}.{v.beat_in_measure} [{v.severity}] {v.description}")
            if gct and v.beat in gct:
                ct_pcs = sorted(gct[v.beat])
                print(f"      chord_tones: {[NOTE_NAMES[pc] for pc in ct_pcs]}")
            bp = beat_pitches.get(v.beat, {})
            for vt, m in sorted(bp.items(), key=lambda x: x[0].value):
                in_ch = ""
                if gct and v.beat in gct:
                    in_ch = "chord" if m % 12 in gct[v.beat] else "NCT"
                print(f"      {vt.value}: {midi_to_name(m)} (pc={m%12}) {in_ch}")

if __name__ == "__main__":
    main()
