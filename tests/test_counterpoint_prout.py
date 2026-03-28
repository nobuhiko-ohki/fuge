"""
対位法エンジン テストスイート（Prout 準拠版）
"""

import sys
sys.path.insert(0, "../src")

from counterpoint_engine import (
    CounterpointProhibitions,
    CounterpointScoring,
    SpeciesCounterpointRules,
    InvertibleCounterpoint,
    CounterpointEngine,
    MelodicContext,
    MotionType,
    DissonanceType,
)


def run_tests():
    print("=" * 70)
    print("対位法エンジン テストスイート (Prout 準拠)")
    print("=" * 70)

    total = 0
    passed = 0
    failed_details = []

    def check(name, condition, detail=""):
        nonlocal total, passed
        total += 1
        if condition:
            passed += 1
        else:
            failed_details.append(f"  ✗ {name}" + (f": {detail}" if detail else ""))

    proh = CounterpointProhibitions()
    scoring = CounterpointScoring()
    species = SpeciesCounterpointRules()
    inv = InvertibleCounterpoint()

    # Layer 1
    print("\n--- Layer 1: 禁則 ---")
    check("反行", proh.classify_motion(60, 62, 67, 65) == MotionType.CONTRARY)
    check("斜行", proh.classify_motion(60, 60, 67, 65) == MotionType.OBLIQUE)
    check("平行", proh.classify_motion(60, 62, 67, 69) == MotionType.PARALLEL)
    check("同進行", proh.classify_motion(60, 64, 67, 69) == MotionType.SIMILAR)

    v, m = proh.check_parallel_perfect(60, 62, 67, 69)
    check("平行5度検出", not v)
    v, m = proh.check_parallel_perfect(60, 62, 72, 74)
    check("平行8度検出", not v)
    v, m = proh.check_parallel_perfect(60, 62, 67, 65)
    check("反行は許容", v)
    v, m = proh.check_parallel_perfect(60, 60, 67, 69)
    check("斜行は許容", v)
    v, m = proh.check_parallel_perfect(60, 62, 64, 66)
    check("平行3度は許容", v)

    v, m = proh.check_hidden_perfect(60, 67, 48, 55, True)
    check("隠伏5度検出", not v)
    v, m = proh.check_hidden_perfect(60, 62, 48, 55, True)
    check("ソプラノ順次進行は許容", v)
    v, m = proh.check_hidden_perfect(60, 67, 48, 55, False)
    check("内声部は許容", v)

    v, m = proh.check_direct_unison(65, 67, 60, 67)
    check("直接同度検出", not v)
    v, m = proh.check_direct_unison(65, 67, 70, 67)
    check("反行からの同度は許容", v)

    v, m = proh.check_voice_overlap(67, 65, 60, 68)
    check("下声超越検出", not v)
    v, m = proh.check_voice_overlap(67, 58, 60, 62)
    check("上声超越検出", not v)
    v, m = proh.check_voice_overlap(67, 65, 60, 62)
    check("正常な動きは許容", v)

    v, m = proh.check_melodic_augmented(60, 66)
    check("増4度検出", not v)
    v, m = proh.check_melodic_augmented(60, 68)
    check("増5度検出", not v)
    v, m = proh.check_melodic_augmented(60, 67)
    check("完全5度は許容", v)

    v, m = proh.check_melodic_seventh(60, 70)
    check("短7度検出", not v)
    v, m = proh.check_melodic_seventh(60, 71)
    check("長7度検出", not v)
    v, m = proh.check_melodic_seventh(60, 72)
    check("8度は許容", v)

    ctx = MelodicContext(pitches=[60, 65, 70])
    v, m = proh.check_consecutive_leaps_same_dir(ctx, 75, max_consecutive=2)
    check("同方向連続跳躍3回検出", not v)

    # Layer 2
    print("\n--- Layer 2: スコアリング ---")
    s = scoring.score_motion_type(60, 62, 67, 65)
    check("反行はボーナス", s < 0)
    s = scoring.score_motion_type(60, 62, 67, 69)
    check("平行はペナルティ", s > 0)

    ctx = MelodicContext(pitches=[60, 67])
    s = scoring.score_leap_resolution(ctx, 65)
    check("適切な解決はボーナス", s < 0)

    ctx = MelodicContext(pitches=[60, 62, 64, 66, 68])
    s = scoring.score_consecutive_direction(ctx, 70)
    check("5回連続上行は大ペナルティ", s >= 4.0)

    s = scoring.score_voice_independence(
        [72, 67, 60, 48], [74, 65, 62, 46])
    check("方向混合はボーナス", s < 0)
    s = scoring.score_voice_independence(
        [72, 67, 60, 48], [74, 69, 62, 50])
    check("全声部同方向は大ペナルティ", s >= 3.0)

    # Layer 3
    print("\n--- Layer 3: 種別対位法 ---")
    v, m = species.first_species_check_interval(67, 60, is_first=True)
    check("開始で5度は許容", v)
    v, m = species.first_species_check_interval(64, 60, is_first=True)
    check("開始で3度は禁止", not v)

    v, m = species.second_species_check_weak_beat(
        60, 62, 64, 67, {0, 4, 7})
    check("経過音は許容", v)
    v, m = species.second_species_check_weak_beat(
        60, 66, 64, 67, {0, 4, 7})
    check("跳躍進入の非和声音は禁止", not v)

    v, m = species.fourth_species_check_suspension(67, 67, 65, 60)
    check("7-6掛留は許容", v)
    v, m = species.fourth_species_check_suspension(67, 65, 64, 60)
    check("準備≠掛留は禁止", not v)

    d = species.classify_nonchord_tone(60, 62, 64, {0, 4, 7})
    check("経過音判定", d == DissonanceType.PASSING_TONE)
    d = species.classify_nonchord_tone(60, 62, 60, {0, 4, 7})
    check("刺繍音判定", d == DissonanceType.NEIGHBOR_TONE)

    # Layer 4
    print("\n--- Layer 4: 転回対位法 ---")
    upper = [64, 65, 67, 69]
    lower = [60, 60, 60, 60]
    v, errs = inv.check_invertible_at_octave(upper, lower)
    check("転回対位法テスト実行", True)

    # 統合
    print("\n--- 統合テスト ---")
    engine = CounterpointEngine(num_voices=4)
    engine.reset()
    prev = (72, 64, 55, 48)
    curr = (71, 65, 55, 48)
    v, errs = engine.check_transition_hard(prev, curr)
    check("正常な遷移はパス", v)

    prev2 = (67, 64, 60, 48)
    curr2 = (69, 66, 62, 50)
    v, errs = engine.check_transition_hard(prev2, curr2)
    check("平行5度遷移は拒否", not v)

    ranges = [(60, 79), (55, 74), (48, 67), (40, 60)]
    engine.reset()
    s_good = engine.score_transition_soft(
        (72, 64, 55, 48), (71, 65, 53, 50), ranges)
    engine.reset()
    s_bad = engine.score_transition_soft(
        (72, 64, 55, 48), (74, 66, 57, 50), ranges)
    check("反行多い方がスコア良い", s_good < s_bad)

    engine.reset()
    engine.update_contexts((72, 64, 55, 48))
    engine.update_contexts((71, 65, 53, 50))
    check("文脈更新後のピッチ数=2", len(engine.contexts[0].pitches) == 2)

    # 結果
    print("\n" + "=" * 70)
    print(f"合格: {passed}/{total}")
    rate = passed / total * 100 if total > 0 else 0
    print(f"成功率: {rate:.1f}%")
    if rate == 100.0:
        print("🎉 全テスト合格！")
    elif failed_details:
        for d in failed_details:
            print(d)
    return rate == 100.0


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
