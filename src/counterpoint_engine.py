"""
バッハ様式フーガ作曲支援システム - 対位法エンジン
Counterpoint Engine for Bach-style Fugue Composition

このモジュールは厳格対位法の規則を実装し、
声部進行の妥当性を検証します。
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import Enum


class IntervalQuality(Enum):
    """音程の種類"""
    PERFECT = "perfect"
    MAJOR = "major"
    MINOR = "minor"
    AUGMENTED = "augmented"
    DIMINISHED = "diminished"


@dataclass
class Pitch:
    """音高を表現するクラス
    
    Attributes:
        midi_number: MIDI音高番号（C4=60）
        name: 音名（例: "C", "D#", "Eb"）
    """
    midi_number: int
    name: str = ""
    
    def __post_init__(self):
        if not self.name:
            self.name = self._midi_to_name()
    
    def _midi_to_name(self) -> str:
        """MIDI番号から音名を生成"""
        notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        octave = (self.midi_number // 12) - 1
        note = notes[self.midi_number % 12]
        return f"{note}{octave}"
    
    def interval_to(self, other: 'Pitch') -> int:
        """他の音高との半音数での音程を計算"""
        return other.midi_number - self.midi_number
    
    def chromatic_interval_to(self, other: 'Pitch') -> int:
        """絶対的な半音数での音程（方向を考慮しない）"""
        return abs(self.interval_to(other))


@dataclass
class Interval:
    """音程を表現するクラス"""
    semitones: int  # 半音数
    diatonic_steps: int  # 音度数（1=同度、2=2度、など）
    quality: IntervalQuality
    
    @classmethod
    def from_pitches(cls, pitch1: Pitch, pitch2: Pitch) -> 'Interval':
        """2つの音高から音程を生成"""
        semitones = pitch2.midi_number - pitch1.midi_number
        # 簡易的な実装（完全な実装には調性情報が必要）
        abs_semitones = abs(semitones) % 12
        
        # 音程の種類を判定
        interval_map = {
            0: (1, IntervalQuality.PERFECT),
            1: (2, IntervalQuality.MINOR),
            2: (2, IntervalQuality.MAJOR),
            3: (3, IntervalQuality.MINOR),
            4: (3, IntervalQuality.MAJOR),
            5: (4, IntervalQuality.PERFECT),
            6: (5, IntervalQuality.DIMINISHED),
            7: (5, IntervalQuality.PERFECT),
            8: (6, IntervalQuality.MINOR),
            9: (6, IntervalQuality.MAJOR),
            10: (7, IntervalQuality.MINOR),
            11: (7, IntervalQuality.MAJOR),
        }
        
        diatonic_steps, quality = interval_map.get(abs_semitones, (1, IntervalQuality.PERFECT))
        
        return cls(semitones=semitones, diatonic_steps=diatonic_steps, quality=quality)
    
    def is_perfect_consonance(self) -> bool:
        """完全協和音程かどうか（1度、4度、5度、8度）"""
        return self.quality == IntervalQuality.PERFECT and self.diatonic_steps in [1, 4, 5, 8]
    
    def is_imperfect_consonance(self) -> bool:
        """不完全協和音程かどうか（3度、6度）"""
        return self.diatonic_steps in [3, 6] and self.quality in [IntervalQuality.MAJOR, IntervalQuality.MINOR]
    
    def is_dissonance(self) -> bool:
        """不協和音程かどうか"""
        return not (self.is_perfect_consonance() or self.is_imperfect_consonance())


@dataclass
class Voice:
    """声部を表現するクラス"""
    pitches: List[Pitch]
    name: str = "Voice"
    
    def get_pitch_at(self, index: int) -> Optional[Pitch]:
        """指定位置の音高を取得"""
        if 0 <= index < len(self.pitches):
            return self.pitches[index]
        return None
    
    def add_pitch(self, pitch: Pitch):
        """音高を追加"""
        self.pitches.append(pitch)
    
    def get_motion_to_next(self, index: int) -> Optional[int]:
        """次の音への動き（半音数）を取得"""
        if index < len(self.pitches) - 1:
            return self.pitches[index + 1].midi_number - self.pitches[index].midi_number
        return None


class CounterpointRules:
    """対位法の規則を実装するクラス"""
    
    @staticmethod
    def check_parallel_perfect(voice1: Voice, voice2: Voice, index: int) -> Tuple[bool, str]:
        """平行5度・8度をチェック
        
        Returns:
            (is_valid, error_message): 規則に違反していなければ(True, "")
        """
        if index >= len(voice1.pitches) - 1 or index >= len(voice2.pitches) - 1:
            return True, ""
        
        # 現在の音程
        current_interval = Interval.from_pitches(voice1.pitches[index], voice2.pitches[index])
        # 次の音程
        next_interval = Interval.from_pitches(voice1.pitches[index + 1], voice2.pitches[index + 1])
        
        # 完全協和音程の平行進行をチェック
        if current_interval.is_perfect_consonance() and next_interval.is_perfect_consonance():
            if current_interval.diatonic_steps == next_interval.diatonic_steps:
                # 同じ完全協和音程への平行進行
                if current_interval.diatonic_steps in [5, 8]:  # 5度または8度
                    return False, f"平行{current_interval.diatonic_steps}度が検出されました（位置{index}）"
        
        return True, ""
    
    @staticmethod
    def check_hidden_parallel(voice1: Voice, voice2: Voice, index: int) -> Tuple[bool, str]:
        """隠伏5度・8度をチェック
        
        2つの声部が同じ方向に動いて完全協和音程に到達する場合、
        上声が順次進行でなければ隠伏進行となる
        """
        if index >= len(voice1.pitches) - 1 or index >= len(voice2.pitches) - 1:
            return True, ""
        
        # 到達音程
        next_interval = Interval.from_pitches(voice1.pitches[index + 1], voice2.pitches[index + 1])
        
        if not next_interval.is_perfect_consonance():
            return True, ""
        
        # 両声部の動き
        motion1 = voice1.get_motion_to_next(index)
        motion2 = voice2.get_motion_to_next(index)
        
        if motion1 is None or motion2 is None:
            return True, ""
        
        # 同じ方向への動き
        if (motion1 > 0 and motion2 > 0) or (motion1 < 0 and motion2 < 0):
            # 上声部を判定（より高い音域の声部）
            upper_voice = voice1 if voice1.pitches[index].midi_number > voice2.pitches[index].midi_number else voice2
            upper_motion = motion1 if upper_voice == voice1 else motion2
            
            # 上声が跳躍進行（3度以上）の場合は隠伏進行
            if abs(upper_motion) > 2:
                return False, f"隠伏{next_interval.diatonic_steps}度が検出されました（位置{index}）"
        
        return True, ""
    
    @staticmethod
    def check_voice_crossing(voice1: Voice, voice2: Voice, index: int) -> Tuple[bool, str]:
        """声部交差をチェック"""
        if index >= len(voice1.pitches) or index >= len(voice2.pitches):
            return True, ""
        
        p1 = voice1.pitches[index].midi_number
        p2 = voice2.pitches[index].midi_number
        
        # 前の位置での順序
        if index > 0:
            prev_p1 = voice1.pitches[index - 1].midi_number
            prev_p2 = voice2.pitches[index - 1].midi_number
            
            # 順序が逆転したら交差
            if (prev_p1 > prev_p2 and p1 < p2) or (prev_p1 < prev_p2 and p1 > p2):
                return False, f"声部交差が検出されました（位置{index}）"
        
        return True, ""
    
    @staticmethod
    def check_leap_resolution(voice: Voice, index: int) -> Tuple[bool, str]:
        """跳躍進行の解決をチェック
        
        6度以上の跳躍は反対方向への順次進行で解決されるべき
        """
        if index >= len(voice.pitches) - 2:
            return True, ""
        
        # 最初の動き（跳躍）
        motion1 = voice.get_motion_to_next(index)
        # 次の動き（解決）
        motion2 = voice.get_motion_to_next(index + 1)
        
        if motion1 is None or motion2 is None:
            return True, ""
        
        # 6度以上の跳躍
        if abs(motion1) >= 9:  # 6度 = 9半音
            # 反対方向への順次進行（2度 = 1-2半音）かチェック
            if not ((motion1 > 0 and motion2 < 0 and abs(motion2) <= 2) or
                    (motion1 < 0 and motion2 > 0 and abs(motion2) <= 2)):
                return False, f"大跳躍の不適切な解決（位置{index}）"
        
        return True, ""
    
    @staticmethod
    def check_augmented_intervals(voice: Voice, index: int) -> Tuple[bool, str]:
        """増音程（特に増4度）の旋律的使用をチェック"""
        if index >= len(voice.pitches) - 1:
            return True, ""
        
        interval = voice.pitches[index].interval_to(voice.pitches[index + 1])
        
        # 増4度（6半音）または減5度
        if abs(interval) == 6:
            return False, f"増4度（または減5度）の旋律的使用（位置{index}）"
        
        return True, ""


class CounterpointValidator:
    """対位法の妥当性を検証するクラス"""
    
    def __init__(self):
        self.rules = CounterpointRules()
    
    def validate_two_voices(self, voice1: Voice, voice2: Voice) -> List[str]:
        """2声部の対位法を検証
        
        Returns:
            エラーメッセージのリスト（空の場合は問題なし）
        """
        errors = []
        max_length = min(len(voice1.pitches), len(voice2.pitches))
        
        for i in range(max_length):
            # 平行5度・8度
            is_valid, msg = self.rules.check_parallel_perfect(voice1, voice2, i)
            if not is_valid:
                errors.append(msg)
            
            # 隠伏5度・8度
            is_valid, msg = self.rules.check_hidden_parallel(voice1, voice2, i)
            if not is_valid:
                errors.append(msg)
            
            # 声部交差
            is_valid, msg = self.rules.check_voice_crossing(voice1, voice2, i)
            if not is_valid:
                errors.append(msg)
        
        return errors
    
    def validate_single_voice(self, voice: Voice) -> List[str]:
        """単一声部の旋律的妥当性を検証"""
        errors = []
        
        for i in range(len(voice.pitches)):
            # 跳躍の解決
            is_valid, msg = self.rules.check_leap_resolution(voice, i)
            if not is_valid:
                errors.append(msg)
            
            # 増音程
            is_valid, msg = self.rules.check_augmented_intervals(voice, i)
            if not is_valid:
                errors.append(msg)
        
        return errors
    
    def validate_all_voices(self, voices: List[Voice]) -> dict:
        """すべての声部を検証
        
        Returns:
            {'single_voice_errors': [...], 'two_voice_errors': {...}}
        """
        result = {
            'single_voice_errors': {},
            'two_voice_errors': {}
        }
        
        # 各声部の単独検証
        for i, voice in enumerate(voices):
            errors = self.validate_single_voice(voice)
            if errors:
                result['single_voice_errors'][voice.name] = errors
        
        # 声部間の検証
        for i in range(len(voices)):
            for j in range(i + 1, len(voices)):
                errors = self.validate_two_voices(voices[i], voices[j])
                if errors:
                    pair_name = f"{voices[i].name} - {voices[j].name}"
                    result['two_voice_errors'][pair_name] = errors
        
        return result


# 使用例とテスト
if __name__ == "__main__":
    print("=== バッハ様式フーガ対位法エンジン ===\n")
    
    # テストケース1: 平行5度の検出
    print("テスト1: 平行5度の検出")
    soprano = Voice([
        Pitch(67, "G4"),  # G4
        Pitch(69, "A4"),  # A4
    ], name="ソプラノ")
    
    alto = Voice([
        Pitch(60, "C4"),  # C4
        Pitch(62, "D4"),  # D4
    ], name="アルト")
    
    validator = CounterpointValidator()
    errors = validator.validate_two_voices(soprano, alto)
    print(f"エラー: {errors if errors else '検出なし'}\n")
    
    # テストケース2: 正しい対位法
    print("テスト2: 正しい対位法（反行）")
    soprano2 = Voice([
        Pitch(67, "G4"),  # G4
        Pitch(69, "A4"),  # A4
        Pitch(67, "G4"),  # G4
    ], name="ソプラノ")
    
    alto2 = Voice([
        Pitch(60, "C4"),  # C4
        Pitch(62, "D4"),  # D4
        Pitch(64, "E4"),  # E4
    ], name="アルト")
    
    errors = validator.validate_two_voices(soprano2, alto2)
    print(f"エラー: {errors if errors else '検出なし'}\n")
    
    # テストケース3: 大跳躍の検証
    print("テスト3: 大跳躍とその解決")
    voice_with_leap = Voice([
        Pitch(60, "C4"),  # C4
        Pitch(72, "C5"),  # C5 (1オクターブ上昇)
        Pitch(71, "B4"),  # B4 (順次下降で解決)
    ], name="メロディ")
    
    errors = validator.validate_single_voice(voice_with_leap)
    print(f"エラー: {errors if errors else '検出なし'}\n")
    
    print("対位法エンジンの基本機能のテスト完了")
