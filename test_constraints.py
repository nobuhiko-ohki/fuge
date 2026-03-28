"""設計制約の機械的回帰検証

CONSTRAINTS.md に記載された全制約を自動検証する。
コード変更後に必ず実行し、全テスト PASS を確認すること。

使い方:
    python test_constraints.py
"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from harmony_rules_complete import Pitch
from fugue_structure import Key, Subject, FugueStructure, FugueVoiceType
from fugue_realization import (
    FugueRealizationEngine, SUBBEATS_PER_BEAT, ChordLabel, VOICE_RANGES,
    SubjectHarmonicAnalyzer,
)
from bach_harmony_model import ChordProgressionModel, CounterpointPatternModel
from key_transition_model import KeyTransitionModel, MarkovKeyPathStrategy

BASE = os.path.dirname(__file__)
MODEL_DIR = os.path.join(BASE, "corpus", "models")


def load_models():
    chord_model = ChordProgressionModel()
    cp_model = CounterpointPatternModel()
    key_model = KeyTransitionModel()
    for name, model in [("chord_progression", chord_model),
                        ("counterpoint_patterns", cp_model),
                        ("key_transition", key_model)]:
        p = os.path.join(MODEL_DIR, f"{name}.json")
        if os.path.exists(p):
            model.load(p)
    return chord_model, cp_model, key_model


def build_engine(elaborate=True):
    """テスト用エンジンを構築"""
    chord_model, cp_model, key_model = load_models()
    key = Key('C', 'major')
    pitches = [Pitch(m) for m in [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 64, 60]]
    subject = Subject(pitches, key, "C major test")
    structure = FugueStructure(num_voices=3, main_key=key, subject=subject)
    markov = (MarkovKeyPathStrategy(key_model, seed=42)
              if key_model.num_transitions > 0 else None)
    engine = FugueRealizationEngine(
        structure, seed=42,
        chord_model=chord_model,
        counterpoint_model=cp_model,
        elaborate=elaborate,
    )
    full_midi = engine.realize_fugue(key_path_strategy=markov)
    return engine, full_midi


# ============================================================
# テスト関数群
# ============================================================

def test_C1_seventh_chord_restriction(engine):
    """C1: 七の和音は V7 と vii°7 のみ"""
    violations = []
    gcl = getattr(engine, 'global_chord_labels', {})
    for beat, cl in gcl.items():
        if cl.has_seventh and cl.degree not in (4, 6):
            violations.append(
                f"beat {beat}: degree={cl.degree} has_seventh=True "
                f"(allowed: 4=V, 6=vii° only)")
    return violations


def test_C2_seventh_freq_zero():
    """C2: ソースコード中の全 seventh_freq= が 0.0"""
    src_path = os.path.join(BASE, "src", "fugue_realization.py")
    with open(src_path, 'r') as f:
        content = f.read()

    violations = []
    for i, line in enumerate(content.split('\n'), 1):
        # seventh_freq= の値を抽出
        match = re.search(r'seventh_freq\s*=\s*([\d.]+)', line)
        if match:
            val = float(match.group(1))
            if val != 0.0:
                violations.append(
                    f"line {i}: seventh_freq={val} (must be 0.0)")
    return violations


def test_C3_root_third_coverage(engine, full_midi):
    """C3: 2声部以上の全拍で根音・第3音が各々存在（省略可は第5音のみ）

    例外: フーガ冒頭（単声部から漸増する区間）、終止和音（空虚5度）
    """
    gcl = getattr(engine, 'global_chord_labels', {})
    ticks_per_beat = SUBBEATS_PER_BEAT * 120

    # 拍頭で鳴っている音を収集（開始だけでなく持続中の音も含む）
    beat_head_notes = {}
    for vt, notes in full_midi.items():
        for start_tick, midi_val, dur_tick in notes:
            end_tick = start_tick + dur_tick
            # この音が鳴っている全拍の拍頭を登録
            first_beat = start_tick // ticks_per_beat
            last_beat = (end_tick - 1) // ticks_per_beat if end_tick > start_tick else first_beat
            for beat in range(first_beat, last_beat + 1):
                beat_tick = beat * ticks_per_beat
                if start_tick <= beat_tick < end_tick:
                    if beat not in beat_head_notes:
                        beat_head_notes[beat] = {}
                    if vt not in beat_head_notes[beat]:
                        beat_head_notes[beat][vt] = []
                    if midi_val not in beat_head_notes[beat][vt]:
                        beat_head_notes[beat][vt].append(midi_val)

    # 最終拍を特定（終止和音の例外判定用）
    all_beats = sorted(beat_head_notes.keys())
    last_beat = all_beats[-1] if all_beats else -1

    violations = []
    for beat in all_beats:
        cl = gcl.get(beat)
        if not cl:
            continue
        pcs = set()
        active = 0
        for vt, midis in beat_head_notes[beat].items():
            for m in midis:
                pcs.add(m % 12)
                active += 1
        if active < 2:
            continue

        # 終止和音の例外: 最終拍付近（空虚5度=根音+5度は正統な終止法）
        if beat >= last_beat - 1:
            continue

        has_root = cl.root_pc in pcs
        has_third = cl.third_pc in pcs

        if not has_root and not has_third:
            violations.append(
                f"beat {beat} (m{beat//4+1}.{beat%4+1}): "
                f"根音({cl.root_pc})・第3音({cl.third_pc})ともに欠落 "
                f"pcs={pcs}")
        elif not has_root:
            violations.append(
                f"beat {beat} (m{beat//4+1}.{beat%4+1}): "
                f"根音({cl.root_pc})欠落 pcs={pcs}")
        elif not has_third:
            violations.append(
                f"beat {beat} (m{beat//4+1}.{beat%4+1}): "
                f"第3音({cl.third_pc})欠落 pcs={pcs}")

    return violations


def test_C6_modulation_per_episode(engine):
    """C6: 嬉遊部の転調は最大1回"""
    key_paths = getattr(engine, '_last_key_paths', {})
    violations = []
    for label, kp in key_paths.items():
        if not hasattr(kp, 'beat_keys') or not kp.beat_keys:
            continue
        changes = 0
        prev = kp.beat_keys[0]
        for k in kp.beat_keys[1:]:
            if k != prev:
                changes += 1
                prev = k
        if changes > 1:
            violations.append(
                f"{label}: {changes} modulations (max 1 allowed)")
    return violations


def test_C7_diatonic_ml_candidates(engine):
    """C7: MLリファイン後の和声が全拍ダイアトニック"""
    gcl = getattr(engine, 'global_chord_labels', {})
    # 各セクションの調に対して、和音がダイアトニックかチェック
    # （簡易検証: degree が 0-6 の範囲内であること）
    violations = []
    for beat, cl in gcl.items():
        if cl.degree < 0 or cl.degree > 6:
            violations.append(
                f"beat {beat}: degree={cl.degree} out of range 0-6")
    return violations


def test_C8_seed_reproducibility():
    """C8: 同一シードで同一結果"""
    chord_model, cp_model, key_model = load_models()
    key = Key('C', 'major')
    pitches = [Pitch(m) for m in [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 64, 60]]
    subject = Subject(pitches, key, "C major test")
    structure = FugueStructure(num_voices=3, main_key=key, subject=subject)
    markov = (MarkovKeyPathStrategy(key_model, seed=42)
              if key_model.num_transitions > 0 else None)

    results = []
    for _ in range(2):
        engine = FugueRealizationEngine(
            structure, seed=42,
            chord_model=chord_model,
            counterpoint_model=cp_model,
            elaborate=True,
        )
        midi = engine.realize_fugue(key_path_strategy=markov)
        # 全ノートをソートして比較用文字列化
        all_notes = []
        for vt in sorted(midi.keys(), key=lambda x: x.value):
            for n in midi[vt]:
                all_notes.append(n)
        results.append(tuple(all_notes))

    violations = []
    if results[0] != results[1]:
        violations.append("2回の実行で結果が異なる（シード再現性の欠如）")
    return violations


def test_C9_vertical_bonus_values():
    """C9: _score_vertical の和音充足ボーナス値が正しい"""
    src_path = os.path.join(BASE, "src", "fugue_realization.py")
    with open(src_path, 'r') as f:
        content = f.read()

    violations = []
    # 新構成音補完: -4.0
    if 'cost -= 4.0' not in content:
        violations.append("新構成音補完ボーナス (-4.0) が見つからない")
    # 重複ペナルティ: +2.0
    if 'cost += 2.0' not in content:
        violations.append("重複ペナルティ (+2.0) が見つからない")
    # 根音補完: -3.0
    if 'cost -= 3.0' not in content:
        violations.append("根音補完ボーナス (-3.0) が見つからない")
    return violations


def test_C11_no_parallel_fifths(full_midi):
    """C11: 並行5度・8度がないこと（拍頭で鳴っている音を検査）"""
    ticks_per_beat = SUBBEATS_PER_BEAT * 120
    # 拍頭で鳴っている音を声部ごとに収集
    beat_pitches = {}  # beat -> {voice: midi}
    for vt, notes in full_midi.items():
        for start_tick, midi_val, dur_tick in notes:
            end_tick = start_tick + dur_tick
            first_beat = start_tick // ticks_per_beat
            last_beat = (end_tick - 1) // ticks_per_beat if end_tick > start_tick else first_beat
            for beat in range(first_beat, last_beat + 1):
                beat_tick = beat * ticks_per_beat
                if start_tick <= beat_tick < end_tick:
                    if beat not in beat_pitches:
                        beat_pitches[beat] = {}
                    beat_pitches[beat][vt] = midi_val

    violations = []
    beats = sorted(beat_pitches.keys())
    for i in range(1, len(beats)):
        b_prev, b_curr = beats[i-1], beats[i]
        if b_curr != b_prev + 1:
            continue  # 連続拍のみ検査
        voices = list(set(beat_pitches[b_prev].keys()) &
                      set(beat_pitches[b_curr].keys()))
        for vi in range(len(voices)):
            for vj in range(vi+1, len(voices)):
                v1, v2 = voices[vi], voices[vj]
                prev_int = abs(beat_pitches[b_prev][v1] -
                              beat_pitches[b_prev][v2]) % 12
                curr_int = abs(beat_pitches[b_curr][v1] -
                              beat_pitches[b_curr][v2]) % 12
                if prev_int == curr_int and prev_int in (0, 7):
                    # 同方向チェック
                    d1 = beat_pitches[b_curr][v1] - beat_pitches[b_prev][v1]
                    d2 = beat_pitches[b_curr][v2] - beat_pitches[b_prev][v2]
                    if d1 != 0 and d2 != 0 and (d1 > 0) == (d2 > 0):
                        ic_name = "5度" if prev_int == 7 else "8度/ユニゾン"
                        violations.append(
                            f"beat {b_curr} (m{b_curr//4+1}.{b_curr%4+1}): "
                            f"並行{ic_name} {v1.value}-{v2.value}")
    return violations


def test_C13_voice_ranges(full_midi):
    """C13: 全音が声部音域内"""
    violations = []
    for vt, notes in full_midi.items():
        lo, hi = VOICE_RANGES[vt]
        for start_tick, midi_val, dur_tick in notes:
            if midi_val < lo or midi_val > hi:
                beat = start_tick // (SUBBEATS_PER_BEAT * 120)
                violations.append(
                    f"beat {beat}: {vt.value} pitch={midi_val} "
                    f"out of range [{lo},{hi}]")
    return violations


# ============================================================
# メイン
# ============================================================

def main():
    print("=" * 60)
    print("  設計制約の回帰検証 (CONSTRAINTS.md)")
    print("=" * 60)

    # --- ソースコードのみで検証可能なテスト ---
    static_tests = [
        ("C2: seventh_freq=0.0（全箇所）", test_C2_seventh_freq_zero),
        ("C9: 和音充足ボーナス値", test_C9_vertical_bonus_values),
    ]

    all_pass = True
    for name, test_fn in static_tests:
        violations = test_fn()
        status = "PASS" if not violations else "FAIL"
        print(f"\n  [{status}] {name}")
        if violations:
            all_pass = False
            for v in violations:
                print(f"    !! {v}")

    # --- 生成が必要なテスト ---
    print("\n  --- 生成テスト（elaborate=True）---")
    engine, full_midi = build_engine(elaborate=True)

    runtime_tests = [
        ("C1: 七の和音はV7/vii°7のみ",
         lambda: test_C1_seventh_chord_restriction(engine)),
        ("C3: 根音+第3音の同時欠落ゼロ",
         lambda: test_C3_root_third_coverage(engine, full_midi)),
        ("C6: 転調は1嬉遊部あたり最大1回",
         lambda: test_C6_modulation_per_episode(engine)),
        ("C7: ML和声候補がダイアトニック",
         lambda: test_C7_diatonic_ml_candidates(engine)),
        ("C11: 並行5度・8度なし",
         lambda: test_C11_no_parallel_fifths(full_midi)),
        ("C13: 声部音域内",
         lambda: test_C13_voice_ranges(full_midi)),
    ]

    for name, test_fn in runtime_tests:
        violations = test_fn()
        status = "PASS" if not violations else "FAIL"
        print(f"\n  [{status}] {name}")
        if violations:
            all_pass = False
            for v in violations[:10]:  # 最大10件表示
                print(f"    !! {v}")
            if len(violations) > 10:
                print(f"    ... 他 {len(violations)-10} 件")

    # --- シード再現性テスト ---
    print(f"\n  --- シード再現性テスト ---")
    violations = test_C8_seed_reproducibility()
    status = "PASS" if not violations else "FAIL"
    print(f"\n  [{status}] C8: シード固定による再現性")
    if violations:
        all_pass = False
        for v in violations:
            print(f"    !! {v}")

    # --- 結果サマリ ---
    print(f"\n{'=' * 60}")
    if all_pass:
        print("  全テスト PASS")
    else:
        print("  !! 一部テスト FAIL — 修正が必要")
    print(f"{'=' * 60}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
