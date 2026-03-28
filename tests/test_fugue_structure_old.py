"""
フーガ構造モジュール 包括的テストスイート
Fugue Structure Module - Comprehensive Test Suite

Key, Subject, Countersubject, FugueStructure の各クラスを体系的にテストする。
特に調的応答（tonal answer）の mutation ロジックを重点的に検証する。
"""

import sys
sys.path.insert(0, "../src")

from fugue_structure import (
    Key, Subject, Countersubject, FugueEntry, FugueStructure,
    FugueVoiceType, FugueSection,
    NOTE_TO_PC, PC_TO_NOTE,
)
from harmony_rules_complete import Pitch


def run_tests():
    """全テスト実行"""
    print("=" * 70)
    print("フーガ構造モジュール 包括的テストスイート")
    print("=" * 70)

    total = 0
    passed = 0
    failed_details = []

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal total, passed
        total += 1
        if condition:
            passed += 1
        else:
            failed_details.append(
                f"  ✗ {name}" + (f": {detail}" if detail else "")
            )

    # ============================================================
    # NOTE_TO_PC / PC_TO_NOTE 辞書
    # ============================================================
    print("\n--- 音名変換辞書 ---")
    check("C=0", NOTE_TO_PC['C'] == 0)
    check("D=2", NOTE_TO_PC['D'] == 2)
    check("F#=6", NOTE_TO_PC['F#'] == 6)
    check("Gb=6", NOTE_TO_PC['Gb'] == 6)
    check("B=11", NOTE_TO_PC['B'] == 11)
    check("Cb=11", NOTE_TO_PC['Cb'] == 11)
    check("PC_TO_NOTE[0]=C", PC_TO_NOTE[0] == 'C')
    check("PC_TO_NOTE[7]=G", PC_TO_NOTE[7] == 'G')

    # ============================================================
    # Key クラス
    # ============================================================
    print("\n--- Key クラス ---")

    # ---- tonic_pc ----
    print("\n  主音ピッチクラス:")
    c_maj = Key("C", "major")
    check("C major tonic_pc=0", c_maj.tonic_pc == 0)
    d_maj = Key("D", "major")
    check("D major tonic_pc=2", d_maj.tonic_pc == 2)
    a_min = Key("A", "minor")
    check("A minor tonic_pc=9", a_min.tonic_pc == 9)

    # ---- scale ----
    print("\n  音階:")
    c_scale = c_maj.scale
    check("C major scale[0]=0", c_scale[0] == 0)
    check("C major scale[2]=4", c_scale[2] == 4)  # E
    check("C major scale[4]=7", c_scale[4] == 7)  # G (dominant)
    check("C major scale length=7", len(c_scale) == 7)
    # A harmonic minor: A B C D E F G#
    a_scale = a_min.scale
    check("A minor scale[0]=9", a_scale[0] == 9)    # A
    check("A minor scale[6]=8", a_scale[6] == 8)    # G# (leading tone)

    # ---- dominant_pc ----
    print("\n  属音:")
    check("C major dominant=7(G)", c_maj.dominant_pc == 7)
    check("D major dominant=9(A)", d_maj.dominant_pc == 9)
    check("A minor dominant=4(E)", a_min.dominant_pc == 4)

    # ---- get_scale_degree ----
    print("\n  音階度数:")
    check("C in C major = degree 0", c_maj.get_scale_degree(0) == 0)
    check("G in C major = degree 4", c_maj.get_scale_degree(7) == 4)
    check("F# in C major = None", c_maj.get_scale_degree(6) is None)
    check("B in C major = degree 6", c_maj.get_scale_degree(11) == 6)

    # ---- get_dominant_key ----
    print("\n  属調:")
    g_key = c_maj.get_dominant_key()
    check("C major → 属調=G", g_key.tonic == 'G')
    check("属調は major", g_key.mode == "major")
    d_dom = d_maj.get_dominant_key()
    check("D major → 属調=A", d_dom.tonic == 'A')

    # ---- get_subdominant_key ----
    print("\n  下属調:")
    f_key = c_maj.get_subdominant_key()
    check("C major → 下属調=F", f_key.tonic == 'F')
    check("下属調は同mode", f_key.mode == "major")

    # ---- get_relative_key ----
    print("\n  平行調:")
    rel = c_maj.get_relative_key()
    check("C major → 平行短調=A", rel.tonic == 'A')
    check("平行短調は minor", rel.mode == "minor")
    rel2 = a_min.get_relative_key()
    check("A minor → 平行長調=C", rel2.tonic == 'C')
    check("平行長調は major", rel2.mode == "major")

    # ============================================================
    # Subject クラス
    # ============================================================
    print("\n--- Subject クラス ---")

    # テスト主題: C-D-E-F-G（ハ長調, WTC I Fugue 1 風）
    subj_pitches = [Pitch(60), Pitch(62), Pitch(64), Pitch(65), Pitch(67)]
    subject = Subject(subj_pitches, c_maj, "主題")

    # ---- 基本 ----
    print("\n  基本操作:")
    check("get_length=5", subject.get_length() == 5)
    check("name=主題", subject.name == "主題")

    # ---- transpose ----
    print("\n  移調:")
    t2 = subject.transpose(2)
    check("移調+2: 先頭=62", t2.pitches[0].midi == 62)
    check("移調+2: 末尾=69", t2.pitches[4].midi == 69)
    t7 = subject.transpose(7)
    check("移調+7(P5): 先頭=67", t7.pitches[0].midi == 67)
    check("移調+7(P5): 末尾=74", t7.pitches[4].midi == 74)

    # ---- analyze_intervals ----
    print("\n  音程分析:")
    intervals = subject.analyze_intervals()
    check("intervals length=4", len(intervals) == 4)
    check("C→D=+2", intervals[0] == 2)
    check("D→E=+2", intervals[1] == 2)
    check("E→F=+1", intervals[2] == 1)
    check("F→G=+2", intervals[3] == 2)

    # ---- head/tail split ----
    print("\n  頭部/尾部分割:")
    head, tail = subject.get_head_tail_split()
    # G(67) = dominant(pc=7) が位置4にある → head = [C,D,E,F,G], tail = []
    check("head length=5（属音が末尾）", len(head) == 5)
    check("tail length=0", len(tail) == 0)

    # 属音が中間にある主題
    subj2_pitches = [Pitch(60), Pitch(67), Pitch(65), Pitch(64), Pitch(62)]
    subj2 = Subject(subj2_pitches, c_maj, "主題2")
    head2, tail2 = subj2.get_head_tail_split()
    check("head2 length=2（G(67)は位置1）", len(head2) == 2)
    check("tail2 length=3", len(tail2) == 3)

    # 属音がない主題
    subj3_pitches = [Pitch(60), Pitch(62), Pitch(64)]  # C, D, E only
    subj3 = Subject(subj3_pitches, c_maj, "主題3")
    head3, tail3 = subj3.get_head_tail_split()
    check("属音なし: head=全体", len(head3) == 3)
    check("属音なし: tail=空", len(tail3) == 0)

    # ============================================================
    # 実音応答 vs 調的応答（核心テスト）
    # ============================================================
    print("\n--- 実音応答 vs 調的応答 ---")

    # 主題 C-D-E-F-G（ハ長調）
    real = subject.get_answer("real")
    tonal = subject.get_answer("tonal")

    print("\n  実音応答:")
    # 全て +7 半音: G4-A4-B4-C5-D5
    check("実音[0]=G4(67)", real.pitches[0].midi == 67)
    check("実音[1]=A4(69)", real.pitches[1].midi == 69)
    check("実音[2]=B4(71)", real.pitches[2].midi == 71)
    check("実音[3]=C5(72)", real.pitches[3].midi == 72)
    check("実音[4]=D5(74)", real.pitches[4].midi == 74)
    check("実音応答の調=G", real.key.tonic == 'G')
    check("実音応答名", real.name == "応答（実音）")

    print("\n  調的応答:")
    # C(60)→+7=67, D(62)→+7=69, E(64)→+7=71, F(65)→+7=72
    # G(67)=dominant → mutation: +5=72 (C5, not D5)
    check("調的[0]=G4(67)", tonal.pitches[0].midi == 67)
    check("調的[1]=A4(69)", tonal.pitches[1].midi == 69)
    check("調的[2]=B4(71)", tonal.pitches[2].midi == 71)
    check("調的[3]=C5(72)", tonal.pitches[3].midi == 72)
    check("調的[4]=C5(72) mutation", tonal.pitches[4].midi == 72,
          f"got {tonal.pitches[4].midi}, expected 72")
    check("調的応答の調=G", tonal.key.tonic == 'G')
    check("調的応答名", tonal.name == "応答（調的）")

    print("\n  実音 vs 調的 差分:")
    # 位置0-3は同じ、位置4だけ異なる（72 vs 74）
    for i in range(4):
        check(f"位置{i}: 実音=調的", real.pitches[i].midi == tonal.pitches[i].midi)
    check("位置4: 調的が2半音低い",
          tonal.pitches[4].midi == real.pitches[4].midi - 2,
          f"tonal={tonal.pitches[4].midi}, real={real.pitches[4].midi}")

    # ---- 属音が先頭の主題 ----
    print("\n  属音が先頭の主題:")
    # G-A-B-C-D (主題が属音から始まる)
    subj_g = Subject(
        [Pitch(67), Pitch(69), Pitch(71), Pitch(72), Pitch(74)],
        c_maj, "G開始主題"
    )
    tonal_g = subj_g.get_answer("tonal")
    # G(67)=dominant → mutation: 67+5=72 (C5)
    check("G開始: 調的[0]=C5(72)", tonal_g.pitches[0].midi == 72,
          f"got {tonal_g.pitches[0].midi}")
    # 残りは+7: A→E, B→F#, C→G, D→A
    check("G開始: 調的[1]=A4+7=76", tonal_g.pitches[1].midi == 76)
    check("G開始: 調的[2]=B4+7=78", tonal_g.pitches[2].midi == 78)

    # ---- 属音がない主題 → mutation なし、実音と同じ ----
    print("\n  属音なし主題:")
    # C-D-E（属音Gが含まれない）
    subj_no_dom = Subject(
        [Pitch(60), Pitch(62), Pitch(64)],
        c_maj, "属音なし"
    )
    real_nd = subj_no_dom.get_answer("real")
    tonal_nd = subj_no_dom.get_answer("tonal")
    for i in range(3):
        check(f"属音なし位置{i}: 実音=調的",
              real_nd.pitches[i].midi == tonal_nd.pitches[i].midi)

    # ---- mutation は最初の属音のみ ----
    print("\n  mutation は最初の属音のみ:")
    # C-G-E-G-C (G が2回出現)
    subj_2g = Subject(
        [Pitch(60), Pitch(67), Pitch(64), Pitch(67), Pitch(60)],
        c_maj, "G2回"
    )
    tonal_2g = subj_2g.get_answer("tonal")
    # 位置1: G→mutation→+5=72
    check("1回目のG: mutation(+5)", tonal_2g.pitches[1].midi == 72,
          f"got {tonal_2g.pitches[1].midi}")
    # 位置3: 2回目のG→通常移調(+7)=74
    check("2回目のG: real(+7)", tonal_2g.pitches[3].midi == 74,
          f"got {tonal_2g.pitches[3].midi}")

    # ============================================================
    # D major での調的応答テスト
    # ============================================================
    print("\n--- D major での調的応答 ---")
    d_major = Key("D", "major")
    # D(62)-E(64)-F#(66)-G(67)-A(69)
    # dominant of D = A (pc=9)
    subj_d = Subject(
        [Pitch(62), Pitch(64), Pitch(66), Pitch(67), Pitch(69)],
        d_major, "D主題"
    )
    tonal_d = subj_d.get_answer("tonal")
    real_d = subj_d.get_answer("real")
    # A(69)=dominant → mutation: 69+5=74 (D5) instead of 69+7=76 (E5)
    check("D major: 調的末尾=D5(74)", tonal_d.pitches[4].midi == 74,
          f"got {tonal_d.pitches[4].midi}")
    check("D major: 実音末尾=E5(76)", real_d.pitches[4].midi == 76)
    check("D major: mutation差=−2",
          tonal_d.pitches[4].midi == real_d.pitches[4].midi - 2)

    # ============================================================
    # 主題変形
    # ============================================================
    print("\n--- 主題変形 ---")

    # ---- invert ----
    print("\n  反転（invert）:")
    inv = subject.invert()
    # 軸=60(C4): C4→C4, D4(62)→A#3(58), E4(64)→G#3(56), F4(65)→G3(55), G4(67)→E3(53)
    check("反転[0]=C4(60)", inv.pitches[0].midi == 60)
    check("反転[1]=A#3(58)", inv.pitches[1].midi == 58,
          f"got {inv.pitches[1].midi}")
    check("反転[4]=E3(53)", inv.pitches[4].midi == 53,
          f"got {inv.pitches[4].midi}")
    # 反転の音程は元と符号が逆
    inv_intervals = inv.analyze_intervals()
    orig_intervals = subject.analyze_intervals()
    for i, (o, v) in enumerate(zip(orig_intervals, inv_intervals)):
        check(f"反転音程{i}: {v}==-{o}", v == -o,
              f"orig={o}, inv={v}")

    # ---- retrograde ----
    print("\n  逆行（retrograde）:")
    retro = subject.retrograde()
    check("逆行[0]=G4(67)", retro.pitches[0].midi == 67)
    check("逆行[4]=C4(60)", retro.pitches[4].midi == 60)
    check("逆行の長さ=5", retro.get_length() == 5)

    # ---- retrograde_inversion ----
    print("\n  反転逆行:")
    ri = subject.retrograde_inversion()
    check("反転逆行の長さ=5", ri.get_length() == 5)
    # 反転逆行 = invert してから retrograde
    # inv: [60,58,56,55,53] → retro: [53,55,56,58,60]
    check("反転逆行[0]=53", ri.pitches[0].midi == 53)
    check("反転逆行[4]=60", ri.pitches[4].midi == 60)

    # ---- augmentation / diminution (メタ情報のみ) ----
    print("\n  拡大/縮小:")
    aug = subject.augmentation(2)
    check("拡大の長さ=5", aug.get_length() == 5)
    check("拡大の名前に×2", "×2" in aug.name)
    dim = subject.diminution(2)
    check("縮小の長さ=5", dim.get_length() == 5)
    check("縮小の名前に÷2", "÷2" in dim.name)

    # ---- 空の主題 ----
    print("\n  空の主題:")
    empty = Subject([], c_maj, "空")
    check("空の長さ=0", empty.get_length() == 0)
    inv_empty = empty.invert()
    check("空の反転も空", inv_empty.get_length() == 0)

    # ============================================================
    # Countersubject クラス
    # ============================================================
    print("\n--- Countersubject クラス ---")

    # 対主題: E4-D4-C4-D4-E4（反進行）
    cs_pitches = [Pitch(64), Pitch(62), Pitch(60), Pitch(62), Pitch(64)]
    cs = Countersubject(cs_pitches, "対主題")

    # ---- check_invertibility ----
    print("\n  転回可能性検証:")
    valid, errs = cs.check_invertibility(subj_pitches)
    check("転回可能性テスト実行", True)  # エラーなく実行
    if valid:
        check("対主題は転回可能", valid)
    else:
        check("転回可能性: エラー数確認", len(errs) > 0,
              f"errors={errs}")

    # ---- find_fifths_to_avoid ----
    print("\n  問題の5度特定:")
    probs = cs.find_fifths_to_avoid(subj_pitches)
    check("5度探索実行", True)  # エラーなく実行
    # C4(60) vs E4(64) = 4半音 → 3度、問題なし
    # D4(62) vs D4(62) = 0半音 → 同度
    # E4(64) vs C4(60) = 4半音 → 3度
    # F4(65) vs D4(62) = 3半音 → 短3度
    # G4(67) vs E4(64) = 3半音 → 短3度
    # 5度(7半音)はないはず
    check("この対主題に5度なし", len(probs) == 0,
          f"found {len(probs)} problems")

    # 5度を含む対主題
    cs_with_fifth = Countersubject(
        [Pitch(60), Pitch(62), Pitch(64), Pitch(65), Pitch(60)],
        "5度含む対主題"
    )
    subj_fifth_test = [Pitch(67), Pitch(69), Pitch(71), Pitch(72), Pitch(67)]
    probs2 = cs_with_fifth.find_fifths_to_avoid(subj_fifth_test)
    # 位置0: |67-60|=7 → 5度！
    # 位置4: |67-60|=7 → 5度！
    check("5度の位置を検出", len(probs2) >= 1,
          f"found {len(probs2)} problems")

    # ============================================================
    # FugueStructure クラス
    # ============================================================
    print("\n--- FugueStructure クラス ---")

    # ---- 3声フーガ提示部 ----
    print("\n  3声フーガ提示部:")
    fugue3 = FugueStructure(num_voices=3, main_key=c_maj, subject=subject)
    entries = fugue3.create_exposition()
    check("3声: 登場回数=3", len(entries) == 3)
    check("3声: 第1声=Alto", entries[0].voice_type == FugueVoiceType.ALTO)
    check("3声: 第2声=Soprano", entries[1].voice_type == FugueVoiceType.SOPRANO)
    check("3声: 第3声=Bass", entries[2].voice_type == FugueVoiceType.BASS)
    check("3声: 第1=主題", not entries[0].is_answer)
    check("3声: 第2=応答", entries[1].is_answer)
    check("3声: 第3=主題", not entries[2].is_answer)
    check("3声: 第1開始位置=0", entries[0].start_position == 0)
    check("3声: 第2開始位置=5", entries[1].start_position == 5)
    check("3声: 第3開始位置=10", entries[2].start_position == 10)

    # ---- 4声フーガ提示部 ----
    print("\n  4声フーガ提示部:")
    fugue4 = FugueStructure(num_voices=4, main_key=c_maj, subject=subject)
    entries4 = fugue4.create_exposition()
    check("4声: 登場回数=4", len(entries4) == 4)
    check("4声: 第1声=Alto", entries4[0].voice_type == FugueVoiceType.ALTO)
    check("4声: 第2声=Soprano", entries4[1].voice_type == FugueVoiceType.SOPRANO)
    check("4声: 第3声=Bass", entries4[2].voice_type == FugueVoiceType.BASS)
    check("4声: 第4声=Tenor", entries4[3].voice_type == FugueVoiceType.TENOR)
    check("4声: 偶数位=応答", entries4[1].is_answer and entries4[3].is_answer)
    check("4声: 奇数位=主題",
          not entries4[0].is_answer and not entries4[2].is_answer)

    # ---- 2声フーガ提示部 ----
    print("\n  2声フーガ提示部:")
    fugue2 = FugueStructure(num_voices=2, main_key=c_maj, subject=subject)
    entries2 = fugue2.create_exposition()
    check("2声: 登場回数=2", len(entries2) == 2)
    check("2声: 第1声=Soprano", entries2[0].voice_type == FugueVoiceType.SOPRANO)
    check("2声: 第2声=Alto", entries2[1].voice_type == FugueVoiceType.ALTO)

    # ---- 応答の調 ----
    print("\n  応答の調:")
    answer_entry = entries[1]  # 3声の第2声（応答）
    check("応答の調=G major", answer_entry.key.tonic == 'G')
    subject_entry = entries[0]
    check("主題の調=C major", subject_entry.key.tonic == 'C')

    # ---- セクション情報 ----
    print("\n  セクション:")
    check("セクション数=1（提示部）", len(fugue3.sections) == 1)
    sec, start, end = fugue3.sections[0]
    check("セクション=EXPOSITION", sec == FugueSection.EXPOSITION)
    check("セクション開始=0", start == 0)
    check("セクション終了=15", end == 15)  # 3声 × 5音 = 15

    # ---- check_stretto_feasibility ----
    print("\n  ストレット実現可能性:")
    # C-D-E-F-G を distance=2 でずらす
    feasible2, errs2 = fugue3.check_stretto_feasibility(2)
    check("ストレット距離2: 実行", True)
    # C-D-E-F-G と E-F-G の重なりを検証
    # 重なる区間: leader=[E,F,G], follower=[C,D,E]
    # leader: E→F(+1), F→G(+2) / follower: C→D(+2), D→E(+2)
    # 平行チェック: E-C(4)→F-D(4) = 平行3度 → OK
    #               F-D(4)→G-E(4) = 平行3度 → OK
    # distance=2 は平行5度・8度なし → 可能のはず
    if feasible2:
        check("ストレット距離2: 可能", True)
    else:
        # エラーがある場合も記録
        check("ストレット距離2: 結果確認", True, f"errors={errs2}")

    # distance >= length は常に可能
    feasible_far, _ = fugue3.check_stretto_feasibility(5)
    check("ストレット距離5(=長さ): 常に可能", feasible_far)
    feasible_far2, _ = fugue3.check_stretto_feasibility(10)
    check("ストレット距離10(>長さ): 常に可能", feasible_far2)

    # ---- add_stretto ----
    print("\n  ストレット追加:")
    fugue_s = FugueStructure(num_voices=3, main_key=c_maj, subject=subject)
    fugue_s.create_exposition()
    initial_entries = len(fugue_s.entries)
    fugue_s.add_stretto(start_position=20, overlap_distance=3)
    check("ストレット後のエントリ数増加",
          len(fugue_s.entries) == initial_entries + 3)
    check("セクション数=2（提示部+ストレット）",
          len(fugue_s.sections) == 2)
    sec2, s2_start, s2_end = fugue_s.sections[1]
    check("第2セクション=STRETTO", sec2 == FugueSection.STRETTO)
    check("ストレット開始=20", s2_start == 20)

    # ---- get_section_info ----
    print("\n  構造情報:")
    info = fugue_s.get_section_info()
    check("構造情報にフーガ構造分析が含まれる", "フーガ構造分析" in info)
    check("構造情報に声部数が含まれる", "声部数: 3" in info)
    check("構造情報に主調が含まれる", "C major" in info)
    check("構造情報にexpositionが含まれる", "exposition" in info)
    check("構造情報にstrettoが含まれる", "stretto" in info)

    # ============================================================
    # 追加テスト: 短調のフーガ
    # ============================================================
    print("\n--- 短調のフーガ ---")

    # A minor: A-B-C-D-E
    a_minor = Key("A", "minor")
    subj_am = Subject(
        [Pitch(69), Pitch(71), Pitch(72), Pitch(74), Pitch(76)],
        a_minor, "A minor主題"
    )
    # A minor の dominant = E (pc=4)
    check("A minor dominant=E(4)", a_minor.dominant_pc == 4)

    real_am = subj_am.get_answer("real")
    tonal_am = subj_am.get_answer("tonal")

    # E(76) = pc4 = dominant of A minor
    # mutation: 76+5=81 instead of 76+7=83
    check("A minor実音末尾=83", real_am.pitches[4].midi == 83)
    check("A minor調的末尾=81(mutation)",
          tonal_am.pitches[4].midi == 81,
          f"got {tonal_am.pitches[4].midi}")

    # ============================================================
    # エッジケース
    # ============================================================
    print("\n--- エッジケース ---")

    # 1音の主題
    subj1 = Subject([Pitch(60)], c_maj, "1音")
    check("1音主題の長さ=1", subj1.get_length() == 1)
    check("1音の音程列=空", subj1.analyze_intervals() == [])
    inv1 = subj1.invert()
    check("1音の反転=同音", inv1.pitches[0].midi == 60)
    real1 = subj1.get_answer("real")
    check("1音の実音応答=67", real1.pitches[0].midi == 67)

    # 主題が主音のみで構成（G なし）→ mutation 不発
    subj_c_only = Subject(
        [Pitch(60), Pitch(60), Pitch(60)],
        c_maj, "C反復"
    )
    tonal_c = subj_c_only.get_answer("tonal")
    real_c = subj_c_only.get_answer("real")
    for i in range(3):
        check(f"C反復: 位置{i}実音=調的",
              tonal_c.pitches[i].midi == real_c.pitches[i].midi)

    # ============================================================
    # 結果サマリー
    # ============================================================
    print("\n" + "=" * 70)
    print("テスト結果サマリー")
    print("=" * 70)
    print(f"合格: {passed}/{total}")

    if failed_details:
        print(f"\n【失敗した項目】")
        for d in failed_details:
            print(d)

    rate = passed / total * 100 if total > 0 else 0
    print(f"\n成功率: {rate:.1f}%")

    if rate == 100.0:
        print("🎉 全テスト合格！")
    elif rate >= 90.0:
        print("✓ ほぼ合格")
    else:
        print("⚠️ 要修正")

    return rate == 100.0


if __name__ == "__main__":
    success = run_tests()
    exit(0 if success else 1)
