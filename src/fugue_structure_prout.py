"""
フーガ構造モジュール（Prout 準拠）
Fugue Structure Module - Based on Ebenezer Prout

フーガに特有の構造要素を定義・管理する。
調的応答（tonal answer）、コデッタ、エピソード構成を含む。

理論的根拠:
- Ebenezer Prout: "Fugue" (1891) ← 主要参照文献
- André Gedalge: "Traité de la Fugue" (1901)
- Johann Joseph Fux: "Gradus ad Parnassum" (1725)

Prout の体系:
  Ch.I-II   : 主題の性格と構造
  Ch.III-IV : 応答（調的応答 vs 実音応答）
  Ch.V      : 対主題（counter-subject）
  Ch.VI     : コデッタ（codetta）
  Ch.VII    : エピソード（episode）
  Ch.VIII   : ストレット（stretto）
  Ch.IX-X   : 中間部の主題提示と調性計画
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Set
from enum import Enum

from harmony_rules_complete import Pitch, HarmonyRules
from counterpoint_engine import (
    InvertibleCounterpoint,
    CounterpointProhibitions,
)


# ============================================================
# 音名 → ピッチクラス変換
# ============================================================

NOTE_TO_PC = {
    'C': 0, 'C#': 1, 'Db': 1,
    'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'Fb': 4,
    'F': 5, 'F#': 6, 'Gb': 6,
    'G': 7, 'G#': 8, 'Ab': 8,
    'A': 9, 'A#': 10, 'Bb': 10,
    'B': 11, 'Cb': 11,
}

PC_TO_NOTE = {
    0: 'C', 1: 'C#', 2: 'D', 3: 'D#', 4: 'E', 5: 'F',
    6: 'F#', 7: 'G', 8: 'G#', 9: 'A', 10: 'A#', 11: 'B',
}


# ============================================================
# 基本定義
# ============================================================

class FugueVoiceType(Enum):
    """フーガにおける声部の種類"""
    SOPRANO = "soprano"
    ALTO = "alto"
    TENOR = "tenor"
    BASS = "bass"


class FugueSection(Enum):
    """フーガの構成部分"""
    EXPOSITION = "exposition"      # 提示部
    CODETTA = "codetta"            # コデッタ（接続句）
    EPISODE = "episode"            # 間奏部（エピソード）
    MIDDLE_ENTRY = "middle_entry"  # 中間提示
    STRETTO = "stretto"            # ストレット
    CODA = "coda"                  # コーダ


class AnswerType(Enum):
    """応答の種類（Prout Ch.III）"""
    REAL = "real"       # 実音応答: 全音を機械的に5度上移調
    TONAL = "tonal"     # 調的応答: 主音-属音軸の修正を伴う移調


# ============================================================
# 調性
# ============================================================

@dataclass
class Key:
    """調性を表現するクラス"""
    tonic: str   # 主音（例: "C", "D", "F#"）
    mode: str    # 旋法（"major" or "minor"）

    @property
    def tonic_pc(self) -> int:
        """主音のピッチクラス（0-11）"""
        return NOTE_TO_PC.get(self.tonic, 0)

    @property
    def scale(self) -> List[int]:
        """音階のピッチクラス列"""
        rules = HarmonyRules()
        if self.mode == "major":
            return rules.get_major_scale(self.tonic_pc)
        else:
            return rules.get_harmonic_minor_scale(self.tonic_pc)

    @property
    def dominant_pc(self) -> int:
        """属音のピッチクラス"""
        return self.scale[4]

    @property
    def leading_tone_pc(self) -> int:
        """導音のピッチクラス"""
        return self.scale[6]

    @property
    def subdominant_pc(self) -> int:
        """下属音のピッチクラス"""
        return self.scale[3]

    def get_scale_degree(self, pitch_class: int) -> Optional[int]:
        """ピッチクラスの音階度数（0-6）を返す。音階外ならNone"""
        try:
            return self.scale.index(pitch_class)
        except ValueError:
            return None

    def get_dominant_key(self) -> 'Key':
        """属調を取得"""
        dom_pc = self.dominant_pc
        return Key(PC_TO_NOTE.get(dom_pc, 'G'), "major")

    def get_subdominant_key(self) -> 'Key':
        """下属調を取得"""
        sub_pc = self.scale[3]
        return Key(PC_TO_NOTE.get(sub_pc, 'F'), self.mode)

    def get_relative_key(self) -> 'Key':
        """平行調を取得"""
        if self.mode == "major":
            rel_pc = self.scale[5]
            return Key(PC_TO_NOTE.get(rel_pc, 'A'), "minor")
        else:
            rel_pc = self.scale[2]
            return Key(PC_TO_NOTE.get(rel_pc, 'C'), "major")


# ============================================================
# 主題（Subject） — Prout Ch.I-II
# ============================================================

@dataclass
class Subject:
    """フーガの主題

    Prout Ch.I:
    - 主題は明確な調性を確立すること
    - 主音または属音で開始するのが一般的
    - 長さは通常1-4小節
    - 強い旋律的輪郭を持つこと
    """
    pitches: List[Pitch]
    key: Key
    name: str = "主題"

    def get_length(self) -> int:
        """主題の長さ（音符数）"""
        return len(self.pitches)

    def transpose(self, semitones: int) -> 'Subject':
        """主題を移調"""
        transposed = [Pitch(p.midi + semitones) for p in self.pitches]
        return Subject(transposed, self.key, f"{self.name}(移調)")

    # ================================================================
    # 応答生成 — Prout Ch.III-IV (中核ロジック)
    # ================================================================

    def get_answer(self, answer_type: str = "tonal") -> 'Subject':
        """応答（Answer）を生成

        Prout Ch.III:
        - 実音応答 (real): 全音を機械的に完全5度上に移調
        - 調的応答 (tonal): 主音-属音の対応関係を修正して移調

        Prout の原則:
        「主題中の主音(1度)は応答で属音(5度)に、
         主題中の属音(5度)は応答で主音(1度)に対応する」

        Args:
            answer_type: "tonal" または "real"
        """
        if answer_type == "real":
            return self._real_answer()
        else:
            return self._tonal_answer()

    def _real_answer(self) -> 'Subject':
        """実音応答（Prout Ch.III §1）

        全ての音を一律に7半音（完全5度）上げる。
        主題が主調の音階内に留まり、属音を含まない場合に適切。
        """
        answer = self.transpose(7)
        answer.name = "応答（実音）"
        answer.key = self.key.get_dominant_key()
        return answer

    def _tonal_answer(self) -> 'Subject':
        """調的応答（Prout Ch.III-IV）

        Prout の規則体系:

        §1. 主題を「頭部（head）」と「尾部（tail）」に分割する。
            - 頭部: 主音-属音軸を確立する最初の区間
              （最初の属音到達まで、または最初の主音回帰まで）
            - 尾部: それ以降

        §2. 頭部の音程変換（mutation）:
            - 主題の1度(tonic) → +7半音（属調の主音へ）
            - 主題の5度(dominant) → +5半音（主調の主音へ = mutation）
            - その他の音階音 → +7半音（実音移調）
            - 半音階音 → +7半音

        §3. 尾部は実音移調（+7半音）をそのまま適用する。

        §4. 属音で開始する主題:
            - 応答は主音で開始する（+5半音、+7ではない）

        §5. 主音で開始する主題:
            - 応答は属音で開始する（+7半音）

        核心原理（Prout Ch.III §8）:
        「主題中の主音(1度)は応答で属音(5度)に対応し、
         主題中の属音(5度)は応答で主音(1度)に対応する。
         それ以外の音は実音移調される。」
        """
        tonic_pc = self.key.tonic_pc
        dominant_pc = self.key.dominant_pc

        # 頭部/尾部分割
        head, tail = self.get_head_tail_split()

        answer_pitches = []

        # ---- 頭部: 主音-属音軸の mutation ----
        for p in head:
            pc = p.midi % 12
            degree = self.key.get_scale_degree(pc)

            if degree == 4:
                # 属音(5度) → 主音(1度): +5半音 (mutation)
                # Prout §8: 「属音は応答で主音に対応する」
                answer_pitches.append(Pitch(p.midi + 5))
            else:
                # 主音(1度)およびその他すべて → +7半音（実音移調）
                # Prout: 主音は +7 で属調の主音に到達する
                answer_pitches.append(Pitch(p.midi + 7))

        # ---- 尾部: 実音移調 ----
        for p in tail:
            answer_pitches.append(Pitch(p.midi + 7))

        dom_key = self.key.get_dominant_key()
        return Subject(answer_pitches, dom_key, "応答（調的）")

    def _is_tonic_region_context(self, built: List[Pitch],
                                  head: List[Pitch], current: Pitch) -> bool:
        """直前の文脈が主調領域にあるか判定

        Prout の文脈判定: 主題の冒頭部分が主調の主和音
        (I度: 1-3-5) の構成音で始まっていれば主調領域。
        """
        tonic_triad = {
            self.key.tonic_pc,
            self.key.scale[2],   # 3度
            self.key.dominant_pc  # 5度
        }
        # 先頭から current の直前までの音が主調の主和音構成音か
        idx = head.index(current) if current in head else len(head)
        if idx == 0:
            return True
        preceding = [p.midi % 12 for p in head[:idx]]
        tonic_count = sum(1 for pc in preceding if pc in tonic_triad)
        return tonic_count > len(preceding) / 2

    def _is_in_dominant_region(self, pitch: Pitch,
                                head: List[Pitch]) -> bool:
        """音が属調領域にあるか判定

        Prout: 主題中の属音以降の部分は属調領域とみなす。
        最初の属音が出現した後の音は属調領域。
        """
        dominant_pc = self.key.dominant_pc
        found_dominant = False
        for p in head:
            if p.midi % 12 == dominant_pc:
                found_dominant = True
            if p is pitch:
                return found_dominant
        return False

    def needs_tonal_answer(self) -> bool:
        """調的応答が必要か判定（Prout Ch.III §1）

        Prout: 以下の場合に調的応答が必要:
        1. 主題が属音を含む（特に頭部に）
        2. 主題が属調に転調する
        3. 主題が主音-属音の跳躍で始まる

        実音応答が適切な場合:
        1. 主題が音階的で属音を強調しない
        2. 主題が主調内に留まる
        """
        dominant_pc = self.key.dominant_pc
        tonic_pc = self.key.tonic_pc

        # 属音で開始 → 調的応答が必要
        if self.pitches and self.pitches[0].midi % 12 == dominant_pc:
            return True

        # 最初の2音が主音→属音 → 調的応答が必要
        if len(self.pitches) >= 2:
            pc0 = self.pitches[0].midi % 12
            pc1 = self.pitches[1].midi % 12
            if pc0 == tonic_pc and pc1 == dominant_pc:
                return True

        # 頭部に属音を含む → 調的応答が必要
        head, _ = self.get_head_tail_split()
        for p in head:
            if p.midi % 12 == dominant_pc:
                return True

        return False

    # ---- 主題変形（Prout Ch.VIII-X） ----

    def invert(self) -> 'Subject':
        """主題を反転（上下逆転）

        Prout: ストレットや展開部で使用される技法。
        最初の音を軸として、上行を下行に、下行を上行に変換。
        """
        if not self.pitches:
            return Subject([], self.key, f"{self.name}(反転)")
        axis = self.pitches[0].midi
        inverted = [Pitch(axis - (p.midi - axis)) for p in self.pitches]
        return Subject(inverted, self.key, f"{self.name}(反転)")

    def retrograde(self) -> 'Subject':
        """主題を逆行"""
        rev = list(reversed(self.pitches))
        return Subject(rev, self.key, f"{self.name}(逆行)")

    def retrograde_inversion(self) -> 'Subject':
        """主題を反転逆行"""
        return self.invert().retrograde()

    def augmentation(self, factor: int = 2) -> 'Subject':
        """主題を拡大（音価を整数倍）

        Prout Ch.X: ストレットで頻用。音高は不変、音価のみ変化。
        現在は音価情報未実装のためメタ情報として保持。
        """
        aug = Subject(list(self.pitches), self.key,
                      f"{self.name}(拡大×{factor})")
        return aug

    def diminution(self, factor: int = 2) -> 'Subject':
        """主題を縮小（音価を整数分の1）"""
        dim = Subject(list(self.pitches), self.key,
                      f"{self.name}(縮小÷{factor})")
        return dim

    # ---- 分析 ----

    def get_head_tail_split(self) -> Tuple[List[Pitch], List[Pitch]]:
        """主題を「頭部」と「尾部」に分割（Prout Ch.III §4）

        Prout の定義:
        - 頭部（head）: 主音-属音軸を確立する区間
          → 最初の属音到達まで（属音を含む）
        - 尾部（tail）: それ以降
          → 実音移調がそのまま適用される部分

        属音がない場合は全体が頭部（→ 実音応答が適切）。
        """
        dominant_pc = self.key.dominant_pc
        for i, p in enumerate(self.pitches):
            if p.midi % 12 == dominant_pc:
                return self.pitches[:i + 1], self.pitches[i + 1:]
        return list(self.pitches), []

    def analyze_intervals(self) -> List[int]:
        """音程列を返す（半音数、符号付き）"""
        intervals = []
        for i in range(len(self.pitches) - 1):
            intervals.append(self.pitches[i + 1].midi - self.pitches[i].midi)
        return intervals

    def get_opening_degree(self) -> Optional[int]:
        """主題の開始音の音階度数を返す（Prout Ch.III §1）

        Prout: 主題は通常、主音(1度)または属音(5度)で開始する。
        """
        if not self.pitches:
            return None
        return self.key.get_scale_degree(self.pitches[0].midi % 12)


# ============================================================
# コデッタ（Codetta） — Prout Ch.VI
# ============================================================

@dataclass
class Codetta:
    """コデッタ（接続句）

    Prout Ch.VI:
    - 主題の終止と応答の開始を接続する短い経過句
    - 主題の終止音から応答の開始音への滑らかな移行を確保する
    - 通常1-2拍、長くても1小節以内
    - 主題末尾の素材から派生させることが望ましい

    用途:
    - 主題が主音で終わり、応答が属音で始まる場合、
      直接接続すると和声的に不自然になりうる → コデッタで橋渡し
    """
    pitches: List[Pitch]
    name: str = "コデッタ"

    def get_length(self) -> int:
        return len(self.pitches)

    @staticmethod
    def needs_codetta(subject: Subject, answer: Subject) -> bool:
        """コデッタが必要か判定（Prout Ch.VI §1-2）

        Prout:
        - 主題の末尾と応答の冒頭が同度または近い → 不要
        - 主題の末尾と応答の冒頭に大きな跳躍 → 必要
        - 主題が主音で終止し応答が属音で開始 → 推奨
        """
        if not subject.pitches or not answer.pitches:
            return False

        last_midi = subject.pitches[-1].midi
        first_answer = answer.pitches[0].midi
        interval = abs(first_answer - last_midi)

        # 5度以上の跳躍 → コデッタ推奨
        if interval >= 7:
            return True

        # 4度の跳躍 → 文脈次第だが推奨
        if interval >= 5:
            return True

        return False

    @staticmethod
    def generate_codetta(subject: Subject, answer: Subject,
                         max_length: int = 3) -> 'Codetta':
        """コデッタを自動生成（Prout Ch.VI §3-5）

        Prout の推奨:
        - 主題末尾の動機から素材を取る
        - 順次進行で応答の開始音に接続する
        - 可能な限り短く

        Returns:
            生成されたコデッタ
        """
        if not subject.pitches or not answer.pitches:
            return Codetta([], "コデッタ（空）")

        start = subject.pitches[-1].midi
        target = answer.pitches[0].midi
        diff = target - start

        if abs(diff) <= 2:
            # 順次進行で直接接続可能 → 1音のコデッタ
            mid = start + (1 if diff > 0 else -1)
            return Codetta([Pitch(mid)], "コデッタ")

        # 順次進行で段階的に接続
        pitches = []
        step = 2 if diff > 0 else -2
        current = start
        for _ in range(max_length):
            current += step
            if abs(current - target) <= 2:
                break
            pitches.append(Pitch(current))

        return Codetta(pitches, "コデッタ")


# ============================================================
# 対主題（Counter-subject） — Prout Ch.V
# ============================================================

@dataclass
class Countersubject:
    """対主題（Counter-subject）

    Prout Ch.V:
    - 対主題は主題と同時に鳴る対旋律
    - 主題と転回可能対位法（通常はオクターブ転回）で書くべき
    - 主題と対照的なリズムを持つべき
    - 主題の上にも下にも配置可能でなければならない

    Prout の3条件:
    1. 主題との転回可能性（invertibility）
    2. リズムの対照（rhythmic contrast）
    3. 独立した旋律的関心（melodic interest）
    """
    pitches: List[Pitch]
    name: str = "対主題"

    def check_invertibility(
        self, subject_pitches: List[Pitch],
    ) -> Tuple[bool, List[str]]:
        """主題との転回可能性を検証（Prout Ch.V §3-5）

        Prout:
        「対主題が主題の上にあるとき成立し、
         かつ下にあるときにも成立すること」
        """
        inv = InvertibleCounterpoint()
        upper = [p.midi for p in subject_pitches]
        lower = [p.midi for p in self.pitches]

        # 対主題が上の場合
        valid_above, errs_above = inv.check_invertible_at_octave(
            [p.midi for p in self.pitches], upper
        )
        # 主題が上の場合
        valid_below, errs_below = inv.check_invertible_at_octave(
            upper, lower
        )

        all_errors = []
        if not valid_above:
            all_errors.extend([f"対主題が上: {e}" for e in errs_above])
        if not valid_below:
            all_errors.extend([f"対主題が下: {e}" for e in errs_below])

        return len(all_errors) == 0, all_errors

    def find_fifths_to_avoid(
        self, subject_pitches: List[Pitch],
    ) -> List[Tuple[int, str]]:
        """転回時に問題となる5度の位置を特定（Prout Ch.V §6）

        Prout: 「5度はオクターブ転回で4度となり、
        対位法上で不協和音程として扱われることがある」
        """
        inv = InvertibleCounterpoint()
        upper = [p.midi for p in subject_pitches]
        lower = [p.midi for p in self.pitches]
        return inv.find_problematic_fifth(upper, lower)


# ============================================================
# エピソード（Episode） — Prout Ch.VII
# ============================================================

@dataclass
class Episode:
    """エピソード（間奏部）

    Prout Ch.VII:
    - 主題提示と主題提示の間を接続する部分
    - 主題または対主題の素材から反復進行（sequence）で構成
    - 調性の推移（modulation）を担う
    - 通常2-8小節

    Prout の構成原則:
    1. 主題の断片（動機）を用いる
    2. 反復進行（上行または下行）で展開する
    3. 次の主題提示の調性へ導く
    """
    motif_pitches: List[Pitch]       # 動機（主題からの抽出）
    sequence_steps: int = 3          # 反復進行の回数
    step_interval: int = -2          # 各反復の移調幅（半音数）
    source: str = "主題"             # 素材源

    def generate_pitches(self) -> List[Pitch]:
        """エピソードの音列を生成（Prout Ch.VII §2-4）

        Prout の反復進行（sequence）:
        - 動機を一定音程ずつ移調して繰り返す
        - 下行反復進行が最も一般的
        - 2度下行または3度下行が典型
        """
        all_pitches = []
        for step in range(self.sequence_steps):
            offset = step * self.step_interval
            for p in self.motif_pitches:
                all_pitches.append(Pitch(p.midi + offset))
        return all_pitches

    def get_total_length(self) -> int:
        """エピソードの総音符数"""
        return len(self.motif_pitches) * self.sequence_steps

    @staticmethod
    def extract_motif(subject: Subject, start: int = 0,
                      length: int = 3) -> List[Pitch]:
        """主題から動機を抽出（Prout Ch.VII §1）

        Prout: 「エピソードの素材は主題の一部分から取るべし」
        通常は主題の冒頭部分（head motif）を使用。
        """
        end = min(start + length, subject.get_length())
        return list(subject.pitches[start:end])


# ============================================================
# フーガの登場（Entry）
# ============================================================

@dataclass
class FugueEntry:
    """フーガにおける主題の登場"""
    subject: Subject
    voice_type: FugueVoiceType
    start_position: int   # 開始位置（拍単位）
    key: Key
    is_answer: bool = False


# ============================================================
# フーガ構造 — Prout Ch.I-X 統合
# ============================================================

class FugueStructure:
    """フーガ全体の構造を管理

    Prout の標準的フーガ構造:
    1. 提示部（Exposition）: 全声部が主題/応答を順次提示
    2. エピソード1: 転調
    3. 中間部（Middle Section）: 近親調での主題提示
    4. エピソード2
    5. ストレット（任意）: 主題の密接模倣
    6. コーダ: 終結部（ペダルポイントを含むことが多い）
    """

    def __init__(self, num_voices: int, main_key: Key, subject: Subject):
        self.num_voices = num_voices
        self.main_key = main_key
        self.subject = subject
        self.entries: List[FugueEntry] = []
        self.sections: List[Tuple[FugueSection, int, int]] = []
        self.codettas: List[Codetta] = []
        self.episodes: List[Episode] = []

    def create_exposition(self,
                          answer_type: str = "auto") -> List[FugueEntry]:
        """提示部を生成（Prout Ch.I §1-3）

        Prout:
        - 第1声部: 主題（主調）
        - 第2声部: 応答（属調）
        - 第3声部: 主題（主調）
        - 第4声部: 応答（属調）
        - 主題と応答の間にコデッタを挿入可能

        Args:
            answer_type: "tonal", "real", "auto"
                "auto"の場合、needs_tonal_answer()で自動判定
        """
        entries = []
        voice_order = self._get_voice_order()

        # 応答タイプの自動判定
        if answer_type == "auto":
            actual_type = "tonal" if self.subject.needs_tonal_answer() else "real"
        else:
            actual_type = answer_type

        answer = self.subject.get_answer(actual_type)

        position = 0
        for i, voice_type in enumerate(voice_order):
            if i % 2 == 0:
                # 主題（主調）
                entry = FugueEntry(
                    subject=self.subject,
                    voice_type=voice_type,
                    start_position=position,
                    key=self.main_key,
                    is_answer=False,
                )
            else:
                # 応答（属調）
                entry = FugueEntry(
                    subject=answer,
                    voice_type=voice_type,
                    start_position=position,
                    key=self.main_key.get_dominant_key(),
                    is_answer=True,
                )

            entries.append(entry)

            # コデッタの必要性チェック（Prout Ch.VI）
            if i < len(voice_order) - 1:
                current_end_subject = entry.subject
                next_is_answer = (i + 1) % 2 == 1
                next_subject = answer if next_is_answer else self.subject

                if Codetta.needs_codetta(current_end_subject, next_subject):
                    codetta = Codetta.generate_codetta(
                        current_end_subject, next_subject
                    )
                    self.codettas.append(codetta)
                    position += self.subject.get_length() + codetta.get_length()
                else:
                    position += self.subject.get_length()
            else:
                position += self.subject.get_length()

        self.entries.extend(entries)
        self.sections.append((FugueSection.EXPOSITION, 0, position))
        return entries

    def create_episode(self, start_position: int,
                       motif_length: int = 3,
                       sequence_steps: int = 3,
                       step_interval: int = -2) -> Episode:
        """エピソードを生成（Prout Ch.VII）

        Args:
            start_position: 開始位置
            motif_length: 動機の長さ
            sequence_steps: 反復回数
            step_interval: 移調幅（半音）
        """
        motif = Episode.extract_motif(self.subject, 0, motif_length)
        episode = Episode(
            motif_pitches=motif,
            sequence_steps=sequence_steps,
            step_interval=step_interval,
            source="主題",
        )
        self.episodes.append(episode)
        end_position = start_position + episode.get_total_length()
        self.sections.append(
            (FugueSection.EPISODE, start_position, end_position)
        )
        return episode

    def _get_voice_order(self) -> List[FugueVoiceType]:
        """声部の登場順序を決定（Prout Ch.I §5）

        Prout: バッハの慣例として中声部から開始することが多い。
        """
        if self.num_voices == 2:
            return [FugueVoiceType.SOPRANO, FugueVoiceType.ALTO]
        elif self.num_voices == 3:
            return [
                FugueVoiceType.ALTO,
                FugueVoiceType.SOPRANO,
                FugueVoiceType.BASS,
            ]
        else:
            return [
                FugueVoiceType.ALTO,
                FugueVoiceType.SOPRANO,
                FugueVoiceType.BASS,
                FugueVoiceType.TENOR,
            ]

    def add_middle_entry(self, start_position: int,
                         target_key: Key) -> FugueEntry:
        """中間提示を追加（Prout Ch.IX）

        Prout: 中間部では近親調（属調、下属調、平行調など）で
        主題を提示する。
        """
        transposition = target_key.tonic_pc - self.main_key.tonic_pc
        transposed = self.subject.transpose(transposition)
        transposed.key = target_key

        entry = FugueEntry(
            subject=transposed,
            voice_type=FugueVoiceType.SOPRANO,  # 簡易: 固定
            start_position=start_position,
            key=target_key,
            is_answer=False,
        )
        self.entries.append(entry)
        end = start_position + transposed.get_length()
        self.sections.append(
            (FugueSection.MIDDLE_ENTRY, start_position, end)
        )
        return entry

    def add_stretto(self, start_position: int, overlap_distance: int):
        """ストレット（Prout Ch.VIII）を追加

        Prout: 主題を完全に呈示し終わる前に次の声部が
        同じ主題で開始する密接模倣。
        """
        entries = []
        voice_types = self._get_voice_order()

        position = start_position
        for voice_type in voice_types:
            entry = FugueEntry(
                subject=self.subject,
                voice_type=voice_type,
                start_position=position,
                key=self.main_key,
                is_answer=False,
            )
            entries.append(entry)
            position += overlap_distance

        self.entries.extend(entries)
        end_position = position + self.subject.get_length()
        self.sections.append(
            (FugueSection.STRETTO, start_position, end_position)
        )

    def check_stretto_feasibility(
        self, overlap_distance: int
    ) -> Tuple[bool, List[str]]:
        """ストレットの実現可能性を検証（Prout Ch.VIII §2-3）

        Prout: ストレットが成立するためには、
        重なる区間で対位法上の禁則が生じないこと。
        """
        proh = CounterpointProhibitions()
        errors = []
        midi_vals = [p.midi for p in self.subject.pitches]
        length = len(midi_vals)

        if overlap_distance >= length:
            return True, []

        overlap_length = length - overlap_distance
        for i in range(overlap_length - 1):
            leader_idx = overlap_distance + i
            follower_idx = i

            if leader_idx + 1 >= length or follower_idx + 1 >= length:
                break

            v, msg = proh.check_parallel_perfect(
                midi_vals[leader_idx], midi_vals[leader_idx + 1],
                midi_vals[follower_idx], midi_vals[follower_idx + 1],
            )
            if not v:
                errors.append(f"位置{i}: {msg}")

        return len(errors) == 0, errors

    def get_modulation_plan(self) -> List[Tuple[str, Key]]:
        """調性計画を生成（Prout Ch.IX）

        Prout の標準的調性計画:
        - 提示部: 主調 → 属調
        - 中間部: 近親調（平行調、下属調、ii度調など）
        - 再帰: 主調

        長調のフーガ:
        1. C major（提示部）
        2. G major（応答）
        3. A minor（平行調での中間提示）
        4. F major（下属調）
        5. C major（再帰・ストレット）

        短調のフーガ:
        1. A minor（提示部）
        2. E major（応答）
        3. C major（平行長調）
        4. D minor（下属調）
        5. A minor（再帰・ストレット）
        """
        plan = []
        plan.append(("提示部: 主題", self.main_key))
        plan.append(("提示部: 応答", self.main_key.get_dominant_key()))

        # 中間部の調性
        rel = self.main_key.get_relative_key()
        plan.append(("中間提示1", rel))

        sub = self.main_key.get_subdominant_key()
        plan.append(("中間提示2", sub))

        # 再帰
        plan.append(("ストレット/再帰", self.main_key))

        return plan

    def get_section_info(self) -> str:
        """構造の概要を文字列で返す"""
        lines = []
        lines.append("フーガ構造分析")
        lines.append(f"声部数: {self.num_voices}")
        lines.append(f"主調: {self.main_key.tonic} {self.main_key.mode}")
        lines.append(f"主題の長さ: {self.subject.get_length()}音")
        lines.append("")
        lines.append("セクション:")
        for section, start, end in self.sections:
            lines.append(f"  {section.value}: 位置 {start}-{end}")
        lines.append("")
        lines.append(f"コデッタ: {len(self.codettas)}個")
        lines.append(f"エピソード: {len(self.episodes)}個")
        lines.append("")
        lines.append(f"主題の登場: {len(self.entries)}回")
        for i, entry in enumerate(self.entries):
            entry_type = "応答" if entry.is_answer else "主題"
            lines.append(
                f"  {i+1}. {entry.voice_type.value} - {entry_type} "
                f"({entry.key.tonic}調, 位置{entry.start_position})"
            )

        # 調性計画
        lines.append("")
        lines.append("調性計画 (Prout Ch.IX):")
        for label, key in self.get_modulation_plan():
            lines.append(f"  {label}: {key.tonic} {key.mode}")

        return "\n".join(lines)


# ============================================================
# 使用例
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("フーガ構造モジュール テスト (Prout 準拠)")
    print("=" * 60)

    # ハ長調の主題（WTC I Fugue 1 風）
    c_major = Key("C", "major")
    subject_pitches = [
        Pitch(60),  # C4 (主音)
        Pitch(62),  # D4
        Pitch(64),  # E4
        Pitch(65),  # F4
        Pitch(67),  # G4 (属音)
    ]
    subject = Subject(subject_pitches, c_major, "主題")

    print(f"\n主題: {[p.name for p in subject.pitches]}")
    print(f"音程列: {subject.analyze_intervals()}")
    print(f"開始音度数: {subject.get_opening_degree()}")
    print(f"調的応答が必要: {subject.needs_tonal_answer()}")

    head, tail = subject.get_head_tail_split()
    print(f"頭部: {[p.name for p in head]}")
    print(f"尾部: {[p.name for p in tail]}")

    # 実音応答 vs 調的応答
    real = subject.get_answer("real")
    tonal = subject.get_answer("tonal")
    print(f"\n実音応答: {[p.name for p in real.pitches]}")
    print(f"調的応答: {[p.name for p in tonal.pitches]}")

    print("\n--- 実音 vs 調的 応答比較 ---")
    for i, (r, t) in enumerate(zip(real.pitches, tonal.pitches)):
        diff = "同" if r.midi == t.midi else f"差{t.midi - r.midi:+d}"
        print(f"  {i}: 実音={r.name}, 調的={t.name} ({diff})")

    # コデッタ
    print("\n--- コデッタ ---")
    answer = subject.get_answer("tonal")
    needs = Codetta.needs_codetta(subject, answer)
    print(f"コデッタ必要: {needs}")
    if needs:
        codetta = Codetta.generate_codetta(subject, answer)
        print(f"コデッタ: {[p.name for p in codetta.pitches]}")

    # エピソード
    print("\n--- エピソード ---")
    motif = Episode.extract_motif(subject, 0, 3)
    ep = Episode(motif, sequence_steps=3, step_interval=-2)
    ep_pitches = ep.generate_pitches()
    print(f"動機: {[p.name for p in motif]}")
    print(f"エピソード: {[p.name for p in ep_pitches]}")

    # フーガ構造
    print("\n--- フーガ構造 ---")
    fugue = FugueStructure(num_voices=3, main_key=c_major, subject=subject)
    fugue.create_exposition(answer_type="auto")

    # ストレット実現可能性
    for dist in [2, 3, 4]:
        feasible, stretto_errs = fugue.check_stretto_feasibility(dist)
        status = "可能" if feasible else f"不可（{len(stretto_errs)}件）"
        print(f"ストレット（重なり{dist}拍）: {status}")

    # 調性計画
    print()
    print(fugue.get_section_info())
