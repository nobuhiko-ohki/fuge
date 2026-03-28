"""
対位法エンジン（包括的実装）
Counterpoint Engine - Comprehensive Implementation

厳格対位法の規則を体系的に定義・検証する。
harmony_rules_complete.Pitch を統一的に使用。
DP生成エンジン（voice_leading_fugue_gen.py）への統合を目的とする。

理論的根拠:
- Johann Joseph Fux: "Gradus ad Parnassum" (1725)
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
    """声部の旋律的文脈（直近の履歴を保持）

    DP生成時に各声部の履歴を追跡し、
    連続同方向・クライマックス・反復などを判定する。
    """
    pitches: List[int] = field(default_factory=list)
    max_history: int = 12

    def add(self, midi_val: int):
        """MIDI値を追加"""
        self.pitches.append(midi_val)
        if len(self.pitches) > self.max_history:
            self.pitches = self.pitches[-self.max_history:]

    @property
    def last(self) -> Optional[int]:
        return self.pitches[-1] if self.pitches else None

    @property
    def direction_sequence(self) -> List[int]:
        """連続する動きの方向列 (+1=上行, 0=保持, -1=下行)"""
        dirs = []
        for i in range(len(self.pitches) - 1):
            diff = self.pitches[i + 1] - self.pitches[i]
            dirs.append(1 if diff > 0 else (-1 if diff < 0 else 0))
        return dirs

    def consecutive_same_direction(self) -> int:
        """末尾からの連続同方向動きの回数"""
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
        """浅いコピーを作成（DP分岐用）"""
        return MelodicContext(pitches=list(self.pitches),
                              max_history=self.max_history)


# ============================================================
# Layer 1: 禁則（Hard Constraints）
# ============================================================

class CounterpointProhibitions:
    """対位法の絶対禁則

    DP生成エンジンの _check_transition で使用。
    違反した遷移は候補から完全に排除される。
    """

    @staticmethod
    def classify_motion(v1_prev: int, v1_curr: int,
                        v2_prev: int, v2_curr: int) -> MotionType:
        """2声部間の動きの種類を判定

        Args:
            v1_prev, v1_curr: 声部1の前→現在のMIDI値
            v2_prev, v2_curr: 声部2の前→現在のMIDI値
        """
        m1 = v1_curr - v1_prev
        m2 = v2_curr - v2_prev

        if m1 == 0 or m2 == 0:
            return MotionType.OBLIQUE

        if (m1 > 0 and m2 < 0) or (m1 < 0 and m2 > 0):
            return MotionType.CONTRARY

        # 同方向: 平行 or 同進行
        prev_ic = abs(v1_prev - v2_prev) % 12
        curr_ic = abs(v1_curr - v2_curr) % 12
        if prev_ic == curr_ic:
            return MotionType.PARALLEL

        return MotionType.SIMILAR

    # ---- 平行完全協和音程の禁止 ----

    @staticmethod
    def check_parallel_perfect(v1_prev: int, v1_curr: int,
                               v2_prev: int, v2_curr: int) -> Tuple[bool, str]:
        """平行5度・8度（同度含む）の禁止

        Fux/Piston: 2声部が同方向に動いて前後とも同じ完全協和音程を形成する場合、
        これは最も重大な禁則である。
        """
        m1 = v1_curr - v1_prev
        m2 = v2_curr - v2_prev

        # 両方静止 or 片方静止: 平行ではない
        if m1 == 0 or m2 == 0:
            return True, ""
        # 反行: 平行ではない
        if (m1 > 0 and m2 < 0) or (m1 < 0 and m2 > 0):
            return True, ""

        prev_ic = abs(v1_prev - v2_prev) % 12
        curr_ic = abs(v1_curr - v2_curr) % 12

        if prev_ic in (0, 7) and prev_ic == curr_ic:
            name = "同度/8度" if prev_ic == 0 else "5度"
            return False, f"平行{name}"

        return True, ""

    # ---- 隠伏完全協和音程の禁止 ----

    @staticmethod
    def check_hidden_perfect(soprano_prev: int, soprano_curr: int,
                             bass_prev: int, bass_curr: int,
                             is_outer_voices: bool) -> Tuple[bool, str]:
        """隠伏5度・8度の禁止

        Piston: 外声部が同方向に動いて完全協和音程に到達する場合、
        ソプラノ（上声）は順次進行（半音または全音）でなければならない。
        内声部ペアではこの規則は緩和される。
        """
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

        # ソプラノが跳躍（3半音以上）
        if abs(m_s) > 2:
            name = "同度/8度" if curr_ic == 0 else "5度"
            return False, f"隠伏{name}（ソプラノが跳躍）"

        return True, ""

    # ---- 直接同度の禁止 ----

    @staticmethod
    def check_direct_unison(v1_prev: int, v1_curr: int,
                            v2_prev: int, v2_curr: int) -> Tuple[bool, str]:
        """直接同度の禁止

        Fux: 2声部が同方向に動いて同度（ユニゾン）に到達することは禁止。
        """
        m1 = v1_curr - v1_prev
        m2 = v2_curr - v2_prev

        if m1 == 0 or m2 == 0:
            return True, ""
        if not ((m1 > 0 and m2 > 0) or (m1 < 0 and m2 < 0)):
            return True, ""

        if v1_curr == v2_curr:
            return False, "直接同度（同方向からユニゾンに到達）"

        return True, ""

    # ---- 声部超越の禁止 ----

    @staticmethod
    def check_voice_overlap(upper_prev: int, upper_curr: int,
                            lower_prev: int, lower_curr: int) -> Tuple[bool, str]:
        """声部超越（voice overlap）の禁止

        Kennan: ある声部が、隣接声部の前の音を超えてはならない。
        例: アルトの現在の音がソプラノの前の音より高い場合、超越。
        """
        if lower_curr > upper_prev:
            return False, "声部超越（下声が上声の前の音を超過）"
        if upper_curr < lower_prev:
            return False, "声部超越（上声が下声の前の音を下回る）"
        return True, ""

    # ---- 増音程の旋律的使用禁止 ----

    @staticmethod
    def check_melodic_augmented(prev_midi: int, curr_midi: int) -> Tuple[bool, str]:
        """増音程の旋律的使用禁止

        Fux/Piston: 増4度（6半音=三全音）、増5度（8半音）の
        旋律的跳躍は禁止。
        """
        interval = abs(curr_midi - prev_midi)
        if interval == 6:
            return False, "増4度（三全音）の旋律的使用"
        if interval == 8:
            return False, "増5度の旋律的使用"
        return True, ""

    # ---- 7度跳躍の禁止 ----

    @staticmethod
    def check_melodic_seventh(prev_midi: int, curr_midi: int) -> Tuple[bool, str]:
        """7度跳躍の禁止

        Fux/Kennan: 短7度（10半音）・長7度（11半音）の旋律的跳躍は禁止。
        """
        interval = abs(curr_midi - prev_midi)
        if interval == 10:
            return False, "短7度の旋律的跳躍"
        if interval == 11:
            return False, "長7度の旋律的跳躍"
        return True, ""

    # ---- 連続跳躍の制限 ----

    @staticmethod
    def check_consecutive_leaps_same_dir(
        ctx: MelodicContext, new_midi: int,
        max_consecutive: int = 2
    ) -> Tuple[bool, str]:
        """同方向の連続跳躍制限

        Kennan: 同方向に3度以上の跳躍が3回以上連続するのは禁止。
        （分散和音の輪郭は例外だが、現段階では厳格に適用）
        """
        if len(ctx.pitches) < max_consecutive:
            return True, ""

        prev = ctx.pitches[-1]
        new_leap = new_midi - prev

        if abs(new_leap) < 3:
            return True, ""

        # 直前のmax_consecutive個の動きが全て同方向跳躍かチェック
        leaps = []
        for i in range(len(ctx.pitches) - 1,
                       max(0, len(ctx.pitches) - max_consecutive) - 1, -1):
            if i > 0:
                leap = ctx.pitches[i] - ctx.pitches[i - 1]
                leaps.append(leap)

        # 新しい跳躍を先頭に追加
        leaps.insert(0, new_leap)

        if len(leaps) < max_consecutive + 1:
            return True, ""

        # 最新の (max_consecutive+1) 個が全て同方向跳躍か
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
    """対位法の推奨規則（スコアリング）

    DP生成エンジンの _score_transition に加算。
    値が正ならペナルティ、負ならボーナス。
    """

    @staticmethod
    def score_motion_type(v1_prev: int, v1_curr: int,
                          v2_prev: int, v2_curr: int) -> float:
        """動きの種類によるスコアリング

        反行（contrary）が最も望ましい。
        斜行（oblique）も良い。
        平行（prohibited以外）は軽ペナルティ。
        """
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
        """跳躍後の解決のスコアリング

        Fux: 跳躍の後は反対方向への順次進行で解決すべき。
        特に大跳躍（6度以上=9半音以上）は必ず解決が必要。
        """
        if len(ctx.pitches) < 2:
            return 0.0

        prev = ctx.pitches[-1]
        prev2 = ctx.pitches[-2]
        leap = prev - prev2
        resolution = new_midi - prev

        if abs(leap) < 3:
            return 0.0  # 前回が跳躍でなければ評価なし

        # 反対方向への順次進行で解決
        if leap > 0 and resolution < 0 and abs(resolution) <= 2:
            return -2.0  # 適切な解決
        if leap < 0 and resolution > 0 and abs(resolution) <= 2:
            return -2.0  # 適切な解決

        # 大跳躍の未解決
        if abs(leap) >= 9:
            if (leap > 0 and resolution >= 0) or (leap < 0 and resolution <= 0):
                return 5.0  # 大ペナルティ

        # 通常跳躍の同方向継続
        if (leap > 0 and resolution > 0) or (leap < 0 and resolution < 0):
            return 1.5

        return 0.0

    @staticmethod
    def score_consecutive_direction(ctx: MelodicContext, new_midi: int) -> float:
        """連続同方向動きのペナルティ

        Kennan: 4回以上の連続同方向進行は旋律的に弱い。
        """
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
            return -1.0  # ボーナス: 方向転換

        if count >= 5:
            return 4.0
        elif count >= 4:
            return 2.0
        elif count >= 3:
            return 0.5

        return 0.0

    @staticmethod
    def score_melodic_variety(ctx: MelodicContext, new_midi: int) -> float:
        """旋律の多様性: 同音反復の回避

        3回以上の連続同音反復はペナルティ。
        """
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
        """クライマックスの唯一性

        Kennan: 各声部の最高音は理想的には曲中1回のみ。
        """
        if not ctx.pitches:
            return 0.0

        current_high = max(ctx.pitches)

        if new_midi > current_high:
            return -1.0  # 新しいクライマックス（更新）
        elif new_midi == current_high:
            high_count = ctx.pitches.count(current_high)
            if high_count >= 2:
                return 2.0
            return 0.5

        return 0.0

    @staticmethod
    def score_voice_independence(voices_prev: List[int],
                                voices_curr: List[int]) -> float:
        """声部独立性のスコア

        全声部が同方向に動くことを避ける。
        方向の多様性が高いほど良い。
        """
        n = min(len(voices_prev), len(voices_curr))
        if n < 2:
            return 0.0

        directions = []
        for i in range(n):
            diff = voices_curr[i] - voices_prev[i]
            directions.append(1 if diff > 0 else (-1 if diff < 0 else 0))

        non_zero = [d for d in directions if d != 0]
        if len(non_zero) >= 3 and all(d == non_zero[0] for d in non_zero):
            return 3.0  # 大ペナルティ: 全声部同方向

        unique_dirs = len(set(directions))
        if unique_dirs >= 3:
            return -2.0
        elif unique_dirs >= 2:
            return -0.5

        return 0.0

    @staticmethod
    def score_range_usage(ctx: MelodicContext,
                          voice_range: Tuple[int, int]) -> float:
        """音域利用の評価

        声部が音域の広い範囲を活用していることを評価する。
        音域の利用幅が小さすぎるとペナルティ。
        """
        if len(ctx.pitches) < 4:
            return 0.0

        lo, hi = voice_range
        full_range = hi - lo
        used_range = (max(ctx.pitches) - min(ctx.pitches))

        # 利用率
        ratio = used_range / full_range if full_range > 0 else 0

        if ratio < 0.2:
            return 2.0   # 音域の20%未満しか使っていない
        elif ratio < 0.3:
            return 0.5

        return 0.0


# ============================================================
# Layer 3: 種別対位法の規則
# ============================================================

class SpeciesCounterpointRules:
    """種別対位法の規則定義

    現在のDP生成エンジンは和音単位（1:1=1種相当）で動作する。
    将来の拍細分化（経過音・掛留音の導入）に備えて規則を形式化する。
    """

    # ---- 1種対位法: 垂直音程 ----

    @staticmethod
    def first_species_check_interval(upper: int, lower: int,
                                     is_first: bool = False,
                                     is_last: bool = False) -> Tuple[bool, str]:
        """1種: 垂直音程の判定

        Fux:
        - 使用可能: 長短3度、完全5度、長短6度、完全8度
        - 開始と終結: 完全協和音程（同度、5度、8度）のみ
        - 同度は開始・終結以外では禁止
        """
        ic = abs(upper - lower) % 12

        consonant_imperfect = {3, 4, 8, 9}  # 短3, 長3, 短6, 長6
        consonant_perfect = {0, 7}           # 同度/8度, 5度

        if is_first or is_last:
            if ic not in consonant_perfect:
                return False, f"開始/終結は完全協和音程のみ（{ic}半音）"
            return True, ""

        if ic in consonant_imperfect or ic in consonant_perfect:
            if ic == 0:
                return False, "同度は開始・終結以外では禁止"
            return True, ""

        return False, f"不協和音程（{ic}半音）"

    # ---- 2種対位法: 弱拍の扱い ----

    @staticmethod
    def second_species_check_weak_beat(
        prev_strong: int,
        weak: int,
        next_strong: int,
        cantus_at_weak: int,
        chord_tones: Set[int],
    ) -> Tuple[bool, str]:
        """2種: 弱拍の音の判定

        Fux:
        - 弱拍で和音構成音 → 常にOK
        - 弱拍で非和声音 → 経過音として許容:
          条件: 順次進行で進入し、同方向に順次進行で退出
        - 刺繍音（neighbor tone）も許容:
          条件: 順次進行で進入し、反対方向に順次進行で退出（元の音に戻る）
        """
        weak_pc = weak % 12

        if weak_pc in chord_tones:
            return True, ""

        approach = weak - prev_strong
        departure = next_strong - weak

        # 進入・退出とも順次進行（1-2半音）
        if abs(approach) > 2:
            return False, "弱拍非和声音: 進入が跳躍"
        if abs(departure) > 2:
            return False, "弱拍非和声音: 退出が跳躍"

        # 同方向 → 経過音、反対方向 → 刺繍音
        return True, ""

    # ---- 4種対位法: 掛留音 ----

    @staticmethod
    def fourth_species_check_suspension(
        preparation: int,
        suspension: int,
        resolution: int,
        cantus_at_suspension: int,
    ) -> Tuple[bool, str]:
        """4種: 掛留音（suspension）の判定

        Fux:
        1. 準備（Preparation）: 弱拍で協和音として導入
        2. 掛留（Suspension）: 準備音を強拍に繋留、不協和音を形成
        3. 解決（Resolution）: 順次下行（上声）または順次上行（下声）

        有効な掛留（上声）: 7-6, 4-3, 9-8 → 下行解決
        有効な掛留（下声）: 2-3, 4-5 → 上行解決
        """
        # 条件1: 準備=掛留（同音保持）
        if preparation != suspension:
            return False, "掛留音: 準備音と掛留音が異なる"

        # 条件2: 解決は順次進行
        res_interval = resolution - suspension
        if abs(res_interval) > 2:
            return False, "掛留音: 解決が跳躍"
        if res_interval == 0:
            return False, "掛留音: 解決が同音（非解決）"

        # 掛留時の音程
        sus_ic = abs(suspension - cantus_at_suspension) % 12

        # 不協和音程でなければ掛留ではない（ただし「協和掛留」も理論上存在）
        dissonant = {1, 2, 5, 6, 10, 11}
        if sus_ic not in dissonant:
            # 協和音上の掛留: 技法として存在するが典型ではない
            return True, ""

        # 上声掛留: 下行解決
        if res_interval < 0:
            return True, ""

        # 下声掛留: 上行解決
        if res_interval > 0:
            if sus_ic in {1, 2, 5}:  # 2度 or 4度
                return True, ""
            return False, f"下声掛留: 不適切な音程（{sus_ic}半音）"

        return True, ""

    # ---- 2種・3種: 非和声音の分類 ----

    @staticmethod
    def classify_nonchord_tone(
        prev: int, target: int, next_note: int,
        chord_tones: Set[int],
    ) -> Optional[DissonanceType]:
        """非和声音の種類を判定

        Returns:
            DissonanceType または None（和声音の場合）
        """
        target_pc = target % 12
        if target_pc in chord_tones:
            return None

        approach = target - prev
        departure = next_note - target

        # 経過音: 順次進入・同方向順次退出
        if abs(approach) <= 2 and abs(departure) <= 2:
            if (approach > 0 and departure > 0) or (approach < 0 and departure < 0):
                return DissonanceType.PASSING_TONE

        # 刺繍音: 順次進入・反対方向順次退出（元の音に戻る）
        if abs(approach) <= 2 and abs(departure) <= 2:
            if (approach > 0 and departure < 0) or (approach < 0 and departure > 0):
                return DissonanceType.NEIGHBOR_TONE

        # 逸音: 順次進入・跳躍退出
        if abs(approach) <= 2 and abs(departure) > 2:
            return DissonanceType.ESCAPE_TONE

        # 倚音: 跳躍進入・順次退出
        if abs(approach) > 2 and abs(departure) <= 2:
            return DissonanceType.APPOGGIATURA

        # 先取音: 和音構成音と同じ音を事前に出す
        next_pc = next_note % 12
        if target_pc == next_pc:
            return DissonanceType.ANTICIPATION

        return None  # 分類不能


# ============================================================
# Layer 4: 転回対位法（Invertible Counterpoint）
# ============================================================

class InvertibleCounterpoint:
    """転回対位法の検証

    フーガで主題と対主題の上下を入れ替えても成立するか検証する。
    """

    @staticmethod
    def check_invertible_at_octave(
        upper_pitches: List[int],
        lower_pitches: List[int],
    ) -> Tuple[bool, List[str]]:
        """オクターブ転回対位法の検証

        2声部を上下入れ替えた時に禁則が生じないか確認。

        転回時の音程変化:
        - 3度 ↔ 6度（安全）
        - 同度 ↔ 8度（安全）
        - 5度 → 4度（要注意: 4度は不協和と扱われることがある）
        - 2度 ↔ 7度（不協和同士 → 非和声音処理が必要）
        """
        if len(upper_pitches) != len(lower_pitches):
            return False, ["声部の長さが一致しない"]

        errors = []
        proh = CounterpointProhibitions()

        for i in range(len(upper_pitches)):
            inv_upper = lower_pitches[i] + 12
            inv_lower = upper_pitches[i]

            # 交差チェック
            if inv_upper < inv_lower:
                errors.append(f"位置{i}: 転回後に声部交差")
                continue

            ic = abs(inv_upper - inv_lower) % 12
            if ic in {1, 2, 6, 10, 11}:
                errors.append(f"位置{i}: 転回後に不協和音程（{ic}半音）")

            # 転回後の平行禁則
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
        """転回で問題となる5度の位置を特定

        5度（7半音）は転回すると4度になり、対位法上で問題となりうる。
        """
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
    """対位法エンジン統合クラス

    DP生成エンジン（VoiceLeadingGenerator）から呼び出す
    統一的インターフェースを提供する。

    使用方法:
        engine = CounterpointEngine(num_voices=4)
        engine.reset()

        # DP の _check_transition 内で:
        valid, errors = engine.check_transition_hard(prev_voicing, curr_voicing)

        # DP の _score_transition 内で:
        score = engine.score_transition_soft(prev_voicing, curr_voicing, ranges)

        # 配置確定後:
        engine.update_contexts(chosen_voicing)
    """

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
        """文脈をリセット（新規生成の開始時に呼ぶ）"""
        self.contexts = [
            MelodicContext() for _ in range(self.num_voices)
        ]

    # ---- DP統合: ハード制約 ----

    def check_transition_hard(
        self, prev: Tuple[int, ...], curr: Tuple[int, ...],
    ) -> Tuple[bool, List[str]]:
        """遷移のハード制約チェック

        Args:
            prev: 前の配置 (S, A, T, B) の MIDI 値
            curr: 現在の配置

        Returns:
            (is_valid, error_messages)
        """
        errors = []
        n = min(len(prev), len(curr))

        for i in range(n):
            for j in range(i + 1, n):
                # 平行5度・8度
                valid, msg = self.prohibitions.check_parallel_perfect(
                    prev[i], curr[i], prev[j], curr[j]
                )
                if not valid:
                    errors.append(msg)

                # 隠伏5度・8度（外声部のみ）
                is_outer = (i == 0 and j == n - 1)
                valid, msg = self.prohibitions.check_hidden_perfect(
                    prev[i], curr[i], prev[j], curr[j], is_outer
                )
                if not valid:
                    errors.append(msg)

            # 増音程
            valid, msg = self.prohibitions.check_melodic_augmented(
                prev[i], curr[i]
            )
            if not valid:
                errors.append(msg)

            # 7度跳躍
            valid, msg = self.prohibitions.check_melodic_seventh(
                prev[i], curr[i]
            )
            if not valid:
                errors.append(msg)

        # 声部超越（隣接声部ペア）
        for i in range(n - 1):
            valid, msg = self.prohibitions.check_voice_overlap(
                prev[i], curr[i], prev[i + 1], curr[i + 1]
            )
            if not valid:
                errors.append(msg)

        return len(errors) == 0, errors

    # ---- DP統合: ソフト制約 ----

    def score_transition_soft(
        self, prev: Tuple[int, ...], curr: Tuple[int, ...],
        voice_ranges: Optional[List[Tuple[int, int]]] = None,
    ) -> float:
        """遷移のソフトスコアリング

        Args:
            prev: 前の配置
            curr: 現在の配置
            voice_ranges: 各声部の音域 [(lo, hi), ...]

        Returns:
            スコア（低いほど良い）
        """
        score = 0.0
        n = min(len(prev), len(curr))

        # 声部独立性
        score += self.scoring.score_voice_independence(
            list(prev), list(curr)
        )

        # 声部ペアの動きの種類
        for i in range(n):
            for j in range(i + 1, n):
                score += self.scoring.score_motion_type(
                    prev[i], curr[i], prev[j], curr[j]
                ) * 0.3

        # 各声部の旋律的品質
        for k in range(n):
            ctx = self.contexts[k]
            score += self.scoring.score_leap_resolution(ctx, curr[k]) * 0.5
            score += self.scoring.score_consecutive_direction(ctx, curr[k]) * 0.5
            score += self.scoring.score_melodic_variety(ctx, curr[k]) * 0.3
            score += self.scoring.score_climax_uniqueness(ctx, curr[k]) * 0.2
            if voice_ranges and k < len(voice_ranges):
                score += self.scoring.score_range_usage(ctx, voice_ranges[k]) * 0.2

        return score

    # ---- 文脈更新 ----

    def update_contexts(self, voicing: Tuple[int, ...]):
        """声部の旋律的文脈を更新（配置確定後に呼ぶ）"""
        for k in range(min(len(voicing), self.num_voices)):
            self.contexts[k].add(voicing[k])


# ============================================================
# 使用例
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("対位法エンジン（包括的実装）テスト")
    print("=" * 60)

    proh = CounterpointProhibitions()

    # 平行5度テスト
    valid, msg = proh.check_parallel_perfect(67, 69, 60, 62)
    print(f"\n平行5度: valid={valid}, msg='{msg}'")
    assert not valid, "平行5度が検出されるべき"

    # 隠伏8度テスト
    valid, msg = proh.check_hidden_perfect(60, 72, 48, 60, True)
    print(f"隠伏8度: valid={valid}, msg='{msg}'")
    assert not valid, "隠伏8度が検出されるべき"

    # 7度跳躍テスト
    valid, msg = proh.check_melodic_seventh(60, 71)
    print(f"長7度跳躍: valid={valid}, msg='{msg}'")
    assert not valid, "長7度跳躍が検出されるべき"

    # 声部超越テスト
    valid, msg = proh.check_voice_overlap(67, 65, 60, 68)
    print(f"声部超越: valid={valid}, msg='{msg}'")
    assert not valid, "声部超越が検出されるべき"

    # 増4度テスト
    valid, msg = proh.check_melodic_augmented(60, 66)
    print(f"増4度: valid={valid}, msg='{msg}'")
    assert not valid, "増4度が検出されるべき"

    # 直接同度テスト
    valid, msg = proh.check_direct_unison(65, 67, 60, 67)
    print(f"直接同度: valid={valid}, msg='{msg}'")
    assert not valid, "直接同度が検出されるべき"

    # --- スコアリングテスト ---
    scoring = CounterpointScoring()

    score1 = scoring.score_voice_independence(
        [72, 67, 60, 48], [74, 65, 62, 46]
    )
    print(f"\n声部独立性（反行あり）: {score1}")

    score2 = scoring.score_voice_independence(
        [72, 67, 60, 48], [74, 69, 62, 50]
    )
    print(f"声部独立性（全声部上行）: {score2}")

    # --- 種別対位法テスト ---
    species = SpeciesCounterpointRules()

    valid, msg = species.fourth_species_check_suspension(
        preparation=67, suspension=67, resolution=65,
        cantus_at_suspension=60,
    )
    print(f"\n掛留音（7-6）: valid={valid}, msg='{msg}'")

    valid, msg = species.first_species_check_interval(
        upper=67, lower=60, is_first=True
    )
    print(f"1種・開始（5度）: valid={valid}, msg='{msg}'")

    valid, msg = species.first_species_check_interval(
        upper=67, lower=60, is_first=False
    )
    print(f"1種・中間（5度）: valid={valid}, msg='{msg}'")

    # --- 転回対位法テスト ---
    inv = InvertibleCounterpoint()
    upper = [72, 71, 69, 67]
    lower = [60, 62, 64, 65]
    valid, errs = inv.check_invertible_at_octave(upper, lower)
    print(f"\n転回対位法: valid={valid}")
    if errs:
        for e in errs:
            print(f"  {e}")

    # --- 統合テスト ---
    engine = CounterpointEngine(num_voices=4)
    engine.reset()

    prev_v = (72, 67, 60, 48)
    curr_v = (74, 69, 62, 50)

    valid, errs = engine.check_transition_hard(prev_v, curr_v)
    print(f"\n統合ハード制約: valid={valid}")
    if errs:
        for e in errs:
            print(f"  {e}")

    s = engine.score_transition_soft(prev_v, curr_v,
                                     [(60, 79), (55, 74), (48, 67), (40, 60)])
    print(f"統合ソフトスコア: {s:.2f}")

    print("\n✓ 対位法エンジンテスト完了")
