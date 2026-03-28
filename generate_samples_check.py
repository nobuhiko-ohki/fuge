"""3調のサンプル生成 + 品質検証スクリプト"""
import sys, os, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from harmony_rules_complete import Pitch
from fugue_structure import Key, Subject, FugueStructure, FugueVoiceType
from fugue_realization import FugueRealizationEngine, SUBBEATS_PER_BEAT
from midi_writer import MIDIWriter
from fugue_quality_checker import FugueQualityChecker
from bach_harmony_model import ChordProgressionModel, CounterpointPatternModel
from key_transition_model import KeyTransitionModel, MarkovKeyPathStrategy

BASE = os.path.dirname(__file__)
REPO_DIR = "/sessions/fervent-vigilant-hypatia/mnt/fuge"
MODEL_DIR = os.path.join(BASE, "corpus", "models")

def load_models():
    chord_model = ChordProgressionModel()
    cp_model = CounterpointPatternModel()
    key_model = KeyTransitionModel()

    chord_path = os.path.join(MODEL_DIR, "chord_progression.json")
    cp_path = os.path.join(MODEL_DIR, "counterpoint_patterns.json")
    key_path = os.path.join(MODEL_DIR, "key_transition.json")

    if os.path.exists(chord_path):
        chord_model.load(chord_path)
        print(f"  chord model: {chord_model.num_transitions} transitions")
    if os.path.exists(cp_path):
        cp_model.load(cp_path)
        print(f"  counterpoint model: {cp_model.num_patterns} patterns")
    if os.path.exists(key_path):
        key_model.load(key_path)
        print(f"  key model: {key_model.num_transitions} transitions")

    return chord_model, cp_model, key_model

SAMPLES = [
    {
        "name": "C_major_3v",
        "key": Key('C', 'major'),
        "pitches": [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60],
    },
    {
        "name": "D_minor_3v",
        "key": Key('D', 'minor'),
        "pitches": [62, 64, 65, 67, 69, 67, 65, 64, 62],
    },
    {
        "name": "G_major_3v",
        "key": Key('G', 'major'),
        "pitches": [67, 69, 71, 72, 74, 72, 71, 69, 67],
    },
]

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

def main():
    chord_model, cp_model, key_model = load_models()
    all_passed = True

    for sample in SAMPLES:
        print(f"\n{'='*60}")
        print(f"  {sample['name']}")
        print(f"{'='*60}")

        key = sample["key"]
        pitches = [Pitch(m) for m in sample["pitches"]]
        subject = Subject(pitches, key, f"{sample['name']}主題")
        structure = FugueStructure(num_voices=3, main_key=key, subject=subject)

        # 各サンプルに独立したseedを使用
        markov_strategy = MarkovKeyPathStrategy(key_model, seed=42) if key_model.num_transitions > 0 else None

        engine = FugueRealizationEngine(
            structure,
            chord_model=chord_model,
            counterpoint_model=cp_model,
        )
        full_midi = engine.realize_fugue(
            key_path_strategy=markov_strategy
        )

        # 品質検証（和声情報あり）
        gct = getattr(engine, 'global_chord_tones', None)
        checker = FugueQualityChecker(full_midi, key, beat_chord_tones=gct)
        report = checker.run_all()
        n_err = len(report.errors)
        n_warn = len(report.warnings)
        print(f"  errors={n_err}, warnings={n_warn}")
        for v in report.violations:
            level = "ERROR" if v.severity == "error" else "WARN"
            loc = f"m{v.measure}.{v.beat_in_measure}"
            print(f"  [{level}] {loc}: {v.description}")

        if n_err > 0:
            all_passed = False

        # MIDI出力
        fname = f"sample_fugue_{sample['name']}.mid"
        out_path = os.path.join(BASE, fname)
        write_midi(full_midi, out_path)
        print(f"  -> {out_path}")

        # リポジトリにもコピー
        repo_path = os.path.join(REPO_DIR, fname)
        shutil.copy2(out_path, repo_path)
        print(f"  -> {repo_path}")

    print(f"\n{'='*60}")
    if all_passed:
        print("  ALL SAMPLES: 0 errors")
    else:
        print("  SOME SAMPLES HAVE ERRORS")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
