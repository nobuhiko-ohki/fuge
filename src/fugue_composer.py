"""
fugue_composer.py — フーガ作曲エンジン v2

設計原則:
  1. 単方向パイプライン: 上流→下流のみ。下流は上流を一切変更しない。
  2. HarmonicPlan は構築後に不変（frozen tuple）。
  3. 全拍頭は和音構成音のみ。非和声音は Phase 1 では扱わない。
  4. 修復なし: 生成失敗 → 棄却・再試行。
  5. 品質チェッカーは読み取り専用。推論なし、直接参照のみ。

パイプライン:
  Layer 1: HarmonicPlan  (chord_plan + key_map, immutable after construction)
  Layer 2: VoicePlan     (beat-level pitches, ALL chord tones, immutable)
  Layer 3: MidiOutput    (VoicePlan → MIDI, quarter notes only)
  Layer 4: Validation    (HarmonicPlan + VoicePlan → ValidationReport)
"""

from __future__ import annotations
import itertools
import random
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from counterpoint_engine import CounterpointProhibitions
from fugue_structure import (
    FugueEntry, FugueStructure, FugueVoiceType, Key, Subject,
)
from fugue_realization import ChordLabel, VOICE_RANGES


# ============================================================
# Layer 1: HarmonicPlan（不変）
# ============================================================

@dataclass(frozen=True)
class HarmonicPlan:
    """不変の和声計画。一度構築したら変更不可。

    chord_plan: 各拍の和音ラベル (tuple = immutable)
    key_map:    各拍の調 (Dict は通常変更されないが呼び出し元が保証する)
    """
    chord_plan: Tuple[ChordLabel, ...]
    key_map: Tuple[Key, ...]  # key_map[beat] = Key; chord_plan と同長

    def __len__(self) -> int:
        return len(self.chord_plan)

    def chord(self, beat: int) -> ChordLabel:
        return self.chord_plan[beat]

    def key(self, beat: int) -> Key:
        return self.key_map[beat]

    @classmethod
    def from_lists(
        cls,
        chords: List[ChordLabel],
        keys: Optional[List[Key]] = None,
        default_key: Optional[Key] = None,
    ) -> 'HarmonicPlan':
        """リストから HarmonicPlan を構築。"""
        n = len(chords)
        if keys is None:
            if default_key is None:
                raise ValueError("keys か default_key のいずれかが必要")
            keys = [default_key] * n
        if len(keys) != n:
            raise ValueError(f"chords ({n}) と keys ({len(keys)}) の長さが不一致")
        return cls(
            chord_plan=tuple(chords),
            key_map=tuple(keys),
        )


# ============================================================
# Layer 2: VoicePlan（不変）
# ============================================================

@dataclass(frozen=True)
class VoicePlan:
    """不変の声部計画。全拍が和音構成音のみ。

    pitches[voice][beat] = MIDI ピッチ (int) or None（その拍で未発音）
    """
    pitches: Dict[FugueVoiceType, Tuple[Optional[int], ...]]
    num_beats: int

    def pitch(self, voice: FugueVoiceType, beat: int) -> Optional[int]:
        return self.pitches.get(voice, (None,) * self.num_beats)[beat]

    @classmethod
    def from_dicts(
        cls,
        pitches: Dict[FugueVoiceType, List[Optional[int]]],
        num_beats: int,
    ) -> 'VoicePlan':
        return cls(
            pitches={v: tuple(ps) for v, ps in pitches.items()},
            num_beats=num_beats,
        )


# ============================================================
# Layer 2 エンジン: ChordRealizationEngine（バックトラッキング）
# ============================================================

# 声部の上下順
_VOICE_ORDER: Dict[FugueVoiceType, int] = {
    FugueVoiceType.SOPRANO: 0,
    FugueVoiceType.ALTO:    1,
    FugueVoiceType.TENOR:   2,
    FugueVoiceType.BASS:    3,
}

# 転回対位法（8度）音程クラス定数
# 音程クラス = abs(cs_pitch - subject_pitch) % 12
_ICP_FORBIDDEN = frozenset({1, 2, 6, 10, 11})  # 2度・増4度・7度（転回後も不協和）
_ICP_CAUTIOUS  = frozenset({0, 5, 7})           # 同度/8度・4度(→5度転回)・5度(→4度転回)


def _backtrack(
    harmonic_plan: HarmonicPlan,
    pinned: Dict[FugueVoiceType, Dict[int, int]],
    all_voices: List[FugueVoiceType],
    voice_ranges: Dict[FugueVoiceType, Tuple[int, int]],
    prev_pitches: Optional[Dict[FugueVoiceType, Optional[int]]] = None,
    max_backtrack: int = 32,
    voice_start_beats: Optional[Dict[FugueVoiceType, int]] = None,
) -> Optional[Dict[FugueVoiceType, List[Optional[int]]]]:
    """全声部をバックトラッキングで生成（拍単位ピン止め方式）。

    設計原則:
    - pinned[voice][beat] = 必須ピッチ（主題音符など）。レンジ外でも可。
    - それ以外の拍は和音構成音からバックトラッキングで最適選択。
    - voice_start_beats[voice] = その声部が入声する拍番号。
      指定がある場合、入声前の拍は休止（None）のみが候補となる。

    Args:
        harmonic_plan: 不変の和声計画
        pinned: {voice: {beat: required_pitch}} 拍単位の固定ピッチ
        all_voices: 生成する全声部リスト（上声部→下声部の順）
        voice_ranges: {voice: (lo, hi)} 自由拍の音域制約
        prev_pitches: 直前拍の全声部ピッチ（区間連続性用）
        max_backtrack: 最大バックトラック深度
        voice_start_beats: {voice: start_beat} 各声部の入声拍。
                           None の場合は全声部が拍0から発音する。

    Returns:
        {voice: [beat_pitch_or_None, ...]} or None（解なし）
    """
    if not all_voices:
        return {}

    num_beats = len(harmonic_plan)
    proh = CounterpointProhibitions()

    def is_upper(va: FugueVoiceType, vb: FugueVoiceType) -> bool:
        return _VOICE_ORDER[va] < _VOICE_ORDER[vb]

    def is_outer(va: FugueVoiceType, vb: FugueVoiceType) -> bool:
        return {va, vb} == {FugueVoiceType.SOPRANO, FugueVoiceType.BASS}

    # --- 各拍×各声部の候補リスト ---
    # 未入声拍: [None] のみ（休止）
    # ピン止め拍: [required_pitch] のみ
    # 自由拍: レンジ内の和音構成音
    candidates_per_beat: List[List[List[Optional[int]]]] = []
    for beat in range(num_beats):
        chord_tones = harmonic_plan.chord(beat).tones
        beat_cands: List[List[Optional[int]]] = []
        for vt in all_voices:
            # 未入声: 休止（None）のみ
            if voice_start_beats and beat < voice_start_beats.get(vt, 0):
                beat_cands.append([None])
            elif vt in pinned and beat in pinned[vt]:
                beat_cands.append([pinned[vt][beat]])
            else:
                lo, hi = voice_ranges.get(vt, (36, 84))
                cands: List[Optional[int]] = [
                    m for m in range(lo, hi + 1) if m % 12 in chord_tones
                ]
                beat_cands.append(cands)
        candidates_per_beat.append(beat_cands)

    def _prev_combo_to_dict(
        prev_combo: Optional[Tuple[Optional[int], ...]],
    ) -> Dict[FugueVoiceType, int]:
        """直前 combo タプル → 声部ピッチ辞書。beat=0 では prev_pitches を参照。
        None（休止）の声部は辞書に含まない。
        """
        prev: Dict[FugueVoiceType, int] = {}
        if prev_combo is not None:
            for i, vt in enumerate(all_voices):
                if prev_combo[i] is not None:
                    prev[vt] = prev_combo[i]  # type: ignore[assignment]
        elif prev_pitches is not None:
            for vt, p in prev_pitches.items():
                if p is not None:
                    prev[vt] = p
        return prev

    def check(
        beat: int,
        combo: Tuple[Optional[int], ...],
        prev_combo: Optional[Tuple[Optional[int], ...]],
    ) -> bool:
        """全声部ペアの禁則を検証。None（休止）の声部は無視する。"""
        # 発音中の声部のみ（None = 休止）
        curr: Dict[FugueVoiceType, int] = {
            vt: combo[i]  # type: ignore[misc]
            for i, vt in enumerate(all_voices)
            if combo[i] is not None
        }
        prev = _prev_combo_to_dict(prev_combo)

        # (1) ユニゾン禁止
        vals = list(curr.values())
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                if vals[i] == vals[j]:
                    return False

        # (2) 声部交差禁止
        sorted_vt = sorted(curr.keys(), key=lambda v: _VOICE_ORDER[v])
        for i in range(len(sorted_vt) - 1):
            if curr[sorted_vt[i]] < curr[sorted_vt[i + 1]]:
                return False

        # (3) 根音・第3音カバレッジ（3声以上）
        if len(curr) >= 3:
            chord = harmonic_plan.chord(beat)
            curr_pcs = {p % 12 for p in curr.values()}
            if chord.root_pc not in curr_pcs:
                return False
            if chord.third_pc not in curr_pcs:
                return False

        # (3b) C15: 導音重複禁止
        # 2声以上が導音を持つとき、自由声部が含まれていれば禁止
        # （ピン止め同士の重複は主題の都合なので容認）
        key_b = harmonic_plan.key(beat)
        lt_pc = key_b.leading_tone_pc
        lt_voices = [vt for vt in curr if curr[vt] % 12 == lt_pc]
        if len(lt_voices) >= 2:
            free_lt = [vt for vt in lt_voices
                       if not (vt in pinned and beat in pinned[vt])]
            if free_lt:
                return False

        # (4) 前拍なければ終了
        if not prev:
            return True

        # (5) 全声部ペアの平行・超越チェック
        vlist = list(curr.keys())
        for i in range(len(vlist)):
            vi = vlist[i]
            if vi not in prev:
                continue
            for j in range(i + 1, len(vlist)):
                vj = vlist[j]
                if vj not in prev:
                    continue
                up_v, lo_v = (vi, vj) if is_upper(vi, vj) else (vj, vi)
                up_p, up_c = prev[up_v], curr[up_v]
                lo_p, lo_c = prev[lo_v], curr[lo_v]
                ok, _ = proh.check_parallel_perfect(up_p, up_c, lo_p, lo_c)
                if not ok:
                    return False
                ok, _ = proh.check_voice_overlap(up_p, up_c, lo_p, lo_c)
                if not ok:
                    return False
                if is_outer(vi, vj):
                    ok, _ = proh.check_hidden_perfect(up_p, up_c, lo_p, lo_c, True)
                    if not ok:
                        return False
                ok, _ = proh.check_direct_unison(
                    prev[vi], curr[vi], prev[vj], curr[vj])
                if not ok:
                    return False

        # (6) 旋律制約（自由拍のみ。ピン止め拍への跳躍は主題の自由）
        for i, vt in enumerate(all_voices):
            if combo[i] is None:
                continue  # 休止声部は旋律制約なし
            if vt not in prev:
                continue
            if vt in pinned and beat in pinned[vt]:
                continue  # ピン止め拍は制約なし
            ok, _ = proh.check_melodic_augmented(prev[vt], combo[i])
            if not ok:
                return False
            ok, _ = proh.check_melodic_seventh(prev[vt], combo[i])
            if not ok:
                return False
            # C17+: 増2度禁止（短調 b6→#7 ペア、key-aware）
            if abs(combo[i] - prev[vt]) == 3:
                key_ctx = harmonic_plan.key(beat)
                sc = key_ctx.scale
                if len(sc) == 7:
                    aug2_pair = {sc[5] % 12, sc[6] % 12}
                    if {prev[vt] % 12, combo[i] % 12} == aug2_pair:
                        return False

        return True

    def score(
        beat: int,
        combo: Tuple[Optional[int], ...],
        prev_combo: Optional[Tuple[Optional[int], ...]],
    ) -> float:
        """低い方が良い。自由拍の順次進行を好む。対斜をペナルティ。"""
        cost = 0.0
        prev = _prev_combo_to_dict(prev_combo)

        for i, vt in enumerate(all_voices):
            if combo[i] is None:
                continue  # 休止声部はスコア評価しない
            # ピン止め拍は評価しない
            if vt in pinned and beat in pinned[vt]:
                continue
            if vt not in prev:
                continue
            interval = abs(combo[i] - prev[vt])
            if interval == 0:
                cost += 4.0      # 同音保持: ペナルティ
            elif interval <= 2:
                cost -= 1.0      # 順次: ボーナス
            elif interval <= 4:
                cost += 0.5      # 3度: 許容
            elif interval <= 7:
                cost += 2.0      # 4〜5度
            else:
                cost += 5.0      # 6度以上: 大ペナルティ

        # 対斜ペナルティ（ソフト）
        if prev and beat > 0:
            bk_prev = harmonic_plan.key(beat - 1)
            bk_curr = harmonic_plan.key(beat)
            cr_pairs: Set[Tuple[int, int]] = set()
            for bk in (bk_prev, bk_curr):
                t = bk.tonic_pc
                for a, b2 in (((t+10)%12, (t+11)%12), ((t+8)%12, (t+9)%12)):
                    cr_pairs.add((min(a, b2), max(a, b2)))
            prev_pcs = {prev[vt] % 12 for vt in prev}
            curr_pcs = {combo[i] % 12 for i in range(len(all_voices)) if combo[i] is not None}
            for lo_pc, hi_pc in cr_pairs:
                if ((lo_pc in prev_pcs and hi_pc in curr_pcs) or
                        (hi_pc in prev_pcs and lo_pc in curr_pcs)):
                    cost += 50.0

        # C14: 導音未解決ペナルティ（ソフト）
        # V→I 等（次の和音に導音が含まれない）場合のみペナルティ
        if prev and beat > 0:
            key_prev = harmonic_plan.key(beat - 1)
            lt_pc = key_prev.leading_tone_pc
            tonic_pc = key_prev.tonic_pc
            curr_chord_tones = harmonic_plan.chord(beat).tones
            if lt_pc not in curr_chord_tones:
                for i, vt in enumerate(all_voices):
                    if combo[i] is None:
                        continue  # 休止声部は評価しない
                    if vt in pinned and beat in pinned[vt]:
                        continue  # ピン止め拍は主題の論理を尊重
                    if vt not in prev:
                        continue
                    if prev[vt] % 12 == lt_pc:
                        curr_pc = combo[i] % 12
                        if curr_pc != tonic_pc:
                            cost += 40.0  # C14: 導音未解決
                        elif combo[i] <= prev[vt]:
                            cost += 5.0   # 上行解決でない（下降オクターブ）

        return cost

    # --- バックトラッキング探索 ---
    solution: List[Optional[Tuple[Tuple[Optional[int], ...], int]]] = [None] * num_beats

    beat = 0
    while beat < num_beats:
        cands_lists = candidates_per_beat[beat]
        prev_combo: Optional[Tuple[int, ...]] = None
        if beat > 0 and solution[beat - 1] is not None:
            prev_combo = solution[beat - 1][0]

        all_combos = list(itertools.product(*cands_lists))
        valid_scored: List[Tuple[float, int, Tuple[int, ...]]] = []
        for combo in all_combos:
            if check(beat, combo, prev_combo):
                s = score(beat, combo, prev_combo)
                valid_scored.append((s, id(combo), combo))
        valid_scored.sort()

        start_idx = 0
        if solution[beat] is not None:
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
            solution[beat] = None
            beat -= 1
            if beat < 0 or (num_beats - 1 - beat) > max_backtrack:
                return None  # 解なし

    # 結果を辞書へ（None = 休止を含む）
    result: Dict[FugueVoiceType, List[Optional[int]]] = {vt: [] for vt in all_voices}
    for b in range(num_beats):
        combo = solution[b][0]
        for i, vt in enumerate(all_voices):
            result[vt].append(combo[i])  # None の場合は休止
    return result


# ============================================================
# Layer 4: Validation（読み取り専用）
# ============================================================

@dataclass
class ValidationError:
    beat: int
    measure: int          # 1-based
    beat_in_measure: int  # 1-based
    category: str
    description: str
    severity: str = "error"  # "error" | "warning"


@dataclass
class ValidationReport:
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    def add(self, e: ValidationError):
        if e.severity == "error":
            self.errors.append(e)
        else:
            self.warnings.append(e)


_NOTE_NAMES = {
    0: 'C', 1: 'C#', 2: 'D', 3: 'D#', 4: 'E', 5: 'F',
    6: 'F#', 7: 'G', 8: 'G#', 9: 'A', 10: 'A#', 11: 'B',
}


def validate(
    harmonic_plan: HarmonicPlan,
    voice_plan: VoicePlan,
    beats_per_measure: int = 4,
) -> ValidationReport:
    """HarmonicPlan と VoicePlan を直接参照して検証。

    beat_harmonic の推論は不要。
    全ピッチが和音構成音であることは生成時に保証済みなので、
    ここでは対位法規則のみを検証する。
    ただし念のため外音チェックも行う（回帰防止）。
    """
    report = ValidationReport()
    proh = CounterpointProhibitions()
    voices = [vt for vt in FugueVoiceType
              if vt in voice_plan.pitches]
    n = voice_plan.num_beats

    def _loc(beat: int) -> Tuple[int, int]:
        m = beat // beats_per_measure + 1
        b = beat % beats_per_measure + 1
        return m, b

    voice_order = _VOICE_ORDER

    def is_upper(va: FugueVoiceType, vb: FugueVoiceType) -> bool:
        return voice_order[va] < voice_order[vb]

    def is_outer(va: FugueVoiceType, vb: FugueVoiceType) -> bool:
        return {va, vb} == {FugueVoiceType.SOPRANO, FugueVoiceType.BASS}

    # --- C15: 導音重複チェック ---
    for beat in range(n):
        key_b = harmonic_plan.key(beat)
        lt_pc = key_b.leading_tone_pc
        active_b = {vt: voice_plan.pitch(vt, beat)
                    for vt in voices
                    if voice_plan.pitch(vt, beat) is not None}
        lt_voices = [vt for vt, p in active_b.items() if p % 12 == lt_pc]
        if len(lt_voices) >= 2:
            m, b = _loc(beat)
            report.add(ValidationError(
                beat=beat, measure=m, beat_in_measure=b,
                category="leading_tone_doubled",
                description=(
                    f"導音重複: {_NOTE_NAMES.get(lt_pc, '?')} が"
                    f" {', '.join(vt.value for vt in lt_voices)} に重複"
                ),
                severity="warning",
            ))

    # --- 外音チェック（回帰防止） ---
    for beat in range(n):
        chord = harmonic_plan.chord(beat)
        active = {vt: voice_plan.pitch(vt, beat)
                  for vt in voices
                  if voice_plan.pitch(vt, beat) is not None}
        if len(active) < 2:
            continue
        foreign = {_NOTE_NAMES.get(p % 12, str(p % 12))
                   for p in active.values()
                   if p % 12 not in chord.tones}
        if foreign:
            m, b = _loc(beat)
            report.add(ValidationError(
                beat=beat, measure=m, beat_in_measure=b,
                category="foreign_tone",
                description=(
                    f"外音 {{{','.join(sorted(foreign))}}} "
                    f"in {_NOTE_NAMES.get(chord.root_pc, '?')}{chord.quality}"
                    f" {{{','.join(_NOTE_NAMES.get(pc,'?') for pc in sorted(chord.tones))}}}"
                ),
                severity="error",
            ))

        # --- 根音欠如チェック ---
        pcs = {p % 12 for p in active.values()}
        if len(active) >= 3 and chord.root_pc not in pcs:
            m, b = _loc(beat)
            report.add(ValidationError(
                beat=beat, measure=m, beat_in_measure=b,
                category="missing_root",
                description=(
                    f"根音欠如: {_NOTE_NAMES.get(chord.root_pc, '?')} が不在 "
                    f"(計画={_NOTE_NAMES.get(chord.root_pc, '?')}{chord.quality})"
                ),
                severity="error",
            ))

        # --- 第3音欠如チェック ---
        if len(active) >= 3 and chord.third_pc not in pcs:
            m, b = _loc(beat)
            sev = "warning" if len(active) < 3 else "error"
            report.add(ValidationError(
                beat=beat, measure=m, beat_in_measure=b,
                category="missing_third",
                description=(
                    f"第3音欠如: {_NOTE_NAMES.get(chord.third_pc, '?')} が不在 "
                    f"(計画={_NOTE_NAMES.get(chord.root_pc, '?')}{chord.quality})"
                ),
                severity=sev,
            ))

    # --- 声部進行チェック ---
    for beat in range(1, n):
        curr = {vt: voice_plan.pitch(vt, beat)
                for vt in voices
                if voice_plan.pitch(vt, beat) is not None}
        prev = {vt: voice_plan.pitch(vt, beat - 1)
                for vt in voices
                if voice_plan.pitch(vt, beat - 1) is not None}
        if not curr or not prev:
            continue

        vlist = list(curr.keys())
        m, b = _loc(beat)

        for i in range(len(vlist)):
            vi = vlist[i]
            if vi not in prev:
                continue
            for j in range(i + 1, len(vlist)):
                vj = vlist[j]
                if vj not in prev:
                    continue
                up_v, lo_v = (vi, vj) if is_upper(vi, vj) else (vj, vi)
                up_p, up_c = prev[up_v], curr[up_v]
                lo_p, lo_c = prev[lo_v], curr[lo_v]

                ok, msg = proh.check_parallel_perfect(up_p, up_c, lo_p, lo_c)
                if not ok:
                    report.add(ValidationError(
                        beat=beat, measure=m, beat_in_measure=b,
                        category="parallel_perfect",
                        description=f"{msg}: {up_v.value}+{lo_v.value}",
                        severity="error",
                    ))
                ok, msg = proh.check_voice_overlap(up_p, up_c, lo_p, lo_c)
                if not ok:
                    report.add(ValidationError(
                        beat=beat, measure=m, beat_in_measure=b,
                        category="voice_overlap",
                        description=f"{msg}: {up_v.value}+{lo_v.value}",
                        severity="error",
                    ))
                if is_outer(vi, vj):
                    ok, msg = proh.check_hidden_perfect(
                        up_p, up_c, lo_p, lo_c, True)
                    if not ok:
                        report.add(ValidationError(
                            beat=beat, measure=m, beat_in_measure=b,
                            category="hidden_perfect",
                            description=f"{msg}: {up_v.value}+{lo_v.value}",
                            severity="error",
                        ))

        # ユニゾン
        vals = list(curr.values())
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                if vals[i] == vals[j]:
                    vi = vlist[i]
                    vj = vlist[j]
                    report.add(ValidationError(
                        beat=beat, measure=m, beat_in_measure=b,
                        category="unison",
                        description=f"ユニゾン: {vi.value}+{vj.value} = {vals[i]}",
                        severity="error",
                    ))

        # 声部交差
        sorted_vt = sorted(curr.keys(), key=lambda v: _VOICE_ORDER[v])
        for i in range(len(sorted_vt) - 1):
            va = sorted_vt[i]
            vb = sorted_vt[i + 1]
            if va in curr and vb in curr:
                if curr[va] < curr[vb]:
                    report.add(ValidationError(
                        beat=beat, measure=m, beat_in_measure=b,
                        category="voice_crossing",
                        description=f"声部交差: {va.value}({curr[va]}) < {vb.value}({curr[vb]})",
                        severity="error",
                    ))

        # 旋律制約
        key_curr = harmonic_plan.key(beat)
        key_prev_beat = harmonic_plan.key(beat - 1)
        for vt in vlist:
            if vt not in prev:
                continue
            ok, msg = proh.check_melodic_augmented(prev[vt], curr[vt])
            if not ok:
                report.add(ValidationError(
                    beat=beat, measure=m, beat_in_measure=b,
                    category="melodic_augmented",
                    description=f"{msg}: {vt.value}",
                    severity="error",
                ))
            ok, msg = proh.check_melodic_seventh(prev[vt], curr[vt])
            if not ok:
                report.add(ValidationError(
                    beat=beat, measure=m, beat_in_measure=b,
                    category="melodic_seventh",
                    description=f"{msg}: {vt.value}",
                    severity="error",
                ))
            # C17+: 増2度チェック（b6→#7 ペア）
            if abs(curr[vt] - prev[vt]) == 3:
                sc = key_curr.scale
                if len(sc) == 7:
                    aug2_pair = {sc[5] % 12, sc[6] % 12}
                    if {prev[vt] % 12, curr[vt] % 12} == aug2_pair:
                        report.add(ValidationError(
                            beat=beat, measure=m, beat_in_measure=b,
                            category="augmented_second",
                            description=(
                                f"増2度旋律: {_NOTE_NAMES.get(prev[vt]%12,'?')}"
                                f"→{_NOTE_NAMES.get(curr[vt]%12,'?')}"
                                f": {vt.value}"
                            ),
                            severity="warning",
                        ))
            # C14: 導音未解決チェック
            # 導音が次の和音に含まれない（V→I 等）場合のみ警告
            # V→V のように導音を含む和音が続く場合は解決猶予あり
            lt_pc = key_prev_beat.leading_tone_pc
            tonic_pc = key_prev_beat.tonic_pc
            if prev[vt] % 12 == lt_pc and curr[vt] % 12 != tonic_pc:
                curr_chord_tones = harmonic_plan.chord(beat).tones
                if lt_pc not in curr_chord_tones:
                    report.add(ValidationError(
                        beat=beat, measure=m, beat_in_measure=b,
                        category="leading_tone_unresolved",
                        description=(
                            f"導音未解決: {_NOTE_NAMES.get(lt_pc,'?')}"
                            f"→{_NOTE_NAMES.get(curr[vt]%12,'?')}"
                            f" (期待={_NOTE_NAMES.get(tonic_pc,'?')})"
                            f": {vt.value}"
                        ),
                        severity="warning",
                    ))

    return report


# ============================================================
# Layer 3: MIDI 出力（四分音符グリッド）
# ============================================================

TICKS_PER_BEAT = 480  # 四分音符 = 480 ticks


def build_midi(
    voice_plan: VoicePlan,
) -> Dict[FugueVoiceType, List[Tuple[int, int, int]]]:
    """VoicePlan → {voice: [(start_tick, midi, duration_tick), ...]}

    Phase 1: 全音符を四分音符で出力（装飾なし）。
    連続する同ピッチは1音符にまとめる（連符扱い）。
    """
    result: Dict[FugueVoiceType, List[Tuple[int, int, int]]] = {}
    for vt, pitch_tuple in voice_plan.pitches.items():
        notes: List[Tuple[int, int, int]] = []
        i = 0
        while i < len(pitch_tuple):
            p = pitch_tuple[i]
            if p is None:
                i += 1
                continue
            j = i + 1
            while j < len(pitch_tuple) and pitch_tuple[j] == p:
                j += 1
            start_tick = i * TICKS_PER_BEAT
            dur_tick = (j - i) * TICKS_PER_BEAT
            notes.append((start_tick, p, dur_tick))
            i = j
        result[vt] = notes
    return result


def build_midi_with_passing_tones(
    voice_plan: VoicePlan,
    harmonic_plan: HarmonicPlan,
    voices_to_elaborate: Optional[List[FugueVoiceType]] = None,
) -> Dict[FugueVoiceType, List[Tuple[int, int, int]]]:
    """VoicePlan → MIDI データ（経過音付き）。

    各声部の拍ごとピッチを検査し、連続する拍頭音が3度以上離れている場合に
    スケール経過音（八分音符）を拍の後半に挿入する。

    規則:
      - 同音保持 (interval=0):  連続する同音をまとめて長い音符に
      - 2度以内 (interval 1-2): 四分音符のまま（既に順次進行）
      - 3度以上 (interval ≥ 3): 八分音符(拍頭音) + 八分音符(経過音)
                                 経過音はその調のスケール上で
                                 拍頭音と次拍頭音の間にある最初の音

    Args:
        voice_plan:          拍単位の声部計画
        harmonic_plan:       和声計画（スケール情報に使用）
        voices_to_elaborate: 経過音を付加する声部リスト（None = 全声部）

    Returns:
        {voice: [(start_tick, midi_pitch, duration_ticks), ...]}
    """
    half_tick = TICKS_PER_BEAT // 2   # 八分音符 = 240 ticks

    result: Dict[FugueVoiceType, List[Tuple[int, int, int]]] = {}

    for vt, pitch_tuple in voice_plan.pitches.items():
        notes: List[Tuple[int, int, int]] = []
        n = len(pitch_tuple)
        elaborate = (voices_to_elaborate is None or vt in voices_to_elaborate)

        i = 0
        while i < n:
            p = pitch_tuple[i]
            if p is None:
                i += 1
                continue

            start_tick = i * TICKS_PER_BEAT
            p_next = pitch_tuple[i + 1] if i + 1 < n else None

            # ── 同音保持: まとめて長い音符 ──────────────────────────────
            if p_next is None or p_next == p:
                k = i + 1
                while k < n and pitch_tuple[k] == p:
                    k += 1
                notes.append((start_tick, p, (k - i) * TICKS_PER_BEAT))
                i = k
                continue

            # ── 経過音を試みる ─────────────────────────────────────────
            passing: Optional[int] = None
            if elaborate:
                interval = abs(p_next - p)
                if interval >= 3:
                    # 経過音スケール: 自然短音階（ナチュラルマイナー）を使用。
                    # ハーモニックマイナーの導音（C#）は和声的短音階特有で、
                    # 自由経過音に使うと ♭6(Bb)→#7(C#) の増2度が生じて半音階風になる。
                    # 自然短音階 = ハーモニックマイナーの導音を長7音（tonic-2）に置換。
                    key_at = harmonic_plan.key(i)
                    lt_pc = key_at.leading_tone_pc
                    nat7_pc = (key_at.tonic_pc - 2) % 12
                    scale_pcs: Set[int] = {
                        (nat7_pc if pc % 12 == lt_pc else pc % 12)
                        for pc in key_at.scale
                    }
                    direction = 1 if p_next > p else -1
                    for candidate in range(p + direction, p_next, direction):
                        if candidate % 12 in scale_pcs:
                            passing = candidate
                            break

            if passing is not None:
                # 八分音符(拍頭音) + 八分音符(経過音)
                notes.append((start_tick,             p,       half_tick))
                notes.append((start_tick + half_tick, passing, half_tick))
            else:
                # 四分音符（2度以内、またはスケール経過音なし）
                notes.append((start_tick, p, TICKS_PER_BEAT))

            i += 1

        result[vt] = notes

    return result


def apply_note_events_to_midi(
    midi_data: Dict[FugueVoiceType, List[Tuple[int, int, int]]],
    voice: FugueVoiceType,
    start_tick: int,
    note_events: list,   # List[NoteEvent] — 型ヒントは循環回避のため省略
    transpose: int = 0,
    subbeats_per_beat: int = 4,
) -> None:
    """MIDI データの特定範囲を NoteEvent リストで上書き。

    VoicePlan は拍単位グリッドのみ保持するため、主題内の十六分音符等の
    sub-beat 音符が失われる。本関数はその音符を MIDI 出力に復元する。

    Args:
        midi_data:  build_midi() が返す {voice: [(start, pitch, dur), ...]}
        voice:      対象声部
        start_tick: 主題開始の絶対 tick
        note_events: NoteEvent リスト（duration は subbeat 単位）
        transpose:  半音単位の移調量
        subbeats_per_beat: 1拍あたりの subbeat 数（通常 4 = 十六分音符単位）
    """
    ticks_per_subbeat = TICKS_PER_BEAT // subbeats_per_beat
    total_ticks = sum(n.duration for n in note_events) * ticks_per_subbeat
    end_tick = start_tick + total_ticks

    # 対象範囲外のノートをそのまま残す
    existing = midi_data.get(voice, [])
    outside = [
        (s, m, d) for s, m, d in existing
        if s + d <= start_tick or s >= end_tick
    ]

    # NoteEvent を tick 単位に変換して追加
    new_notes: List[Tuple[int, int, int]] = []
    tick = start_tick
    for n in note_events:
        dur_ticks = n.duration * ticks_per_subbeat
        new_notes.append((tick, n.pitch.midi + transpose, dur_ticks))
        tick += dur_ticks

    midi_data[voice] = sorted(outside + new_notes, key=lambda x: x[0])


# ============================================================
# SectionSpec: 提示部後の区間仕様
# ============================================================

@dataclass
class SectionSpec:
    """提示部後の一区間の仕様。

    start:          全体での開始拍インデックス
    length:         区間の拍数
    fixed_entries:  [(声部, ピッチリスト)] — ピッチリスト[i] は区間内の i 拍目のピッチ。
                    None の要素は「その拍は自由生成」を意味する。
                    空リストの場合は全声部を自由生成（エピソード/コーダ用）。
    cs_voices:      [(声部, 区間内開始オフセット)] — 対主題を割り当てる声部と開始拍。
                    compose_full() が FugueComposer.countersubject を当該声部にピン止めする。
    """
    start: int
    length: int
    fixed_entries: List[Tuple[FugueVoiceType, List[Optional[int]]]] = field(
        default_factory=list
    )
    cs_voices: List[Tuple[FugueVoiceType, int]] = field(
        default_factory=list
    )


# ============================================================
# FugueComposer: オーケストレーション
# ============================================================

class FugueComposer:
    """4声フーガ作曲エンジン v2。

    使用方法:
        composer = FugueComposer(structure, harmonic_plan, seed=42)
        voice_plan = composer.compose()
        if voice_plan is not None:
            midi = build_midi(voice_plan)
            report = validate(composer.harmonic_plan, voice_plan)
    """

    def __init__(
        self,
        structure: FugueStructure,
        harmonic_plan: HarmonicPlan,
        seed: int = 42,
    ):
        self.structure = structure
        self.harmonic_plan = harmonic_plan
        self.seed = seed
        self.rng = random.Random(seed)
        # 対主題: compose_exposition() 実行後に設定される拍単位ピッチ列
        # countersubject[i] = 区間内 i 拍目のMIDIピッチ（主題と同長）
        self.countersubject: Optional[List[Optional[int]]] = None

    def _expand_subject_beats(
        self, entry: FugueEntry
    ) -> List[int]:
        """主題/応答の拍ごとのMIDIピッチを返す。

        各拍頭で鳴っているピッチを1拍=1要素で返す。
        subbeat単位（16分音符）ではなく拍単位。
        """
        SUBBEATS = 4  # 四分音符 = 4 subbeats
        subject = entry.subject
        notes = subject.notes
        total_beats = subject.get_length()

        result: List[int] = []
        for beat in range(total_beats):
            beat_sb = beat * SUBBEATS
            acc = 0
            pitch_midi = notes[-1].pitch.midi
            for n in notes:
                if acc <= beat_sb < acc + n.duration:
                    pitch_midi = n.pitch.midi
                    break
                acc += n.duration
            result.append(pitch_midi)
        return result

    def compose_exposition(self) -> Optional[VoicePlan]:
        """提示部を生成。4声部全体を通してバックトラッキング。

        アルゴリズム:
        1. 各エントリの主題/応答ピッチを pinned として登録。
        2. 全 65 拍を 1 回の _backtrack() で生成。
           - ピン止め拍: 主題音符（和音外でも主題優先）
           - 自由拍: 各声部の音域内の和音構成音から最適選択
        3. 主題声部は主題提示中以外も常に発音し続ける。

        Returns:
            VoicePlan or None（生成失敗）
        """
        entries = self.structure.entries
        if not entries:
            entries = self.structure.create_exposition(
                answer_type="auto",
                overlap=self.structure.entry_overlap,
            )

        subject_len = self.structure.subject.get_length()
        total_beats = max(e.start_position + subject_len for e in entries)
        total_beats = min(total_beats, len(self.harmonic_plan))

        # 拍単位ピン止め: {voice: {beat: required_pitch}}
        # 音域外のピッチはオクターブ移調で音域内に収める（例: Bass主題 D4→D3）
        pinned: Dict[FugueVoiceType, Dict[int, int]] = {}
        for entry in entries:
            vt = entry.voice_type
            lo, hi = VOICE_RANGES.get(vt, (36, 84))
            beat_pitches = self._expand_subject_beats(entry)
            # 先頭音から移調量を決定（全音符を同量シフト）
            first_p = beat_pitches[0] if beat_pitches else 60
            transpose = 0
            while first_p + transpose < lo:
                transpose += 12
            while first_p + transpose > hi:
                transpose -= 12
            pinned[vt] = {}
            for i, p in enumerate(beat_pitches):
                b = entry.start_position + i
                if b < total_beats:
                    pinned[vt][b] = p + transpose

        all_voices = [
            FugueVoiceType.SOPRANO,
            FugueVoiceType.ALTO,
            FugueVoiceType.TENOR,
            FugueVoiceType.BASS,
        ]

        # 各声部の入声拍: エントリの start_position を使用
        # 入声前の拍は休止（None）となり、本物のフーガ提示部らしい
        # 順次入声が実現する。
        voice_start_beats: Dict[FugueVoiceType, int] = {
            entry.voice_type: entry.start_position for entry in entries
        }

        result = _backtrack(
            harmonic_plan=HarmonicPlan.from_lists(
                list(self.harmonic_plan.chord_plan[:total_beats]),
                list(self.harmonic_plan.key_map[:total_beats]),
            ),
            pinned=pinned,
            all_voices=all_voices,
            voice_ranges=VOICE_RANGES,
            prev_pitches=None,
            max_backtrack=128,
            voice_start_beats=voice_start_beats,
        )

        if result is None:
            return None

        return VoicePlan.from_dicts(result, total_beats)

    def compose_full(
        self,
        post_expo_sections: List[SectionSpec],
    ) -> Optional[VoicePlan]:
        """提示部 + 後続区間（エピソード・中間部・コーダ）を生成。

        アルゴリズム:
        1. compose_exposition() で提示部を生成。
        2. post_expo_sections の各区間を _backtrack() で順次生成。
           前区間の最終拍ピッチを prev_pitches として次区間に渡す（連続性保証）。
        3. 全区間を結合して VoicePlan を返す。
        """
        # Step 1: 提示部
        expo_result = self.compose_exposition()
        if expo_result is None:
            return None

        expo_beats = expo_result.num_beats

        if not post_expo_sections:
            return expo_result

        # 全体拍数の確認
        total_beats = post_expo_sections[-1].start + post_expo_sections[-1].length
        if total_beats > len(self.harmonic_plan):
            print(f"  [警告] 全体拍数 {total_beats} が和声計画 {len(self.harmonic_plan)} を超える")
            total_beats = len(self.harmonic_plan)

        # 全声部ピッチ配列を初期化（提示部 + None で拡張）
        all_pitches: Dict[FugueVoiceType, List[Optional[int]]] = {}
        for vt in FugueVoiceType:
            expo_row = list(expo_result.pitches.get(vt, (None,) * expo_beats))
            all_pitches[vt] = expo_row + [None] * (total_beats - expo_beats)

        # 提示部最後の拍のピッチ（区間連続性用）
        prev_pitches: Dict[FugueVoiceType, Optional[int]] = {
            vt: all_pitches[vt][expo_beats - 1] for vt in FugueVoiceType
        }

        # Step 2: 後続区間を順次生成
        voice_prio = [
            FugueVoiceType.SOPRANO,
            FugueVoiceType.ALTO,
            FugueVoiceType.TENOR,
            FugueVoiceType.BASS,
        ]

        for spec in post_expo_sections:
            start = spec.start
            length = spec.length

            if start + length > len(self.harmonic_plan):
                print(f"  [警告] セクション start={start}+{length} が和声計画を超える — スキップ")
                break

            section_plan = HarmonicPlan.from_lists(
                list(self.harmonic_plan.chord_plan[start:start + length]),
                list(self.harmonic_plan.key_map[start:start + length]),
            )

            # fixed_entries → 拍単位 pinned に変換
            # {voice: {local_beat: required_pitch}}
            pinned: Dict[FugueVoiceType, Dict[int, int]] = {}
            for vt, pitches in spec.fixed_entries:
                pinned[vt] = {}
                for i, p in enumerate(pitches[:length]):
                    if p is not None:
                        pinned[vt][i] = p
                        all_pitches[vt][start + i] = p  # 全体配列にも即時配置

            # 対主題を cs_voices で指定された声部にピン止め
            if self.countersubject and spec.cs_voices:
                for cs_vt, cs_offset in spec.cs_voices:
                    lo, hi = VOICE_RANGES.get(cs_vt, (36, 84))
                    if cs_vt not in pinned:
                        pinned[cs_vt] = {}
                    for i, p in enumerate(self.countersubject):
                        if p is None:
                            continue
                        beat_in_section = cs_offset + i
                        if beat_in_section >= length:
                            break
                        # 音域に収まるようオクターブ移調
                        while p < lo:
                            p += 12
                        while p > hi:
                            p -= 12
                        pinned[cs_vt][beat_in_section] = p

            bt_result = _backtrack(
                harmonic_plan=section_plan,
                pinned=pinned,
                all_voices=voice_prio,
                voice_ranges=VOICE_RANGES,
                prev_pitches=prev_pitches,
                max_backtrack=128,
            )

            if bt_result is None:
                print(f"  [失敗] セクション start={start} length={length} の生成失敗")
                return None

            for vt, pitches in bt_result.items():
                for i, p in enumerate(pitches):
                    all_pitches[vt][start + i] = p

            # 次区間用の前拍ピッチ
            prev_pitches = {
                vt: all_pitches[vt][start + length - 1] for vt in FugueVoiceType
            }

        return VoicePlan.from_dicts(all_pitches, total_beats)

    def generate_countersubject(
        self,
        subject_beats: List[int],
        cs_harmony_plan: HarmonicPlan,
        cs_voice: FugueVoiceType,
        ensure_gap_voice_range: Optional[Tuple[int, int]] = None,
        max_backtrack: int = 512,
    ) -> Optional[List[int]]:
        """転回対位法（8度）の原則に従い対主題を生成。

        主題を定旋律（CF）として扱い、各拍で以下を満たす声部線を生成する:
          1. 和音構成音（cs_harmony_plan の各拍の chord tone）
          2. ICP 有効音程: 2度(1,2)・増4度(6)・7度(10,11) を禁止
          3. 並行5度・8度なし（主題との間）
          4. 旋律禁則なし（増4度・増5度・7度跳躍・増2度）
          5. 順次進行優先（スコアリング）

        Args:
            subject_beats:          主題の拍ごとMIDIピッチリスト（subject_len 要素）
                                    実際に配置される移調済みピッチ（例: -12 移調の Bass主題）を渡す。
            cs_harmony_plan:        主題の和声計画（subject_len 拍）
            cs_voice:               対主題担当声部（音域制約に使用）
            ensure_gap_voice_range: (lo, hi) — CS と主題の間に挟まれる声部の音域。
                                    この範囲内に少なくとも 1 つの和音構成音が存在するよう制約する。
                                    4声配置での声部間隙を保証するために使用。
            max_backtrack:          最大バックトラック回数

        Returns:
            対主題の拍ごとMIDIピッチリスト or None（解なし）
        """
        proh = CounterpointProhibitions()
        lo, hi = VOICE_RANGES.get(cs_voice, (36, 84))
        n = len(subject_beats)
        key = cs_harmony_plan.key(0)

        def _ic(a: int, b: int) -> int:
            """音程クラス (mod 12)"""
            return abs(a - b) % 12

        def _valid_icp(cs: int, subj: int) -> bool:
            return _ic(cs, subj) not in _ICP_FORBIDDEN

        def _has_gap(cs: int, subj: int, beat: int) -> bool:
            """CS と主題の間に中間声部用の和音構成音が存在するか検証。

            ensure_gap_voice_range が指定された場合のみ検証する。
            4声配置で CS が主題の直上に来すぎて中間声部の配置不可能になるのを防ぐ。
            """
            if ensure_gap_voice_range is None:
                return True
            gap_lo, gap_hi = ensure_gap_voice_range
            chord_tones = cs_harmony_plan.chord(beat).tones
            lo_pitch = min(cs, subj)
            hi_pitch = max(cs, subj)
            # lo_pitch と hi_pitch の間（exclusive）に gap_voice の和音構成音が存在するか
            for m in range(max(lo_pitch + 1, gap_lo), min(hi_pitch, gap_hi + 1)):
                if m % 12 in chord_tones:
                    return True
            return False

        def _aug2(a: int, b: int) -> bool:
            """増2度（短調 b6→#7 ペア）か"""
            if abs(a - b) != 3:
                return False
            sc = key.scale
            if len(sc) < 7:
                return False
            aug2_pair = {sc[5] % 12, sc[6] % 12}
            return {a % 12, b % 12} == aug2_pair

        # 各拍の基本候補: 和音構成音 ∩ 音域 ∩ ICP 有効 ∩ ギャップ確保
        base_cands: List[List[int]] = []
        for beat in range(n):
            chord_tones = cs_harmony_plan.chord(beat).tones
            subj = subject_beats[beat]
            cands = [
                m for m in range(lo, hi + 1)
                if m % 12 in chord_tones
                and _valid_icp(m, subj)
                and _has_gap(m, subj, beat)
            ]
            base_cands.append(cands)

        def _melodic_ok(cs: int, prev_cs: int, beat: int) -> bool:
            """旋律禁則チェック（主題との並行・旋律線の両方）"""
            prev_subj = subject_beats[beat - 1]
            curr_subj = subject_beats[beat]
            # 並行5度・8度（対主題と主題の間）
            ok, _ = proh.check_parallel_perfect(prev_cs, cs, prev_subj, curr_subj)
            if not ok:
                return False
            # 旋律禁則: 増4度・増5度
            ok, _ = proh.check_melodic_augmented(prev_cs, cs)
            if not ok:
                return False
            # 旋律禁則: 7度跳躍
            ok, _ = proh.check_melodic_seventh(prev_cs, cs)
            if not ok:
                return False
            # C17: 増2度（短調 b6→#7）
            if _aug2(prev_cs, cs):
                return False
            return True

        def _score(cs: int, beat: int, prev_cs: Optional[int]) -> float:
            cost = 0.0
            if prev_cs is not None:
                interval = abs(cs - prev_cs)
                if interval == 0:
                    cost += 4.0        # 同音保持: ペナルティ
                elif interval <= 2:
                    cost -= 1.0        # 順次進行: ボーナス
                elif interval <= 4:
                    cost += 0.5        # 3度: 許容
                elif interval <= 7:
                    cost += 2.0        # 4〜5度
                else:
                    cost += 5.0        # 6度以上
            # ICP 注意音程ペナルティ
            ic = _ic(cs, subject_beats[beat])
            if ic in _ICP_CAUTIOUS:
                cost += 3.0
            return cost

        def _build_sorted(beat: int, prev_cs: Optional[int]) -> List[int]:
            """フィルタ済み・スコアソート済み候補リストを生成。"""
            if prev_cs is None:
                filtered = list(base_cands[beat])
            else:
                filtered = [c for c in base_cands[beat]
                            if _melodic_ok(c, prev_cs, beat)]
            return sorted(filtered, key=lambda c: _score(c, beat, prev_cs))

        # バックトラッキング
        solution: List[Optional[Tuple[int, int]]] = [None] * n
        sorted_cands: List[List[int]] = [[] for _ in range(n)]

        beat = 0
        backtracks = 0
        while beat < n:
            prev_cs: Optional[int] = (
                solution[beat - 1][0] if beat > 0 and solution[beat - 1] else None
            )

            if solution[beat] is None:
                # 新規到達: 候補リストを構築
                sorted_cands[beat] = _build_sorted(beat, prev_cs)
                start_idx = 0
            else:
                # バックトラックで戻ってきた: 次の候補から
                start_idx = solution[beat][1] + 1
                solution[beat] = None

            found = False
            for idx in range(start_idx, len(sorted_cands[beat])):
                solution[beat] = (sorted_cands[beat][idx], idx)
                found = True
                break

            if found:
                beat += 1
            else:
                solution[beat] = None
                beat -= 1
                backtracks += 1
                if beat < 0 or backtracks > max_backtrack:
                    return None

        self.countersubject = [solution[b][0] for b in range(n)]
        return self.countersubject

    def compose(self) -> Optional[VoicePlan]:
        """フーガ全体を生成（Phase 1: 提示部のみ）。"""
        return self.compose_exposition()
