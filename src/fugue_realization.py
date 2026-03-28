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
from typing import List, Dict, Tuple, Optional, Set, FrozenSet
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
    FugueVoiceType, Codetta, Episode,
    KeyPath, KeyPathStrategy,
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
    def third_pc(self) -> int:
        """第3音のピッチクラス"""
        if "minor" in self.quality or "dim" in self.quality:
            return (self.root_pc + 3) % 12
        return (self.root_pc + 4) % 12

    @property
    def fifth_pc(self) -> int:
        """第5音のピッチクラス"""
        if "dim" in self.quality:
            return (self.root_pc + 6) % 12
        return (self.root_pc + 7) % 12

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
# 主題和声テンプレート（トップダウン和声計画の基盤）
# ============================================================

@dataclass
class BeatHarmony:
    """主題1拍の和声制約

    degree: 調内の和音度数（0-based: 0=I, 1=ii, ..., 6=vii°）
    quality: 和音の種類 ("major", "minor", "diminished")
    fixed_pcs: 不可侵ピッチクラス（例: 導音C#=1）。他声部もこのPCと
               矛盾する音を出してはならない。
    flexibility: "strict"=和音変更不可, "flexible"=代理和音への差替え可
    custom_chord: ダイアトニック外の和音を直接指定（V/V等の二次属和音用）
                  指定時はdegreeによるルックアップを迂回する
    """
    degree: int
    quality: str
    fixed_pcs: FrozenSet[int] = field(default_factory=frozenset)
    flexibility: str = "strict"
    custom_chord: Optional[ChordLabel] = None


@dataclass
class SubjectHarmonicTemplate:
    """主題の権威的和声テンプレート

    主題が暗黙に持つ和声進行を明示化する。提示部の和声計画は
    このテンプレートから演繹的に構築される。

    構築方法:
      1. from_manual(): 手動指定（最優先、Contrapunctus I参照等）
      2. from_analyzer(): 既存SubjectHarmonicAnalyzerの結果から自動導出
    """
    beats: List[BeatHarmony]

    @classmethod
    def from_manual(cls, specs) -> 'SubjectHarmonicTemplate':
        """手動指定から構築

        Args:
            specs: [(degree, quality, fixed_pcs_list, flexibility), ...] or
                   [(degree, quality, fixed_pcs_list, flexibility, custom_chord), ...]
                   例: [(0, "minor", [2], "strict"), (4, "major", [1], "strict")]
                   custom_chord: ChordLabel（V/V等の非ダイアトニック和音用）
        """
        beats = []
        for spec in specs:
            if len(spec) == 5:
                d, q, p, f, cc = spec
                beats.append(BeatHarmony(d, q, frozenset(p), f, custom_chord=cc))
            else:
                d, q, p, f = spec
                beats.append(BeatHarmony(d, q, frozenset(p), f))
        return cls(beats)

    @classmethod
    def from_analyzer(cls, chord_plan: List['ChordLabel'], key: 'Key') -> 'SubjectHarmonicTemplate':
        """既存アナライザの結果から構築（フォールバック）

        導音を含む和音は strict、それ以外は flexible とする。
        """
        beats = []
        leading_tone = (key.tonic_pc - 1) % 12
        for cl in chord_plan:
            flex = "strict" if leading_tone in cl.tones else "flexible"
            beats.append(BeatHarmony(cl.degree, cl.quality, frozenset(), flex))
        return cls(beats)

    def transpose(self, interval_semitones: int) -> 'SubjectHarmonicTemplate':
        """移調（属調テンプレート生成用）

        degree は調内機能なので変更しない。
        fixed_pcs のみ移調する。
        """
        new_beats = []
        for bh in self.beats:
            new_fixed = frozenset((pc + interval_semitones) % 12 for pc in bh.fixed_pcs)
            new_beats.append(BeatHarmony(bh.degree, bh.quality, new_fixed, bh.flexibility))
        return SubjectHarmonicTemplate(new_beats)


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

    @staticmethod
    def find_pivot_chords(from_key: Key, to_key: Key) -> List[Tuple[ChordLabel, ChordLabel]]:
        """両調に共通するダイアトニック三和音（ピボットコード）を発見する。

        Returns:
            [(from_key側のChordLabel, to_key側のChordLabel), ...]
            和声的重要度順（I,IV,V系を優先）
        """
        rules = HarmonyRules()

        def build_triads(key: Key) -> List[ChordLabel]:
            if key.mode == "major":
                qualities = ["major", "minor", "minor", "major",
                             "major", "minor", "diminished"]
            else:
                qualities = ["minor", "diminished", "major", "minor",
                             "major", "major", "diminished"]
            chords = []
            for degree in range(7):
                root_pc = key.scale[degree]
                quality = qualities[degree]
                tones_list = rules.build_triad(root_pc, quality)
                chords.append(ChordLabel(
                    degree=degree, root_pc=root_pc,
                    quality=quality, tones=set(tones_list),
                ))
            return chords

        from_chords = build_triads(from_key)
        to_chords = build_triads(to_key)

        # 構成音（ピッチクラス集合）が一致するペアを収集
        pivots = []
        for fc in from_chords:
            for tc in to_chords:
                if fc.tones == tc.tones:
                    pivots.append((fc, tc))

        # 和声的重要度でソート: I,IV,V (度数 0,3,4) > ii,vi (1,5) > iii,vii° (2,6)
        priority = {0: 0, 3: 0, 4: 0, 1: 1, 5: 1, 2: 2, 6: 2}
        pivots.sort(key=lambda pair: (
            priority.get(pair[0].degree, 3) + priority.get(pair[1].degree, 3)
        ))

        return pivots

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
        """V度またはvii度の三和音を七の和音に昇格する。

        古典和声で解決先が明確な七の和音のみ許可:
          - V7（属七）: V→I の解決。最も基本的な七の和音。
          - vii°7（減七）: vii°→I の解決。短調で頻用される。
        それ以外（Imaj7, ii7 等）は短二度衝突のリスクが高く禁止。
        """
        if chord.has_seventh:
            return chord
        # V度（属七）またはvii度（減七/導七）のみ昇格
        if chord.degree in (4, 6) and chord.degree in self.diatonic_sevenths:
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

        サブビート位置を累積し、4サブビート境界（拍頭）で鳴っている音を取得。
        半音符等の長い音は複数の拍頭にまたがるため、
        各拍頭にその時点で鳴っている音のPCを割り当てる。
        """
        beat_pcs = []
        subbeat_pos = 0
        next_beat_boundary = 0

        for note in subject.notes:
            # この音のスパン内にある全拍頭を捕捉
            note_end = subbeat_pos + note.duration
            while next_beat_boundary < note_end:
                beat_pcs.append(note.pitch.pitch_class)
                next_beat_boundary += 4
            subbeat_pos = note_end

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
            # 音階外音 → V（属和音）にフォールバック
            # 古典和声の原則: 音階外音は多くの場合ドミナント領域で生じる
            # 副属七和音への安易なフォールバックは調性を曖昧にするため禁止
            return self.diatonic_chords[4]  # V（属和音）

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

    def __init__(self, counterpoint_model=None, elaborate: bool = True):
        self.proh = CounterpointProhibitions()
        self.scoring = CounterpointScoring()
        self.cp_model = counterpoint_model  # CounterpointPatternModel (optional)
        self.elaborate = elaborate  # False: 和声音のみ候補とする

    def generate(
        self,
        num_beats: int,
        chord_plan: List[ChordLabel],
        voice_range: Tuple[int, int],
        fixed_voices: Dict[str, List[int]],
        free_voice_name: str,
        start_from: Optional[int] = None,
        prev_fixed_pitches: Optional[Dict[str, int]] = None,
        cs_profile: Optional[List[Optional[int]]] = None,
        beat_keys: Optional[List['Key']] = None,
    ) -> List[int]:
        """単声部の最適旋律をDP探索で生成

        Args:
            num_beats: 拍数
            chord_plan: 各拍の和声割り当て
            voice_range: (最低MIDI, 最高MIDI)
            fixed_voices: {声部名: [拍ごとのMIDI値]} 固定声部群
            free_voice_name: 生成対象の声部名（上下関係判定用）
            start_from: 直前の拍のMIDIピッチ（区間境界の連続性確保）
            prev_fixed_pitches: {声部名: 前セクション末尾のMIDIピッチ}
                セクション境界での並行5度/8度チェック用
            cs_profile: 対主題の理想的音程プロフィール（各拍の目標MIDI値）
                Noneの拍は誘導なし。柔らかいボーナスとして機能し、
                和声・対位法の制約より優先度は低い。

        Returns:
            MIDIピッチのリスト（各拍1音）
        """
        lo, hi = voice_range

        # 和声計画をインスタンスに一時保存（_score_transitionで参照）
        self._chord_plan = chord_plan
        self._cs_profile = cs_profile

        # --- 拍ごとの候補音を列挙 ---
        # コード優先でスケールを決定: コードに導音が含まれれば和声的短音階、
        # 含まれなければ自然短音階。主題 > コード > スケール の優先順位。
        candidates_per_beat = []
        for beat in range(num_beats):
            chord_tones_pc = chord_plan[beat].tones
            # 拍ごとのスケールをコードから決定
            # beat_keys が指定されていればそれを最優先
            beat_key_obj = None
            if beat_keys and beat < len(beat_keys):
                beat_key_obj = beat_keys[beat]
            elif hasattr(self, '_key_obj') and self._key_obj is not None:
                beat_key_obj = self._key_obj
            if beat_key_obj is not None:
                scale_pcs = set(beat_key_obj.scale_for_chord(chord_tones_pc))
            elif hasattr(self, '_key_scale'):
                scale_pcs = self._key_scale
            else:
                scale_pcs = set(chord_tones_pc)
            cands = []
            if self.elaborate:
                # elaborate=True: 和声音 + スケール音を候補とする
                for midi in range(lo, hi + 1):
                    pc = midi % 12
                    if pc in chord_tones_pc or pc in scale_pcs:
                        cands.append(midi)
            else:
                # elaborate=False: 和声音のみ候補とする（経過音なし）
                for midi in range(lo, hi + 1):
                    if midi % 12 in chord_tones_pc:
                        cands.append(midi)
            if not cands:
                # フォールバック: 和声音のみ
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

            # セクション境界の並行5度/8度チェック
            if prev_fixed_pitches and start_from is not None:
                boundary_ok = True
                for name, melody in fixed_voices.items():
                    if name not in prev_fixed_pitches:
                        continue
                    prev_fixed = prev_fixed_pitches[name]
                    curr_fixed = melody[0]
                    upper_p, upper_c, lower_p, lower_c = self._order_voices(
                        start_from, pitch, prev_fixed, curr_fixed,
                        free_voice_name, name
                    )
                    ok, _ = self.proh.check_parallel_perfect(
                        upper_p, upper_c, lower_p, lower_c)
                    if not ok:
                        boundary_ok = False
                        break
                if not boundary_ok:
                    continue  # この候補を除外

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

            # 固定声部が休符（None）の拍はスキップ
            if curr_fixed is None or prev_fixed is None:
                continue

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

            # 固定声部が休符（None）の拍はスキップ
            if curr_fixed is None or prev_fixed is None:
                continue

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

        # --- 増音程: ハード禁止 ---
        # 増2度（3半音で増音程に該当）と増4度/減5度（トライトーン=6半音）
        # ユーザ方針: 禁止事項は他のボーナスで覆せない絶対的コストにする
        if interval == 6:
            cost += 1000.0    # トライトーン跳躍: ハード禁止
        elif interval == 3:
            prev_pc = prev_free % 12
            curr_pc = curr_free % 12
            is_augmented = False
            # コードに整合するスケールで増2度判定
            if hasattr(self, '_key_obj') and self._key_obj is not None:
                chord_tones = (self._chord_plan[beat].tones
                               if self._chord_plan and beat < len(self._chord_plan)
                               else set())
                beat_scale = self._key_obj.scale_for_chord(chord_tones)
                if len(beat_scale) == 7:
                    aug2_pair = {beat_scale[5], beat_scale[6]}
                    if {prev_pc, curr_pc} == aug2_pair:
                        is_augmented = True
                if not is_augmented:
                    beat_scale_set = set(beat_scale)
                    if prev_pc not in beat_scale_set or curr_pc not in beat_scale_set:
                        is_augmented = True
            elif hasattr(self, '_key_scale_list') and len(self._key_scale_list) == 7:
                # フォールバック: 旧方式
                aug2_pair = {self._key_scale_list[5], self._key_scale_list[6]}
                if {prev_pc, curr_pc} == aug2_pair:
                    is_augmented = True
                if not is_augmented and hasattr(self, '_key_scale'):
                    sc = self._key_scale
                    if sc and (prev_pc not in sc or curr_pc not in sc):
                        is_augmented = True
            if is_augmented:
                cost += 1000.0  # 増2度: ハード禁止

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

        # --- 半音衝突ペナルティ ---
        # (a) 同一拍で固定声部と短2度（半音）の関係にある場合: 重いペナルティ
        curr_pc = curr_free % 12
        for name, melody in fixed_voices.items():
            if beat >= len(melody):
                continue
            fixed_pitch = melody[beat]
            if fixed_pitch is None:
                continue
            fixed_pc = fixed_pitch % 12
            pc_diff = min(abs(curr_pc - fixed_pc), 12 - abs(curr_pc - fixed_pc))
            if pc_diff == 1:
                # 導音→主音の同時鳴響は許容（コードに基づく判定）
                is_leading_tonic = False
                if hasattr(self, '_key_obj') and self._key_obj is not None:
                    chord_tones = (self._chord_plan[beat].tones
                                   if self._chord_plan and beat < len(self._chord_plan)
                                   else set())
                    bs = self._key_obj.scale_for_chord(chord_tones)
                    if len(bs) == 7 and {curr_pc, fixed_pc} == {bs[6], bs[0]}:
                        is_leading_tonic = True
                elif hasattr(self, '_key_scale_list') and len(self._key_scale_list) == 7:
                    leading = self._key_scale_list[6]
                    tonic = self._key_scale_list[0]
                    if {curr_pc, fixed_pc} == {leading, tonic}:
                        is_leading_tonic = True
                if is_leading_tonic:
                    continue
                cost += 1000.0  # 半音衝突: ハード禁止
        # (b) 交差半音: 前拍→現拍で固定声部がPC保持なのに自由声部がその半音へ移動
        prev_pc = prev_free % 12
        if prev_pc != curr_pc:
            for name, melody in fixed_voices.items():
                if beat >= len(melody) or beat - 1 < 0:
                    continue
                if melody[beat] is None or melody[beat - 1] is None:
                    continue
                fixed_prev_pc = melody[beat - 1] % 12
                fixed_curr_pc = melody[beat] % 12
                if (fixed_prev_pc == fixed_curr_pc and
                        min(abs(curr_pc - fixed_curr_pc),
                            12 - abs(curr_pc - fixed_curr_pc)) == 1):
                    cost += 6.0  # 交差半音衝突: 追加ペナルティ

        # --- 対旋律パターンモデルによるバッハ的旋律ボーナス ---
        if self.cp_model and self.cp_model.num_patterns > 0:
            # 和音音との距離
            if hasattr(self, '_chord_plan') and beat < len(self._chord_plan):
                chord_tones = self._chord_plan[beat].tones
                curr_pc = curr_free % 12
                min_dist = min(
                    min((curr_pc - ct) % 12, (ct - curr_pc) % 12)
                    for ct in chord_tones) if chord_tones else 0
                chord_offset = min_dist if min_dist <= 6 else min_dist - 12

                prev_interval = curr_free - prev_free
                # beat+1 の推定（DPでは次拍は不明だが、現在の遷移を評価）
                # prev→curr の遷移をパターンスコアで評価
                # 文脈: 前の遷移パターンが学習データにどれだけ合致するか
                score = self.cp_model.get_interval_score(
                    chord_offset, prev_interval, prev_interval)
                # 高スコア（バッハ的パターン） → コスト減少
                # log scale で -3.0 〜 0 のボーナス
                import math
                if score > 0:
                    cost -= min(3.0, math.log(score + 1e-8) + 5.0)

        # --- 対主題プロフィール誘導（柔らかいボーナス）---
        # cs_profileが指定されている場合、目標音への近接度でボーナスを与える。
        # 硬い制約ではなく、和声・対位法の制約がすべて優先される。
        if hasattr(self, '_cs_profile') and self._cs_profile is not None:
            if beat < len(self._cs_profile) and self._cs_profile[beat] is not None:
                target = self._cs_profile[beat]
                dist = abs(curr_free - target)
                if dist == 0:
                    cost -= 2.0   # 完全一致: ボーナス
                elif dist <= 2:
                    cost -= 1.0   # 2半音以内: 小ボーナス
                elif dist <= 4:
                    cost -= 0.3   # 4半音以内: 微ボーナス
                # 5半音以上: ボーナスなし（ペナルティも加えない）

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
        """垂直音程の協和性スコア + 和音充足ボーナス"""
        num_voices = len(fixed_voices) + 1  # 固定声部 + 自由声部
        cost = 0.0

        # 固定声部が鳴らしているPCを収集
        fixed_pcs = set()
        for name, melody in fixed_voices.items():
            if beat >= len(melody):
                continue
            fixed = melody[beat]
            if fixed is not None:
                fixed_pcs.add(fixed % 12)

        for name, melody in fixed_voices.items():
            if beat >= len(melody):
                continue
            fixed = melody[beat]
            if fixed is None:
                continue
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
                    cost += 1.5   # 3声以上でオクターブ: 軽ペナルティ
            elif ic == 7:
                cost -= 0.3   # 5度（完全協和）: 軽いボーナス
            elif ic in {5}:
                cost += 1.0   # 4度: 軽いペナルティ
            elif ic in {1, 11}:
                # 導音→主音の同時鳴響は許容
                my_pc = pitch % 12
                fx_pc = fixed % 12
                is_leading_tonic = False
                if hasattr(self, '_key_obj') and self._key_obj is not None:
                    chord_tones = (self._chord_plan[beat].tones
                                   if self._chord_plan and beat < len(self._chord_plan)
                                   else set())
                    bs = self._key_obj.scale_for_chord(chord_tones)
                    if len(bs) == 7 and {my_pc, fx_pc} == {bs[6], bs[0]}:
                        is_leading_tonic = True
                elif hasattr(self, '_key_scale_list') and len(self._key_scale_list) == 7:
                    leading = self._key_scale_list[6]
                    tonic = self._key_scale_list[0]
                    if {my_pc, fx_pc} == {leading, tonic}:
                        is_leading_tonic = True
                if is_leading_tonic:
                    cost += 3.0  # 導音-主音: 軽ペナルティのみ
                    continue
                cost += 1000.0  # 短2度・長7度: ハード禁止（半音衝突）
            elif ic in {2, 10}:
                cost += 5.0   # 長2度・短7度: 大ペナルティ
            elif ic == 6:
                cost += 5.0   # 三全音: 大ペナルティ

        # --- 和音充足ボーナス ---
        # 自由声部が固定声部にないPCを補完するとき大きなボーナス
        # これにより3声で根音・3音・5音が揃いやすくなる
        if hasattr(self, '_chord_plan') and beat < len(self._chord_plan):
            chord = self._chord_plan[beat]
            my_pc = pitch % 12
            chord_tones = chord.tones
            # この拍で既に鳴っているPC（固定声部）
            covered_pcs = fixed_pcs & chord_tones
            # 自由声部のPCが新しい構成音を補完するか
            if my_pc in chord_tones and my_pc not in covered_pcs:
                cost -= 4.0  # 新しい構成音を補完: 強いボーナス
            elif my_pc in covered_pcs:
                cost += 2.0  # 既に他声部が鳴らしているPCと重複: ペナルティ

            # 根音補完ボーナス: 根音が全声部から欠落する場合、根音を選ぶと追加ボーナス
            root_pc = chord.root_pc
            if root_pc not in covered_pcs and my_pc == root_pc:
                cost -= 3.0  # 根音補完: 追加ボーナス

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

def _best_octave_shift(
    midi_values: List[int], voice_range: Tuple[int, int]
) -> int:
    """voice_range 内に最も多くの音が収まるオクターブシフトを返す。

    同数の場合は絶対値が小さいシフトを優先する。
    """
    lo, hi = voice_range
    center = (lo + hi) // 2
    mc = sum(midi_values) // len(midi_values)
    base = round((center - mc) / 12) * 12
    best_shift = base
    best_score = (-1, 0)
    for shift in sorted(set([0, base, base - 12, base + 12, -12, 12]),
                        key=abs):
        in_range = sum(1 for m in midi_values if lo <= m + shift <= hi)
        score = (in_range, -abs(shift))
        if score > best_score:
            best_score = score
            best_shift = shift
    return best_shift


def fit_melody_to_range(
    melody: List[Pitch], voice_range: Tuple[int, int],
    preserve_intervals: bool = False,
) -> List[Pitch]:
    """旋律を声部音域の中央付近に配置

    オクターブ単位でシフトし、全音が音域内に収まるよう調整する。

    Args:
        preserve_intervals: True の場合、個別音のクランプを行わない
            （主題の音程構造を保持する用途）
    """
    if not melody:
        return []

    lo, hi = voice_range
    shift = _best_octave_shift([p.midi for p in melody], voice_range)

    result = []
    for p in melody:
        midi = p.midi + shift
        if preserve_intervals:
            # 音程保持モード: 個別クランプなし
            pass
        else:
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

    def __init__(self, scale: List[int], seed: Optional[int] = None,
                 force_quarter: bool = False,
                 elaborate: bool = True):
        self.scale = scale  # 使用する音階のピッチクラス集合
        self.rng = random.Random(seed)
        # elaborate=False or force_quarter=True → 全拍四分音符
        # elaborate=True → 8分音符=和声音, 16分音符=非和声音
        self.force_quarter = force_quarter and not elaborate
        self.elaborate = elaborate

    def elaborate_beat(
        self,
        skeleton_pitch: int,
        next_pitch: Optional[int],
        pattern_name: str,
        voice_range: Tuple[int, int],
        chord_tones: Optional[Set[int]] = None,
        beat_scale: Optional[List[int]] = None,
    ) -> List[Tuple[int, int]]:
        """1拍を装飾する

        Args:
            skeleton_pitch: 拍頭の骨格音（MIDIピッチ）
            next_pitch: 次の拍の骨格音（接続先、Noneなら折り返し）
            pattern_name: リズムパターン名
            voice_range: 声部音域
            chord_tones: 当該拍の和音構成音PC集合（8分音符の和声音選択用）
            beat_scale: 当該拍のスケール（コードから決定済み）。
                        指定時はインスタンスのscaleを一時的に上書き。

        Returns:
            [(MIDIピッチ, サブビート数), ...] — 合計4サブビート
        """
        # コードに基づくスケールの一時切替
        saved_scale = None
        if beat_scale is not None:
            saved_scale = self.scale
            self.scale = beat_scale
        try:
            return self._elaborate_beat_inner(
                skeleton_pitch, next_pitch, pattern_name,
                voice_range, chord_tones)
        finally:
            if saved_scale is not None:
                self.scale = saved_scale

    def _elaborate_beat_inner(
        self,
        skeleton_pitch: int,
        next_pitch: Optional[int],
        pattern_name: str,
        voice_range: Tuple[int, int],
        chord_tones: Optional[Set[int]] = None,
    ) -> List[Tuple[int, int]]:
        """elaborate_beat の内部実装"""
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

            if dur >= 2 and chord_tones:
                # 8分音符以上 → 順次進行優先、和声音を優遇しつつ経過音も許容
                pitch = self._pick_eighth_note(
                    prev_pitch, chord_tones, voice_range, target)
            elif dur == 1:
                # 16分音符 → 非和声音（経過音・刺繍音）を許容
                if slot_idx == len(pattern) - 1 and next_pitch is not None:
                    pitch = self._passing_toward(prev_pitch, target, lo, hi)
                else:
                    if self.rng.random() < 0.4:
                        pitch = self._neighbor_tone(prev_pitch, lo, hi)
                    else:
                        pitch = self._passing_toward(prev_pitch, target, lo, hi)
            else:
                # chord_tonesなし（フォールバック）: 従来の経過音ロジック
                if slot_idx == len(pattern) - 1 and next_pitch is not None:
                    pitch = self._passing_toward(prev_pitch, target, lo, hi)
                else:
                    if self.rng.random() < 0.4:
                        pitch = self._neighbor_tone(prev_pitch, lo, hi)
                    else:
                        pitch = self._passing_toward(prev_pitch, target, lo, hi)

            result.append((pitch, dur))

        return result

    def _pick_eighth_note(
        self,
        prev_pitch: int,
        chord_tones: Set[int],
        voice_range: Tuple[int, int],
        target: int,
    ) -> int:
        """8分音符用: 順次進行を優先した音選択

        対位法の原則: 旋律は順次進行（2度）が基本。
        8分音符は和声音に限定せず、適切に処理された経過音・刺繍音を許容する。

        優先順位:
        1. 順次進行で和声音 → 最良（ステップで構成音に到達）
        2. 順次進行で非和声音 → targetへの経過音として許容
           (前後が和声音であれば経過音として正当化される)
        3. 3度跳躍で和声音 → 許容（対位法的に3度は自然な跳躍）
        4. 同音保持 → フォールバック
        """
        lo, hi = voice_range

        # target方向を決定
        if target == prev_pitch:
            direction = self.rng.choice([-1, 1])
        elif target > prev_pitch:
            direction = 1
        else:
            direction = -1

        # --- 候補を順次進行 → 3度の順に探索 ---
        # step候補: 順次進行(±1,±2半音), 3度(±3,±4半音)
        step_candidates = []

        # (A) 順方向の順次進行（target方向）
        for step in [1, 2]:
            p = prev_pitch + direction * step
            p = self._snap_to_scale(p)
            if lo <= p <= hi and p != prev_pitch:
                is_chord = (p % 12) in chord_tones
                step_candidates.append((p, is_chord, abs(step)))

        # (B) 逆方向の順次進行（刺繍音的）
        for step in [1, 2]:
            p = prev_pitch - direction * step
            p = self._snap_to_scale(p)
            if lo <= p <= hi and p != prev_pitch:
                is_chord = (p % 12) in chord_tones
                step_candidates.append((p, is_chord, abs(step) + 0.5))

        # (C) 3度跳躍（和声音のみ）
        for step in [3, 4]:
            for d in [direction, -direction]:
                p = prev_pitch + d * step
                if lo <= p <= hi and (p % 12) in chord_tones:
                    step_candidates.append((p, True, step + 1.0))

        if not step_candidates:
            return prev_pitch  # フォールバック: 同音保持

        # スコア計算
        def score(item):
            p, is_chord, base_cost = item
            cost = base_cost
            if is_chord:
                cost -= 2.0  # 和声音ボーナス
            # target方向に進む場合ボーナス
            if target != prev_pitch:
                if (target > prev_pitch and p > prev_pitch) or \
                   (target < prev_pitch and p < prev_pitch):
                    cost -= 1.0
            return cost

        step_candidates.sort(key=score)

        # 上位候補からランダム選択（単調さ回避）
        top_n = min(3, len(step_candidates))
        chosen = self.rng.choice(step_candidates[:top_n])
        return chosen[0]

    def _passing_toward(self, current: int, target: int,
                        lo: int, hi: int) -> int:
        """targetに向かう順次進行の経過音"""
        if current == target:
            step = self.rng.choice([-1, 1])
        elif target > current:
            step = 1
        else:
            step = -1

        pitch = current + step
        pitch = self._snap_to_scale(pitch)
        pitch = max(lo, min(hi, pitch))
        return pitch

    def _neighbor_tone(self, current: int, lo: int, hi: int) -> int:
        """上方または下方の刺繍音"""
        direction = self.rng.choice([-1, 1])
        pitch = current + direction
        pitch = self._snap_to_scale(pitch)
        pitch = max(lo, min(hi, pitch))
        return pitch

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
        - elaborate=True: 8分音符=和声音、16分音符=非和声音
        - elaborate=False (force_quarter): 全四分音符
        """
        if not self.elaborate:
            return 'Q'  # 装飾なし: 全声部四分音符のみ

        if is_subject_voice:
            return 'Q'  # 主題声部は骨格維持

        if other_has_motion:
            # 他声部が既に動いている→四分音符寄り
            choices = ['Q', 'Q', 'EE']
        else:
            # 自由に装飾可能（8分音符中心、16分音符は控えめ）
            choices = ['EE', 'EE', 'EE', 'ES', 'Q']

        return self.rng.choice(choices)


def fit_notes_to_range(
    notes: List['NoteEvent'], voice_range: Tuple[int, int],
    preserve_intervals: bool = False,
) -> List['NoteEvent']:
    """NoteEvent版オクターブ補正（音長保持）

    Args:
        preserve_intervals: True の場合、個別音のクランプを行わない
            （主題の音程構造を保持する用途）
    """
    if not notes:
        return []
    lo, hi = voice_range
    shift = _best_octave_shift([n.pitch.midi for n in notes], voice_range)

    result = []
    for n in notes:
        midi = n.pitch.midi + shift
        if not preserve_intervals:
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
                 seed: Optional[int] = None,
                 chord_model=None,
                 counterpoint_model=None,
                 elaborate: bool = True,
                 reference_progression: Optional[List['ChordLabel']] = None):
        self.fs = fugue_structure
        self.key = fugue_structure.main_key
        self.subject = fugue_structure.subject
        self.seed = seed
        self.elaborate = elaborate  # False: 経過音・装飾音を無効化

        # 参照和声進行（バッハMIDI等から抽出、全拍分のChordLabel）
        # 指定時はテンプレート/アナライザ生成の和声計画を上書きする
        self.reference_progression = reference_progression

        # ML モデル（オプション）
        self.chord_model = chord_model          # ChordProgressionModel
        self.counterpoint_model = counterpoint_model  # CounterpointPatternModel

        # 提示部では調的安定性を優先: 七の和音・変化和音・副属七とも禁止
        # 七の和音はV7以外では短二度衝突（B-C等）を招くため全面禁止
        self.analyzer = SubjectHarmonicAnalyzer(
            self.key, seed=seed,
            seventh_freq=0.0,
            altered_freq=0.0,
            secondary_dom_freq=0.0,
        )
        self.dp = ContrapuntalDP(counterpoint_model=counterpoint_model,
                                  elaborate=elaborate)

        # 結果格納
        self.voice_melodies: Dict[FugueVoiceType, List[Optional[int]]] = {}
        self.chord_plan: List[ChordLabel] = []
        self.countersubject_midi: List[int] = []

    @staticmethod
    def _expand_subject_to_beat_pitches(subject: 'Subject') -> List[Pitch]:
        """NoteEvent列をbeat-levelに展開（各拍で鳴っているピッチを返す）

        二分音符（duration=8, 2拍分）は同じピッチを2拍分返す。
        主題長が17拍なら17要素のリストを返す。
        """
        result: List[Pitch] = []
        notes = subject.notes
        total_beats = subject.get_length()

        for beat in range(total_beats):
            beat_start_sb = beat * SUBBEATS_PER_BEAT
            # この拍の先頭で鳴っている音を探す
            acc = 0
            pitch = notes[-1].pitch  # fallback
            for n in notes:
                if acc <= beat_start_sb < acc + n.duration:
                    pitch = n.pitch
                    break
                acc += n.duration
            result.append(pitch)
        return result

    @staticmethod
    def _expand_subject_to_beat_all_pitches(subject: 'Subject') -> List[List[Pitch]]:
        """NoteEvent列をbeat-levelに展開（各拍で鳴る全ピッチを返す）

        1拍内に複数のNoteEventがある場合（例: 八分音符2つ）、
        その拍の全ピッチをリストで返す。重複は除去。
        バックトラッキングの固定声部チェック（平行判定）に使用。
        """
        notes = subject.notes
        total_beats = subject.get_length()
        result: List[List[Pitch]] = []

        for beat in range(total_beats):
            beat_start_sb = beat * SUBBEATS_PER_BEAT
            beat_end_sb = (beat + 1) * SUBBEATS_PER_BEAT
            pitches_in_beat: List[Pitch] = []
            seen_midi: set = set()
            acc = 0
            for n in notes:
                note_start = acc
                note_end = acc + n.duration
                # この拍と重複するか
                if note_start < beat_end_sb and note_end > beat_start_sb:
                    if n.pitch.midi not in seen_midi:
                        pitches_in_beat.append(n.pitch)
                        seen_midi.add(n.pitch.midi)
                acc += n.duration
            if not pitches_in_beat:
                pitches_in_beat = [notes[-1].pitch]
            result.append(pitches_in_beat)
        return result

    def _build_exposition_harmony(
        self,
        entries: List['FugueEntry'],
        subject_template: SubjectHarmonicTemplate,
        answer_template: SubjectHarmonicTemplate,
        total_beats: int,
        subject_len: int,
    ) -> List[ChordLabel]:
        """提示部全体の和声進行をトップダウンで構築

        各エントリの和声テンプレートをマージし、重複区間では
        strict/flexible の優先順位に従って衝突を解決する。

        優先順位:
          1. strict + fixed_pcs あり → 最優先（導音C#を含むV等）
          2. strict + fixed_pcs なし → 高優先
          3. flexible → 低優先（代理和音への差替え可）
        """
        # 各拍のBeatHarmonyを保持（優先順位付き）
        beat_assignments: List[Optional[BeatHarmony]] = [None] * total_beats
        # 優先度スコア: strict+fixed=3, strict=2, flexible=1, unset=0
        beat_priorities: List[int] = [0] * total_beats
        # 各拍がどのエントリのキーに属するか（C26スケール判定用）
        beat_entry_keys: List[Optional['Key']] = [None] * total_beats

        for entry in entries:
            template = answer_template if entry.is_answer else subject_template
            start = entry.start_position

            for rel_beat, bh in enumerate(template.beats):
                abs_beat = start + rel_beat
                if abs_beat >= total_beats:
                    break

                # 優先度計算
                if bh.flexibility == "strict" and bh.fixed_pcs:
                    priority = 3
                elif bh.flexibility == "strict":
                    priority = 2
                else:
                    priority = 1

                # 既存の割り当てと比較
                existing_priority = beat_priorities[abs_beat]
                if priority > existing_priority:
                    # 新しいエントリの方が優先度が高い → 上書き
                    beat_assignments[abs_beat] = bh
                    beat_priorities[abs_beat] = priority
                    beat_entry_keys[abs_beat] = entry.key
                elif priority == existing_priority and beat_assignments[abs_beat] is not None:
                    # 同優先度: fixed_pcsが多い方を採用
                    existing = beat_assignments[abs_beat]
                    if len(bh.fixed_pcs) > len(existing.fixed_pcs):
                        beat_assignments[abs_beat] = bh
                        beat_priorities[abs_beat] = priority
                        beat_entry_keys[abs_beat] = entry.key

        # BeatHarmony → ChordLabel への変換
        # 提示部は転調しない。応答テンプレートも主調内で表現されている前提。
        # 常に主調のダイアトニック和音を使用する。
        dia = self.analyzer.diatonic_chords

        result: List[ChordLabel] = []
        for beat in range(total_beats):
            bh = beat_assignments[beat]
            if bh is None:
                # エントリが存在しない拍 → 主調 I
                result.append(dia[0])
                continue

            # custom_chord があればダイアトニックルックアップを迂回
            if bh.custom_chord is not None:
                result.append(bh.custom_chord)
            else:
                degree = bh.degree
                if 0 <= degree < len(dia):
                    result.append(dia[degree])
                else:
                    result.append(dia[0])  # fallback to I

        # C26: fixed_pcs と和音構成音の半音衝突を自動修正
        # (Gédalge §52,55,69: 応答の導音は属調のドミナントとして扱う)
        #
        # 判定: fixed_pcsの±1半音が和音構成音に含まれ、かつfixed_pcs自体が
        # 和音構成音に含まれない場合、その拍の和音をfixed_pcsを含む和音に差替え。
        # ただし、fixed_pcsが主調のダイアトニック和音（自然+和声短音階）に
        # 自然に含まれる場合（例: 主調D minorのC#→V=A major）はスキップ
        # （既にダイアトニック和音がfixed_pcsを包含しているはず）。
        main_combined_scale = set(self.key.scale)
        if self.key.mode == "minor":
            main_combined_scale |= set(self.key.natural_minor_scale)
        c26_modifications = []
        c26_beat_local_keys: Dict[int, 'Key'] = {}  # C26修正拍→局所キー
        for beat in range(total_beats):
            bh = beat_assignments[beat]
            if bh is None or not bh.fixed_pcs:
                continue
            # flexible拍はNCT（非和声音）を許容 → 和音修正不要
            if bh.flexibility != "strict":
                continue
            chord = result[beat]
            for fpc in bh.fixed_pcs:
                # fixed_pcsが既に和音構成音に含まれている → 衝突なし
                if fpc in chord.tones:
                    continue
                # ±1半音が和音構成音に含まれていなければ衝突なし
                clash_pcs = {(fpc + 1) % 12, (fpc - 1) % 12}
                if not (chord.tones & clash_pcs):
                    continue
                # 衝突あり: fpcを導音としてV/xを自動生成
                # fpcは導音 → fpc+1が局所的主音 → V/xの根音 = fpc-4(長3度下)
                dominant_root_pc = (fpc - 4) % 12
                new_chord = ChordLabel(
                    degree=bh.degree,
                    root_pc=dominant_root_pc,
                    quality="major",
                    tones={dominant_root_pc, fpc, (dominant_root_pc + 7) % 12},
                )
                result[beat] = new_chord
                # 局所キー: fpc+1を主音とする短調（例: G#→Am）
                local_tonic_pc = (fpc + 1) % 12
                c26_beat_local_keys[beat] = Key(
                    local_tonic_pc, "minor")
                c26_modifications.append(beat)
                break
        if c26_modifications:
            print(f"  [C26] {len(c26_modifications)} 拍を自動修正")

        # コード進行のログ出力
        print(f"  提示部和声計画: {total_beats}拍")
        for beat, chord in enumerate(result):
            bh = beat_assignments[beat]
            prio = beat_priorities[beat]
            flex = bh.flexibility if bh else "—"
            fixed = bh.fixed_pcs if bh else set()
            active_entries = []
            for entry in entries:
                rel = beat - entry.start_position
                if 0 <= rel < subject_len:
                    label = "応答" if entry.is_answer else "主題"
                    active_entries.append(f"{entry.voice_type.value}:{label}")
            entry_str = ",".join(active_entries) if active_entries else "—"
            print(f"    beat {beat:2d}: {chord.roman:6s} "
                  f"({flex}, prio={prio}, fixed={fixed}) [{entry_str}]")

        # fixed_pcs情報をインスタンス変数に保持（リズム装飾で参照）
        self._exposition_fixed_pcs: List[FrozenSet[int]] = []
        for beat in range(total_beats):
            bh = beat_assignments[beat]
            self._exposition_fixed_pcs.append(
                bh.fixed_pcs if bh is not None else frozenset())

        return result, beat_assignments, c26_beat_local_keys

    # ============================================================
    # バックトラッキング対位法生成器
    # ============================================================

    @staticmethod
    def _cr_pairs_for_key(key: 'Key') -> Set[Tuple[int, int]]:
        """短調における対斜ペア（自然7度/導音、自然6度/長6度）を返す。

        Returns:
            Set of (lower_pc, upper_pc) tuples.
        """
        if key.mode != "minor":
            return set()
        t = key.tonic_pc
        # 自然7度 vs 導音: e.g. D minor → C(0) vs C#(1)
        nat7 = (t + 10) % 12   # 自然短7度 (♭VII)
        lead = (t + 11) % 12   # 導音 (#VII)
        # 自然6度 vs 長6度: e.g. D minor → Bb(10) vs B(11)
        nat6 = (t + 8) % 12    # 自然短6度 (♭VI)
        maj6 = (t + 9) % 12    # 長6度 (#VI)
        return {
            (min(nat7, lead), max(nat7, lead)),
            (min(nat6, maj6), max(nat6, maj6)),
        }

    def _backtrack_counterpoint(
        self,
        num_beats: int,
        chord_plan: List[ChordLabel],
        fixed_pitches: Dict[FugueVoiceType, List[Optional[int]]],
        free_voices: List[FugueVoiceType],
        voice_ranges: Dict[FugueVoiceType, Tuple[int, int]],
        prev_all_pitches: Optional[Dict[FugueVoiceType, int]] = None,
        fixed_all_pitches: Optional[Dict[FugueVoiceType, List[List[int]]]] = None,
        beat_keys: Optional[List['Key']] = None,
        cs_profiles: Optional[Dict[FugueVoiceType, List[Optional[int]]]] = None,
    ) -> Optional[Dict[FugueVoiceType, List[int]]]:
        """全自由声部を同時にバックトラッキング探索で生成する。

        各拍で全自由声部の和声音の組み合わせを列挙し、
        全声部ペア（固定-自由、自由-自由）間の禁則をチェックする。
        解がなければ1拍戻してやり直す。

        Args:
            num_beats: 生成する拍数
            chord_plan: 各拍の和声（ChordLabel）
            fixed_pitches: {声部: [拍ごとのMIDI値 or None]} 固定声部群
            free_voices: 生成対象の声部リスト（上声部から順）
            voice_ranges: {声部: (lo, hi)} 各声部の音域
            prev_all_pitches: 直前拍の全声部ピッチ（区間連続性）
            beat_keys: 各拍の調（対斜検出用）
            cs_profiles: {声部: [目標MIDI or None]} 対主題プロファイル

        Returns:
            {声部: [拍ごとのMIDI値]} or None（解なし）
        """
        if not free_voices:
            return {}

        proh = CounterpointProhibitions()

        # 声部の上下関係（ソプラノ=0が最上位）
        voice_order = {
            FugueVoiceType.SOPRANO: 0,
            FugueVoiceType.ALTO: 1,
            FugueVoiceType.TENOR: 2,
            FugueVoiceType.BASS: 3,
        }

        def is_upper(va: FugueVoiceType, vb: FugueVoiceType) -> bool:
            return voice_order[va] < voice_order[vb]

        def is_outer(va: FugueVoiceType, vb: FugueVoiceType) -> bool:
            return {va, vb} == {FugueVoiceType.SOPRANO, FugueVoiceType.BASS}

        # --- 拍ごとの候補音を事前計算 ---
        # candidates_per_beat[beat][voice_idx] = [midi, ...]
        # C26の半音衝突回避は和声計画段階（_build_exposition_harmony）で処理済み。
        # 候補フィルタは不要（和音が適切に設定されていれば衝突は生じない）。
        candidates_per_beat: List[List[List[int]]] = []
        for beat in range(num_beats):
            chord_tones_pc = chord_plan[beat].tones
            beat_cands = []
            for vt in free_voices:
                lo, hi = voice_ranges[vt]
                cands = [m for m in range(lo, hi + 1)
                         if m % 12 in chord_tones_pc]
                beat_cands.append(cands)
            candidates_per_beat.append(beat_cands)

        # --- 全声部リスト（固定 + 自由）を構築 ---
        all_voices = list(free_voices)
        for vt in fixed_pitches:
            if vt not in all_voices:
                all_voices.append(vt)

        # --- 組み合わせ検証関数 ---
        def check_combination(
            beat: int,
            combo: Tuple[int, ...],
            prev_combo: Optional[Tuple[int, ...]],
            prev_fixed: Dict[FugueVoiceType, Optional[int]],
        ) -> bool:
            """全声部ペアの禁則をチェック。

            combo: free_voices[i] → combo[i] のMIDI値
            prev_combo: 前拍の自由声部の値（beat==0ではNone可）
            prev_fixed: 前拍の固定声部の値
            """
            # 現在拍の全声部ピッチを構築
            curr_all: Dict[FugueVoiceType, int] = {}
            for i, vt in enumerate(free_voices):
                curr_all[vt] = combo[i]
            for vt, melody in fixed_pitches.items():
                if melody[beat] is not None:
                    curr_all[vt] = melody[beat]

            # 前拍の全声部ピッチを構築
            prev_all: Dict[FugueVoiceType, int] = {}
            if prev_combo is not None:
                for i, vt in enumerate(free_voices):
                    prev_all[vt] = prev_combo[i]
            elif prev_all_pitches is not None:
                for vt in free_voices:
                    if vt in prev_all_pitches and prev_all_pitches[vt] is not None:
                        prev_all[vt] = prev_all_pitches[vt]
            for vt, val in prev_fixed.items():
                if val is not None:
                    prev_all[vt] = val

            # (1) ユニゾン禁止（全ペア）
            pitches_used = list(curr_all.values())
            for i in range(len(pitches_used)):
                for j in range(i + 1, len(pitches_used)):
                    if pitches_used[i] == pitches_used[j]:
                        return False

            # (2) 声部交差禁止
            sorted_voices = sorted(curr_all.keys(), key=lambda v: voice_order[v])
            for i in range(len(sorted_voices) - 1):
                upper_v = sorted_voices[i]
                lower_v = sorted_voices[i + 1]
                if curr_all[upper_v] < curr_all[lower_v]:
                    return False

            # (3) 前拍がなければ垂直チェックのみで終了
            if not prev_all:
                return True

            # (4) 全声部ペアの並行禁止チェック
            voice_list = list(curr_all.keys())
            for i in range(len(voice_list)):
                vi = voice_list[i]
                if vi not in prev_all:
                    continue
                for j in range(i + 1, len(voice_list)):
                    vj = voice_list[j]
                    if vj not in prev_all:
                        continue

                    # 上下関係の確定
                    if is_upper(vi, vj):
                        up_v, lo_v = vi, vj
                    else:
                        up_v, lo_v = vj, vi

                    upper_p = prev_all[up_v]
                    upper_c = curr_all[up_v]
                    lower_p = prev_all[lo_v]
                    lower_c = curr_all[lo_v]

                    # 並行5度/8度
                    ok, _ = proh.check_parallel_perfect(
                        upper_p, upper_c, lower_p, lower_c)
                    if not ok:
                        return False

                    # 直接同度
                    ok, _ = proh.check_direct_unison(
                        prev_all[vi], curr_all[vi],
                        prev_all[vj], curr_all[vj])
                    if not ok:
                        return False

                    # 声部超越
                    ok, _ = proh.check_voice_overlap(
                        upper_p, upper_c, lower_p, lower_c)
                    if not ok:
                        return False

                    # 外声間の隠伏5/8度
                    if is_outer(vi, vj):
                        ok, _ = proh.check_hidden_perfect(
                            upper_p, upper_c, lower_p, lower_c, True)
                        if not ok:
                            return False

            # (4b) 固定声部のサブビート全ピッチに対する平行チェック
            # 主題/応答の最終拍など、1拍内に複数の音が存在する場合、
            # beat-start以外のピッチとの平行も検出する。
            # チェッカーはNCT分類後の和声音を使うため、この追加チェックが必要。
            if fixed_all_pitches and prev_all:
                for vt_f, all_ps in fixed_all_pitches.items():
                    if beat >= len(all_ps):
                        continue
                    beat_ps = all_ps[beat]
                    # beat-startピッチ以外の追加ピッチをチェック
                    base_pitch = fixed_pitches[vt_f][beat] if vt_f in fixed_pitches else None
                    for alt_p in beat_ps:
                        if alt_p == base_pitch:
                            continue  # beat-startは既にチェック済み
                        if vt_f not in prev_all:
                            continue
                        # 自由声部との平行チェック
                        for i_fv, vt_free in enumerate(free_voices):
                            if vt_free not in prev_all:
                                continue
                            if is_upper(vt_free, vt_f):
                                up_p, up_c = prev_all[vt_free], combo[i_fv]
                                lo_p, lo_c = prev_all[vt_f], alt_p
                            else:
                                up_p, up_c = prev_all[vt_f], alt_p
                                lo_p, lo_c = prev_all[vt_free], combo[i_fv]
                            ok, _ = proh.check_parallel_perfect(
                                up_p, up_c, lo_p, lo_c)
                            if not ok:
                                return False

            # (5) 自由声部の旋律制約（増音程・7度跳躍禁止）
            for i, vt in enumerate(free_voices):
                if vt not in prev_all:
                    continue
                prev_midi = prev_all[vt]
                curr_midi = combo[i]
                ok, _ = proh.check_melodic_augmented(prev_midi, curr_midi)
                if not ok:
                    return False
                ok, _ = proh.check_melodic_seventh(prev_midi, curr_midi)
                if not ok:
                    return False

            # (6) 対斜: ソフトペナルティに委ねる（硬制約ではない）
            # 理由: 調境界では和声進行自体が対斜を強制する場合がある
            # (例: D minor V の C# → A minor i の C)
            # score_combination() でペナルティを加算する。

            return True

        # --- 組み合わせのスコアリング（順次進行を好む） ---
        def score_combination(
            beat: int,
            combo: Tuple[int, ...],
            prev_combo: Optional[Tuple[int, ...]],
        ) -> float:
            """低い方が良い。順次進行（2半音以内）にボーナス。"""
            cost = 0.0
            for i, vt in enumerate(free_voices):
                prev_midi = None
                if prev_combo is not None:
                    prev_midi = prev_combo[i]
                elif prev_all_pitches and vt in prev_all_pitches:
                    prev_midi = prev_all_pitches[vt]

                if prev_midi is not None:
                    interval = abs(combo[i] - prev_midi)
                    if interval == 0:
                        cost += 4.0     # 同音保持: ペナルティ
                    elif interval <= 2:
                        cost -= 1.0     # 順次進行: ボーナス
                    elif interval <= 4:
                        cost += 0.5     # 3度: 許容
                    elif interval <= 7:
                        cost += 2.0     # 4-5度: ペナルティ
                    else:
                        cost += 5.0     # 6度以上: 大ペナルティ

                # 対主題プロファイルへの誘導（ソフトボーナス）
                if cs_profiles and vt in cs_profiles:
                    profile = cs_profiles[vt]
                    if beat < len(profile) and profile[beat] is not None:
                        dist = abs(combo[i] - profile[beat])
                        if dist == 0:
                            cost -= 2.0
                        elif dist <= 2:
                            cost -= 1.0
                        elif dist <= 4:
                            cost += 0.0
                        else:
                            cost += 0.5

            # 反行ボーナス: 固定声部との間で反行していればボーナス
            if prev_combo is not None:
                for vt_f, melody in fixed_pitches.items():
                    if melody[beat] is None or (beat > 0 and melody[beat - 1] is None):
                        continue
                    fixed_motion = melody[beat] - melody[beat - 1]
                    for i, vt in enumerate(free_voices):
                        free_motion = combo[i] - prev_combo[i]
                        if fixed_motion != 0 and free_motion != 0:
                            if (fixed_motion > 0) != (free_motion > 0):
                                cost -= 0.5  # 反行ボーナス

            # 対斜ペナルティ（ソフト制約）
            if beat_keys and prev_combo is not None:
                b_abs = beat  # section-local beat
                if b_abs > 0 or prev_all_pitches:
                    curr_key = beat_keys[b_abs] if b_abs < len(beat_keys) else None
                    prev_key_idx = b_abs - 1
                    prev_key = beat_keys[prev_key_idx] if prev_key_idx >= 0 and prev_key_idx < len(beat_keys) else None
                    cr_pairs_set: Set[Tuple[int, int]] = set()
                    if curr_key:
                        cr_pairs_set |= self._cr_pairs_for_key(curr_key)
                    if prev_key:
                        cr_pairs_set |= self._cr_pairs_for_key(prev_key)
                    if cr_pairs_set:
                        prev_pcs_set = set()
                        curr_pcs_set = set()
                        for i2, vt2 in enumerate(free_voices):
                            curr_pcs_set.add(combo[i2] % 12)
                            if prev_combo is not None:
                                prev_pcs_set.add(prev_combo[i2] % 12)
                        # 固定声部のPCも追加
                        for vt2, mel in fixed_pitches.items():
                            if beat < len(mel) and mel[beat] is not None:
                                curr_pcs_set.add(mel[beat] % 12)
                            if beat > 0 and (beat - 1) < len(mel) and mel[beat - 1] is not None:
                                prev_pcs_set.add(mel[beat - 1] % 12)
                        if prev_all_pitches and beat == 0:
                            for vt2, pm in prev_all_pitches.items():
                                if pm is not None:
                                    prev_pcs_set.add(pm % 12)
                        for lo_pc, hi_pc in cr_pairs_set:
                            if (lo_pc in prev_pcs_set and hi_pc in curr_pcs_set) or \
                               (hi_pc in prev_pcs_set and lo_pc in curr_pcs_set):
                                cost += 50.0  # 対斜: 強いペナルティだが回避不能なら許容

            return cost

        # --- バックトラッキング探索 ---
        import itertools

        # 結果: solution[beat] = (combo, combo_index_in_sorted_list)
        solution: List[Optional[Tuple[Tuple[int, ...], int]]] = [None] * num_beats

        # 各拍の前拍固定ピッチを事前計算
        def get_prev_fixed(beat: int) -> Dict[FugueVoiceType, Optional[int]]:
            result: Dict[FugueVoiceType, Optional[int]] = {}
            if beat == 0:
                if prev_all_pitches:
                    for vt in fixed_pitches:
                        if vt in prev_all_pitches:
                            result[vt] = prev_all_pitches[vt]
            else:
                for vt, melody in fixed_pitches.items():
                    result[vt] = melody[beat - 1]
            return result

        beat = 0
        max_backtrack_depth = 16  # セクション全長までバックトラック可

        while beat < num_beats:
            beat_candidates_lists = candidates_per_beat[beat]

            # 前拍の情報
            prev_combo = None
            if beat > 0 and solution[beat - 1] is not None:
                prev_combo = solution[beat - 1][0]
            pf = get_prev_fixed(beat)

            # 全自由声部の和声音の直積
            all_combos = list(itertools.product(*beat_candidates_lists))

            # 有効な組み合わせをフィルタリング
            valid_scored: List[Tuple[float, int, Tuple[int, ...]]] = []
            for combo in all_combos:
                if check_combination(beat, combo, prev_combo, pf):
                    score = score_combination(beat, combo, prev_combo)
                    valid_scored.append((score, id(combo), combo))

            # スコア順にソート（低い方が良い）
            valid_scored.sort()

            # 前回この拍でどこまで試したか
            start_idx = 0
            if solution[beat] is not None:
                # バックトラックで戻ってきた場合: 前回の次から試す
                start_idx = solution[beat][1] + 1
                solution[beat] = None

            found = False
            for idx in range(start_idx, len(valid_scored)):
                solution[beat] = (valid_scored[idx][2], idx)
                found = True
                break

            if found:
                beat += 1
            else:
                # バックトラック: 1拍戻る
                solution[beat] = None
                beat -= 1
                if beat < 0 or (num_beats - 1 - beat) > max_backtrack_depth:
                    # 解なし
                    return None

        # --- 結果を辞書に変換 ---
        result: Dict[FugueVoiceType, List[int]] = {
            vt: [] for vt in free_voices
        }
        for beat_idx in range(num_beats):
            combo = solution[beat_idx][0]
            for i, vt in enumerate(free_voices):
                result[vt].append(combo[i])

        return result

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
            entries = self.fs.create_exposition(
                answer_type="auto", overlap=self.fs.entry_overlap)

        subject_len = self.subject.get_length()

        # --- 和声テンプレート構築 ---
        # 手動指定があればそれを使用、なければアナライザで自動導出
        if self.subject.harmonic_template is not None:
            subject_template = self.subject.harmonic_template
            print("  和声テンプレート: 手動指定")
        else:
            self.chord_plan = self.analyzer.analyze(self.subject)
            subject_template = SubjectHarmonicTemplate.from_analyzer(
                self.chord_plan, self.key)
            print("  和声テンプレート: アナライザ自動導出")

        # 応答テンプレート: 手動指定があればそれを使用（主調内表現）
        # なければ主題テンプレートを属調に移調（従来の自動生成）
        if self.subject.answer_harmonic_template is not None:
            answer_template = self.subject.answer_harmonic_template
            print("  応答和声テンプレート: 手動指定（主調内表現）")
        else:
            dom_pc = self.key.dominant_pc
            from fugue_structure import PC_TO_NOTE
            dom_note = PC_TO_NOTE.get(dom_pc, 'A')
            dom_key = Key(dom_note, "minor" if self.key.mode == "minor" else "major")
            interval = (dom_key.tonic_pc - self.key.tonic_pc) % 12
            answer_template = subject_template.transpose(interval)
            print("  応答和声テンプレート: 自動移調")

        # アナライザの chord_plan も生成（DP の diatonic_chords 参照用に必要）
        if not self.chord_plan:
            self.chord_plan = self.analyzer.analyze(self.subject)

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

        first_voice_center = None
        for entry_idx, entry in enumerate(entries):
            voice = entry.voice_type
            start = entry.start_position
            entry_start[voice] = start

            # NoteEvent主題をbeat-levelに展開（二分音符→2拍分同じピッチ）
            beat_pitches = self._expand_subject_to_beat_pitches(entry.subject)
            if entry_idx <= 1:
                # 第1・第2エントリ: 主題/応答の原音高をそのまま使用
                # （get_answer()が正しい絶対音高を生成済み）
                fitted = beat_pitches
                if entry_idx == 0:
                    first_voice_center = sum(
                        (VOICE_RANGES[voice][0], VOICE_RANGES[voice][1])
                    ) // 2
            else:
                # 第3エントリ以降: 第1声部との声部音域差でオクターブ補正
                this_center = (VOICE_RANGES[voice][0]
                               + VOICE_RANGES[voice][1]) // 2
                octave_diff = round(
                    (this_center - first_voice_center) / 12) * 12
                fitted = [Pitch(p.midi + octave_diff) for p in beat_pitches]
            for i, p in enumerate(fitted):
                abs_beat = start + i
                if abs_beat < total_beats:
                    melodies[voice][abs_beat] = p.midi

        # --- Phase C: 提示部全体の和声進行を構築（トップダウン） ---
        self.exposition_chords, beat_assignments, c26_local_keys = \
            self._build_exposition_harmony(
                entries, subject_template, answer_template,
                total_beats, subject_len)

        # 参照和声進行があれば提示部の和声計画を上書き
        if self.reference_progression is not None:
            ref = self.reference_progression
            overwritten = 0
            for beat in range(min(total_beats, len(ref))):
                self.exposition_chords[beat] = ref[beat]
                overwritten += 1
            if overwritten > 0:
                print(f"  参照和声進行で提示部を上書き: {overwritten}拍")

        exposition_chords = self.exposition_chords

        # 提示部の拍→調マップを構築 (C26: Gédalge §52,55,69)
        # 基本は全拍が主調。C26修正拍は局所的に属調に切り替え。
        # これにより対位法生成時のスケール候補が局所キーに基づく。
        expo_beat_key_map: Dict[int, Key] = {}
        for b in range(total_beats):
            expo_beat_key_map[b] = self.key
        # C26修正拍: 局所キー（属調）に切り替え
        for b, local_key in c26_local_keys.items():
            expo_beat_key_map[b] = local_key
        self._expo_beat_key_map = expo_beat_key_map
        self._expo_beat_assignments = beat_assignments  # 参照用に保持

        # DPに音階情報を渡す（候補音の全音階拡張のため）
        # _key_obj は各DP呼び出し前に区間の調に設定し直す
        self.dp._key_obj = self.key  # デフォルト（後で上書き）
        self.dp._key_scale = set(self.key.scale)
        self.dp._key_scale_list = list(self.key.scale)  # 増2度検出用（順序保持）

        # --- Phase D: バックトラッキング対位法生成 ---
        #
        # 各エントリ入場時に、全自由声部を同時に生成する。
        # 全声部ペア（固定-自由、自由-自由）間の禁則を拍ごとに検証し、
        # 解がなければ1拍戻ってやり直す。
        #
        # BWV 1080 (entries at 0, 16, 32, 48, subject_len=16):
        #   beats  0-15: alto subject     → 自由声部なし
        #   beats 16-31: soprano answer   → alto が自由（1声部）
        #   beats 32-47: bass subject     → soprano + alto が自由（2声部）
        #   beats 48-63: tenor answer     → soprano + alto + bass が自由（3声部）

        for entry_idx in range(1, len(entries)):
            entry = entries[entry_idx]
            curr_start = entry.start_position
            curr_end = min(curr_start + subject_len, total_beats)

            prev_entry = entries[entry_idx - 1]
            prev_end = prev_entry.start_position + subject_len

            # (a) コデッタ区間の充填（バックトラッキングで対位法規則を遵守）
            if prev_end < curr_start:
                codetta_start = prev_end
                codetta_end = curr_start
                codetta_len = codetta_end - codetta_start

                # 固定声部と自由声部を判定
                codetta_fixed: Dict[FugueVoiceType, List[Optional[int]]] = {}
                codetta_free: List[FugueVoiceType] = []
                for prev_idx in range(entry_idx):
                    pv = entries[prev_idx].voice_type
                    section = [melodies[pv][b] for b in range(codetta_start, codetta_end)]
                    if all(v is not None for v in section):
                        codetta_fixed[pv] = section
                    else:
                        codetta_free.append(pv)

                if codetta_free:
                    # 区間の和声進行
                    codetta_chords = exposition_chords[codetta_start:codetta_end]
                    # 区間の調マップ
                    codetta_beat_keys = [expo_beat_key_map.get(codetta_start + b, self.key)
                                         for b in range(codetta_len)]
                    # 前拍ピッチ
                    prev_pitches: Dict[FugueVoiceType, int] = {}
                    if codetta_start > 0:
                        for vt in FugueVoiceType:
                            if melodies[vt][codetta_start - 1] is not None:
                                prev_pitches[vt] = melodies[vt][codetta_start - 1]

                    bt_result = self._backtrack_counterpoint(
                        num_beats=codetta_len,
                        chord_plan=codetta_chords,
                        fixed_pitches=codetta_fixed,
                        free_voices=codetta_free,
                        voice_ranges=VOICE_RANGES,
                        prev_all_pitches=prev_pitches if prev_pitches else None,
                        beat_keys=codetta_beat_keys,
                    )
                    if bt_result:
                        for vt, pitches in bt_result.items():
                            for i, midi_val in enumerate(pitches):
                                b = codetta_start + i
                                if b < total_beats:
                                    melodies[vt][b] = midi_val

            # (b) エントリ区間: 全自由声部を同時にバックトラッキング生成
            section_len = curr_end - curr_start
            section_chords = exposition_chords[curr_start:curr_end]

            # 固定声部（主題/応答を含む）と自由声部の判定
            section_fixed: Dict[FugueVoiceType, List[Optional[int]]] = {}
            section_free: List[FugueVoiceType] = []

            # 全入場済み声部 + 現エントリ声部をチェック
            active_voices: Set[FugueVoiceType] = set()
            for idx in range(entry_idx + 1):
                active_voices.add(entries[idx].voice_type)

            for vt in active_voices:
                section = [melodies[vt][b] for b in range(curr_start, curr_end)]
                if all(v is not None for v in section):
                    # 主題/応答が入っている → 固定
                    section_fixed[vt] = section
                elif any(v is None for v in section):
                    # Noneがある → 自由声部
                    section_free.append(vt)

            # 声部順序で並べ替え（ソプラノ→バス）
            section_free.sort(key=lambda v: {
                FugueVoiceType.SOPRANO: 0, FugueVoiceType.ALTO: 1,
                FugueVoiceType.TENOR: 2, FugueVoiceType.BASS: 3}[v])

            if not section_free:
                continue

            # 区間の調マップ
            section_beat_keys = [expo_beat_key_map.get(curr_start + b, self.key)
                                  for b in range(section_len)]

            # 前拍ピッチ（区間連続性のため）
            prev_pitches = {}
            if curr_start > 0:
                for vt in FugueVoiceType:
                    if melodies[vt][curr_start - 1] is not None:
                        prev_pitches[vt] = melodies[vt][curr_start - 1]

            # 対主題プロファイル構築
            cs_profiles: Optional[Dict[FugueVoiceType, List[Optional[int]]]] = None
            if entry_idx >= 2 and self.countersubject_midi:
                cs_profiles = {}
                for pv in section_free:
                    cs = self.countersubject_midi
                    cs_center = sum(cs) / len(cs)
                    pv_center = (VOICE_RANGES[pv][0]
                                 + VOICE_RANGES[pv][1]) / 2
                    octave_shift = round((pv_center - cs_center) / 12) * 12

                    interval_shift = 0
                    if entry.is_answer != entries[1].is_answer:
                        interval_shift = 7 if entry.is_answer else -7

                    profile = [
                        p + octave_shift + interval_shift
                        for p in cs[:section_len]
                    ]
                    lo_pv, hi_pv = VOICE_RANGES[pv]
                    profile = [max(lo_pv, min(hi_pv, p)) for p in profile]
                    cs_profiles[pv] = profile

            # 固定声部のサブビート全ピッチを構築（平行チェック用）
            section_fixed_all: Optional[Dict[FugueVoiceType, List[List[int]]]] = None
            for idx in range(entry_idx + 1):
                e = entries[idx]
                if e.voice_type in section_fixed:
                    all_beat_ps = self._expand_subject_to_beat_all_pitches(e.subject)
                    # オクターブ補正: fit_melody_to_rangeと同じシフトを適用
                    # section_fixed の beat-start 値との差からシフト量を推定
                    beat0_raw = all_beat_ps[0][0].midi if all_beat_ps[0] else None
                    beat0_actual = section_fixed[e.voice_type][0]
                    if beat0_raw is not None and beat0_actual is not None:
                        shift = beat0_actual - beat0_raw
                        shifted_all: List[List[int]] = []
                        for ps in all_beat_ps:
                            shifted_all.append([p.midi + shift for p in ps])
                        if section_fixed_all is None:
                            section_fixed_all = {}
                        section_fixed_all[e.voice_type] = shifted_all

            print(f"  entry {entry_idx}: 固定={[v.value for v in section_fixed]}, "
                  f"自由={[v.value for v in section_free]}, "
                  f"beats {curr_start}-{curr_end-1}")

            bt_result = self._backtrack_counterpoint(
                num_beats=section_len,
                chord_plan=section_chords,
                fixed_pitches=section_fixed,
                free_voices=section_free,
                voice_ranges=VOICE_RANGES,
                prev_all_pitches=prev_pitches if prev_pitches else None,
                fixed_all_pitches=section_fixed_all,
                beat_keys=section_beat_keys,
                cs_profiles=cs_profiles,
            )

            if bt_result:
                for vt, pitches in bt_result.items():
                    for i, midi_val in enumerate(pitches):
                        b = curr_start + i
                        if b < total_beats and melodies[vt][b] is None:
                            melodies[vt][b] = midi_val
                print(f"    → 解あり")

                # 第2エントリでの生成結果を対主題として確定
                if entry_idx == 1 and not self.countersubject_midi:
                    # 最初の自由声部（entry 0の声部）の結果を対主題とする
                    first_free = section_free[0]
                    cs_result = bt_result[first_free]
                    self.countersubject_midi = cs_result
                    print(f"  対主題確定: {len(cs_result)}拍, "
                          f"音域 {min(cs_result)}-{max(cs_result)}")
            else:
                print(f"    → 解なし（バックトラッキング失敗）")
                # フォールバック: 従来のDP逐次生成
                for prev_idx in range(entry_idx):
                    pv = entries[prev_idx].voice_type
                    needs_fill = any(
                        melodies[pv][b] is None
                        for b in range(curr_start, curr_end))
                    if not needs_fill:
                        continue
                    fixed = {}
                    for other_idx in range(entry_idx + 1):
                        ov = entries[other_idx].voice_type
                        if ov == pv:
                            continue
                        sm = [melodies[ov][b] for b in range(curr_start, curr_end)]
                        if any(v is not None for v in sm):
                            sm = self._interpolate_nones(sm)
                            fixed[ov.value] = sm
                    if not fixed:
                        continue
                    prev_note = None
                    if curr_start > 0 and melodies[pv][curr_start - 1] is not None:
                        prev_note = melodies[pv][curr_start - 1]
                    entry_key = entry.key
                    self.dp._key_obj = entry_key
                    self.dp._key_scale = set(entry_key.scale)
                    self.dp._key_scale_list = list(entry_key.scale)
                    result = self.dp.generate(
                        num_beats=section_len,
                        chord_plan=section_chords,
                        voice_range=VOICE_RANGES[pv],
                        fixed_voices=fixed,
                        free_voice_name=pv.value,
                        start_from=prev_note,
                    )
                    for i, midi_val in enumerate(result):
                        b = curr_start + i
                        if b < total_beats and melodies[pv][b] is None:
                            melodies[pv][b] = midi_val

        # --- Phase E: 和音充足検証・修復 ---
        # 主題拍を収集（修正対象外）
        # subject.get_length() で拍数を取得（subject.pitches は NoteEvent 数で不正確）
        _subject_beats: Dict[FugueVoiceType, Set[int]] = {
            vt: set() for vt in FugueVoiceType
        }
        for entry in entries:
            start = entry.start_position
            length = entry.subject.get_length()  # 拍数（NoteEvent数ではない）
            for b in range(start, start + length):
                if b < total_beats:
                    _subject_beats[entry.voice_type].add(b)

        melodies, exposition_chords = self._verify_and_repair_chord_coverage(
            melodies, exposition_chords, subject_beats=_subject_beats,
            allow_chord_modification=False)  # トップダウン和声計画を保護
        self.exposition_chords = exposition_chords  # 和声計画は不変のまま

        # --- Phase F: サブビートグリッド構築 ---
        # beat-level melodies → subbeat-level grid
        # 主題は元のNoteEvent音長を反映、DP生成部はリズム装飾
        subbeat_grid = self._build_subbeat_grid(
            melodies, entries, total_beats,
            chord_plan=exposition_chords)

        # --- Phase G: 後処理なし ---
        # VNS・修復は行わない。DPの出力をそのまま評価し、
        # 禁則違反があれば候補ごと破棄して別seedで再生成する。

        self.voice_melodies = melodies      # beat-level（レポート用）
        self.subbeat_grid = subbeat_grid    # subbeat-level（MIDI出力用）
        self._expo_entries = entries         # 提示部エントリ情報（beat_key_map構築用）

        return self._to_midi_events_subbeat(subbeat_grid)

    # ============================================================
    # 古典和声に基づく転調手順
    # ============================================================

    def _build_modulation_chords(
        self, old_key: Key, new_key: Key,
        melody_pcs: List[int], num_beats: int,
    ) -> List[ChordLabel]:
        """古典和声の手順に従った転調和声列を生成する。

        構造（num_beats >= 4 の場合）:
          [旧調確立: 1+拍] → [ピボット: 1拍] → [新調V(7): 1拍] → [新調I: 1+拍]

        Args:
            old_key: 転調前の調
            new_key: 転調先の調
            melody_pcs: 各拍の旋律のピッチクラス列
            num_beats: この区間の拍数（>=4 を前提）

        Returns:
            num_beats 個の ChordLabel リスト
        """
        rules = HarmonyRules()

        # 旧調と新調のアナライザ
        old_analyzer = SubjectHarmonicAnalyzer(
            old_key, seed=self.seed, seventh_freq=0.0,
            secondary_dom_freq=0.0, altered_freq=0.0)
        new_analyzer = SubjectHarmonicAnalyzer(
            new_key, seed=self.seed, seventh_freq=0.0,
            secondary_dom_freq=0.0, altered_freq=0.0)

        result: List[ChordLabel] = []

        # 転換点の位置を決定:
        # 旧調確立に少なくとも1拍、新調確立に少なくとも1拍
        # ピボット+V で2拍使うので、残りを前後に分配
        pivot_beat = max(1, (num_beats - 2) // 2)  # ピボットの位置
        v_beat = pivot_beat + 1                     # 新調Vの位置
        resolve_beat = v_beat + 1                   # 新調Iの位置（解決）

        # --- 旧調確立区間 (beat 0 ~ pivot_beat-1) ---
        for b in range(pivot_beat):
            pc = melody_pcs[b] if b < len(melody_pcs) else old_key.tonic_pc
            candidates = old_analyzer.find_containing_chords(pc)
            if candidates:
                # 機能進行を考慮: 最初はI系、後半はS/D系を好む
                if b == pivot_beat - 1:
                    # ピボット直前: サブドミナント系を好む（IV, ii）
                    sd = [c for c in candidates if c.degree in (1, 3)]
                    result.append(sd[0] if sd else candidates[0])
                else:
                    result.append(candidates[0])
            else:
                # 旋律音を含む和音がない場合: I度で代替
                result.append(old_analyzer.diatonic_chords[0])

        # --- ピボットコード (pivot_beat) ---
        pivots = SubjectHarmonicAnalyzer.find_pivot_chords(old_key, new_key)
        pivot_pc = melody_pcs[pivot_beat] if pivot_beat < len(melody_pcs) else None

        pivot_chord = None
        if pivots:
            # 旋律音を含むピボットコードを優先
            if pivot_pc is not None:
                for fc, tc in pivots:
                    if pivot_pc in fc.tones:
                        pivot_chord = fc  # 旧調側の解釈で記録
                        break
            if pivot_chord is None:
                pivot_chord = pivots[0][0]  # 最優先のピボット
        else:
            # 共通和音が見つからない場合: 旧調のIV度で代替
            pivot_chord = old_analyzer.diatonic_chords[3]
        result.append(pivot_chord)

        # --- 新調のV(7) (v_beat) ---
        dom_root = new_key.dominant_pc
        dom_tones = rules.build_seventh_chord(dom_root, "dominant7")
        v7_chord = ChordLabel(
            degree=4, root_pc=dom_root, quality="dominant7",
            tones=set(dom_tones), has_seventh=True,
            seventh_pc=dom_tones[3],
        )
        if v_beat < num_beats:
            result.append(v7_chord)

        # --- 新調のI（解決）+ 新調内継続 ---
        tonic_chord = new_analyzer.diatonic_chords[0]  # 新調のI度
        for b in range(resolve_beat, num_beats):
            if b == resolve_beat:
                # 解決: 新調I度
                result.append(tonic_chord)
            else:
                # 新調内の継続: 旋律に合う和音を選択
                pc = melody_pcs[b] if b < len(melody_pcs) else new_key.tonic_pc
                candidates = new_analyzer.find_containing_chords(pc)
                if candidates:
                    result.append(candidates[0])
                else:
                    result.append(tonic_chord)

        # 長さ調整（安全策）
        while len(result) < num_beats:
            result.append(tonic_chord)
        result = result[:num_beats]

        return result

    def _build_abbreviated_modulation(
        self, old_key: Key, new_key: Key,
        melody_pcs: List[int], num_beats: int,
    ) -> List[ChordLabel]:
        """3拍以下の短い転調: ピボット省略、V→I で即座に解決

        構造:
          beat 0: 旧調の和音（旋律に合致）
          beat -2: 新調のV(7)
          beat -1: 新調のI

        Args:
            old_key: 転調前の調
            new_key: 転調先の調
            melody_pcs: 各拍の旋律のピッチクラス列
            num_beats: この区間の拍数（1〜3）

        Returns:
            num_beats 個の ChordLabel リスト
        """
        rules = HarmonyRules()
        old_analyzer = SubjectHarmonicAnalyzer(
            old_key, seed=self.seed, seventh_freq=0.0,
            secondary_dom_freq=0.0, altered_freq=0.0)
        new_analyzer = SubjectHarmonicAnalyzer(
            new_key, seed=self.seed, seventh_freq=0.0,
            secondary_dom_freq=0.0, altered_freq=0.0)

        result: List[ChordLabel] = []

        if num_beats == 1:
            # 1拍: 新調のV(7)のみ（次の区間でI度解決を期待）
            dom_root = new_key.dominant_pc
            dom_tones = rules.build_seventh_chord(dom_root, "dominant7")
            result.append(ChordLabel(
                degree=4, root_pc=dom_root, quality="dominant7",
                tones=set(dom_tones), has_seventh=True,
                seventh_pc=dom_tones[3],
            ))
        elif num_beats == 2:
            # 2拍: V(7) → I
            dom_root = new_key.dominant_pc
            dom_tones = rules.build_seventh_chord(dom_root, "dominant7")
            result.append(ChordLabel(
                degree=4, root_pc=dom_root, quality="dominant7",
                tones=set(dom_tones), has_seventh=True,
                seventh_pc=dom_tones[3],
            ))
            result.append(new_analyzer.diatonic_chords[0])
        else:
            # 3拍: 旧調の和音 → V(7) → I
            pc = melody_pcs[0] if melody_pcs else old_key.tonic_pc
            candidates = old_analyzer.find_containing_chords(pc)
            result.append(candidates[0] if candidates else old_analyzer.diatonic_chords[0])

            dom_root = new_key.dominant_pc
            dom_tones = rules.build_seventh_chord(dom_root, "dominant7")
            result.append(ChordLabel(
                degree=4, root_pc=dom_root, quality="dominant7",
                tones=set(dom_tones), has_seventh=True,
                seventh_pc=dom_tones[3],
            ))
            result.append(new_analyzer.diatonic_chords[0])

        return result

    def _avoid_leading_tone_in_short_segment(
        self, plan: List[ChordLabel], key: Key,
        pitches: List['Pitch'],
    ) -> List[ChordLabel]:
        """短い短調区間で導音（和声的短音階の第7音）を含む和音を回避する。

        短調の V 度（例: A minor の E major = E,G#,B）と
        vii° 度（G# diminished）は導音 G# を含み、
        短い経過的転調では不自然な半音階的衝突を起こす。

        置換規則:
          V (major)  → v (minor): E,G#,B → E,G,B
          vii° (dim) → VII (major): G#,B,D → G,B,D
        自然短音階の対応する和音に置き換える。
        """
        # 自然短音階の第7音（半音下げ）
        tonic_pc = key.tonic_pc
        # 和声的短音階の第7音 = tonic - 1 (半音)
        harmonic_7th = (tonic_pc - 1) % 12   # 例: A minor → G# (pc=8)
        natural_7th = (tonic_pc - 2) % 12    # 例: A minor → G  (pc=7)

        from harmony_rules_complete import HarmonyRules
        rules = HarmonyRules()

        result = []
        for ch in plan:
            if harmonic_7th in ch.tones:
                # 導音を含む和音 → 自然短音階の和音に置換
                new_tones = set()
                for t in ch.tones:
                    if t == harmonic_7th:
                        new_tones.add(natural_7th)
                    else:
                        new_tones.add(t)

                # 和音品質を更新
                new_quality = ch.quality
                if ch.degree == 4 and ch.quality == "major":
                    new_quality = "minor"  # V → v
                elif ch.degree == 6 and ch.quality == "diminished":
                    new_quality = "major"  # vii° → VII
                elif ch.quality == "dominant7":
                    new_quality = "minor7"  # V7 → v7

                result.append(ChordLabel(
                    degree=ch.degree,
                    root_pc=ch.root_pc if ch.root_pc != harmonic_7th
                            else natural_7th,
                    quality=new_quality,
                    tones=new_tones,
                    is_secondary=ch.is_secondary,
                    has_seventh=ch.has_seventh,
                    seventh_pc=natural_7th if ch.seventh_pc == harmonic_7th
                               else ch.seventh_pc,
                ))
            else:
                result.append(ch)

        return result

    def _refine_chord_plan_with_model(
        self, chord_plan: List[ChordLabel],
        pitches: List['Pitch'], key_path: 'KeyPath',
    ) -> List[ChordLabel]:
        """学習済みの和声進行モデルで和声計画を改善する。

        既存のルールベース計画をベースに、バイグラム確率が低い遷移を
        モデルが好む和音に置換する。

        制約:
        - 候補は現在の調のダイアトニック和音（三和音＋属七）に限定
        - 旋律音を構成音に含む和音のみ
        - 始点・終点の和音は保持
        """
        if not self.chord_model or len(chord_plan) < 3:
            return chord_plan

        import random as rng_mod
        from bach_harmony_model import CHORD_TEMPLATES
        rng = rng_mod.Random(self.seed)
        model = self.chord_model
        refined = list(chord_plan)

        # 調ごとのダイアトニック和音キャッシュ
        _diatonic_cache: Dict[int, List[ChordLabel]] = {}

        def get_diatonic(k) -> List[ChordLabel]:
            """指定調のダイアトニック三和音のみを取得（七の和音は除外）"""
            cache_key = k.tonic_pc * 2 + (0 if k.mode == "major" else 1)
            if cache_key not in _diatonic_cache:
                analyzer = SubjectHarmonicAnalyzer(
                    k, seed=self.seed,
                    seventh_freq=0.0, secondary_dom_freq=0.0,
                    altered_freq=0.0)
                _diatonic_cache[cache_key] = list(analyzer.diatonic_chords)
            return _diatonic_cache[cache_key]

        for beat in range(1, len(refined) - 1):
            curr_key = key_path.key_at(beat) if key_path else self.key
            tonic_pc = curr_key.tonic_pc

            prev = refined[beat - 1]
            prev_rel = ((prev.root_pc - tonic_pc) % 12, prev.quality)

            # 旋律音
            mel_pc = pitches[beat].midi % 12 if beat < len(pitches) else 0

            # 現在の調のダイアトニック和音から、旋律音を含むもののみ候補にする
            diatonic = get_diatonic(curr_key)
            candidates = []
            for dc in diatonic:
                if mel_pc in dc.tones:
                    # モデルの相対表現に変換
                    rel_root = (dc.root_pc - tonic_pc) % 12
                    candidates.append((rel_root, dc.quality))

            if not candidates:
                continue

            # モデルで選択
            selected = model.select_chord(
                prev_rel, mel_pc, tonic_pc, candidates, rng,
                temperature=0.8)

            # 選択されたコードに対応するダイアトニック ChordLabel を取得
            sel_root, sel_quality = selected
            abs_root = (sel_root + tonic_pc) % 12

            # ダイアトニックから一致するものを探す（degree が正確）
            matched = None
            for dc in diatonic:
                if dc.root_pc == abs_root and dc.quality == sel_quality:
                    matched = dc
                    break

            if matched is not None:
                refined[beat] = matched
            else:
                # フォールバック: 手動でChordLabelを構築
                tones_template = CHORD_TEMPLATES.get(sel_quality, {0, 4, 7})
                tones = {(abs_root + iv) % 12 for iv in tones_template}
                # 音階度数を正しく算出
                scale = curr_key.scale
                degree = next(
                    (i for i, s in enumerate(scale) if s == abs_root), 0)
                refined[beat] = ChordLabel(
                    degree=degree,
                    root_pc=abs_root,
                    quality=sel_quality,
                    tones=tones,
                )

        return refined

    def realize_episode(
        self,
        episode: Episode,
        start_beat: int,
        leading_voice: FugueVoiceType,
        expo_midi: Dict[FugueVoiceType, List[Tuple[int, int, int]]],
        key_path_strategy: Optional[KeyPathStrategy] = None,
    ) -> Dict[FugueVoiceType, List[Tuple[int, int, int]]]:
        """嬉遊部を実現する

        Prout Ch.VII: エピソードは主題の断片（動機）を反復進行で展開し、
        次の主題提示の調性へ導く。

        Args:
            episode: Episode オブジェクト
            start_beat: 嬉遊部の開始拍（提示部終了拍）
            leading_voice: 動機を担当する声部
            expo_midi: 提示部のMIDIデータ（接続音の参照用）
            key_path_strategy: 調性経路の生成戦略（差し替え可能）。
                Noneならデフォルト戦略を使用。
                学習済みモデルを注入する際はここを差し替える。

        Returns:
            {voice: [(start_tick, midi, duration_tick), ...]}
        """
        ep_pitches = episode.generate_pitches()
        ep_length = len(ep_pitches)  # 拍数

        # --- Phase A: 動機声部の配置 ---
        fitted = fit_melody_to_range(ep_pitches, VOICE_RANGES[leading_voice])

        melodies: Dict[FugueVoiceType, List[Optional[int]]] = {}
        # 提示部で実際に音を持つ声部のみ（空声部を除外）
        active_voices = [
            v for v, mel in self.voice_melodies.items()
            if any(m is not None for m in mel)
        ]
        for vt in active_voices:
            melodies[vt] = [None] * ep_length

        for i, p in enumerate(fitted):
            melodies[leading_voice][i] = p.midi

        # --- Phase B: 調性経路の生成と拍ごとの和声分析 ---
        start_key = episode.start_key if episode.start_key else self.key
        end_key = episode.end_key if episode.end_key else self.key
        strategy = key_path_strategy or KeyPathStrategy()
        key_path = strategy.generate(start_key, end_key, ep_length)
        self.episode_key_path = key_path  # レポート用に保存
        # 複数嬉遊部の調性経路を辞書で記録
        if not hasattr(self, '_last_key_paths'):
            self._last_key_paths = {}
        ep_label = f"episode_{len(self._last_key_paths) + 1}"
        self._last_key_paths[ep_label] = key_path

        # --- Phase B1: 古典和声に基づく転調手順付き和声計画 ---
        # 転調点を取得し、各転調にピボットコード→V→I の手順を適用
        modulation_points = key_path.modulation_points()

        ep_chord_plan: List[ChordLabel] = []

        if not modulation_points:
            # 転調なし: 全体を1キーで分析
            seg_key = key_path.key_at(0)
            seg_subject = Subject(ep_pitches, seg_key, "episode_segment")
            seg_analyzer = SubjectHarmonicAnalyzer(
                seg_key, seed=self.seed,
                seventh_freq=0.0,
                secondary_dom_freq=0.10,
                altered_freq=0.0,
            )
            ep_chord_plan = seg_analyzer.analyze(seg_subject)
        else:
            prev_key = key_path.key_at(0)
            seg_start = 0

            for mod_beat in modulation_points:
                next_key = key_path.key_at(mod_beat)
                seg_len = mod_beat - seg_start

                # この区間の旋律ピッチクラス
                seg_melody_pcs = [
                    p.pitch_class if hasattr(p, 'pitch_class') else p.midi % 12
                    for p in ep_pitches[seg_start:mod_beat]
                ]

                if seg_len >= 4:
                    # 十分な長さ → 古典的転調手順を適用
                    # 旧調確立 → ピボット → 新調V(7) → 新調I
                    chords = self._build_modulation_chords(
                        prev_key, next_key, seg_melody_pcs, seg_len)
                elif seg_len > 0:
                    # 短い → 略式転調（V→I のみ）
                    chords = self._build_abbreviated_modulation(
                        prev_key, next_key, seg_melody_pcs, seg_len)
                else:
                    chords = []

                ep_chord_plan.extend(chords)
                seg_start = mod_beat
                prev_key = next_key

            # 最終区間（転調後の新調での継続）
            if seg_start < ep_length:
                final_pitches = ep_pitches[seg_start:]
                final_subject = Subject(final_pitches, prev_key, "episode_final")
                final_analyzer = SubjectHarmonicAnalyzer(
                    prev_key, seed=self.seed,
                    seventh_freq=0.0,
                    secondary_dom_freq=0.10,
                    altered_freq=0.0,
                )
                final_plan = final_analyzer.analyze(final_subject)

                # NOTE: V→v置換 (_avoid_leading_tone_in_short_segment) は廃止。
                # コード優先でスケールを合わせる設計に移行済み。
                # 短調のVは長和音（A major in D minor）が正しい。

                ep_chord_plan.extend(final_plan)

        # 長さ調整（安全策: 和声計画がエピソード長と一致することを保証）
        while len(ep_chord_plan) < ep_length:
            ep_chord_plan.append(ep_chord_plan[-1] if ep_chord_plan
                                 else SubjectHarmonicAnalyzer(
                                     start_key, seed=self.seed
                                 ).diatonic_chords[0])
        ep_chord_plan = ep_chord_plan[:ep_length]

        # --- Phase B2: 和声進行モデルによる和声計画の改善 ---
        if self.chord_model and self.chord_model.num_transitions > 0:
            ep_chord_plan = self._refine_chord_plan_with_model(
                ep_chord_plan, ep_pitches, key_path)

        # --- Phase C: 対位法声部のDP生成 ---
        dp = self.dp
        # 嬉遊部のkey_pathから拍ごとのキーリストを構築
        ep_beat_keys: List[Key] = []
        for beat in range(ep_length):
            if key_path:
                ep_beat_keys.append(key_path.key_at(beat))
            else:
                ep_beat_keys.append(start_key)
        ep_key = ep_beat_keys[0]
        dp._key_obj = ep_key  # フォールバック用
        dp._key_scale = set(ep_key.scale)
        dp._key_scale_list = list(ep_key.scale)

        # 提示部末尾の各声部の最後の音を取得（接続用）
        last_pitches: Dict[FugueVoiceType, Optional[int]] = {}
        for vt in active_voices:
            if vt in expo_midi and expo_midi[vt]:
                # 最後のノートのMIDI値
                last_pitches[vt] = expo_midi[vt][-1][1]
            else:
                last_pitches[vt] = None

        # バックトラッキングで全自由声部を同時生成
        # Gédalge §205-206: 全声部は旋律的に処理される。
        # 非主導声部に対旋律プロファイル（主題断片の模倣）を供給する。
        ep_fixed: Dict[FugueVoiceType, List[Optional[int]]] = {
            leading_voice: [melodies[leading_voice][b] for b in range(ep_length)]
        }
        ep_free = [vt for vt in active_voices if vt != leading_voice]
        ep_free.sort(key=lambda v: {
            FugueVoiceType.SOPRANO: 0, FugueVoiceType.ALTO: 1,
            FugueVoiceType.TENOR: 2, FugueVoiceType.BASS: 3}[v])

        # Gédalge §206/C21: 非主導声部の対旋律プロファイル生成
        # 主導声部の旋律輪郭を遅延模倣（1-2拍遅れ）として各自由声部に供給
        ep_cs_profiles: Optional[Dict[FugueVoiceType, List[Optional[int]]]] = None
        if ep_length >= 4:
            ep_cs_profiles = {}
            leading_pitches = [melodies[leading_voice][b] for b in range(ep_length)]
            for vi, vt in enumerate(ep_free):
                # 声部ごとに異なる遅延量（1拍、2拍）で主導声部の旋律輪郭を模倣
                delay = (vi + 1)  # 1拍遅れ、2拍遅れ…
                profile: List[Optional[int]] = [None] * ep_length
                vr = VOICE_RANGES[vt]
                for b in range(ep_length):
                    src_b = b - delay
                    if 0 <= src_b < ep_length and leading_pitches[src_b] is not None:
                        # 主導声部の音を自声部の音域に移調（オクターブ調整）
                        src_midi = leading_pitches[src_b]
                        while src_midi > vr[1]:
                            src_midi -= 12
                        while src_midi < vr[0]:
                            src_midi += 12
                        if vr[0] <= src_midi <= vr[1]:
                            profile[b] = src_midi
                ep_cs_profiles[vt] = profile

        bt_result = self._backtrack_counterpoint(
            num_beats=ep_length,
            chord_plan=ep_chord_plan,
            fixed_pitches=ep_fixed,
            free_voices=ep_free,
            voice_ranges=VOICE_RANGES,
            prev_all_pitches=last_pitches if any(v is not None for v in last_pitches.values()) else None,
            beat_keys=ep_beat_keys,
            cs_profiles=ep_cs_profiles,
        )

        if bt_result:
            print(f"  嬉遊部: バックトラッキング成功 (自由={[v.value for v in ep_free]})")
            for vt, pitches in bt_result.items():
                for i, midi_val in enumerate(pitches):
                    melodies[vt][i] = midi_val
        else:
            print(f"  嬉遊部: バックトラッキング失敗→DP逐次生成")
            # フォールバック: 従来の逐次DP
            for vt in active_voices:
                if vt == leading_voice:
                    continue
                fixed = {}
                fixed[leading_voice.value] = [
                    melodies[leading_voice][b] for b in range(ep_length)]
                for other_vt in active_voices:
                    if other_vt == vt or other_vt == leading_voice:
                        continue
                    if melodies[other_vt][0] is not None:
                        fixed[other_vt.value] = [
                            melodies[other_vt][b] for b in range(ep_length)]
                start_from = last_pitches.get(vt)
                prev_fp: Optional[Dict[str, int]] = None
                if last_pitches:
                    prev_fp = {}
                    for other_vt, p in last_pitches.items():
                        if other_vt != vt and p is not None:
                            prev_fp[other_vt.value] = p
                    if not prev_fp:
                        prev_fp = None
                generated = dp.generate(
                    num_beats=ep_length,
                    chord_plan=ep_chord_plan,
                    voice_range=VOICE_RANGES[vt],
                    fixed_voices=fixed,
                    free_voice_name=vt.value,
                    start_from=start_from,
                    prev_fixed_pitches=prev_fp,
                    beat_keys=ep_beat_keys,
                )
                for i, midi_val in enumerate(generated):
                    melodies[vt][i] = midi_val

        # --- Phase C2: 和音充足検証・修復 ---
        _ep_subject_beats: Dict[FugueVoiceType, Set[int]] = {
            vt: set() for vt in active_voices
        }
        # 動機声部は全拍が固定
        for b in range(ep_length):
            _ep_subject_beats[leading_voice].add(b)
        # エピソード終端キーのダイアトニック和音を修復に使用
        _ep_end_key = key_path.key_at(ep_length - 1) if ep_length > 0 else start_key
        _ep_dia_analyzer = SubjectHarmonicAnalyzer(
            _ep_end_key, seed=self.seed,
            seventh_freq=0.0, secondary_dom_freq=0.0, altered_freq=0.0)
        melodies, ep_chord_plan = self._verify_and_repair_chord_coverage(
            melodies, ep_chord_plan, subject_beats=_ep_subject_beats,
            diatonic_chords=_ep_dia_analyzer.diatonic_chords)

        # --- Phase D: サブビートグリッド構築（リズム装飾）---
        SB = SUBBEATS_PER_BEAT
        total_sb = ep_length * SB
        grid: Dict[FugueVoiceType, List[Optional[int]]] = {}
        for vt in active_voices:
            grid[vt] = [None] * total_sb

        # 拍ごとの調に応じたRhythmElaboratorを取得するヘルパー
        # （同一調の区間ではキャッシュして再生成を避ける）
        _elaborator_cache: Dict[int, RhythmElaborator] = {}

        # 転調区間の長さを前計算（短区間の minor では自然短音階を使用）
        _seg_lengths: Dict[int, int] = {}
        if key_path and key_path.beat_keys:
            seg_s = 0
            while seg_s < ep_length:
                seg_k = key_path.key_at(seg_s)
                seg_e = seg_s + 1
                while seg_e < ep_length and key_path.key_at(seg_e) == seg_k:
                    seg_e += 1
                for b in range(seg_s, seg_e):
                    _seg_lengths[b] = seg_e - seg_s
                seg_s = seg_e

        def _get_elaborator(beat: int) -> RhythmElaborator:
            beat_key = key_path.key_at(beat)
            seg_len = _seg_lengths.get(beat, ep_length)
            # NOTE: スケール選択はコード優先設計に移行。
            # elaborator のデフォルトスケールは和声的短音階で初期化し、
            # elaborate_beat 呼び出し時に beat_scale で拍ごとに切替。
            cache_key = (beat_key.tonic_pc * 2
                         + (0 if beat_key.mode == "major" else 1))
            if cache_key not in _elaborator_cache:
                _elaborator_cache[cache_key] = RhythmElaborator(
                    beat_key.scale, seed=self.seed,
                    elaborate=self.elaborate)
            return _elaborator_cache[cache_key]

        # 動機声部: 四分音符で配置（元のNoteEvent情報がないため）
        for beat in range(ep_length):
            midi_val = melodies[leading_voice][beat]
            if midi_val is not None:
                sb_start = beat * SB
                for s in range(SB):
                    if sb_start + s < total_sb:
                        grid[leading_voice][sb_start + s] = midi_val

        # 対位法声部: リズム装飾
        for vt in active_voices:
            if vt == leading_voice:
                continue
            for beat in range(ep_length):
                midi_val = melodies[vt][beat]
                if midi_val is None:
                    continue
                next_val = (melodies[vt][beat + 1]
                            if beat + 1 < ep_length
                            and melodies[vt][beat + 1] is not None
                            else None)
                elaborator = _get_elaborator(beat)
                pattern = elaborator.select_pattern(
                    is_subject_voice=(vt == leading_voice),
                    other_has_motion=True)
                beat_chord_tones = (ep_chord_plan[beat].tones
                                    if beat < len(ep_chord_plan) else None)
                # コードからスケールを決定
                beat_key = key_path.key_at(beat) if key_path else start_key
                b_scale = (beat_key.scale_for_chord(beat_chord_tones)
                           if beat_chord_tones else beat_key.scale)
                elaborated = elaborator.elaborate_beat(
                    midi_val, next_val, pattern, VOICE_RANGES[vt],
                    chord_tones=beat_chord_tones,
                    beat_scale=b_scale)
                sb_start = beat * SB
                sb_offset = 0
                for pitch, dur in elaborated:
                    for s in range(dur):
                        abs_sb = sb_start + sb_offset + s
                        if abs_sb < total_sb:
                            grid[vt][abs_sb] = pitch
                    sb_offset += dur

        # --- Phase D2: VNS後処理 (C25: Gédalge原則に基づく品質保証) ---
        # 嬉遊部にもVNSを適用し、並行5度/8度・半音衝突等を修正する。
        _ep_subject_beats_vns: Dict[FugueVoiceType, Set[int]] = {
            vt: set() for vt in active_voices
        }
        for b in range(ep_length):
            _ep_subject_beats_vns[leading_voice].add(b)

        # beat_key_map を構築（VNSに渡す）
        _ep_beat_key_map: Dict[int, Key] = {}
        for b in range(ep_length):
            _ep_beat_key_map[b] = ep_beat_keys[b] if b < len(ep_beat_keys) else start_key

        try:
            from vns_refiner import VNSRefiner  # 遅延インポート（循環回避）
            vns = VNSRefiner(
                grid=grid,
                chord_plan=ep_chord_plan,
                key=start_key,
                subject_beats=_ep_subject_beats_vns,
                total_beats=ep_length,
                seed=self.seed,
                elaborate=self.elaborate,
                beat_key_map=_ep_beat_key_map,
            )
            grid, vns_report = vns.refine(
                max_iterations=200,
                patience=30,
                verbose=False,
            )
            if vns_report:
                print(f"  嬉遊部VNS: {len(vns_report)}件修正")
        except Exception as e:
            print(f"  嬉遊部VNS: エラー ({e}), スキップ")

        # --- Phase E: MIDI出力（tickをstart_beatからのオフセットで生成）---
        ticks_per_sb = 120
        offset_ticks = start_beat * SB * ticks_per_sb
        result: Dict[FugueVoiceType, List[Tuple[int, int, int]]] = {}
        for voice, melody in grid.items():
            notes = []
            i = 0
            while i < len(melody):
                if melody[i] is not None:
                    pitch = melody[i]
                    start = i
                    while i < len(melody) and melody[i] == pitch:
                        i += 1
                    duration = (i - start) * ticks_per_sb
                    notes.append((
                        offset_ticks + start * ticks_per_sb,
                        pitch,
                        duration,
                    ))
                else:
                    i += 1
            if notes:
                result[voice] = notes

        # 嬉遊部の和声計画とkey_pathを保存
        self.episode_chord_plan = ep_chord_plan
        self._last_episode_beat_keys = ep_beat_keys
        self.episode_melodies = melodies

        return result

    # ================================================================
    # 中間部主題提示（Middle Entry）
    # ================================================================

    def realize_middle_entry(
        self,
        entry: FugueEntry,
        start_beat: int,
        prev_midi: Dict[FugueVoiceType, List[Tuple[int, int, int]]],
    ) -> Dict[FugueVoiceType, List[Tuple[int, int, int]]]:
        """中間部の主題提示を実現する

        提示部と同じパイプラインを使い、指定調で単一の主題を提示する。
        他の声部は対位法DPで生成。

        Args:
            entry: FugueEntry（voice_type, subject, key=target_key）
            start_beat: 開始拍
            prev_midi: 直前セクションのMIDIデータ（接続用）

        Returns:
            {voice: [(start_tick, midi, duration_tick), ...]}
        """
        target_key = entry.key
        subject_orig = entry.subject
        entry_voice = entry.voice_type

        # --- 主題の移調: 原調 → 目標調 ---
        # 中間提示では主題を目標調にダイアトニック移調する。
        # 各音のスケール度数を保持し、導音は正しく対応させる。
        # 例: D minor → F major: D→F, C#→E(導音), F→A(第3音)
        from_key = subject_orig.key
        if from_key.tonic_pc != target_key.tonic_pc or from_key.mode != target_key.mode:
            subject = subject_orig.diatonic_transpose_to(from_key, target_key)
        else:
            subject = subject_orig
        subject_len = subject.get_length()

        # --- Phase A: 主題の和声分析（対象調で）---
        analyzer = SubjectHarmonicAnalyzer(
            target_key, seed=self.seed,
            seventh_freq=0.0,
            secondary_dom_freq=0.05,
            altered_freq=0.0,
        )
        chord_plan = analyzer.analyze(subject)

        # --- Phase B: 主題声部の配置 ---
        # subject.pitches は NoteEvent 単位（11要素）であり beat 単位（16要素）ではない。
        # _expand_subject_to_beat_pitches() で各拍で鳴っている音に展開する。
        beat_pitches = self._expand_subject_to_beat_pitches(subject)
        fitted = fit_melody_to_range(beat_pitches, VOICE_RANGES[entry_voice])

        active_voices = [
            v for v, mel in self.voice_melodies.items()
            if any(m is not None for m in mel)
        ]
        melodies: Dict[FugueVoiceType, List[Optional[int]]] = {}
        for vt in active_voices:
            melodies[vt] = [None] * subject_len

        for i, p in enumerate(fitted):
            melodies[entry_voice][i] = p.midi

        # --- Phase C: 対位法声部のDP生成 ---
        dp = self.dp
        # 中間提示のキーに合わせて増音程検出用スケールを更新
        dp._key_obj = target_key  # コード→スケール決定用
        dp._key_scale = set(target_key.scale)
        dp._key_scale_list = list(target_key.scale)

        # 前セクション末尾の音を取得（接続用）
        last_pitches: Dict[FugueVoiceType, Optional[int]] = {}
        for vt in active_voices:
            if vt in prev_midi and prev_midi[vt]:
                last_pitches[vt] = prev_midi[vt][-1][1]
            else:
                last_pitches[vt] = None

        # バックトラッキングで全自由声部を同時生成
        me_fixed: Dict[FugueVoiceType, List[Optional[int]]] = {
            entry_voice: [melodies[entry_voice][b] for b in range(subject_len)]
        }
        me_free = [vt for vt in active_voices if vt != entry_voice]
        me_free.sort(key=lambda v: {
            FugueVoiceType.SOPRANO: 0, FugueVoiceType.ALTO: 1,
            FugueVoiceType.TENOR: 2, FugueVoiceType.BASS: 3}[v])

        # 中間提示の拍ごとの調マップ
        me_beat_keys = [target_key] * subject_len

        bt_result = self._backtrack_counterpoint(
            num_beats=subject_len,
            chord_plan=chord_plan,
            fixed_pitches=me_fixed,
            free_voices=me_free,
            voice_ranges=VOICE_RANGES,
            prev_all_pitches=last_pitches if any(v is not None for v in last_pitches.values()) else None,
            beat_keys=me_beat_keys,
        )

        if bt_result:
            print(f"  中間提示: バックトラッキング成功 (自由={[v.value for v in me_free]})")
            for vt, pitches in bt_result.items():
                for i, midi_val in enumerate(pitches):
                    melodies[vt][i] = midi_val
        else:
            print(f"  中間提示: バックトラッキング失敗→DP逐次生成")
            # フォールバック: 従来の逐次DP
            for vt in active_voices:
                if vt == entry_voice:
                    continue
                fixed = {}
                fixed[entry_voice.value] = [
                    melodies[entry_voice][b] for b in range(subject_len)]
                for other_vt in active_voices:
                    if other_vt == vt or other_vt == entry_voice:
                        continue
                    if melodies[other_vt][0] is not None:
                        fixed[other_vt.value] = [
                            melodies[other_vt][b] for b in range(subject_len)]
                start_from = last_pitches.get(vt)
                prev_fp: Optional[Dict[str, int]] = None
                if last_pitches:
                    prev_fp = {}
                    for other_vt, p in last_pitches.items():
                        if other_vt != vt and p is not None:
                            prev_fp[other_vt.value] = p
                    if not prev_fp:
                        prev_fp = None
                generated = dp.generate(
                    num_beats=subject_len,
                    chord_plan=chord_plan,
                    voice_range=VOICE_RANGES[vt],
                    fixed_voices=fixed,
                    free_voice_name=vt.value,
                    start_from=start_from,
                    prev_fixed_pitches=prev_fp,
                )
                for i, midi_val in enumerate(generated):
                    melodies[vt][i] = midi_val

        # --- Phase C2: 和音充足検証・修復 ---
        _me_subject_beats: Dict[FugueVoiceType, Set[int]] = {
            vt: set() for vt in active_voices
        }
        for b in range(subject_len):
            _me_subject_beats[entry_voice].add(b)
        melodies, chord_plan = self._verify_and_repair_chord_coverage(
            melodies, chord_plan, subject_beats=_me_subject_beats,
            diatonic_chords=analyzer.diatonic_chords)

        # --- Phase D: サブビートグリッド ---
        SB = SUBBEATS_PER_BEAT
        total_sb = subject_len * SB
        grid: Dict[FugueVoiceType, List[Optional[int]]] = {}
        for vt in active_voices:
            grid[vt] = [None] * total_sb

        elaborator = RhythmElaborator(target_key.scale, seed=self.seed,
                                      elaborate=self.elaborate)

        # NOTE: 旧実装では counterpoint_elaborator に自然短音階を使用していたが、
        # コード優先設計に移行: V和音の拍では和声的短音階、それ以外は自然短音階。
        # elaborate_beat の beat_scale パラメータで拍ごとに切替。

        # 主題声部: 元のNoteEventの音長を反映
        sb_pos = 0
        for note in subject.notes:
            fitted_pitch = fit_melody_to_range(
                [note.pitch], VOICE_RANGES[entry_voice])[0]
            for s in range(note.duration):
                if sb_pos + s < total_sb:
                    grid[entry_voice][sb_pos + s] = fitted_pitch.midi
            sb_pos += note.duration

        # 対位法声部: リズム装飾
        for vt in active_voices:
            if vt == entry_voice:
                continue
            for beat in range(subject_len):
                midi_val = melodies[vt][beat]
                if midi_val is None:
                    continue
                next_val = (melodies[vt][beat + 1]
                            if beat + 1 < subject_len
                            and melodies[vt][beat + 1] is not None
                            else None)
                pattern = elaborator.select_pattern(
                    is_subject_voice=False, other_has_motion=True)
                beat_chord_tones = (chord_plan[beat].tones
                                    if beat < len(chord_plan) else None)
                # コードからスケールを決定（V和音ならC#、i和音ならC♮）
                b_scale = (target_key.scale_for_chord(beat_chord_tones)
                           if beat_chord_tones else target_key.scale)
                elaborated = elaborator.elaborate_beat(
                    midi_val, next_val, pattern, VOICE_RANGES[vt],
                    chord_tones=beat_chord_tones,
                    beat_scale=b_scale)
                sb_start = beat * SB
                sb_offset = 0
                for pitch, dur in elaborated:
                    for s in range(dur):
                        abs_sb = sb_start + sb_offset + s
                        if abs_sb < total_sb:
                            grid[vt][abs_sb] = pitch
                    sb_offset += dur

        # --- Phase D2: VNS後処理 (C25) ---
        _me_subject_beats_vns: Dict[FugueVoiceType, Set[int]] = {
            vt: set() for vt in active_voices
        }
        for b in range(subject_len):
            _me_subject_beats_vns[entry_voice].add(b)

        try:
            from vns_refiner import VNSRefiner  # 遅延インポート（循環回避）
            vns = VNSRefiner(
                grid=grid,
                chord_plan=chord_plan,
                key=target_key,
                subject_beats=_me_subject_beats_vns,
                total_beats=subject_len,
                seed=self.seed,
                elaborate=self.elaborate,
            )
            grid, vns_report = vns.refine(
                max_iterations=200,
                patience=30,
                verbose=False,
            )
            if vns_report:
                print(f"  中間提示VNS: {len(vns_report)}件修正")
        except Exception as e:
            print(f"  中間提示VNS: エラー ({e}), スキップ")

        # --- Phase E: MIDI出力 ---
        ticks_per_sb = 120
        offset_ticks = start_beat * SB * ticks_per_sb
        result: Dict[FugueVoiceType, List[Tuple[int, int, int]]] = {}
        for voice, melody in grid.items():
            notes = []
            i = 0
            while i < len(melody):
                if melody[i] is not None:
                    pitch = melody[i]
                    start = i
                    while i < len(melody) and melody[i] == pitch:
                        i += 1
                    duration = (i - start) * ticks_per_sb
                    notes.append((
                        offset_ticks + start * ticks_per_sb,
                        pitch,
                        duration,
                    ))
                else:
                    i += 1
            if notes:
                result[voice] = notes

        # レポート用
        self.middle_entry_chord_plan = chord_plan
        self.middle_entry_melodies = melodies

        return result

    # ================================================================
    # 終止部（Coda）
    # ================================================================

    def realize_coda(
        self,
        start_beat: int,
        prev_midi: Dict[FugueVoiceType, List[Tuple[int, int, int]]],
        num_beats: int = 8,
        pedal_voice: FugueVoiceType = FugueVoiceType.BASS,
        pedal_degree: int = 0,
        cadence_beats: int = 4,
    ) -> Dict[FugueVoiceType, List[Tuple[int, int, int]]]:
        """終止部を実現する

        Prout: コーダはペダルポイント上の終止で締めくくる。

        Args:
            start_beat: 開始拍
            prev_midi: 直前セクションのMIDI
            num_beats: 総拍数
            pedal_voice: ペダルポイントを担当する声部
            pedal_degree: ペダル音の音階度数（0=主音, 4=属音）
            cadence_beats: 最終カデンツの拍数

        Returns:
            {voice: [(start_tick, midi, duration_tick), ...]}
        """
        main_key = self.key
        scale = main_key.scale

        # --- Phase A: ペダルポイント ---
        pedal_pc = scale[pedal_degree]
        # ペダル音をvoice rangeに収める
        lo, hi = VOICE_RANGES[pedal_voice]
        pedal_midi = lo + (pedal_pc - lo % 12) % 12
        if pedal_midi < lo:
            pedal_midi += 12
        if pedal_midi > hi:
            pedal_midi -= 12

        active_voices = [
            v for v, mel in self.voice_melodies.items()
            if any(m is not None for m in mel)
        ]

        melodies: Dict[FugueVoiceType, List[Optional[int]]] = {}
        for vt in active_voices:
            melodies[vt] = [None] * num_beats

        # ペダル声部: 全拍同一音
        for i in range(num_beats):
            melodies[pedal_voice][i] = pedal_midi

        # --- Phase B: カデンツ和声計画 ---
        chord_plan = self._build_coda_harmony(
            main_key, num_beats, cadence_beats)

        # --- Phase C: 上声部のDP生成 ---
        dp = self.dp
        # 終止部のキーに合わせて増音程検出用スケールを更新
        dp._key_obj = main_key  # コード→スケール決定用
        dp._key_scale = set(main_key.scale)
        dp._key_scale_list = list(main_key.scale)

        last_pitches: Dict[FugueVoiceType, Optional[int]] = {}
        for vt in active_voices:
            if vt in prev_midi and prev_midi[vt]:
                last_pitches[vt] = prev_midi[vt][-1][1]
            else:
                last_pitches[vt] = None

        # バックトラッキングで全自由声部を同時生成
        coda_fixed: Dict[FugueVoiceType, List[Optional[int]]] = {
            pedal_voice: [melodies[pedal_voice][b] for b in range(num_beats)]
        }
        coda_free = [vt for vt in active_voices if vt != pedal_voice]
        coda_free.sort(key=lambda v: {
            FugueVoiceType.SOPRANO: 0, FugueVoiceType.ALTO: 1,
            FugueVoiceType.TENOR: 2, FugueVoiceType.BASS: 3}[v])

        coda_beat_keys = [main_key] * num_beats

        bt_result = self._backtrack_counterpoint(
            num_beats=num_beats,
            chord_plan=chord_plan,
            fixed_pitches=coda_fixed,
            free_voices=coda_free,
            voice_ranges=VOICE_RANGES,
            prev_all_pitches=last_pitches if any(v is not None for v in last_pitches.values()) else None,
            beat_keys=coda_beat_keys,
        )

        if bt_result:
            print(f"  終止部: バックトラッキング成功 (自由={[v.value for v in coda_free]})")
            for vt, pitches in bt_result.items():
                for i, midi_val in enumerate(pitches):
                    melodies[vt][i] = midi_val
        else:
            print(f"  終止部: バックトラッキング失敗→DP逐次生成")
            # フォールバック: 従来の逐次DP
            for vt in active_voices:
                if vt == pedal_voice:
                    continue
                fixed = {}
                fixed[pedal_voice.value] = [
                    melodies[pedal_voice][b] for b in range(num_beats)]
                for other_vt in active_voices:
                    if other_vt == vt or other_vt == pedal_voice:
                        continue
                    if melodies[other_vt][0] is not None:
                        fixed[other_vt.value] = [
                            melodies[other_vt][b] for b in range(num_beats)]
                start_from = last_pitches.get(vt)
                prev_fp: Optional[Dict[str, int]] = None
                if last_pitches:
                    prev_fp = {}
                    for other_vt, p in last_pitches.items():
                        if other_vt != vt and p is not None:
                            prev_fp[other_vt.value] = p
                    if not prev_fp:
                        prev_fp = None
                generated = dp.generate(
                    num_beats=num_beats,
                    chord_plan=chord_plan,
                    voice_range=VOICE_RANGES[vt],
                    fixed_voices=fixed,
                    free_voice_name=vt.value,
                    start_from=start_from,
                    prev_fixed_pitches=prev_fp,
                )
                for i, midi_val in enumerate(generated):
                    melodies[vt][i] = midi_val

        # --- Phase C2: 和音充足検証・修復 ---
        _coda_subject_beats: Dict[FugueVoiceType, Set[int]] = {
            vt: set() for vt in active_voices
        }
        # ペダル声部は修正対象外
        for b in range(num_beats):
            _coda_subject_beats[pedal_voice].add(b)
        _coda_analyzer = SubjectHarmonicAnalyzer(
            self.key, seed=self.seed,
            seventh_freq=0.0, secondary_dom_freq=0.0, altered_freq=0.0)
        melodies, chord_plan = self._verify_and_repair_chord_coverage(
            melodies, chord_plan, subject_beats=_coda_subject_beats,
            diatonic_chords=_coda_analyzer.diatonic_chords)

        # --- Phase D: サブビートグリッド（終止部は控えめな装飾）---
        SB = SUBBEATS_PER_BEAT
        total_sb = num_beats * SB
        grid: Dict[FugueVoiceType, List[Optional[int]]] = {}
        for vt in active_voices:
            grid[vt] = [None] * total_sb

        elaborator = RhythmElaborator(main_key.scale, seed=self.seed,
                                      elaborate=self.elaborate)

        for vt in active_voices:
            for beat in range(num_beats):
                midi_val = melodies[vt][beat]
                if midi_val is None:
                    continue
                sb_start = beat * SB
                if vt == pedal_voice or beat >= num_beats - cadence_beats:
                    # ペダル声部、または最終カデンツ: 四分音符（装飾なし）
                    for s in range(SB):
                        if sb_start + s < total_sb:
                            grid[vt][sb_start + s] = midi_val
                else:
                    # 前半: 軽い装飾
                    next_val = (melodies[vt][beat + 1]
                                if beat + 1 < num_beats
                                and melodies[vt][beat + 1] is not None
                                else None)
                    pattern = elaborator.select_pattern(
                        is_subject_voice=False, other_has_motion=False)
                    beat_chord_tones = (chord_plan[beat].tones
                                        if beat < len(chord_plan) else None)
                    b_scale = (main_key.scale_for_chord(beat_chord_tones)
                               if beat_chord_tones else main_key.scale)
                    elaborated = elaborator.elaborate_beat(
                        midi_val, next_val, pattern, VOICE_RANGES[vt],
                        chord_tones=beat_chord_tones,
                        beat_scale=b_scale)
                    sb_offset = 0
                    for pitch, dur in elaborated:
                        for s in range(dur):
                            abs_sb = sb_start + sb_offset + s
                            if abs_sb < total_sb:
                                grid[vt][abs_sb] = pitch
                        sb_offset += dur

        # --- Phase D2: VNS後処理 (C25) ---
        _coda_subject_beats_vns: Dict[FugueVoiceType, Set[int]] = {
            vt: set() for vt in active_voices
        }
        if pedal_voice:
            for b in range(num_beats):
                _coda_subject_beats_vns[pedal_voice].add(b)

        try:
            from vns_refiner import VNSRefiner  # 遅延インポート（循環回避）
            vns = VNSRefiner(
                grid=grid,
                chord_plan=chord_plan,
                key=main_key,
                subject_beats=_coda_subject_beats_vns,
                total_beats=num_beats,
                seed=self.seed,
                elaborate=self.elaborate,
            )
            grid, vns_report = vns.refine(
                max_iterations=200,
                patience=30,
                verbose=False,
            )
            if vns_report:
                print(f"  終止部VNS: {len(vns_report)}件修正")
        except Exception as e:
            print(f"  終止部VNS: エラー ({e}), スキップ")

        # --- Phase E: MIDI出力 ---
        ticks_per_sb = 120
        offset_ticks = start_beat * SB * ticks_per_sb
        result: Dict[FugueVoiceType, List[Tuple[int, int, int]]] = {}
        for voice, melody in grid.items():
            notes = []
            i = 0
            while i < len(melody):
                if melody[i] is not None:
                    pitch = melody[i]
                    start = i
                    while i < len(melody) and melody[i] == pitch:
                        i += 1
                    duration = (i - start) * ticks_per_sb
                    notes.append((
                        offset_ticks + start * ticks_per_sb,
                        pitch,
                        duration,
                    ))
                else:
                    i += 1
            if notes:
                result[voice] = notes

        self.coda_chord_plan = chord_plan
        self.coda_melodies = melodies
        return result

    def _build_coda_harmony(
        self, key: Key, num_beats: int, cadence_beats: int,
    ) -> List[ChordLabel]:
        """終止部の和声計画を生成する

        前半: I（トニック）周辺の和声
        後半: 終止カデンツ（IV→V→I）
        """
        analyzer = SubjectHarmonicAnalyzer(
            key, seed=self.seed,
            seventh_freq=0.0,
            secondary_dom_freq=0.0,
            altered_freq=0.0,
        )

        # 終止カデンツの和声（末尾から逆順に構築）
        cadence_chords: List[ChordLabel] = []
        if cadence_beats >= 3:
            # IV → V → I
            cadence_chords.append(analyzer.diatonic_chords[3])   # IV
            for _ in range(cadence_beats - 2):
                cadence_chords.append(analyzer.diatonic_chords[4])  # V
            cadence_chords.append(analyzer.diatonic_chords[0])   # I
        elif cadence_beats == 2:
            cadence_chords.append(analyzer.diatonic_chords[4])   # V
            cadence_chords.append(analyzer.diatonic_chords[0])   # I
        else:
            cadence_chords.append(analyzer.diatonic_chords[0])   # I

        # 前半: I を基本にトニック機能の和声
        pre_beats = num_beats - len(cadence_chords)
        pre_chords: List[ChordLabel] = []
        tonic_options = [
            analyzer.diatonic_chords[0],   # I
            analyzer.diatonic_chords[5],   # vi
            analyzer.diatonic_chords[2],   # iii
        ]
        for i in range(pre_beats):
            pre_chords.append(tonic_options[i % len(tonic_options)])

        return pre_chords + cadence_chords

    # ================================================================
    # 全体オーケストレータ（realize_fugue）
    # ================================================================

    def realize_fugue(
        self,
        key_path_strategy: Optional[KeyPathStrategy] = None,
        episode_motif_length: int = 3,
        episode_steps: int = 4,
        episode_interval: int = -1,
        coda_beats: int = 8,
    ) -> Dict[FugueVoiceType, List[Tuple[int, int, int]]]:
        """フーガ全体を実現する

        提示部→嬉遊部1→中間部1→嬉遊部2→中間部2→終止部

        Args:
            key_path_strategy: 嬉遊部の調性経路戦略（差し替え可能）
            episode_motif_length: 嬉遊部の動機長
            episode_steps: 嬉遊部の反復回数
            episode_interval: 嬉遊部の反復移調幅（音階度数）
            coda_beats: 終止部の拍数

        Returns:
            {voice: [(start_tick, midi, duration_tick), ...]}
        """
        # 調性計画
        mod_plan = self.fs.get_modulation_plan()
        # mod_plan: [(label, Key), ...] — [主調, 属調, 平行調, 下属調, 主調]
        # 中間部1 = mod_plan[2][1]（平行調）, 中間部2 = mod_plan[3][1]（下属調）
        key_me1 = mod_plan[2][1] if len(mod_plan) > 2 else self.key
        key_me2 = mod_plan[3][1] if len(mod_plan) > 3 else self.key
        # 4声の場合: 中間部3 = 属調（短調では属短調を使用）
        dom_key_raw = mod_plan[1][1] if len(mod_plan) > 1 else self.key
        if self.key.mode == "minor" and dom_key_raw.mode == "major":
            # get_dominant_key()がmajorを返すが、短調フーガの中間提示は属短調
            from fugue_structure import PC_TO_NOTE
            key_me3 = Key(PC_TO_NOTE.get(dom_key_raw.tonic_pc, 'A'), "minor")
        else:
            key_me3 = dom_key_raw

        num_voices = self.fs.num_voices

        combined: Dict[FugueVoiceType, List[Tuple[int, int, int]]] = {}
        current_beat = 0
        prev_midi: Dict[FugueVoiceType, List[Tuple[int, int, int]]] = {}

        # グローバル和声マップ（品質検証用）
        # beat → Set[int] (和音構成音のピッチクラス集合)
        global_chord_tones: Dict[int, Set[int]] = {}
        # 嬉遊部の拍→調マップ（key_pathからの実際のキー）
        _episode_beat_keys_global: Dict[int, Key] = {}
        global_chord_labels: Dict[int, 'ChordLabel'] = {}

        def _register_chord_plan(
            plan: List['ChordLabel'], start_beat: int,
        ) -> None:
            """chord_planをグローバルビート番号でchord_tonesに登録"""
            for local_beat, chord in enumerate(plan):
                global_beat = start_beat + local_beat
                global_chord_tones[global_beat] = set(chord.tones)
                global_chord_labels[global_beat] = chord

        # ヘルパー: エピソード生成
        def _do_episode(end_key, leading_voice, label):
            nonlocal current_beat, prev_midi
            ep = self.fs.create_episode(
                start_position=current_beat,
                motif_length=episode_motif_length,
                sequence_steps=episode_steps,
                step_interval=episode_interval,
                end_key=end_key,
            )
            ep_len = ep.get_total_length()
            ep_midi = self.realize_episode(
                ep, current_beat, leading_voice, prev_midi,
                key_path_strategy=key_path_strategy,
            )
            for vt, notes in ep_midi.items():
                combined.setdefault(vt, []).extend(notes)
            prev_midi = ep_midi
            _register_chord_plan(self.episode_chord_plan, current_beat)
            # 嬉遊部の拍ごとのキーを保存（global_beat_key_map構築用）
            ep_bk = getattr(self, '_last_episode_beat_keys', None)
            if ep_bk:
                for local_b, bk in enumerate(ep_bk):
                    _episode_beat_keys_global[current_beat + local_b] = bk
            section_boundaries.append((label, current_beat, current_beat + ep_len))
            current_beat += ep_len

        # ヘルパー: 中間提示生成
        def _do_middle_entry(target_key, entry_voice, label):
            nonlocal current_beat, prev_midi
            me_entry = FugueEntry(
                subject=self.subject,
                voice_type=entry_voice,
                start_position=current_beat,
                key=target_key,
                is_answer=False,
            )
            me_midi = self.realize_middle_entry(me_entry, current_beat, prev_midi)
            for vt, notes in me_midi.items():
                combined.setdefault(vt, []).extend(notes)
            prev_midi = me_midi
            _register_chord_plan(self.middle_entry_chord_plan, current_beat)
            me_len = self.subject.get_length()
            section_boundaries.append((label, current_beat, current_beat + me_len))
            current_beat += me_len

        # --- 1. 提示部 ---
        expo_midi = self.realize_exposition()
        for vt, notes in expo_midi.items():
            combined.setdefault(vt, []).extend(notes)
        prev_midi = expo_midi
        _register_chord_plan(self.exposition_chords, 0)

        # 声部のローテーション（提示部実行後にactive_voicesを取得）
        active_voices = [
            v for v, mel in self.voice_melodies.items()
            if any(m is not None for m in mel)
        ]
        voice_cycle = list(active_voices)

        # 提示部の終了拍を計算
        max_tick = 0
        for notes in expo_midi.values():
            for tick, midi, dur in notes:
                if tick + dur > max_tick:
                    max_tick = tick + dur
        ticks_per_beat = SUBBEATS_PER_BEAT * 120
        current_beat = max_tick // ticks_per_beat

        # セクション境界を記録
        section_boundaries = [('提示部 (Exposition)', 0, current_beat)]

        # --- 中間部構成: 声部数に応じて拡張 ---
        if num_voices >= 4:
            # 4声: 提示部→嬉遊部1→中間提示1(平行調)→嬉遊部2→
            #       中間提示2(下属調)→嬉遊部3→中間提示3(属調)→終止部
            _do_episode(key_me1, voice_cycle[0 % len(voice_cycle)],
                        '嬉遊部1 (Episode 1)')
            _do_middle_entry(key_me1, voice_cycle[1 % len(voice_cycle)],
                             '中間提示1 (Middle Entry 1) - 平行調')
            _do_episode(key_me2, voice_cycle[2 % len(voice_cycle)],
                        '嬉遊部2 (Episode 2)')
            _do_middle_entry(key_me2, voice_cycle[3 % len(voice_cycle)],
                             '中間提示2 (Middle Entry 2) - 下属調')
            _do_episode(key_me3, voice_cycle[0 % len(voice_cycle)],
                        '嬉遊部3 (Episode 3)')
            _do_middle_entry(key_me3, voice_cycle[1 % len(voice_cycle)],
                             '中間提示3 (Middle Entry 3) - 属調')
        else:
            # 3声以下: 従来構成
            _do_episode(key_me1, voice_cycle[0 % len(voice_cycle)],
                        '嬉遊部1 (Episode 1)')
            _do_middle_entry(key_me1, voice_cycle[1 % len(voice_cycle)],
                             '中間提示1 (Middle Entry 1)')
            _do_episode(key_me2, voice_cycle[2 % len(voice_cycle)],
                        '嬉遊部2 (Episode 2)')
            _do_middle_entry(key_me2, voice_cycle[0 % len(voice_cycle)],
                             '中間提示2 (Middle Entry 2)')

        # --- 終止部 ---
        coda_midi = self.realize_coda(
            start_beat=current_beat,
            prev_midi=prev_midi,
            num_beats=coda_beats,
        )
        for vt, notes in coda_midi.items():
            combined.setdefault(vt, []).extend(notes)
        _register_chord_plan(self.coda_chord_plan, current_beat)
        section_boundaries.append(('終止部 (Coda)', current_beat, current_beat + coda_beats))

        # 品質検証用: グローバル和声マップを保持
        self.global_chord_tones = global_chord_tones
        self.global_chord_labels = global_chord_labels
        self.section_boundaries = section_boundaries

        # 品質検証用: セクション毎の調をbeat_key_mapとして構築
        # 提示部: 主調→属調（応答）→主調…（エントリ毎に交互）
        # 嬉遊部/中間提示: 各セクションの目標調
        global_beat_key_map: Dict[int, Key] = {}

        # セクション情報から調を特定（優先順位付き）
        # 1. まず全拍を主調で初期化
        all_beats = set()
        for _, s_start, s_end in section_boundaries:
            for b in range(s_start, s_end):
                all_beats.add(b)
        for b in all_beats:
            global_beat_key_map[b] = self.key

        # 2. 嬉遊部の調を上書き（key_pathの実際のキーを使用）
        for b, bk in _episode_beat_keys_global.items():
            global_beat_key_map[b] = bk

        # 3. 中間提示・終止部の調を上書き（より高い優先度）
        for label, s_start, s_end in section_boundaries:
            if '中間提示1' in label:
                for b in range(s_start, s_end):
                    global_beat_key_map[b] = key_me1
            elif '中間提示2' in label:
                for b in range(s_start, s_end):
                    global_beat_key_map[b] = key_me2
            elif '中間提示3' in label:
                for b in range(s_start, s_end):
                    global_beat_key_map[b] = key_me3
            elif '終止部' in label:
                for b in range(s_start, s_end):
                    global_beat_key_map[b] = self.key

        # 4. 提示部エントリの調を最優先で上書き（個別エントリの調）
        expo_entries = getattr(self, '_expo_entries', [])
        for entry in expo_entries:
            e_start = entry.start_position
            e_end = e_start + self.subject.get_length()
            for b in range(e_start, e_end):
                if b in global_beat_key_map:
                    global_beat_key_map[b] = entry.key

        self.global_beat_key_map = global_beat_key_map

        # NOTE: _global_parallel_cleanup は廃止。
        # ポストプロセスで音を書き換えるのではなく、DP/VNS が正しい解を見つけるべき。
        # 品質ゲート + リトライで対処する（generate_art_of_fugue.py 側）。

        return combined

    def _global_parallel_cleanup(
        self,
        combined: Dict[FugueVoiceType, List[Tuple[int, int, int]]],
        beat_key_map: Dict[int, Key],
    ) -> Dict[FugueVoiceType, List[Tuple[int, int, int]]]:
        """全セクション組み立て後にグローバルな平行5度/8度を修正する。

        拍頭のピッチを抽出し、連続拍間で平行完全音程が検出された場合、
        自由声部（非主題声部）の音を半音/全音ずらして解消する。
        """
        ticks_per_beat = SUBBEATS_PER_BEAT * 120

        # 全拍数を算出
        max_tick = 0
        for notes in combined.values():
            for tick, midi, dur in notes:
                if tick + dur > max_tick:
                    max_tick = tick + dur
        total_beats = max_tick // ticks_per_beat + 1

        # 拍→声部→(ピッチ, ノートリストindex) を構築
        # チェッカーのbeat_harmonicと同じ方式:
        #   拍頭で鳴っている音のうち、拍頭onset優先、なければ最長持続音
        def _build_beat_voice_info():
            bvi: Dict[int, Dict[FugueVoiceType, Tuple[int, int]]] = {}
            for vt in combined:
                notes = combined[vt]
                for idx in range(len(notes)):
                    tick, midi_val, dur = notes[idx]
                    nend = tick + dur
                    start_beat = tick // ticks_per_beat
                    end_beat = max(start_beat, (nend - 1) // ticks_per_beat)
                    for b in range(start_beat, min(end_beat + 1, total_beats)):
                        if b not in bvi:
                            bvi[b] = {}
                        is_onset = (tick == b * ticks_per_beat)
                        if vt not in bvi[b]:
                            bvi[b][vt] = (midi_val, idx, is_onset, dur)
                        else:
                            _, _, prev_onset, prev_dur = bvi[b][vt]
                            # onset優先、同じなら最長
                            if is_onset and not prev_onset:
                                bvi[b][vt] = (midi_val, idx, is_onset, dur)
                            elif is_onset == prev_onset and dur > prev_dur:
                                bvi[b][vt] = (midi_val, idx, is_onset, dur)
            # (pitch, idx)のタプルに簡素化
            result: Dict[int, Dict[FugueVoiceType, Tuple[int, int]]] = {}
            for b, vdict in bvi.items():
                result[b] = {}
                for vt, (midi_val, idx, _, _) in vdict.items():
                    result[b][vt] = (midi_val, idx)
            return result

        beat_voice_info = _build_beat_voice_info()

        # 主題拍を特定（グローバル拍番号）
        global_subject_beats: Dict[FugueVoiceType, Set[int]] = {}
        expo_entries = getattr(self, '_expo_entries', [])
        for entry in expo_entries:
            vt = entry.voice_type
            s_len = self.subject.get_length()
            for b in range(entry.start_position, entry.start_position + s_len):
                global_subject_beats.setdefault(vt, set()).add(b)

        fix_count = 0
        for beat in range(1, total_beats):
            prev_info = beat_voice_info.get(beat - 1, {})
            curr_info = beat_voice_info.get(beat, {})
            voices_at_beat = [vt for vt in curr_info if vt in prev_info]
            if len(voices_at_beat) < 2:
                continue

            for i in range(len(voices_at_beat)):
                for j in range(i + 1, len(voices_at_beat)):
                    v1, v2 = voices_at_beat[i], voices_at_beat[j]
                    prev_p1 = prev_info[v1][0]
                    curr_p1 = curr_info[v1][0]
                    prev_p2 = prev_info[v2][0]
                    curr_p2 = curr_info[v2][0]

                    # 両声部とも静止ならスキップ
                    if prev_p1 == curr_p1 and prev_p2 == curr_p2:
                        continue
                    # 反行ならスキップ
                    m1 = curr_p1 - prev_p1
                    m2 = curr_p2 - prev_p2
                    if m1 == 0 or m2 == 0:
                        continue
                    if (m1 > 0 and m2 < 0) or (m1 < 0 and m2 > 0):
                        continue

                    prev_ic = abs(prev_p1 - prev_p2) % 12
                    curr_ic = abs(curr_p1 - curr_p2) % 12
                    if prev_ic != curr_ic or curr_ic not in (0, 7):
                        continue

                    # 平行5度/8度を検出 — 自由声部を修正
                    # 主題声部でない方を選択
                    is_subj_v1 = beat in global_subject_beats.get(v1, set())
                    is_subj_v2 = beat in global_subject_beats.get(v2, set())
                    if is_subj_v1 and is_subj_v2:
                        continue  # 両方主題声部なら修正不可
                    target_vt = v2 if not is_subj_v2 else v1
                    other_vt = v1 if target_vt == v2 else v2

                    target_pitch = curr_info[target_vt][0]
                    target_idx = curr_info[target_vt][1]
                    other_pitch = curr_info[other_vt][0]

                    # コードに基づくスケールを取得
                    bk = beat_key_map.get(beat, self.key)
                    gct = getattr(self, 'global_chord_tones', None)
                    bct = gct.get(beat, set()) if gct else set()
                    scale_set = set(bk.scale_for_chord(bct))

                    # この拍の全声部のPCを収集（半音衝突チェック用）
                    other_pcs = set()
                    for vt_x, (px, _) in curr_info.items():
                        if vt_x != target_vt:
                            other_pcs.add(px % 12)

                    # 候補: ±1, ±2半音で平行を解消し、
                    # かつダイアトニックで半音衝突しない音
                    best = None
                    for delta in [1, -1, 2, -2]:
                        cand = target_pitch + delta
                        cand_pc = cand % 12
                        # 半音衝突チェック
                        has_clash = any(
                            (cand_pc - opc) % 12 in (1, 11)
                            for opc in other_pcs)
                        if has_clash:
                            continue
                        cand_ic = abs(cand - other_pitch) % 12
                        # 新しい音程が完全音程（0,7）でなければ平行は解消
                        if cand_ic in (0, 7):
                            continue
                        # 半音衝突を避ける
                        clash = False
                        for vt3 in voices_at_beat:
                            if vt3 == target_vt:
                                continue
                            p3 = curr_info[vt3][0]
                            d = abs(cand - p3) % 12
                            if d == 1 or d == 11:
                                clash = True
                                break
                        if clash:
                            continue
                        # ダイアトニック優先
                        if cand % 12 in scale_set:
                            best = cand
                            break
                        if best is None:
                            best = cand

                    if best is not None:
                        # 対象拍内の当該声部の全ノートを移調
                        delta_applied = best - target_pitch
                        beat_start_tick = beat * ticks_per_beat
                        beat_end_tick = (beat + 1) * ticks_per_beat
                        for nidx, (ntick, nmidi, ndur) in enumerate(
                                combined[target_vt]):
                            # この拍に含まれるノート（開始 or 持続）
                            nend = ntick + ndur
                            if ntick < beat_end_tick and nend > beat_start_tick:
                                combined[target_vt][nidx] = (
                                    ntick, nmidi + delta_applied, ndur)
                        # beat_voice_infoも更新
                        curr_info[target_vt] = (best, target_idx)
                        fix_count += 1

        if fix_count > 0:
            print(f"  グローバル平行修正: {fix_count}箇所")
            # 修正後に再構築して残存チェック（最大2回）
            for retry in range(2):
                beat_voice_info = _build_beat_voice_info()
                retry_fixes = 0
                for beat in range(1, total_beats):
                    prev_info = beat_voice_info.get(beat - 1, {})
                    curr_info = beat_voice_info.get(beat, {})
                    voices_at_beat = [vt for vt in curr_info if vt in prev_info]
                    if len(voices_at_beat) < 2:
                        continue
                    for i in range(len(voices_at_beat)):
                        for j in range(i + 1, len(voices_at_beat)):
                            v1, v2 = voices_at_beat[i], voices_at_beat[j]
                            prev_p1, prev_p2 = prev_info[v1][0], prev_info[v2][0]
                            curr_p1, curr_p2 = curr_info[v1][0], curr_info[v2][0]
                            if prev_p1 == curr_p1 and prev_p2 == curr_p2:
                                continue
                            m1, m2 = curr_p1 - prev_p1, curr_p2 - prev_p2
                            if m1 == 0 or m2 == 0:
                                continue
                            if (m1 > 0 and m2 < 0) or (m1 < 0 and m2 > 0):
                                continue
                            prev_ic = abs(prev_p1 - prev_p2) % 12
                            curr_ic = abs(curr_p1 - curr_p2) % 12
                            if prev_ic != curr_ic or curr_ic not in (0, 7):
                                continue
                            is_subj_v1 = beat in global_subject_beats.get(v1, set())
                            is_subj_v2 = beat in global_subject_beats.get(v2, set())
                            if is_subj_v1 and is_subj_v2:
                                continue
                            target_vt = v2 if not is_subj_v2 else v1
                            other_vt = v1 if target_vt == v2 else v2
                            target_pitch = curr_info[target_vt][0]
                            other_pitch = curr_info[other_vt][0]
                            bk = beat_key_map.get(beat, self.key)
                            scale_set = set(bk.scale)
                            best = None
                            for delta in [1, -1, 2, -2]:
                                cand = target_pitch + delta
                                cand_ic = abs(cand - other_pitch) % 12
                                if cand_ic in (0, 7):
                                    continue
                                clash = False
                                for vt3 in voices_at_beat:
                                    if vt3 == target_vt:
                                        continue
                                    p3 = curr_info[vt3][0]
                                    d = abs(cand - p3) % 12
                                    if d == 1 or d == 11:
                                        clash = True
                                        break
                                if clash:
                                    continue
                                if cand % 12 in scale_set:
                                    best = cand
                                    break
                                if best is None:
                                    best = cand
                            if best is not None:
                                delta_applied = best - target_pitch
                                beat_start_tick = beat * ticks_per_beat
                                beat_end_tick = (beat + 1) * ticks_per_beat
                                for nidx, (ntick, nmidi, ndur) in enumerate(
                                        combined[target_vt]):
                                    nend = ntick + ndur
                                    if ntick < beat_end_tick and nend > beat_start_tick:
                                        combined[target_vt][nidx] = (
                                            ntick, nmidi + delta_applied, ndur)
                                curr_info[target_vt] = (best, curr_info[target_vt][1])
                                retry_fixes += 1
                if retry_fixes == 0:
                    break
                print(f"  グローバル平行修正（再走査{retry+1}）: {retry_fixes}箇所")

        return combined

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
        chord_plan: Optional[List['ChordLabel']] = None,
    ) -> Dict[FugueVoiceType, List[Optional[int]]]:
        """beat-levelメロディ → subbeat-levelグリッドを構築

        - 主題のNoteEventは元の音長（duration）を反映
        - DP生成部はRhythmElaboratorでリズム装飾
        - chord_plan: 各拍のChordLabel（8分音符の和声音選択用）
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
        first_vc = None
        for entry_idx, entry in enumerate(entries):
            voice = entry.voice_type
            start_sb = entry.start_position * SB
            if entry_idx <= 1:
                # 第1・第2エントリ: 原音高をそのまま使用
                fitted = list(entry.subject.notes)
                if entry_idx == 0:
                    first_vc = (VOICE_RANGES[voice][0]
                                + VOICE_RANGES[voice][1]) // 2
            else:
                # 第3エントリ以降: 声部音域差でオクターブ補正
                this_c = (VOICE_RANGES[voice][0]
                          + VOICE_RANGES[voice][1]) // 2
                od = round((this_c - first_vc) / 12) * 12
                fitted = [NoteEvent(Pitch(n.pitch.midi + od), n.duration)
                          for n in entry.subject.notes]
            sb_pos = start_sb
            for note in fitted:
                # このNoteEventが跨ぐ全拍をsubject_beatsに登録
                note_end_sb = sb_pos + note.duration
                first_beat = sb_pos // SB
                last_beat = (note_end_sb - 1) // SB
                for b in range(first_beat, last_beat + 1):
                    if b < total_beats:
                        subject_beats[voice].add(b)
                for s in range(note.duration):
                    abs_sb = sb_pos + s
                    if abs_sb < total_sb:
                        grid[voice][abs_sb] = note.pitch.midi
                sb_pos += note.duration

        # --- DP生成部をリズム装飾付きで配置 ---
        elaborator = RhythmElaborator(self.key.scale, seed=self.seed,
                                      elaborate=self.elaborate)

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

                # 装飾（当該拍の構成音を渡す）
                beat_chord_tones = None
                if chord_plan and beat < len(chord_plan):
                    beat_chord_tones = chord_plan[beat].tones
                # コードからスケールを決定（拍ごとの調を参照）
                bsg_key = (self._expo_beat_key_map.get(beat, self.key)
                           if hasattr(self, '_expo_beat_key_map')
                           else self.key)
                b_scale = (bsg_key.scale_for_chord(beat_chord_tones)
                           if beat_chord_tones else bsg_key.scale)
                elaborated = elaborator.elaborate_beat(
                    skeleton, next_skeleton, pattern, VOICE_RANGES[vt],
                    chord_tones=beat_chord_tones,
                    beat_scale=b_scale)

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

    # ================================================================
    # 並行同度/8度の修復（展開形変更）
    # ================================================================

    @staticmethod
    def _repair_parallel_octaves_in_grid(
        grid: Dict['FugueVoiceType', List[Optional[int]]],
        chord_plan: List['ChordLabel'],
        subject_beats: Dict['FugueVoiceType', Set[int]],
        key_obj: 'Key',
        beat_key_map: Optional[Dict[int, 'Key']] = None,
    ) -> Dict['FugueVoiceType', List[Optional[int]]]:
        """サブビートグリッド上の並行同度/8度を展開形変更で修復

        各拍の拍頭音（subbeat 0）で全声部ペアを走査し、
        連続する2拍で同度/8度の並行進行があれば、
        主題外の声部の音を和音の別の構成音に変更する。

        Args:
            grid: subbeat-level grid
            chord_plan: beat-level chord plan
            subject_beats: 各声部の主題拍集合
            key_obj: デフォルトの調
            beat_key_map: 拍ごとの調マップ（省略可）
        """
        SB = SUBBEATS_PER_BEAT
        voices = [vt for vt in grid if any(
            p is not None for p in grid[vt])]
        num_beats = len(chord_plan)
        repairs = 0

        for beat in range(1, num_beats):
            sb_prev = (beat - 1) * SB
            sb_curr = beat * SB
            if sb_prev >= len(grid[voices[0]]) or sb_curr >= len(grid[voices[0]]):
                continue

            for i in range(len(voices)):
                for j in range(i + 1, len(voices)):
                    v1, v2 = voices[i], voices[j]
                    p1_prev = grid[v1][sb_prev]
                    p1_curr = grid[v1][sb_curr]
                    p2_prev = grid[v2][sb_prev]
                    p2_curr = grid[v2][sb_curr]

                    if any(p is None for p in [p1_prev, p1_curr, p2_prev, p2_curr]):
                        continue

                    # 両声部とも静止なら問題なし
                    if p1_prev == p1_curr and p2_prev == p2_curr:
                        continue

                    # 並行同度/8度の判定
                    interval_prev = abs(p1_prev - p2_prev) % 12
                    interval_curr = abs(p1_curr - p2_curr) % 12
                    if not (interval_prev == 0 and interval_curr == 0):
                        continue  # 並行同度/8度でない

                    # 修復対象: 主題拍でない声部を選択
                    target_vt = None
                    target_beat = beat
                    if target_beat not in subject_beats.get(v2, set()):
                        target_vt = v2
                    elif target_beat not in subject_beats.get(v1, set()):
                        target_vt = v1
                    else:
                        # 前拍で試行
                        target_beat = beat - 1
                        if target_beat not in subject_beats.get(v2, set()):
                            target_vt = v2
                        elif target_beat not in subject_beats.get(v1, set()):
                            target_vt = v1

                    if target_vt is None:
                        continue  # 両方とも主題拍 → 修復不可

                    # 目標拍の和音構成音を取得
                    if target_beat < len(chord_plan):
                        chord_tones = chord_plan[target_beat].tones
                    else:
                        continue

                    # 現在の音のPC
                    sb_target = target_beat * SB
                    curr_pitch = grid[target_vt][sb_target]
                    if curr_pitch is None:
                        continue
                    curr_pc = curr_pitch % 12

                    # 別の和音構成音を選択（現在のPCと異なるもの）
                    lo, hi = VOICE_RANGES.get(target_vt, (36, 84))
                    best_alt = None
                    best_cost = float('inf')
                    for alt_pc in chord_tones:
                        if alt_pc == curr_pc:
                            continue  # 同じPC → 同度のまま
                        # 最寄りのオクターブを探す
                        for midi_val in range(lo, hi + 1):
                            if midi_val % 12 != alt_pc:
                                continue
                            cost = abs(midi_val - curr_pitch)
                            # 他の声部との半音衝突チェック
                            has_clash = False
                            for ov in voices:
                                if ov == target_vt:
                                    continue
                                ov_pitch = grid[ov][sb_target]
                                if ov_pitch is not None:
                                    d = abs(midi_val - ov_pitch)
                                    if d == 1 or d == 11:
                                        has_clash = True
                                        break
                            if has_clash:
                                continue
                            # 新たな並行を生まないか確認
                            new_parallel = False
                            for ov in voices:
                                if ov == target_vt:
                                    continue
                                if target_beat == beat:
                                    ov_prev = grid[ov][(beat - 1) * SB]
                                    ov_curr_p = midi_val
                                    tv_prev = grid[target_vt][(beat - 1) * SB]
                                    # 新しい音で並行8度になるか
                                    if (ov_prev is not None and tv_prev is not None
                                            and abs(ov_prev - tv_prev) % 12 == 0
                                            and abs(grid[ov][sb_target] - midi_val) % 12 == 0):
                                        new_parallel = True
                                        break
                            if new_parallel:
                                continue
                            if cost < best_cost:
                                best_cost = cost
                                best_alt = midi_val

                    if best_alt is not None:
                        # サブビート全体を書き換え（同じ拍内で同じ音のサブビート）
                        old_pitch = grid[target_vt][sb_target]
                        for s in range(SB):
                            sb_idx = target_beat * SB + s
                            if sb_idx < len(grid[target_vt]):
                                if grid[target_vt][sb_idx] == old_pitch:
                                    grid[target_vt][sb_idx] = best_alt
                                else:
                                    break  # 装飾で音が変わっていたらそこで止める
                        repairs += 1

        if repairs > 0:
            print(f"  並行8度修復: {repairs}箇所の展開形を変更")
        return grid

    # ================================================================
    # 和音充足検証・修復
    # ================================================================

    # 代理和音マッピング: degree → 代理候補の degree リスト
    _SUBSTITUTE_MAP = {
        0: [5],    # I → vi
        5: [0],    # vi → I
        3: [1],    # IV → ii
        1: [3],    # ii → IV
        4: [2],    # V → iii
        2: [4],    # iii → V
    }

    def _verify_and_repair_chord_coverage(
        self,
        melodies: Dict['FugueVoiceType', List[Optional[int]]],
        chord_plan: List['ChordLabel'],
        subject_beats: Optional[Dict['FugueVoiceType', Set[int]]] = None,
        diatonic_chords: Optional[List['ChordLabel']] = None,
        allow_chord_modification: bool = True,
    ) -> Tuple[Dict['FugueVoiceType', List[Optional[int]]], List['ChordLabel']]:
        """DP生成後の和音充足検証・修復

        各拍で根音・第3音が全声部を通じて存在するか検証し、
        欠落時は (1) 代理和音への差替え (2) 声部音の修正
        (3) 和音再割当て+声部修正 で修復する。

        Args:
            melodies: 各声部のbeat-levelメロディ
            chord_plan: 拍ごとの和声計画
            subject_beats: 主題が配置されている拍の集合（修正対象外）
            diatonic_chords: ローカルキーのダイアトニック和音リスト（7要素）
            allow_chord_modification: Falseの場合、和声計画の変更を禁止し
                声部音の修正のみ許可する。提示部のトップダウン和声計画を
                保護するために使用。

        Returns:
            (修復済みmelodies, 修復済みchord_plan)
        """
        if subject_beats is None:
            subject_beats = {vt: set() for vt in melodies}

        # ダイアトニック和音リストの確定
        _dia = diatonic_chords
        if _dia is None and hasattr(self, 'analyzer') and self.analyzer:
            _dia = self.analyzer.diatonic_chords
        if _dia is None:
            _dia = []

        def _get_dia(deg: int) -> Optional['ChordLabel']:
            if 0 <= deg < len(_dia):
                return _dia[deg]
            return None

        voices = list(melodies.keys())
        num_beats = min(len(chord_plan), *(len(melodies[v]) for v in voices))

        for beat in range(num_beats):
            chord = chord_plan[beat]

            # 全声部のPCを収集
            voice_pitches: Dict['FugueVoiceType', Optional[int]] = {}
            present_pcs: Set[int] = set()
            active_count = 0
            for vt in voices:
                p = melodies[vt][beat]
                voice_pitches[vt] = p
                if p is not None:
                    present_pcs.add(p % 12)
                    active_count += 1

            # 声部が2つ未満なら検証不要（提示部冒頭など）
            if active_count < 2:
                continue

            root_ok = chord.root_pc in present_pcs
            third_ok = chord.third_pc in present_pcs

            if root_ok and third_ok:
                continue  # 根音・第3音とも存在 → OK

            # --- (1) 代理和音への差替えを試行 ---
            # allow_chord_modification=False の場合はスキップ（和声計画保護）
            substituted = False
            if allow_chord_modification:
                sub_degrees = self._SUBSTITUTE_MAP.get(chord.degree, [])
                for sub_deg in sub_degrees:
                    # 現在の調のダイアトニック和音を取得
                    sub_chord = _get_dia(sub_deg)
                    if sub_chord is None:
                        continue
                    # 全声部の現在音が代理和音の構成音に含まれるか
                    all_fit = True
                    for vt in voices:
                        p = voice_pitches[vt]
                        if p is not None and p % 12 not in sub_chord.tones:
                            all_fit = False
                            break
                    if all_fit:
                        # 代理和音の根音・第3音も存在するか確認
                        sub_root_ok = sub_chord.root_pc in present_pcs
                        sub_third_ok = sub_chord.third_pc in present_pcs
                        if sub_root_ok and sub_third_ok:
                            chord_plan[beat] = sub_chord
                            substituted = True
                            break

            if substituted:
                continue

            # --- (2) 声部音の修正 ---
            # 欠落しているPCを特定
            missing_pcs = []
            if not root_ok:
                missing_pcs.append(chord.root_pc)
            if not third_ok:
                missing_pcs.append(chord.third_pc)

            for missing_pc in missing_pcs:
                # 修正対象の声部を選択: 主題声部以外で旋律的影響が最小の声部
                best_voice = None
                best_new_pitch = None
                best_cost = float('inf')

                # 各PCを提供している声部数をカウント（重複検出用）
                pc_providers: Dict[int, int] = {}
                for vt in voices:
                    p = voice_pitches[vt]
                    if p is not None:
                        pc = p % 12
                        pc_providers[pc] = pc_providers.get(pc, 0) + 1

                for vt in voices:
                    p = voice_pitches[vt]
                    if p is None:
                        continue
                    # 主題声部は修正対象外
                    if beat in subject_beats.get(vt, set()):
                        continue
                    # この声部のPCが根音か第3音の場合、
                    # 他の声部も同じPCを提供していれば変更可能（重複提供）
                    pc = p % 12
                    if pc == chord.root_pc or pc == chord.third_pc:
                        if pc_providers.get(pc, 0) <= 1:
                            continue  # 唯一の提供者→修正不可

                    # 最寄りのmissing_pcオクターブを探す
                    lo, hi = VOICE_RANGES.get(vt, (36, 84))
                    candidate = self._nearest_pitch_with_pc(p, missing_pc, lo, hi)
                    if candidate is None:
                        continue

                    # コスト = 跳躍量 + 前後との連続性
                    interval = abs(candidate - p)
                    # 前の拍との連続性
                    prev_cost = 0
                    if beat > 0 and melodies[vt][beat - 1] is not None:
                        prev_cost = abs(candidate - melodies[vt][beat - 1])
                    # 次の拍との連続性
                    next_cost = 0
                    if beat + 1 < num_beats and melodies[vt][beat + 1] is not None:
                        next_cost = abs(candidate - melodies[vt][beat + 1])
                    cost = interval + prev_cost * 0.5 + next_cost * 0.5

                    if cost < best_cost:
                        best_cost = cost
                        best_voice = vt
                        best_new_pitch = candidate

                if best_voice is not None and best_new_pitch is not None:
                    # 半音衝突チェック: 修正後の音が他声部と半音衝突しないか
                    new_pc = best_new_pitch % 12
                    has_clash = False
                    for vt2 in voices:
                        if vt2 == best_voice:
                            continue
                        p2 = voice_pitches[vt2]
                        if p2 is not None:
                            diff = abs(best_new_pitch - p2)
                            if diff == 1 or diff == 11:
                                has_clash = True
                                break
                    # 平行5/8度チェック: 修正後に平行禁則が生じないか
                    if not has_clash and beat > 0:
                        _proh = CounterpointProhibitions()
                        prev_pitch_bv = melodies[best_voice][beat - 1]
                        if prev_pitch_bv is not None:
                            for vt2 in voices:
                                if vt2 == best_voice:
                                    continue
                                p2_prev = melodies[vt2][beat - 1]
                                p2_curr = voice_pitches[vt2]
                                if p2_prev is not None and p2_curr is not None:
                                    ok, _ = _proh.check_parallel_perfect(
                                        prev_pitch_bv, best_new_pitch,
                                        p2_prev, p2_curr)
                                    if not ok:
                                        has_clash = True
                                        break
                    if not has_clash:
                        melodies[best_voice][beat] = best_new_pitch
                        voice_pitches[best_voice] = best_new_pitch
                        present_pcs.add(missing_pc)

            # --- (3) 最終フォールバック: 和音再割当て + 声部修正の合わせ技 ---
            # allow_chord_modification=False の場合はスキップ（和声計画保護）
            if not allow_chord_modification:
                continue

            # present_pcsだけでは根音+第3音が揃わない場合、
            # 和音変更と声部修正を組み合わせて解決する。
            present_pcs_now = set()
            for vt in voices:
                p = melodies[vt][beat]
                if p is not None:
                    present_pcs_now.add(p % 12)

            final_chord = chord_plan[beat]
            final_root_ok = final_chord.root_pc in present_pcs_now
            final_third_ok = final_chord.third_pc in present_pcs_now

            if final_root_ok and final_third_ok:
                continue

            # (3a) 純粋な和音再割当て: present_pcsだけでroot+third揃う和音
            best_reassign = None
            best_score = -1
            for deg in range(7):
                cand = _get_dia(deg)
                if cand is None:
                    continue
                if (cand.root_pc in present_pcs_now
                        and cand.third_pc in present_pcs_now):
                    score = 0
                    for pc in present_pcs_now:
                        if pc in cand.tones:
                            score += 1
                    if score > best_score:
                        best_score = score
                        best_reassign = cand
            if best_reassign is not None:
                chord_plan[beat] = best_reassign
                continue

            # (3b) 和音再割当て + 1声部修正の組み合わせ
            # 各候補和音について、1声部を修正すればroot+third揃うか試す
            best_combo = None  # (chord, voice, new_pitch, cost)
            best_combo_cost = float('inf')
            for deg in range(7):
                cand = _get_dia(deg)
                if cand is None:
                    continue
                cand_root_ok = cand.root_pc in present_pcs_now
                cand_third_ok = cand.third_pc in present_pcs_now
                if cand_root_ok and cand_third_ok:
                    continue  # already handled in 3a
                if not cand_root_ok and not cand_third_ok:
                    continue  # 2声部修正が必要→スキップ
                # 1つだけ欠落 → 1声部修正で解決可能
                need_pc = cand.root_pc if not cand_root_ok else cand.third_pc
                for vt in voices:
                    p = melodies[vt][beat]
                    if p is None:
                        continue
                    if beat in subject_beats.get(vt, set()):
                        continue
                    pc = p % 12
                    # この声部のPCが候補和音のroot/thirdなら修正不可
                    if pc == cand.root_pc or pc == cand.third_pc:
                        continue
                    lo, hi = VOICE_RANGES.get(vt, (36, 84))
                    new_p = self._nearest_pitch_with_pc(p, need_pc, lo, hi)
                    if new_p is None:
                        continue
                    # 半音衝突チェック
                    combo_clash = False
                    for vt2 in voices:
                        if vt2 == vt:
                            continue
                        p2 = melodies[vt2][beat]
                        if p2 is not None:
                            d = abs(new_p - p2)
                            if d == 1 or d == 11:
                                combo_clash = True
                                break
                    if combo_clash:
                        continue
                    cost = abs(new_p - p)
                    if beat > 0 and melodies[vt][beat - 1] is not None:
                        cost += abs(new_p - melodies[vt][beat - 1]) * 0.5
                    if beat + 1 < num_beats and melodies[vt][beat + 1] is not None:
                        cost += abs(new_p - melodies[vt][beat + 1]) * 0.5
                    if cost < best_combo_cost:
                        best_combo_cost = cost
                        best_combo = (cand, vt, new_p)

            if best_combo is not None:
                cand, mod_vt, new_p = best_combo
                chord_plan[beat] = cand
                melodies[mod_vt][beat] = new_p

        return melodies, chord_plan

    def _get_diatonic_chord_for_beat(
        self,
        beat: int,
        chord_plan: List['ChordLabel'],
        target_degree: int,
    ) -> Optional['ChordLabel']:
        """指定拍の調に対応するダイアトニック和音を取得"""
        # SubjectHarmonicAnalyzerのdiatonic_chordsから取得
        if hasattr(self, 'analyzer') and self.analyzer:
            diatonic = self.analyzer.diatonic_chords
            if 0 <= target_degree < len(diatonic):
                return diatonic[target_degree]
        return None

    @staticmethod
    def _nearest_pitch_with_pc(
        current: int, target_pc: int, lo: int, hi: int
    ) -> Optional[int]:
        """currentに最も近い、target_pcを持つMIDIピッチを返す"""
        best = None
        best_dist = float('inf')
        for midi in range(lo, hi + 1):
            if midi % 12 == target_pc:
                dist = abs(midi - current)
                if dist < best_dist:
                    best_dist = dist
                    best = midi
        return best

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
