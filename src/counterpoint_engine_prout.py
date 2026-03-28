"""
対位法エンジン（包括的実装）
Counterpoint Engine - Comprehensive Implementation

厳格対位法の規則を体系的に定義・検証する。
harmony_rules_complete.Pitch を統一的に使用。
DP生成エンジン（voice_leading_fugue_gen.py）への統合を目的とする。

理論的根拠:
- Johann Joseph Fux: "Gradus ad Parnassum" (1725)
- Ebenezer Prout: "Counterpoint" (1890) / "Fugue" (1891)
- Kent Kennan: "Counterpoint" (4th edition, 1999)
- Walter Piston: "Counterpoint" (1947)

規則の階層:
  Layer 1 - 禁則（CounterpointProhibitions）: 絶対禁止。DP の _check_transition で使用。
  Layer 2 - 推奨（CounterpointScoring）: スコアリング。DP の _score_transition で使用。
  Layer 3 - 種別対位法（SpeciesCounterpointRules）: 拍細分化対応時に使用。
  Layer 4 - 転回対位法（InvertibleCounterpoint）: フーガ構造検証に使用。
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Set
from enum import Enum

# harmony_rules_complete.Pitch を統一使用
from harmony_rules_complete import Pitch


# ============================================================
# 基本定義
# ============================================================

class MotionType(Enum):
    """2声部間の動きの種類"""
    PARALLEL = "parallel"    # 平行: 同方向・同音程
    SIMILAR = "similar"      # 同進行: 同方向・異音程
    CONTRARY = "contrary"    # 反行: 反対方向
    OBLIQUE = "oblique"      # 斜行: 一方が保持


class DissonanceType(Enum):
    """非和声音の種類（将来の拍細分化で使用）"""
    PASSING_TONE = "passing_tone"        # 経過音
    NEIGHBOR_TONE = "neighbor_tone"      # 刺繍音（補助音）
    SUSPENSION = "suspension"            # 掛留音
    ANTICIPATION = "anticipation"        # 先取音
    APPOGGIATURA = "appoggiatura"        # 倚音
    ESCAPE_TONE = "escape_tone"          # 逸音
    PEDAL_TONE = "pedal_tone"            # 保続音


class SpeciesType(Enum):
    """種別対位法の種類"""
    FIRST = 1    # 1:1 全音符対全音符
    SECOND = 2   # 2:1 2分音符対全音符
    THIRD = 3    # 4:1 4分音符対全音符
    FOURTH = 4   # 掛留音（切分音）
    FIFTH = 5    # 華麗対位法（混合）


# ============================================================
# 旋律的文脈: 声部の履歴追跡
# ============================================================

@dataclass
class MelodicContext:
    """声部の旋律的文脈（直近の履歴を保持）"""
    pitches: List[int] = field(default_factory=list)
    max_history: int = 12

    def add(self, midi_val: int):
        self.pitches.append(midi_val)
        if len(self.pitches) > self.max_history:
            self.pitches = self.pitches[-self.max_history:]

    @property
    def last(self) -> Optional[int]:
        return self.pitches[-1] if self.pitches else None

    @property
    def direction_sequence(self) -> List[int]:
        dirs = []
        for i in range(len(self.pitches) - 1):
            diff = self.pitches[i + 1] - self.pitches[i]
            dirs.append(1 if diff > 0 else (-1 if diff < 0 else 0))
        return dirs

    def consecutive_same_direction(self) -> int:
        dirs = self.direction_sequence
        if not dirs:
            return 0
        last_dir = dirs[-1]
        if last_dir == 0:
            return 0
        count = 0
        for d in reversed(dirs):
            if d == last_dir:
                count += 1
            else:
                break
        return count

    @property
    def highest(self) -> Optional[int]:
        return max(self.pitches) if self.pitches else None

    @property
    def lowest(self) -> Optional[int]:
        return min(self.pitches) if self.pitches else None

    def clone(self) -> 'MelodicContext':
        return MelodicContext(pitches=list(self.pitches),
                              max_history=self.max_history)


# ============================================================
# Layer 1: 禁則（Hard Constraints）
# ============================================================

class CounterpointProhibitions:
    """対位法の絶対禁則

    Prout "Counterpoint" Ch.III-V, Fux "Gradus" Ex.I-III
    """

    @staticmethod
    def classify_motion(v1_prev: int, v1_curr: int,
                        v2_prev: int, v2_curr: int) -> MotionType:
        m1 = v1_curr - v1_prev
        m2 = v2_curr - v2_prev

        if m1 == 0 or m2 == 0:
            return MotionType.OBLIQUE
        if (m1 > 0 and m2 < 0) or (m1 < 0 and m2 > 0):
            return MotionType.CONTRARY
        prev_ic = abs(v1_prev - v2_prev) % 12
        curr_ic = abs(v1_curr - v2_curr) % 12
        if prev_ic == curr_ic:
            return MotionType.PARALLEL
        return MotionType.SIMILAR

    @staticmethod
    def check_parallel_perfect(v1_prev: int, v1_curr: int,
                               v2_prev: int, v2_curr: int) -> Tuple[bool, str]:
        """平行5度・8度の禁止（Prout "Counterpoint" Ch.III §7-12）"""
        m1 = v1_curr - v1_prev
        m2 = v2_curr - v2_prev
        if m1 == 0 or m2 == 0:
            return True, ""
        if (m1 > 0 and m2 < 0) or (m1 < 0 and m2 > 0):
            return True, ""
        prev_ic = abs(v1_prev - v2_prev) % 12
        curr_ic = abs(v1_curr - v2_curr) % 12
        if prev_ic in (0, 7) and prev_ic == curr_ic:
            name = "同度/8度" if prev_ic == 0 else "5度"
            return False, f"平行{name}"
        return True, ""

    @staticmethod
    def check_hidden_perfect(soprano_prev: int, soprano_curr: int,
                             bass_prev: int, bass_curr: int,
                             is_outer_voices: bool) -> Tuple[bool, str]:
        """隠伏5度・8度の禁止（Prout "Counterpoint" Ch.III §13-18）"""
        if not is_outer_voices:
            return True, ""
        m_s = soprano_curr - soprano_prev
        m_b = bass_curr - bass_prev
        if m_s == 0 or m_b == 0:
            return True, ""
        if not ((m_s > 0 and m_b > 0) or (m_s < 0 and m_b < 0)):
            return True, ""
        curr_ic = abs(soprano_curr - bass_curr) % 12
        if curr_ic not in (0, 7):
            return True, ""
        if abs(m_s) > 2:
            name = "同度/8度" if curr_ic == 0 else "5度"
            return False, f"隠伏{name}（ソプラノが跳躍）"
        return True, ""

    @staticmethod
    def check_direct_unison(v1_prev: int, v1_curr: int,
                            v2_prev: int, v2_curr: int) -> Tuple[bool, str]:
        """直接同度の禁止"""
        m1 = v1_curr - v1_prev
        m2 = v2_curr - v2_prev
        if m1 == 0 or m2 == 0:
            return True, ""
        if not ((m1 > 0 and m2 > 0) or (m1 < 0 and m2 < 0)):
            return True, ""
        if v1_curr == v2_curr:
            return False, "直接同度（同方向からユニゾンに到達）"
        return True, ""

    @staticmethod
    def check_voice_overlap(upper_prev: int, upper_curr: int,
                            lower_prev: int, lower_curr: int) -> Tuple[bool, str]:
        """声部超越の禁止（Prout "Counterpoint" Ch.IV §3）"""
        if lower_curr > upper_prev:
            return False, "声部超越（下声が上声の前の音を超過）"
        if upper_curr < lower_prev:
            return False, "声部超越（上声が下声の前の音を下回る）"
        return True, ""

    @staticmethod
    def check_melodic_augmented(prev_midi: int, curr_midi: int) -> Tuple[bool, str]:
        """増音程の旋律的使用禁止（Prout "Counterpoint" Ch.II §5）"""
        interval = abs(curr_midi - prev_midi)
        if interval == 6:
            return False, "増4度（三全音）の旋律的使用"
        if interval == 8:
            return False, "増5度の旋律的使用"
        return True, ""

    @staticmethod
    def check_melodic_seventh(prev_midi: int, curr_midi: int) -> Tuple[bool, str]:
        """7度跳躍の禁止"""
        interval = abs(curr_midi - prev_midi)
        if interval == 10:
            return False, "短7度の旋律的跳躍"
        if interval == 11:
            return False, "長7度の旋律的跳躍"
        return True, ""

    @staticmethod
    def check_consecutive_leaps_same_dir(
        ctx: MelodicContext, new_midi: int,
        max_consecutive: int = 2
    ) -> Tuple[bool, str]:
        """同方向の連続跳躍制限"""
        if len(ctx.pitches) < max_consecutive:
            return True, ""
        prev = ctx.pitches[-1]
        new_leap = new_midi - prev
        if abs(new_leap) < 3:
            return True, ""
        leaps = []
        for i in range(len(ctx.pitches) - 1,
                       max(0, len(ctx.pitches) - max_consecutive) - 1, -1):
            if i > 0:
                leap = ctx.pitches[i] - ctx.pitches[i - 1]
                leaps.append(leap)
        leaps.insert(0, new_leap)
        if len(leaps) < max_consecutive + 1:
            return True, ""
        target = leaps[:max_consecutive + 1]
        all_same_dir = all(
            (l > 0 and abs(l) >= 3) for l in target
        ) or all(
            (l < 0 and abs(l) >= 3) for l in target
        )
        if all_same_dir:
            return False, f"同方向の連続跳躍が{max_consecutive + 1}回"
        return True, ""


# ============================================================
# Layer 2: 推奨規則（Soft Constraints / Scoring）
# ============================================================

class CounterpointScoring:
    """対位法の推奨規則（Prout "Counterpoint" Ch.II, V）"""

    @staticmethod
    def score_motion_type(v1_prev: int, v1_curr: int,
                          v2_prev: int, v2_curr: int) -> float:
        motion = CounterpointProhibitions.classify_motion(
            v1_prev, v1_curr, v2_prev, v2_curr
        )
        return {
            MotionType.CONTRARY: -2.0,
            MotionType.OBLIQUE:  -1.0,
            MotionType.SIMILAR:   0.0,
            MotionType.PARALLEL:  1.0,
        }[motion]

    @staticmethod
    def score_leap_resolution(ctx: MelodicContext, new_midi: int) -> float:
        """跳躍後の解決（Prout "Counterpoint" Ch.II §8-12）"""
        if len(ctx.pitches) < 2:
            return 0.0
        prev = ctx.pitches[-1]
        prev2 = ctx.pitches[-2]
        leap = prev - prev2
        resolution = new_midi - prev
        if abs(leap) < 3:
            return 0.0
        if leap > 0 and resolution < 0 and abs(resolution) <= 2:
            return -2.0
        if leap < 0 and resolution > 0 and abs(resolution) <= 2:
            return -2.0
        if abs(leap) >= 9:
            if (leap > 0 and resolution >= 0) or (leap < 0 and resolution <= 0):
                return 5.0
        if (leap > 0 and resolution > 0) or (leap < 0 and resolution < 0):
            return 1.5
        return 0.0

    @staticmethod
    def score_consecutive_direction(ctx: MelodicContext, new_midi: int) -> float:
        if not ctx.pitches:
            return 0.0
        prev = ctx.pitches[-1]
        new_dir = 1 if new_midi > prev else (-1 if new_midi < prev else 0)
        if new_dir == 0:
            return 0.0
        dirs = ctx.direction_sequence
        if dirs and dirs[-1] == new_dir:
            count = ctx.consecutive_same_direction() + 1
        else:
            return -1.0
        if count >= 5:
            return 4.0
        elif count >= 4:
            return 2.0
        elif count >= 3:
            return 0.5
        return 0.0

    @staticmethod
    def score_melodic_variety(ctx: MelodicContext, new_midi: int) -> float:
        if not ctx.pitches:
            return 0.0
        repeat_count = 0
        for p in reversed(ctx.pitches):
            if p == new_midi:
                repeat_count += 1
            else:
                break
        if repeat_count >= 3:
            return 4.0
        elif repeat_count >= 2:
            return 2.0
        return 0.0

    @staticmethod
    def score_climax_uniqueness(ctx: MelodicContext, new_midi: int) -> float:
        if not ctx.pitches:
            return 0.0
        current_high = max(ctx.pitches)
        if new_midi > current_high:
            return -1.0
        elif new_midi == current_high:
            high_count = ctx.pitches.count(current_high)
            if high_count >= 2:
                return 2.0
            return 0.5
        return 0.0

    @staticmethod
    def score_voice_independence(voices_prev: List[int],
                                voices_curr: List[int]) -> float:
        n = min(len(voices_prev), len(voices_curr))
        if n < 2:
            return 0.0
        directions = []
        for i in range(n):
            diff = voices_curr[i] - voices_prev[i]
            directions.append(1 if diff > 0 else (-1 if diff < 0 else 0))
        non_zero = [d for d in directions if d != 0]
        if len(non_zero) >= 3 and all(d == non_zero[0] for d in non_zero):
            return 3.0
        unique_dirs = len(set(directions))
        if unique_dirs >= 3:
            return -2.0
        elif unique_dirs >= 2:
            return -0.5
        return 0.0

    @staticmethod
    def score_range_usage(ctx: MelodicContext,
                          voice_range: Tuple[int, int]) -> float:
        if len(ctx.pitches) < 4:
            return 0.0
        lo, hi = voice_range
        full_range = hi - lo
        used_range = (max(ctx.pitches) - min(ctx.pitches))
        ratio = used_range / full_range if full_range > 0 else 0
        if ratio < 0.2:
            return 2.0
        elif ratio < 0.3:
            return 0.5
        return 0.0


# ============================================================
# Layer 3: 種別対位法の規則
# ============================================================

class SpeciesCounterpointRules:
    """種別対位法（Fux/Prout）"""

    @staticmethod
    def first_species_check_interval(upper: int, lower: int,
                                     is_first: bool = False,
                                     is_last: bool = False) -> Tuple[bool, str]:
        ic = abs(upper - lower) % 12
        consonant_imperfect = {3, 4, 8, 9}
        consonant_perfect = {0, 7}
        if is_first or is_last:
            if ic not in consonant_perfect:
                return False, f"開始/終結は完全協和音程のみ（{ic}半音）"
            return True, ""
        if ic in consonant_imperfect or ic in consonant_perfect:
            if ic == 0:
                return False, "同度は開始・終結以外では禁止"
            return True, ""
        return False, f"不協和音程（{ic}半音）"

    @staticmethod
    def second_species_check_weak_beat(
        prev_strong: int, weak: int, next_strong: int,
        cantus_at_weak: int, chord_tones: Set[int],
    ) -> Tuple[bool, str]:
        weak_pc = weak % 12
        if weak_pc in chord_tones:
            return True, ""
        approach = weak - prev_strong
        departure = next_strong - weak
        if abs(approach) > 2:
            return False, "弱拍非和声音: 進入が跳躍"
        if abs(departure) > 2:
            return False, "弱拍非和声音: 退出が跳躍"
        return True, ""

    @staticmethod
    def fourth_species_check_suspension(
        preparation: int, suspension: int, resolution: int,
        cantus_at_suspension: int,
    ) -> Tuple[bool, str]:
        if preparation != suspension:
            return False, "掛留音: 準備音と掛留音が異なる"
        res_interval = resolution - suspension
        if abs(res_interval) > 2:
            return False, "掛留音: 解決が跳躍"
        if res_interval == 0:
            return False, "掛留音: 解決が同音（非解決）"
        sus_ic = abs(suspension - cantus_at_suspension) % 12
        dissonant = {1, 2, 5, 6, 10, 11}
        if sus_ic not in dissonant:
            return True, ""
        if res_interval < 0:
            return True, ""
        if res_interval > 0:
            if sus_ic in {1, 2, 5}:
                return True, ""
            return False, f"下声掛留: 不適切な音程（{sus_ic}半音）"
        return True, ""

    @staticmethod
    def classify_nonchord_tone(
        prev: int, target: int, next_note: int,
        chord_tones: Set[int],
    ) -> Optional[DissonanceType]:
        target_pc = target % 12
        if target_pc in chord_tones:
            return None
        approach = target - prev
        departure = next_note - target
        if abs(approach) <= 2 and abs(departure) <= 2:
            if (approach > 0 and departure > 0) or (approach < 0 and departure < 0):
                return DissonanceType.PASSING_TONE
        if abs(approach) <= 2 and abs(departure) <= 2:
            if (approach > 0 and departure < 0) or (approach < 0 and departure > 0):
                return DissonanceType.NEIGHBOR_TONE
        if abs(approach) <= 2 and abs(departure) > 2:
            return DissonanceType.ESCAPE_TONE
        if abs(approach) > 2 and abs(departure) <= 2:
            return DissonanceType.APPOGGIATURA
        next_pc = next_note % 12
        if target_pc == next_pc:
            return DissonanceType.ANTICIPATION
        return None


# ============================================================
# Layer 4: 転回対位法（Invertible Counterpoint）
# ============================================================

class InvertibleCounterpoint:
    """転回対位法の検証（Prout "Fugue" Ch.V）"""

    @staticmethod
    def check_invertible_at_octave(
        upper_pitches: List[int],
        lower_pitches: List[int],
    ) -> Tuple[bool, List[str]]:
        if len(upper_pitches) != len(lower_pitches):
            return False, ["声部の長さが一致しない"]
        errors = []
        proh = CounterpointProhibitions()
        for i in range(len(upper_pitches)):
            inv_upper = lower_pitches[i] + 12
            inv_lower = upper_pitches[i]
            if inv_upper < inv_lower:
                errors.append(f"位置{i}: 転回後に声部交差")
                continue
            ic = abs(inv_upper - inv_lower) % 12
            if ic in {1, 2, 6, 10, 11}:
                errors.append(f"位置{i}: 転回後に不協和音程（{ic}半音）")
            if i > 0:
                prev_inv_upper = lower_pitches[i - 1] + 12
                prev_inv_lower = upper_pitches[i - 1]
                valid, msg = proh.check_parallel_perfect(
                    prev_inv_upper, inv_upper,
                    prev_inv_lower, inv_lower,
                )
                if not valid:
                    errors.append(f"位置{i}: 転回後の{msg}")
        return len(errors) == 0, errors

    @staticmethod
    def find_problematic_fifth(
        upper_pitches: List[int],
        lower_pitches: List[int],
    ) -> List[Tuple[int, str]]:
        problems = []
        for i in range(len(upper_pitches)):
            ic = abs(upper_pitches[i] - lower_pitches[i]) % 12
            if ic == 7:
                problems.append(
                    (i, "5度は転回すると4度（対位法上の不協和）")
                )
        return problems


# ============================================================
# 統合インターフェース
# ============================================================

class CounterpointEngine:
    """対位法エンジン統合クラス"""

    def __init__(self, num_voices: int = 4):
        self.prohibitions = CounterpointProhibitions()
        self.scoring = CounterpointScoring()
        self.species = SpeciesCounterpointRules()
        self.invertible = InvertibleCounterpoint()
        self.num_voices = num_voices
        self.contexts: List[MelodicContext] = [
            MelodicContext() for _ in range(num_voices)
        ]

    def reset(self):
        self.contexts = [
            MelodicContext() for _ in range(self.num_voices)
        ]

    def check_transition_hard(
        self, prev: Tuple[int, ...], curr: Tuple[int, ...],
    ) -> Tuple[bool, List[str]]:
        errors = []
        n = min(len(prev), len(curr))
        for i in range(n):
            for j in range(i + 1, n):
                valid, msg = self.prohibitions.check_parallel_perfect(
                    prev[i], curr[i], prev[j], curr[j]
                )
                if not valid:
                    errors.append(msg)
                is_outer = (i == 0 and j == n - 1)
                valid, msg = self.prohibitions.check_hidden_perfect(
                    prev[i], curr[i], prev[j], curr[j], is_outer
                )
                if not valid:
                    errors.append(msg)
            valid, msg = self.prohibitions.check_melodic_augmented(
                prev[i], curr[i]
            )
            if not valid:
                errors.append(msg)
            valid, msg = self.prohibitions.check_melodic_seventh(
                prev[i], curr[i]
            )
            if not valid:
                errors.append(msg)
        for i in range(n - 1):
            valid, msg = self.prohibitions.check_voice_overlap(
                prev[i], curr[i], prev[i + 1], curr[i + 1]
            )
            if not valid:
                errors.append(msg)
        return len(errors) == 0, errors

    def score_transition_soft(
        self, prev: Tuple[int, ...], curr: Tuple[int, ...],
        voice_ranges: Optional[List[Tuple[int, int]]] = None,
    ) -> float:
        score = 0.0
        n = min(len(prev), len(curr))
        score += self.scoring.score_voice_independence(
            list(prev), list(curr)
        )
        for i in range(n):
            for j in range(i + 1, n):
                score += self.scoring.score_motion_type(
                    prev[i], curr[i], prev[j], curr[j]
                ) * 0.3
        for k in range(n):
            ctx = self.contexts[k]
            score += self.scoring.score_leap_resolution(ctx, curr[k]) * 0.5
            score += self.scoring.score_consecutive_direction(ctx, curr[k]) * 0.5
            score += self.scoring.score_melodic_variety(ctx, curr[k]) * 0.3
            score += self.scoring.score_climax_uniqueness(ctx, curr[k]) * 0.2
            if voice_ranges and k < len(voice_ranges):
                score += self.scoring.score_range_usage(ctx, voice_ranges[k]) * 0.2
        return score

    def update_contexts(self, voicing: Tuple[int, ...]):
        for k in range(min(len(voicing), self.num_voices)):
            self.contexts[k].add(voicing[k])
