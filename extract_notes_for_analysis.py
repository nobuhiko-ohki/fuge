#!/usr/bin/env python3
"""
MIDI から小節・拍単位の音符リストを出力する（和声分析用）

usage: python extract_notes_for_analysis.py corpus/bach_midi/uncategorized/1080-c01.mid
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from midi_reader import MIDIReader

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

def pitch_name(pitch: int) -> str:
    return NOTE_NAMES[pitch % 12] + str(pitch // 12 - 1)

def pitch_class_name(pc: int) -> str:
    return NOTE_NAMES[pc]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "corpus/bach_midi/uncategorized/1080-c01.mid"
    midi = MIDIReader().read(path)
    tpb = midi.ticks_per_beat  # ticks per quarter note

    # Collect all notes
    all_notes = []
    for track in midi.tracks:
        for note in track.notes:
            all_notes.append(note)
    all_notes.sort(key=lambda n: n.start_tick)

    # Find total length
    if not all_notes:
        print("No notes found")
        return

    max_tick = max(n.end_tick for n in all_notes)
    total_beats = (max_tick + tpb - 1) // tpb
    beats_per_measure = 4  # 4/4 time

    print(f"# ticks_per_beat={tpb}, total_beats={total_beats}, total_measures={total_beats//beats_per_measure}")
    print(f"# {'Measure':>7} {'Beat':>5}  {'Attack notes':30}  {'Sustained notes'}")
    print("#" + "-"*90)

    for beat_idx in range(total_beats):
        measure = beat_idx // beats_per_measure + 1
        beat_in_measure = beat_idx % beats_per_measure + 1
        beat_start = beat_idx * tpb
        beat_end = beat_start + tpb
        attack_window = tpb // 4  # within first 1/4 beat = attack

        attacks = []
        sustained = []
        for note in all_notes:
            if note.end_tick <= beat_start:
                continue
            if note.start_tick >= beat_end:
                continue
            if abs(note.start_tick - beat_start) <= attack_window:
                attacks.append(note.pitch)
            else:
                sustained.append(note.pitch)

        attacks_str  = " ".join(pitch_name(p) for p in sorted(set(attacks)))
        sustain_str  = " ".join(pitch_name(p) for p in sorted(set(sustained)))
        # Also show pitch classes
        attack_pcs  = sorted(set(p % 12 for p in attacks))
        sustain_pcs = sorted(set(p % 12 for p in sustained))
        attack_pc_str  = "[" + " ".join(pitch_class_name(pc) for pc in attack_pcs) + "]"
        sustain_pc_str = "[" + " ".join(pitch_class_name(pc) for pc in sustain_pcs) + "]"

        print(f"m{measure:>3}.{beat_in_measure}  atk={attacks_str:<20} {attack_pc_str:<14}  sus={sustain_str:<15} {sustain_pc_str}")

if __name__ == "__main__":
    main()
