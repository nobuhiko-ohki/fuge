"""
古典和声学モジュール
Classical Harmony Module

バッハ様式に必要な和声理論を実装します。
- 三和音・七の和音
- 機能和声（T, S, D）
- 和声進行規則
- カデンツ
"""

from dataclasses import dataclass
from typing import List, Optional, Set, Tuple
from enum import Enum
from counterpoint_engine import Pitch, Interval


class ChordQuality(Enum):
    """和音の種類"""
    MAJOR = "major"                    # 長三和音
    MINOR = "minor"                    # 短三和音
    DIMINISHED = "diminished"          # 減三和音
    AUGMENTED = "augmented"            # 増三和音
    DOMINANT_SEVENTH = "dominant7"     # 属七の和音
    MINOR_SEVENTH = "minor7"           # 短七の和音
    MAJOR_SEVENTH = "major7"           # 長七の和音
    DIMINISHED_SEVENTH = "dim7"        # 減七の和音
    HALF_DIMINISHED = "half_dim7"      # 半減七の和音


class ChordFunction(Enum):
    """和音の機能"""
    TONIC = "T"              # 主和音（I）
    SUBDOMINANT = "S"        # 下属和音（IV）
    DOMINANT = "D"           # 属和音（V）
    TONIC_PARALLEL = "Tp"    # 主和音の平行調（vi）
    SUBDOMINANT_PARALLEL = "Sp"  # 下属和音の平行調（ii）
    DOMINANT_PARALLEL = "Dp"     # 属和音の平行調（iii）
    SECONDARY_DOMINANT = "SD"    # 副属和音


class ScaleDegree(Enum):
    """音階上の度数"""
    I = 1    # 主音
    II = 2   # 上主音
    III = 3  # 中音
    IV = 4   # 下属音
    V = 5    # 属音
    VI = 6   # 下中音
    VII = 7  # 導音


@dataclass
class Chord:
    """和音を表現するクラス"""
    root: int           # 根音（MIDI番号）
    quality: ChordQuality
    pitches: List[int]  # 和音を構成する音高（MIDI番号）
    inversion: int = 0  # 転回（0=基本形、1=第1転回、2=第2転回）
    
    def __post_init__(self):
        if not self.pitches:
            self.pitches = self._generate_pitches()
    
    def _generate_pitches(self) -> List[int]:
        """和音の種類に応じて音高を生成"""
        intervals = {
            ChordQuality.MAJOR: [0, 4, 7],
            ChordQuality.MINOR: [0, 3, 7],
            ChordQuality.DIMINISHED: [0, 3, 6],
            ChordQuality.AUGMENTED: [0, 4, 8],
            ChordQuality.DOMINANT_SEVENTH: [0, 4, 7, 10],
            ChordQuality.MINOR_SEVENTH: [0, 3, 7, 10],
            ChordQuality.MAJOR_SEVENTH: [0, 4, 7, 11],
            ChordQuality.DIMINISHED_SEVENTH: [0, 3, 6, 9],
            ChordQuality.HALF_DIMINISHED: [0, 3, 6, 10],
        }
        
        base_intervals = intervals.get(self.quality, [0, 4, 7])
        pitches = [self.root + interval for interval in base_intervals]
        
        # 転回形を適用
        for _ in range(self.inversion):
            pitches[0] += 12  # 最低音を1オクターブ上げる
            pitches.sort()
        
        return pitches
    
    def get_bass_note(self) -> int:
        """バス音（最低音）を取得"""
        return min(self.pitches)
    
    def contains_pitch_class(self, pitch: int) -> bool:
        """指定された音高（音級）が和音に含まれるか"""
        pitch_class = pitch % 12
        return any((p % 12) == pitch_class for p in self.pitches)
    
    def is_consonant_with(self, pitch: int) -> bool:
        """指定された音高が和音と協和するか"""
        pitch_class = pitch % 12
        
        # 和音構成音なら協和
        if self.contains_pitch_class(pitch):
            return True
        
        # 非和声音の場合は不協和
        return False
    
    def get_chord_tones(self) -> Set[int]:
        """和音構成音の音級セットを返す"""
        return {p % 12 for p in self.pitches}


@dataclass
class Key:
    """調性（拡張版）"""
    tonic: int  # 主音（0=C, 1=C#, 2=D, ...）
    mode: str   # "major" or "minor"
    
    @classmethod
    def from_name(cls, name: str, mode: str) -> 'Key':
        """音名から調性を生成"""
        note_names = {
            'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
            'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8,
            'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11
        }
        tonic = note_names.get(name, 0)
        return cls(tonic, mode)
    
    def get_scale_degree(self, pitch: int) -> Optional[int]:
        """音高から音階上の度数を取得（1-7）"""
        pitch_class = pitch % 12
        
        if self.mode == "major":
            # 長音階: C-D-E-F-G-A-B
            scale = [0, 2, 4, 5, 7, 9, 11]
        else:
            # 自然短音階: A-B-C-D-E-F-G
            scale = [0, 2, 3, 5, 7, 8, 10]
        
        # 移調
        scale = [(n + self.tonic) % 12 for n in scale]
        
        if pitch_class in scale:
            return scale.index(pitch_class) + 1
        return None
    
    def get_diatonic_chord(self, degree: int, seventh: bool = False) -> Chord:
        """指定度数の和音を生成
        
        Args:
            degree: 度数（1-7）
            seventh: 七の和音を含むか
        """
        if self.mode == "major":
            # 長調の和音
            qualities = {
                1: ChordQuality.MAJOR,           # I: 長三和音
                2: ChordQuality.MINOR,           # ii: 短三和音
                3: ChordQuality.MINOR,           # iii: 短三和音
                4: ChordQuality.MAJOR,           # IV: 長三和音
                5: ChordQuality.MAJOR,           # V: 長三和音
                6: ChordQuality.MINOR,           # vi: 短三和音
                7: ChordQuality.DIMINISHED,      # vii°: 減三和音
            }
            scale = [0, 2, 4, 5, 7, 9, 11]
        else:
            # 短調の和音（和声的短音階）
            qualities = {
                1: ChordQuality.MINOR,           # i: 短三和音
                2: ChordQuality.DIMINISHED,      # ii°: 減三和音
                3: ChordQuality.AUGMENTED,       # III+: 増三和音
                4: ChordQuality.MINOR,           # iv: 短三和音
                5: ChordQuality.MAJOR,           # V: 長三和音
                6: ChordQuality.MAJOR,           # VI: 長三和音
                7: ChordQuality.DIMINISHED,      # vii°: 減三和音
            }
            # 和声的短音階（第7音が半音上がる）
            scale = [0, 2, 3, 5, 7, 8, 11]
        
        quality = qualities.get(degree, ChordQuality.MAJOR)
        
        # 七の和音の場合
        if seventh and degree == 5:
            quality = ChordQuality.DOMINANT_SEVENTH
        elif seventh and degree == 7:
            quality = ChordQuality.DIMINISHED_SEVENTH if self.mode == "minor" else ChordQuality.HALF_DIMINISHED
        
        root_pitch_class = (self.tonic + scale[degree - 1]) % 12
        root = root_pitch_class + 48  # C3を基準
        
        return Chord(root, quality, [])


class HarmonicProgression:
    """和声進行を管理するクラス"""
    
    # 古典和声学の基本的な進行規則
    STRONG_PROGRESSIONS = [
        # (from_function, to_function, strength)
        (ChordFunction.SUBDOMINANT, ChordFunction.DOMINANT, 1.0),  # S→D（最強）
        (ChordFunction.DOMINANT, ChordFunction.TONIC, 1.0),        # D→T（最強）
        (ChordFunction.TONIC, ChordFunction.SUBDOMINANT, 0.9),     # T→S（強）
        (ChordFunction.TONIC, ChordFunction.DOMINANT, 0.8),        # T→D（強）
        (ChordFunction.SUBDOMINANT, ChordFunction.TONIC, 0.6),     # S→T（可）
    ]
    
    # 禁則進行
    FORBIDDEN_PROGRESSIONS = [
        (ChordFunction.DOMINANT, ChordFunction.SUBDOMINANT),  # D→S（禁則）
    ]
    
    @classmethod
    def get_chord_function(cls, key: Key, degree: int) -> ChordFunction:
        """度数から和音の機能を取得"""
        if key.mode == "major":
            functions = {
                1: ChordFunction.TONIC,
                2: ChordFunction.SUBDOMINANT_PARALLEL,
                3: ChordFunction.DOMINANT_PARALLEL,
                4: ChordFunction.SUBDOMINANT,
                5: ChordFunction.DOMINANT,
                6: ChordFunction.TONIC_PARALLEL,
                7: ChordFunction.DOMINANT,  # vii°はDの代理
            }
        else:
            functions = {
                1: ChordFunction.TONIC,
                2: ChordFunction.SUBDOMINANT_PARALLEL,
                3: ChordFunction.TONIC,  # III（平行長調の主和音）
                4: ChordFunction.SUBDOMINANT,
                5: ChordFunction.DOMINANT,
                6: ChordFunction.SUBDOMINANT,  # VI（平行長調の下属和音）
                7: ChordFunction.DOMINANT,
            }
        
        return functions.get(degree, ChordFunction.TONIC)
    
    @classmethod
    def is_valid_progression(cls, from_func: ChordFunction, 
                           to_func: ChordFunction) -> bool:
        """和声進行が妥当かチェック"""
        # 同じ機能への進行は常に可
        if from_func == to_func:
            return True
        
        # 禁則進行をチェック
        if (from_func, to_func) in cls.FORBIDDEN_PROGRESSIONS:
            return False
        
        return True
    
    @classmethod
    def get_progression_strength(cls, from_func: ChordFunction,
                                 to_func: ChordFunction) -> float:
        """和声進行の強さを取得（0.0-1.0）"""
        for from_f, to_f, strength in cls.STRONG_PROGRESSIONS:
            if from_f == from_func and to_f == to_func:
                return strength
        
        # リストにない進行は弱い
        return 0.3 if cls.is_valid_progression(from_func, to_func) else 0.0


class Cadence:
    """カデンツ（終止形）"""
    
    @staticmethod
    def create_authentic_cadence(key: Key, perfect: bool = True) -> List[Tuple[int, Chord]]:
        """正格終止（V-I）を生成
        
        Args:
            key: 調性
            perfect: 完全正格終止（V→I、両方とも基本形）か
        """
        if perfect:
            # V7→I（完全正格終止）
            v_chord = key.get_diatonic_chord(5, seventh=True)
            i_chord = key.get_diatonic_chord(1, seventh=False)
            return [(0, v_chord), (1, i_chord)]
        else:
            # 不完全正格終止（転回形を含む）
            v_chord = key.get_diatonic_chord(5, seventh=True)
            v_chord.inversion = 1  # 第1転回
            i_chord = key.get_diatonic_chord(1, seventh=False)
            return [(0, v_chord), (1, i_chord)]
    
    @staticmethod
    def create_plagal_cadence(key: Key) -> List[Tuple[int, Chord]]:
        """変格終止（IV-I）を生成"""
        iv_chord = key.get_diatonic_chord(4)
        i_chord = key.get_diatonic_chord(1)
        return [(0, iv_chord), (1, i_chord)]
    
    @staticmethod
    def create_half_cadence(key: Key) -> List[Tuple[int, Chord]]:
        """半終止（I-V or IV-V）を生成"""
        i_chord = key.get_diatonic_chord(1)
        v_chord = key.get_diatonic_chord(5)
        return [(0, i_chord), (1, v_chord)]
    
    @staticmethod
    def create_deceptive_cadence(key: Key) -> List[Tuple[int, Chord]]:
        """偽終止（V-vi）を生成"""
        v_chord = key.get_diatonic_chord(5, seventh=True)
        vi_chord = key.get_diatonic_chord(6)
        return [(0, v_chord), (1, vi_chord)]


class HarmonicAnalyzer:
    """和声分析を行うクラス"""
    
    def __init__(self, key: Key):
        self.key = key
    
    def analyze_vertical_sonority(self, pitches: List[int]) -> Optional[Chord]:
        """垂直方向の響き（和音）を分析
        
        Args:
            pitches: 同時に鳴っている音高のリスト
            
        Returns:
            識別された和音（識別できない場合はNone）
        """
        if len(pitches) < 2:
            return None
        
        # 音級（ピッチクラス）に変換
        pitch_classes = sorted(set(p % 12 for p in pitches))
        
        # 各度数の和音と照合
        for degree in range(1, 8):
            chord = self.key.get_diatonic_chord(degree)
            chord_tones = chord.get_chord_tones()
            
            # 音級が一致するかチェック
            if pitch_classes == sorted(chord_tones):
                return chord
            
            # 七の和音もチェック
            if degree in [5, 7]:
                chord_7 = self.key.get_diatonic_chord(degree, seventh=True)
                chord_7_tones = chord_7.get_chord_tones()
                if pitch_classes == sorted(chord_7_tones):
                    return chord_7
        
        return None
    
    def get_nonharmonic_tones(self, pitches: List[int], chord: Chord) -> List[int]:
        """非和声音を特定
        
        Args:
            pitches: 音高のリスト
            chord: 現在の和音
            
        Returns:
            非和声音のリスト
        """
        nonharmonic = []
        chord_tones = chord.get_chord_tones()
        
        for pitch in pitches:
            if (pitch % 12) not in chord_tones:
                nonharmonic.append(pitch)
        
        return nonharmonic
    
    def suggest_next_chord(self, current_degree: int) -> List[int]:
        """次の和音の候補を提案
        
        Args:
            current_degree: 現在の度数
            
        Returns:
            推奨される次の度数のリスト（強い順）
        """
        current_func = HarmonicProgression.get_chord_function(self.key, current_degree)
        
        suggestions = []
        for degree in range(1, 8):
            next_func = HarmonicProgression.get_chord_function(self.key, degree)
            strength = HarmonicProgression.get_progression_strength(current_func, next_func)
            if strength > 0:
                suggestions.append((degree, strength))
        
        # 強度順にソート
        suggestions.sort(key=lambda x: x[1], reverse=True)
        return [deg for deg, _ in suggestions]


# 使用例とテスト
if __name__ == "__main__":
    print("=" * 60)
    print("古典和声学モジュール - テスト")
    print("=" * 60)
    
    # ハ長調の調性
    c_major = Key.from_name("C", "major")
    
    print("\n【ハ長調の各度数の和音】")
    for degree in range(1, 8):
        chord = c_major.get_diatonic_chord(degree)
        function = HarmonicProgression.get_chord_function(c_major, degree)
        roman = ['I', 'ii', 'iii', 'IV', 'V', 'vi', 'vii°'][degree - 1]
        print(f"  {roman}: {chord.quality.value:15s} (機能: {function.value})")
    
    print("\n【属七の和音】")
    v7 = c_major.get_diatonic_chord(5, seventh=True)
    print(f"  V7: {v7.quality.value}")
    print(f"  構成音: {v7.pitches}")
    
    print("\n【和声進行の妥当性】")
    progressions = [
        (1, 4), (1, 5), (4, 5), (5, 1),  # 良い進行
        (5, 4),  # 禁則
    ]
    for from_deg, to_deg in progressions:
        from_func = HarmonicProgression.get_chord_function(c_major, from_deg)
        to_func = HarmonicProgression.get_chord_function(c_major, to_deg)
        valid = HarmonicProgression.is_valid_progression(from_func, to_func)
        strength = HarmonicProgression.get_progression_strength(from_func, to_func)
        status = "✓" if valid else "✗"
        print(f"  {status} {from_deg}→{to_deg}: 強度 {strength:.1f}")
    
    print("\n【カデンツ】")
    print("  完全正格終止（V7-I）:")
    pac = Cadence.create_authentic_cadence(c_major, perfect=True)
    for pos, chord in pac:
        print(f"    位置{pos}: {chord.quality.value}, 音高: {chord.pitches}")
    
    print("\n  偽終止（V-vi）:")
    dc = Cadence.create_deceptive_cadence(c_major)
    for pos, chord in dc:
        print(f"    位置{pos}: {chord.quality.value}, 音高: {chord.pitches}")
    
    print("\n【和声分析】")
    analyzer = HarmonicAnalyzer(c_major)
    
    # ハ長調のI和音の音高
    test_pitches = [60, 64, 67]  # C-E-G
    analyzed = analyzer.analyze_vertical_sonority(test_pitches)
    if analyzed:
        print(f"  音高 {test_pitches} は: {analyzed.quality.value}")
    
    print("\n✓ 古典和声学モジュールのテスト完了")
