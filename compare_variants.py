#!/usr/bin/env python3
"""バリアント比較スクリプト: 異なる和声方針でフーガ生成 → 品質統計の比較

複数の和声方針変種（harmonic policy variants）でN候補を生成し、
品質指標（errors, warnings）を集計・比較するスクリプト。

使用方法:
    python compare_variants.py --num-candidates 50 --seeds-start 42
"""
import sys, os, argparse, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from generate_art_of_fugue import (
    load_models, write_midi, _run_quality_gate,
    ART_OF_FUGUE_NOTES, ART_OF_FUGUE_HARMONY, ART_OF_FUGUE_ANSWER_HARMONY,
    SAMPLE
)
from bach_chord_data import (
    get_bach_progression_as_chord_labels
)

from fugue_structure import Key, Subject, FugueStructure, FugueVoiceType
from fugue_realization import FugueRealizationEngine, ChordLabel
from key_transition_model import KeyTransitionModel, MarkovKeyPathStrategy
from typing import List, Callable, Optional, Tuple, Dict, Any


def variant_bach_raw(progression: Optional[List[ChordLabel]]) -> Optional[List[ChordLabel]]:
    """バリアント1: 生のバッハMIDI抽出（修正なし）"""
    return progression


def variant_bach_v_fixed(progression: Optional[List[ChordLabel]]) -> Optional[List[ChordLabel]]:
    """バリアント2: V終止補正版（if関数が存在する場合）

    assume get_bach_progression_v_fixed() exists in bach_chord_data
    """
    if progression is None:
        return None
    # 試しに関数を呼び出す、なければ元の進行を返す
    try:
        from bach_chord_data import get_bach_progression_v_fixed
        return get_bach_progression_v_fixed()
    except (ImportError, AttributeError):
        # 関数が存在しない場合は、生の進行を返す
        return progression


def variant_template_only(_progression: Optional[List[ChordLabel]]) -> Optional[List[ChordLabel]]:
    """バリアント3: テンプレートのみ（参照進行なし）

    reference_progression=None を使用することで、
    手作業テンプレートに基づく和声計画のみを使用する
    """
    return None


VARIANTS = {
    "template_only": variant_template_only,
    "bach_raw": variant_bach_raw,
    "bach_v_fixed": variant_bach_v_fixed,
}


def generate_fugue_with_variant(
    variant_name: str,
    chord_model, cp_model, key_model,
    structure: FugueStructure,
    key: Key,
    seed: int,
) -> Tuple[Dict[str, Any], Any, Any]:
    """1つのバリアント・seedで1フーガを生成

    Returns:
        (stats_dict, full_midi, engine)
        stats_dict: {"errors": int, "warnings": int, "seed": int}
    """
    # 和声方針を適用
    variant_fn = VARIANTS[variant_name]
    bach_prog = get_bach_progression_as_chord_labels()
    reference_progression = variant_fn(bach_prog)

    # フーガ生成エンジンを実行
    markov_strategy = (
        MarkovKeyPathStrategy(key_model, seed=seed)
        if key_model and key_model.num_transitions > 0
        else None
    )

    engine = FugueRealizationEngine(
        structure,
        seed=seed,
        chord_model=chord_model,
        counterpoint_model=cp_model,
        elaborate=False,
        reference_progression=reference_progression,
    )

    full_midi = engine.realize_fugue(key_path_strategy=markov_strategy)

    # 品質チェック
    report = _run_quality_gate(full_midi, key, engine)
    n_err = len(report.errors)
    n_warn = len(report.warnings)

    stats = {
        "errors": n_err,
        "warnings": n_warn,
        "seed": seed,
    }

    return stats, full_midi, engine


def run_variant_comparison(
    num_candidates: int = 50,
    seeds_start: int = 42,
    verbose: bool = False,
) -> Dict[str, Any]:
    """全バリアントで比較実験を実行

    Args:
        num_candidates: 各バリアントあたりの生成候補数
        seeds_start: 乱数シード開始値
        verbose: 進捗詳細出力

    Returns:
        {variant_name: {
            "errors_0_count": int,
            "best_errors": int,
            "best_warnings": int,
            "avg_errors": float,
            "all_results": [(errors, warnings, seed, midi, engine), ...]
        }}
    """
    print(f"\n{'='*70}")
    print(f"  バリアント比較実験開始（N={num_candidates}）")
    print(f"{'='*70}")

    # モデル読み込み
    print("\n  モデル読み込み中...")
    chord_model, cp_model, key_model = load_models()

    # フーガ構造を構築（全バリアント共通）
    key = SAMPLE["key"]
    subject = Subject(
        ART_OF_FUGUE_NOTES, key, "Art of Fugue grundthema",
        harmonic_template=ART_OF_FUGUE_HARMONY,
        answer_harmonic_template=ART_OF_FUGUE_ANSWER_HARMONY
    )
    structure = FugueStructure(
        num_voices=4,
        main_key=key,
        subject=subject,
        entry_overlap=1
    )
    print(f"  主題: {len(subject.notes)}音, {subject.get_length()}拍")

    results = {}

    # 各バリアントを実行
    for variant_name in sorted(VARIANTS.keys()):
        print(f"\n  【{variant_name}】バリアント: {num_candidates}候補生成")
        candidates = []

        for i in range(num_candidates):
            seed = seeds_start + i

            try:
                stats, full_midi, engine = generate_fugue_with_variant(
                    variant_name, chord_model, cp_model, key_model,
                    structure, key, seed
                )

                candidates.append(
                    (stats["errors"], stats["warnings"], seed, full_midi, engine)
                )

                # 進捗表示（10候補ごと）
                if (i + 1) % 10 == 0 or i == num_candidates - 1:
                    ok_count = sum(1 for c in candidates if c[0] == 0)
                    print(f"    ... {i+1}/{num_candidates} 完了"
                          f" (errors=0: {ok_count})"
                    )

            except Exception as e:
                if verbose:
                    print(f"    警告: seed={seed}で生成失敗: {e}")
                candidates.append((999, 999, seed, None, None))

        # 統計を集計
        valid_candidates = [c for c in candidates if c[3] is not None]
        errors_0_count = sum(1 for c in valid_candidates if c[0] == 0)

        all_errors = [c[0] for c in valid_candidates if c[0] < 999]
        all_warnings = [c[1] for c in valid_candidates if c[0] < 999]

        avg_errors = statistics.mean(all_errors) if all_errors else 0.0

        # best を決定
        if valid_candidates:
            # errors < 999 のもののみを考慮
            valid = [c for c in valid_candidates if c[0] < 999]
            if valid:
                valid.sort(key=lambda c: (c[0], c[1]))  # errors最少 → warnings最少
                best = valid[0]
                best_errors = best[0]
                best_warnings = best[1]
            else:
                best = valid_candidates[0]
                best_errors = 999
                best_warnings = 999
        else:
            best = None
            best_errors = 999
            best_warnings = 999

        results[variant_name] = {
            "errors_0_count": errors_0_count,
            "best_errors": best_errors,
            "best_warnings": best_warnings,
            "avg_errors": avg_errors,
            "all_results": candidates,
            "best_candidate": best,
        }

    return results


def print_comparison_table(results: Dict[str, Any], num_candidates: int):
    """比較テーブルを出力"""
    print(f"\n{'='*70}")
    print(f"=== バリアント比較 (N={num_candidates}) ===")
    print(f"{'='*70}\n")

    # テーブルヘッダ
    print(f"{'Variant':<20} | {'errors=0':>8} | {'best_err':>8} | {'best_warn':>9} | {'avg_err':>8}")
    print("-" * 70)

    # 各行
    for variant_name in sorted(results.keys()):
        data = results[variant_name]
        variant_display = variant_name.replace("_", " ")

        print(
            f"{variant_display:<20} | {data['errors_0_count']:>8} | "
            f"{data['best_errors']:>8} | {data['best_warnings']:>9} | "
            f"{data['avg_errors']:>8.1f}"
        )

    print()


def save_best_midis(results: Dict[str, Any], output_dir: str):
    """各バリアントの最良MIDIを保存"""
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n{'='*70}")
    print(f"  最良MIDI生成・保存")
    print(f"{'='*70}\n")

    for variant_name in sorted(results.keys()):
        data = results[variant_name]
        best = data["best_candidate"]

        if best and best[3] is not None:  # full_midi が存在
            out_path = os.path.join(output_dir, f"variant_{variant_name}.mid")
            write_midi(best[3], out_path, tempo=60)
            print(f"  ✓ {variant_name}: {out_path}")
            print(f"    (seed={best[2]}, errors={best[0]}, warnings={best[1]})")
        else:
            print(f"  ✗ {variant_name}: 有効なMIDIがありません")


def main():
    parser = argparse.ArgumentParser(
        description="異なる和声方針でフーガを生成し品質を比較"
    )
    parser.add_argument(
        "--num-candidates", type=int, default=50,
        help="各バリアントあたりの生成候補数（デフォルト: 50）"
    )
    parser.add_argument(
        "--seeds-start", type=int, default=42,
        help="乱数シード開始値（デフォルト: 42）"
    )
    parser.add_argument(
        "--output-dir", type=str,
        default="/sessions/fervent-vigilant-hypatia/mnt/fuge",
        help="出力ディレクトリ（デフォルト: /sessions/.../mnt/fuge）"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="詳細な進捗出力"
    )

    args = parser.parse_args()

    # 比較実験を実行
    results = run_variant_comparison(
        num_candidates=args.num_candidates,
        seeds_start=args.seeds_start,
        verbose=args.verbose,
    )

    # テーブルを出力
    print_comparison_table(results, args.num_candidates)

    # 最良MIDIを保存
    save_best_midis(results, args.output_dir)

    print(f"\n{'='*70}")
    print(f"  バリアント比較完了")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
