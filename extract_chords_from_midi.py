#!/usr/bin/env python3
"""
MIDIファイルから拍ごとのコード進行を抽出する。

バッハの Contrapunctus 1 (BWV 1080) 等のMIDIを入力し、
四分音符単位で和音ラベルを推定して出力する。

使い方:
    python extract_chords_from_midi.py <input.mid>
    python extract_chords_from_midi.py <input.mid> --diatonic   # 調性優先モード

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

# ───── 調性ごとのダイアトニック和音候補 ─────

def get_diatonic_candidates(key_pc: int, mode: str = "minor") -> List[Tuple[int, str, frozenset]]:
    """指定調のダイアトニック和音候補を返す。

    バッハのスタイルで実際に使われる和音（三和音＋主要七の和音＋副属和音）に絞る。
    augmented は和声短音階の III+ のみ許容するが、バッハではほぼ使われないため除外。

    Returns:
        [(root_pc, quality, template_frozenset), ...]
    """
    candidates = []

    if mode == "minor":
        # 自然短音階上の三和音
        # 音程: i=0, ii°=2, III=3, iv=5, v=7, VI=8, VII=10
        # 注: V (A major) を v (A minor) より前に配置。
        #     バッハのDmではV(A major)の方がv(Am)より出現頻度が高いため。
        natural_triads = [
            (0, "minor"),       # i
            (2, "diminished"),  # ii°
            (3, "major"),       # III
            (5, "minor"),       # iv
            (8, "major"),       # VI
            (10, "major"),      # VII
            (7, "minor"),       # v (自然短) ← V(major)より後に配置
        ]
        for interval, quality in natural_triads:
            root = (key_pc + interval) % 12
            candidates.append((root, quality, TRIAD_TEMPLATES[quality]))

        # 和声短音階: V (major), vii° (dim) ← V を v の前に追加済み
        dom = (key_pc + 7) % 12
        lead = (key_pc + 11) % 12
        candidates.append((dom, "major", TRIAD_TEMPLATES["major"]))       # V
        candidates.append((lead, "diminished", TRIAD_TEMPLATES["diminished"]))  # vii°

        # 七の和音
        candidates.append((dom, "dominant7", SEVENTH_TEMPLATES["dominant7"]))      # V7
        candidates.append((lead, "dim7", SEVENTH_TEMPLATES["dim7"]))               # vii°7
        candidates.append((lead, "half-dim7", SEVENTH_TEMPLATES["half-dim7"]))     # viiø7
        # ii°7, ii ø7
        ii_root = (key_pc + 2) % 12
        candidates.append((ii_root, "half-dim7", SEVENTH_TEMPLATES["half-dim7"]))  # iiø7
        candidates.append((ii_root, "dim7", SEVENTH_TEMPLATES["dim7"]))            # ii°7

        # 副属和音: V/V = E major (D minor の場合)
        v_of_v = (key_pc + 2) % 12  # II度の長和音
        candidates.append((v_of_v, "major", TRIAD_TEMPLATES["major"]))

    else:  # major
        # 長音階上の三和音: I=0, ii=2, iii=4, IV=5, V=7, vi=9, vii°=11
        major_triads = [
            (0, "major"),       # I
            (2, "minor"),       # ii
            (4, "minor"),       # iii
            (5, "major"),       # IV
            (7, "major"),       # V
            (9, "minor"),       # vi
            (11, "diminished"), # vii°
        ]
        for interval, quality in major_triads:
            root = (key_pc + interval) % 12
            candidates.append((root, quality, TRIAD_TEMPLATES[quality]))

        # 七の和音
        dom = (key_pc + 7) % 12
        lead = (key_pc + 11) % 12
        ii_root = (key_pc + 2) % 12
        candidates.append((dom, "dominant7", SEVENTH_TEMPLATES["dominant7"]))       # V7
        candidates.append((lead, "half-dim7", SEVENTH_TEMPLATES["half-dim7"]))      # viiø7
        candidates.append((ii_root, "minor7", SEVENTH_TEMPLATES["minor7"]))         # ii7

    # 重複除去（同じ root_pc × quality の組み合わせ）
    seen = set()
    unique = []
    for item in candidates:
        key = (item[0], item[1])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def collect_beat_pitches(midi: MIDIFile) -> Dict[int, List[Tuple[int, int]]]:
    """各拍（四分音符単位）で鳴っている音を収集する。

    Returns:
        Dict[beat_index, List[(midi_pitch, duration_weight)]]
        duration_weight: その拍内で鳴っている持続時間（tick）

    重み付けの方針:
    - 拍頭（先頭 1/4 以内）に始まる音: フルウェイト
    - それ以外のタイミングで始まる音（経過音の可能性）: ウェイトを半減
    - 前の拍から持続している音（当拍には始まっていない）: ウェイトを半減
    """
    tpb = midi.ticks_per_beat
    attack_window = tpb // 4  # 拍頭と見なす許容範囲（1/4 拍以内）
    all_notes = midi.all_notes
    if not all_notes:
        return {}

    total_ticks = max(n.end_tick for n in all_notes)
    total_beats = (total_ticks + tpb - 1) // tpb

    beat_pitches: Dict[int, List[Tuple[int, int]]] = {}

    for note in all_notes:
        first_beat = note.start_tick // tpb
        last_beat = (note.end_tick - 1) // tpb

        for b in range(first_beat, last_beat + 1):
            beat_start = b * tpb
            beat_end = (b + 1) * tpb
            sounding_start = max(note.start_tick, beat_start)
            sounding_end = min(note.end_tick, beat_end)
            weight = sounding_end - sounding_start

            if weight <= 0:
                continue

            # 拍頭アタック判定: この拍の開始近くで始まっている音かどうか
            is_attack = abs(note.start_tick - beat_start) <= attack_window
            # 経過音（当拍の中ほどから始まる）は重みを半減
            if not is_attack:
                weight = weight // 2

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


def bass_pc(pitches_weights: List[Tuple[int, int]]) -> Optional[int]:
    """拍内の最低ピッチのピッチクラスを返す（バス音推定）。"""
    if not pitches_weights:
        return None
    return min(pitches_weights, key=lambda x: x[0])[0] % 12


def identify_chord(pcs: Counter) -> Optional[Tuple[str, int, str, Set[int]]]:
    """加重PCプロファイルから最尤和音を推定する（調性なしモード）。

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

    # 品質優先度: 同スコア時に augmented を避ける
    quality_pref = {
        "major": 0.002, "minor": 0.002,
        "diminished": 0.001, "dominant7": 0.001,
        "major7": 0.001, "minor7": 0.001,
        "dim7": 0.0005, "half-dim7": 0.0005,
        "augmented": 0.0,  # augmented は最下位
    }

    # 三和音を優先的に検査
    for root_pc in range(12):
        for quality, template in TRIAD_TEMPLATES.items():
            chord_pcs = {(root_pc + iv) % 12 for iv in template}
            score = sum(pcs.get(pc, 0) for pc in chord_pcs)
            outside = total_weight - score
            adjusted = score - outside * 0.3 + quality_pref.get(quality, 0)

            if adjusted > best_score:
                best_score = adjusted
                best_result = (NOTE_NAMES[root_pc], root_pc, quality, chord_pcs)

    # 七の和音も試す（三和音より良い場合のみ採用）
    for root_pc in range(12):
        for quality, template in SEVENTH_TEMPLATES.items():
            chord_pcs = {(root_pc + iv) % 12 for iv in template}
            score = sum(pcs.get(pc, 0) for pc in chord_pcs)
            outside = total_weight - score
            adjusted = score - outside * 0.2 + quality_pref.get(quality, 0)

            if adjusted > best_score * 1.1:  # 三和音より10%以上良い場合のみ
                best_score = adjusted
                best_result = (NOTE_NAMES[root_pc], root_pc, quality, chord_pcs)

    return best_result


def identify_chord_diatonic(
    pcs: Counter,
    key_pc: int,
    mode: str = "minor",
    context_chord: Optional[Tuple[str, int, str, Set[int]]] = None,
) -> Optional[Tuple[str, int, str, Set[int]]]:
    """調性を考慮した和音推定。ダイアトニック候補のみを対象とする。

    Args:
        pcs: ピッチクラスの加重カウンタ
        key_pc: 主音のピッチクラス
        mode: "major" または "minor"
        context_chord: 前後の確定済み和音（単音拍のコンテキスト補正用）

    Returns:
        (note_name, root_pc, quality, tone_pcs) or None
    """
    if not pcs:
        return None

    total_weight = sum(pcs.values())
    present_pcs = set(pcs.keys())
    n_distinct = len(present_pcs)
    candidates = get_diatonic_candidates(key_pc, mode)

    # 品質優先度（同スコア時のタイブレーク）
    quality_pref = {
        "major": 0.003, "minor": 0.003,
        "dominant7": 0.002, "minor7": 0.002,
        "diminished": 0.001,
        "dim7": 0.001, "half-dim7": 0.001,
    }

    best_score = -999.0
    best_triad_score = -999.0  # 三和音の最高スコアを追跡
    best_result = None

    for root_pc, quality, template in candidates:
        chord_pcs = {(root_pc + iv) % 12 for iv in template}
        covered = len(chord_pcs & present_pcs)

        # 七の和音は2音以上一致しないと採用しない
        is_seventh = len(template) >= 4
        if is_seventh and covered < 2:
            continue

        # 加重スコア: 和音構成音の重みの合計
        score = sum(pcs.get(pc, 0) for pc in chord_pcs)
        outside = total_weight - score

        # 外音ペナルティ（一律 0.35）
        adjusted = score - outside * 0.35

        # カバー数ボーナス
        adjusted += covered * 0.5

        # 品質優先度（微小タイブレーク）
        adjusted += quality_pref.get(quality, 0)

        # コンテキストボーナス（単音・2音拍のみ）
        if context_chord is not None and n_distinct <= 2:
            ctx_root = context_chord[1]
            ctx_tones: Set[int] = set(context_chord[3])

            # (a) 根音一致: 同じ和音の継続
            if root_pc == ctx_root:
                adjusted += total_weight * 0.25

            # (b) 和声延長: 現在の全音がコンテキスト和音の構成音に含まれる
            # → コンテキスト和音の根音を持つ候補を優遇
            if present_pcs.issubset(ctx_tones) and root_pc == ctx_root:
                adjusted += total_weight * 0.20

        # 七の和音は三和音の最高スコアの 1.05 倍を超えないと採用しない
        if is_seventh and adjusted <= best_triad_score * 1.05:
            continue

        if adjusted > best_score:
            best_score = adjusted
            best_result = (NOTE_NAMES[root_pc], root_pc, quality, chord_pcs)
            if not is_seventh:
                best_triad_score = adjusted

    return best_result


def _fill_context(
    progression: List[Optional[Tuple]],
    idx: int,
    window: int = 4,
) -> Optional[Tuple]:
    """index の前後 window 拍から最も近い非 None の和音を返す。"""
    for delta in range(1, window + 1):
        if idx - delta >= 0 and progression[idx - delta] is not None:
            return progression[idx - delta]
        if idx + delta < len(progression) and progression[idx + delta] is not None:
            return progression[idx + delta]
    return None


def extract_chord_progression(
    midi: MIDIFile,
    key_pc: int = 0,
    mode: str = "major",
    diatonic: bool = False,
) -> List[Optional[Tuple[str, int, str, Set[int]]]]:
    """MIDIから拍ごとのコード進行を抽出する。

    Args:
        midi: MIDIFile オブジェクト
        key_pc: 主音のピッチクラス（0=C, 2=D, 7=G, ...）
        mode: "major" または "minor"
        diatonic: True のとき調性優先モード（ダイアトニック候補に絞る）
    """
    beat_pitches = collect_beat_pitches(midi)
    if not beat_pitches:
        return []

    max_beat = max(beat_pitches.keys())
    progression: List[Optional[Tuple]] = []

    for b in range(max_beat + 1):
        pw = beat_pitches.get(b, [])
        if not pw:
            progression.append(None)
            continue

        pcs = weighted_pcs(pw)
        if diatonic:
            chord = identify_chord_diatonic(pcs, key_pc, mode)
        else:
            chord = identify_chord(pcs)
        progression.append(chord)

    # 調性優先モードのみ: 後処理2パス
    if diatonic:
        beat_pitches_set: Dict[int, Set[int]] = {
            b: set(p % 12 for p, _ in pw)
            for b, pw in beat_pitches.items() if pw
        }
        tpb = midi.ticks_per_beat
        attack_window = tpb // 4

        # --- パス1: 単音拍の再推定 ---
        for b in range(len(progression)):
            pw = beat_pitches.get(b, [])
            if not pw:
                continue
            present = beat_pitches_set.get(b, set())
            if len(present) != 1:
                continue
            the_note = next(iter(present))
            ctx = _fill_context(progression, b)
            pcs = weighted_pcs(pw)
            # 導音 → V (dominant triad) に固定
            leading_tone = (key_pc + 11) % 12
            if mode == "minor" and the_note == leading_tone:
                dom_root = (key_pc + 7) % 12
                dom_pcs = {(dom_root + iv) % 12 for iv in TRIAD_TEMPLATES["major"]}
                progression[b] = (NOTE_NAMES[dom_root], dom_root, "major", dom_pcs)
            else:
                progression[b] = identify_chord_diatonic(pcs, key_pc, mode,
                                                          context_chord=ctx)

        # --- パス2: 和声持続判定 ---
        # 2音以下の拍でアタック音が全て前後の確定和音の構成音なら
        # その和音を継続する（経過音・刺繍音をコードとして誤認識しない）
        note_starts: Dict[int, List[int]] = {}  # pitch → [start_tick, ...]
        for n in midi.all_notes:
            note_starts.setdefault(n.pitch, []).append(n.start_tick)

        for b in range(len(progression)):
            pw = beat_pitches.get(b, [])
            if not pw:
                continue
            present = beat_pitches_set.get(b, set())
            if len(present) > 2:
                continue  # 3音以上は信頼度高いため変更しない

            ctx = _fill_context(progression, b, window=2)
            if ctx is None:
                continue
            ctx_tones: Set[int] = set(ctx[3])

            beat_start_tick = b * tpb
            attack_pcs: Set[int] = set()
            for pitch, _ in beat_pitches[b]:
                for st in note_starts.get(pitch, []):
                    if abs(st - beat_start_tick) <= attack_window:
                        attack_pcs.add(pitch % 12)
                        break

            # アタック音が全てコンテキスト和音に含まれる → 和声を継続
            if attack_pcs and attack_pcs.issubset(ctx_tones):
                progression[b] = ctx

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
        print("使い方: python extract_chords_from_midi.py <input.mid> [--diatonic]")
        print("        バッハのMIDIファイルから拍ごとのコード進行を抽出します。")
        print("        --diatonic: 調性優先モード（ダイアトニック候補に絞る、推奨）")
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"ファイルが見つかりません: {filepath}")
        sys.exit(1)

    use_diatonic = "--diatonic" in sys.argv

    # MIDI読み込み
    reader = MIDIReader()
    midi = reader.read(filepath)

    print(f"  ファイル: {filepath}")
    print(f"  フォーマット: Type {midi.format_type}")
    print(f"  トラック数: {len(midi.tracks)}")
    print(f"  分解能: {midi.ticks_per_beat} ticks/beat")
    print(f"  総ノート数: {len(midi.all_notes)}")
    print(f"  モード: {'調性優先 (--diatonic)' if use_diatonic else '標準'}")

    if midi.all_notes:
        total_ticks = max(n.end_tick for n in midi.all_notes)
        total_beats = total_ticks // midi.ticks_per_beat
        print(f"  総拍数: {total_beats} ({total_beats // 4}小節)")

        # ピッチ範囲で調性を推定
        all_pcs = Counter(n.pitch_class for n in midi.all_notes)
        print(f"  ピッチクラス分布: {dict(sorted(all_pcs.items()))}")

    # D minor (BWV 1080)
    key_pc = 2  # D
    mode = "minor"

    # 和音抽出
    progression = extract_chord_progression(midi, key_pc=key_pc, mode=mode,
                                            diatonic=use_diatonic)

    print_progression(progression, key_pc=key_pc, mode=mode)

    # Pythonコードとしてエクスポート
    export_as_python(progression, key_pc=key_pc)


if __name__ == "__main__":
    main()
