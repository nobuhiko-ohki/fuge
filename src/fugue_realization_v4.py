"""
フーガ実現エンジン
Fugue Realization Engine

設計方針（合意事項）:
  1. 主題の各拍から暗示和声を分析する
  2. 基本パターン＋制御されたランダム化で和声進行を決定する
  3. 各拍の和声音から候補を生成し、和声学の禁則で絞る
  4. 対位法規則に基づくDPで最適な声部進行を選ぶ
  5. 将来のML層が和声選択の確率分布を調整する接続口を持つ

処理の流れ:
  SubjectHarmonicAnalyzer  → 主題の各拍に和音を割り当て
  HarmonicPlan             → 提示部全体の和声骨格
  ContrapuntalDP           → 和声音ベースの単声部DP
  FugueRealizationEngine   → 提示部の全声部を統合しMIDI出力
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Set
from enum import Enum
import random

from harmony_rules_complete import Pitch, NoteEvent, HarmonyRules
from counterpoint_engine import (
    CounterpointProhibitions,
    CounterpointScoring,
    InvertibleCounterpoint,
    MelodicContext,
    MotionType,
)
from fugue_structure import (
    Key, Subject, FugueStructure, FugueEntry,
    FugueVoiceType, Codetta,
)
from midi_writer import MIDIWriter


# ============================================================
# 声部音域定義（Piston p.17）
# ============================================================

VOICE_RANGES: Dict[FugueVoiceType, Tuple[int, int]] = {
    FugueVoiceType.SOPRANO: (60, 79),  # C4 - G5
    FugueVoiceType.ALTO:    (55, 74),  # G3 - D5
    FugueVoiceType.TENOR:   (48, 67),  # C3 - G4
    FugueVoiceType.BASS:    (40, 60),  # E2 - C4
}


# ============================================================
# 和声記号
# ============================================================

@dataclass
class ChordLabel:
    """拍ごとの和声割り当て"""
    degree: int           # 音階度数（0-based: 0=I, 1=ii, ..., 6=vii°）
    root_pc: int          # 根音ピッチクラス
    quality: str          # "major", "minor", "diminished", "dominant7", "minor7" 等
    tones: Set[int]       # 構成音のピッチクラス集合（3音 or 4音）
    is_secondary: bool = False  # 代理和音かどうか

    # Phase 1: 七の和音
    has_seventh: bool = False              # 七の和音か
    seventh_pc: Optional[int] = None       # 第七音のPC（解決追跡用）

    # Phase 2: 副属七和音
    is_secondary_dominant: bool = False    # V7/X かどうか
    resolution_target_pc: Optional[int] = None  # 解決先の根音PC

    # Phase 3: 変化和音
    alteration_type: Optional[str] = None  # "neapolitan", "italian", "german", "french"

    @property
    def roman(self) -> str:
        """ローマ数字表記"""
        if self.alteration_type == "neapolitan":
            return "♭II6"
        if self.alteration_type in ("italian", "german", "french"):
            type_label = {"italian": "It", "german": "Ger", "french": "Fr"}
            return f"{type_label[self.alteration_type]}+6"

        names = ["I", "ii", "iii", "IV", "V", "vi", "vii°"]
        base = names[self.degree] if 0 <= self.degree <= 6 else "?"

        if self.is_secondary_dominant:
            # V7/X 表記: 解決先の度数を表示
            base = base.upper()
        if self.has_seventh:
            base += "7"
        return base


# ============================================================
# 主題和声分析
# ============================================================

class SubjectHarmonicAnalyzer:
    """主題の各拍に和声を割り当てる

    手順:
    1. 調の全ダイアトニック三和音を構築
    2. 各拍の主題音を含む和音を候補として列挙
    3. 基本進行パターン（T→S→D→T）に沿って選択
    4. 代理和音で変化を付加（制御されたランダム化）

    将来のML統合点:
      select_chord() の確率分布をMLモデルが提供する
    """

    # 基本4パターンの和声機能
    FUNCTION_T = {0, 5}     # I, vi  （トニック機能）
    FUNCTION_S = {1, 3}     # ii, IV （サブドミナント機能）
    FUNCTION_D = {4, 6}     # V, vii°（ドミナント機能）
    FUNCTION_III = {2}      # iii    （T/D両義的）

    def __init__(self, key: Key, seed: Optional[int] = None,
                 seventh_freq: float = 0.15,
                 secondary_dom_freq: float = 0.10,
                 altered_freq: float = 0.05):
        self.key = key
        self.scale = key.scale
        self.rules = HarmonyRules()
        self.rng = random.Random(seed)

        # 頻度パラメータ
        self.seventh_freq = seventh_freq
        self.secondary_dom_freq = secondary_dom_freq
        self.altered_freq = altered_freq

        # ダイアトニック三和音を構築
        self.diatonic_chords = self._build_diatonic_chords()

        # ダイアトニック七の和音を構築
        self.diatonic_sevenths = self._build_diatonic_sevenths()

        # 副属七和音を構築
        self.secondary_dominants = self._build_secondary_dominants()

        # 変化和音を構築
        self.altered_chords = self._build_altered_chords()

    def _build_diatonic_chords(self) -> List[ChordLabel]:
        """調のダイアトニック三和音7つを構築"""
        # 長調: I(M) ii(m) iii(m) IV(M) V(M) vi(m) vii°(dim)
        # 短調: i(m) ii°(dim) III(M) iv(m) V(M) VI(M) vii°(dim)
        if self.key.mode == "major":
            qualities = ["major", "minor", "minor", "major",
                         "major", "minor", "diminished"]
        else:
            qualities = ["minor", "diminished", "major", "minor",
                         "major", "major", "diminished"]

        chords = []
        for degree in range(7):
            root_pc = self.scale[degree]
            quality = qualities[degree]
            tones_list = self.rules.build_triad(root_pc, quality)
            chord = ChordLabel(
                degree=degree,
                root_pc=root_pc,
                quality=quality,
                tones=set(tones_list),
            )
            chords.append(chord)
        return chords

    def _build_diatonic_sevenths(self) -> Dict[int, ChordLabel]:
        """各音階度上のダイアトニック七の和音を構築

        長調: Imaj7, ii7, iii7, IVmaj7, V7, vi7, viiø7
        短調: imaj7, iiø7, IIImaj7, iv7, V7, VImaj7, vii°7
        """
        if self.key.mode == "major":
            seventh_qualities = [
                "major7", "minor7", "minor7", "major7",
                "dominant7", "minor7", "half_diminished7",
            ]
        else:
            seventh_qualities = [
                "minor7", "half_diminished7", "major7", "minor7",
                "dominant7", "major7", "diminished7",
            ]

        sevenths = {}
        for degree in range(7):
            root_pc = self.scale[degree]
            quality = seventh_qualities[degree]
            tones_list = self.rules.build_seventh_chord(root_pc, quality)
            seventh_pc = tones_list[3]  # 第七音
            chord = ChordLabel(
                degree=degree,
                root_pc=root_pc,
                quality=quality,
                tones=set(tones_list),
                has_seventh=True,
                seventh_pc=seventh_pc,
            )
            sevenths[degree] = chord
        return sevenths

    def _build_secondary_dominants(self) -> Dict[int, ChordLabel]:
        """副属七和音を構築

        V7/ii, V7/iii, V7/IV, V7/V, V7/vi を事前構築。
        V7/I（= 通常のV7）と V7/vii°（実用されない）は除外。
        """
        secondaries = {}
        for target_degree in [1, 2, 3, 4, 5]:  # ii, iii, IV, V, vi
            target_root = self.scale[target_degree]
            dom_root = (target_root + 7) % 12  # V of target
            tones_list = self.rules.build_seventh_chord(dom_root, "dominant7")
            seventh_pc = tones_list[3]
            chord = ChordLabel(
                degree=target_degree,  # 解決先の度数で記録
                root_pc=dom_root,
                quality="dominant7",
                tones=set(tones_list),
                is_secondary_dominant=True,
                has_seventh=True,
                seventh_pc=seventh_pc,
                resolution_target_pc=target_root,
            )
            secondaries[target_degree] = chord
        return secondaries

    def _build_altered_chords(self) -> List[ChordLabel]:
        """変化和音を構築

        ナポリの六度: ♭II長三和音（サブドミナント機能）
        増六和音: イタリア・ドイツ・フランスの六（ドミナント前置）
        """
        tonic = self.key.tonic_pc
        altered = []

        # ナポリの六度: ♭II = (tonic+1) の長三和音
        nap_root = (tonic + 1) % 12
        nap_tones = self.rules.build_triad(nap_root, "major")
        altered.append(ChordLabel(
            degree=1,  # ♭II（ii の代替として機能）
            root_pc=nap_root,
            quality="major",
            tones=set(nap_tones),
            alteration_type="neapolitan",
        ))

        # 増六和音: ♭VI, I, #IV を基礎
        flat6 = (tonic + 8) % 12   # ♭VI
        sharp4 = (tonic + 6) % 12  # #IV

        # イタリアの六: ♭VI, I, #IV
        altered.append(ChordLabel(
            degree=4,  # ドミナントに解決
            root_pc=flat6,
            quality="augmented",
            tones={flat6, tonic, sharp4},
            alteration_type="italian",
        ))

        # ドイツの六: ♭VI, I, ♭III, #IV
        flat3 = (tonic + 3) % 12
        altered.append(ChordLabel(
            degree=4,
            root_pc=flat6,
            quality="augmented",
            tones={flat6, tonic, flat3, sharp4},
            alteration_type="german",
        ))

        # フランスの六: ♭VI, I, II, #IV
        second = (tonic + 2) % 12
        altered.append(ChordLabel(
            degree=4,
            root_pc=flat6,
            quality="augmented",
            tones={flat6, tonic, second, sharp4},
            alteration_type="french",
        ))

        return altered

    def find_containing_chords(self, pitch_class: int) -> List[ChordLabel]:
        """指定ピッチクラスを含む全ダイアトニック和音を返す"""
        return [c for c in self.diatonic_chords if pitch_class in c.tones]

    def analyze(self, subject: Subject) -> List[ChordLabel]:
        """主題の各拍に和声を割り当てる

        サブビート対応: 各拍の拍頭音（強拍上の音）のピッチクラスで和声を決定。
        1拍 = 4サブビート。拍頭はサブビート 0, 4, 8, ... の音。

        拡張和声選択:
          1. ダイアトニック三和音を基本として選択
          2. seventh_freq の確率で七の和音に昇格
          3. secondary_dom_freq の確率で副属七和音に置換
          4. altered_freq の確率で変化和音に置換
          ※ 冒頭・末尾は安定性のためダイアトニック三和音を固定

        Returns:
            主題の各拍に対応するChordLabel のリスト
        """
        # 各拍の拍頭音のピッチクラスを抽出
        beat_pcs = self._extract_beat_head_pcs(subject)
        length = len(beat_pcs)

        result: List[Optional[ChordLabel]] = [None] * length

        # --- 冒頭と末尾をアンカー（ダイアトニック三和音で固定）---
        result[0] = self._select_for_beat(beat_pcs[0], preferred_degrees={0})
        if length >= 2:
            result[-1] = self._select_for_beat(
                beat_pcs[-1], preferred_degrees={0, 4})

        # --- 中間拍を充填 ---
        functional_plan = self._create_functional_plan(length)

        for beat in range(length):
            if result[beat] is not None:
                continue
            preferred = self._degrees_for_function(functional_plan[beat])
            result[beat] = self._select_for_beat(beat_pcs[beat], preferred)

        # --- 同一和音の過度な連続を修正 ---
        dummy_pitches = [Pitch(60 + pc) for pc in beat_pcs]
        result = self._reduce_repetition(result, dummy_pitches)

        # --- 拡張和声の適用（冒頭・末尾を除く中間拍のみ）---
        result = self._apply_extended_harmony(result, beat_pcs, functional_plan)

        return result

    def analyze_answer(self, answer: Subject) -> List[ChordLabel]:
        """応答の和声分析（主調の枠組みで属調域を分析）

        バッハのフーガの慣例に基づく:
        - 和声枠組みは主調のカデンツ構造を保持
        - 冒頭は V（属和音）で開始（応答は属音から入る）
        - 末尾も V で終了（属音回帰）
        - 属調の導音（C major での F#）は V/V として処理
        - 変化和音は提示部では使用しない
        """
        beat_pcs = self._extract_beat_head_pcs(answer)
        length = len(beat_pcs)

        result: List[Optional[ChordLabel]] = [None] * length

        # --- 応答のアンカー: V（属和音）で開始・終了 ---
        result[0] = self._select_for_beat(beat_pcs[0], preferred_degrees={4})
        if length >= 2:
            result[-1] = self._select_for_beat(
                beat_pcs[-1], preferred_degrees={4, 0})

        # --- 中間拍: 主調の機能進行だがD機能を多めに ---
        functional_plan = self._create_functional_plan(length)
        # 応答ではD領域（属和音圏）の比重を高める
        for i in range(length):
            if functional_plan[i] == "T" and 0 < i < length - 1:
                functional_plan[i] = "D"

        for beat in range(length):
            if result[beat] is not None:
                continue
            preferred = self._degrees_for_function(functional_plan[beat])
            result[beat] = self._select_for_beat(beat_pcs[beat], preferred)

        # --- 同一和音の過度な連続を修正 ---
        dummy_pitches = [Pitch(60 + pc) for pc in beat_pcs]
        result = self._reduce_repetition(result, dummy_pitches)

        # --- 拡張和声の適用（提示部なので変化和音なし、七の和音と副属七のみ）---
        result = self._apply_extended_harmony(result, beat_pcs, functional_plan)

        return result

    def _apply_extended_harmony(
        self,
        plan: List[ChordLabel],
        beat_pcs: List[int],
        functional_plan: List[str],
    ) -> List[ChordLabel]:
        """ダイアトニック三和音の和声計画に拡張和声を適用

        適用順序:
          1. 変化和音（S機能の拍、D直前の拍）
          2. 副属七和音（次拍への解決が可能な拍）
          3. 七の和音（任意の拍を昇格）

        冒頭（拍0）と末尾は安定性のため対象外。
        """
        length = len(plan)

        for beat in range(1, length - 1):
            pc = beat_pcs[beat]
            func = functional_plan[beat] if beat < len(functional_plan) else "T"

            # --- 変化和音 ---
            if self.rng.random() < self.altered_freq:
                altered = self._try_altered_chord(pc, func, beat, plan)
                if altered is not None:
                    plan[beat] = altered
                    continue

            # --- 副属七和音 ---
            if beat + 1 < length and self.rng.random() < self.secondary_dom_freq:
                sec_dom = self._try_secondary_dominant(pc, plan[beat + 1])
                if sec_dom is not None:
                    plan[beat] = sec_dom
                    continue

            # --- 七の和音昇格 ---
            if self.rng.random() < self.seventh_freq:
                plan[beat] = self._upgrade_to_seventh(plan[beat])

        return plan

    def _upgrade_to_seventh(self, chord: ChordLabel) -> ChordLabel:
        """ダイアトニック三和音を同度数の七の和音に昇格"""
        if chord.has_seventh:
            return chord  # 既に七の和音
        if chord.degree in self.diatonic_sevenths:
            return self.diatonic_sevenths[chord.degree]
        return chord

    def _try_secondary_dominant(
        self, pitch_class: int, next_chord: ChordLabel,
    ) -> Optional[ChordLabel]:
        """次拍の和音に解決する副属七和音を試行

        条件:
          - 次拍の度数に対応する副属七和音が存在する
          - 現拍のピッチクラスが副属七和音の構成音に含まれる
        """
        target_degree = next_chord.degree
        if target_degree not in self.secondary_dominants:
            return None
        sec_dom = self.secondary_dominants[target_degree]
        if pitch_class in sec_dom.tones:
            return sec_dom
        return None

    def _try_altered_chord(
        self, pitch_class: int, func: str, beat: int,
        plan: List[ChordLabel],
    ) -> Optional[ChordLabel]:
        """変化和音を試行

        ナポリの六度: S機能の拍で適用
        増六和音: D直前の拍（次拍がD機能）で適用
        """
        candidates = []

        if func == "S":
            # ナポリの六度（S機能の代替）
            for ac in self.altered_chords:
                if ac.alteration_type == "neapolitan" and pitch_class in ac.tones:
                    candidates.append(ac)

        # 増六和音: 次拍がV（ドミナント）に解決する位置
        if beat + 1 < len(plan) and plan[beat + 1].degree == 4:
            for ac in self.altered_chords:
                if ac.alteration_type in ("italian", "german", "french"):
                    if pitch_class in ac.tones:
                        candidates.append(ac)

        if candidates:
            return self.rng.choice(candidates)
        return None

    @staticmethod
    def _extract_beat_head_pcs(subject: Subject) -> List[int]:
        """主題の各拍の拍頭音ピッチクラスを抽出

        サブビート位置を累積し、4サブビート境界（拍頭）の音を取得。
        """
        beat_pcs = []
        subbeat_pos = 0
        next_beat_boundary = 0

        for note in subject.notes:
            # この音が拍頭をまたぐ場合
            while next_beat_boundary <= subbeat_pos and next_beat_boundary < subbeat_pos + note.duration:
                if subbeat_pos <= next_beat_boundary:
                    beat_pcs.append(note.pitch.pitch_class)
                    next_beat_boundary += 4
            subbeat_pos += note.duration

        return beat_pcs

    def _create_functional_plan(self, length: int) -> List[str]:
        """主題長に応じた和声機能のテンプレートを生成

        基本形: T → (T) → S → D → T
        主題が長いほど中間に S や D を挿入
        """
        if length <= 4:
            return ["T", "T", "D", "T"][:length]
        elif length <= 7:
            # T T S S D D T
            plan = ["T"] * length
            mid = length // 2
            plan[mid - 1] = "S"
            plan[mid] = "S"
            plan[mid + 1] = "D"
            if mid + 2 < length - 1:
                plan[mid + 2] = "D"
            plan[-1] = "T"
            return plan
        else:
            # 長い主題: T T T S S D D T T T T
            plan = ["T"] * length
            third = length // 3
            two_third = 2 * length // 3
            for i in range(third, two_third):
                if i < (third + two_third) // 2:
                    plan[i] = "S"
                else:
                    plan[i] = "D"
            plan[-1] = "T"
            plan[-2] = "D"  # 末尾前はD（V→I終止準備）
            return plan

    def _degrees_for_function(self, func: str) -> Set[int]:
        """和声機能→優先度数の集合"""
        if func == "T":
            return self.FUNCTION_T | self.FUNCTION_III
        elif func == "S":
            return self.FUNCTION_S
        elif func == "D":
            return self.FUNCTION_D
        return set(range(7))

    def _select_for_beat(self, pitch_class: int,
                         preferred_degrees: Set[int]) -> ChordLabel:
        """指定ピッチクラスを含む和音から、優先度数に基づき選択

        ML統合点: ここの選択確率をMLモデルが調整可能
        """
        candidates = self.find_containing_chords(pitch_class)
        if not candidates:
            # 音階外音 → 副属七和音でその音を含むものを検索
            # V/V（属和音への副属七、degree=4）を最優先
            sec_candidates = [
                sec_dom for deg, sec_dom in self.secondary_dominants.items()
                if pitch_class in sec_dom.tones
            ]
            if sec_candidates:
                # V/V を優先（応答の属調導音に最も自然）
                vv = [c for c in sec_candidates
                      if c.resolution_target_pc == self.scale[4]]
                return vv[0] if vv else sec_candidates[0]
            # それでも見つからなければI和音にフォールバック
            return self.diatonic_chords[0]

        # 優先度数に合致する候補
        preferred = [c for c in candidates if c.degree in preferred_degrees]
        if preferred:
            # 主要和音（I, IV, V）を優先、代理は低確率で選択
            primary = [c for c in preferred if c.degree in {0, 3, 4}]
            secondary = [c for c in preferred if c.degree not in {0, 3, 4}]

            if primary and secondary and self.rng.random() < 0.25:
                choice = self.rng.choice(secondary)
                choice = ChordLabel(
                    degree=choice.degree, root_pc=choice.root_pc,
                    quality=choice.quality, tones=choice.tones,
                    is_secondary=True,
                )
                return choice
            if primary:
                return primary[0]
            return preferred[0]

        # 優先度数に合致しない → 候補から最良を選択
        return candidates[0]

    def _reduce_repetition(self, plan: List[ChordLabel],
                           pitches: List[Pitch]) -> List[ChordLabel]:
        """3拍以上の同一和音連続を代理和音で置換"""
        for i in range(1, len(plan) - 1):
            if (plan[i].degree == plan[i - 1].degree and
                    i + 1 < len(plan) and plan[i].degree == plan[i + 1].degree):
                pc = pitches[i].pitch_class
                alternatives = [
                    c for c in self.find_containing_chords(pc)
                    if c.degree != plan[i].degree
                ]
                if alternatives:
                    alt = alternatives[0]
                    plan[i] = ChordLabel(
                        degree=alt.degree, root_pc=alt.root_pc,
                        quality=alt.quality, tones=alt.tones,
                        is_secondary=True,
                    )
        return plan


# ============================================================
# 対位法DP（和声音ベース）
# ============================================================

class ContrapuntalDP:
    """和声音を候補とする単声部DP最適化

    既存の CounterpointProhibitions（硬制約）と
    CounterpointScoring（軟制約）を活用する。

    状態: (拍, MIDIピッチ)
    遷移: 固定声部群に対する対位法規則でフィルタ・スコアリング
    候補: その拍の和声音 × 声部音域内のオクターブ
    """

    def __init__(self):
        self.proh = CounterpointProhibitions()
        self.scoring = CounterpointScoring()

    def generate(
        self,
        num_beats: int,
        chord_plan: List[ChordLabel],
        voice_range: Tuple[int, int],
        fixed_voices: Dict[str, List[int]],
        free_voice_name: str,
        start_from: Optional[int] = None,
    ) -> List[int]:
        """単声部の最適旋律をDP探索で生成

        Args:
            num_beats: 拍数
            chord_plan: 各拍の和声割り当て
            voice_range: (最低MIDI, 最高MIDI)
            fixed_voices: {声部名: [拍ごとのMIDI値]} 固定声部群
            free_voice_name: 生成対象の声部名（上下関係判定用）
            start_from: 直前の拍のMIDIピッチ（区間境界の連続性確保）

        Returns:
            MIDIピッチのリスト（各拍1音）
        """
        lo, hi = voice_range

        # 和声計画をインスタンスに一時保存（_score_transitionで参照）
        self._chord_plan = chord_plan

        # --- 拍ごとの候補音を列挙 ---
        candidates_per_beat = []
        for beat in range(num_beats):
            chord_tones_pc = chord_plan[beat].tones
            cands = []
            for midi in range(lo, hi + 1):
                if midi % 12 in chord_tones_pc:
                    cands.append(midi)
            candidates_per_beat.append(cands)

        # --- DP前方パス ---
        # dp[beat][pitch] = (累積コスト, 前拍のpitch or None)
        INF = float('inf')
        dp: List[Dict[int, Tuple[float, Optional[int]]]] = [
            {} for _ in range(num_beats)
        ]

        # 初期拍
        center = (lo + hi) // 2
        anchor = start_from if start_from is not None else center
        for pitch in candidates_per_beat[0]:
            # 直前の音からの跳躍にペナルティ（区間連続性）
            interval = abs(pitch - anchor)
            if interval <= 2:
                cost = -0.5       # 順次進行: ボーナス
            elif interval <= 4:
                cost = 0.5        # 3度: 許容
            elif interval <= 7:
                cost = 3.0        # 4-5度: ペナルティ
            else:
                cost = interval * 0.8  # 6度以上: 距離比例ペナルティ
            # 固定声部との初期音程チェック
            cost += self._score_vertical(pitch, 0, fixed_voices)
            dp[0][pitch] = (cost, None)

        # 遷移
        ctx = MelodicContext()
        for beat in range(1, num_beats):
            for curr in candidates_per_beat[beat]:
                best_cost = INF
                best_prev = None

                for prev, (prev_cost, _) in dp[beat - 1].items():
                    # --- 硬制約チェック ---
                    if not self._check_hard(
                        prev, curr, beat, fixed_voices, free_voice_name
                    ):
                        continue

                    # --- 軟制約コスト ---
                    t_cost = self._score_transition(
                        prev, curr, beat, fixed_voices,
                        free_voice_name, voice_range, ctx
                    )
                    total = prev_cost + t_cost

                    if total < best_cost:
                        best_cost = total
                        best_prev = prev

                if best_prev is not None:
                    dp[beat][curr] = (best_cost, best_prev)

        # --- 後方パス（バックトラック）---
        if not dp[-1]:
            # フォールバック: DPが到達不能 → 中央音で埋める
            return [center] * num_beats

        # 最終拍で最小コストのピッチを選択
        last_beat = dp[-1]
        best_final = min(last_beat.keys(), key=lambda p: last_beat[p][0])

        result = [0] * num_beats
        result[-1] = best_final
        for beat in range(num_beats - 2, -1, -1):
            result[beat] = dp[beat + 1][result[beat + 1]][1]

        return result

    def _check_hard(
        self, prev_free: int, curr_free: int, beat: int,
        fixed_voices: Dict[str, List[int]], free_voice_name: str,
    ) -> bool:
        """全固定声部に対する硬制約チェック"""
        for name, melody in fixed_voices.items():
            if beat >= len(melody) or beat - 1 < 0:
                continue
            prev_fixed = melody[beat - 1]
            curr_fixed = melody[beat]

            # 上下関係を判定
            upper_p, upper_c, lower_p, lower_c = self._order_voices(
                prev_free, curr_free, prev_fixed, curr_fixed,
                free_voice_name, name
            )

            # ユニゾン禁止（完全同音は常に不可）
            if curr_free == curr_fixed:
                return False

            # 同ピッチクラス禁止（オクターブ含む）: 2声テクスチャでは硬制約
            # 3声以上では和音構成音が3つしかないため軟制約に委ねる
            if len(fixed_voices) == 1 and curr_free % 12 == curr_fixed % 12:
                return False

            # 声部交差禁止: 上声が下声より低くなってはならない
            if upper_c < lower_c:
                return False

            ok, _ = self.proh.check_parallel_perfect(
                upper_p, upper_c, lower_p, lower_c)
            if not ok:
                return False

            ok, _ = self.proh.check_direct_unison(
                prev_free, curr_free, prev_fixed, curr_fixed)
            if not ok:
                return False

            ok, _ = self.proh.check_voice_overlap(
                upper_p, upper_c, lower_p, lower_c)
            if not ok:
                return False

            # 外声間の隠伏5/8度
            is_outer = self._is_outer(free_voice_name, name)
            if is_outer:
                ok, _ = self.proh.check_hidden_perfect(
                    upper_p, upper_c, lower_p, lower_c, True)
                if not ok:
                    return False

        # 自由声部内の旋律制約
        ok, _ = self.proh.check_melodic_augmented(prev_free, curr_free)
        if not ok:
            return False
        ok, _ = self.proh.check_melodic_seventh(prev_free, curr_free)
        if not ok:
            return False

        return True

    def _score_transition(
        self, prev_free: int, curr_free: int, beat: int,
        fixed_voices: Dict[str, List[int]], free_voice_name: str,
        voice_range: Tuple[int, int], ctx: MelodicContext,
    ) -> float:
        """軟制約コスト（低い方が良い）"""
        cost = 0.0

        # --- 各固定声部との対位法スコア ---
        for name, melody in fixed_voices.items():
            if beat >= len(melody) or beat - 1 < 0:
                continue
            prev_fixed = melody[beat - 1]
            curr_fixed = melody[beat]

            # 反行優先（重み大）
            cost += self.scoring.score_motion_type(
                prev_free, curr_free, prev_fixed, curr_fixed) * 2.0

        # --- 自由声部自身の旋律コスト ---
        # 順次進行を好む（跳躍にペナルティ）
        interval = abs(curr_free - prev_free)
        if interval == 0:
            cost += 4.0       # 同音保持: 強いペナルティ（対位法では旋律の動きが重要）
        elif interval <= 2:
            cost -= 1.0       # 半音・全音: ボーナス
        elif interval <= 4:
            cost += 0.5       # 3度: 許容
        elif interval <= 7:
            cost += 2.0       # 4度-5度: ペナルティ
        else:
            cost += 5.0       # 6度以上: 大ペナルティ

        # 跳躍解決
        cost += self.scoring.score_leap_resolution(ctx, curr_free) * 1.5

        # 同方向連続制限
        cost += self.scoring.score_consecutive_direction(ctx, curr_free)

        # 旋律的多様性
        cost += self.scoring.score_melodic_variety(ctx, curr_free) * 1.5

        # --- 垂直音程の質 ---
        cost += self._score_vertical(curr_free, beat, fixed_voices)

        # --- 拡張和声の解決コスト ---
        cost += self._score_chord_resolution(prev_free, curr_free, beat)

        return cost

    def _score_chord_resolution(
        self, prev_free: int, curr_free: int, beat: int,
    ) -> float:
        """七の和音・副属七和音・変化和音の解決に関するコスト

        前拍の和声が拡張和声の場合、適切な解決を促進する。
        全て軟制約（hard constraintではない）。
        """
        if not hasattr(self, '_chord_plan') or beat < 1:
            return 0.0
        cp = self._chord_plan
        if beat - 1 >= len(cp) or beat >= len(cp):
            return 0.0

        prev_chord = cp[beat - 1]
        curr_chord = cp[beat]
        cost = 0.0

        # --- 七の和音の解決 ---
        # 自由声部が前拍で七の音を弾いていたなら、下行順次進行を促進
        if prev_chord.has_seventh and prev_chord.seventh_pc is not None:
            if prev_free % 12 == prev_chord.seventh_pc:
                resolved_down = (
                    curr_free < prev_free
                    and abs(curr_free - prev_free) <= 2
                )
                if not resolved_down:
                    cost += 2.0

        # --- 副属七和音の解決 ---
        # V7/X は X に解決すべき
        if prev_chord.is_secondary_dominant and prev_chord.resolution_target_pc is not None:
            if curr_chord.root_pc != prev_chord.resolution_target_pc:
                cost += 3.0

        # --- 変化和音の解決 ---
        if prev_chord.alteration_type is not None:
            alt = prev_chord.alteration_type
            if alt == "neapolitan":
                # ナポリの六度 → V または vii° に解決
                if curr_chord.degree not in (4, 6):
                    cost += 2.0
            elif alt in ("italian", "german", "french"):
                # 増六和音 → V に解決
                if curr_chord.degree != 4:
                    cost += 3.0

        return cost

    def _score_vertical(
        self, pitch: int, beat: int,
        fixed_voices: Dict[str, List[int]],
    ) -> float:
        """垂直音程の協和性スコア"""
        num_voices = len(fixed_voices) + 1  # 固定声部 + 自由声部
        cost = 0.0
        for name, melody in fixed_voices.items():
            if beat >= len(melody):
                continue
            fixed = melody[beat]
            raw_interval = abs(pitch - fixed)
            ic = raw_interval % 12
            if ic in {3, 4, 8, 9}:
                cost -= 1.5   # 3度・6度（不完全協和）: 強いボーナス
            elif ic == 0:
                if raw_interval == 0:
                    cost += 10.0  # ユニゾン: 禁止的ペナルティ
                elif num_voices <= 2:
                    cost += 10.0  # 2声でオクターブ: 禁止的（モノフォニー化）
                else:
                    cost += 1.5   # 3声以上でオクターブ: 軽ペナルティ（根音重複・5度省略許容）
            elif ic == 7:
                cost -= 0.3   # 5度（完全協和）: 軽いボーナス
            elif ic in {5}:
                cost += 1.0   # 4度: 軽いペナルティ
            elif ic in {1, 2, 10, 11}:
                cost += 3.0   # 2度・7度: ペナルティ
            elif ic == 6:
                cost += 5.0   # 三全音: 大ペナルティ
        return cost

    def _order_voices(
        self, prev_free: int, curr_free: int,
        prev_fixed: int, curr_fixed: int,
        free_name: str, fixed_name: str,
    ) -> Tuple[int, int, int, int]:
        """声部の上下関係に基づきupper/lowerを返す"""
        voice_order = {
            FugueVoiceType.SOPRANO.value: 0,
            FugueVoiceType.ALTO.value: 1,
            FugueVoiceType.TENOR.value: 2,
            FugueVoiceType.BASS.value: 3,
        }
        free_rank = voice_order.get(free_name, 1)
        fixed_rank = voice_order.get(fixed_name, 2)

        if free_rank < fixed_rank:
            # 自由声部が上
            return prev_free, curr_free, prev_fixed, curr_fixed
        else:
            return prev_fixed, curr_fixed, prev_free, curr_free

    @staticmethod
    def _is_outer(name_a: str, name_b: str) -> bool:
        """2声部が外声（ソプラノ-バス）かどうか"""
        pair = {name_a, name_b}
        return FugueVoiceType.SOPRANO.value in pair and FugueVoiceType.BASS.value in pair


# ============================================================
# オクターブ補正
# ============================================================

def fit_melody_to_range(
    melody: List[Pitch], voice_range: Tuple[int, int]
) -> List[Pitch]:
    """旋律を声部音域の中央付近に配置

    オクターブ単位でシフトし、全音が音域内に収まるよう調整する。
    """
    if not melody:
        return []

    lo, hi = voice_range
    center = (lo + hi) // 2
    melody_center = sum(p.midi for p in melody) // len(melody)

    # 最適オクターブシフト
    shift = round((center - melody_center) / 12) * 12

    result = []
    for p in melody:
        midi = p.midi + shift
        # 音域外ならオクターブ調整
        while midi < lo:
            midi += 12
        while midi > hi:
            midi -= 12
        # それでも収まらない場合は最寄り
        midi = max(lo, min(hi, midi))
        result.append(Pitch(midi))

    return result


SUBBEATS_PER_BEAT = 4  # 1拍 = 4サブビート（十六分音符）


# ============================================================
# リズム装飾（Layer 2）
# ============================================================

class RhythmElaborator:
    """拍内のリズム装飾

    拍頭の骨格音（和声音）が決まった後、拍内を装飾する。
    対位法の原則:
    - 拍頭（強拍）は和声音
    - 拍内（弱拍）は経過音・刺繍音・補助音が許容される
    - 十六分音符は順次進行のみ
    - 八分音符は3度跳躍まで許容
    """

    # リズムパターン: 各値はサブビート数
    PATTERNS = {
        'Q':    [4],              # 四分音符 ♩
        'EE':   [2, 2],           # 八分×2 ♪♪
        'SSSS': [1, 1, 1, 1],    # 十六分×4
        'ES':   [2, 1, 1],       # 八分＋十六分×2
        'SE':   [1, 1, 2],       # 十六分×2＋八分
        'DS':   [3, 1],          # 付点八分＋十六分
    }

    def __init__(self, scale: List[int], seed: Optional[int] = None):
        self.scale = scale  # 使用する音階のピッチクラス集合
        self.rng = random.Random(seed)

    def elaborate_beat(
        self,
        skeleton_pitch: int,
        next_pitch: Optional[int],
        pattern_name: str,
        voice_range: Tuple[int, int],
    ) -> List[Tuple[int, int]]:
        """1拍を装飾する

        Args:
            skeleton_pitch: 拍頭の骨格音（MIDIピッチ）
            next_pitch: 次の拍の骨格音（接続先、Noneなら折り返し）
            pattern_name: リズムパターン名
            voice_range: 声部音域

        Returns:
            [(MIDIピッチ, サブビート数), ...] — 合計4サブビート
        """
        pattern = self.PATTERNS.get(pattern_name, [4])
        if len(pattern) == 1:
            return [(skeleton_pitch, 4)]

        lo, hi = voice_range
        result = [(skeleton_pitch, pattern[0])]

        # 拍内の追加音を生成
        target = next_pitch if next_pitch is not None else skeleton_pitch
        for slot_idx in range(1, len(pattern)):
            dur = pattern[slot_idx]
            prev_pitch = result[-1][0]

            if slot_idx == len(pattern) - 1 and next_pitch is not None:
                # 最後のスロット: 次の骨格音に接近する経過音
                pitch = self._passing_toward(prev_pitch, target, lo, hi)
            else:
                # 中間スロット: 刺繍音 or 経過音
                if self.rng.random() < 0.4:
                    pitch = self._neighbor_tone(prev_pitch, lo, hi)
                else:
                    pitch = self._passing_toward(prev_pitch, target, lo, hi)

            result.append((pitch, dur))

        return result

    def _passing_toward(self, current: int, target: int,
                        lo: int, hi: int) -> int:
        """targetに向かう順次進行の経過音"""
        if current == target:
            # 同音なら上下いずれかの隣接音
            step = self.rng.choice([-1, 1])
        elif target > current:
            step = 1
        else:
            step = -1

        pitch = current + step
        # 音階音に補正
        pitch = self._snap_to_scale(pitch)
        return max(lo, min(hi, pitch))

    def _neighbor_tone(self, current: int, lo: int, hi: int) -> int:
        """上方または下方の刺繍音"""
        direction = self.rng.choice([-1, 1])
        pitch = current + direction
        pitch = self._snap_to_scale(pitch)
        return max(lo, min(hi, pitch))

    def _snap_to_scale(self, pitch: int) -> int:
        """最寄りの音階音にスナップ"""
        pc = pitch % 12
        if pc in self.scale:
            return pitch
        # 最寄りの音階音を探す
        for offset in [1, -1, 2, -2]:
            candidate = (pc + offset) % 12
            if candidate in self.scale:
                return (pitch // 12) * 12 + candidate
        return pitch

    def select_pattern(self, is_subject_voice: bool,
                       other_has_motion: bool) -> str:
        """リズムパターンを選択

        原則:
        - 主題が四分音符で動く間、対旋律は八分・十六分で動く
        - 全声部が同時に細かくなることを避ける
        - ランダム性を持たせて単調さを防ぐ
        """
        if is_subject_voice:
            return 'Q'  # 主題声部は骨格維持

        if other_has_motion:
            # 他声部が既に動いている→四分音符寄り
            choices = ['Q', 'Q', 'EE']
        else:
            # 自由に装飾可能
            choices = ['EE', 'EE', 'ES', 'SE', 'SSSS', 'Q']

        return self.rng.choice(choices)


def fit_notes_to_range(
    notes: List['NoteEvent'], voice_range: Tuple[int, int]
) -> List['NoteEvent']:
    """NoteEvent版オクターブ補正（音長保持）"""
    if not notes:
        return []
    lo, hi = voice_range
    center = (lo + hi) // 2
    melody_center = sum(n.pitch.midi for n in notes) // len(notes)
    shift = round((center - melody_center) / 12) * 12

    result = []
    for n in notes:
        midi = n.pitch.midi + shift
        while midi < lo:
            midi += 12
        while midi > hi:
            midi -= 12
        midi = max(lo, min(hi, midi))
        result.append(NoteEvent(Pitch(midi), n.duration))
    return result


# ============================================================
# フーガ実現エンジン
# ============================================================

class FugueRealizationEngine:
    """提示部を和声分析→DP最適化で実現する

    公開API:
        realize_exposition() → Dict[FugueVoiceType, List[Tuple[int, int, int]]]
        export_midi(filename, tempo)
    """

    def __init__(self, fugue_structure: FugueStructure,
                 seed: Optional[int] = None):
        self.fs = fugue_structure
        self.key = fugue_structure.main_key
        self.subject = fugue_structure.subject
        self.seed = seed

        # 提示部では調的安定性を優先: 変化和音禁止、副属七も控えめ
        self.analyzer = SubjectHarmonicAnalyzer(
            self.key, seed=seed,
            altered_freq=0.0,
            secondary_dom_freq=0.05,
        )
        self.dp = ContrapuntalDP()

        # 結果格納
        self.voice_melodies: Dict[FugueVoiceType, List[Optional[int]]] = {}
        self.chord_plan: List[ChordLabel] = []
        self.countersubject_midi: List[int] = []

    def realize_exposition(
        self,
    ) -> Dict[FugueVoiceType, List[Tuple[int, int, int]]]:
        """提示部全体を実現する

        アルゴリズム:
        Phase A: 全固定声部（主題・応答）をオクターブ補正して配置
        Phase B: 各声部の入場拍を記録
        Phase C: 提示部全体の和声進行を構築
        Phase D: 入場済みかつNoneの拍をDP充填（入場順に処理）

        Returns:
            {voice: [(start_tick, midi, duration_tick), ...]}
            MIDIWriter.add_track_from_notes() 互換フォーマット
        """
        entries = self.fs.entries
        if not entries:
            entries = self.fs.create_exposition(answer_type="auto")

        subject_len = self.subject.get_length()

        # --- 和声分析 ---
        self.chord_plan = self.analyzer.analyze(self.subject)

        answer = entries[1].subject if len(entries) > 1 else self.subject
        # 応答は主調の枠組みで分析（V開始、属調導音はV/Vとして処理）
        answer_chord_plan = self.analyzer.analyze_answer(answer)

        # --- 提示部の全拍数 ---
        total_beats = 0
        for entry in entries:
            end = entry.start_position + subject_len
            if end > total_beats:
                total_beats = end

        # --- Phase A: 全固定声部を配置 ---
        melodies: Dict[FugueVoiceType, List[Optional[int]]] = {}
        for vt in FugueVoiceType:
            melodies[vt] = [None] * total_beats

        entry_start: Dict[FugueVoiceType, int] = {}  # 入場拍

        for entry in entries:
            voice = entry.voice_type
            start = entry.start_position
            entry_start[voice] = start

            fitted = fit_melody_to_range(
                entry.subject.pitches,
                VOICE_RANGES[voice],
            )
            for i, p in enumerate(fitted):
                abs_beat = start + i
                if abs_beat < total_beats:
                    melodies[voice][abs_beat] = p.midi

        # --- Phase C: 提示部全体の和声進行を構築 ---
        exposition_chords: List[ChordLabel] = []
        for beat in range(total_beats):
            chord = None
            # この拍にエントリがあればその和声を使用
            for entry in entries:
                rel = beat - entry.start_position
                if 0 <= rel < subject_len:
                    plan = (answer_chord_plan if entry.is_answer
                            else self.chord_plan)
                    if rel < len(plan):
                        chord = plan[rel]
                    break
            if chord is None:
                chord = self.analyzer.diatonic_chords[0]  # I
            exposition_chords.append(chord)

        # --- Phase D: エントリ順に区間処理 ---
        #
        # エントリ i が入場するとき:
        #   (a) コデッタ区間: エントリ(i-1)終了 ～ エントリ(i)開始
        #       → 順次進行（ステップワイズ）で埋める
        #   (b) エントリ区間: エントリ(i)開始 ～ エントリ(i)終了
        #       → 既入場の声部に対してDP生成

        for entry_idx in range(1, len(entries)):
            entry = entries[entry_idx]
            curr_start = entry.start_position
            curr_end = min(curr_start + subject_len, total_beats)

            prev_entry = entries[entry_idx - 1]
            prev_end = prev_entry.start_position + subject_len

            # (a) コデッタ区間の充填（DPで対位法規則を遵守）
            if prev_end < curr_start:
                codetta_len = curr_start - prev_end
                for prev_idx in range(entry_idx):
                    pv = entries[prev_idx].voice_type
                    if melodies[pv][prev_end] is not None:
                        continue  # 既に埋まっている

                    # 固定声部を収集
                    fixed = {}
                    for other_idx in range(entry_idx):
                        ov = entries[other_idx].voice_type
                        if ov == pv:
                            continue
                        section = []
                        all_none = True
                        for b in range(prev_end, curr_start):
                            val = melodies[ov][b]
                            if val is not None:
                                all_none = False
                            section.append(val)
                        if not all_none:
                            section = self._interpolate_nones(section)
                            fixed[ov.value] = section

                    codetta_chords = exposition_chords[prev_end:curr_start]
                    prev_note = melodies[pv][prev_end - 1] if prev_end > 0 else None

                    result = self.dp.generate(
                        num_beats=codetta_len,
                        chord_plan=codetta_chords,
                        voice_range=VOICE_RANGES[pv],
                        fixed_voices=fixed,
                        free_voice_name=pv.value,
                        start_from=prev_note,
                    )
                    for i, midi_val in enumerate(result):
                        beat = prev_end + i
                        if beat < total_beats:
                            melodies[pv][beat] = midi_val

            # (b) エントリ区間: 既入場声部にDP対位法生成
            for prev_idx in range(entry_idx):
                pv = entries[prev_idx].voice_type

                # この区間でpvがまだNoneの拍があるか
                needs_fill = any(
                    melodies[pv][b] is None
                    for b in range(curr_start, curr_end)
                )
                if not needs_fill:
                    continue

                # 固定声部を収集（この区間で実データがある声部のみ）
                fixed = {}
                for other_idx in range(entry_idx + 1):
                    ov = entries[other_idx].voice_type
                    if ov == pv:
                        continue
                    section_melody = []
                    all_none = True
                    for b in range(curr_start, curr_end):
                        val = melodies[ov][b]
                        if val is not None:
                            all_none = False
                            section_melody.append(val)
                        else:
                            section_melody.append(None)
                    if not all_none:
                        # None拍を前後の値で補間
                        section_melody = self._interpolate_nones(section_melody)
                        fixed[ov.value] = section_melody

                if not fixed:
                    continue

                section_len = curr_end - curr_start
                section_chords = exposition_chords[curr_start:curr_end]

                # 直前の音を取得（区間連続性のため）
                prev_note = None
                if curr_start > 0 and melodies[pv][curr_start - 1] is not None:
                    prev_note = melodies[pv][curr_start - 1]

                result = self.dp.generate(
                    num_beats=section_len,
                    chord_plan=section_chords,
                    voice_range=VOICE_RANGES[pv],
                    fixed_voices=fixed,
                    free_voice_name=pv.value,
                    start_from=prev_note,
                )

                for i, midi_val in enumerate(result):
                    beat = curr_start + i
                    if beat < total_beats and melodies[pv][beat] is None:
                        melodies[pv][beat] = midi_val

                # 最初のDP充填を対主題として保存
                if not self.countersubject_midi:
                    self.countersubject_midi = result

        # --- Phase E: サブビートグリッド構築 ---
        # beat-level melodies → subbeat-level grid
        # 主題は元のNoteEvent音長を反映、DP生成部は四分音符
        subbeat_grid = self._build_subbeat_grid(
            melodies, entries, total_beats)

        self.voice_melodies = melodies      # beat-level（レポート用）
        self.subbeat_grid = subbeat_grid    # subbeat-level（MIDI出力用）
        return self._to_midi_events_subbeat(subbeat_grid)

    @staticmethod
    def _interpolate_nones(melody: List[Optional[int]]) -> List[int]:
        """None値を前後の値で補間する"""
        result = list(melody)
        # 前方補間
        last_val = None
        for i in range(len(result)):
            if result[i] is not None:
                last_val = result[i]
            elif last_val is not None:
                result[i] = last_val
        # 後方補間（先頭のNoneを埋める）
        next_val = None
        for i in range(len(result) - 1, -1, -1):
            if result[i] is not None:
                next_val = result[i]
            elif next_val is not None:
                result[i] = next_val
        # それでもNoneが残る場合はフォールバック
        for i in range(len(result)):
            if result[i] is None:
                result[i] = 60  # C4
        return result

    @staticmethod
    def _find_gaps(
        melody: List[Optional[int]], start: int, end: int,
    ) -> List[Tuple[int, int]]:
        """入場拍以降のNone連続区間を特定"""
        gaps = []
        gap_start = None
        for i in range(start, end):
            if melody[i] is None:
                if gap_start is None:
                    gap_start = i
            else:
                if gap_start is not None:
                    gaps.append((gap_start, i))
                    gap_start = None
        if gap_start is not None:
            gaps.append((gap_start, end))
        return gaps

    def _build_subbeat_grid(
        self,
        beat_melodies: Dict[FugueVoiceType, List[Optional[int]]],
        entries: List[FugueEntry],
        total_beats: int,
    ) -> Dict[FugueVoiceType, List[Optional[int]]]:
        """beat-levelメロディ → subbeat-levelグリッドを構築

        - 主題のNoteEventは元の音長（duration）を反映
        - DP生成部はRhythmElaboratorでリズム装飾
        """
        SB = SUBBEATS_PER_BEAT
        total_sb = total_beats * SB
        grid: Dict[FugueVoiceType, List[Optional[int]]] = {}
        for vt in FugueVoiceType:
            grid[vt] = [None] * total_sb

        # --- 主題エントリをNoteEvent音長で配置 ---
        subject_beats: Dict[FugueVoiceType, Set[int]] = {
            vt: set() for vt in FugueVoiceType
        }
        for entry in entries:
            voice = entry.voice_type
            start_sb = entry.start_position * SB
            fitted = fit_notes_to_range(entry.subject.notes, VOICE_RANGES[voice])
            sb_pos = start_sb
            for note in fitted:
                beat_idx = sb_pos // SB
                subject_beats[voice].add(beat_idx)
                for s in range(note.duration):
                    abs_sb = sb_pos + s
                    if abs_sb < total_sb:
                        grid[voice][abs_sb] = note.pitch.midi
                sb_pos += note.duration

        # --- DP生成部をリズム装飾付きで配置 ---
        elaborator = RhythmElaborator(self.key.scale, seed=self.seed)

        for vt, beat_melody in beat_melodies.items():
            for beat in range(len(beat_melody)):
                if beat_melody[beat] is None:
                    continue
                if beat in subject_beats[vt]:
                    continue  # 主題が配置済み

                skeleton = beat_melody[beat]
                next_skeleton = (beat_melody[beat + 1]
                                 if beat + 1 < len(beat_melody)
                                    and beat_melody[beat + 1] is not None
                                 else None)

                # リズムパターン選択
                is_subject = beat in subject_beats[vt]
                # 他声部がこの拍で主題を歌っているか
                other_has_motion = any(
                    beat in subject_beats[ov]
                    for ov in subject_beats if ov != vt
                )
                pattern = elaborator.select_pattern(is_subject, other_has_motion)

                # 装飾
                elaborated = elaborator.elaborate_beat(
                    skeleton, next_skeleton, pattern, VOICE_RANGES[vt])

                # サブビートグリッドに書き込み
                sb_start = beat * SB
                sb_offset = 0
                for pitch, dur in elaborated:
                    for s in range(dur):
                        abs_sb = sb_start + sb_offset + s
                        if abs_sb < total_sb:
                            grid[vt][abs_sb] = pitch
                    sb_offset += dur

        return grid

    def _to_midi_events_subbeat(
        self,
        grid: Dict[FugueVoiceType, List[Optional[int]]],
        ticks_per_subbeat: int = 120,
    ) -> Dict[FugueVoiceType, List[Tuple[int, int, int]]]:
        """サブビートグリッドをMIDI互換フォーマットに変換

        連続する同一ピッチをタイ結合して1つのノートにする。
        """
        result = {}
        for voice, melody in grid.items():
            notes = []
            i = 0
            while i < len(melody):
                if melody[i] is not None:
                    pitch = melody[i]
                    start = i
                    # 同一ピッチの連続をまとめる
                    while i < len(melody) and melody[i] == pitch:
                        i += 1
                    duration = (i - start) * ticks_per_subbeat
                    notes.append((start * ticks_per_subbeat, pitch, duration))
                else:
                    i += 1
            if notes:
                result[voice] = notes
        return result

    def _to_midi_events(
        self,
        melodies: Dict[FugueVoiceType, List[Optional[int]]],
        ticks_per_beat: int = 480,
    ) -> Dict[FugueVoiceType, List[Tuple[int, int, int]]]:
        """メロディ配列をMIDI互換フォーマットに変換（後方互換）"""
        result = {}
        for voice, melody in melodies.items():
            notes = []
            for beat, midi_val in enumerate(melody):
                if midi_val is not None:
                    notes.append((
                        beat * ticks_per_beat,
                        midi_val,
                        ticks_per_beat,
                    ))
            if notes:
                result[voice] = notes
        return result

    def export_midi(self, filename: str, tempo: int = 72):
        """MIDIファイルに書き出す"""
        if hasattr(self, 'subbeat_grid') and self.subbeat_grid:
            midi_events = self._to_midi_events_subbeat(self.subbeat_grid)
        else:
            midi_events = self._to_midi_events(self.voice_melodies)
        writer = MIDIWriter(tempo=tempo, ticks_per_beat=480)

        channel_map = {
            FugueVoiceType.SOPRANO: 0,
            FugueVoiceType.ALTO: 1,
            FugueVoiceType.TENOR: 2,
            FugueVoiceType.BASS: 3,
        }

        for voice, notes in midi_events.items():
            if notes:
                writer.add_track_from_notes(
                    notes, channel=channel_map.get(voice, 0))

        writer.write_file(filename)

    def get_analysis_report(self) -> str:
        """分析結果のレポートを生成"""
        lines = []
        lines.append("=" * 50)
        lines.append("フーガ提示部 実現レポート")
        lines.append("=" * 50)

        # 和声進行
        lines.append("\n--- 主題の和声分析 ---")
        for beat, chord in enumerate(self.chord_plan):
            pc = self.subject.pitches[beat].pitch_class
            note = Pitch(60 + pc).name[:-1]  # 音名（オクターブなし）
            sec = "（代理）" if chord.is_secondary else ""
            lines.append(f"  拍{beat}: {note} → {chord.roman}{sec}")

        # 声部状況
        lines.append("\n--- 声部配置 ---")
        for voice, melody in self.voice_melodies.items():
            active = [m for m in melody if m is not None]
            if active:
                lo, hi = min(active), max(active)
                lines.append(
                    f"  {voice.value}: {Pitch(lo).name}-{Pitch(hi).name} "
                    f"({len(active)}拍 / {len(melody)}拍)")

        return "\n".join(lines)
