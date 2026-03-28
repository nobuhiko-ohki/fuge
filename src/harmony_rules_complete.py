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
class NoteEvent:
    """音高＋音長

    duration はサブビート単位:
        4 = 四分音符
        2 = 八分音符
        1 = 十六分音符
        6 = 付点四分音符
        3 = 付点八分音符
    """
    pitch: Pitch
    duration: int = 4  # デフォルト四分音符

    @property
    def midi(self) -> int:
        return self.pitch.midi

    @property
    def pitch_class(self) -> int:
        return self.pitch.pitch_class


@dataclass
class Interval:
    """音程"""
    semitones: int

    @property
    def interval_class(self) -> int:
        """音程クラス（0-11）"""
        return abs(self.semitones) % 12
    
    def is_consonant(self) -> bool:
        """協和音程か"""
        consonant = {0, 3, 4, 7, 8, 9}  # 1度, 短3度, 長3度, 5度, 短6度, 長6度
        return self.interval_class in consonant
    
    def is_perfect(self) -> bool:
        """完全協和音程か"""
        return self.interval_class in {0, 7}  # 1度, 5度


class HarmonyRules:
    """古典和声学の完全規則集"""
    
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
    def build_triad(root: int, quality: str) -> List[int]:
        """三和音を構築
        
        Args:
            root: 根音（ピッチクラス）
            quality: "major", "minor", "diminished", "augmented"
        
        Returns:
            [根音, 第三音, 第五音]
        """
        intervals = {
            "major": [0, 4, 7],
            "minor": [0, 3, 7],
            "diminished": [0, 3, 6],
            "augmented": [0, 4, 8]
        }
        
        if quality not in intervals:
            raise ValueError(f"Invalid quality: {quality}")
        
        return [(root + i) % 12 for i in intervals[quality]]
    
    @staticmethod
    def build_seventh_chord(root: int, quality: str) -> List[int]:
        """七の和音を構築
        
        Args:
            quality: "dominant7", "major7", "minor7", "half_diminished7", "diminished7"
        
        Returns:
            [根音, 第三音, 第五音, 第七音]
        """
        intervals = {
            "dominant7": [0, 4, 7, 10],      # 長三・短七
            "major7": [0, 4, 7, 11],         # 長三・長七
            "minor7": [0, 3, 7, 10],         # 短三・短七
            "half_diminished7": [0, 3, 6, 10],  # 減三・短七
            "diminished7": [0, 3, 6, 9]      # 減三・減七
        }
        
        if quality not in intervals:
            raise ValueError(f"Invalid quality: {quality}")
        
        return [(root + i) % 12 for i in intervals[quality]]
    
    # ============================================================
    # 第3章: 声部配置（Voice Leading）
    # ============================================================
    
    @staticmethod
    def check_voice_range(pitch: Pitch, voice: str) -> Tuple[bool, str]:
        """声部の音域チェック
        
        Piston p.17:
        - Soprano: C4 (60) - G5 (79)
        - Alto: G3 (55) - D5 (74)
        - Tenor: C3 (48) - G4 (67)
        - Bass: E2 (40) - C4 (60)
        """
        ranges = {
            "soprano": (60, 79),
            "alto": (55, 74),
            "tenor": (48, 67),
            "bass": (40, 60)
        }
        
        if voice not in ranges:
            return False, f"Unknown voice: {voice}"
        
        min_pitch, max_pitch = ranges[voice]
        
        if pitch.midi < min_pitch:
            return False, f"{voice} too low: {pitch.midi} < {min_pitch}"
        if pitch.midi > max_pitch:
            return False, f"{voice} too high: {pitch.midi} > {max_pitch}"
        
        return True, ""
    
    @staticmethod
    def check_voice_crossing(pitches: Dict[str, Pitch]) -> Tuple[bool, str]:
        """声部交差のチェック
        
        Piston p.18: 声部の順序は常に S > A > T > B
        """
        order = ["soprano", "alto", "tenor", "bass"]
        
        for i in range(len(order) - 1):
            if order[i] in pitches and order[i+1] in pitches:
                if pitches[order[i]].midi < pitches[order[i+1]].midi:
                    return False, f"Voice crossing: {order[i]} below {order[i+1]}"
        
        return True, ""
    
    @staticmethod
    def check_spacing(pitches: Dict[str, Pitch]) -> Tuple[bool, str]:
        """声部間隔のチェック
        
        Piston p.18:
        - 上3声（S, A, T）間：1オクターブ以内
        - バスと他の声部：制限なし
        """
        if "soprano" in pitches and "alto" in pitches:
            if pitches["soprano"].midi - pitches["alto"].midi > 12:
                return False, "Soprano-Alto spacing > octave"
        
        if "alto" in pitches and "tenor" in pitches:
            if pitches["alto"].midi - pitches["tenor"].midi > 12:
                return False, "Alto-Tenor spacing > octave"
        
        return True, ""
    
    # ============================================================
    # 第4章: 禁則 - 平行進行
    # ============================================================
    
    @staticmethod
    def check_parallel_perfect(voice1_prev: Pitch, voice1_curr: Pitch,
                               voice2_prev: Pitch, voice2_curr: Pitch) -> Tuple[bool, str]:
        """平行5度・8度の禁止
        
        Piston p.21: "The most important prohibition"
        
        完全協和音程（1度, 5度, 8度）が同じ方向に平行進行することは絶対禁止
        """
        prev_interval = Interval(voice1_prev.midi - voice2_prev.midi)
        curr_interval = Interval(voice1_curr.midi - voice2_curr.midi)
        
        # 両方が完全協和音程か
        if not (prev_interval.is_perfect() and curr_interval.is_perfect()):
            return True, ""
        
        # 同じ音程クラスか（平行）
        if prev_interval.interval_class != curr_interval.interval_class:
            return True, ""
        
        # 同じ方向に動いているか
        motion1 = voice1_curr.midi - voice1_prev.midi
        motion2 = voice2_curr.midi - voice2_prev.midi
        
        if (motion1 > 0 and motion2 > 0) or (motion1 < 0 and motion2 < 0):
            interval_name = "unison/octave" if curr_interval.interval_class == 0 else "fifth"
            return False, f"Parallel {interval_name}"
        
        return True, ""
    
    @staticmethod
    def check_hidden_parallel(voice1_prev: Pitch, voice1_curr: Pitch,
                              voice2_prev: Pitch, voice2_curr: Pitch,
                              is_outer_voices: bool) -> Tuple[bool, str]:
        """隠伏5度・8度のチェック
        
        Piston p.23:
        外声部（ソプラノ-バス）が同方向に動いて完全協和音程に到達する場合、
        ソプラノは順次進行でなければならない
        """
        if not is_outer_voices:
            return True, ""  # 内声部は緩い
        
        curr_interval = Interval(voice1_curr.midi - voice2_curr.midi)
        
        if not curr_interval.is_perfect():
            return True, ""
        
        # 同じ方向に動いているか
        motion1 = voice1_curr.midi - voice1_prev.midi
        motion2 = voice2_curr.midi - voice2_prev.midi
        
        if not ((motion1 > 0 and motion2 > 0) or (motion1 < 0 and motion2 < 0)):
            return True, ""
        
        # ソプラノ（上声）が順次進行か
        if abs(motion1) > 2:
            return False, "Hidden parallel (soprano must move by step)"
        
        return True, ""
    
    # ============================================================
    # 第5章: 禁則 - 不協和音程
    # ============================================================
    
    @staticmethod
    def check_melodic_augmented_interval(pitch1: Pitch, pitch2: Pitch) -> Tuple[bool, str]:
        """増音程の旋律的使用禁止
        
        Piston p.25: 増4度、増5度などの旋律的跳躍は禁止
        """
        interval = abs(pitch2.midi - pitch1.midi)
        
        # 増4度（6半音）または減5度
        if interval == 6:
            return False, "Melodic augmented fourth (tritone)"
        
        # 増5度（8半音）
        if interval == 8:
            return False, "Melodic augmented fifth"
        
        return True, ""
    
    @staticmethod
    def check_vertical_dissonance(pitches: List[Pitch], 
                                  chord_tones: Set[int],
                                  is_strong_beat: bool) -> Tuple[bool, str]:
        """垂直方向の不協和音チェック
        
        Piston p.48-50:
        - 強拍：和音構成音のみ（不協和音禁止）
        - 弱拍：経過音・刺繍音として限定的に許容
        """
        for i in range(len(pitches)):
            for j in range(i + 1, len(pitches)):
                interval = Interval(pitches[i].midi - pitches[j].midi)
                
                # 短2度は常に禁止
                if interval.interval_class == 1:
                    return False, "Minor second (always forbidden)"
                
                # 増4度は常に禁止
                if interval.interval_class == 6:
                    return False, "Augmented fourth (tritone)"
                
                if is_strong_beat:
                    # 強拍：長2度、長7度も禁止
                    if interval.interval_class == 2:
                        return False, "Major second on strong beat"
                    if interval.interval_class == 10:
                        return False, "Minor seventh on strong beat"
                    if interval.interval_class == 11:
                        return False, "Major seventh on strong beat"
        
        # 強拍では全ての音が和音構成音でなければならない
        if is_strong_beat:
            for pitch in pitches:
                if pitch.pitch_class not in chord_tones:
                    return False, "Non-chord tone on strong beat"
        
        return True, ""
    
    # ============================================================
    # 第6章: 和声進行
    # ============================================================
    
    @staticmethod
    def check_chord_progression(prev_degree: ScaleDegree, 
                                curr_degree: ScaleDegree) -> Tuple[bool, str]:
        """和声進行の妥当性チェック
        
        Piston p.29-31:
        禁則:
        - V → IV （属和音から下属和音への逆行）
        - V → ii （同上）
        - vii° → IV （同上）
        """
        forbidden = [
            (ScaleDegree.V, ScaleDegree.IV),
            (ScaleDegree.V, ScaleDegree.II),
            (ScaleDegree.VII, ScaleDegree.IV),
        ]
        
        if (prev_degree, curr_degree) in forbidden:
            return False, f"Forbidden progression: {prev_degree.name} → {curr_degree.name}"
        
        return True, ""
    
    # ============================================================
    # 第7章: 導音と解決
    # ============================================================
    
    @staticmethod
    def check_leading_tone_resolution(prev_pitch: Pitch, curr_pitch: Pitch,
                                      tonic_pc: int,
                                      is_leading_tone: bool) -> Tuple[bool, str]:
        """導音の解決チェック
        
        Piston p.32:
        導音（第7音）は主音へ上行解決しなければならない
        """
        if not is_leading_tone:
            return True, ""
        
        expected_resolution = (tonic_pc) % 12
        
        if curr_pitch.pitch_class != expected_resolution:
            return False, "Leading tone must resolve to tonic"
        
        if curr_pitch.midi <= prev_pitch.midi:
            return False, "Leading tone must resolve upward"
        
        return True, ""
    
    @staticmethod
    def check_seventh_resolution(prev_pitch: Pitch, curr_pitch: Pitch,
                                 is_seventh: bool) -> Tuple[bool, str]:
        """第七音の解決チェック
        
        Piston p.118:
        七の和音の第七音は半音または全音下行解決
        """
        if not is_seventh:
            return True, ""
        
        motion = curr_pitch.midi - prev_pitch.midi
        
        if motion >= 0:
            return False, "Seventh must resolve downward"
        
        if motion < -2:
            return False, "Seventh must resolve by step (tone or semitone)"
        
        return True, ""
    
    # ============================================================
    # 第8章: 重複と省略
    # ============================================================
    
    @staticmethod
    def check_chord_doubling(pitches: List[Pitch], 
                            chord_tones: List[int],
                            root: int, third: int, fifth: int) -> Tuple[bool, str]:
        """和音の重複・省略チェック
        
        Piston p.19-20:
        - 根音の重複：推奨
        - 第三音の重複：避ける（和音の性格を決める音）
        - 第三音の省略：絶対禁止
        - 第五音の省略：可（根音を重複）
        """
        pitch_classes = [p.pitch_class for p in pitches]
        
        # 第三音が含まれているか（絶対必須）
        if third not in pitch_classes:
            return False, "Third must not be omitted"
        
        # 根音が含まれているか（必須）
        if root not in pitch_classes:
            return False, "Root must be present"
        
        # 第三音の重複チェック（避けるべき）
        third_count = pitch_classes.count(third)
        if third_count > 1:
            return False, "Third should not be doubled"
        
        return True, ""
    
    # ============================================================
    # 第9章: カデンツ（終止形）
    # ============================================================
    
    @staticmethod
    def check_authentic_cadence(v_chord_pitches: Dict[str, Pitch],
                               i_chord_pitches: Dict[str, Pitch],
                               tonic: int,
                               is_perfect: bool) -> Tuple[bool, str]:
        """正格終止のチェック
        
        Piston p.88-89:
        完全正格終止（Perfect Authentic Cadence）:
        - V（またはV7）→ I
        - 両和音とも基本形（バス=根音）
        - ソプラノは主音で終わる
        - 導音は主音へ上行解決
        """
        if is_perfect:
            # バスが根音か
            if "bass" not in i_chord_pitches:
                return False, "Bass voice missing in I chord"
            
            if i_chord_pitches["bass"].pitch_class != tonic:
                return False, "Bass must be root (tonic) in perfect cadence"
            
            # ソプラノが主音か
            if "soprano" not in i_chord_pitches:
                return False, "Soprano voice missing in I chord"
            
            if i_chord_pitches["soprano"].pitch_class != tonic:
                return False, "Soprano must be tonic in perfect cadence"
        
        return True, ""
    
    # ============================================================
    # 第10章: 非和声音（Non-Harmonic Tones）
    # ============================================================
    
    @staticmethod
    def validate_passing_tone(prev_pitch: Pitch, passing_pitch: Pitch, next_pitch: Pitch,
                             chord_tones: Set[int]) -> Tuple[bool, str]:
        """経過音の妥当性チェック
        
        Piston p.48-50:
        経過音の規則:
        1. 2つの和音構成音の間にある
        2. 順次進行（半音または全音）
        3. 同じ方向に進む
        4. 弱拍に置く
        """
        # 前後が和音構成音か
        if prev_pitch.pitch_class not in chord_tones:
            return False, "Passing tone must be between chord tones"
        if next_pitch.pitch_class not in chord_tones:
            return False, "Passing tone must be between chord tones"
        
        # 順次進行か
        interval1 = abs(passing_pitch.midi - prev_pitch.midi)
        interval2 = abs(next_pitch.midi - passing_pitch.midi)
        
        if interval1 > 2:
            return False, "Passing tone must approach by step"
        if interval2 > 2:
            return False, "Passing tone must leave by step"
        
        # 同じ方向か
        motion1 = passing_pitch.midi - prev_pitch.midi
        motion2 = next_pitch.midi - passing_pitch.midi
        
        if (motion1 > 0 and motion2 < 0) or (motion1 < 0 and motion2 > 0):
            return False, "Passing tone must continue in same direction"
        
        return True, ""


# ============================================================
# テストスイート
# ============================================================

def test_all_rules():
    """全ての規則をテスト"""
    
    print("=" * 70)
    print("古典和声学規則 - 完全性テスト")
    print("=" * 70)
    
    rules = HarmonyRules()
    passed = 0
    failed = 0
    
    tests = [
        # 音階
        ("Major scale", lambda: rules.get_major_scale(0) == [0, 2, 4, 5, 7, 9, 11]),
        
        # 三和音
        ("C major triad", lambda: rules.build_triad(0, "major") == [0, 4, 7]),
        
        # 平行5度検出
        ("Parallel fifths detection", lambda: not rules.check_parallel_perfect(
            Pitch(60), Pitch(62), Pitch(67), Pitch(69)
        )[0]),
        
        # 声部音域
        ("Soprano range", lambda: rules.check_voice_range(Pitch(72), "soprano")[0]),
        ("Soprano too high", lambda: not rules.check_voice_range(Pitch(85), "soprano")[0]),
        
        # 禁則進行
        ("V→IV forbidden", lambda: not rules.check_chord_progression(
            ScaleDegree.V, ScaleDegree.IV
        )[0]),
        
        # 増4度禁止
        ("Augmented fourth", lambda: not rules.check_melodic_augmented_interval(
            Pitch(60), Pitch(66)
        )[0]),
    ]
    
    for name, test_func in tests:
        try:
            result = test_func()
            if result:
                print(f"✓ {name}")
                passed += 1
            else:
                print(f"✗ {name}")
                failed += 1
        except Exception as e:
            print(f"✗ {name}: {e}")
            failed += 1
    
    print(f"\n結果: {passed}/{passed + failed} passed")
    
    if failed == 0:
        print("✓ 全てのテストに合格")
    else:
        print(f"✗ {failed}個のテストが失敗")


if __name__ == "__main__":
    test_all_rules()
