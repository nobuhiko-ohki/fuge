#!/usr/bin/env python3
"""
MIDIファイルから拍ごとのコード進行を抽出する。

バッハの Contrapunctus 1 (BWV 1080) 等のMIDIを入力し、
四分音符単位で和音ラベルを推定して出力する。

使い方:
    python extract_chords_from_midi.py <input.mid>

出力: 拍ごとの和音ラベル（根音, 質, 構成音PC集合）
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from midi_reader import MIDIReader, MIDIFile, MIDINote
from typing import List, Dict, Tuple, Set, Optional
from collections import Counter

# ───── 定数 ─────
NOTE_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']

# 三和音テンプレート: (quality, interval_set)
TRIAD_TEMPLATES = {
    "major":      frozenset({0, 4, 7}),
    "minor":      frozenset({0, 3, 7}),
    "diminished": frozenset({0, 3, 6}),
    "augmented":  frozenset({0, 4, 8}),
}

# 七の和音テンプレート
SEVENTH_TEMPLATES = {
    "dominant7":   frozenset({0, 4, 7, 10}),
    "major7":      frozenset({0, 4, 7, 11}),
    "minor7":      frozenset({0, 3, 7, 10}),
    "dim7":        frozenset({0, 3, 6, 9}),
    "half-dim7":   frozenset({0, 3, 6, 10}),
}


def collect_beat_pitches(midi: MIDIFile) -> Dict[int, List[Tuple[int, int]]]:
    """各拍（四分音符単位）で鳴っている音を収集する。

    Returns:
        Dict[beat_index, List[(midi_pitch, duration_weight)]]
        duration_weight: その拍内で鳴っている持続時間（tick）
    """
    tpb = midi.ticks_per_beat
    all_notes = midi.all_notes
    if not all_notes:
        return {}

    total_ticks = max(n.end_tick for n in all_notes)
    total_beats = (total_ticks + tpb - 1) // tpb

    beat_pitches: Dict[int, List[Tuple[int, int]]] = {}

    for note in all_notes:
        # この音が跨ぐ拍の範囲
        first_beat = note.start_tick // tpb
        last_beat = (note.end_tick - 1) // tpb

        for b in range(first_beat, last_beat + 1):
            beat_start = b * tpb
            beat_end = (b + 1) * tpb
            # この拍内での実際の発音区間
            sounding_start = max(note.start_tick, beat_start)
            sounding_end = min(note.end_tick, beat_end)
            weight = sounding_end - sounding_start

            if weight > 0:
                if b not in beat_pitches:
                    beat_pitches[b] = []
                beat_pitches[b].append((note.pitch, weight))

    return beat_pitches


def weighted_pcs(pitches_weights: List[Tuple[int, int]]) -> Counter:
    """ピッチクラスの加重カウンタを返す。"""
    pcs = Counter()
    for pitch, weight in pitches_weights:
        pcs[pitch % 12] += weight
    return pcs


def identify_chord(pcs: Counter) -> Optional[Tuple[str, int, str, Set[int]]]:
    """加重PCプロファイルから最尤和音を推定する。

    Returns:
        (note_name, root_pc, quality, tone_pcs) or None

    方法: 全12根音 × 全テンプレートを試し、テンプレート内のPCの
    加重合計が最大になる組み合わせを選ぶ。
    """
    if not pcs:
        return None

    total_weight = sum(pcs.values())
    best_score = -1
    best_result = None

    # 三和音を優先的に検査
    for root_pc in range(12):
        for quality, template in TRIAD_TEMPLATES.items():
            # テンプレートを root_pc に移調
            chord_pcs = {(root_pc + iv) % 12 for iv in template}
            # 和音構成音の加重合計
            score = sum(pcs.get(pc, 0) for pc in chord_pcs)
            # 和音外音のペナルティ
            outside = total_weight - score
            adjusted = score - outside * 0.3

            if adjusted > best_score:
                best_score = adjusted
                best_result = (NOTE_NAMES[root_pc], root_pc, quality, chord_pcs)

    # 七の和音も試す（三和音より良い場合のみ採用）
    for root_pc in range(12):
        for quality, template in SEVENTH_TEMPLATES.items():
            chord_pcs = {(root_pc + iv) % 12 for iv in template}
            score = sum(pcs.get(pc, 0) for pc in chord_pcs)
            outside = total_weight - score
            adjusted = score - outside * 0.2  # 七の和音は4音あるのでペナルティ緩和

            if adjusted > best_score * 1.1:  # 三和音より10%以上良い場合のみ
                best_score = adjusted
                best_result = (NOTE_NAMES[root_pc], root_pc, quality, chord_pcs)

    return best_result


def extract_chord_progression(midi: MIDIFile) -> List[Optional[Tuple[str, int, str, Set[int]]]]:
    """MIDIから拍ごとのコード進行を抽出する。"""
    beat_pitches = collect_beat_pitches(midi)
    if not beat_pitches:
        return []

    max_beat = max(beat_pitches.keys())
    progression = []

    for b in range(max_beat + 1):
        pw = beat_pitches.get(b, [])
        if not pw:
            progression.append(None)
            continue

        pcs = weighted_pcs(pw)
        chord = identify_chord(pcs)
        progression.append(chord)

    return progression


def format_chord_name(chord: Optional[Tuple[str, int, str, Set[int]]]) -> str:
    """和音を表示用文字列にフォーマット。"""
    if chord is None:
        return "---"
    name, root_pc, quality, tones = chord
    suffix = {
        "major": "",
        "minor": "m",
        "diminished": "dim",
        "augmented": "aug",
        "dominant7": "7",
        "major7": "M7",
        "minor7": "m7",
        "dim7": "dim7",
        "half-dim7": "ø7",
    }.get(quality, quality)
    return f"{name}{suffix}"


def degree_in_key(root_pc: int, key_pc: int, mode: str = "minor") -> str:
    """調性内のローマ数字表記を返す。"""
    if mode == "minor":
        # D minor: D=0 → i, E=2 → ii°, F=3 → III, G=5 → iv, A=7 → v/V, Bb=8 → VI, C#=1 → V(導音)
        degree_map = {0: "i", 1: "ii°", 2: "N", 3: "III", 4: "IV", 5: "iv",
                      6: "v(dim?)", 7: "v", 8: "VI", 9: "VII", 10: "VII", 11: "vii°"}
    else:
        degree_map = {0: "I", 2: "ii", 4: "iii", 5: "IV", 7: "V", 9: "vi", 11: "vii°"}

    interval = (root_pc - key_pc) % 12
    return degree_map.get(interval, f"?({interval})")


def print_progression(progression, key_pc: int = 2, mode: str = "minor",
                      beats_per_measure: int = 4):
    """コード進行を小節形式で表示する。"""
    total_beats = len(progression)
    total_measures = (total_beats + beats_per_measure - 1) // beats_per_measure

    print(f"\n{'='*70}")
    print(f"  抽出されたコード進行 ({total_beats}拍, {total_measures}小節)")
    print(f"  主調: {NOTE_NAMES[key_pc]} {mode}")
    print(f"{'='*70}")

    for m in range(total_measures):
        chords_in_measure = []
        for b_in_m in range(beats_per_measure):
            beat_idx = m * beats_per_measure + b_in_m
            if beat_idx < total_beats:
                chord = progression[beat_idx]
                name = format_chord_name(chord)
                chords_in_measure.append(name)
            else:
                chords_in_measure.append("")

        measure_str = " | ".join(f"{c:>6}" for c in chords_in_measure)
        print(f"  m{m+1:>2}: {measure_str}")

    print(f"{'='*70}")


def export_as_python(progression, key_pc: int = 2, mode: str = "minor",
                     var_name: str = "BACH_CHORD_PROGRESSION"):
    """Pythonコードとしてエクスポート（generate_art_of_fugue.pyに貼り付け可能）。"""
    print(f"\n# --- バッハ Contrapunctus 1 の和声進行（MIDI抽出） ---")
    print(f"# 主調: {NOTE_NAMES[key_pc]} {mode}")
    print(f"{var_name} = [")
    for i, chord in enumerate(progression):
        m = i // 4 + 1
        b = i % 4 + 1
        if chord is None:
            print(f"    None,  # m{m}.{b}")
        else:
            name, root_pc, quality, tones = chord
            tones_str = "{" + ", ".join(str(t) for t in sorted(tones)) + "}"
            print(f'    ("{name}", {root_pc}, "{quality}", {tones_str}),  # m{m}.{b} = {format_chord_name(chord)}')
    print("]")


def main():
    if len(sys.argv) < 2:
        print("使い方: python extract_chords_from_midi.py <input.mid>")
        print("        バッハのMIDIファイルから拍ごとのコード進行を抽出します。")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"ファイルが見つかりません: {filepath}")
        sys.exit(1)

    # MIDI読み込み
    reader = MIDIReader()
    midi = reader.read(filepath)

    print(f"  ファイル: {filepath}")
    print(f"  フォーマット: Type {midi.format_type}")
    print(f"  トラック数: {len(midi.tracks)}")
    print(f"  分解能: {midi.ticks_per_beat} ticks/beat")
    print(f"  総ノート数: {len(midi.all_notes)}")

    if midi.all_notes:
        total_ticks = max(n.end_tick for n in midi.all_notes)
        total_beats = total_ticks // midi.ticks_per_beat
        print(f"  総拍数: {total_beats} ({total_beats // 4}小節)")

        # ピッチ範囲で調性を推定
        all_pcs = Counter(n.pitch_class for n in midi.all_notes)
        print(f"  ピッチクラス分布: {dict(sorted(all_pcs.items()))}")

    # 和音抽出
    progression = extract_chord_progression(midi)

    # D minor (BWV 1080) として表示
    key_pc = 2  # D
    print_progression(progression, key_pc=key_pc, mode="minor")

    # Pythonコードとしてエクスポート
    export_as_python(progression, key_pc=key_pc)


if __name__ == "__main__":
    main()
