"""
フーガ構造モジュール
Fugue Structure Module

フーガに特有の構造要素を定義・管理する。
調的応答（tonal answer）の正確な生成、
対主題の転回可能性検証を含む。

理論的根拠:
- André Gedalge: "Traité de la Fugue" (1901)
- Kent Kennan: "Counterpoint" (4th edition, 1999)
- Robert Gauldin: "A Practical Approach to 18th-Century Counterpoint" (2013)
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
    EPISODE = "episode"            # 間奏部（エピソード）
    MIDDLE_ENTRY = "middle_entry"  # 中間提示
    STRETTO = "stretto"            # ストレット
    CODA = "coda"                  # コーダ


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
        sub_pc = self.scale[3]  # 4度
        return Key(PC_TO_NOTE.get(sub_pc, 'F'), self.mode)

    def get_relative_key(self) -> 'Key':
        """平行調を取得"""
        if self.mode == "major":
            rel_pc = self.scale[5]  # 6度 = 平行短調の主音
            return Key(PC_TO_NOTE.get(rel_pc, 'A'), "minor")
        else:
            rel_pc = self.scale[2]  # 短3度上 = 平行長調の主音
            return Key(PC_TO_NOTE.get(rel_pc, 'C'), "major")


# ============================================================
# 主題（Subject）
# ============================================================

@dataclass
class Subject:
    """フーガの主題"""
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

    # ---- 応答生成 ----

    def get_answer(self, answer_type: str = "tonal") -> 'Subject':
        """応答（Answer）を生成

        Args:
            answer_type: "tonal"（調的応答）または "real"（実音応答）

        Returns:
            応答の Subject
        """
        if answer_type == "real":
            return self._real_answer()
        else:
            return self._tonal_answer()

    def _real_answer(self) -> 'Subject':
        """実音応答: 完全5度上に機械的に移調

        全ての音を一律に7半音上げる。
        主題が主音から属音へ向かう場合、応答は属音から
        さらに5度上（=上主音の領域）へ進んでしまう。
        """
        answer = self.transpose(7)
        answer.name = "応答（実音）"
        answer.key = self.key.get_dominant_key()
        return answer

    def _tonal_answer(self) -> 'Subject':
        """調的応答: 主音-属音軸の修正を伴う移調

        Gedalge/Gauldin:
        - 主題の各音の音階度数を判定
        - 属音（第5度）→ 主音（第1度）への変換（mutation）
          実音応答では +7 半音だが、調的応答では +5 半音
        - 主音（第1度）→ 属音（第5度）は実音と同じ +7 半音
        - その他の音 → 実音移調（+7 半音）
        - 音階外の音（半音階的経過音など） → 実音移調

        この変換により、主題が主調→属調へ向かうのに対し、
        応答は属調→主調へ戻る対称構造が形成される。
        """
        tonic_pc = self.key.tonic_pc
        dominant_pc = self.key.dominant_pc

        answer_pitches = []
        mutation_applied = False

        for p in self.pitches:
            pc = p.midi % 12

            if pc == dominant_pc and not mutation_applied:
                # 属音 → 主音への変換（mutation）
                # +5 半音（完全4度上）= 属調の主音ではなく元調の主音
                answer_pitches.append(Pitch(p.midi + 5))
                mutation_applied = True
            elif pc == tonic_pc and mutation_applied:
                # mutation後の主音: 通常の実音移調
                answer_pitches.append(Pitch(p.midi + 7))
            else:
                # その他: 実音移調
                answer_pitches.append(Pitch(p.midi + 7))

        dom_key = self.key.get_dominant_key()
        return Subject(answer_pitches, dom_key, "応答（調的）")

    # ---- 主題変形 ----

    def invert(self) -> 'Subject':
        """主題を反転（上下逆転）

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
        """主題を拡大（音価を整数倍にする）

        音高は変えず、将来のリズム情報で使用予定。
        現在は音符列のみ保持しているため、メタ情報として返す。
        """
        # 音価情報が導入されたら実装
        aug = Subject(list(self.pitches), self.key, f"{self.name}(拡大×{factor})")
        return aug

    def diminution(self, factor: int = 2) -> 'Subject':
        """主題を縮小（音価を整数分の1にする）"""
        dim = Subject(list(self.pitches), self.key, f"{self.name}(縮小÷{factor})")
        return dim

    # ---- 分析 ----

    def get_head_tail_split(self) -> Tuple[List[Pitch], List[Pitch]]:
        """主題を「頭部」と「尾部」に分割

        頭部: 主音-属音軸を確立する部分（最初の属音到達まで）
        尾部: それ以降

        調的応答の mutation 判定に使用。
        """
        dominant_pc = self.key.dominant_pc
        for i, p in enumerate(self.pitches):
            if p.midi % 12 == dominant_pc:
                return self.pitches[:i + 1], self.pitches[i + 1:]
        # 属音がない場合、全体が頭部
        return list(self.pitches), []

    def analyze_intervals(self) -> List[int]:
        """音程列を返す（半音数、符号付き）"""
        intervals = []
        for i in range(len(self.pitches) - 1):
            intervals.append(self.pitches[i + 1].midi - self.pitches[i].midi)
        return intervals


# ============================================================
# 対主題（Counter-subject）
# ============================================================

@dataclass
class Countersubject:
    """対主題（Counter-subject）

    主題と同時に鳴り、主題の上下が入れ替わっても
    対位法的に成立すること（転回可能性）が望ましい。
    """
    pitches: List[Pitch]
    name: str = "対主題"

    def check_invertibility(
        self, subject_pitches: List[Pitch],
    ) -> Tuple[bool, List[str]]:
        """主題との転回可能性を検証

        InvertibleCounterpoint を使用して、
        主題と対主題の上下を入れ替えても禁則が生じないか確認する。
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
        """転回時に問題となる5度の位置を特定"""
        inv = InvertibleCounterpoint()
        upper = [p.midi for p in subject_pitches]
        lower = [p.midi for p in self.pitches]
        return inv.find_problematic_fifth(upper, lower)


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
# フーガ構造
# ============================================================

class FugueStructure:
    """フーガ全体の構造を管理"""

    def __init__(self, num_voices: int, main_key: Key, subject: Subject):
        """
        Args:
            num_voices: 声部数（通常3-4）
            main_key: 主調
            subject: 主題
        """
        self.num_voices = num_voices
        self.main_key = main_key
        self.subject = subject
        self.entries: List[FugueEntry] = []
        self.sections: List[Tuple[FugueSection, int, int]] = []

    def create_exposition(self) -> List[FugueEntry]:
        """提示部を生成

        標準的なフーガの提示部:
        1. 主題が主調で提示される（第1声部）
        2. 応答が属調で提示される（第2声部）
        3. 主題と応答が交互に、全声部が登場するまで続く
        """
        entries = []
        voice_order = self._get_voice_order()

        position = 0
        for i, voice_type in enumerate(voice_order):
            if i % 2 == 0:
                entry = FugueEntry(
                    subject=self.subject,
                    voice_type=voice_type,
                    start_position=position,
                    key=self.main_key,
                    is_answer=False,
                )
            else:
                answer = self.subject.get_answer("tonal")
                entry = FugueEntry(
                    subject=answer,
                    voice_type=voice_type,
                    start_position=position,
                    key=self.main_key.get_dominant_key(),
                    is_answer=True,
                )

            entries.append(entry)
            position += self.subject.get_length()

        self.entries.extend(entries)
        self.sections.append((FugueSection.EXPOSITION, 0, position))
        return entries

    def _get_voice_order(self) -> List[FugueVoiceType]:
        """声部の登場順序を決定

        バッハの慣例: 中声部→上声部→下声部（3声）
                      中声部→上声部→下声部→残り（4声）
        """
        if self.num_voices == 2:
            return [FugueVoiceType.SOPRANO, FugueVoiceType.ALTO]
        elif self.num_voices == 3:
            return [
                FugueVoiceType.ALTO,
                FugueVoiceType.SOPRANO,
                FugueVoiceType.BASS,
            ]
        else:  # 4声
            return [
                FugueVoiceType.ALTO,
                FugueVoiceType.SOPRANO,
                FugueVoiceType.BASS,
                FugueVoiceType.TENOR,
            ]

    def add_stretto(self, start_position: int, overlap_distance: int):
        """ストレット（主題の密接模倣）を追加

        Args:
            start_position: 開始位置
            overlap_distance: 主題間の重なり距離（拍単位）
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
        self.sections.append((FugueSection.STRETTO, start_position, end_position))

    def check_stretto_feasibility(self, overlap_distance: int) -> Tuple[bool, List[str]]:
        """ストレットの実現可能性を検証

        主題を overlap_distance 拍ずらして重ねた時に、
        対位法上の禁則が生じないか確認する。
        """
        proh = CounterpointProhibitions()
        errors = []
        midi_vals = [p.midi for p in self.subject.pitches]
        length = len(midi_vals)

        if overlap_distance >= length:
            return True, []  # 重ならない

        # 重なる区間で禁則チェック
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

    def get_section_info(self) -> str:
        """構造の概要を文字列で返す"""
        lines = []
        lines.append(f"フーガ構造分析")
        lines.append(f"声部数: {self.num_voices}")
        lines.append(f"主調: {self.main_key.tonic} {self.main_key.mode}")
        lines.append(f"主題の長さ: {self.subject.get_length()}音")
        lines.append(f"")
        lines.append(f"セクション:")
        for section, start, end in self.sections:
            lines.append(f"  {section.value}: 位置 {start}-{end}")
        lines.append(f"")
        lines.append(f"主題の登場: {len(self.entries)}回")
        for i, entry in enumerate(self.entries):
            entry_type = "応答" if entry.is_answer else "主題"
            lines.append(
                f"  {i+1}. {entry.voice_type.value} - {entry_type} "
                f"({entry.key.tonic}調, 位置{entry.start_position})"
            )
        return "\n".join(lines)


# ============================================================
# 使用例
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("フーガ構造モジュール テスト")
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

    head, tail = subject.get_head_tail_split()
    print(f"頭部: {[p.name for p in head]}")
    print(f"尾部: {[p.name for p in tail]}")

    # 実音応答
    real = subject.get_answer("real")
    print(f"\n実音応答: {[p.name for p in real.pitches]}")

    # 調的応答
    tonal = subject.get_answer("tonal")
    print(f"調的応答: {[p.name for p in tonal.pitches]}")

    # 比較
    print("\n--- 実音 vs 調的 応答比較 ---")
    for i, (r, t) in enumerate(zip(real.pitches, tonal.pitches)):
        diff = "同" if r.midi == t.midi else f"差{t.midi - r.midi:+d}"
        print(f"  {i}: 実音={r.name}, 調的={t.name} ({diff})")

    # 反転・逆行
    inverted = subject.invert()
    print(f"\n反転: {[p.name for p in inverted.pitches]}")

    retro = subject.retrograde()
    print(f"逆行: {[p.name for p in retro.pitches]}")

    # 対主題の転回可能性
    print("\n--- 対主題の転回可能性 ---")
    cs_pitches = [
        Pitch(64),  # E4
        Pitch(62),  # D4
        Pitch(60),  # C4
        Pitch(62),  # D4
        Pitch(64),  # E4
    ]
    cs = Countersubject(cs_pitches, "対主題")
    valid, errs = cs.check_invertibility(subject.pitches)
    print(f"転回可能: {valid}")
    if errs:
        for e in errs:
            print(f"  {e}")

    # 5度の問題箇所
    probs = cs.find_fifths_to_avoid(subject.pitches)
    if probs:
        print(f"注意すべき5度: {len(probs)}箇所")
        for pos, reason in probs:
            print(f"  位置{pos}: {reason}")

    # フーガ構造
    print("\n--- フーガ構造 ---")
    fugue = FugueStructure(num_voices=3, main_key=c_major, subject=subject)
    fugue.create_exposition()

    # ストレット実現可能性
    for dist in [2, 3, 4]:
        feasible, stretto_errs = fugue.check_stretto_feasibility(dist)
        status = "可能" if feasible else f"不可（{len(stretto_errs)}件）"
        print(f"ストレット（重なり{dist}拍）: {status}")

    fugue.add_stretto(start_position=20, overlap_distance=3)
    print()
    print(fugue.get_section_info())
