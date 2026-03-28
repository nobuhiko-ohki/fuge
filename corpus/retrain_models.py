"""新パイプラインでの和声進行モデル再学習

VoiceAwareChordEstimator + HierarchicalKeyTracker を使用して
bach_midi コーパスから和声進行バイグラムを学習し直す。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from bach_harmony_model import ChordProgressionModel

MIDI_DIR = os.path.join(os.path.dirname(__file__), 'bach_midi', 'uncategorized')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'models')


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # フーガMIDIのみを対象（Fugue*.mid）
    fugue_dir = MIDI_DIR
    print(f"MIDI directory: {fugue_dir}")

    # 新パイプラインで学習
    print("\n=== 声部認識型和音推定 + 階層的転調追跡 ===")
    model = ChordProgressionModel(smoothing=0.01)
    model.train_from_midi_voices(fugue_dir, max_files=60)

    print(f"  学習完了: {model.num_sequences} sequences, "
          f"{model.num_transitions} transitions, "
          f"{len(model.chords)} unique chords")

    # バイグラム分析
    print("\n=== V (7, major) からの遷移 TOP10 ===")
    v_chord = (7, 'major')
    if v_chord in model.bigram_counts:
        counts = model.bigram_counts[v_chord]
        total = sum(counts.values())
        sorted_c = sorted(counts.items(), key=lambda x: -x[1])
        for chord, cnt in sorted_c[:10]:
            print(f"  V -> {chord}: {cnt} ({100*cnt/total:.1f}%)")
    else:
        print("  V和音なし")

    print("\n=== V7 (7, dom7) からの遷移 TOP10 ===")
    v7_chord = (7, 'dom7')
    if v7_chord in model.bigram_counts:
        counts = model.bigram_counts[v7_chord]
        total = sum(counts.values())
        sorted_c = sorted(counts.items(), key=lambda x: -x[1])
        for chord, cnt in sorted_c[:10]:
            print(f"  V7 -> {chord}: {cnt} ({100*cnt/total:.1f}%)")

    print("\n=== 自己遷移率 TOP10 ===")
    self_loops = []
    for chord in model.bigram_counts:
        total = sum(model.bigram_counts[chord].values())
        self_cnt = model.bigram_counts[chord].get(chord, 0)
        if total >= 5:
            self_loops.append((chord, self_cnt, total, self_cnt/total))
    self_loops.sort(key=lambda x: -x[3])
    for chord, self_cnt, total, ratio in self_loops[:10]:
        print(f"  {chord}: {self_cnt}/{total} ({100*ratio:.1f}%)")

    # V→サブドミナント率
    print("\n=== V→サブドミナント(ii, IV)率 ===")
    if v_chord in model.bigram_counts:
        counts = model.bigram_counts[v_chord]
        total = sum(counts.values())
        sd_count = sum(counts.get(c, 0) for c in counts
                       if c[0] in (2, 5))
        print(f"  {sd_count}/{total} ({100*sd_count/total:.1f}%)")

    # 保存
    out_path = os.path.join(OUTPUT_DIR, 'chord_progression.json')
    model.save(out_path)
    print(f"\n保存: {out_path}")


if __name__ == '__main__':
    main()
