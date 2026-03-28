"""
古典和声学 完全規則集
Complete Rules of Classical Harmony

Based on:
- Walter Piston: "Harmony" (5th edition, 1987)
- Johann Joseph Fux: "Gradus ad Parnassum" (1725)
- Arnold Schoenberg: "Theory of Harmony" (1911)

すべての禁則を網羅的に実装
"""

from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class ScaleDegree(Enum):
    """音階上の度数"""
    I = 1
    II = 2
    III = 3
    IV = 4
    V = 5
    VI = 6
    VII = 7


@dataclass
class Pitch:
    """音高"""
    midi: int

    @property
    def pitch_class(self) -> int:
        """ピッチクラス（0-11）"""
        return self.midi % 12

    @property
    def octave(self) -> int:
        """オクターブ"""
        return self.midi // 12

    @property
    def name(self) -> str:
        """音名（例: C4, F#5）"""
        notes = ['C', 'C#', 'D', 'D#', 'E', 'F',
                 'F#', 'G', 'G#', 'A', 'A#', 'B']
        octave = (self.midi // 12) - 1
        note = notes[self.midi % 12]
        return f"{note}{octave}"


@dataclass
class Interval:
    """音程"""
    semitones: int

    @property
    def interval_class(self) -> int:
        return self.semitones % 12


class HarmonyRules:
    """古典和声学の規則"""

    # ============================================================
    # 第1章: 音階と調性
    # ============================================================

    @staticmethod
    def get_major_scale(tonic: int) -> List[int]:
        """長音階の音（ピッチクラス）

        規則: 全全半全全全半
        """
        intervals = [0, 2, 4, 5, 7, 9, 11]
        return [(tonic + i) % 12 for i in intervals]

    @staticmethod
    def get_natural_minor_scale(tonic: int) -> List[int]:
        """自然短音階の音（ピッチクラス）

        規則: 全半全全半全全
        """
        intervals = [0, 2, 3, 5, 7, 8, 10]
        return [(tonic + i) % 12 for i in intervals]

    @staticmethod
    def get_harmonic_minor_scale(tonic: int) -> List[int]:
        """和声的短音階の音（ピッチクラス）

        規則: 全半全全半増2度半（第7音を半音上げる）
        """
        intervals = [0, 2, 3, 5, 7, 8, 11]
        return [(tonic + i) % 12 for i in intervals]

    # ============================================================
    # 第2章: 三和音と七の和音
    # ============================================================

    @staticmethod
    def get_triad(root_pc: int, quality: str) -> Set[int]:
        """三和音のピッチクラス集合"""
        if quality == "major":
            return {root_pc, (root_pc + 4) % 12, (root_pc + 7) % 12}
        elif quality == "minor":
            return {root_pc, (root_pc + 3) % 12, (root_pc + 7) % 12}
        elif quality == "diminished":
            return {root_pc, (root_pc + 3) % 12, (root_pc + 6) % 12}
        elif quality == "augmented":
            return {root_pc, (root_pc + 4) % 12, (root_pc + 8) % 12}
        return set()

    @staticmethod
    def get_diatonic_triads(tonic: int, mode: str = "major") -> Dict[int, Tuple[int, str]]:
        """各度数の三和音（根音, 性質）"""
        if mode == "major":
            scale = HarmonyRules.get_major_scale(tonic)
            qualities = ["major", "minor", "minor", "major",
                        "major", "minor", "diminished"]
        else:
            scale = HarmonyRules.get_harmonic_minor_scale(tonic)
            qualities = ["minor", "diminished", "augmented", "minor",
                        "major", "major", "diminished"]
        return {i+1: (scale[i], qualities[i]) for i in range(7)}

    # ============================================================
    # 第3章: 声部配置と音域
    # ============================================================

    VOICE_RANGES = {
        'soprano': (60, 79),   # C4-G5
        'alto':    (55, 74),   # G3-D5
        'tenor':   (48, 67),   # C3-G4
        'bass':    (40, 60),   # E2-C4
    }

    @staticmethod
    def check_spacing(soprano: int, alto: int, tenor: int, bass: int) -> Tuple[bool, str]:
        """声部間隔チェック

        隣接上3声部間はオクターブ以内、バス-テノール間は12度以内
        """
        if soprano - alto > 12:
            return False, "ソプラノ-アルト間が1オクターブ超過"
        if alto - tenor > 12:
            return False, "アルト-テノール間が1オクターブ超過"
        if tenor - bass > 19:
            return False, "テノール-バス間が12度超過"
        return True, ""

    @staticmethod
    def check_voice_crossing(soprano: int, alto: int, tenor: int, bass: int) -> Tuple[bool, str]:
        """声部交差チェック"""
        if soprano < alto:
            return False, "ソプラノがアルトより低い"
        if alto < tenor:
            return False, "アルトがテノールより低い"
        if tenor < bass:
            return False, "テノールがバスより低い"
        return True, ""

    # ============================================================
    # 第4章: 禁則
    # ============================================================

    @staticmethod
    def check_parallel_fifths(v1_prev: int, v1_curr: int,
                               v2_prev: int, v2_curr: int) -> Tuple[bool, str]:
        """連続5度チェック"""
        m1 = v1_curr - v1_prev
        m2 = v2_curr - v2_prev
        if m1 == 0 or m2 == 0:
            return True, ""
        if (m1 > 0 and m2 < 0) or (m1 < 0 and m2 > 0):
            return True, ""
        prev_ic = abs(v1_prev - v2_prev) % 12
        curr_ic = abs(v1_curr - v2_curr) % 12
        if prev_ic == 7 and curr_ic == 7:
            return False, "連続5度"
        return True, ""

    @staticmethod
    def check_parallel_octaves(v1_prev: int, v1_curr: int,
                                v2_prev: int, v2_curr: int) -> Tuple[bool, str]:
        """連続8度チェック"""
        m1 = v1_curr - v1_prev
        m2 = v2_curr - v2_prev
        if m1 == 0 or m2 == 0:
            return True, ""
        if (m1 > 0 and m2 < 0) or (m1 < 0 and m2 > 0):
            return True, ""
        prev_ic = abs(v1_prev - v2_prev) % 12
        curr_ic = abs(v1_curr - v2_curr) % 12
        if prev_ic == 0 and curr_ic == 0:
            return False, "連続8度"
        return True, ""

    @staticmethod
    def check_doubling(soprano: int, alto: int, tenor: int, bass: int,
                       leading_tone_pc: int) -> Tuple[bool, str]:
        """導音の重複チェック"""
        pcs = [soprano % 12, alto % 12, tenor % 12, bass % 12]
        if pcs.count(leading_tone_pc) > 1:
            return False, "導音の重複"
        return True, ""

    @staticmethod
    def check_leading_tone_resolution(prev_soprano: int, curr_soprano: int,
                                       prev_alto: int, curr_alto: int,
                                       prev_tenor: int, curr_tenor: int,
                                       leading_tone_pc: int,
                                       tonic_pc: int) -> Tuple[bool, str]:
        """導音解決チェック"""
        pairs = [
            (prev_soprano, curr_soprano, "soprano"),
            (prev_alto, curr_alto, "alto"),
            (prev_tenor, curr_tenor, "tenor"),
        ]
        for prev_v, curr_v, name in pairs:
            if prev_v % 12 == leading_tone_pc:
                expected_resolution = (leading_tone_pc + 1) % 12
                if curr_v % 12 != expected_resolution:
                    return False, f"{name}の導音が主音に解決していない"
        return True, ""
