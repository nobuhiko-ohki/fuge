"""VNS (Variable Neighborhood Search) による対位法サブビートグリッド洗練モジュール

設計思想:
  - 初期解（DP + RhythmElaborator 出力）を受け取り、局所修正で品質を向上させる
  - 近傍操作はピッチ変更だけでなくリズム操作（音の延長・ずらし）を含む
  - 評価は辞書式順序（lexicographic）: 致命的 > 和声 > 旋律 > 美学
  - 問題駆動型: 全体をランダムに動かさず、最悪の拍に修正を集中する

用語:
  - subbeat: 16分音符1つ分 (SUBBEATS_PER_BEAT = 4)
  - beat: 四分音符1つ分 = 4 subbeats
  - grid: Dict[FugueVoiceType, List[Optional[int]]] — サブビートレベルのMIDIピッチ
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, FrozenSet

from fugue_structure import Key, FugueVoiceType
from fugue_realization import (
    SUBBEATS_PER_BEAT, VOICE_RANGES, ChordLabel, RhythmElaborator,
)

SB = SUBBEATS_PER_BEAT  # 4


# ============================================================
# 辞書式順序スコア
# ============================================================

@dataclass(order=True)
class LexScore:
    """辞書式順序で比較可能なスコア。値が小さいほど良い。

    level0_fatal:  並行5度/8度、声部交差 (件数)
    level1_harmony: 半音衝突、和音構成音の欠落 (件数)
    level2_melody:  跳躍過多、順次進行不足 (件数)
    level3_aesthetic: リズム単調さ等 (件数)
    """
    level0_fatal: int = 0
    level1_harmony: int = 0
    level2_melody: int = 0
    level3_aesthetic: int = 0

    def __add__(self, other: 'LexScore') -> 'LexScore':
        return LexScore(
            self.level0_fatal + other.level0_fatal,
            self.level1_harmony + other.level1_harmony,
            self.level2_melody + other.level2_melody,
            self.level3_aesthetic + other.level3_aesthetic,
        )


# ============================================================
# 拍単位の評価関数
# ============================================================

def _interval_class(a: int, b: int) -> int:
    """2音間のインターバルクラス (0-6)"""
    diff = abs(a - b) % 12
    return diff if diff <= 6 else 12 - diff


def evaluate_beat(
    grid: Dict[FugueVoiceType, List[Optional[int]]],
    beat: int,
    chord: Optional[ChordLabel],
    key: Key,
    total_beats: int,
    subject_beats: Dict[FugueVoiceType, Set[int]],
    prev_section_pitches: Optional[Dict[FugueVoiceType, int]] = None,
) -> LexScore:
    """1拍のスコアを算出する。

    全声部のサブビートを見て、致命的→和声→旋律の順に違反を数える。
    """
    sb_start = beat * SB
    sb_end = sb_start + SB
    # gridに存在する声部のみ（3声フーガではTENOR等が不在の場合がある）
    voice_order = [FugueVoiceType.SOPRANO, FugueVoiceType.ALTO,
                   FugueVoiceType.TENOR, FugueVoiceType.BASS]
    voices = [vt for vt in voice_order if vt in grid]
    score = LexScore()

    # --- この拍の各声部のピッチを取得 ---
    beat_pitches: Dict[FugueVoiceType, List[Optional[int]]] = {}
    for vt in voices:
        pitches = grid[vt][sb_start:sb_end]
        beat_pitches[vt] = pitches

    # 活動中の声部（この拍でNone以外がある声部）
    active_voices = [vt for vt in voices
                     if any(p is not None for p in beat_pitches[vt])]
    if len(active_voices) < 2:
        return score

    # === Level 0: 致命的 ===

    # (0a) 声部交差: 拍頭で判定
    beat_head = {}
    for vt in active_voices:
        p = beat_pitches[vt][0]
        if p is not None:
            beat_head[vt] = p
    voice_order = [FugueVoiceType.SOPRANO, FugueVoiceType.ALTO,
                   FugueVoiceType.TENOR, FugueVoiceType.BASS]
    ordered = [vt for vt in voice_order if vt in beat_head]
    for i in range(len(ordered) - 1):
        if beat_head[ordered[i]] < beat_head[ordered[i + 1]]:
            score.level0_fatal += 1

    # (0b) 並行5度/8度: 前拍→この拍の拍頭で判定
    # beat==0でもprev_section_pitchesがあればセクション境界チェック
    if beat == 0 and prev_section_pitches:
        for i in range(len(active_voices)):
            for j in range(i + 1, len(active_voices)):
                va, vb = active_voices[i], active_voices[j]
                prev_a = prev_section_pitches.get(va)
                prev_b = prev_section_pitches.get(vb)
                curr_a = beat_pitches[va][0]
                curr_b = beat_pitches[vb][0]
                if None in (prev_a, prev_b, curr_a, curr_b):
                    continue
                if prev_a == curr_a or prev_b == curr_b:
                    continue
                prev_ic = _interval_class(prev_a, prev_b)
                curr_ic = _interval_class(curr_a, curr_b)
                if prev_ic == curr_ic and curr_ic in (0, 5):
                    weight = 2 if {va, vb} == {FugueVoiceType.SOPRANO,
                                                FugueVoiceType.BASS} else 1
                    score.level0_fatal += weight
    if beat > 0:
        prev_sb = (beat - 1) * SB
        for i in range(len(active_voices)):
            for j in range(i + 1, len(active_voices)):
                va, vb = active_voices[i], active_voices[j]
                prev_a = grid[va][prev_sb]
                prev_b = grid[vb][prev_sb]
                curr_a = beat_pitches[va][0]
                curr_b = beat_pitches[vb][0]
                if None in (prev_a, prev_b, curr_a, curr_b):
                    continue
                # 両方とも動いている場合のみ（斜行は除外）
                if prev_a == curr_a or prev_b == curr_b:
                    continue
                prev_ic = _interval_class(prev_a, prev_b)
                curr_ic = _interval_class(curr_a, curr_b)
                # 並行5度(ic=5)または並行8度(ic=0, ユニゾン含む)
                if prev_ic == curr_ic and curr_ic in (0, 5):
                    # 外声（ソプラノ-バス）は特に重い
                    weight = 2 if {va, vb} == {FugueVoiceType.SOPRANO,
                                                FugueVoiceType.BASS} else 1
                    score.level0_fatal += weight

    # === (0c) 半音衝突: 同一サブビートで半音差の2音がある ===
    # 半音衝突は並行5度/8度と同等以上に深刻 → L0に分類
    for sb_offset in range(SB):
        abs_sb = sb_start + sb_offset
        sounding = []
        for vt in active_voices:
            p = grid[vt][abs_sb]
            if p is not None:
                sounding.append(p)
        for ii in range(len(sounding)):
            for jj in range(ii + 1, len(sounding)):
                diff = abs(sounding[ii] - sounding[jj])
                if diff == 1 or diff == 11:
                    pc_pair = {sounding[ii] % 12, sounding[jj] % 12}
                    leading = (key.tonic_pc - 1) % 12
                    if pc_pair == {leading, key.tonic_pc}:
                        # 導音-主音ペア: MIDI距離が近く、片方のみ和声音なら衝突
                        if diff > 2:
                            continue  # 離れた音域（≥短3度）は許容
                        if chord is not None:
                            pc_a = sounding[ii] % 12
                            pc_b = sounding[jj] % 12
                            a_in = pc_a in chord.tones
                            b_in = pc_b in chord.tones
                            if a_in == b_in:
                                continue  # 両方和声音 or 両方非和声音 → OK
                            # 片方が和声音、片方が非和声音 → 衝突
                        else:
                            continue  # コード情報なし → 従来通り許容
                    score.level0_fatal += 1

    # === (0d) 対斜（cross relation）: 前拍→この拍で同一音名の半音変化 ===
    # 短調における自然7度/導音、自然6度/長6度のペアのみ対象
    if beat > 0 and key.mode == "minor":
        t = key.tonic_pc
        cr_pairs = {
            (min((t - 2) % 12, (t - 1) % 12),
             max((t - 2) % 12, (t - 1) % 12)),   # 自然7度/導音
            (min((t + 8) % 12, (t + 9) % 12),
             max((t + 8) % 12, (t + 9) % 12)),   # 自然6度/長6度
        }
        prev_sb_cr = (beat - 1) * SB
        for i in range(len(active_voices)):
            for j in range(len(active_voices)):
                if i == j:
                    continue
                va, vb = active_voices[i], active_voices[j]
                prev_p = grid[va][prev_sb_cr]
                curr_p = beat_pitches[vb][0]
                if prev_p is None or curr_p is None:
                    continue
                pc_prev = prev_p % 12
                pc_curr = curr_p % 12
                diff_cr = (pc_curr - pc_prev) % 12
                if diff_cr != 1 and diff_cr != 11:
                    continue
                pair = (min(pc_prev, pc_curr), max(pc_prev, pc_curr))
                if pair not in cr_pairs:
                    continue
                # 同一声部が変化を引き受けていれば許容
                va_curr = beat_pitches[va][0]
                if va_curr is not None and va_curr % 12 == pc_curr:
                    continue
                vb_prev = grid[vb][prev_sb_cr]
                if vb_prev is not None and vb_prev % 12 == pc_prev:
                    continue
                score.level0_fatal += 1

    # === Level 1: 和声 ===

    if chord is not None:
        chord_tones = chord.tones

        # (1b) 拍頭の構成音充足: 根音または第3音が全声部に存在するか
        head_pcs = set()
        for vt in active_voices:
            p = beat_pitches[vt][0]
            if p is not None:
                head_pcs.add(p % 12)
        if chord.root_pc not in head_pcs and chord.third_pc not in head_pcs:
            score.level1_harmony += 1

    # === Level 2: 旋律 ===

    for vt in active_voices:
        if beat in subject_beats.get(vt, set()):
            continue  # 主題声部は旋律評価しない（固定）

        # (2a) 前拍→この拍の跳躍幅 + 増音程チェック
        if beat > 0:
            prev_head = grid[vt][(beat - 1) * SB]
            curr_head = beat_pitches[vt][0]
            if prev_head is not None and curr_head is not None:
                leap = abs(curr_head - prev_head)
                if leap > 7:  # 5度超の跳躍
                    score.level2_melody += 1
                if leap > 12:  # オクターブ超
                    score.level2_melody += 1
                # 増音程: 増2度(3半音)、増4度/減5度(6半音=トライトーン)
                # ハード禁止: L0に分類（並行5度/8度、半音衝突と同等）
                interval_mod = leap % 12
                if interval_mod == 3:
                    prev_pc = prev_head % 12
                    curr_pc = curr_head % 12
                    # コードに整合するスケールで増2度判定
                    is_aug = False
                    chord_tones = chord.tones if chord else set()
                    beat_scale_list = key.scale_for_chord(chord_tones)
                    if len(beat_scale_list) == 7:
                        aug2_pair = {beat_scale_list[5], beat_scale_list[6]}
                        if {prev_pc, curr_pc} == aug2_pair:
                            is_aug = True
                    # スケール外音を含む3半音音程
                    if not is_aug:
                        beat_scale_set = set(beat_scale_list)
                        if prev_pc not in beat_scale_set or curr_pc not in beat_scale_set:
                            is_aug = True
                    if is_aug:
                        score.level0_fatal += 1  # 増2度: ハード禁止
                elif interval_mod == 6:
                    score.level0_fatal += 1       # トライトーン跳躍: ハード禁止

        # (2b) 拍内の連続同音（トリル的パターン）
        pitches_in_beat = [p for p in beat_pitches[vt] if p is not None]
        if len(pitches_in_beat) >= 3:
            # A-B-A パターンの検出
            for k in range(len(pitches_in_beat) - 2):
                if (pitches_in_beat[k] == pitches_in_beat[k + 2] and
                        pitches_in_beat[k] != pitches_in_beat[k + 1]):
                    score.level2_melody += 1

    # === Level 3: 美学 ===
    # （現時点では最小限。リズム多様性等は今後追加）

    return score


def evaluate_grid(
    grid: Dict[FugueVoiceType, List[Optional[int]]],
    chord_plan: List[ChordLabel],
    key: Key,
    total_beats: int,
    subject_beats: Dict[FugueVoiceType, Set[int]],
    prev_section_pitches: Optional[Dict[FugueVoiceType, int]] = None,
    beat_key_map: Optional[Dict[int, Key]] = None,
) -> Tuple[LexScore, List[Tuple[int, LexScore]]]:
    """全拍を評価し、合計スコアと拍別スコアを返す。"""
    total = LexScore()
    per_beat: List[Tuple[int, LexScore]] = []
    for beat in range(total_beats):
        chord = chord_plan[beat] if beat < len(chord_plan) else None
        psp = prev_section_pitches if beat == 0 else None
        bk = beat_key_map.get(beat, key) if beat_key_map else key
        bs = evaluate_beat(grid, beat, chord, bk, total_beats, subject_beats, psp)
        total = total + bs
        per_beat.append((beat, bs))
    return total, per_beat


# ============================================================
# 近傍操作 (Neighborhood moves)
# ============================================================

def _get_mutable_voices(
    beat: int,
    grid: Dict[FugueVoiceType, List[Optional[int]]],
    subject_beats: Dict[FugueVoiceType, Set[int]],
) -> List[FugueVoiceType]:
    """指定拍で変更可能な（主題でない）声部を返す"""
    sb_start = beat * SB
    result = []
    for vt in FugueVoiceType:
        if vt not in grid:
            continue  # この声部はgridに存在しない（3声フーガ等）
        if beat in subject_beats.get(vt, set()):
            continue  # 主題は不可変
        if any(grid[vt][sb_start + s] is not None for s in range(SB)):
            result.append(vt)
    return result


class NeighborhoodMove:
    """1回の近傍操作を表すプロトコル"""

    def apply(
        self,
        grid: Dict[FugueVoiceType, List[Optional[int]]],
    ) -> None:
        """gridを直接変更する"""
        raise NotImplementedError

    def undo(
        self,
        grid: Dict[FugueVoiceType, List[Optional[int]]],
    ) -> None:
        """applyを巻き戻す"""
        raise NotImplementedError


class PitchChangeMove(NeighborhoodMove):
    """N1: 1拍の骨格音（拍頭）を変更し、拍内サブビートを再装飾"""

    def __init__(self, vt: FugueVoiceType, beat: int,
                 new_head_pitch: int,
                 new_subbeats: List[int],
                 old_subbeats: List[int]):
        self.vt = vt
        self.beat = beat
        self.new_subbeats = new_subbeats
        self.old_subbeats = old_subbeats

    def apply(self, grid):
        sb_start = self.beat * SB
        for s in range(SB):
            grid[self.vt][sb_start + s] = self.new_subbeats[s]

    def undo(self, grid):
        sb_start = self.beat * SB
        for s in range(SB):
            grid[self.vt][sb_start + s] = self.old_subbeats[s]


class RhythmPatternMove(NeighborhoodMove):
    """N2: リズムパターンを変えて再装飾（拍頭は維持）"""

    def __init__(self, vt: FugueVoiceType, beat: int,
                 new_subbeats: List[int],
                 old_subbeats: List[int]):
        self.vt = vt
        self.beat = beat
        self.new_subbeats = new_subbeats
        self.old_subbeats = old_subbeats

    def apply(self, grid):
        sb_start = self.beat * SB
        for s in range(SB):
            grid[self.vt][sb_start + s] = self.new_subbeats[s]

    def undo(self, grid):
        sb_start = self.beat * SB
        for s in range(SB):
            grid[self.vt][sb_start + s] = self.old_subbeats[s]


class NoteExtensionMove(NeighborhoodMove):
    """N3: 前拍末尾の音を現拍に延長（タイ的効果）

    バッハの技法: 協和音を次拍まで引き延ばして不協和を回避する。
    拍頭の1-2サブビートを前拍末尾の音で埋め、残りを再装飾。
    """

    def __init__(self, vt: FugueVoiceType, beat: int,
                 extend_subbeats: int,
                 new_subbeats: List[int],
                 old_subbeats: List[int]):
        self.vt = vt
        self.beat = beat
        self.extend_subbeats = extend_subbeats
        self.new_subbeats = new_subbeats
        self.old_subbeats = old_subbeats

    def apply(self, grid):
        sb_start = self.beat * SB
        for s in range(SB):
            grid[self.vt][sb_start + s] = self.new_subbeats[s]

    def undo(self, grid):
        sb_start = self.beat * SB
        for s in range(SB):
            grid[self.vt][sb_start + s] = self.old_subbeats[s]


class DisplacementMove(NeighborhoodMove):
    """N4: 音のずらし（サブビート単位で前後に移動）

    拍頭を1サブビート遅らせ、前拍末尾の音を延長する効果。
    掛留音（suspension）や先取音（anticipation）を生成する。
    """

    def __init__(self, vt: FugueVoiceType, beat: int,
                 new_subbeats: List[int],
                 old_subbeats: List[int]):
        self.vt = vt
        self.beat = beat
        self.new_subbeats = new_subbeats
        self.old_subbeats = old_subbeats

    def apply(self, grid):
        sb_start = self.beat * SB
        for s in range(SB):
            grid[self.vt][sb_start + s] = self.new_subbeats[s]

    def undo(self, grid):
        sb_start = self.beat * SB
        for s in range(SB):
            grid[self.vt][sb_start + s] = self.old_subbeats[s]


class PassingToneSwapMove(NeighborhoodMove):
    """N5: 弱拍サブビートの経過音・刺繍音を差し替え"""

    def __init__(self, vt: FugueVoiceType, beat: int,
                 new_subbeats: List[int],
                 old_subbeats: List[int]):
        self.vt = vt
        self.beat = beat
        self.new_subbeats = new_subbeats
        self.old_subbeats = old_subbeats

    def apply(self, grid):
        sb_start = self.beat * SB
        for s in range(SB):
            grid[self.vt][sb_start + s] = self.new_subbeats[s]

    def undo(self, grid):
        sb_start = self.beat * SB
        for s in range(SB):
            grid[self.vt][sb_start + s] = self.old_subbeats[s]


# ============================================================
# 近傍操作の候補生成
# ============================================================

def _generate_n1_moves(
    grid: Dict[FugueVoiceType, List[Optional[int]]],
    beat: int,
    vt: FugueVoiceType,
    chord: Optional[ChordLabel],
    key: Key,
    elaborator: RhythmElaborator,
    rng: random.Random,
) -> List[PitchChangeMove]:
    """N1: 骨格音変更の候補を生成"""
    moves = []
    if chord is None:
        return moves

    sb_start = beat * SB
    old_subbeats = [grid[vt][sb_start + s] for s in range(SB)]
    old_head = old_subbeats[0]
    if old_head is None:
        return moves

    lo, hi = VOICE_RANGES[vt]

    # 和音構成音およびコードに整合するスケール音から候補を列挙
    beat_scale_pcs = set(key.scale_for_chord(chord.tones))
    candidates = set()
    for midi in range(lo, hi + 1):
        pc = midi % 12
        if pc in chord.tones or pc in beat_scale_pcs:
            candidates.add(midi)
    # 現在値は除外
    candidates.discard(old_head)

    # 順次進行の候補を優先（±1〜4半音以内）
    beat_scale_list = key.scale_for_chord(chord.tones)
    nearby = sorted(candidates, key=lambda m: abs(m - old_head))
    for new_head in nearby[:8]:  # 候補を絞る
        # 次拍の骨格音
        next_sb = (beat + 1) * SB
        next_head = grid[vt][next_sb] if next_sb < len(grid[vt]) else None

        # 再装飾（コードから決定したスケールを渡す）
        ct = chord.tones if chord else None
        elaborated = elaborator.elaborate_beat(
            new_head, next_head, 'Q', VOICE_RANGES[vt], chord_tones=ct,
            beat_scale=beat_scale_list)
        new_subbeats = []
        for pitch, dur in elaborated:
            new_subbeats.extend([pitch] * dur)
        # パディング
        while len(new_subbeats) < SB:
            new_subbeats.append(new_subbeats[-1] if new_subbeats else new_head)
        new_subbeats = new_subbeats[:SB]

        moves.append(PitchChangeMove(vt, beat, new_head, new_subbeats, old_subbeats))

    return moves


def _generate_n2_moves(
    grid: Dict[FugueVoiceType, List[Optional[int]]],
    beat: int,
    vt: FugueVoiceType,
    chord: Optional[ChordLabel],
    elaborator: RhythmElaborator,
    key: Optional[Key] = None,
) -> List[RhythmPatternMove]:
    """N2: リズムパターン変更の候補を生成"""
    moves = []
    sb_start = beat * SB
    old_subbeats = [grid[vt][sb_start + s] for s in range(SB)]
    head_pitch = old_subbeats[0]
    if head_pitch is None:
        return moves

    next_sb = (beat + 1) * SB
    next_head = grid[vt][next_sb] if next_sb < len(grid[vt]) else None
    ct = chord.tones if chord else None
    # コードからスケールを決定
    beat_scale = (key.scale_for_chord(ct) if key and ct else None)

    # 各パターンで再装飾
    for pattern_name in ['Q', 'EE', 'EQ', 'QE', 'SSSS', 'SSE', 'ESS']:
        elaborated = elaborator.elaborate_beat(
            head_pitch, next_head, pattern_name, VOICE_RANGES[vt],
            chord_tones=ct, beat_scale=beat_scale)
        new_subbeats = []
        for pitch, dur in elaborated:
            new_subbeats.extend([pitch] * dur)
        while len(new_subbeats) < SB:
            new_subbeats.append(new_subbeats[-1] if new_subbeats else head_pitch)
        new_subbeats = new_subbeats[:SB]

        if new_subbeats != old_subbeats:
            moves.append(RhythmPatternMove(vt, beat, new_subbeats, old_subbeats))

    return moves


def _generate_n3_moves(
    grid: Dict[FugueVoiceType, List[Optional[int]]],
    beat: int,
    vt: FugueVoiceType,
    chord: Optional[ChordLabel],
    elaborator: RhythmElaborator,
    key: Optional[Key] = None,
) -> List[NoteExtensionMove]:
    """N3: 前拍末尾の音を延長する候補を生成

    バッハの技法: 前拍の協和音を引き延ばし、不協和を回避。
    """
    moves = []
    if beat == 0:
        return moves

    sb_start = beat * SB
    old_subbeats = [grid[vt][sb_start + s] for s in range(SB)]
    if old_subbeats[0] is None:
        return moves

    # 前拍末尾の音
    prev_last = grid[vt][sb_start - 1]
    if prev_last is None:
        return moves

    next_sb = (beat + 1) * SB
    next_head = grid[vt][next_sb] if next_sb < len(grid[vt]) else None
    ct = chord.tones if chord else None
    # コードからスケールを決定
    beat_scale = (key.scale_for_chord(ct) if key and ct else None)

    # 1〜2サブビート延長
    for extend_count in [1, 2]:
        # 延長部分は前拍末尾の音を使用
        new_subbeats = [prev_last] * extend_count

        # 残りを再装飾（延長後の最初の非延長音から）
        remaining_sb = SB - extend_count
        if remaining_sb > 0 and next_head is not None:
            # 残りは元の骨格音から次拍に向かう経過音
            orig_head = old_subbeats[0]
            elaborated = elaborator.elaborate_beat(
                orig_head, next_head, 'Q', VOICE_RANGES[vt],
                chord_tones=ct, beat_scale=beat_scale)
            rest_pitches = []
            for pitch, dur in elaborated:
                rest_pitches.extend([pitch] * dur)
            # 延長分を飛ばした後半を使用
            rest_pitches = rest_pitches[extend_count:extend_count + remaining_sb]
            new_subbeats.extend(rest_pitches)
        else:
            new_subbeats.extend([old_subbeats[0]] * remaining_sb)

        while len(new_subbeats) < SB:
            new_subbeats.append(new_subbeats[-1])
        new_subbeats = new_subbeats[:SB]

        if new_subbeats != old_subbeats:
            moves.append(NoteExtensionMove(
                vt, beat, extend_count, new_subbeats, old_subbeats))

    return moves


def _generate_n4_moves(
    grid: Dict[FugueVoiceType, List[Optional[int]]],
    beat: int,
    vt: FugueVoiceType,
    chord: Optional[ChordLabel],
) -> List[DisplacementMove]:
    """N4: 音のずらし（掛留・先取）候補を生成"""
    moves = []
    if beat == 0:
        return moves

    sb_start = beat * SB
    old_subbeats = [grid[vt][sb_start + s] for s in range(SB)]
    if old_subbeats[0] is None:
        return moves

    prev_last = grid[vt][sb_start - 1]
    if prev_last is None or prev_last == old_subbeats[0]:
        return moves

    # 掛留: 拍頭を前拍末尾の音にし、本来の拍頭音を1サブビート遅らせる
    new_subbeats = [prev_last, old_subbeats[0]] + old_subbeats[2:4]
    while len(new_subbeats) < SB:
        new_subbeats.append(new_subbeats[-1])
    new_subbeats = new_subbeats[:SB]

    if new_subbeats != old_subbeats:
        moves.append(DisplacementMove(vt, beat, new_subbeats, old_subbeats))

    return moves


def _generate_n5_moves(
    grid: Dict[FugueVoiceType, List[Optional[int]]],
    beat: int,
    vt: FugueVoiceType,
    chord: Optional[ChordLabel],
    key: Key,
) -> List[PassingToneSwapMove]:
    """N5: 弱拍サブビート（2番目以降）の経過音差替え候補を生成"""
    moves = []
    sb_start = beat * SB
    old_subbeats = [grid[vt][sb_start + s] for s in range(SB)]
    head = old_subbeats[0]
    if head is None:
        return moves

    lo, hi = VOICE_RANGES[vt]

    # コードからスケールを決定
    ct = chord.tones if chord else set()
    beat_scale_pcs = set(key.scale_for_chord(ct))

    # サブビート1,2,3の各位置で差替え候補を生成
    for sb_offset in range(1, SB):
        old_pitch = old_subbeats[sb_offset]
        if old_pitch is None:
            continue

        prev_p = old_subbeats[sb_offset - 1]
        if prev_p is None:
            continue

        # 順次進行の候補: prev_pから±1〜2半音
        for step in [-2, -1, 1, 2]:
            new_p = prev_p + step
            if new_p < lo or new_p > hi:
                continue
            if new_p == old_pitch:
                continue
            # コードに整合するスケール音を優先
            if (new_p % 12) not in beat_scale_pcs:
                continue

            new_subbeats = list(old_subbeats)
            new_subbeats[sb_offset] = new_p
            moves.append(PassingToneSwapMove(vt, beat, new_subbeats, old_subbeats))

    return moves


# ============================================================
# VNS メインループ
# ============================================================

class VNSRefiner:
    """VNS反復修正によるサブビートグリッドの洗練

    使用法:
        refiner = VNSRefiner(grid, chord_plan, key, subject_beats,
                             total_beats, seed=42)
        improved_grid, report = refiner.refine(max_iterations=500)
    """

    def __init__(
        self,
        grid: Dict[FugueVoiceType, List[Optional[int]]],
        chord_plan: List[ChordLabel],
        key: Key,
        subject_beats: Dict[FugueVoiceType, Set[int]],
        total_beats: int,
        seed: int = 42,
        elaborate: bool = True,
        prev_section_pitches: Optional[Dict[FugueVoiceType, int]] = None,
        beat_key_map: Optional[Dict[int, Key]] = None,
    ):
        # グリッドのディープコピー（元データを壊さない）
        self.grid = {vt: list(pitches) for vt, pitches in grid.items()}
        self.chord_plan = chord_plan
        self.key = key
        self.subject_beats = subject_beats
        self.total_beats = total_beats
        self.rng = random.Random(seed)
        self.elaborator = RhythmElaborator(key.scale, seed=seed,
                                            elaborate=elaborate)
        self._iteration_log: List[str] = []
        # セクション境界での平行5度/8度チェック用
        self.prev_section_pitches = prev_section_pitches or {}
        # 拍→調マップ: 提示部のように区間内で調が変わる場合に使用
        self.beat_key_map = beat_key_map or {}

    def _key_for_beat(self, beat: int) -> Key:
        """拍に対応する調を返す。beat_key_mapがあればそちらを優先。"""
        return self.beat_key_map.get(beat, self.key)

    def refine(
        self,
        max_iterations: int = 500,
        patience: int = 50,
        verbose: bool = True,
    ) -> Tuple[Dict[FugueVoiceType, List[Optional[int]]], List[str]]:
        """VNS反復修正を実行

        Args:
            max_iterations: 最大反復回数
            patience: 改善なしで打ち切る反復数
            verbose: 進捗を標準出力に表示

        Returns:
            (改善されたgrid, ログメッセージのリスト)
        """
        # 初期評価
        total_score, per_beat = evaluate_grid(
            self.grid, self.chord_plan, self.key,
            self.total_beats, self.subject_beats,
            self.prev_section_pitches,
            beat_key_map=self.beat_key_map)

        if verbose:
            msg = (f"VNS初期スコア: L0={total_score.level0_fatal} "
                   f"L1={total_score.level1_harmony} "
                   f"L2={total_score.level2_melody} "
                   f"L3={total_score.level3_aesthetic}")
            print(msg)
            self._iteration_log.append(msg)

        best_score = total_score
        no_improve_count = 0

        for iteration in range(max_iterations):
            if no_improve_count >= patience:
                msg = f"VNS: {patience}反復改善なし、終了 (iter={iteration})"
                if verbose:
                    print(msg)
                self._iteration_log.append(msg)
                break

            # 問題拍の特定: スコアが非ゼロの拍をスコア降順で並べる
            problem_beats = [
                (beat, bs) for beat, bs in per_beat
                if bs > LexScore()
            ]
            if not problem_beats:
                msg = f"VNS: 全拍スコアゼロ、完了 (iter={iteration})"
                if verbose:
                    print(msg)
                self._iteration_log.append(msg)
                break

            # 最悪の拍を選択（ランダム性を少し加える: 上位3拍から）
            problem_beats.sort(key=lambda x: x[1], reverse=True)
            top_n = min(3, len(problem_beats))
            target_beat, target_score = self.rng.choice(problem_beats[:top_n])

            # 変更可能な声部
            mutable = _get_mutable_voices(
                target_beat, self.grid, self.subject_beats)
            if not mutable:
                no_improve_count += 1
                continue

            # 近傍操作の候補を全近傍(N1-N5)から生成
            chord = (self.chord_plan[target_beat]
                     if target_beat < len(self.chord_plan) else None)

            beat_key = self._key_for_beat(target_beat)
            all_moves: List[NeighborhoodMove] = []
            for vt in mutable:
                if self.elaborator.elaborate:
                    # 装飾あり: N2-N5（サブビート操作）も含める
                    all_moves.extend(_generate_n5_moves(
                        self.grid, target_beat, vt, chord, beat_key))
                    all_moves.extend(_generate_n2_moves(
                        self.grid, target_beat, vt, chord, self.elaborator,
                        key=beat_key))
                    all_moves.extend(_generate_n3_moves(
                        self.grid, target_beat, vt, chord, self.elaborator,
                        key=beat_key))
                    all_moves.extend(_generate_n4_moves(
                        self.grid, target_beat, vt, chord))
                # N1（拍頭音変更）は常に有効
                all_moves.extend(_generate_n1_moves(
                    self.grid, target_beat, vt, chord, beat_key,
                    self.elaborator, self.rng))

            if not all_moves:
                no_improve_count += 1
                continue

            # 各moveを試して最良の改善を見つける
            best_move = None
            best_new_total = total_score

            # 候補が多すぎる場合はサンプリング
            if len(all_moves) > 30:
                self.rng.shuffle(all_moves)
                all_moves = all_moves[:30]

            for move in all_moves:
                move.apply(self.grid)

                # 影響範囲の拍だけ再評価（前後1拍を含む）
                affected_beats = [target_beat]
                if target_beat > 0:
                    affected_beats.append(target_beat - 1)
                if target_beat + 1 < self.total_beats:
                    affected_beats.append(target_beat + 1)

                new_total = LexScore(
                    total_score.level0_fatal,
                    total_score.level1_harmony,
                    total_score.level2_melody,
                    total_score.level3_aesthetic,
                )
                # 影響拍の旧スコアを引いて新スコアを足す
                for ab in affected_beats:
                    old_bs = per_beat[ab][1]
                    psp = self.prev_section_pitches if ab == 0 else None
                    ab_key = self._key_for_beat(ab)
                    new_bs = evaluate_beat(
                        self.grid, ab,
                        self.chord_plan[ab] if ab < len(self.chord_plan) else None,
                        ab_key, self.total_beats, self.subject_beats, psp)
                    new_total = LexScore(
                        new_total.level0_fatal - old_bs.level0_fatal + new_bs.level0_fatal,
                        new_total.level1_harmony - old_bs.level1_harmony + new_bs.level1_harmony,
                        new_total.level2_melody - old_bs.level2_melody + new_bs.level2_melody,
                        new_total.level3_aesthetic - old_bs.level3_aesthetic + new_bs.level3_aesthetic,
                    )

                if new_total < best_new_total:
                    best_move = move
                    best_new_total = new_total

                move.undo(self.grid)

            if best_move is not None and best_new_total < total_score:
                # 改善あり: 採用
                best_move.apply(self.grid)
                total_score = best_new_total
                # 影響拍の per_beat を更新
                for ab in [target_beat] + (
                    [target_beat - 1] if target_beat > 0 else []
                ) + (
                    [target_beat + 1] if target_beat + 1 < self.total_beats else []
                ):
                    psp = self.prev_section_pitches if ab == 0 else None
                    ab_key2 = self._key_for_beat(ab)
                    new_bs = evaluate_beat(
                        self.grid, ab,
                        self.chord_plan[ab] if ab < len(self.chord_plan) else None,
                        ab_key2, self.total_beats, self.subject_beats, psp)
                    per_beat[ab] = (ab, new_bs)

                no_improve_count = 0
                if verbose and iteration % 20 == 0:
                    msg = (f"  iter {iteration}: beat {target_beat} "
                           f"→ L0={total_score.level0_fatal} "
                           f"L1={total_score.level1_harmony} "
                           f"L2={total_score.level2_melody}")
                    print(msg)
                    self._iteration_log.append(msg)
            else:
                no_improve_count += 1

        # --- 最終クリーンアップ: L0違反の装飾音を拍頭音で強制置換 ---
        # 「禁止を犯すくらいなら装飾しない」の原則
        cleanup_count = 0
        for beat in range(self.total_beats):
            sb_start = beat * SB
            # この拍の各声部の拍頭音
            head_pitches: Dict[FugueVoiceType, Optional[int]] = {}
            for vt in self.grid:
                head_pitches[vt] = self.grid[vt][sb_start]

            for sb_offset in range(1, SB):  # サブビート1,2,3をチェック
                abs_sb = sb_start + sb_offset
                # 全声部のこのサブビートの音を収集
                sounding = []
                for vt in self.grid:
                    p = self.grid[vt][abs_sb]
                    if p is not None:
                        sounding.append((vt, p))

                # 半音衝突チェック
                has_violation = False
                for ii in range(len(sounding)):
                    for jj in range(ii + 1, len(sounding)):
                        diff = abs(sounding[ii][1] - sounding[jj][1])
                        if diff == 1 or diff == 11:
                            pc_pair = {sounding[ii][1] % 12, sounding[jj][1] % 12}
                            cleanup_key = self._key_for_beat(beat)
                            leading = (cleanup_key.tonic_pc - 1) % 12
                            if pc_pair == {leading, cleanup_key.tonic_pc}:
                                # 導音-主音ペア: 和声音考慮で判定
                                if diff > 2:
                                    continue  # 離れた音域は許容
                                cleanup_chord = (self.chord_plan[beat]
                                                 if beat < len(self.chord_plan) else None)
                                if cleanup_chord is not None:
                                    pc_a = sounding[ii][1] % 12
                                    pc_b = sounding[jj][1] % 12
                                    a_in = pc_a in cleanup_chord.tones
                                    b_in = pc_b in cleanup_chord.tones
                                    if a_in == b_in:
                                        continue  # 両方和声音 or 両方非和声音
                                    # 片方のみ和声音 → 衝突
                                else:
                                    continue  # コード不明 → 許容
                            has_violation = True
                            break
                    if has_violation:
                        break

                if has_violation:
                    # 装飾音（拍頭と異なる音）を拍頭音に戻す
                    for vt, p in sounding:
                        if beat not in self.subject_beats.get(vt, set()):
                            if p != head_pitches[vt] and head_pitches[vt] is not None:
                                self.grid[vt][abs_sb] = head_pitches[vt]
                                cleanup_count += 1

            # サブビート間の平行5度/8度チェック（拍頭と前拍末尾）
            if beat > 0:
                prev_last_sb = sb_start - 1  # 前拍の最終サブビート
                voice_list = list(self.grid.keys())
                for idx_i in range(len(voice_list)):
                    for idx_j in range(idx_i + 1, len(voice_list)):
                        vt_i, vt_j = voice_list[idx_i], voice_list[idx_j]
                        prev_i = self.grid[vt_i][prev_last_sb]
                        prev_j = self.grid[vt_j][prev_last_sb]
                        curr_i = self.grid[vt_i][sb_start]
                        curr_j = self.grid[vt_j][sb_start]
                        if None in (prev_i, prev_j, curr_i, curr_j):
                            continue
                        if prev_i == curr_i or prev_j == curr_j:
                            continue
                        prev_ic = _interval_class(prev_i, prev_j)
                        curr_ic = _interval_class(curr_i, curr_j)
                        if prev_ic == curr_ic and curr_ic in (0, 5):
                            # 前拍最終サブビートの装飾音を拍頭音に戻す
                            prev_beat = beat - 1
                            prev_head_sb = prev_beat * SB
                            for vt in [vt_i, vt_j]:
                                if prev_beat not in self.subject_beats.get(vt, set()):
                                    head_p = self.grid[vt][prev_head_sb]
                                    if (self.grid[vt][prev_last_sb] != head_p
                                            and head_p is not None):
                                        self.grid[vt][prev_last_sb] = head_p
                                        cleanup_count += 1

        if cleanup_count > 0 and verbose:
            msg = f"  クリーンアップ: {cleanup_count}個の装飾音を拍頭音に置換"
            print(msg)
            self._iteration_log.append(msg)

        # 最終スコア
        final_score, _ = evaluate_grid(
            self.grid, self.chord_plan, self.key,
            self.total_beats, self.subject_beats,
            self.prev_section_pitches,
            beat_key_map=self.beat_key_map)
        msg = (f"VNS最終スコア: L0={final_score.level0_fatal} "
               f"L1={final_score.level1_harmony} "
               f"L2={final_score.level2_melody} "
               f"L3={final_score.level3_aesthetic}")
        if verbose:
            print(msg)
        self._iteration_log.append(msg)

        return self.grid, self._iteration_log
