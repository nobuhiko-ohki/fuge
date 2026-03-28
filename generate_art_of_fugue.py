"""「フーガの技法」BWV 1080 基本主題によるフーガ生成

Bach: Die Kunst der Fuge, Contrapunctus I の基本主題
D-A-F-D-C#-D-E-F-G-F-E-D (D minor, 12拍)
"""
import sys, os, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from harmony_rules_complete import Pitch, NoteEvent
from fugue_structure import Key, Subject, FugueStructure, FugueVoiceType
from fugue_realization import (
    FugueRealizationEngine, SUBBEATS_PER_BEAT, SubjectHarmonicTemplate,
    ChordLabel,
)
from midi_writer import MIDIWriter
from fugue_quality_checker import FugueQualityChecker
from bach_harmony_model import ChordProgressionModel, CounterpointPatternModel
from key_transition_model import KeyTransitionModel, MarkovKeyPathStrategy
from bach_chord_data import get_bach_progression_as_chord_labels

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


# Die Kunst der Fuge BWV 1080 - 基本主題 (Contrapunctus I)
# リズム: 二分音符×5, 四分音符×2, 二分+八分タイ×1, 八分音符×3
# 最終音Dは対旋律の一部のため主題に含めない（11音）
#
# サブビート単位 (16分音符=1):
#   二分音符=8, 四分音符=4, 二分+八分タイ=10, 八分音符=2
#
# D(8)-A(8)-F(8)-D(8)-C#(8)-D(4)-E(4)-F(10)-G(2)-F(2)-E(2)
# = 64 subbeats = 16拍
#
# 音高: 科学的音名表記（中央C=C4=MIDI60）
#   日本のヤマハ式（中央C=C3）では1オクターブ低い表記になる

ART_OF_FUGUE_NOTES = [
    NoteEvent(Pitch(62), 8),   # D4  二分音符  ─ 主音
    NoteEvent(Pitch(69), 8),   # A4  二分音符  ─┐
    NoteEvent(Pitch(65), 8),   # F4  二分音符   │ 下行分散和音
    NoteEvent(Pitch(62), 8),   # D4  二分音符  ─┘
    NoteEvent(Pitch(61), 8),   # C#4 二分音符  ← 導音
    NoteEvent(Pitch(62), 4),   # D4  四分音符  ─┐
    NoteEvent(Pitch(64), 4),   # E4  四分音符   │ 順次上行
    NoteEvent(Pitch(65), 10),  # F4  二分+八分タイ│
    NoteEvent(Pitch(67), 2),   # G4  八分音符   │
    NoteEvent(Pitch(65), 2),   # F4  八分音符  ─┘ 回帰
    NoteEvent(Pitch(64), 2),   # E4  八分音符
    NoteEvent(Pitch(62), 4),   # D4  四分音符  ← 主音解決（応答冒頭と同時）
]

# D minor主題の暗黙の和声進行（Contrapunctus I 参照）
#
# サブビート→拍の対応（_expand_subject_to_beat_pitchesと整合）:
#   beat 0-1:  D(8)   sb 0-7    → i  (主音)
#   beat 2-3:  A(8)   sb 8-15   → i  (第5音)
#   beat 4-5:  F(8)   sb 16-23  → i  (第3音)
#   beat 6-7:  D(8)   sb 24-31  → i  (主音)
#   beat 8-9:  C#(8)  sb 32-39  → V  (導音=C#は不可侵) ★
#   beat 10:   D(4)   sb 40-43  → i  (導音解決)
#   beat 11:   E(4)   sb 44-47  → V  (E=A major第5音)
#   beat 12-14: F(10) sb 48-57  → i  (第3音、長い音価)
#   beat 14後半: G(2)  sb 58-59  → iv (G=第5音)
#   beat 15:   F(2)+E(2) sb 60-63 → i→V
#   beat 16:   D(4)   sb 64-67  → i  (主音解決、応答冒頭と同時)
#
# fixed_pcs: D=2, C#=1, F=5
# flexibility: "strict"=和音変更不可, "flexible"=代理和音可
ART_OF_FUGUE_HARMONY = SubjectHarmonicTemplate.from_manual([
    # (degree, quality, fixed_pcs, flexibility)
    (0, "minor", [2],  "strict"),    # beat 0:  i   (D=主音)
    (0, "minor", [2],  "strict"),    # beat 1:  i   (D継続)
    (0, "minor", [9],  "strict"),    # beat 2:  i   (A=第5音)
    (0, "minor", [9],  "strict"),    # beat 3:  i   (A継続)
    (0, "minor", [5],  "flexible"),  # beat 4:  i   (F=第3音)
    (0, "minor", [5],  "flexible"),  # beat 5:  i   (F継続)
    (0, "minor", [2],  "flexible"),  # beat 6:  i   (D=主音)
    (0, "minor", [2],  "flexible"),  # beat 7:  i   (D継続)
    (4, "major", [1],  "strict"),    # beat 8:  V   (C#=導音) ★不可侵
    (4, "major", [1],  "strict"),    # beat 9:  V   (C#継続) ★不可侵
    (0, "minor", [2],  "strict"),    # beat 10: i   (D=導音解決先)
    (4, "major", [4],  "strict"),    # beat 11: V   (E=V第5音)
    (0, "minor", [5],  "flexible"),  # beat 12: i   (F=第3音)
    (0, "minor", [5],  "flexible"),  # beat 13: i   (F継続)
    (0, "minor", [5],  "flexible"),  # beat 14: i   (F→G、拍頭はF)
    (4, "major", [4],  "strict"),    # beat 15: V   (F→E、拍後半=E=V第5音)
    (0, "minor", [2],  "strict"),    # beat 16: i   (D=主音解決) ★応答冒頭と重複
])

# 応答の和声テンプレート（全てD minor内で表現）
#
# 調的応答: A-D-C-A-G#-A-B-C-D-C-B-A
# 提示部は転調しない。応答は属音Aから始まるが、調はD minorのまま。
#
# 和声リズム: 1小節（4拍）= 1和音
#   m5 (beat 0-3):  i   = Dm (D-F-A)   ← A,Dは和声音
#   m6 (beat 4-7):  v   = Am (A-C-E)   ← C,Aは和声音
#   m7 (beat 8-11): V/v→v→V/v = E→Am→E  ← G#,BはE majorの構成音
#   m8 (beat 12-15): v  = Am (A-C-E)   ← C是和声音、D,Bは経過/倚音
#   beat 16: i = Dm（次エントリ主題と重複）
#
# ※ Bach Contrapunctus I ではm8でVII(C major)を代理和音として使用
#
# v = A minor（自然短音階の属和音、C#を含まない）
_v = ChordLabel(
    degree=4, root_pc=9, quality="minor",       # A minor
    tones={9, 0, 4},                            # A=9, C=0, E=4
)
# V/v = E major（属調Amの属和音、導音G#を含む）
_E = ChordLabel(
    degree=1, root_pc=4, quality="major",       # E major
    tones={4, 8, 11},                           # E=4, G#=8, B=11
)

ART_OF_FUGUE_ANSWER_HARMONY = SubjectHarmonicTemplate.from_manual([
    # m5: i (Dm: D-F-A) — 応答冒頭、主題解決と同時
    (0, "minor", [9],  "strict"),               # beat 0:  i (A=第5音)
    (0, "minor", [9],  "strict"),               # beat 1:  i (A継続)
    (0, "minor", [2],  "strict"),               # beat 2:  i (D=根音)
    (0, "minor", [2],  "strict"),               # beat 3:  i (D継続)
    # m6: v (Am: A-C-E) — 応答の下行分散
    (4, "minor", [0],  "strict",  _v),          # beat 4:  v (C=第3音)
    (4, "minor", [0],  "strict",  _v),          # beat 5:  v (C継続)
    (4, "minor", [9],  "strict",  _v),          # beat 6:  v (A=根音)
    (4, "minor", [9],  "strict",  _v),          # beat 7:  v (A継続)
    # m7: G#→A→B→C = E(V/v)→Am(v)→E(V/v)→...
    (1, "major", [8],  "strict"),               # beat 8:  G#=固定（C26→E major）
    (1, "major", [8],  "strict"),               # beat 9:  G#=固定（C26→E major）
    (4, "minor", [9],  "strict",  _v),          # beat 10: v (A=Am根音、G#解決先)
    (1, "major", [11], "strict",  _E),          # beat 11: V/v (B=E major第5音)
    # m8: v (Am: A-C-E) — バッハはVII(C major)を代理で使用
    (4, "minor", [0],  "strict",  _v),          # beat 12: v (C=第3音)
    (4, "minor", [0],  "strict",  _v),          # beat 13: v (C継続)
    (4, "minor", [0],  "flexible", _v),         # beat 14: v (C→D、Dは経過音)
    (4, "minor", [11], "flexible", _v),         # beat 15: v (B=倚音→A)
    # 次エントリとの重複拍
    (0, "minor", [9],  "strict"),               # beat 16: i (A=第5音)
])

SAMPLE = {
    "name": "art_of_fugue_Dm",
    "key": Key('D', 'minor'),
}


def write_midi(full_midi, out_path, tempo=60):
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


def _run_quality_gate(full_midi, key, engine):
    """品質関門: チェッカーを実行し、errors数とreportを返す"""
    gct = getattr(engine, 'global_chord_tones', None)
    gcl = getattr(engine, 'global_chord_labels', None)
    beat_key_map = getattr(engine, 'global_beat_key_map', None)
    checker = FugueQualityChecker(full_midi, key,
                                  beat_chord_tones=gct,
                                  beat_chord_labels=gcl,
                                  beat_key_map=beat_key_map)
    report = checker.run_all()
    return report


def main():
    chord_model, cp_model, key_model = load_models()

    print(f"\n{'='*60}")
    print(f"  Die Kunst der Fuge - 基本主題: {SAMPLE['name']}")
    print(f"{'='*60}")

    key = SAMPLE["key"]
    subject = Subject(ART_OF_FUGUE_NOTES, key, "Art of Fugue grundthema",
                      harmonic_template=ART_OF_FUGUE_HARMONY,
                      answer_harmonic_template=ART_OF_FUGUE_ANSWER_HARMONY)
    print(f"  主題: {len(subject.notes)}音, {subject.get_length_subbeats()}サブビート, {subject.get_length()}拍")
    structure = FugueStructure(num_voices=4, main_key=key, subject=subject,
                               entry_overlap=1)

    # --- 総当たり生成 → 全候補評価 → 最良採用 ---
    # 生成後の修正は一切行わない。多数のseedで生成し、
    # チェッカーで評価、errors=0の候補からwarnings最少を採用する。
    # バッハ Contrapunctus 1 の和声進行をMIDIから抽出した参照データとして使用
    bach_progression = get_bach_progression_as_chord_labels()
    print(f"  参照和声進行: バッハ Contrapunctus 1 ({len(bach_progression)}拍)")

    NUM_CANDIDATES = 200
    base_seed = 42

    candidates = []  # (errors, warnings, seed, midi, engine, report)

    for i in range(NUM_CANDIDATES):
        seed = base_seed + i
        markov_strategy = (MarkovKeyPathStrategy(key_model, seed=seed)
                           if key_model.num_transitions > 0 else None)
        engine = FugueRealizationEngine(
            structure,
            seed=seed,
            chord_model=chord_model,
            counterpoint_model=cp_model,
            elaborate=False,
            reference_progression=bach_progression,
        )
        full_midi = engine.realize_fugue(
            key_path_strategy=markov_strategy
        )

        report = _run_quality_gate(full_midi, key, engine)
        n_err = len(report.errors)
        n_warn = len(report.warnings)
        candidates.append((n_err, n_warn, seed, full_midi, engine, report))

        if (i + 1) % 50 == 0 or i == NUM_CANDIDATES - 1:
            ok_count = sum(1 for c in candidates if c[0] == 0)
            print(f"  ... {i+1}/{NUM_CANDIDATES} 生成完了"
                  f" (errors=0: {ok_count}候補)")

    # errors=0の候補からwarnings最少を選択
    clean = [c for c in candidates if c[0] == 0]
    if clean:
        # warnings最少 → seed最小 の順でソート
        clean.sort(key=lambda c: (c[1], c[2]))
        best = clean[0]
        print(f"\n  採用: seed={best[2]} (errors=0, warnings={best[1]})"
              f" [{len(clean)}/{NUM_CANDIDATES}候補がerrors=0]")
    else:
        # errors=0がなければ errors最少 → warnings最少 を採用
        candidates.sort(key=lambda c: (c[0], c[1]))
        best = candidates[0]
        print(f"\n  errors=0の候補なし。最良: seed={best[2]}"
              f" (errors={best[0]}, warnings={best[1]})")

    full_midi = best[3]
    engine = best[4]
    report = best[5]

    # 対主題情報
    cs = engine.countersubject_midi
    if cs:
        NOTE_NAMES_CS = ['C', 'C#', 'D', 'Eb', 'E', 'F',
                         'F#', 'G', 'Ab', 'A', 'Bb', 'B']
        cs_names = [NOTE_NAMES_CS[m % 12] + str(m // 12 - 1) for m in cs]
        print(f"  対主題: {cs_names}")

    # 統計
    total_notes = sum(len(notes) for notes in full_midi.values())
    max_tick = 0
    for vt, notes in full_midi.items():
        if notes:
            last_end = max(n[0] + n[2] for n in notes)
            max_tick = max(max_tick, last_end)
    ticks_per_beat = SUBBEATS_PER_BEAT * 120
    total_beats = max_tick // ticks_per_beat
    print(f"  総音数: {total_notes}")
    print(f"  総拍数: {total_beats} ({total_beats // 4}小節)")
    approx_seconds = total_beats * 60 / 60  # tempo=60
    print(f"  概算: {approx_seconds:.0f}秒 ({approx_seconds/60:.1f}分)")
    print(f"  声部数: {len(full_midi)}")

    # 品質関門の結果表示
    n_err = len(report.errors)
    n_warn = len(report.warnings)
    n_info = len(report.infos)
    print(f"  errors={n_err}, warnings={n_warn}, info={n_info}")
    # error/warning は個別表示
    for v in report.violations:
        if v.severity == "info":
            continue
        level = "ERROR" if v.severity == "error" else "WARN"
        loc = f"m{v.measure}.{v.beat_in_measure}"
        vs = "+".join(v.voices) if v.voices else ""
        midi_str = f" midi={v.midi_values}" if v.midi_values else ""
        vt_str = f" voice={v.voices[0]}" if v.voices and len(v.voices) == 1 else ""
        print(f"  [{level}] {loc} ({vs}): {v.description}{midi_str}{vt_str}")
    # info はカテゴリ別集計のみ
    if n_info > 0:
        info_cats: dict = {}
        for v in report.infos:
            info_cats[v.category] = info_cats.get(v.category, 0) + 1
        for cat, cnt in sorted(info_cats.items()):
            print(f"  [INFO] {cat}: {cnt}拍")

    # MIDI出力
    fname = f"sample_fugue_{SAMPLE['name']}.mid"
    out_path = os.path.join(BASE, fname)
    write_midi(full_midi, out_path)
    print(f"  -> {out_path}")

    repo_path = os.path.join(REPO_DIR, fname)
    shutil.copy2(out_path, repo_path)
    print(f"  -> {repo_path}")

    # コード進行
    global_chord_labels = getattr(engine, 'global_chord_labels', {})
    section_boundaries = getattr(engine, 'section_boundaries', [])
    if global_chord_labels and section_boundaries:
        print(f"\n{'='*60}")
        print("  コード進行 (四分音符 = 和声骨格)")
        print(f"{'='*60}")
        NOTE_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F',
                      'F#', 'G', 'Ab', 'A', 'Bb', 'B']
        DEGREE_NAMES = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII']

        for sec_info in section_boundaries:
            sec_name, sec_start, sec_end = sec_info[0], sec_info[1], sec_info[2]
            print(f"\n  --- {sec_name} ---")
            chords_in_section = []
            for beat in range(sec_start, sec_end):
                if beat in global_chord_labels:
                    cl = global_chord_labels[beat]
                    root_name = NOTE_NAMES[cl.root_pc % 12]
                    quality_str = ""
                    if cl.quality == "minor":
                        quality_str = "m"
                    elif cl.quality == "diminished":
                        quality_str = "dim"
                    elif cl.quality == "aug":
                        quality_str = "aug"
                    elif "7" in cl.quality:
                        quality_str = "7"
                    alpha = f"{root_name}{quality_str}"

                    if hasattr(cl, 'degree') and cl.degree is not None:
                        deg = cl.degree % 7
                        roman = DEGREE_NAMES[deg]
                        if cl.quality == "minor":
                            roman = roman.lower()
                        elif cl.quality == "diminished":
                            roman = roman.lower() + "°"
                        roman_str = f"{roman}"
                    else:
                        roman_str = "?"

                    chords_in_section.append(f"{alpha}({roman_str})")

            for i in range(0, len(chords_in_section), 4):
                bar = chords_in_section[i:i+4]
                bar_num = (sec_start + i) // 4 + 1
                print(f"    m{bar_num}: {' | '.join(bar)}")


if __name__ == "__main__":
    main()
