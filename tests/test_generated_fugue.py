"""
生成フーガの完全規則チェック
Complete Rule Verification for Generated Fugue

生成されたフーガが古典和声学のすべての規則を守っているかチェック
"""

from voice_leading_fugue_gen import VoiceLeadingGenerator, Voice
from harmony_rules_complete import HarmonyRules, Pitch, ScaleDegree


def test_generated_fugue():
    """生成されたフーガを全規則でテスト"""
    
    print("=" * 70)
    print("生成フーガの完全規則チェック")
    print("=" * 70)
    
    # フーガを生成
    generator = VoiceLeadingGenerator(tonic_pc=0)
    generator.generate(num_chords=8)
    
    rules = HarmonyRules()
    
    total_checks = 0
    violations = []
    
    print("\n【規則チェック開始】")
    
    # ============================================================
    # 1. 声部音域チェック
    # ============================================================
    
    print("\n1. 声部音域チェック...")
    for voice in Voice:
        for i, midi in enumerate(generator.voices[voice]):
            total_checks += 1
            valid, msg = rules.check_voice_range(Pitch(midi), voice.value)
            if not valid:
                violations.append(f"  拍{i} {voice.value}: {msg}")
    
    if not violations:
        print("  ✓ 全ての音が適切な音域内")
    
    # ============================================================
    # 2. 声部交差チェック
    # ============================================================
    
    print("\n2. 声部交差チェック...")
    num_positions = len(generator.voices[Voice.SOPRANO])
    
    for i in range(num_positions):
        total_checks += 1
        voice_dict = {
            "soprano": Pitch(generator.voices[Voice.SOPRANO][i]),
            "alto": Pitch(generator.voices[Voice.ALTO][i]),
            "bass": Pitch(generator.voices[Voice.BASS][i])
        }
        
        valid, msg = rules.check_voice_crossing(voice_dict)
        if not valid:
            violations.append(f"  拍{i}: {msg}")
    
    if len(violations) == 0:
        print("  ✓ 声部交差なし")
    
    # ============================================================
    # 3. 声部間隔チェック
    # ============================================================
    
    print("\n3. 声部間隔チェック...")
    for i in range(num_positions):
        total_checks += 1
        voice_dict = {
            "soprano": Pitch(generator.voices[Voice.SOPRANO][i]),
            "alto": Pitch(generator.voices[Voice.ALTO][i])
        }
        
        valid, msg = rules.check_spacing(voice_dict)
        if not valid:
            violations.append(f"  拍{i}: {msg}")
    
    if len(violations) == 0:
        print("  ✓ 声部間隔適切（1オクターブ以内）")
    
    # ============================================================
    # 4. 平行5度・8度チェック
    # ============================================================
    
    print("\n4. 平行5度・8度チェック...")
    for i in range(num_positions - 1):
        # 全ての声部ペアをチェック
        voices_list = [Voice.SOPRANO, Voice.ALTO, Voice.BASS]
        
        for j in range(len(voices_list)):
            for k in range(j + 1, len(voices_list)):
                total_checks += 1
                v1 = voices_list[j]
                v2 = voices_list[k]
                
                prev1 = Pitch(generator.voices[v1][i])
                curr1 = Pitch(generator.voices[v1][i + 1])
                prev2 = Pitch(generator.voices[v2][i])
                curr2 = Pitch(generator.voices[v2][i + 1])
                
                valid, msg = rules.check_parallel_perfect(
                    prev1, curr1, prev2, curr2
                )
                if not valid:
                    violations.append(f"  拍{i}→{i+1} {v1.value}-{v2.value}: {msg}")
    
    if len(violations) == 0:
        print("  ✓ 平行5度・8度なし")
    
    # ============================================================
    # 5. 増音程の旋律的使用チェック
    # ============================================================
    
    print("\n5. 増音程の旋律的使用チェック...")
    for voice in Voice:
        for i in range(num_positions - 1):
            total_checks += 1
            prev = Pitch(generator.voices[voice][i])
            curr = Pitch(generator.voices[voice][i + 1])
            
            valid, msg = rules.check_melodic_augmented_interval(prev, curr)
            if not valid:
                violations.append(f"  拍{i}→{i+1} {voice.value}: {msg}")
    
    if len(violations) == 0:
        print("  ✓ 増音程の旋律的使用なし")
    
    # ============================================================
    # 6. 和声進行チェック
    # ============================================================
    
    print("\n6. 和声進行チェック...")
    for i in range(len(generator.progression) - 1):
        total_checks += 1
        curr_degree = generator.progression[i].degree
        next_degree = generator.progression[i + 1].degree
        
        valid, msg = rules.check_chord_progression(curr_degree, next_degree)
        if not valid:
            violations.append(f"  {i}→{i+1}: {curr_degree.name}→{next_degree.name} {msg}")
    
    if len(violations) == 0:
        print("  ✓ 和声進行は全て妥当")
    
    # ============================================================
    # 7. 和音の完全性チェック（第三音省略なし）
    # ============================================================
    
    print("\n7. 和音の完全性チェック...")
    for i in range(num_positions):
        total_checks += 1
        prog = generator.progression[i]
        
        # その位置で鳴っている音
        pitches = [
            Pitch(generator.voices[Voice.SOPRANO][i]),
            Pitch(generator.voices[Voice.ALTO][i]),
            Pitch(generator.voices[Voice.BASS][i])
        ]
        
        valid, msg = rules.check_chord_doubling(
            pitches,
            list(prog.chord_tones),
            prog.root_pc,
            prog.third_pc,
            prog.fifth_pc
        )
        if not valid:
            violations.append(f"  拍{i}: {msg}")
    
    if len(violations) == 0:
        print("  ✓ 全ての和音が完全（第三音省略なし）")
    
    # ============================================================
    # 結果サマリー
    # ============================================================
    
    print("\n" + "=" * 70)
    print("チェック結果サマリー")
    print("=" * 70)
    print(f"総チェック数: {total_checks}")
    print(f"違反数: {len(violations)}")
    
    if violations:
        print("\n【検出された違反】")
        for v in violations[:20]:  # 最初の20個を表示
            print(v)
        if len(violations) > 20:
            print(f"  ... 他{len(violations) - 20}件")
    
    success_rate = ((total_checks - len(violations)) / total_checks * 100) if total_checks > 0 else 0
    print(f"\n成功率: {success_rate:.1f}%")
    
    if success_rate == 100.0:
        print("\n🎉 完璧！すべての規則を100%遵守しています！")
        return True
    elif success_rate >= 95.0:
        print("\n✓ 優秀：ほぼすべての規則を遵守")
        return True
    else:
        print("\n⚠️ 改善が必要です")
        return False


if __name__ == "__main__":
    success = test_generated_fugue()
    exit(0 if success else 1)
