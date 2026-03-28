#!/usr/bin/env python3
"""バッハ Contrapunctus 1 の和声進行データ（MIDI自動抽出 + 調性優先推定）

extract_chords_from_midi.py --diatonic で抽出した312拍分の和声進行を
ChordLabel形式に変換し、フーガ生成エンジンに供給する。

使い方:
    from bach_chord_data import get_bach_progression_as_chord_labels
    progression = get_bach_progression_as_chord_labels()
    # progression: List[ChordLabel]  (312拍分)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from fugue_realization import ChordLabel
from typing import List, Optional, Tuple, Set

# ラベル→degree変換（D minor基準、0-based）
# i=0, ii°=1, III=2, iv=3, V=4, VI=5, VII=6
LABEL_TO_DEGREE = {
    "i":     0,
    "ii°":   1,
    "III":   2,
    "iv":    3,
    "V":     4,
    "v":     4,   # 自然属和音も degree=4
    "VI":    5,
    "VII":   6,
    "vii°":  6,
    "vii°7": 6,
    "V/v":   4,   # 二次属和音 → degree=4 (secondary)
    "V7":    4,
}

# --- バッハ Contrapunctus 1 の和声進行（MIDI抽出、調性優先推定） ---
# 形式: (name, root_pc, quality, tones_set, label)
# 312拍 = 78小節
BACH_DIATONIC_PROGRESSION = [
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m1.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m1.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m1.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m1.4
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m2.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m2.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m2.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m2.4
    ("A", 9, "major", {1, 4, 9}, "V"),          # m3.1
    ("A", 9, "major", {1, 4, 9}, "V"),          # m3.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m3.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m3.4
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m4.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m4.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m4.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m4.4
    # m5
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m5.1
    ("A", 9, "major", {1, 4, 9}, "V"),          # m5.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m5.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m5.4
    # m6
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m6.1
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m6.2
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m6.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m6.4
    # m7
    ("E", 4, "major", {4, 8, 11}, "V/v"),       # m7.1
    ("E", 4, "major", {4, 8, 11}, "V/v"),       # m7.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m7.3
    ("E", 4, "major", {4, 8, 11}, "V/v"),       # m7.4
    # m8
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m8.1
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m8.2
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m8.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m8.4
    # m9
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m9.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m9.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m9.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m9.4
    # m10
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m10.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m10.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m10.3
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m10.4
    # m11
    ("C#", 1, "dim7", {1, 4, 7, 10}, "vii°7"), # m11.1
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m11.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m11.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m11.4
    # m12
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m12.1
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m12.2
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m12.3
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m12.4
    # m13
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m13.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m13.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m13.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m13.4
    # m14
    ("E", 4, "major", {4, 8, 11}, "V/v"),       # m14.1
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m14.2
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m14.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m14.4
    # m15
    ("E", 4, "major", {4, 8, 11}, "V/v"),       # m15.1
    ("E", 4, "major", {4, 8, 11}, "V/v"),       # m15.2
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m15.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m15.4
    # m16
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m16.1
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m16.2
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m16.3
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m16.4
    # m17
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m17.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m17.2
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m17.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m17.4
    # m18
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m18.1
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m18.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m18.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m18.4
    # m19
    ("E", 4, "major", {4, 8, 11}, "V/v"),       # m19.1
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m19.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m19.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m19.4
    # m20
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m20.1
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m20.2
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m20.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m20.4
    # m21
    ("A", 9, "major", {1, 4, 9}, "V"),          # m21.1
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m21.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m21.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m21.4
    # m22
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m22.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m22.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m22.3
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m22.4
    # m23
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m23.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m23.2
    ("A", 9, "major", {1, 4, 9}, "V"),          # m23.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m23.4
    # m24
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m24.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m24.2
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m24.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m24.4
    # m25
    ("A", 9, "major", {1, 4, 9}, "V"),          # m25.1
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m25.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m25.3
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m25.4
    # m26
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m26.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m26.2
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m26.3
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m26.4
    # m27
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m27.1
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m27.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m27.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m27.4
    # m28
    ("A", 9, "major", {1, 4, 9}, "V"),          # m28.1
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m28.2
    ("E", 4, "major", {4, 8, 11}, "V/v"),       # m28.3
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m28.4
    # m29
    ("A", 9, "major", {1, 4, 9}, "V"),          # m29.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m29.2
    ("E", 4, "major", {4, 8, 11}, "V/v"),       # m29.3
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m29.4
    # m30
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m30.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m30.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m30.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m30.4
    # m31
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m31.1
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m31.2
    ("F", 5, "major", {0, 5, 9}, "III"),        # m31.3
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m31.4
    # m32
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m32.1
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m32.2
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m32.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m32.4
    # m33
    ("A", 9, "major", {1, 4, 9}, "V"),          # m33.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m33.2
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m33.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m33.4
    # m34
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m34.1
    ("A", 9, "major", {1, 4, 9}, "V"),          # m34.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m34.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m34.4
    # m35
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m35.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m35.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m35.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m35.4
    # m36
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m36.1
    ("F", 5, "major", {0, 5, 9}, "III"),        # m36.2
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m36.3
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m36.4
    # m37
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m37.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m37.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m37.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m37.4
    # m38
    ("A", 9, "major", {1, 4, 9}, "V"),          # m38.1
    ("A", 9, "major", {1, 4, 9}, "V"),          # m38.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m38.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m38.4
    # m39
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m39.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m39.2
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m39.3
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m39.4
    # m40
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m40.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m40.2
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m40.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m40.4
    # m41
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m41.1
    ("F", 5, "major", {0, 5, 9}, "III"),        # m41.2
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m41.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m41.4
    # m42
    ("A", 9, "major", {1, 4, 9}, "V"),          # m42.1
    ("A", 9, "major", {1, 4, 9}, "V"),          # m42.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m42.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m42.4
    # m43
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m43.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m43.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m43.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m43.4
    # m44
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m44.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m44.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m44.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m44.4
    # m45
    ("A", 9, "major", {1, 4, 9}, "V"),          # m45.1
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m45.2
    ("F", 5, "major", {0, 5, 9}, "III"),        # m45.3
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m45.4
    # m46
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m46.1
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m46.2
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m46.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m46.4
    # m47
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m47.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m47.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m47.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m47.4
    # m48
    ("A", 9, "major", {1, 4, 9}, "V"),          # m48.1
    ("A", 9, "major", {1, 4, 9}, "V"),          # m48.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m48.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m48.4
    # m49
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m49.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m49.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m49.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m49.4
    # m50
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m50.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m50.2
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m50.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m50.4
    # m51
    ("A", 9, "major", {1, 4, 9}, "V"),          # m51.1
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m51.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m51.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m51.4
    # m52
    ("A", 9, "major", {1, 4, 9}, "V"),          # m52.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m52.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m52.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m52.4
    # m53
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m53.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m53.2
    ("A", 9, "major", {1, 4, 9}, "V"),          # m53.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m53.4
    # m54
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m54.1
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m54.2
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m54.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m54.4
    # m55
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m55.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m55.2
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m55.3
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m55.4
    # m56
    ("F", 5, "major", {0, 5, 9}, "III"),        # m56.1
    ("F", 5, "major", {0, 5, 9}, "III"),        # m56.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m56.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m56.4
    # m57
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m57.1
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m57.2
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m57.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m57.4
    # m58
    ("E", 4, "diminished", {1, 4, 7}, "ii°"),   # m58.1 — E dim ≈ ii°
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m58.2
    ("A", 9, "major", {1, 4, 9}, "V"),          # m58.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m58.4
    # m59
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m59.1
    ("A", 9, "major", {1, 4, 9}, "V"),          # m59.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m59.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m59.4
    # m60
    ("A", 9, "major", {1, 4, 9}, "V"),          # m60.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m60.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m60.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m60.4
    # m61
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m61.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m61.2
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m61.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m61.4
    # m62
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m62.1
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m62.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m62.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m62.4
    # m63
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m63.1
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m63.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m63.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m63.4
    # m64
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m64.1
    ("A", 9, "major", {1, 4, 9}, "V"),          # m64.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m64.3
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m64.4
    # m65
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m65.1
    ("F", 5, "major", {0, 5, 9}, "III"),        # m65.2
    ("A", 9, "minor", {0, 4, 9}, "v"),          # m65.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m65.4
    # m66
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m66.1
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m66.2
    ("F", 5, "major", {0, 5, 9}, "III"),        # m66.3
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m66.4
    # m67
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m67.1
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m67.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m67.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m67.4
    # m68
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m68.1
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m68.2
    ("A", 9, "major", {1, 4, 9}, "V"),          # m68.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m68.4
    # m69
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m69.1
    ("A", 9, "major", {1, 4, 9}, "V"),          # m69.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m69.3
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m69.4
    # m70
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m70.1
    ("A", 9, "major", {1, 4, 9}, "V"),          # m70.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m70.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m70.4
    # m71
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m71.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m71.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m71.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m71.4
    # m72
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m72.1
    ("G", 7, "minor", {2, 7, 10}, "iv"),        # m72.2
    ("A", 9, "major", {1, 4, 9}, "V"),          # m72.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m72.4
    # m73
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m73.1
    ("C", 0, "major", {0, 4, 7}, "VII"),        # m73.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m73.3
    ("Bb", 10, "major", {2, 5, 10}, "VI"),      # m73.4
    # m74
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m74.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m74.2
    ("C#", 1, "dim7", {1, 4, 7, 10}, "vii°7"), # m74.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m74.4
    # m75
    ("A", 9, "major", {1, 4, 9}, "V"),          # m75.1
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m75.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m75.3
    ("A", 9, "dominant7", {1, 4, 7, 9}, "V7"),  # m75.4
    # m76
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m76.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m76.2
    ("A", 9, "major", {1, 4, 9}, "V"),          # m76.3
    ("A", 9, "major", {1, 4, 9}, "V"),          # m76.4
    # m77
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m77.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m77.2
    ("A", 9, "major", {1, 4, 9}, "V"),          # m77.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m77.4
    # m78
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m78.1
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m78.2
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m78.3
    ("D", 2, "minor", {2, 5, 9}, "i"),          # m78.4
]

assert len(BACH_DIATONIC_PROGRESSION) == 312, \
    f"Expected 312 beats, got {len(BACH_DIATONIC_PROGRESSION)}"


def _tuple_to_chord_label(t: Tuple) -> ChordLabel:
    """5-tuple → ChordLabel変換"""
    name, root_pc, quality, tones, label = t
    degree = LABEL_TO_DEGREE.get(label, 0)
    is_secondary = label in ("V/v",)
    is_dom7 = quality in ("dominant7",)
    seventh_pc = None
    if is_dom7:
        seventh_pc = (root_pc + 10) % 12  # 短7度
    return ChordLabel(
        degree=degree,
        root_pc=root_pc,
        quality=quality,
        tones=set(tones),
        is_secondary=is_secondary,
        has_seventh=is_dom7,
        seventh_pc=seventh_pc,
    )


def get_bach_progression_as_chord_labels() -> List[ChordLabel]:
    """バッハの和声進行を ChordLabel リストとして返す（312拍分）"""
    return [_tuple_to_chord_label(t) for t in BACH_DIATONIC_PROGRESSION]


def get_bach_exposition_chords(num_beats: int = 65) -> List[ChordLabel]:
    """提示部（m1-m17）のChordLabelリストを返す

    Args:
        num_beats: 提示部の拍数（デフォルト=65, m1-m17の最初の拍まで）
    """
    full = get_bach_progression_as_chord_labels()
    return full[:num_beats]


def apply_answer_ending_v_fix(progression: List[ChordLabel]) -> List[ChordLabel]:
    """Fix answer ending beats to end on V (dominant) for proper cadence preparation.

    In a fugue, both answer entries (soprano and tenor) must end on V (A major in D minor)
    to properly transition to the next subject entry on i (D minor tonic).

    Fixes:
    - Beat 30 (m8.3): soprano answer ending, change from iv (G minor) to V (A major)
    - Beat 31 (m8.4): soprano answer ending, change from iv (G minor) to V (A major)
    - Beat 62 (m16.3): tenor answer ending, change from iv (G minor) to V (A major)

    Args:
        progression: List of ChordLabel objects (312 beats)

    Returns:
        Modified copy of the progression with V-fix applied
    """
    # Create a copy to avoid modifying the original
    fixed = progression[:]

    # V (A major) in D minor: root_pc=9, quality="major", tones={1,4,9}
    v_chord_tuple = ("A", 9, "major", {1, 4, 9}, "V")
    v_chord_label = _tuple_to_chord_label(v_chord_tuple)

    # Apply fixes at the specified beats
    beats_to_fix = [30, 31, 62]
    for beat in beats_to_fix:
        if 0 <= beat < len(fixed):
            fixed[beat] = v_chord_label

    return fixed


def get_bach_progression_v_fixed() -> List[ChordLabel]:
    """Return the full Bach progression with V-fix applied to answer endings.

    This is a convenience function that applies apply_answer_ending_v_fix() to the
    standard Bach progression, ensuring both answer entries properly transition
    to the next subject/answer on the tonic.

    Returns:
        List of 312 ChordLabel objects with V-fix applied
    """
    progression = get_bach_progression_as_chord_labels()
    return apply_answer_ending_v_fix(progression)


if __name__ == "__main__":
    labels = get_bach_progression_as_chord_labels()
    print(f"Total beats: {len(labels)}")
    print(f"\n提示部 (m1-m17):")
    NOTE_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']
    for i, cl in enumerate(labels[:68]):
        m = i // 4 + 1
        b = i % 4 + 1
        root_name = NOTE_NAMES[cl.root_pc]
        q_suffix = {"major": "", "minor": "m", "diminished": "dim",
                     "dominant7": "7", "dim7": "dim7"}.get(cl.quality, cl.quality)
        print(f"  m{m:>2}.{b}: {root_name}{q_suffix} (degree={cl.degree}, tones={cl.tones})")
