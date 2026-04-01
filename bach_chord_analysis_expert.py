#!/usr/bin/env python3
"""
BWV 1080 Contrapunctus 1 — 和声進行（専門的分析）

MIDIノートデータ（extract_notes_for_analysis.py 出力）を参照し、
Piston "Harmony" の原則に基づいて拍単位で和声を分析。

調性: D minor（d-Moll）
拍子: 4/4、78小節 = 312拍

【各ローマ数字の意味（D minor 基準）】
  i    = Dm  (D, F, A)
  ii°  = E°  (E, G, Bb)
  III  = F   (F, A, C)
  iv   = Gm  (G, Bb, D)
  V    = A   (A, C#, E)   ← 和声短音階の主属和音
  v    = Am  (A, C, E)    ← 自然短音階の属和音
  VI   = Bb  (Bb, D, F)
  VII  = C   (C, E, G)
  vii° = C#° (C#, E, G)

二次ドミナント等:
  V/v    = E   (E, G#, B)   ← Am への属和音
  V7/v   = E7  (E, G#, B, D)
  vii°7/v= G#°7(G#, B, D, F) ← Am への導音7和音
  V/iv   = D   (D, F#, A)   ← Gm への属和音
  V7/iv  = D7  (D, F#, A, C)
  V7/III = G7  (G, B, D, F) ← F への属7和音
  iiø7   = Eø7 (E, G, Bb, D) ← 導音半減7和音（前属）
  vii°7  = C#°7(C#, E, G, Bb)← 主音への導音7和音
  V7     = A7  (A, C#, E, G)
  i7     = Dm7 (D, F, A, C)
  VII7   = C7  (C, E, G, Bb)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from fugue_realization import ChordLabel
from typing import List

# ──────────────────────────────────────────────
# 和音定義（ショートカット）
# ──────────────────────────────────────────────
def _c(name, root, quality, tones, label):
    return (name, root, quality, tones, label)

# 主要和音
Dm   = _c("D",  2, "minor",      {2, 5, 9},          "i")
Dm7  = _c("D",  2, "minor7",     {0, 2, 5, 9},        "i7")
Amaj = _c("A",  9, "major",      {1, 4, 9},           "V")
A7   = _c("A",  9, "dom7",       {1, 4, 7, 9},        "V7")
Am   = _c("A",  9, "minor",      {0, 4, 9},           "v")
Gm   = _c("G",  7, "minor",      {2, 7, 10},          "iv")
F    = _c("F",  5, "major",      {0, 5, 9},           "III")
Bb   = _c("Bb",10, "major",      {2, 5, 10},          "VI")
C    = _c("C",  0, "major",      {0, 4, 7},           "VII")
C7   = _c("C",  0, "dom7",       {0, 4, 7, 10},       "VII7")
Edim = _c("E",  4, "diminished", {4, 7, 10},          "ii°")
Eo7  = _c("E",  4, "halfdiim7",  {2, 4, 7, 10},       "iiø7")  # Eø7
Cs7  = _c("C#", 1, "dim7",       {1, 4, 7, 10},       "vii°7") # C#°7

# 二次ドミナント
E    = _c("E",  4, "major",      {4, 8, 11},          "V/v")
E7   = _c("E",  4, "dom7",       {2, 4, 8, 11},       "V7/v")
Gs7  = _c("G#", 8, "dim7",       {2, 5, 8, 11},       "vii°7/v") # G#°7
Dmaj = _c("D",  2, "major",      {2, 6, 9},           "V/iv")
D7   = _c("D",  2, "dom7",       {0, 2, 6, 9},        "V7/iv")
G7   = _c("G",  7, "dom7",       {2, 5, 7, 11},       "V7/III")
Gmaj = _c("G",  7, "major",      {2, 7, 11},          "V/VII")  # G major (B natural)

# ──────────────────────────────────────────────
# 312拍の和声進行
# 各エントリ: (根音名, 根音PC, 質, 音程集合, ローマ数字)
# ──────────────────────────────────────────────
PROGRESSION = [
    # ============================================================
    # 提示部 第1声（ソプラノ）主題 D minor — m1〜m4
    # 主題: D-A | F-D | C#-D-E | F-...-E  主調トニカ延長
    # ============================================================
    Dm,   Dm,   Dm,   Dm,   # m1  D-A (主題冒頭, i延長)
    Dm,   Dm,   Dm,   Dm,   # m2  F-D (i延長)
    Amaj, Amaj, Dm,   Dm,   # m3  C#→V, D→i, E経過音
    Dm,   Dm,   Gm,   Amaj, # m4  F→i, G→iv(経過), E→V
    # ============================================================
    # 提示部 第2声（アルト）応答 A minor area — m5〜m8
    # 応答はA上で開始（comes）、第1声は対位旋律
    # ============================================================
    Dm,   Amaj, Dm,   Gm,   # m5  {D,A}→i, {E,A}→V, {D,F}→i, {G,D}→iv
    Am,   Am,   Am,   F,    # m6  {A,C}→v, {A,C}→v, {A,C}→v, {F,A}→III
    E,    E,    Am,   E7,   # m7  {G#,B}→V/v, {E,G#}→V/v, {A,E}→v, {E,B,D}→V7/v
    Am,   D7,   Gm,   C,    # m8  {E,C}→v, {F#,C}→V7/iv, {G,C,D}→iv, {G,Bb,C}→VII
    # ============================================================
    # 提示部 第3声（テノール）主題 D minor — m9〜m12
    # ============================================================
    Dm,   Dm,   Amaj, Amaj, # m9  {D,A}→i, {D,F}→i, {A,E}→V, {A,E,C#}→V
    Dm,   Dm7,  Dm7,  Bb,   # m10 {D,F,A}→i, 経過→i7, {D,F,A,C}→i7, {D,F,Bb}→VI
    Cs7,  A7,   Dm,   Amaj, # m11 {C#,E,G,Bb}→vii°7, {A,C#,G}→V7, {D,F,A}→i, V接近
    Dm7,  G7,   F,    Am,   # m12 {D,F,A,C}→i7, {G,B,F}→V7/III, {C,F,G}→III, {C,E}→v
    # ============================================================
    # 提示部 第4声（バス）応答 A minor area — m13〜m16
    # ============================================================
    Dm7,  Dm7,  Dm7,  Gs7,  # m13 {D,F,A,C}→i7×3, {G#,B,D,F}→vii°7/v
    Am,   E,    Am,   Dm7,  # m14 {C,E}→v, {A,E,G#}→V/v, {A,C,E}→v, {A,C,D,F}→i7
    Gs7,  E7,   Am,   E7,   # m15 {G#,B,D,F}→vii°7/v, {E,G#,B,D}→V7/v, {A,C,E}→v, V7/v
    C7,   D7,   Gm,   C,    # m16 {C,E,G,Bb}→VII7, {F#,A,C}→V7/iv, {G,Bb}→iv, {G,Bb,C}→VII
    # ============================================================
    # エピソード・展開部 — m17〜m32
    # ============================================================
    Dm,   Dm,   Bb,   Eo7,  # m17 {D,A}→i, {D,F}→i, {Bb,D,F}→VI, {E,G,Bb,D}→iiø7
    C7,   F,    D7,   Gmaj, # m18 {C,E,G,Bb}→VII7, {F,A}→III, {D,F#,A,C}→V7/iv, {G,B,D}→V/VII
    E7,   Am,   Amaj, Bb,   # m19 {E,G#,B,D}→V7/v, {A,C,E}→v, {A,C#,E}→V, {Bb,D,F}→VI
    G7,   C,    A7,   Dm,   # m20 {G,B,D,F}→V7/III, {C,E,G}→VII, {A,C#,E,G}→V7, {D,F}→i
    Am,   C,    A7,   Gm,   # m21 {A,E}→v, {C,E,G}→VII, {A,C#,E}→V, {G,Bb,D}→iv
    A7,   Dm,   Dm,   E,    # m22 {A,C#}→V, {D,F,A}→i, {D,B}経過→i, {E,G}→V/v
    Dm,   F,    Am,   C,    # m23 {D,A}→i, {F,A}→III, {A,E}→v, {C#}→V準備
    Dm,   F,    Gm,   Dm,   # m24 {D,F}→i, {C,F}→III, {Bb,A#}→iv, {D}→i
    # ──── m25〜m32: 各調への転調エピソード ────
    Amaj, Amaj, Dm,   Gm,   # m25 {A,C#}→V, {A}→V, {D,F}→i, {F,A,E}→iv接近
    Dm,   Edim, C,    F,    # m26 {D,F,A}→i, {E,B}→ii°, {A,C}→VII, {F,A}→III
    Bb,   Gm,   Dm,   Dm,   # m27 {A#,D}→VI, {G,A#}→iv, {D,A}→i, {D,F}→i
    Am,   F,    E,    E,    # m28 {A,E}→v, {A,C}→III, {E,B}→V/v, {F#,A}→V/v
    E,    Amaj, E7,   E7,   # m29 {F#,A}→V/v, {D}→V, {E,G#}→V7/v, {E,G#,B}→V7/v
    Am,   Am,   F,    Dm,   # m30 {A,C,A}→v, {E,A}→v, {F,C,A}→III, {A,D}→i
    E,    Gs7,  Am,   C,    # m31 {D,G#,B}→V/v, {E,G#,B}→vii°7/v, {C,E,A}→v, {C,G#,B}→VII
    Am,   D7,   Dm,   C,    # m32 {A,C,F#}→V7/iv, {D,F#}→V/iv, {D,A}→i, {C,D,G}→VII
    # ============================================================
    # 展開部中期 — m33〜m48
    # ============================================================
    A7,   F,    F,    Dm,   # m33 {C#,E,A}→V7, {F,A}→III, {F,A}→III, {D,F,A}→i
    Dmaj, Bb,   Gm,   Dm7,  # m34 {D,F#}→V/iv, {A#}→VI, {G,A#}→iv, {D,A}i→i7
    Bb,   Bb,   C,    D7,   # m35 {A#,G}→VI, {G,A#}→VI, {E,A#,C}→VII, {A#,E,F#}→V7/iv
    Dm,   C,    E,    F,    # m36 {G,G}→?→i, {A#}→VII, {A,C#}→V/v, {F}→III
    Bb,   Gm,   C,    Dm,   # m37 {A#,D}→VI, {G}→iv, {C,E}→VII, {A}→i
    Dm,   Bb,   Edim, C,    # m38 {D,F}→i, {B,F,A}→VI(B=Bb?), {E,G}→ii°, {C}→VII
    F,    Dm,   Gmaj, E,    # m39 {F,A}→III, {D}→i, {G,B}→V/VII, {E}→V/v
    E7,   E7,   Dm,   Amaj, # m40 {A,C#,E}→V7/v, {A#}→V7/v, {D,F,A}→i, {D,E}→V
    Dm,   Dm,   Bb,   Gm,   # m41 {D,F}→i, {D}→i, {A#,D}→VI, {D,F,A}→iv
    E7,   E7,   Dm,   E,    # m42 {A,C#,F}→V7/v, {G}→V7/v, {D,A}→i, {E,G}→V/v
    E,    Gm,   Am,   F,    # m43 {F,C#}→V/v, {D,F}→iv, {A}→v, {F,C,A}→III
    D7,   Gm,   Dm,   Dm7,  # m44 {A#,D,F#,C}→V7/iv, {G,A#}→iv, {D,A}→i, {A,F}→i7
    Bb,   Gm,   C,    F,    # m45 {A#}→VI, {E,G}→iv, {C}→VII, {F,A}→III
    F,    Gm,   C,    Amaj, # m46 {D,F,A}→III, {G,A#}→iv, {E,C}→VII, {F,A}→V?
    Dm,   Eo7,  E7,   Dm,   # m47 {D,A#}→i, {E,G}→iiø7, {C#,A}→V7/v, {D,F}→i
    Am,   E7,   E7,   E,    # m48 {E,A}→v, {B,G#}→V7/v, {B,D}→V7/v, {F#}→V/v
    # ============================================================
    # 展開部後期 — m49〜m64
    # ============================================================
    Amaj, E7,   F,    Amaj, # m49 {A,E}→V, {D,E}→V7/v, {D,F,A}→III, {D,E}→V
    Dm,   Dm,   Bb,   Gm,   # m50 {D,F}→i, {D,F}→i, {A#,D}→VI, {G,A#}→iv
    E7,   E7,   Am,   Cs7,  # m51 {A,C#}→V7/v, {A,F,C#}→V7/v, {B,D}→v, {C#,E,F}→vii°7
    Dm,   Am,   C,    F,    # m52 {D,F}→i, {B,D}→v, {C,G}→VII, {A,C,F}→III
    Bb,   Gm,   A7,   Dm,   # m53 {A#,D}→VI, {G,A#}→iv, {A,C#}→V7, {D,F}→i
    Gm,   Eo7,  A7,   A7,   # m54 {G,A#}→iv, {E,D,F,A#}→iiø7, {C#,E}→V7, {A,C#,E,G}→V7
    Dm,   Dm,   Gm,   Gm,   # m55 {D,F}→i, {A#,D}→i, {D,G,A#}→iv, {G,A#}→iv
    Dm,   Dm,   Amaj, Amaj, # m56 {D,A}→i, {D}→i, {A,E}→V, {C#,E}→V
    F,    F,    Dm,   Bb,   # m57 {F,A}→III, {A,D}→III, {D,F}→i, {G,A#}→VI
    A7,   A7,   Dm,   Amaj, # m58 {C#,E,A}→V7, {A}→V7, {D,F}→i, {E,F,G,D}→V
    Dm,   Bb,   Gm,   A7,   # m59 {D,F,A}→i, {A#}→VI, {G,B}→iv, {C#,E,F}→V7
    Dm,   Dm,   Dm,   D7,   # m60 {D,A}→i, {F}→i, {A}→i, {D,F#,D#}→V7/iv(modal)
    Bb,   Gm,   C,    C,    # m61 {A#,D,G}→VI, {A#,G}→iv, {C}→VII, {A#,C,F#}→VII
    Gmaj, Gmaj, Gm,   Gm,   # m62 {D,G}→V/VII, {G,A#}→V/VII, {D#}→iv, {G,A#,D}→iv
    E,    E,    Am,   E,    # m63 {C#,E}→V/v, {F,A}→V/v, {B}→v, {E,G}→V/v
    Am,   F,    Gm,   Amaj, # m64 {A}→v, {D,F}→III, {G,A#}→iv, {E}→V
    # ============================================================
    # クライマックス・終止部 — m65〜m78
    # ============================================================
    F,    Dm,   Amaj, Am,   # m65 {F,A}→III, {A,E}→i, {E,A}→V, {A,C}→v
    D7,   Gm,   Dm,   F,    # m66 {D,F#,A#}→V7/iv, {D,G,A#}→iv, {D,A}→i, {F,A}→III
    Bb,   C,    F,    Dm,   # m67 {A#,D}→VI, {C,E}→VII, {F}→III, {A,D}→i
    Dm,   E,    F,    Am,   # m68 {D,A#}→i, {E,G#}→V/v, {F,A}→III, {C,E}→v
    F,    C,    C,    Dm,   # m69 {F,A}→III, {G,C}→VII, {C}→VII, {D#}→i?
    Dm,   Gm,   A7,   Dm,   # m70 {D,A,G}→i, {A#,G}→iv, {E,C#}→V7, rest
    # ============================================================
    # コーダ — m71〜m78（終止和音の積み上げ）
    # ============================================================
    Dm,   Dm,   Dm,   Dm,   # m71 sparse→i
    Dm,   Dm,   Dm,   Dm,   # m72 {D,F,G#,B}=vii°7/v→Dm解決: i
    Am,   Am,   Am,   A7,   # m73 {A,F,D}→v, {E}→v, {A,B,D}→v, {A,C#}→V7
    Dmaj, Amaj, Gm,   Gm,   # m74 {D,F#,A}→V/iv, {A,C}→V, {D,A#}→iv, {C}→iv
    Bb,   Gm,   Gm,   Amaj, # m75 {A#,D}→VI, {G}→iv, {G,D#}→iv, {A}→V
    Dmaj, Am,   Gm,   D7,   # m76 {D,F#}→V/iv, {A,C}→v, {G,A#}→iv, {C,F#,A}→V7/iv
    Bb,   Gm,   Dm,   C,    # m77 {A#,D}→VI, {G,A#}→iv, {D}→i, {C,A}→VII
    Dmaj, Amaj, Amaj, Dm,   # m78 {D,F#,A}→V/iv, {A,E}→V, {F#}→V, {D,F#,A}→i (終止)
]

assert len(PROGRESSION) == 312, f"Expected 312 beats, got {len(PROGRESSION)}"


def get_expert_progression_as_chord_labels() -> List[ChordLabel]:
    """312拍の和声進行をChordLabelリストとして返す"""
    result = []
    for entry in PROGRESSION:
        name, root_pc, quality, tones, label = entry
        # quality を ChordLabel が受け付ける形式に正規化
        q = quality
        if q == "minor7":   q = "minor"    # Dm7 → minor で近似
        if q == "dom7":     q = "major"    # A7 → major で近似（rootとqualityで識別）
        if q == "dim7":     q = "diminished"
        if q == "halfdiim7":q = "diminished"
        cl = ChordLabel(
            root=root_pc,
            quality=q,
            tones=frozenset(tones),
            label=label,
        )
        result.append(cl)
    return result


if __name__ == "__main__":
    # 簡易表示
    print(f"Total beats: {len(PROGRESSION)}")
    print(f"Total measures: {len(PROGRESSION) // 4}")
    print()
    for i, (name, root, quality, tones, label) in enumerate(PROGRESSION):
        m = i // 4 + 1
        b = i % 4 + 1
        print(f"m{m:>2}.{b}  {label:<12} {name} {quality}")
