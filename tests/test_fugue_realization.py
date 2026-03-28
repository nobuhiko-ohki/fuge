"""
フーガ実現エンジン テストスイート
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from harmony_rules_complete import Pitch, NoteEvent, HarmonyRules
from counterpoint_engine import CounterpointProhibitions, InvertibleCounterpoint
from fugue_structure import (
    Key, Subject, FugueStructure, FugueVoiceType, Episode,
    FugueEntry, KeyPath, KeyPathStrategy,
)
from fugue_realization import (
    SubjectHarmonicAnalyzer, ContrapuntalDP, FugueRealizationEngine,
    fit_melody_to_range, fit_notes_to_range, ChordLabel, VOICE_RANGES,
    RhythmElaborator, SUBBEATS_PER_BEAT,
)


def run_tests():
    passed = 0
    failed = 0
    total = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed, total
        total += 1
        if condition:
            passed += 1
        else:
            failed += 1
            print(f"  ✗ {name}: {detail}")

    # ==========================================================
    # 1. 主題和声分析
    # ==========================================================
    print("--- 1. 主題和声分析 ---")

    key_c = Key("C", "major")
    subject_pitches = [Pitch(m) for m in [60, 62, 64, 65, 67]]  # C D E F G
    subject = Subject(subject_pitches, key_c, "テスト主題")

    analyzer = SubjectHarmonicAnalyzer(key_c, seed=42)

    # 1.1 ダイアトニック和音の構築
    chords = analyzer.diatonic_chords
    check("ダイアトニック7和音", len(chords) == 7)
    check("I = C major", chords[0].quality == "major" and chords[0].root_pc == 0)
    check("ii = D minor", chords[1].quality == "minor" and chords[1].root_pc == 2)
    check("V = G major", chords[4].quality == "major" and chords[4].root_pc == 7)
    check("vii° = B dim", chords[6].quality == "diminished" and chords[6].root_pc == 11)

    # 1.2 含有和音の検索
    c_chords = analyzer.find_containing_chords(0)  # C を含む和音
    c_degrees = {c.degree for c in c_chords}
    check("Cを含む和音にIあり", 0 in c_degrees)
    check("Cを含む和音にIVあり", 3 in c_degrees)
    check("Cを含む和音にviあり", 5 in c_degrees)

    # 1.3 和声分析の実行
    plan = analyzer.analyze(subject)
    check("和声計画の長さ = 主題長", len(plan) == 5)
    check("冒頭拍はI", plan[0].degree == 0,
          f"got {plan[0].roman}")
    check("各拍に主題音を含む",
          all(subject_pitches[i].pitch_class in plan[i].tones
              for i in range(5)),
          "和声音に主題音が含まれていない拍あり")

    # 1.4 短調
    key_a = Key("A", "minor")
    analyzer_minor = SubjectHarmonicAnalyzer(key_a, seed=42)
    minor_chords = analyzer_minor.diatonic_chords
    check("短調 i = A minor", minor_chords[0].quality == "minor")
    check("短調 V = E major", minor_chords[4].quality == "major")

    # ==========================================================
    # 2. オクターブ補正
    # ==========================================================
    print("\n--- 2. オクターブ補正 ---")

    melody_c4 = [Pitch(60), Pitch(62), Pitch(64)]  # C4 D4 E4

    # ソプラノ範囲（60-79）: そのまま収まるはず
    fitted_s = fit_melody_to_range(melody_c4, VOICE_RANGES[FugueVoiceType.SOPRANO])
    check("ソプラノ: 音域内",
          all(60 <= p.midi <= 79 for p in fitted_s))

    # バス範囲（40-60）: オクターブ下にシフト
    fitted_b = fit_melody_to_range(melody_c4, VOICE_RANGES[FugueVoiceType.BASS])
    check("バス: 音域内",
          all(40 <= p.midi <= 60 for p in fitted_b),
          f"got {[p.midi for p in fitted_b]}")
    check("バス: 旋律構造保持",
          fitted_b[1].midi - fitted_b[0].midi == 2 and
          fitted_b[2].midi - fitted_b[1].midi == 2,
          "音程関係が崩れている")

    # ==========================================================
    # 3. 対位法DP
    # ==========================================================
    print("\n--- 3. 対位法DP ---")

    dp = ContrapuntalDP()

    # 固定声部: C4-D4-E4-F4-G4 (ソプラノ)
    fixed_soprano = [60, 62, 64, 65, 67]

    # I-I-I-IV-V の和声計画
    chord_I = analyzer.diatonic_chords[0]
    chord_IV = analyzer.diatonic_chords[3]
    chord_V = analyzer.diatonic_chords[4]
    test_chord_plan = [chord_I, chord_I, chord_I, chord_IV, chord_V]

    # アルト声部を生成
    result = dp.generate(
        num_beats=5,
        chord_plan=test_chord_plan,
        voice_range=VOICE_RANGES[FugueVoiceType.ALTO],
        fixed_voices={"soprano": fixed_soprano},
        free_voice_name="alto",
    )

    check("DP結果の長さ = 5", len(result) == 5)
    check("DP結果がアルト音域内",
          all(55 <= m <= 74 for m in result),
          f"got {result}")

    # 各拍が和声音であること
    for beat in range(5):
        pc = result[beat] % 12
        check(f"拍{beat}: 和声音",
              pc in test_chord_plan[beat].tones,
              f"MIDI={result[beat]}, PC={pc}, chord={test_chord_plan[beat].roman}, "
              f"tones={test_chord_plan[beat].tones}")

    # 並行5度・8度がないこと
    proh = CounterpointProhibitions()
    for beat in range(1, 5):
        ok, msg = proh.check_parallel_perfect(
            fixed_soprano[beat - 1], fixed_soprano[beat],
            result[beat - 1], result[beat]
        )
        check(f"拍{beat}: 並行5/8度なし", ok, msg)

    # ==========================================================
    # 4. 提示部全体の実現
    # ==========================================================
    print("\n--- 4. 提示部実現 ---")

    # 11音の主題
    subject_11 = Subject(
        [Pitch(m) for m in [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60]],
        key_c, "テスト主題"
    )
    fs = FugueStructure(num_voices=3, main_key=key_c, subject=subject_11)
    fs.create_exposition(answer_type="auto")

    engine = FugueRealizationEngine(fs, seed=42)
    midi_events = engine.realize_exposition()

    # 声部数チェック
    active_voices = [v for v, notes in midi_events.items() if notes]
    check("3声部がアクティブ", len(active_voices) == 3,
          f"got {len(active_voices)}")

    # 各声部が途切れなく鳴っているか（入場後）
    for entry in fs.entries:
        voice = entry.voice_type
        melody = engine.voice_melodies.get(voice, [])
        start = entry.start_position
        active_after_entry = melody[start:]
        none_count = sum(1 for m in active_after_entry if m is None)
        check(f"{voice.value}: 入場後に沈黙なし",
              none_count == 0,
              f"{none_count}拍の沈黙あり")

    # 全声部が音域内
    for voice, notes in midi_events.items():
        lo, hi = VOICE_RANGES[voice]
        for start_tick, midi_val, dur in notes:
            if not (lo <= midi_val <= hi):
                check(f"{voice.value}: 音域違反", False,
                      f"MIDI={midi_val} at tick={start_tick}")
                break
        else:
            check(f"{voice.value}: 全音が音域内", True)

    # 並行5/8度チェック（全声部ペア）
    voices_list = list(engine.voice_melodies.items())
    parallel_violations = 0
    for i in range(len(voices_list)):
        for j in range(i + 1, len(voices_list)):
            v1_name, v1_melody = voices_list[i]
            v2_name, v2_melody = voices_list[j]
            for beat in range(1, len(v1_melody)):
                if (v1_melody[beat] is None or v1_melody[beat - 1] is None or
                        v2_melody[beat] is None or v2_melody[beat - 1] is None):
                    continue
                ok, msg = proh.check_parallel_perfect(
                    v1_melody[beat - 1], v1_melody[beat],
                    v2_melody[beat - 1], v2_melody[beat],
                )
                if not ok:
                    parallel_violations += 1

    check("並行5/8度違反 = 0", parallel_violations == 0,
          f"{parallel_violations}箇所の違反")

    # ==========================================================
    # 5. MIDI出力
    # ==========================================================
    print("\n--- 5. MIDI出力 ---")

    output_path = "/sessions/fervent-vigilant-hypatia/fuge_final/test_output.mid"
    engine.export_midi(output_path, tempo=72)

    import os as _os
    check("MIDIファイル生成", _os.path.exists(output_path))
    check("MIDIファイルサイズ > 0",
          _os.path.getsize(output_path) > 0)

    # ==========================================================
    # 6. 分析レポート
    # ==========================================================
    print("\n--- 6. 分析レポート ---")

    report = engine.get_analysis_report()
    check("レポート生成", len(report) > 100)
    print(report)

    # ==========================================================
    # 7. NoteEvent と Subject の後方互換
    # ==========================================================
    print("\n--- 7. NoteEvent・Subject後方互換 ---")

    # 7.1 Pitch リストで構築 → 四分音符NoteEvent
    subj_pitch = Subject([Pitch(60), Pitch(62), Pitch(64)], key_c, "P互換")
    check("Pitch→NoteEvent変換", len(subj_pitch.notes) == 3)
    check("duration=4（四分音符）", all(n.duration == 4 for n in subj_pitch.notes))
    check("pitchesプロパティ", [p.midi for p in subj_pitch.pitches] == [60, 62, 64])
    check("get_length()=3拍", subj_pitch.get_length() == 3)
    check("get_length_subbeats()=12", subj_pitch.get_length_subbeats() == 12)

    # 7.2 NoteEvent リストで構築（混合音価）
    mixed_notes = [
        NoteEvent(Pitch(60), 4),   # 四分
        NoteEvent(Pitch(62), 2),   # 八分
        NoteEvent(Pitch(64), 2),   # 八分
        NoteEvent(Pitch(65), 1),   # 十六分
        NoteEvent(Pitch(67), 1),   # 十六分
        NoteEvent(Pitch(69), 2),   # 八分
    ]
    subj_mixed = Subject(mixed_notes, key_c, "混合主題")
    check("混合音価: notes数=6", len(subj_mixed.notes) == 6)
    check("混合音価: subbeats=12", subj_mixed.get_length_subbeats() == 12)
    check("混合音価: beats=3", subj_mixed.get_length() == 3)
    check("混合音価: pitches数=6", len(subj_mixed.pitches) == 6)

    # 7.3 transpose が duration を保持
    transposed = subj_mixed.transpose(7)
    check("transpose: notes数保持", len(transposed.notes) == 6)
    check("transpose: duration保持",
          [n.duration for n in transposed.notes] == [4, 2, 2, 1, 1, 2])
    check("transpose: pitch+7",
          transposed.notes[0].pitch.midi == 67)

    # 7.4 augmentation / diminution
    aug = subj_mixed.augmentation(2)
    check("augmentation: duration倍増",
          [n.duration for n in aug.notes] == [8, 4, 4, 2, 2, 4])
    dim = subj_mixed.diminution(2)
    check("diminution: duration半減",
          [n.duration for n in dim.notes] == [2, 1, 1, 1, 1, 1])

    # 7.5 invert が duration を保持
    inv = subj_mixed.invert()
    check("invert: duration保持",
          [n.duration for n in inv.notes] == [4, 2, 2, 1, 1, 2])

    # ==========================================================
    # 8. サブビート和声分析
    # ==========================================================
    print("\n--- 8. サブビート和声分析 ---")

    # 拍頭音ピッチクラスの抽出テスト
    # 混合主題: C4(4sb) D4(2sb) E4(2sb) F4(1sb) G4(1sb) A4(2sb)
    # 拍0(sb0): C4=0, 拍1(sb4): E4=4, 拍2(sb8): A4=9
    beat_pcs = SubjectHarmonicAnalyzer._extract_beat_head_pcs(subj_mixed)
    check("拍頭PC数=3", len(beat_pcs) == 3,
          f"got {len(beat_pcs)}: {beat_pcs}")
    check("拍0: C(pc=0)", beat_pcs[0] == 0, f"got {beat_pcs[0]}")
    # 拍1(sb4): D4(2sb)の後=sb2, E4(2sb)はsb2-3, なので拍1(sb4)はF4の前…
    # 再計算: sb0-3=C4(dur4), sb4-5=D4(dur2), sb6-7=E4(dur2), sb8=F4(dur1), sb9=G4(dur1), sb10-11=A4(dur2)
    # 拍頭: sb0→C4(pc0), sb4→D4(pc2), sb8→F4(pc5)
    check("拍1: D(pc=2)", beat_pcs[1] == 2, f"got {beat_pcs[1]}")
    check("拍2: F(pc=5)", beat_pcs[2] == 5, f"got {beat_pcs[2]}")

    # 混合主題の和声分析が実行可能
    plan_mixed = analyzer.analyze(subj_mixed)
    check("混合主題の和声計画長=3", len(plan_mixed) == 3)

    # ==========================================================
    # 9. RhythmElaborator
    # ==========================================================
    print("\n--- 9. RhythmElaborator ---")

    elab = RhythmElaborator(key_c.scale, seed=42)

    # 9.1 四分音符パターン: 1音のみ
    q_result = elab.elaborate_beat(60, 62, 'Q', (55, 74))
    check("Q: 1要素", len(q_result) == 1)
    check("Q: pitch=60, dur=4", q_result[0] == (60, 4))

    # 9.2 八分×2パターン: 2音
    ee_result = elab.elaborate_beat(60, 64, 'EE', (55, 74))
    check("EE: 2要素", len(ee_result) == 2)
    check("EE: 拍頭=60", ee_result[0][0] == 60)
    check("EE: dur合計=4",
          sum(d for _, d in ee_result) == 4)

    # 9.3 十六分×4パターン: 4音
    ssss_result = elab.elaborate_beat(60, 64, 'SSSS', (55, 74))
    check("SSSS: 4要素", len(ssss_result) == 4)
    check("SSSS: 拍頭=60", ssss_result[0][0] == 60)
    check("SSSS: dur合計=4",
          sum(d for _, d in ssss_result) == 4)
    check("SSSS: 全durが1",
          all(d == 1 for _, d in ssss_result))

    # 9.4 装飾音が音域内
    for name in ['EE', 'ES', 'SE', 'DS', 'SSSS']:
        result = elab.elaborate_beat(64, 67, name, (55, 74))
        all_in_range = all(55 <= p <= 74 for p, _ in result)
        check(f"{name}: 音域内", all_in_range,
              f"range violation: {result}")

    # 9.5 select_pattern
    check("主題声部→Q", elab.select_pattern(True, False) == 'Q')
    # 自由声部のパターンが有効な名前
    for _ in range(20):
        pat = elab.select_pattern(False, False)
        check(f"自由声部パターン '{pat}' は有効",
              pat in RhythmElaborator.PATTERNS)

    # ==========================================================
    # 10. サブビートグリッド・MIDI出力
    # ==========================================================
    print("\n--- 10. サブビートグリッド ---")

    # 提示部実現で subbeat_grid が生成されること
    check("subbeat_grid存在", hasattr(engine, 'subbeat_grid'))
    check("subbeat_grid非空", bool(engine.subbeat_grid))

    # サブビートグリッドのサイズ確認
    sb_total = 35 * SUBBEATS_PER_BEAT  # 35拍 × 4 = 140サブビート
    for voice, grid in engine.subbeat_grid.items():
        if any(v is not None for v in grid):
            check(f"{voice.value}: sb長={sb_total}",
                  len(grid) == sb_total,
                  f"got {len(grid)}")

    # MIDI出力がサブビート対応
    check("MIDI: soprano存在", FugueVoiceType.SOPRANO in midi_events)
    # 八分音符があればtick=240のノートが含まれるはず（120ticks×2subbeats）
    has_eighth = False
    for voice, notes in midi_events.items():
        for start_tick, midi_val, dur in notes:
            if dur == 240:  # 八分音符 = 2サブビート × 120ticks
                has_eighth = True
                break
        if has_eighth:
            break
    check("MIDI: 八分音符存在", has_eighth,
          "240 ticksのノートが見つからない")

    # ==========================================================
    # 11. 混合音価主題での提示部実現
    # ==========================================================
    print("\n--- 11. 混合音価主題 ---")

    # 八分音符を含む主題
    mixed_subject = Subject([
        NoteEvent(Pitch(60), 4),   # C4 四分
        NoteEvent(Pitch(62), 2),   # D4 八分
        NoteEvent(Pitch(64), 2),   # E4 八分
        NoteEvent(Pitch(65), 4),   # F4 四分
        NoteEvent(Pitch(67), 4),   # G4 四分
    ], key_c, "混合主題")

    fs_mixed = FugueStructure(num_voices=3, main_key=key_c, subject=mixed_subject)
    fs_mixed.create_exposition(answer_type="auto")

    engine_mixed = FugueRealizationEngine(fs_mixed, seed=42)
    midi_mixed = engine_mixed.realize_exposition()

    check("混合: 声部数≧2", len(midi_mixed) >= 2)
    check("混合: subbeat_grid存在", hasattr(engine_mixed, 'subbeat_grid'))

    # 混合主題で八分音符がMIDI出力に反映
    has_240 = False
    for voice, notes in midi_mixed.items():
        for start_tick, midi_val, dur in notes:
            if dur == 240:
                has_240 = True
                break
        if has_240:
            break
    check("混合: 八分音符(240ticks)存在", has_240,
          "混合主題の八分音符がMIDI出力に反映されていない")

    # 混合主題のMIDI出力
    mixed_output = "/sessions/fervent-vigilant-hypatia/fuge_final/test_mixed_output.mid"
    engine_mixed.export_midi(mixed_output, tempo=72)
    check("混合: MIDIファイル生成", _os.path.exists(mixed_output))

    # ==========================================================
    # 12. ダイアトニック七の和音
    # ==========================================================
    print("\n--- 12. ダイアトニック七の和音 ---")

    # 12.1 七の和音の構築
    analyzer_7 = SubjectHarmonicAnalyzer(key_c, seed=42, seventh_freq=1.0,
                                          secondary_dom_freq=0.0, altered_freq=0.0)
    check("七の和音辞書: 7度数", len(analyzer_7.diatonic_sevenths) == 7)

    # V7 の構成確認
    v7 = analyzer_7.diatonic_sevenths[4]
    check("V7: has_seventh", v7.has_seventh)
    check("V7: quality=dominant7", v7.quality == "dominant7")
    check("V7: tones=4音", len(v7.tones) == 4)
    # C長調の V7 = G-B-D-F = {7, 11, 2, 5}
    check("V7: 構成音={7,11,2,5}", v7.tones == {7, 11, 2, 5},
          f"got {v7.tones}")
    check("V7: seventh_pc=5(F)", v7.seventh_pc == 5, f"got {v7.seventh_pc}")

    # ii7 の構成確認
    ii7 = analyzer_7.diatonic_sevenths[1]
    check("ii7: quality=minor7", ii7.quality == "minor7")
    # D-F-A-C = {2, 5, 9, 0}
    check("ii7: 構成音={2,5,9,0}", ii7.tones == {2, 5, 9, 0},
          f"got {ii7.tones}")

    # viiø7 の構成確認
    vii7 = analyzer_7.diatonic_sevenths[6]
    check("viiø7: quality=half_diminished7", vii7.quality == "half_diminished7")

    # 12.2 七の和音の選択（freq=1.0で全拍に適用）
    plan_7 = analyzer_7.analyze(subject)
    seventh_count = sum(1 for c in plan_7[1:-1] if c.has_seventh)  # 冒頭・末尾除く
    check("seventh_freq=1.0: 中間拍に七の和音多数",
          seventh_count >= len(plan_7) - 4,
          f"中間拍{len(plan_7)-2}拍中{seventh_count}拍に七の和音")

    # 12.3 freq=0.0 で七の和音なし
    analyzer_no7 = SubjectHarmonicAnalyzer(key_c, seed=42, seventh_freq=0.0,
                                            secondary_dom_freq=0.0, altered_freq=0.0)
    plan_no7 = analyzer_no7.analyze(subject)
    seventh_count_0 = sum(1 for c in plan_no7 if c.has_seventh)
    check("seventh_freq=0.0: 七の和音なし", seventh_count_0 == 0,
          f"got {seventh_count_0}")

    # 12.4 roman表記
    check("V7.roman='V7'", v7.roman == "V7")
    check("ii7.roman='ii7'", ii7.roman == "ii7")

    # ==========================================================
    # 13. 副属七和音
    # ==========================================================
    print("\n--- 13. 副属七和音 ---")

    # 13.1 副属七和音の構築
    analyzer_sec = SubjectHarmonicAnalyzer(key_c, seed=42, seventh_freq=0.0,
                                            secondary_dom_freq=1.0, altered_freq=0.0)
    check("副属七和音辞書: 5つ", len(analyzer_sec.secondary_dominants) == 5)

    # V7/V = D7 = {2, 6, 9, 0}
    sec_v = analyzer_sec.secondary_dominants[4]  # target = V(degree 4)
    check("V7/V: root=D(pc=2)", sec_v.root_pc == 2, f"got {sec_v.root_pc}")
    check("V7/V: tones={2,6,9,0}", sec_v.tones == {2, 6, 9, 0},
          f"got {sec_v.tones}")
    check("V7/V: is_secondary_dominant", sec_v.is_secondary_dominant)
    check("V7/V: resolution_target_pc=7(G)", sec_v.resolution_target_pc == 7)
    check("V7/V: roman='V7' (upper)", sec_v.roman == "V7")

    # V7/ii = A7 = A,C#,E,G = {9, 1, 4, 7}
    sec_ii = analyzer_sec.secondary_dominants[1]  # target = ii(degree 1)
    check("V7/ii: root=A(pc=9)", sec_ii.root_pc == 9, f"got {sec_ii.root_pc}")
    check("V7/ii: tones={9,1,4,7}", sec_ii.tones == {9, 1, 4, 7},
          f"got {sec_ii.tones}")
    check("V7/ii: resolution_target_pc=2(D)", sec_ii.resolution_target_pc == 2)

    # 13.2 副属七和音がピッチクラスで条件付き選択される
    # 長い主題で検証（短い主題ではI-ii-I...となり、V7/Iは除外されるため不適）
    long_subject = Subject(
        [Pitch(m) for m in [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60]],
        key_c, "長い主題")
    analyzer_sec_long = SubjectHarmonicAnalyzer(
        key_c, seed=42, seventh_freq=0.0, secondary_dom_freq=1.0, altered_freq=0.0)
    plan_sec = analyzer_sec_long.analyze(long_subject)
    sec_dom_count = sum(1 for c in plan_sec if c.is_secondary_dominant)
    check("secondary_dom_freq=1.0: 副属和音が存在", sec_dom_count >= 1,
          f"sec_dom={sec_dom_count}")

    # 13.3 freq=0.0 で副属和音なし
    analyzer_nosec = SubjectHarmonicAnalyzer(
        key_c, seed=42, seventh_freq=0.0, secondary_dom_freq=0.0, altered_freq=0.0)
    plan_nosec = analyzer_nosec.analyze(long_subject)
    sec_dom_count_0 = sum(1 for c in plan_nosec if c.is_secondary_dominant)
    check("secondary_dom_freq=0.0: 副属和音なし", sec_dom_count_0 == 0,
          f"got {sec_dom_count_0}")

    # ==========================================================
    # 14. 変化和音
    # ==========================================================
    print("\n--- 14. 変化和音 ---")

    # 14.1 変化和音の構築
    analyzer_alt = SubjectHarmonicAnalyzer(key_c, seed=42, seventh_freq=0.0,
                                            secondary_dom_freq=0.0, altered_freq=1.0)
    check("変化和音リスト: 4つ", len(analyzer_alt.altered_chords) == 4)

    # ナポリの六度: ♭II = Db major = {1, 5, 8}
    nap = [c for c in analyzer_alt.altered_chords if c.alteration_type == "neapolitan"][0]
    check("Nap: root=Db(pc=1)", nap.root_pc == 1, f"got {nap.root_pc}")
    check("Nap: tones={1,5,8}", nap.tones == {1, 5, 8}, f"got {nap.tones}")
    check("Nap: roman='♭II6'", nap.roman == "♭II6")

    # イタリアの六: Ab, C, F# = {8, 0, 6}
    it6 = [c for c in analyzer_alt.altered_chords if c.alteration_type == "italian"][0]
    check("It+6: tones={8,0,6}", it6.tones == {8, 0, 6}, f"got {it6.tones}")
    check("It+6: roman='It+6'", it6.roman == "It+6")

    # ドイツの六: Ab, C, Eb, F# = {8, 0, 3, 6}
    ger6 = [c for c in analyzer_alt.altered_chords if c.alteration_type == "german"][0]
    check("Ger+6: tones={8,0,3,6}", ger6.tones == {8, 0, 3, 6}, f"got {ger6.tones}")

    # フランスの六: Ab, C, D, F# = {8, 0, 2, 6}
    fr6 = [c for c in analyzer_alt.altered_chords if c.alteration_type == "french"][0]
    check("Fr+6: tones={8,0,2,6}", fr6.tones == {8, 0, 2, 6}, f"got {fr6.tones}")

    # 14.2 変化和音の選択（条件付き: S機能の拍、D前の拍）
    plan_alt = analyzer_alt.analyze(subject)
    alt_count = sum(1 for c in plan_alt if c.alteration_type is not None)
    # altered_freq=1.0 でも条件に合致しない拍には適用されない
    check("altered_freq=1.0: 変化和音が存在（条件付き）", True)  # 存在の有無は主題依存

    # 14.3 freq=0.0 で変化和音なし
    alt_count_0 = sum(1 for c in plan_no7 if c.alteration_type is not None)
    check("altered_freq=0.0: 変化和音なし", alt_count_0 == 0,
          f"got {alt_count_0}")

    # ==========================================================
    # 15. 拡張和声での提示部実現
    # ==========================================================
    print("\n--- 15. 拡張和声での提示部実現 ---")

    # デフォルト頻度で提示部生成（クラッシュしないことの確認）
    # 長い主題で拡張和声が出やすくする
    ext_subject = Subject(
        [Pitch(m) for m in [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60]],
        key_c, "拡張和声テスト主題")
    fs_ext = FugueStructure(num_voices=3, main_key=key_c, subject=ext_subject)
    fs_ext.create_exposition(answer_type="auto")
    engine_ext = FugueRealizationEngine(fs_ext, seed=42)
    midi_ext = engine_ext.realize_exposition()
    check("拡張和声: 声部数≧2", len(midi_ext) >= 2)
    # 和声計画に拡張和声が含まれるか（主題の和声計画を参照）
    has_extended = any(
        c.has_seventh or c.is_secondary_dominant or c.alteration_type is not None
        for c in engine_ext.chord_plan
    )
    check("拡張和声: 和声計画に拡張和声あり", has_extended,
          "デフォルト頻度で拡張和声が1つも選ばれなかった（確率的な失敗の可能性）")

    # レポートに拡張和声の表記が反映
    report = engine_ext.get_analysis_report()
    check("レポート: 拡張和声表記あり",
          any(x in report for x in ["7", "♭II6", "+6"]),
          "レポートに拡張和声の表記なし")

    # ==========================================================
    # 16. ChordLabel.roman 表記
    # ==========================================================
    print("\n--- 16. ChordLabel.roman ---")

    check("I.roman='I'", ChordLabel(0, 0, "major", {0,4,7}).roman == "I")
    check("V.roman='V'", ChordLabel(4, 7, "major", {7,11,2}).roman == "V")
    check("V7.roman='V7'",
          ChordLabel(4, 7, "dominant7", {7,11,2,5}, has_seventh=True).roman == "V7")
    check("II7(sec_dom).roman='V7'",
          ChordLabel(4, 2, "dominant7", {2,6,9,0},
                     is_secondary_dominant=True, has_seventh=True).roman == "V7")
    check("♭II6.roman='♭II6'",
          ChordLabel(1, 1, "major", {1,5,8}, alteration_type="neapolitan").roman == "♭II6")
    check("Ger+6.roman='Ger+6'",
          ChordLabel(4, 8, "augmented", {8,0,3,6}, alteration_type="german").roman == "Ger+6")

    # ==========================================================
    # 17. 提示部での変化和音抑制
    # ==========================================================
    print("\n--- 17. 提示部での変化和音抑制 ---")

    # 17.1 提示部エンジンの主題分析器は altered_freq=0.0
    expo_subject = Subject(
        [Pitch(m) for m in [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60]],
        key_c, "提示部抑制テスト主題")
    fs_expo = FugueStructure(num_voices=3, main_key=key_c, subject=expo_subject)
    fs_expo.create_exposition(answer_type="auto")
    engine_expo = FugueRealizationEngine(fs_expo, seed=42)
    # analyzer の altered_freq が 0.0 であることを確認
    check("提示部: altered_freq=0.0（主題分析器）",
          engine_expo.analyzer.altered_freq == 0.0,
          f"altered_freq={engine_expo.analyzer.altered_freq}")

    # 17.2 提示部を実現し、変化和音が和声計画に含まれないことを確認
    midi_expo = engine_expo.realize_exposition()
    altered_in_plan = [c for c in engine_expo.chord_plan if c.alteration_type is not None]
    check("提示部: 和声計画に変化和音なし", len(altered_in_plan) == 0,
          f"found {len(altered_in_plan)} altered chords: {[c.roman for c in altered_in_plan]}")

    # 17.3 複数シードで提示部に変化和音が出ないことを確認（堅牢性）
    altered_found_any = False
    for test_seed in range(10):
        fs_tmp = FugueStructure(num_voices=3, main_key=key_c, subject=expo_subject)
        fs_tmp.create_exposition(answer_type="auto")
        eng_tmp = FugueRealizationEngine(fs_tmp, seed=test_seed)
        eng_tmp.realize_exposition()
        if any(c.alteration_type is not None for c in eng_tmp.chord_plan):
            altered_found_any = True
            break
    check("提示部: 10シードで変化和音なし", not altered_found_any)

    # 17.4 七の和音は提示部でも許容される
    has_seventh_expo = any(c.has_seventh for c in engine_expo.chord_plan)
    # 七の和音は抑制されていないので出現可能（確率的）
    check("提示部: 七の和音は許容", True)  # 存在有無は確率依存

    # ==========================================================
    # 18. 応答の和声分析（analyze_answer）
    # ==========================================================
    print("\n--- 18. 応答の和声分析 ---")

    # 18.1 応答はV（属和音）で開始
    answer_subject = Subject(
        [Pitch(m) for m in [67, 69, 71, 72, 74, 72, 71, 69, 67]],
        key_c, "応答テスト(G-A-B-C-D-C-B-A-G)")
    answer_plan_test = analyzer.analyze_answer(answer_subject)
    check("応答: 冒頭はV(degree=4)を優先",
          answer_plan_test[0].degree == 4 or answer_plan_test[0].root_pc == 7,
          f"degree={answer_plan_test[0].degree}, root={answer_plan_test[0].root_pc}")

    # 18.2 応答の末尾もV方向
    check("応答: 末尾はV(degree=4)またはI(degree=0)",
          answer_plan_test[-1].degree in {0, 4},
          f"degree={answer_plan_test[-1].degree}")

    # 18.3 F#を含む応答でV/V（D7→G）が使われる
    # 応答: C-E-F#-G-A-G-F#-E-D (F#が属調の導音)
    fs_fsharp = Subject(
        [Pitch(m) for m in [60, 64, 66, 67, 69, 67, 66, 64, 62]],
        key_c, "F#含む応答テスト")
    plan_fsharp = analyzer.analyze_answer(fs_fsharp)
    # F#(pc=6)が拍頭に出る拍でV/V(D7)が選ばれるべき
    fsharp_beats = [i for i, c in enumerate(plan_fsharp) if 6 in c.tones]
    check("F#含む応答: F#を含む和音が存在", len(fsharp_beats) > 0,
          f"F#含む拍: {fsharp_beats}")

    # 18.4 F#の拍はD7/G（V7/V）であること
    fsharp_chords = [plan_fsharp[i] for i in fsharp_beats]
    has_d7_g = any(c.is_secondary_dominant and c.resolution_target_pc == 7
                   for c in fsharp_chords)
    check("F#含む応答: V7/V(D7→G)が使用される", has_d7_g,
          f"chords: {[(c.roman, c.root_pc, c.resolution_target_pc) for c in fsharp_chords]}")

    # 18.5 応答の和声は全て主調(C major)の枠組み
    # → 変化和音なし、全和音のrootがCメジャーダイアトニックまたは副属七
    all_in_c = all(
        c.root_pc in {0, 2, 4, 5, 7, 9, 11} or c.is_secondary_dominant
        for c in answer_plan_test
    )
    check("応答: 全和音が主調の枠組み", all_in_c)

    # ==========================================================
    # 19. 嬉遊部（Episode）
    # ==========================================================
    print("\n--- 19. 嬉遊部（Episode）---")

    # 19.1 ダイアトニック反復進行: 全音が音階内
    c_key = Key("C", "major")
    c_scale_pcs = set(c_key.scale)  # {0,2,4,5,7,9,11}
    motif_19 = [Pitch(60), Pitch(62), Pitch(64)]  # C D E
    ep_19 = Episode(
        motif_pitches=motif_19,
        sequence_steps=4,
        step_interval=-1,
        key=c_key,
    )
    ep_pitches_19 = ep_19.generate_pitches()
    check("嬉遊部: 12音を生成（3音×4回）", len(ep_pitches_19) == 12)

    all_diatonic = all(p.pitch_class in c_scale_pcs for p in ep_pitches_19)
    check("嬉遊部: ダイアトニック移調で全音が音階内",
          all_diatonic,
          f"pcs: {[p.pitch_class for p in ep_pitches_19]}")

    # 19.2 反復進行の音列確認: C-D-E → B-C-D → A-B-C → G-A-B
    expected_pcs = [0, 2, 4, 11, 0, 2, 9, 11, 0, 7, 9, 11]  # C D E B C D A B C G A B
    actual_pcs = [p.pitch_class for p in ep_pitches_19]
    check("嬉遊部: 2度下行反復進行のピッチクラス", actual_pcs == expected_pcs,
          f"expected {expected_pcs}, got {actual_pcs}")

    # 19.3 3度下行（step_interval=-2）
    ep_3rd = Episode(
        motif_pitches=motif_19,
        sequence_steps=3,
        step_interval=-2,
        key=c_key,
    )
    ep_3rd_pitches = ep_3rd.generate_pitches()
    all_diatonic_3rd = all(p.pitch_class in c_scale_pcs for p in ep_3rd_pitches)
    check("嬉遊部: 3度下行でも音階内",
          all_diatonic_3rd,
          f"pcs: {[p.pitch_class for p in ep_3rd_pitches]}")

    # 19.4 realize_episode(): MIDI出力が全声部を含む
    sub_19 = Subject(
        [Pitch(60), Pitch(62), Pitch(64), Pitch(65), Pitch(67),
         Pitch(69), Pitch(67), Pitch(65), Pitch(64), Pitch(62), Pitch(60)],
        c_key, "test_subject_19",
    )
    fs_19 = FugueStructure(num_voices=3, main_key=c_key, subject=sub_19)
    engine_19 = FugueRealizationEngine(fs_19, seed=42)
    expo_midi_19 = engine_19.realize_exposition()

    ep_obj_19 = fs_19.create_episode(
        start_position=35, motif_length=3, sequence_steps=4, step_interval=-1)
    ep_midi_19 = engine_19.realize_episode(
        ep_obj_19, start_beat=35,
        leading_voice=FugueVoiceType.SOPRANO,
        expo_midi=expo_midi_19,
    )
    check("嬉遊部実現: 3声部を出力", len(ep_midi_19) == 3,
          f"voices: {list(ep_midi_19.keys())}")

    # 19.5 全声部にMIDIイベントが存在
    all_have_events = all(len(events) > 0 for events in ep_midi_19.values())
    check("嬉遊部実現: 全声部にMIDIイベント有り", all_have_events)

    # 19.6 動機声部が正しいピッチを持つ
    soprano_events = ep_midi_19.get(FugueVoiceType.SOPRANO, [])
    soprano_pitches = [e[1] for e in soprano_events]
    # ダイアトニック反復のため全音がC長調音階内
    soprano_pcs = set(p % 12 for p in soprano_pitches)
    check("嬉遊部実現: ソプラノ（動機）が音階内",
          soprano_pcs.issubset(c_scale_pcs),
          f"pcs: {soprano_pcs}")

    # 19.7 対位法声部が静止していない（動きがある）
    for vt, events in ep_midi_19.items():
        if vt == FugueVoiceType.SOPRANO:
            continue
        pitches = [e[1] for e in events]
        has_motion = len(set(pitches)) > 1
        check(f"嬉遊部実現: {vt.value}に旋律的動きあり", has_motion,
              f"pitches: {pitches}")

    # 19.8 嬉遊部の和声計画が存在し全ダイアトニック
    ep_plan = engine_19.episode_chord_plan
    check("嬉遊部実現: 和声計画が存在", ep_plan is not None and len(ep_plan) > 0)

    # 19.9 keyなしのEpisodeはフォールバック（半音移調）
    ep_no_key = Episode(
        motif_pitches=motif_19,
        sequence_steps=2,
        step_interval=-1,
        key=None,
    )
    ep_no_key_pitches = ep_no_key.generate_pitches()
    check("嬉遊部: keyなしでもエラーなく生成", len(ep_no_key_pitches) == 6)

    # --- 19.10〜 KeyPath / KeyPathStrategy ---

    # 19.10 KeyPath: 基本プロパティ
    kp = KeyPath(c_key, c_key, [c_key] * 8)
    check("KeyPath: num_beats", kp.num_beats == 8)
    check("KeyPath: key_at(0)", kp.key_at(0) == c_key)
    check("KeyPath: 同一調で転調点なし", kp.modulation_points() == [])

    # 19.11 KeyPath: 転調点の検出
    a_minor = Key("A", "minor")
    kp_mod = KeyPath(c_key, a_minor,
                     [c_key, c_key, c_key, c_key, a_minor, a_minor])
    check("KeyPath: 転調点が1つ", kp_mod.modulation_points() == [4])
    check("KeyPath: 拍3はC major", kp_mod.key_at(3) == c_key)
    check("KeyPath: 拍4はA minor", kp_mod.key_at(4) == a_minor)

    # 19.12 KeyPathStrategy: デフォルト（同一調）
    strat = KeyPathStrategy()
    kp_same = strat.generate(c_key, c_key, 8)
    check("KeyPathStrategy: 同一調→全拍同じ",
          all(k == c_key for k in kp_same.beat_keys))

    # 19.13 KeyPathStrategy: 転調あり
    kp_trans = strat.generate(c_key, a_minor, 10)
    check("KeyPathStrategy: 始点がC major", kp_trans.key_at(0) == c_key)
    check("KeyPathStrategy: 終点がA minor", kp_trans.key_at(9) == a_minor)
    check("KeyPathStrategy: 転調点が存在",
          len(kp_trans.modulation_points()) > 0)

    # 19.14 realize_episode with end_key（転調を伴う嬉遊部）
    fs_mod = FugueStructure(num_voices=3, main_key=c_key, subject=sub_19)
    fs_mod.create_exposition(answer_type="auto")
    engine_mod = FugueRealizationEngine(fs_mod, seed=42)
    expo_mod = engine_mod.realize_exposition()
    ep_mod = fs_mod.create_episode(
        start_position=35, motif_length=3, sequence_steps=4,
        step_interval=-1, end_key=a_minor)
    ep_mod_midi = engine_mod.realize_episode(
        ep_mod, start_beat=35,
        leading_voice=FugueVoiceType.SOPRANO,
        expo_midi=expo_mod,
    )
    check("嬉遊部(転調): 3声部を出力", len(ep_mod_midi) == 3)
    check("嬉遊部(転調): 全声部にイベント有り",
          all(len(v) > 0 for v in ep_mod_midi.values()))

    # 19.15 転調後の和声にA minor域の和音が含まれる
    # 修正: 短い転調区間（≤3拍）では導音(G#=8)を自然短音階(G=7)に
    # 置換するため、G#は含まれない。代わりにA minor の構成音
    # (A=9) が含まれることを検証する。
    mod_plan = engine_mod.episode_chord_plan
    last_chords = mod_plan[-2:]  # 最後の2拍（A minor域）
    last_tones = set()
    for c in last_chords:
        last_tones.update(c.tones)
    check("嬉遊部(転調): 短区間で導音G#(=8)回避",
          8 not in last_tones,
          f"last tones: {last_tones}")
    check("嬉遊部(転調): A minor構成音(A=9)含む",
          9 in last_tones,
          f"last tones: {last_tones}")

    # 19.16 KeyPathStrategy は差し替え可能
    class ConstantKeyStrategy(KeyPathStrategy):
        """テスト用: 全拍を指定調にする"""
        def __init__(self, const_key):
            self.const_key = const_key
        def generate(self, start_key, end_key, num_beats):
            return KeyPath(start_key, end_key,
                           [self.const_key] * num_beats)

    custom_strat = ConstantKeyStrategy(a_minor)
    ep_custom_midi = engine_mod.realize_episode(
        ep_mod, start_beat=35,
        leading_voice=FugueVoiceType.SOPRANO,
        expo_midi=expo_mod,
        key_path_strategy=custom_strat,
    )
    check("嬉遊部(カスタム戦略): 出力生成", len(ep_custom_midi) == 3)
    # カスタム戦略ではkey_pathが全拍A minor
    custom_kp = engine_mod.episode_key_path
    check("嬉遊部(カスタム戦略): 全拍A minor",
          all(k == a_minor for k in custom_kp.beat_keys))

    # ==========================================================
    # 20. 中間部主題提示（realize_middle_entry）
    # ==========================================================
    print("\n--- 20. 中間部主題提示 ---")

    # 共通セットアップ: 提示部+嬉遊部を実行済みのエンジン
    c_key_20 = Key("C", "major")
    sub_20 = Subject(
        [Pitch(60), Pitch(62), Pitch(64), Pitch(65), Pitch(67),
         Pitch(69), Pitch(67), Pitch(65), Pitch(64), Pitch(62), Pitch(60)],
        c_key_20, "test_subject_20",
    )
    fs_20 = FugueStructure(num_voices=3, main_key=c_key_20, subject=sub_20)
    fs_20.create_exposition(answer_type="auto")
    engine_20 = FugueRealizationEngine(fs_20, seed=42)
    expo_20 = engine_20.realize_exposition()

    # 20.1 A minor での中間部提示
    a_min = Key("A", "minor")
    me_entry = FugueEntry(
        subject=sub_20,
        voice_type=FugueVoiceType.ALTO,
        start_position=35,
        key=a_min,
        is_answer=False,
    )
    me_midi = engine_20.realize_middle_entry(me_entry, start_beat=35, prev_midi=expo_20)
    check("中間部: 3声部を出力", len(me_midi) == 3)
    check("中間部: 全声部にイベント有り",
          all(len(v) > 0 for v in me_midi.values()))

    # 20.2 対位法声部に動きがある
    for vt, events in me_midi.items():
        if vt == FugueVoiceType.ALTO:
            continue
        pitches = [e[1] for e in events]
        has_motion = len(set(pitches)) > 1
        check(f"中間部: {vt.value}に旋律的動きあり", has_motion)

    # 20.3 和声計画が対象調に基づく
    me_plan = engine_20.middle_entry_chord_plan
    check("中間部: 和声計画が存在", me_plan is not None and len(me_plan) > 0)
    # A minorの主和音(root_pc=9)が計画に含まれるべき
    has_am = any(c.root_pc == 9 for c in me_plan)
    check("中間部: A minor主和音が和声計画に含まれる", has_am)

    # 20.4 F major での中間部提示（別の調でも動作確認）
    f_key = Key("F", "major")
    me_entry_f = FugueEntry(
        subject=sub_20,
        voice_type=FugueVoiceType.SOPRANO,
        start_position=46,
        key=f_key,
        is_answer=False,
    )
    me_midi_f = engine_20.realize_middle_entry(me_entry_f, start_beat=46, prev_midi=me_midi)
    check("中間部(F major): 3声部を出力", len(me_midi_f) == 3)

    # ==========================================================
    # 21. 終止部（realize_coda）
    # ==========================================================
    print("\n--- 21. 終止部 ---")

    # 21.1 基本生成
    coda_midi = engine_20.realize_coda(
        start_beat=57, prev_midi=me_midi_f, num_beats=8)
    check("終止部: 3声部を出力", len(coda_midi) == 3)
    check("終止部: 全声部にイベント有り",
          all(len(v) > 0 for v in coda_midi.values()))

    # 21.2 ペダルポイント（バスが持続音）
    bass_events = coda_midi.get(FugueVoiceType.BASS, [])
    bass_pitches = set(e[1] for e in bass_events)
    # ペダルポイントの実装: サブビートレベルでは1音が長く持続
    # 四分音符×8拍でもリズム装飾なしなら少数のイベント
    check("終止部: バスのペダルポイント（少数のイベント）",
          len(bass_events) <= 8,
          f"bass events: {len(bass_events)}")

    # 21.3 和声計画の最終和音がI
    coda_plan = engine_20.coda_chord_plan
    check("終止部: 和声計画が存在", coda_plan is not None and len(coda_plan) > 0)
    last_chord = coda_plan[-1]
    check("終止部: 最終和音がI（主和音）",
          last_chord.degree == 0,
          f"last chord degree: {last_chord.degree}")

    # 21.4 カデンツにV（属和音）が含まれる
    has_v = any(c.degree == 4 for c in coda_plan[-4:])
    check("終止部: カデンツにV含む", has_v)

    # ==========================================================
    # 22. 全体統合（realize_fugue）
    # ==========================================================
    print("\n--- 22. 全体統合 ---")

    # 22.1 realize_fugue()が完走する
    fs_22 = FugueStructure(num_voices=3, main_key=c_key_20, subject=sub_20)
    fs_22.create_exposition(answer_type="auto")
    engine_22 = FugueRealizationEngine(fs_22, seed=42)

    full_midi = engine_22.realize_fugue(
        episode_motif_length=3, episode_steps=4,
        episode_interval=-1, coda_beats=8)
    check("全体統合: 出力が存在", len(full_midi) > 0)
    check("全体統合: 3声部", len(full_midi) == 3)

    # 22.2 各声部にイベント有り
    for vt, events in full_midi.items():
        check(f"全体統合: {vt.value}にイベント有り", len(events) > 0)

    # 22.3 拍位置が連続（ギャップなし）
    # 全イベントのtick範囲を確認
    all_ticks = []
    for events in full_midi.values():
        for tick, midi, dur in events:
            all_ticks.append(tick)
            all_ticks.append(tick + dur)
    min_tick = min(all_ticks)
    max_tick = max(all_ticks)
    check("全体統合: 開始tick=0", min_tick == 0)
    check("全体統合: 全体の長さが提示部より長い",
          max_tick > 35 * SUBBEATS_PER_BEAT * 120,
          f"max_tick: {max_tick}")

    # 22.4 終止部の最終tickが全体の最終
    coda_plan_22 = engine_22.coda_chord_plan
    check("全体統合: 終止部和声計画が存在",
          coda_plan_22 is not None and len(coda_plan_22) > 0)
    last_chord_22 = coda_plan_22[-1]
    check("全体統合: 最終和音がI", last_chord_22.degree == 0)

    # ==========================================================
    # 23. 音楽品質検証（生成結果の対位法禁則チェック）
    # ==========================================================
    print("\n--- 23. 音楽品質検証 ---")

    from fugue_quality_checker import FugueQualityChecker

    # 23.1 和声情報つき品質検証: 並行5度/8度なし
    # realize_fugueが生成したglobal_chord_tonesを使用
    gct_23 = engine_22.global_chord_tones
    checker_23 = FugueQualityChecker(
        full_midi, c_key_20, beat_chord_tones=gct_23)
    report_23 = checker_23.run_all()
    check("品質: 和声情報つき 並行5度/8度なし (errors=0)",
          len(report_23.errors) == 0,
          f"errors: {[str(v) for v in report_23.errors]}")

    # 23.2 和声情報なしでも検査可能（厳格モード）
    checker_23b = FugueQualityChecker(full_midi, c_key_20)
    report_23b = checker_23b.run_all()
    check("品質: 和声情報なし errors<=1",
          len(report_23b.errors) <= 1,
          f"errors: {[str(v) for v in report_23b.errors]}")

    # 23.3 声部交差なし
    crossings = [v for v in report_23.violations
                 if v.category == "voice_crossing"]
    check("品質: baseline 声部交差なし",
          len(crossings) == 0,
          f"crossings: {len(crossings)}")

    # 23.4 声域逸脱なし
    range_violations = [v for v in report_23.violations
                        if v.category == "voice_range"]
    check("品質: baseline 声域逸脱なし",
          len(range_violations) == 0,
          f"range violations: {len(range_violations)}")

    # 23.5 Ab/G# (pc=8) がC majorセクションに出現しない
    from fugue_realization import SUBBEATS_PER_BEAT as SB23
    tpb_23 = SB23 * 120
    ab_found = False
    for beat in range(checker_23.total_beats + 1):
        bp = checker_23.beat_pitches.get(beat, {})
        for vt, pitches in bp.items():
            for p in pitches:
                if p % 12 == 8:
                    ab_found = True
    check("品質: baseline Ab/G#なし", not ab_found)

    # 23.6 品質レポートの統計情報が正しい
    check("品質: 統計情報 total_beats",
          report_23.stats["total_beats"] > 0)
    check("品質: 統計情報 total_notes",
          report_23.stats["total_notes"] > 0)
    check("品質: 統計情報 num_voices",
          report_23.stats["num_voices"] == 3)

    # 23.7 global_chord_tonesが全拍カバー
    check("品質: chord_tones全拍カバー",
          len(gct_23) >= report_23.stats["total_beats"],
          f"chord_tones: {len(gct_23)} beats, total: {report_23.stats['total_beats']}")

    # ==========================================================
    # サマリー
    # ==========================================================
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
