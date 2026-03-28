"""
Bach WTC フーガ主題エンコーダ

平均律クラヴィーア曲集 第1巻・第2巻のフーガ主題を
MIDI ノートデータとしてエンコードする。

主題データの形式:
  (MIDI pitch, duration_in_subbeats)
  subbeat = 16分音符 = 120 ticks (at 480 ticks/beat)

注意: 実際のコーパス解析では外部 MIDI ファイルを使用する。
これはテスト・開発用のリファレンスデータ。
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from midi_writer import MIDIWriter

# 1 subbeat = 120 ticks (ticks_per_beat=480, 4 subbeats/beat)
TICKS_PER_SUBBEAT = 120


# ============================================================
# WTC Book I フーガ主題
# ============================================================
# 形式: {"key": str, "voices": int, "subject": [(midi_pitch, subbeats), ...]}

WTC1_FUGUES = {
    # BWV 846: C major, 4声
    1: {
        "key": "C major", "voices": 4, "bwv": 846,
        "subject": [
            # C-D-E-C-D-E-F-E-D-E-C
            (60, 2), (62, 2), (64, 2), (60, 1), (62, 1),
            (64, 1), (65, 1), (64, 1), (62, 1), (64, 2), (60, 2),
        ],
    },
    # BWV 847: C minor, 3声
    2: {
        "key": "C minor", "voices": 3, "bwv": 847,
        "subject": [
            # C (8th rest) C-Eb-G-C5-Bb-Ab-G-F-Eb-D-C
            (60, 2), (60, 1), (63, 1), (67, 1), (72, 1),
            (70, 1), (68, 1), (67, 1), (65, 1), (63, 1), (62, 1), (60, 2),
        ],
    },
    # BWV 848: C# major, 3声
    3: {
        "key": "C# major", "voices": 3, "bwv": 848,
        "subject": [
            # C#-D#-E#-F#-G#-C#5(up)
            (61, 4), (63, 4), (65, 2), (66, 2), (68, 4), (73, 4),
        ],
    },
    # BWV 849: C# minor, 5声
    4: {
        "key": "C# minor", "voices": 5, "bwv": 849,
        "subject": [
            # C#-B#-C#-D#-E-D#-C#-B#-A#-B#-C#-D#-E-F#-G#
            (61, 4), (60, 2), (61, 2), (63, 4), (64, 2), (63, 2),
            (61, 2), (60, 2), (58, 2), (60, 2), (61, 2), (63, 2),
            (64, 4), (66, 4), (68, 4),
        ],
    },
    # BWV 851: D minor, 3声  (Fugue No. 6)
    6: {
        "key": "D minor", "voices": 3, "bwv": 851,
        "subject": [
            # D-A-D5-C#-D-E-F-G-A
            (62, 4), (69, 4), (74, 2), (73, 1), (74, 1),
            (76, 2), (77, 2), (79, 2), (81, 4),
        ],
    },
    # BWV 858: F# minor, 3声  (Fugue No. 14)
    14: {
        "key": "F# minor", "voices": 3, "bwv": 858,
        "subject": [
            # F#-G#-A-G#-F#-E-D#-C#-B-C#-D-C#-B-A-G#
            (66, 2), (68, 2), (69, 1), (68, 1), (66, 1), (64, 1),
            (63, 1), (61, 1), (59, 2), (61, 2), (62, 1), (61, 1),
            (59, 1), (57, 1), (56, 4),
        ],
    },
    # BWV 860: G minor, 4声  (Fugue No. 16)
    16: {
        "key": "G minor", "voices": 4, "bwv": 860,
        "subject": [
            # G-D-Bb-A-G-F#-G-A-Bb-C-D
            (67, 4), (62, 2), (70, 2), (69, 2), (67, 1), (66, 1),
            (67, 2), (69, 2), (70, 2), (72, 2), (74, 4),
        ],
    },
    # BWV 866: Bb major, 3声  (Fugue No. 21)
    21: {
        "key": "Bb major", "voices": 3, "bwv": 866,
        "subject": [
            # Bb-C-D-Eb-F-D-Eb-C-D-Bb
            (70, 2), (72, 2), (74, 1), (75, 1), (77, 1), (74, 1),
            (75, 1), (72, 1), (74, 2), (70, 4),
        ],
    },
    # BWV 869: B minor, 4声  (Fugue No. 24)
    24: {
        "key": "B minor", "voices": 4, "bwv": 869,
        "subject": [
            # B(long)-A#-B-C#-D-E-D-C#-B-A#-G#-A#-B
            (59, 8), (58, 2), (59, 2), (61, 4), (62, 4),
            (64, 4), (62, 2), (61, 2), (59, 2), (58, 2),
            (56, 4), (58, 2), (59, 6),
        ],
    },
}


def subject_to_midi_notes(subject, start_tick=0):
    """主題データを midi_writer 用の notes 形式に変換する。

    Returns:
        [(start_ticks, pitch, duration_ticks), ...]
    """
    notes = []
    t = start_tick
    for pitch, subbeats in subject:
        dur = subbeats * TICKS_PER_SUBBEAT
        notes.append((t, pitch, dur))
        t += dur
    return notes


def create_subject_midi(fugue_data, output_path):
    """フーガ主題を単声の MIDI ファイルとして書き出す。"""
    writer = MIDIWriter(tempo=72, ticks_per_beat=480)
    notes = subject_to_midi_notes(fugue_data["subject"])
    writer.add_track_from_notes(notes, channel=0)
    writer.write_file(output_path)
    return notes


def create_all_subject_midis(output_dir):
    """全フーガ主題の MIDI ファイルを生成する。"""
    os.makedirs(output_dir, exist_ok=True)
    created = []

    for num, data in sorted(WTC1_FUGUES.items()):
        filename = f"wtc1_fugue{num:02d}_subject.mid"
        path = os.path.join(output_dir, filename)
        notes = create_subject_midi(data, path)
        total_beats = sum(s[1] for s in data["subject"]) / 4
        created.append((num, data["key"], data["voices"],
                        len(data["subject"]), total_beats, filename))

    return created


if __name__ == "__main__":
    output_dir = os.path.join(os.path.dirname(__file__), "midi")
    results = create_all_subject_midis(output_dir)

    print("=== Bach WTC Book I — フーガ主題 MIDI 生成 ===\n")
    for num, key, voices, note_count, beats, filename in results:
        print(f"  Fugue {num:2d}: {key:12s} ({voices}v) "
              f"{note_count:2d} notes, {beats:.1f} beats → {filename}")
    print(f"\n合計 {len(results)} 件を {output_dir}/ に生成しました。")
