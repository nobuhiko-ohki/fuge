"""
コーパス解析パイプライン

Bach WTC のフーガ MIDI を一括解析し、
ML 学習用の特徴量データを生成する。

パイプライン:
  1. MIDI 読み込み
  2. 調推定（グローバル + ビート単位）
  3. 声部分離
  4. 主題検出（既知の主題パターンとのマッチング）
  5. 特徴量抽出（ML 用）
  6. JSON 出力

設計方針:
  - 各ステップは独立・交換可能
  - 特徴量形式は numpy 不要（plain list/dict）
  - 外部 MIDI ファイルとの差し替え容易
"""

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from midi_reader import MIDIReader, MIDIFile, MIDINote
from fugue_analyzer import (
    analyze_fugue, FugueAnalysis, KeyEstimate,
    compute_pcp, estimate_key,
    extract_pitch_intervals, extract_rhythm_ratios,
    find_pattern_occurrences,
    separate_voices_by_channel, separate_voices_by_pitch,
)


# ============================================================
# 主題特徴量
# ============================================================

@dataclass
class SubjectFeatures:
    """フーガ主題の特徴量"""
    # 基本情報
    fugue_id: str = ""
    key: str = ""
    num_voices: int = 0

    # 音程列
    pitch_intervals: List[int] = field(default_factory=list)
    # 正規化音程列（オクターブ内に正規化）
    normalized_intervals: List[int] = field(default_factory=list)
    # リズム比列
    rhythm_ratios: List[float] = field(default_factory=list)

    # 統計量
    num_notes: int = 0
    duration_beats: float = 0.0
    pitch_range: int = 0     # 音域幅（半音）
    mean_pitch: float = 0.0
    mean_interval: float = 0.0
    interval_variety: int = 0  # 異なる音程の数
    step_ratio: float = 0.0   # 順次進行の割合

    # PCP（主題全体）
    pcp: List[float] = field(default_factory=list)

    # 推定調
    estimated_key: str = ""
    key_correlation: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_subject_features(
    notes: List[MIDINote],
    fugue_id: str = "",
    known_key: str = "",
    num_voices: int = 0,
    ticks_per_beat: int = 480,
) -> SubjectFeatures:
    """MIDINote 列から主題の特徴量を抽出する。

    Args:
        notes: 主題のノート列
        fugue_id: 識別子（例: "wtc1_01"）
        known_key: 既知の調名
        num_voices: 声部数
        ticks_per_beat: 分解能

    Returns:
        SubjectFeatures
    """
    feat = SubjectFeatures(
        fugue_id=fugue_id,
        key=known_key,
        num_voices=num_voices,
    )

    if not notes:
        return feat

    # 基本統計
    feat.num_notes = len(notes)
    total_ticks = notes[-1].end_tick - notes[0].start_tick
    feat.duration_beats = total_ticks / ticks_per_beat

    pitches = [n.pitch for n in notes]
    feat.pitch_range = max(pitches) - min(pitches)
    feat.mean_pitch = sum(pitches) / len(pitches)

    # 音程列
    feat.pitch_intervals = extract_pitch_intervals(notes)
    feat.normalized_intervals = [iv % 12 if iv > 0 else -((-iv) % 12)
                                  for iv in feat.pitch_intervals]
    feat.rhythm_ratios = extract_rhythm_ratios(notes)

    if feat.pitch_intervals:
        feat.mean_interval = (
            sum(abs(iv) for iv in feat.pitch_intervals)
            / len(feat.pitch_intervals))
        feat.interval_variety = len(set(feat.pitch_intervals))
        steps = sum(1 for iv in feat.pitch_intervals if abs(iv) <= 2)
        feat.step_ratio = steps / len(feat.pitch_intervals)

    # PCP
    if notes:
        start = notes[0].start_tick
        end = notes[-1].end_tick
        feat.pcp = compute_pcp(notes, start, end, weighted=True)

        key_est = estimate_key(feat.pcp)
        feat.estimated_key = key_est.key_name
        feat.key_correlation = key_est.correlation

    return feat


# ============================================================
# フーガ全体の特徴量
# ============================================================

@dataclass
class FugueFeatures:
    """フーガ全体の ML 用特徴量"""
    fugue_id: str = ""
    filename: str = ""

    # 基本情報
    global_key: str = ""
    key_correlation: float = 0.0
    num_voices: int = 0
    total_beats: float = 0.0
    tempo_bpm: int = 120

    # 主題関連
    subject_features: Optional[Dict] = None
    subject_occurrences: int = 0  # 主題の出現回数

    # 調性推移
    key_changes: List[Dict] = field(default_factory=list)
    # [(beat, key_name, correlation), ...]

    # ビート単位の PCP 系列
    pcp_sequence: List[List[float]] = field(default_factory=list)

    # 声部情報
    voice_ranges: List[Dict] = field(default_factory=list)

    # セクション境界
    boundaries: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_fugue_features(
    midi: MIDIFile,
    filename: str = "",
    fugue_id: str = "",
    subject_intervals: Optional[List[int]] = None,
    num_voices: Optional[int] = None,
) -> FugueFeatures:
    """MIDIFile からフーガの ML 特徴量を抽出する。

    Args:
        midi: MIDIFile
        filename: ファイル名
        fugue_id: 識別子
        subject_intervals: 既知の主題音程列（主題検出用）
        num_voices: 声部数（None なら自動）

    Returns:
        FugueFeatures
    """
    # 基礎解析
    analysis = analyze_fugue(
        midi, filename=filename,
        num_voices=num_voices,
        key_window_beats=4.0,
        key_hop_beats=1.0)

    feat = FugueFeatures(
        fugue_id=fugue_id,
        filename=filename,
        global_key=analysis.global_key.key_name if analysis.global_key else "",
        key_correlation=(analysis.global_key.correlation
                         if analysis.global_key else 0.0),
        num_voices=analysis.num_voices,
        total_beats=analysis.total_beats,
        tempo_bpm=analysis.tempo_bpm,
        pcp_sequence=analysis.pcp_sequence,
    )

    # 調変化
    prev_key = ""
    for beat, est in analysis.key_sequence:
        if est.key_name != prev_key:
            feat.key_changes.append({
                "beat": beat,
                "key": est.key_name,
                "correlation": round(est.correlation, 4),
            })
            prev_key = est.key_name

    # 声部情報
    for v in analysis.voices:
        lo, hi = v.pitch_range
        feat.voice_ranges.append({
            "voice_id": v.voice_id,
            "low": lo, "high": hi,
            "notes": len(v.notes),
            "mean_pitch": round(v.mean_pitch, 1),
        })

    # セクション境界
    for b in analysis.boundaries:
        feat.boundaries.append({
            "beat": b.beat,
            "confidence": round(b.confidence, 3),
            "reason": b.reason,
        })

    # 主題検出
    if subject_intervals:
        all_notes = midi.all_notes
        matches = find_pattern_occurrences(
            all_notes, subject_intervals, tolerance=0)
        feat.subject_occurrences = len(matches)

    return feat


# ============================================================
# バッチ解析
# ============================================================

def analyze_corpus(
    midi_dir: str,
    metadata: Optional[Dict[str, Dict]] = None,
    output_path: Optional[str] = None,
) -> List[Dict]:
    """ディレクトリ内の全 MIDI ファイルを解析する。

    Args:
        midi_dir: MIDI ファイルのディレクトリ
        metadata: ファイル名→メタデータの辞書
            例: {"wtc1_fugue01.mid": {"key": "C major", "voices": 4, ...}}
        output_path: JSON 出力先（None なら出力しない）

    Returns:
        解析結果の辞書リスト
    """
    reader = MIDIReader()
    results = []

    midi_files = sorted(
        f for f in os.listdir(midi_dir)
        if f.endswith('.mid') or f.endswith('.midi'))

    for filename in midi_files:
        filepath = os.path.join(midi_dir, filename)
        try:
            midi = reader.read(filepath)
        except Exception as e:
            print(f"  [ERROR] {filename}: {e}")
            continue

        meta = (metadata or {}).get(filename, {})
        fugue_id = meta.get("id", os.path.splitext(filename)[0])
        nv = meta.get("voices")
        subj_iv = meta.get("subject_intervals")

        feat = extract_fugue_features(
            midi, filename=filename,
            fugue_id=fugue_id,
            subject_intervals=subj_iv,
            num_voices=nv)

        results.append(feat.to_dict())

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

    return results


# ============================================================
# テスト実行
# ============================================================

if __name__ == "__main__":
    print("=== Corpus Analysis Pipeline テスト ===\n")

    # 1. 主題 MIDI を解析
    midi_dir = os.path.join(os.path.dirname(__file__), "midi")
    if not os.path.exists(midi_dir):
        print("先に create_wtc_subjects.py を実行してください。")
        sys.exit(1)

    # create_wtc_subjects から主題メタデータを取得
    from create_wtc_subjects import WTC1_FUGUES, subject_to_midi_notes

    reader = MIDIReader()
    print("--- 主題の特徴量抽出 ---\n")
    all_subject_features = []

    for num, data in sorted(WTC1_FUGUES.items()):
        filename = f"wtc1_fugue{num:02d}_subject.mid"
        filepath = os.path.join(midi_dir, filename)
        if not os.path.exists(filepath):
            continue

        midi = reader.read(filepath)
        notes = midi.all_notes

        feat = extract_subject_features(
            notes,
            fugue_id=f"wtc1_{num:02d}",
            known_key=data["key"],
            num_voices=data["voices"],
            ticks_per_beat=midi.ticks_per_beat)

        all_subject_features.append(feat)
        print(f"Fugue {num:2d} ({data['key']:12s}): "
              f"{feat.num_notes} notes, {feat.duration_beats:.1f}b, "
              f"range={feat.pitch_range}, "
              f"step%={feat.step_ratio:.0%}, "
              f"est_key={feat.estimated_key}")

    # 2. 生成フーガ（sample_fugue_v5）を解析
    print("\n--- 生成フーガの解析 ---\n")
    sample_path = os.path.join(
        os.path.dirname(__file__), "..", "sample_fugue_v5.mid")
    if os.path.exists(sample_path):
        midi = reader.read(sample_path)
        feat = extract_fugue_features(
            midi, filename="sample_fugue_v5.mid",
            fugue_id="generated_v5")

        print(f"Global key: {feat.global_key} (r={feat.key_correlation:.3f})")
        print(f"Voices: {feat.num_voices}")
        print(f"Total: {feat.total_beats:.1f} beats")
        print(f"Key changes: {len(feat.key_changes)}")
        print(f"Section boundaries: {len(feat.boundaries)}")

    # 3. JSON 出力
    output_json = os.path.join(os.path.dirname(__file__), "analysis_results.json")
    subjects_json = os.path.join(os.path.dirname(__file__), "subject_features.json")

    with open(subjects_json, 'w', encoding='utf-8') as f:
        json.dump([sf.to_dict() for sf in all_subject_features],
                  f, ensure_ascii=False, indent=2)

    print(f"\n主題特徴量を {subjects_json} に出力しました。")
