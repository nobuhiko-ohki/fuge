"""generate_fugue_v2.py — 新アーキテクチャによるフーガ生成

Phase 1: 提示部 + エピソード + 中間部 + コーダ、四分音符グリッド、和音構成音のみ

全体構成 (118 拍 = 29.5 小節):
  提示部  (65 拍): 4声部が順次主題/応答を提示 (Alto→Sop→Bass→Tenor, overlap=1)
  エピソード1 (8 拍): Dm-Am-Gm-A 進行、全声部自由
  中間部  (33 拍): Bass主題(-12) + Tenor応答(-12) + Sop/Alto自由対位法
  エピソード2 (8 拍): Gm-E°-A 進行、全声部自由
  コーダ   (4 拍): A-Dm 終止、全声部自由
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from typing import List, Optional, Tuple

from harmony_rules_complete import Pitch, NoteEvent
from fugue_structure import Key, Subject, FugueStructure, FugueVoiceType
from fugue_realization import (
    SUBBEATS_PER_BEAT, SubjectHarmonicTemplate, BeatHarmony, ChordLabel,
)
from midi_writer import MIDIWriter
from fugue_composer import (
    HarmonicPlan, FugueComposer, SectionSpec,
    build_midi, apply_note_events_to_midi, validate,
    TICKS_PER_BEAT,
)

# ------------------------------------------------------------------
# 主題定義（generate_art_of_fugue.py と同一）
# ------------------------------------------------------------------
ART_OF_FUGUE_NOTES = [
    NoteEvent(Pitch(62), 8),   # D4  二分音符
    NoteEvent(Pitch(69), 8),   # A4  二分音符
    NoteEvent(Pitch(65), 8),   # F4  二分音符
    NoteEvent(Pitch(62), 8),   # D4  二分音符
    NoteEvent(Pitch(61), 8),   # C#4 二分音符
    NoteEvent(Pitch(62), 4),   # D4  四分音符
    NoteEvent(Pitch(64), 4),   # E4  四分音符
    NoteEvent(Pitch(65), 10),  # F4  付点二分音符
    NoteEvent(Pitch(67), 2),   # G4  八分音符
    NoteEvent(Pitch(65), 2),   # F4  八分音符
    NoteEvent(Pitch(64), 2),   # E4  八分音符
    NoteEvent(Pitch(62), 4),   # D4  四分音符
]

# 応答: A-D-C-A-G#-A-B-C-D-C-B-A (属調A上で、D minor内表現)
ART_OF_FUGUE_ANSWER_NOTES = [
    NoteEvent(Pitch(69), 8),   # A4  二分音符  (主題D→5度上A)
    NoteEvent(Pitch(62), 8),   # D4  二分音符  (主題A→5度上D... 調的応答でD)
    NoteEvent(Pitch(60), 8),   # C4  二分音符  (主題F→C)
    NoteEvent(Pitch(69), 8),   # A4  二分音符  (主題D→A)
    NoteEvent(Pitch(68), 8),   # G#4 二分音符  (主題C#→G#)
    NoteEvent(Pitch(69), 4),   # A4  四分音符  (主題D→A)
    NoteEvent(Pitch(71), 4),   # B4  四分音符  (主題E→B)
    NoteEvent(Pitch(72), 10),  # C5  付点二分音符 (主題F→C)
    NoteEvent(Pitch(74), 2),   # D5  八分音符  (主題G→D)
    NoteEvent(Pitch(72), 2),   # C5  八分音符
    NoteEvent(Pitch(71), 2),   # B4  八分音符
    NoteEvent(Pitch(69), 4),   # A4  四分音符  (解決)
]

# 和声テンプレート（主題用）
_v = ChordLabel(degree=4, root_pc=9, quality="minor", tones={9, 0, 4})   # Am
_E = ChordLabel(degree=1, root_pc=4, quality="major", tones={4, 8, 11})  # E major

ART_OF_FUGUE_HARMONY = SubjectHarmonicTemplate.from_manual([
    (0, "minor", [2],  "strict"),    # beat 0:  i (D)
    (0, "minor", [2],  "strict"),    # beat 1:  i
    (0, "minor", [9],  "strict"),    # beat 2:  i (A)
    (0, "minor", [9],  "strict"),    # beat 3:  i
    (0, "minor", [5],  "flexible"),  # beat 4:  i (F)
    (0, "minor", [5],  "flexible"),  # beat 5:  i
    (0, "minor", [2],  "flexible"),  # beat 6:  i (D)
    (0, "minor", [2],  "flexible"),  # beat 7:  i
    (4, "major", [1],  "strict"),    # beat 8:  V (C#)
    (4, "major", [1],  "strict"),    # beat 9:  V
    (0, "minor", [2],  "strict"),    # beat 10: i (D)
    (4, "major", [4],  "strict"),    # beat 11: V (E)
    (0, "minor", [5],  "flexible"),  # beat 12: i (F)
    (0, "minor", [5],  "flexible"),  # beat 13: i
    (0, "minor", [5],  "flexible"),  # beat 14: i (F→G)
    (0, "minor", [5],  "flexible"),  # beat 15: i (F — subject拍頭はFのためDm)
    (0, "minor", [2],  "strict"),    # beat 16: i (D)
])

ART_OF_FUGUE_ANSWER_HARMONY = SubjectHarmonicTemplate.from_manual([
    (0, "minor", [9],  "strict"),              # beat 0:  i (A)
    (0, "minor", [9],  "strict"),              # beat 1:  i
    (0, "minor", [2],  "strict"),              # beat 2:  i (D)
    (0, "minor", [2],  "strict"),              # beat 3:  i
    (4, "minor", [0],  "strict",  _v),         # beat 4:  v (C)
    (4, "minor", [0],  "strict",  _v),         # beat 5:  v
    (4, "minor", [9],  "strict",  _v),         # beat 6:  v (A)
    (4, "minor", [9],  "strict",  _v),         # beat 7:  v
    (1, "major", [8],  "strict"),              # beat 8:  V/v (G#)
    (1, "major", [8],  "strict"),              # beat 9:  V/v
    (4, "minor", [9],  "strict",  _v),         # beat 10: v (A)
    (1, "major", [11], "strict",  _E),         # beat 11: V/v (B)
    (4, "minor", [0],  "strict",  _v),         # beat 12: v (C)
    (4, "minor", [0],  "strict",  _v),         # beat 13: v
    (4, "minor", [0],  "flexible", _v),        # beat 14: v
    (4, "minor", [11], "flexible", _v),        # beat 15: v (B)
    (0, "minor", [9],  "strict"),              # beat 16: i (A)
])


# ------------------------------------------------------------------
# Layer 1 構築ヘルパー
# ------------------------------------------------------------------

def _beat_harmony_to_chord_label(bh: BeatHarmony, key: Key) -> ChordLabel:
    """BeatHarmony → ChordLabel (keyで解決)"""
    if bh.custom_chord is not None:
        return bh.custom_chord
    scale = key.scale  # harmonic minor for minor
    root_pc = scale[bh.degree % 7]
    q = bh.quality
    if q == "major":
        tones = {root_pc, (root_pc + 4) % 12, (root_pc + 7) % 12}
    elif q == "minor":
        tones = {root_pc, (root_pc + 3) % 12, (root_pc + 7) % 12}
    else:  # diminished
        tones = {root_pc, (root_pc + 3) % 12, (root_pc + 6) % 12}
    return ChordLabel(
        degree=bh.degree, root_pc=root_pc, quality=q, tones=tones,
    )


def build_exposition_harmonic_plan(
    key: Key,
    subject_template: SubjectHarmonicTemplate,
    answer_template: SubjectHarmonicTemplate,
    subject_len: int,
    num_entries: int,
    entry_overlap: int = 1,
) -> HarmonicPlan:
    """提示部の HarmonicPlan を主題和声テンプレートから構築。

    エントリは交互に主題/応答を使用。
    overlapping beat では後から入るエントリのテンプレートを優先。
    """
    entry_starts = []
    start = 0
    for i in range(num_entries):
        entry_starts.append(start)
        start += subject_len - entry_overlap
    total_beats = entry_starts[-1] + subject_len

    chords: List[ChordLabel] = [None] * total_beats  # type: ignore
    keys: List[Key] = [key] * total_beats

    templates = []
    for i in range(num_entries):
        templates.append(subject_template if i % 2 == 0 else answer_template)

    # 後のエントリが優先 → 逆順で書き込む
    for i in range(num_entries - 1, -1, -1):
        tmpl = templates[i]
        s = entry_starts[i]
        for local_beat, bh in enumerate(tmpl.beats):
            g = s + local_beat
            if g < total_beats and chords[g] is None:
                chords[g] = _beat_harmony_to_chord_label(bh, key)

    # 残り（あれば）を主題テンプレートの最後の和音で埋める
    last_chord = _beat_harmony_to_chord_label(subject_template.beats[-1], key)
    for b in range(total_beats):
        if chords[b] is None:
            chords[b] = last_chord

    return HarmonicPlan.from_lists(chords, keys)


# ------------------------------------------------------------------
# ヘルパー関数
# ------------------------------------------------------------------

def _expand_to_beats(notes: List[NoteEvent], transpose: int = 0) -> List[int]:
    """NoteEvent リストを拍単位 MIDI ピッチリストに展開。

    各拍頭 (subbeat 0, 4, 8, ...) で鳴っているピッチを返す。
    transpose: 半音単位の移調量（例: -12 で 1 オクターブ下）。
    """
    SUBBEATS = 4
    total_beats = sum(n.duration for n in notes) // SUBBEATS
    result: List[int] = []
    for beat in range(total_beats):
        beat_sb = beat * SUBBEATS
        acc = 0
        pitch = notes[-1].pitch.midi + transpose
        for n in notes:
            if acc <= beat_sb < acc + n.duration:
                pitch = n.pitch.midi + transpose
                break
            acc += n.duration
        result.append(pitch)
    return result


def _make_chord_label(key: Key, degree: int, quality: str) -> ChordLabel:
    """調と音階度数から ChordLabel を生成。"""
    scale = key.scale
    root_pc = scale[degree % 7]
    if quality == "major":
        tones = {root_pc, (root_pc + 4) % 12, (root_pc + 7) % 12}
    elif quality == "minor":
        tones = {root_pc, (root_pc + 3) % 12, (root_pc + 7) % 12}
    else:  # diminished
        tones = {root_pc, (root_pc + 3) % 12, (root_pc + 6) % 12}
    return ChordLabel(degree=degree, root_pc=root_pc, quality=quality, tones=tones)


def build_full_harmonic_plan(
    key: Key,
    subject_template: SubjectHarmonicTemplate,
    answer_template: SubjectHarmonicTemplate,
    subject_len: int,
) -> HarmonicPlan:
    """全体の和声計画 (118 拍) を構築。

    構成:
      提示部 65 拍  = 4エントリ × (17-1) の重複配置
      エピソード1  8 拍  Dm-Am-Gm-A
      中間部  33 拍  = 2エントリ × (17-1) の重複配置
      エピソード2  8 拍  Gm-E°-A
      コーダ   4 拍  A-Dm
    """
    # 提示部
    expo_plan = build_exposition_harmonic_plan(
        key, subject_template, answer_template, subject_len, 4, 1,
    )

    # エピソード1: Dm-Am-Gm-A (2拍ずつ)
    ep1_pattern: List[Tuple[int, str]] = [
        (0, "minor"), (0, "minor"),
        (4, "minor"), (4, "minor"),
        (3, "minor"), (3, "minor"),
        (4, "major"), (4, "major"),
    ]
    ep1_chords = [_make_chord_label(key, d, q) for d, q in ep1_pattern]

    # 中間部 (2声部、overlap=1)
    mid_plan = build_exposition_harmonic_plan(
        key, subject_template, answer_template, subject_len, 2, 1,
    )

    # エピソード2: Gm-E°-A-A (2拍ずつ)
    ep2_pattern: List[Tuple[int, str]] = [
        (3, "minor"),      (3, "minor"),
        (1, "diminished"), (1, "diminished"),
        (4, "major"),      (4, "major"),
        (4, "major"),      (4, "major"),
    ]
    ep2_chords = [_make_chord_label(key, d, q) for d, q in ep2_pattern]

    # コーダ: A-Dm (2拍ずつ)
    coda_pattern: List[Tuple[int, str]] = [
        (4, "major"), (4, "major"),
        (0, "minor"), (0, "minor"),
    ]
    coda_chords = [_make_chord_label(key, d, q) for d, q in coda_pattern]

    all_chords = (
        list(expo_plan.chord_plan)
        + ep1_chords
        + list(mid_plan.chord_plan)
        + ep2_chords
        + coda_chords
    )
    all_keys = [key] * len(all_chords)
    return HarmonicPlan.from_lists(all_chords, all_keys)


# ------------------------------------------------------------------
# MIDI 書き出し
# ------------------------------------------------------------------

def write_midi(midi_data, path, tempo=60):
    writer = MIDIWriter(tempo=tempo, ticks_per_beat=480)
    ch_map = {
        FugueVoiceType.SOPRANO: 0,
        FugueVoiceType.ALTO:    1,
        FugueVoiceType.TENOR:   2,
        FugueVoiceType.BASS:    3,
    }
    for vt in sorted(midi_data, key=lambda v: v.value):
        ch = ch_map.get(vt, 0)
        writer.add_track_from_notes(midi_data[vt], channel=ch)
    writer.write_file(path)


# ------------------------------------------------------------------
# メイン
# ------------------------------------------------------------------

def main():
    key = Key('D', 'minor')
    subject = Subject(ART_OF_FUGUE_NOTES, key, "Art of Fugue - Grundthema",
                      harmonic_template=ART_OF_FUGUE_HARMONY,
                      answer_harmonic_template=ART_OF_FUGUE_ANSWER_HARMONY)
    structure = FugueStructure(
        num_voices=4, main_key=key, subject=subject, entry_overlap=1,
    )

    subject_len = subject.get_length()
    print(f"主題長: {subject_len} 拍")

    # -----------------------------------------------
    # Layer 1: 全体の和声計画（不変）
    # -----------------------------------------------
    full_plan = build_full_harmonic_plan(
        key=key,
        subject_template=ART_OF_FUGUE_HARMONY,
        answer_template=ART_OF_FUGUE_ANSWER_HARMONY,
        subject_len=subject_len,
    )
    # 区間境界  ※ n エントリ(overlap=1): (n-1)*(len-1) + len
    EXPO_BEATS = 3 * (subject_len - 1) + subject_len  # = 65
    EP1_START  = EXPO_BEATS            # 65
    EP1_LEN    = 8
    MID_START  = EP1_START + EP1_LEN   # 73
    MID_LEN    = 1 * (subject_len - 1) + subject_len  # = 33
    EP2_START  = MID_START + MID_LEN   # 106
    EP2_LEN    = 8
    CODA_START = EP2_START + EP2_LEN   # 114
    CODA_LEN   = 4
    TOTAL_BEATS = CODA_START + CODA_LEN  # 118

    print(f"全体和声計画: {len(full_plan)} 拍  (期待値={TOTAL_BEATS})")
    assert len(full_plan) == TOTAL_BEATS, \
        f"和声計画長不一致: {len(full_plan)} != {TOTAL_BEATS}"

    # -----------------------------------------------
    # 中間部の固定声部ピッチ（-12 移調）
    # -----------------------------------------------
    # Bass: 主題を 1 オクターブ下で提示 (beats 0-16 in section → global 73-89)
    # Tenor: 応答を 1 オクターブ下で提示 (beats 16-32 in section → global 89-105)
    bass_subject_beats  = _expand_to_beats(ART_OF_FUGUE_NOTES,        transpose=-12)
    tenor_answer_beats  = _expand_to_beats(ART_OF_FUGUE_ANSWER_NOTES, transpose=-12)

    # 中間部 33 拍分の固定ピッチリスト（None = 自由生成）
    mid_bass_fixed:  List[Optional[int]] = (
        bass_subject_beats                        # beats 0-16
        + [None] * (MID_LEN - len(bass_subject_beats))  # beats 17-32
    )
    mid_tenor_fixed: List[Optional[int]] = (
        [None] * (subject_len - 1)                # beats 0-15
        + tenor_answer_beats                      # beats 16-32
    )

    # -----------------------------------------------
    # 提示部後の区間仕様
    # -----------------------------------------------
    post_expo_sections = [
        # エピソード1: 全声部自由
        SectionSpec(start=EP1_START,  length=EP1_LEN),
        # 中間部: Bass/Tenor 固定、Sop/Alto 自由
        SectionSpec(
            start=MID_START, length=MID_LEN,
            fixed_entries=[
                (FugueVoiceType.BASS,  mid_bass_fixed),
                (FugueVoiceType.TENOR, mid_tenor_fixed),
            ],
        ),
        # エピソード2: 全声部自由
        SectionSpec(start=EP2_START,  length=EP2_LEN),
        # コーダ: 全声部自由
        SectionSpec(start=CODA_START, length=CODA_LEN),
    ]

    entries = structure.create_exposition(answer_type="auto", overlap=structure.entry_overlap)
    print(f"提示部エントリ数: {len(entries)}")
    for e in entries:
        print(f"  {e.voice_type.value}: start={e.start_position}, answer={e.is_answer}")
    print(f"中間部 Bass 主題 (先頭5拍): {bass_subject_beats[:5]}")
    print(f"中間部 Tenor 応答 (先頭5拍): {tenor_answer_beats[:5]}")

    best = None
    best_errors = 9999

    NUM_SEEDS = 20
    print(f"\n{NUM_SEEDS}シードで生成:")
    for seed in range(NUM_SEEDS):
        # Layer 2: 全体声部生成
        composer = FugueComposer(structure, full_plan, seed=seed)
        voice_plan = composer.compose_full(post_expo_sections)

        if voice_plan is None:
            print(f"  seed={seed}: 生成失敗")
            continue

        # Layer 4: 検証
        report = validate(full_plan, voice_plan)
        n_err  = len(report.errors)
        n_warn = len(report.warnings)
        print(f"  seed={seed}: errors={n_err}, warnings={n_warn}")

        if n_err < best_errors:
            best_errors = n_err
            best = (seed, voice_plan, report)

        if n_err == 0:
            break

    if best is None:
        print("\n全シードで失敗。")
        return

    seed, voice_plan, report = best
    print(f"\n最良: seed={seed} (errors={best_errors})")

    if report.errors:
        print("エラー一覧:")
        for e in report.errors:
            print(f"  [ERROR] m{e.measure}.{e.beat_in_measure}: {e.description}")
    if report.warnings:
        print("警告一覧:")
        for w in report.warnings:
            print(f"  [WARN]  m{w.measure}.{w.beat_in_measure}: {w.description}")

    # Layer 3: MIDI 出力（ビートグリッドを NoteEvents で上書きし sub-beat 復元）
    midi_data = build_midi(voice_plan)

    # --- 提示部: 主題/応答の NoteEvents を正確な duration で上書き ---
    # compose_exposition() と同じロジックで移調量を計算
    from fugue_realization import VOICE_RANGES as VR
    for entry in entries:
        vt = entry.voice_type
        lo, hi = VR.get(vt, (36, 84))
        first_p = entry.subject.notes[0].pitch.midi
        tr = 0
        while first_p + tr < lo: tr += 12
        while first_p + tr > hi: tr -= 12
        start_tick = entry.start_position * TICKS_PER_BEAT
        apply_note_events_to_midi(
            midi_data, vt, start_tick, entry.subject.notes, transpose=tr,
        )

    # --- 中間部: 移調主題/応答の NoteEvents を上書き ---
    apply_note_events_to_midi(
        midi_data, FugueVoiceType.BASS, MID_START * TICKS_PER_BEAT,
        ART_OF_FUGUE_NOTES, transpose=-12,
    )
    apply_note_events_to_midi(
        midi_data, FugueVoiceType.TENOR,
        (MID_START + subject_len - 1) * TICKS_PER_BEAT,
        ART_OF_FUGUE_ANSWER_NOTES, transpose=-12,
    )

    out_path = os.path.join(os.path.dirname(__file__), "output_full.mid")
    write_midi(midi_data, out_path, tempo=72)
    print(f"\nMIDI出力: {out_path}")
    print(f"全体長: {voice_plan.num_beats} 拍 = {voice_plan.num_beats / 4:.1f} 小節")


if __name__ == "__main__":
    main()
