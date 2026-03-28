"""
フーガ解析モジュールのテスト

テスト対象:
  - midi_reader.py
  - fugue_analyzer.py
  - corpus_pipeline.py (SubjectFeatures)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'corpus'))

from midi_reader import MIDIReader, MIDINote, MIDIFile
from midi_writer import MIDIWriter
from fugue_analyzer import (
    compute_pcp, estimate_key, estimate_key_sequence,
    separate_voices_by_channel, separate_voices_by_pitch,
    extract_pitch_intervals, extract_rhythm_ratios,
    find_pattern_occurrences,
    detect_key_changes, detect_silences,
    analyze_fugue, FugueAnalysis,
)
from corpus_pipeline import extract_subject_features
from key_transition_model import (
    KeyTransitionModel, MarkovKeyPathStrategy,
    parse_key_name, relative_state, state_name,
)


# ============================================================
# テスト基盤
# ============================================================

passed = 0
failed = 0
total = 0


def check(label, condition, detail=""):
    global passed, failed, total
    total += 1
    if condition:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failed += 1
        msg = f"  [FAIL] {label}"
        if detail:
            msg += f" — {detail}"
        print(msg)


def make_note(start_beat, pitch, dur_beats=1.0, tpb=480):
    """テスト用 MIDINote を生成する。"""
    return MIDINote(
        start_tick=int(start_beat * tpb),
        end_tick=int((start_beat + dur_beats) * tpb),
        channel=0,
        pitch=pitch,
        velocity=64,
    )


# ============================================================
# Section 23: MIDI Reader
# ============================================================

def test_midi_reader():
    print("\n=== Section 23: MIDI Reader ===")

    # 23.1 MIDIWriter → MIDIReader ラウンドトリップ
    writer = MIDIWriter(tempo=120, ticks_per_beat=480)
    test_notes = [(0, 60, 480), (480, 64, 480), (960, 67, 480)]
    writer.add_track_from_notes(test_notes, channel=0)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as f:
        tmppath = f.name
    writer.write_file(tmppath)

    reader = MIDIReader()
    midi = reader.read(tmppath)
    os.unlink(tmppath)

    check("23.1 ラウンドトリップ: フォーマット", midi.format_type == 1)
    check("23.1 ラウンドトリップ: 分解能", midi.ticks_per_beat == 480)

    notes = midi.all_notes
    check("23.1 ラウンドトリップ: ノート数=3", len(notes) == 3,
          f"got {len(notes)}")
    if len(notes) == 3:
        check("23.1 ラウンドトリップ: pitch[0]=60", notes[0].pitch == 60)
        check("23.1 ラウンドトリップ: pitch[1]=64", notes[1].pitch == 64)
        check("23.1 ラウンドトリップ: pitch[2]=67", notes[2].pitch == 67)

    # 23.2 マルチチャンネル
    writer2 = MIDIWriter(tempo=100, ticks_per_beat=480)
    writer2.add_track_from_notes([(0, 72, 480)], channel=0)
    writer2.add_track_from_notes([(0, 60, 480)], channel=1)
    with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as f:
        tmppath2 = f.name
    writer2.write_file(tmppath2)

    midi2 = reader.read(tmppath2)
    os.unlink(tmppath2)

    voices = midi2.get_voices()
    check("23.2 マルチチャンネル: 2チャンネル", len(voices) == 2,
          f"got {len(voices)}")
    check("23.2 マルチチャンネル: Ch.0に1ノート",
          len(voices.get(0, [])) == 1)
    check("23.2 マルチチャンネル: Ch.1に1ノート",
          len(voices.get(1, [])) == 1)

    # 23.3 テンポ取得
    check("23.3 テンポ: 100 BPM", midi2.get_tempo() == 100,
          f"got {midi2.get_tempo()}")

    # 23.4 duration
    check("23.4 duration: 1拍", abs(midi2.duration_beats - 1.0) < 0.01,
          f"got {midi2.duration_beats}")

    # 23.5 MIDINote プロパティ
    n = MIDINote(start_tick=0, end_tick=480, channel=0, pitch=60, velocity=64)
    check("23.5 pitch_class: C=0", n.pitch_class == 0)
    check("23.5 octave: C4=4", n.octave == 4)
    check("23.5 duration_tick: 480", n.duration_tick == 480)
    check("23.5 as_tuple", n.as_tuple() == (0, 60, 480))


# ============================================================
# Section 24: PCP と調推定
# ============================================================

def test_pcp_and_key_estimation():
    print("\n=== Section 24: PCP と調推定 ===")

    # 24.1 C major の PCP
    c_major_notes = [
        make_note(0, 60), make_note(1, 62), make_note(2, 64),
        make_note(3, 65), make_note(4, 67),
    ]
    pcp = compute_pcp(c_major_notes, 0, 5 * 480)
    check("24.1 PCP: 12次元", len(pcp) == 12)
    check("24.1 PCP: 正規化合計≈1",
          abs(sum(pcp) - 1.0) < 0.01, f"sum={sum(pcp):.4f}")
    # C, D, E, F, G → pc 0, 2, 4, 5, 7 が正
    for pc in [0, 2, 4, 5, 7]:
        check(f"24.1 PCP: pc={pc} > 0", pcp[pc] > 0, f"val={pcp[pc]:.4f}")

    # 24.2 C major 推定
    key_est = estimate_key(pcp)
    check("24.2 調推定: C major",
          key_est.key_name == "C major",
          f"got {key_est.key_name}")
    check("24.2 調推定: 正の相関", key_est.correlation > 0)

    # 24.3 A minor の推定
    a_minor_notes = [
        make_note(0, 69), make_note(1, 71), make_note(2, 72),
        make_note(3, 74), make_note(4, 76),  # A B C D E
    ]
    pcp_am = compute_pcp(a_minor_notes, 0, 5 * 480)
    key_am = estimate_key(pcp_am)
    check("24.3 調推定: A minor の tonic=9",
          key_am.tonic == 9, f"got tonic={key_am.tonic}")

    # 24.4 空のノート列
    pcp_empty = compute_pcp([], 0, 480)
    check("24.4 空PCP: all zero",
          all(v == 0.0 for v in pcp_empty))

    # 24.5 重み付きなし
    pcp_unw = compute_pcp(c_major_notes, 0, 5 * 480, weighted=False)
    check("24.5 非重みPCP: 各 = 0.2",
          all(abs(v - 0.2) < 0.01 for v in pcp_unw if v > 0))


# ============================================================
# Section 25: 声部分離
# ============================================================

def test_voice_separation():
    print("\n=== Section 25: 声部分離 ===")

    # 25.1 チャンネル別分離
    writer = MIDIWriter(tempo=120, ticks_per_beat=480)
    writer.add_track_from_notes([(0, 72, 480), (480, 74, 480)], channel=0)
    writer.add_track_from_notes([(0, 48, 480), (480, 50, 480)], channel=3)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as f:
        tmppath = f.name
    writer.write_file(tmppath)

    reader = MIDIReader()
    midi = reader.read(tmppath)
    os.unlink(tmppath)

    streams = separate_voices_by_channel(midi)
    check("25.1 チャンネル別: 2声部", len(streams) == 2)
    check("25.1 チャンネル別: 各2ノート",
          all(len(s.notes) == 2 for s in streams))

    # 25.2 ピッチベース分離
    mixed_notes = [
        make_note(0, 72), make_note(0, 48),
        make_note(1, 74), make_note(1, 50),
        make_note(2, 76), make_note(2, 52),
    ]
    streams2 = separate_voices_by_pitch(mixed_notes, num_voices=2)
    check("25.2 ピッチ別: 2声部", len(streams2) == 2)
    # 高い声部
    high = streams2[0]
    low = streams2[1]
    check("25.2 ピッチ別: 高声部の平均>65",
          high.mean_pitch > 65, f"mean={high.mean_pitch:.1f}")
    check("25.2 ピッチ別: 低声部の平均<55",
          low.mean_pitch < 55, f"mean={low.mean_pitch:.1f}")

    # 25.3 VoiceStream プロパティ
    check("25.3 pitch_range",
          high.pitch_range[0] <= high.pitch_range[1])
    check("25.3 voice_id", high.voice_id == 0)

    # 25.4 空ノート
    empty_streams = separate_voices_by_pitch([], num_voices=3)
    check("25.4 空: 3声部（空）", len(empty_streams) == 3)
    check("25.4 空: 各0ノート",
          all(len(s.notes) == 0 for s in empty_streams))


# ============================================================
# Section 26: パターン検出
# ============================================================

def test_pattern_detection():
    print("\n=== Section 26: パターン検出 ===")

    # C-D-E パターン → 音程列 [2, 2]
    notes = [
        make_note(0, 60), make_note(1, 62), make_note(2, 64),  # C D E
        make_note(3, 65), make_note(4, 67),                     # F G
        make_note(5, 65), make_note(6, 67), make_note(7, 69),  # F G A (= +2, +2)
    ]

    # 26.1 音程列抽出
    ivs = extract_pitch_intervals(notes)
    check("26.1 音程列: 長さ=7", len(ivs) == 7, f"got {len(ivs)}")
    check("26.1 音程列: [2,2,...1,2,...]",
          ivs[0] == 2 and ivs[1] == 2)

    # 26.2 パターン検索 [2, 2]
    matches = find_pattern_occurrences(notes, [2, 2], tolerance=0)
    check("26.2 パターン [2,2]: 2箇所",
          len(matches) == 2, f"got {len(matches)} at {matches}")

    # 26.3 存在しないパターン
    no_match = find_pattern_occurrences(notes, [5, 5])
    check("26.3 パターン [5,5]: 0箇所", len(no_match) == 0)

    # 26.4 リズム比
    ratios = extract_rhythm_ratios(notes)
    check("26.4 リズム比: 長さ=7", len(ratios) == 7)
    check("26.4 リズム比: 均等→全て1.0",
          all(abs(r - 1.0) < 0.01 for r in ratios))

    # 26.5 tolerance付きパターン検索
    # [2, 3] は存在しないが tolerance=1 なら [2, 2] がマッチ
    matches_tol = find_pattern_occurrences(notes, [2, 3], tolerance=1)
    check("26.5 tolerance=1: [2,3]でマッチ",
          len(matches_tol) >= 2, f"got {len(matches_tol)}")


# ============================================================
# Section 27: セクション境界検出
# ============================================================

def test_section_detection():
    print("\n=== Section 27: セクション境界検出 ===")

    # 27.1 調変化検出
    from fugue_analyzer import KeyEstimate
    key_seq = [
        (0.0, KeyEstimate(0, 'major', 0.9, 'C major')),
        (1.0, KeyEstimate(0, 'major', 0.9, 'C major')),
        (2.0, KeyEstimate(0, 'major', 0.9, 'C major')),
        (3.0, KeyEstimate(7, 'major', 0.8, 'G major')),
        (4.0, KeyEstimate(7, 'major', 0.8, 'G major')),
    ]
    kc = detect_key_changes(key_seq, min_stable_beats=2)
    check("27.1 調変化: 1箇所", len(kc) == 1, f"got {len(kc)}")
    if kc:
        check("27.1 調変化: beat=3.0", abs(kc[0].beat - 3.0) < 0.1)
        check("27.1 調変化: reason に key_change",
              "key_change" in kc[0].reason)

    # 27.2 不安定な推定では検出しない
    unstable_seq = [
        (0.0, KeyEstimate(0, 'major', 0.5, 'C major')),
        (1.0, KeyEstimate(7, 'major', 0.5, 'G major')),
        (2.0, KeyEstimate(0, 'major', 0.5, 'C major')),
    ]
    kc2 = detect_key_changes(unstable_seq, min_stable_beats=2)
    check("27.2 不安定: 0箇所", len(kc2) == 0, f"got {len(kc2)}")

    # 27.3 休符検出
    writer = MIDIWriter(tempo=120, ticks_per_beat=480)
    # 0-2拍にノート、2-4拍は休符、4-6拍にノート
    notes = [(0, 60, 960), (1920, 60, 960)]
    writer.add_track_from_notes(notes, channel=0)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as f:
        tmppath = f.name
    writer.write_file(tmppath)

    reader = MIDIReader()
    midi = reader.read(tmppath)
    os.unlink(tmppath)

    silences = detect_silences(midi, min_silence_ticks=480)
    check("27.3 休符検出: 1箇所", len(silences) >= 1,
          f"got {len(silences)}")
    if silences:
        check("27.3 休符: beat≈2.0",
              abs(silences[0].beat - 2.0) < 0.1,
              f"got {silences[0].beat}")


# ============================================================
# Section 28: 主題特徴量抽出
# ============================================================

def test_subject_features():
    print("\n=== Section 28: 主題特徴量 ===")

    # C-D-E-F-G（5音、順次進行のみ）
    notes = [
        make_note(0, 60, 1.0), make_note(1, 62, 1.0),
        make_note(2, 64, 1.0), make_note(3, 65, 1.0),
        make_note(4, 67, 1.0),
    ]

    feat = extract_subject_features(
        notes, fugue_id="test", known_key="C major",
        num_voices=3, ticks_per_beat=480)

    check("28.1 num_notes=5", feat.num_notes == 5)
    check("28.2 duration≈5.0", abs(feat.duration_beats - 5.0) < 0.1,
          f"got {feat.duration_beats}")
    check("28.3 pitch_range=7 (C4-G4)",
          feat.pitch_range == 7, f"got {feat.pitch_range}")
    check("28.4 step_ratio=1.0（全て順次進行）",
          abs(feat.step_ratio - 1.0) < 0.01)
    check("28.5 intervals=[2,2,1,2]",
          feat.pitch_intervals == [2, 2, 1, 2],
          f"got {feat.pitch_intervals}")
    check("28.6 estimated_key: C major",
          feat.estimated_key == "C major",
          f"got {feat.estimated_key}")
    check("28.7 pcp: 12要素", len(feat.pcp) == 12)
    check("28.8 interval_variety=2（2度と半音）",
          feat.interval_variety == 2, f"got {feat.interval_variety}")
    check("28.9 to_dict: fugue_id",
          feat.to_dict()["fugue_id"] == "test")

    # 28.10 空ノート
    empty = extract_subject_features([], fugue_id="empty")
    check("28.10 空: num_notes=0", empty.num_notes == 0)
    check("28.10 空: step_ratio=0.0", empty.step_ratio == 0.0)


# ============================================================
# Section 29: 統合解析
# ============================================================

def test_full_analysis():
    print("\n=== Section 29: 統合解析 ===")

    # 29.1 sample_fugue_v5 があれば使用
    sample_path = os.path.join(
        os.path.dirname(__file__), "..", "sample_fugue_v5.mid")

    if os.path.exists(sample_path):
        reader = MIDIReader()
        midi = reader.read(sample_path)
        analysis = analyze_fugue(midi, filename="sample_v5.mid")

        check("29.1 global_key 存在", analysis.global_key is not None)
        if analysis.global_key:
            check("29.1 global_key: C major",
                  analysis.global_key.key_name == "C major",
                  f"got {analysis.global_key.key_name}")
        check("29.2 num_voices=3",
              analysis.num_voices == 3,
              f"got {analysis.num_voices}")
        check("29.3 total_beats>0", analysis.total_beats > 0)
        check("29.4 pcp_sequence非空",
              len(analysis.pcp_sequence) > 0)
        check("29.5 key_sequence非空",
              len(analysis.key_sequence) > 0)
        check("29.6 summary()は文字列",
              isinstance(analysis.summary(), str))
        check("29.7 summary()に 'C major' を含む",
              "C major" in analysis.summary())
    else:
        print("  [SKIP] sample_fugue_v5.mid が見つかりません")

    # 29.8 最小の MIDI で統合テスト
    writer = MIDIWriter(tempo=72, ticks_per_beat=480)
    writer.add_track_from_notes(
        [(i * 480, 60 + (i % 7), 480) for i in range(8)],
        channel=0)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as f:
        tmppath = f.name
    writer.write_file(tmppath)

    reader = MIDIReader()
    midi_min = reader.read(tmppath)
    os.unlink(tmppath)

    analysis_min = analyze_fugue(midi_min, filename="minimal.mid")
    check("29.8 最小解析: 完了", analysis_min is not None)
    check("29.8 最小解析: total_beats>0",
          analysis_min.total_beats > 0)


# Section 30: 調推移モデル
# ============================================================

def test_key_transition_model():
    """KeyTransitionModel のユニットテスト"""
    print("\n=== Section 30: 調推移モデル ===")

    # --- 30.1 parse_key_name ---
    check("30.1a C major → (0, major)",
          parse_key_name("C major") == (0, "major"))
    check("30.1b F# minor → (6, minor)",
          parse_key_name("F# minor") == (6, "minor"))
    check("30.1c Bb major → (10, major)",
          parse_key_name("Bb major") == (10, "major"))
    check("30.1d 不正入力 → デフォルト",
          parse_key_name("invalid") == (0, "major"))

    # --- 30.2 relative_state ---
    check("30.2a C major基準, G major → (7, major)",
          relative_state(0, "major", 7, "major") == (7, "major"))
    check("30.2b C major基準, A minor → (9, minor)",
          relative_state(0, "major", 9, "minor") == (9, "minor"))
    check("30.2c G major基準, C major → (5, major)",
          relative_state(7, "major", 0, "major") == (5, "major"))
    check("30.2d 同調 → (0, same)",
          relative_state(3, "minor", 3, "minor") == (0, "minor"))

    # --- 30.3 state_name ---
    check("30.3a (0, major) → I",
          state_name((0, "major")) == "I")
    check("30.3b (7, major) → V",
          state_name((7, "major")) == "V")
    check("30.3c (9, minor) → #vi",
          state_name((9, "minor")) == "#vi")

    # --- 30.4 空のモデル ---
    model = KeyTransitionModel()
    check("30.4a 空モデル: states空",
          len(model.states) == 0)
    check("30.4b 空モデル: summary生成可",
          isinstance(model.summary(), str))

    # --- 30.5 ミニデータで学習 ---
    mini_data = [
        {
            "global_key": "C major",
            "total_beats": 100.0,
            "key_changes": [
                {"beat": 0, "key": "C major"},
                {"beat": 25, "key": "G major"},
                {"beat": 50, "key": "A minor"},
                {"beat": 75, "key": "F major"},
                {"beat": 90, "key": "C major"},
            ]
        },
        {
            "global_key": "G major",
            "total_beats": 80.0,
            "key_changes": [
                {"beat": 0, "key": "G major"},
                {"beat": 20, "key": "D major"},
                {"beat": 40, "key": "E minor"},
                {"beat": 60, "key": "C major"},
                {"beat": 70, "key": "G major"},
            ]
        },
    ]
    model = KeyTransitionModel(smoothing=0.1)
    model.train_from_data(mini_data)

    check("30.5a 2曲学習", model.num_sequences == 2)
    check("30.5b 遷移カウント>0", model.num_transitions > 0)
    check("30.5c 状態数>0", len(model.states) > 0)
    check("30.5d I→V確率>0",
          model.transition_prob((0, "major"), (7, "major")) > 0)

    # --- 30.6 確率正規化 ---
    # 任意の状態からの全遷移確率の和は≒1
    from_I = sum(
        model.transition_prob((0, "major"), s, "all")
        for s in model.states)
    check("30.6 I→全状態の確率和≈1.0",
          abs(from_I - 1.0) < 0.01)

    # --- 30.7 sample_next は有効状態を返す ---
    import random as rng_mod
    test_rng = rng_mod.Random(42)
    next_s = model.sample_next((0, "major"), "all", test_rng)
    check("30.7 sample_nextの結果は有効状態",
          next_s in model.states)

    # --- 30.8 most_likely_next ---
    ml = model.most_likely_next((0, "major"), "all")
    check("30.8 most_likely_nextは有効状態",
          ml in model.states)

    # --- 30.9 保存・読み込み ---
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        tmppath = f.name
    model.save(tmppath)

    model2 = KeyTransitionModel()
    model2.load(tmppath)
    os.unlink(tmppath)

    check("30.9a load後のsequences数一致",
          model2.num_sequences == model.num_sequences)
    check("30.9b load後のtransitions数一致",
          model2.num_transitions == model.num_transitions)
    check("30.9c load後の状態数一致",
          len(model2.states) == len(model.states))
    # 遷移確率が一致（代表値）
    p_orig = model.transition_prob((0, "major"), (7, "major"))
    p_load = model2.transition_prob((0, "major"), (7, "major"))
    check("30.9d 遷移確率保存一致",
          abs(p_orig - p_load) < 0.001)

    # --- 30.10 MarkovKeyPathStrategy ---
    from fugue_structure import Key, KeyPath
    strategy = MarkovKeyPathStrategy(model, seed=42)

    kp = strategy.generate(Key('C', 'major'), Key('G', 'major'), 8)
    check("30.10a 返り値はKeyPath",
          isinstance(kp, KeyPath))
    check("30.10b beat_keys長=8",
          len(kp.beat_keys) == 8)
    check("30.10c start=C major",
          kp.beat_keys[0] == Key('C', 'major'))
    check("30.10d end=G major",
          kp.beat_keys[-1] == Key('G', 'major'))

    # --- 30.11 短い経路 ---
    kp2 = strategy.generate(Key('C', 'major'), Key('G', 'major'), 2)
    check("30.11a 2拍: 長さ2", len(kp2.beat_keys) == 2)

    kp0 = strategy.generate(Key('C', 'major'), Key('G', 'major'), 0)
    check("30.11b 0拍: 空", len(kp0.beat_keys) == 0)

    # --- 30.12 同一調 ---
    kp_same = strategy.generate(Key('C', 'major'), Key('C', 'major'), 8)
    check("30.12 同一調: 全拍C major",
          all(k == Key('C', 'major') for k in kp_same.beat_keys))

    # --- 30.13 deterministic モード ---
    det_strategy = MarkovKeyPathStrategy(model, deterministic=True)
    kp_det1 = det_strategy.generate(Key('C', 'major'), Key('G', 'major'), 8)
    kp_det2 = det_strategy.generate(Key('C', 'major'), Key('G', 'major'), 8)
    check("30.13 deterministic: 再現性",
          [k.tonic for k in kp_det1.beat_keys]
          == [k.tonic for k in kp_det2.beat_keys])

    # --- 30.14 位置ラベル ---
    check("30.14a early",
          model._position_label(10, 100) == "early")
    check("30.14b middle",
          model._position_label(50, 100) == "middle")
    check("30.14c late",
          model._position_label(80, 100) == "late")

    # --- 30.15 key_changesが1件以下→スキップ ---
    model3 = KeyTransitionModel()
    model3.train_from_data([
        {"global_key": "C major", "total_beats": 50,
         "key_changes": [{"beat": 0, "key": "C major"}]}
    ])
    check("30.15 1件のkey_changes→学習スキップ",
          model3.num_sequences == 0)


# ============================================================
# 実行
# ============================================================

def run_tests():
    global passed, failed, total
    passed = failed = total = 0

    test_midi_reader()
    test_pcp_and_key_estimation()
    test_voice_separation()
    test_pattern_detection()
    test_section_detection()
    test_subject_features()
    test_full_analysis()
    test_key_transition_model()

    print("\n" + "=" * 50)
    print(f"合格: {passed}/{total}")
    if failed > 0:
        print(f"不合格: {failed}")
    else:
        print("全テスト合格")
    print("=" * 50)

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
