"""
収集済み Bach MIDI コーパスの一括解析スクリプト

bach_midi_collector.py で収集した MIDI を
fugue_analyzer.py + corpus_pipeline.py で一括解析し、
ML 用の特徴量データセットを生成する。

出力:
  corpus/analysis/all_features.json     — 全ファイルの特徴量
  corpus/analysis/fugue_features.json   — フーガのみの特徴量
  corpus/analysis/summary.txt           — 解析結果サマリー
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

from midi_reader import MIDIReader, MIDIFile
from fugue_analyzer import (
    analyze_fugue, compute_pcp, estimate_key,
    extract_pitch_intervals,
)
from corpus_pipeline import extract_fugue_features
from bach_midi_collector import classify_bach_midi


def find_all_midis(base_dir: str) -> list:
    """ディレクトリ以下の全 MIDI ファイルのパスを返す。"""
    paths = []
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.lower().endswith(('.mid', '.midi')):
                paths.append(os.path.join(root, f))
    return sorted(paths)


def analyze_all(midi_dir: str, output_dir: str):
    """全 MIDI ファイルを解析して JSON 出力する。"""
    os.makedirs(output_dir, exist_ok=True)

    reader = MIDIReader()
    midi_paths = find_all_midis(midi_dir)
    print(f"MIDI ファイル数: {len(midi_paths)}")

    all_results = []
    errors = []
    t0 = time.time()

    for i, path in enumerate(midi_paths):
        filename = os.path.basename(path)
        relpath = os.path.relpath(path, midi_dir)

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            print(f"  進捗: {i+1}/{len(midi_paths)} ({elapsed:.0f}s)")

        try:
            midi = reader.read(path)
        except Exception as e:
            errors.append((filename, str(e)))
            continue

        # 分類
        classification = classify_bach_midi(filename)

        try:
            feat = extract_fugue_features(
                midi,
                filename=filename,
                fugue_id=relpath,
                num_voices=None,
            )
            result = feat.to_dict()
            # 分類情報を追加
            result["genre"] = classification["genre"]
            result["collection"] = classification["collection"]
            result["bwv"] = classification["bwv"]
            result["rel_path"] = relpath

            all_results.append(result)
        except Exception as e:
            errors.append((filename, str(e)))
            continue

    elapsed = time.time() - t0
    print(f"\n解析完了: {len(all_results)} 件成功, "
          f"{len(errors)} 件エラー ({elapsed:.1f}s)")

    # 全結果保存
    all_path = os.path.join(output_dir, "all_features.json")
    with open(all_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"全特徴量: {all_path}")

    # フーガのみフィルタ
    fugue_results = [r for r in all_results if r.get("genre") == "fugue"]
    fugue_path = os.path.join(output_dir, "fugue_features.json")
    with open(fugue_path, 'w', encoding='utf-8') as f:
        json.dump(fugue_results, f, ensure_ascii=False, indent=2)
    print(f"フーガ特徴量: {fugue_path} ({len(fugue_results)} 件)")

    # サマリー生成
    summary = generate_summary(all_results, fugue_results, errors, elapsed)
    summary_path = os.path.join(output_dir, "summary.txt")
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary)
    print(f"サマリー: {summary_path}")

    return all_results, fugue_results


def generate_summary(all_results, fugue_results, errors, elapsed):
    """解析結果のサマリーテキストを生成する。"""
    lines = []
    lines.append("=" * 60)
    lines.append("Bach MIDI コーパス解析サマリー")
    lines.append("=" * 60)
    lines.append(f"解析ファイル数: {len(all_results)}")
    lines.append(f"エラー数: {len(errors)}")
    lines.append(f"処理時間: {elapsed:.1f} 秒")
    lines.append("")

    # ジャンル分布
    genres = {}
    for r in all_results:
        g = r.get("genre") or "unknown"
        genres[g] = genres.get(g, 0) + 1
    lines.append("ジャンル分布:")
    for g, n in sorted(genres.items(), key=lambda x: -x[1]):
        lines.append(f"  {g:20s}: {n}")
    lines.append("")

    # 調の分布（全体）
    keys = {}
    for r in all_results:
        k = r.get("global_key", "?")
        keys[k] = keys.get(k, 0) + 1
    lines.append("グローバルキー分布 (上位10):")
    for k, n in sorted(keys.items(), key=lambda x: -x[1])[:10]:
        lines.append(f"  {k:20s}: {n}")
    lines.append("")

    # フーガの統計
    if fugue_results:
        lines.append("-" * 40)
        lines.append(f"フーガ: {len(fugue_results)} 件")
        lines.append("-" * 40)

        # 声部数分布
        voice_counts = {}
        for r in fugue_results:
            v = r.get("num_voices", 0)
            voice_counts[v] = voice_counts.get(v, 0) + 1
        lines.append("声部数分布:")
        for v, n in sorted(voice_counts.items()):
            lines.append(f"  {v} 声: {n}")
        lines.append("")

        # 長さの統計
        beats = [r.get("total_beats", 0) for r in fugue_results]
        if beats:
            lines.append(f"長さ（拍）: "
                         f"min={min(beats):.0f}, "
                         f"max={max(beats):.0f}, "
                         f"平均={sum(beats)/len(beats):.0f}")

        # 調の分布
        fkeys = {}
        for r in fugue_results:
            k = r.get("global_key", "?")
            fkeys[k] = fkeys.get(k, 0) + 1
        lines.append("\nフーガのキー分布:")
        for k, n in sorted(fkeys.items(), key=lambda x: -x[1]):
            lines.append(f"  {k:20s}: {n}")

        # セクション境界数
        boundaries = [len(r.get("boundaries", [])) for r in fugue_results]
        if boundaries:
            lines.append(f"\nセクション境界数: "
                         f"min={min(boundaries)}, "
                         f"max={max(boundaries)}, "
                         f"平均={sum(boundaries)/len(boundaries):.1f}")

    # エラー
    if errors:
        lines.append("")
        lines.append(f"エラー ({len(errors)} 件):")
        for fname, err in errors[:20]:
            lines.append(f"  {fname}: {err}")
        if len(errors) > 20:
            lines.append(f"  ... 他 {len(errors) - 20} 件")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Bach MIDI コーパス一括解析")
    parser.add_argument(
        '--midi-dir', '-i',
        default='./corpus/bach_midi',
        help='MIDI ディレクトリ')
    parser.add_argument(
        '--output-dir', '-o',
        default='./corpus/analysis',
        help='出力ディレクトリ')
    args = parser.parse_args()

    analyze_all(args.midi_dir, args.output_dir)
