"""
フーガ解析モジュール — Bach WTC コーパス解析基盤

MIDIファイルからフーガの構造的特徴を抽出する。
ML学習データ生成のための前処理パイプライン。

解析機能:
  1. ビート単位のピッチクラスプロファイル (PCP)
  2. 調推定（Krumhansl-Schmuckler アルゴリズム）
  3. 声部分離（ピッチ域・時間的連続性）
  4. 主題検出（パターンマッチング）
  5. セクション境界推定（テクスチャ・調変化）

設計方針:
  - 各解析ステップは独立して使用可能
  - 結果は辞書/リスト形式で返す（ML前処理との接続性）
  - fugue_structure.py の Key クラスとの互換性を維持
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional, Sequence
import math

from midi_reader import MIDIFile, MIDINote


# ============================================================
# ピッチクラスプロファイル (PCP)
# ============================================================

def compute_pcp(notes: List[MIDINote],
                start_tick: int, end_tick: int,
                weighted: bool = True) -> List[float]:
    """指定区間のピッチクラスプロファイルを計算する。

    Args:
        notes: MIDINote のリスト（時刻順）
        start_tick: 区間開始 tick
        end_tick: 区間終了 tick
        weighted: True なら音符長で重み付け

    Returns:
        12要素のリスト [C, C#, D, ..., B] 各値は 0.0〜1.0（正規化済み）
    """
    pcp = [0.0] * 12

    for note in notes:
        # 区間外はスキップ
        if note.end_tick <= start_tick or note.start_tick >= end_tick:
            continue

        # 区間内の実効時間
        eff_start = max(note.start_tick, start_tick)
        eff_end = min(note.end_tick, end_tick)
        duration = eff_end - eff_start

        if duration <= 0:
            continue

        pc = note.pitch % 12
        if weighted:
            pcp[pc] += duration
        else:
            pcp[pc] += 1.0

    # 正規化
    total = sum(pcp)
    if total > 0:
        pcp = [v / total for v in pcp]

    return pcp


def compute_pcp_sequence(midi: MIDIFile,
                         beat_resolution: float = 1.0,
                         weighted: bool = True
                         ) -> List[List[float]]:
    """ビート単位の PCP 系列を計算する。

    Args:
        midi: MIDIFile オブジェクト
        beat_resolution: 何拍ごとに PCP を計算するか（デフォルト 1.0 = 1拍）
        weighted: 音符長による重み付け

    Returns:
        PCP のリスト。各要素は 12次元ベクトル。
    """
    all_notes = midi.all_notes
    if not all_notes:
        return []

    tpb = midi.ticks_per_beat
    tick_step = int(tpb * beat_resolution)
    total_ticks = midi.duration_ticks

    pcps = []
    t = 0
    while t < total_ticks:
        pcp = compute_pcp(all_notes, t, t + tick_step, weighted)
        pcps.append(pcp)
        t += tick_step

    return pcps


# ============================================================
# 調推定 (Key Estimation) — Krumhansl-Schmuckler
# ============================================================

# Krumhansl-Kessler のキープロファイル（1990）
# C major / C minor のテンプレート
MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]

MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

# 12の長調キー名 (C=0)
MAJOR_KEY_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F',
                   'F#', 'G', 'Ab', 'A', 'Bb', 'B']
MINOR_KEY_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F',
                   'F#', 'G', 'G#', 'A', 'Bb', 'B']


def _rotate(profile: List[float], shift: int) -> List[float]:
    """プロファイルを shift だけ巡回シフトする。"""
    n = len(profile)
    shift = shift % n
    return profile[-shift:] + profile[:-shift]


def _pearson_correlation(x: List[float], y: List[float]) -> float:
    """ピアソン相関係数を計算する。"""
    n = len(x)
    if n == 0:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    sx = [xi - mx for xi in x]
    sy = [yi - my for yi in y]
    num = sum(a * b for a, b in zip(sx, sy))
    denom_x = math.sqrt(sum(a * a for a in sx))
    denom_y = math.sqrt(sum(b * b for b in sy))
    if denom_x * denom_y == 0:
        return 0.0
    return num / (denom_x * denom_y)


@dataclass
class KeyEstimate:
    """調推定の結果"""
    tonic: int          # ピッチクラス (0=C)
    mode: str           # 'major' or 'minor'
    correlation: float  # 相関係数（確信度）
    key_name: str       # 例: "G major", "A minor"

    @property
    def tonic_name(self) -> str:
        if self.mode == 'major':
            return MAJOR_KEY_NAMES[self.tonic]
        return MINOR_KEY_NAMES[self.tonic]


def estimate_key(pcp: List[float]) -> KeyEstimate:
    """PCP から調を推定する（Krumhansl-Schmuckler アルゴリズム）。

    24の調（12長調 + 12短調）との相関を計算し、
    最も相関の高い調を返す。

    Args:
        pcp: 12次元のピッチクラスプロファイル

    Returns:
        KeyEstimate（最良の推定結果）
    """
    best_corr = -2.0
    best_tonic = 0
    best_mode = 'major'

    for shift in range(12):
        # 長調
        profile = _rotate(MAJOR_PROFILE, shift)
        corr = _pearson_correlation(pcp, profile)
        if corr > best_corr:
            best_corr = corr
            best_tonic = shift
            best_mode = 'major'

        # 短調
        profile = _rotate(MINOR_PROFILE, shift)
        corr = _pearson_correlation(pcp, profile)
        if corr > best_corr:
            best_corr = corr
            best_tonic = shift
            best_mode = 'minor'

    if best_mode == 'major':
        name = f"{MAJOR_KEY_NAMES[best_tonic]} major"
    else:
        name = f"{MINOR_KEY_NAMES[best_tonic]} minor"

    return KeyEstimate(
        tonic=best_tonic,
        mode=best_mode,
        correlation=best_corr,
        key_name=name,
    )


def estimate_key_sequence(midi: MIDIFile,
                          window_beats: float = 4.0,
                          hop_beats: float = 1.0
                          ) -> List[Tuple[float, KeyEstimate]]:
    """スライディングウィンドウで調の推移を推定する。

    Args:
        midi: MIDIFile
        window_beats: 推定ウィンドウの幅（拍）
        hop_beats: ウィンドウの移動幅（拍）

    Returns:
        [(beat_position, KeyEstimate), ...] のリスト
    """
    all_notes = midi.all_notes
    if not all_notes:
        return []

    tpb = midi.ticks_per_beat
    window_ticks = int(tpb * window_beats)
    hop_ticks = int(tpb * hop_beats)
    total_ticks = midi.duration_ticks

    result = []
    t = 0
    while t + window_ticks <= total_ticks:
        pcp = compute_pcp(all_notes, t, t + window_ticks, weighted=True)
        key_est = estimate_key(pcp)
        beat_pos = t / tpb
        result.append((beat_pos, key_est))
        t += hop_ticks

    return result


# ============================================================
# 声部分離 (Voice Separation)
# ============================================================

@dataclass
class VoiceStream:
    """分離された声部"""
    voice_id: int
    notes: List[MIDINote] = field(default_factory=list)

    @property
    def pitch_range(self) -> Tuple[int, int]:
        if not self.notes:
            return (0, 0)
        pitches = [n.pitch for n in self.notes]
        return (min(pitches), max(pitches))

    @property
    def mean_pitch(self) -> float:
        if not self.notes:
            return 60.0
        return sum(n.pitch for n in self.notes) / len(self.notes)


def separate_voices_by_channel(midi: MIDIFile) -> List[VoiceStream]:
    """チャンネル別に声部分離する（最も単純な方法）。

    チャンネルが声部を表す MIDI（自作の生成出力など）向け。
    """
    voices_dict = midi.get_voices()
    streams = []
    for i, (ch, notes) in enumerate(sorted(voices_dict.items())):
        streams.append(VoiceStream(voice_id=i, notes=sorted(
            notes, key=lambda n: n.start_tick)))
    return streams


def separate_voices_by_pitch(notes: List[MIDINote],
                             num_voices: int = 4,
                             max_gap_ticks: int = 480
                             ) -> List[VoiceStream]:
    """ピッチの連続性に基づいて声部分離する。

    単一チャンネル MIDI（ピアノ曲など）向けの近似的声部分離。
    貪欲法で「最も近いピッチの声部」にノートを割り当てる。

    Args:
        notes: 全ノート（時刻順）
        num_voices: 分離する声部数
        max_gap_ticks: この tick 以上離れたノートは連続性を無視

    Returns:
        VoiceStream のリスト（高い声部から順）
    """
    if not notes:
        return [VoiceStream(voice_id=i) for i in range(num_voices)]

    sorted_notes = sorted(notes, key=lambda n: (n.start_tick, -n.pitch))

    streams = [VoiceStream(voice_id=i) for i in range(num_voices)]
    # 各声部の最後のノート
    last_pitch = [0.0] * num_voices
    last_end = [0] * num_voices

    for note in sorted_notes:
        best_voice = -1
        best_cost = float('inf')

        for v in range(num_voices):
            if not streams[v].notes:
                # 空の声部 — ピッチ順に初期割り当て
                cost = 0.0
            else:
                gap = note.start_tick - last_end[v]
                if gap < 0:
                    # 声部が既に使用中（同時発音）→ 高コスト
                    cost = 1000.0 + abs(note.pitch - last_pitch[v])
                elif gap > max_gap_ticks:
                    # 長い休符後 — ピッチ差のみ
                    cost = abs(note.pitch - last_pitch[v])
                else:
                    # 通常：ピッチ差 + 時間的近さ
                    cost = abs(note.pitch - last_pitch[v]) + gap * 0.001

            if cost < best_cost:
                best_cost = cost
                best_voice = v

        streams[best_voice].notes.append(note)
        last_pitch[best_voice] = note.pitch
        last_end[best_voice] = note.end_tick

    # ピッチの高い順にソート
    streams.sort(key=lambda s: -s.mean_pitch)
    for i, s in enumerate(streams):
        s.voice_id = i

    return streams


# ============================================================
# 主題検出 (Subject Detection)
# ============================================================

def extract_pitch_intervals(notes: List[MIDINote]) -> List[int]:
    """ノート列からピッチ音程列を抽出する。"""
    intervals = []
    for i in range(1, len(notes)):
        intervals.append(notes[i].pitch - notes[i - 1].pitch)
    return intervals


def extract_rhythm_ratios(notes: List[MIDINote]) -> List[float]:
    """ノート列からリズム比列を抽出する。

    各ノートの長さを直前のノートの長さで割った比。
    """
    ratios = []
    for i in range(1, len(notes)):
        prev_dur = notes[i - 1].duration_tick
        curr_dur = notes[i].duration_tick
        if prev_dur > 0:
            ratios.append(curr_dur / prev_dur)
        else:
            ratios.append(1.0)
    return ratios


def find_pattern_occurrences(
    all_notes: List[MIDINote],
    pattern_intervals: List[int],
    tolerance: int = 0,
) -> List[int]:
    """音程パターンの出現位置を検索する。

    Args:
        all_notes: 検索対象のノート列（時刻順）
        pattern_intervals: 検索パターン（音程列）
        tolerance: 半音単位の許容誤差（0 = 完全一致）

    Returns:
        マッチした開始ノートのインデックスのリスト
    """
    pat_len = len(pattern_intervals)
    if pat_len == 0 or len(all_notes) < pat_len + 1:
        return []

    matches = []
    for i in range(len(all_notes) - pat_len):
        match = True
        for j in range(pat_len):
            actual = all_notes[i + j + 1].pitch - all_notes[i + j].pitch
            expected = pattern_intervals[j]
            if abs(actual - expected) > tolerance:
                match = False
                break
        if match:
            matches.append(i)

    return matches


# ============================================================
# セクション境界推定
# ============================================================

@dataclass
class SectionBoundary:
    """セクション境界"""
    beat: float
    confidence: float  # 0.0〜1.0
    reason: str        # "key_change", "texture_change", "silence" etc.


def detect_key_changes(key_sequence: List[Tuple[float, KeyEstimate]],
                       min_stable_beats: int = 2
                       ) -> List[SectionBoundary]:
    """調推定系列からキー変化点を検出する。

    連続する推定結果が異なる調を示す箇所を境界とみなす。

    Args:
        key_sequence: estimate_key_sequence() の出力
        min_stable_beats: この拍数以上同じ調が続いた場合に「安定」とみなす

    Returns:
        SectionBoundary のリスト
    """
    if len(key_sequence) < 2:
        return []

    boundaries = []
    current_key = key_sequence[0][1].key_name
    stable_count = 1

    for i in range(1, len(key_sequence)):
        beat, est = key_sequence[i]
        if est.key_name == current_key:
            stable_count += 1
        else:
            if stable_count >= min_stable_beats:
                # 安定した調からの変化 → 境界
                boundaries.append(SectionBoundary(
                    beat=beat,
                    confidence=min(est.correlation, 0.99),
                    reason=f"key_change: {current_key} → {est.key_name}",
                ))
            current_key = est.key_name
            stable_count = 1

    return boundaries


def detect_texture_changes(
    midi: MIDIFile,
    beat_resolution: float = 1.0,
    threshold: float = 0.5,
) -> List[SectionBoundary]:
    """テクスチャ変化（声部数・音密度の変化）を検出する。

    各ビートの同時発音数を数え、急激な変化を境界候補とする。

    Args:
        midi: MIDIFile
        beat_resolution: 分析単位（拍）
        threshold: 変化率の閾値

    Returns:
        SectionBoundary のリスト
    """
    all_notes = midi.all_notes
    if not all_notes:
        return []

    tpb = midi.ticks_per_beat
    tick_step = int(tpb * beat_resolution)
    total_ticks = midi.duration_ticks

    # 各ビートの発音数を数える
    densities = []
    t = 0
    while t < total_ticks:
        count = 0
        for note in all_notes:
            if note.start_tick < t + tick_step and note.end_tick > t:
                count += 1
        densities.append(count)
        t += tick_step

    # 変化率を計算
    boundaries = []
    for i in range(1, len(densities)):
        prev = max(densities[i - 1], 1)
        curr = densities[i]
        change = abs(curr - prev) / prev
        if change >= threshold:
            boundaries.append(SectionBoundary(
                beat=i * beat_resolution,
                confidence=min(change, 1.0),
                reason=f"texture_change: {densities[i-1]}→{curr} voices",
            ))

    return boundaries


def detect_silences(midi: MIDIFile,
                    min_silence_ticks: int = 240
                    ) -> List[SectionBoundary]:
    """全声部が休符になる箇所を検出する。

    Args:
        midi: MIDIFile
        min_silence_ticks: 最小休符長（tick）

    Returns:
        SectionBoundary のリスト
    """
    all_notes = midi.all_notes
    if not all_notes:
        return []

    # ノートの「被覆」を計算
    events = []
    for note in all_notes:
        events.append((note.start_tick, 1))   # ノートオン
        events.append((note.end_tick, -1))     # ノートオフ
    events.sort()

    tpb = midi.ticks_per_beat
    boundaries = []
    active = 0
    silence_start = None

    for tick, delta in events:
        active += delta
        if active == 0 and silence_start is None:
            silence_start = tick
        elif active > 0 and silence_start is not None:
            silence_len = tick - silence_start
            if silence_len >= min_silence_ticks:
                beat = silence_start / tpb
                boundaries.append(SectionBoundary(
                    beat=beat,
                    confidence=min(silence_len / tpb, 1.0),
                    reason=f"silence: {silence_len/tpb:.1f} beats",
                ))
            silence_start = None

    return boundaries


# ============================================================
# 統合解析 (Full Analysis)
# ============================================================

@dataclass
class FugueAnalysis:
    """フーガ解析の全結果を格納する"""
    # 基本情報
    filename: str = ""
    num_voices: int = 0
    total_beats: float = 0.0
    ticks_per_beat: int = 480
    tempo_bpm: int = 120

    # ビートごとの調推定
    key_sequence: List[Tuple[float, KeyEstimate]] = field(default_factory=list)
    global_key: Optional[KeyEstimate] = None

    # 声部情報
    voices: List[VoiceStream] = field(default_factory=list)

    # セクション境界
    boundaries: List[SectionBoundary] = field(default_factory=list)

    # ビートごとの PCP
    pcp_sequence: List[List[float]] = field(default_factory=list)

    def summary(self) -> str:
        """解析結果の要約を文字列で返す。"""
        lines = [
            f"=== Fugue Analysis: {self.filename} ===",
            f"Voices: {self.num_voices}",
            f"Total: {self.total_beats:.1f} beats @ {self.tempo_bpm} BPM",
        ]
        if self.global_key:
            lines.append(
                f"Global key: {self.global_key.key_name} "
                f"(r={self.global_key.correlation:.3f})")

        if self.voices:
            lines.append("\nVoice ranges:")
            for v in self.voices:
                lo, hi = v.pitch_range
                lines.append(
                    f"  Voice {v.voice_id}: "
                    f"MIDI {lo}-{hi}, {len(v.notes)} notes, "
                    f"mean={v.mean_pitch:.1f}")

        if self.key_sequence:
            lines.append("\nKey changes:")
            prev_key = ""
            for beat, est in self.key_sequence:
                if est.key_name != prev_key:
                    lines.append(
                        f"  beat {beat:6.1f}: {est.key_name} "
                        f"(r={est.correlation:.3f})")
                    prev_key = est.key_name

        if self.boundaries:
            lines.append("\nSection boundaries:")
            for b in self.boundaries:
                lines.append(
                    f"  beat {b.beat:6.1f}: {b.reason} "
                    f"(conf={b.confidence:.2f})")

        return "\n".join(lines)


def analyze_fugue(midi: MIDIFile,
                  filename: str = "",
                  num_voices: Optional[int] = None,
                  key_window_beats: float = 4.0,
                  key_hop_beats: float = 1.0,
                  ) -> FugueAnalysis:
    """MIDIファイルのフーガ解析を実行する。

    Args:
        midi: MIDIFile オブジェクト
        filename: ファイル名（表示用）
        num_voices: 声部数（None なら自動検出）
        key_window_beats: 調推定ウィンドウ幅
        key_hop_beats: 調推定ホップ幅

    Returns:
        FugueAnalysis（全解析結果）
    """
    analysis = FugueAnalysis(
        filename=filename,
        total_beats=midi.duration_beats,
        ticks_per_beat=midi.ticks_per_beat,
        tempo_bpm=midi.get_tempo(),
    )

    # 1. 声部分離
    voices_by_ch = midi.get_voices()
    if len(voices_by_ch) > 1:
        # チャンネル別分離が有効
        analysis.voices = separate_voices_by_channel(midi)
    else:
        # 単一チャンネル → ピッチベース分離
        nv = num_voices or 4
        analysis.voices = separate_voices_by_pitch(
            midi.all_notes, num_voices=nv,
            max_gap_ticks=midi.ticks_per_beat)

    analysis.num_voices = len(analysis.voices)

    # 2. PCP 系列
    analysis.pcp_sequence = compute_pcp_sequence(
        midi, beat_resolution=1.0, weighted=True)

    # 3. グローバルキー推定
    global_pcp = compute_pcp(midi.all_notes, 0, midi.duration_ticks)
    analysis.global_key = estimate_key(global_pcp)

    # 4. ビート単位の調推定
    analysis.key_sequence = estimate_key_sequence(
        midi,
        window_beats=key_window_beats,
        hop_beats=key_hop_beats)

    # 5. セクション境界検出
    key_boundaries = detect_key_changes(analysis.key_sequence)
    texture_boundaries = detect_texture_changes(midi)
    silence_boundaries = detect_silences(midi)

    all_boundaries = key_boundaries + texture_boundaries + silence_boundaries
    all_boundaries.sort(key=lambda b: b.beat)

    # 近接する境界を統合（2拍以内）
    merged = []
    for b in all_boundaries:
        if merged and abs(b.beat - merged[-1].beat) < 2.0:
            # より高い確信度の方を採用
            if b.confidence > merged[-1].confidence:
                merged[-1] = b
        else:
            merged.append(b)

    analysis.boundaries = merged

    return analysis


# ============================================================
# テスト
# ============================================================

if __name__ == "__main__":
    import os
    from midi_reader import MIDIReader

    print("=== Fugue Analyzer テスト ===\n")

    test_path = os.path.join(
        os.path.dirname(__file__), "../sample_fugue_v5.mid")

    if not os.path.exists(test_path):
        print(f"テストファイルが見つかりません: {test_path}")
        print("先に generate_sample_v5.py を実行してください。")
        exit(1)

    reader = MIDIReader()
    midi = reader.read(test_path)

    analysis = analyze_fugue(midi, filename="sample_fugue_v5.mid")
    print(analysis.summary())
