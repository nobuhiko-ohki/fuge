"""
フーガ構造モジュール 包括的テストスイート（Prout 準拠版）
Fugue Structure Module - Comprehensive Test Suite (Prout-based)

Prout "Fugue" (1891) の規則に基づく調的応答、コデッタ、エピソード、
ストレット、調性計画をテストする。
"""

import sys
sys.path.insert(0, "../src")

from fugue_structure import (
    Key, Subject, Countersubject, Codetta, Episode,
    FugueEntry, FugueStructure,
    FugueVoiceType, FugueSection, AnswerType,
    NOTE_TO_PC, PC_TO_NOTE,
)
from harmony_rules_complete import Pitch


def run_tests():
    print("=" * 70)
    print("フーガ構造モジュール 包括的テストスイート (Prout 準拠)")
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
    # NOTE_TO_PC / PC_TO_NOTE
    # ============================================================
    print("\n--- 音名変換辞書 ---")
    check("C=0", NOTE_TO_PC['C'] == 0)
    check("F#=6", NOTE_TO_PC['F#'] == 6)
    check("Gb=6", NOTE_TO_PC['Gb'] == 6)
    check("B=11", NOTE_TO_PC['B'] == 11)
    check("PC_TO_NOTE[0]=C", PC_TO_NOTE[0] == 'C')
    check("PC_TO_NOTE[7]=G", PC_TO_NOTE[7] == 'G')

    # ============================================================
    # Key クラス
    # ============================================================
    print("\n--- Key クラス ---")

    c_maj = Key("C", "major")
    d_maj = Key("D", "major")
    a_min = Key("A", "minor")

    check("C major tonic_pc=0", c_maj.tonic_pc == 0)
    check("C major dominant_pc=7(G)", c_maj.dominant_pc == 7)
    check("C major leading_tone_pc=11(B)", c_maj.leading_tone_pc == 11)
    check("C major subdominant_pc=5(F)", c_maj.subdominant_pc == 5)
    check("D major tonic_pc=2", d_maj.tonic_pc == 2)
    check("D major dominant_pc=9(A)", d_maj.dominant_pc == 9)
    check("A minor tonic_pc=9", a_min.tonic_pc == 9)
    check("A minor dominant_pc=4(E)", a_min.dominant_pc == 4)

    # 音階度数
    check("C in C major = degree 0", c_maj.get_scale_degree(0) == 0)
    check("G in C major = degree 4", c_maj.get_scale_degree(7) == 4)
    check("F# in C major = None", c_maj.get_scale_degree(6) is None)

    # 転調
    g_key = c_maj.get_dominant_key()
    check("C major → 属調=G", g_key.tonic == 'G')
    f_key = c_maj.get_subdominant_key()
    check("C major → 下属調=F", f_key.tonic == 'F')
    rel = c_maj.get_relative_key()
    check("C major → 平行短調=A minor", rel.tonic == 'A' and rel.mode == "minor")
    rel2 = a_min.get_relative_key()
    check("A minor → 平行長調=C major", rel2.tonic == 'C' and rel2.mode == "major")

    # ============================================================
    # Subject 基本
    # ============================================================
    print("\n--- Subject 基本 ---")

    subj = Subject(
        [Pitch(60), Pitch(62), Pitch(64), Pitch(65), Pitch(67)],
        c_maj, "主題"
    )

    check("get_length=5", subj.get_length() == 5)
    check("analyze_intervals=[2,2,1,2]", subj.analyze_intervals() == [2, 2, 1, 2])
    check("get_opening_degree=0(tonic)", subj.get_opening_degree() == 0)

    # ============================================================
    # 調的応答 — Prout Ch.III-IV（中核テスト）
    # ============================================================
    print("\n--- 調的応答 (Prout Ch.III-IV) ---")

    # テスト1: C-D-E-F-G（ハ長調）
    # 頭部: C-D-E-F-G（G=属音で終わる）、尾部: 空
    # 期待:
    #   C(60, 1度) → +7 = G(67)
    #   D(62, 2度) → +7 = A(69)  [主調領域]
    #   E(64, 3度) → +7 = B(71)  [主調領域]
    #   F(65, 4度) → 文脈判定（主調領域→+5=70 or +7=72）
    #   G(67, 5度) → +5 = C(72)  [mutation]

    print("\n  テスト1: C-D-E-F-G")
    real = subj.get_answer("real")
    tonal = subj.get_answer("tonal")

    check("実音[0]=G4(67)", real.pitches[0].midi == 67)
    check("実音[4]=D5(74)", real.pitches[4].midi == 74)
    check("調的[0]=G4(67) [1度→5度: +7]", tonal.pitches[0].midi == 67)

    # G(5度) → mutation: +5 = 72(C5)
    check("調的[4]=C5(72) [5度→1度: +5]",
          tonal.pitches[4].midi == 72,
          f"got {tonal.pitches[4].midi}")

    # 調的応答が必要か
    check("needs_tonal_answer=True (属音含む)", subj.needs_tonal_answer())

    # テスト2: 属音が先頭 G-A-B-C-D
    print("\n  テスト2: G-A-B-C-D（属音開始）")
    subj_g = Subject(
        [Pitch(67), Pitch(69), Pitch(71), Pitch(72), Pitch(74)],
        c_maj, "G開始主題"
    )
    check("needs_tonal=True (属音開始)", subj_g.needs_tonal_answer())
    tonal_g = subj_g.get_answer("tonal")
    # G(67, 5度) → +5 = 72(C5) [mutation]
    check("G開始: 調的[0]=C5(72) [5度→1度]",
          tonal_g.pitches[0].midi == 72,
          f"got {tonal_g.pitches[0].midi}")

    # テスト3: 属音がない C-D-E
    print("\n  テスト3: C-D-E（属音なし）")
    subj_no_dom = Subject(
        [Pitch(60), Pitch(62), Pitch(64)],
        c_maj, "属音なし"
    )
    check("needs_tonal=False (属音なし)", not subj_no_dom.needs_tonal_answer())
    real_nd = subj_no_dom.get_answer("real")
    tonal_nd = subj_no_dom.get_answer("tonal")
    for i in range(3):
        check(f"属音なし位置{i}: 実音=調的",
              real_nd.pitches[i].midi == tonal_nd.pitches[i].midi)

    # テスト4: mutation は最初の属音のみ C-G-E-G-C
    print("\n  テスト4: C-G-E-G-C（G2回）")
    subj_2g = Subject(
        [Pitch(60), Pitch(67), Pitch(64), Pitch(67), Pitch(60)],
        c_maj, "G2回"
    )
    tonal_2g = subj_2g.get_answer("tonal")
    # 位置1: G(5度) → mutation: +5=72
    check("1回目G: +5(mutation)=72",
          tonal_2g.pitches[1].midi == 72,
          f"got {tonal_2g.pitches[1].midi}")

    # テスト5: D major
    print("\n  テスト5: D-E-F#-G-A（ニ長調）")
    subj_d = Subject(
        [Pitch(62), Pitch(64), Pitch(66), Pitch(67), Pitch(69)],
        d_maj, "D主題"
    )
    tonal_d = subj_d.get_answer("tonal")
    real_d = subj_d.get_answer("real")
    # A(69) = dominant of D major (pc=9) → mutation: 69+5=74
    check("D major: 調的末尾=74(+5)",
          tonal_d.pitches[4].midi == 74,
          f"got {tonal_d.pitches[4].midi}")
    check("D major: 実音末尾=76(+7)", real_d.pitches[4].midi == 76)

    # テスト6: A minor
    print("\n  テスト6: A-B-C-D-E（イ短調）")
    subj_am = Subject(
        [Pitch(69), Pitch(71), Pitch(72), Pitch(74), Pitch(76)],
        a_min, "A minor主題"
    )
    tonal_am = subj_am.get_answer("tonal")
    # E(76) = dominant(pc=4) → mutation: 76+5=81
    check("A minor: 調的末尾=81(+5)",
          tonal_am.pitches[4].midi == 81,
          f"got {tonal_am.pitches[4].midi}")

    # テスト7: 主音→属音の跳躍 C-G
    print("\n  テスト7: C-G（主音→属音跳躍）")
    subj_cg = Subject([Pitch(60), Pitch(67)], c_maj, "C-G")
    check("C-G needs_tonal=True", subj_cg.needs_tonal_answer())
    tonal_cg = subj_cg.get_answer("tonal")
    check("C→G: 調的[0]=67(+7)", tonal_cg.pitches[0].midi == 67)
    check("C→G: 調的[1]=72(+5)", tonal_cg.pitches[1].midi == 72,
          f"got {tonal_cg.pitches[1].midi}")

    # ============================================================
    # head/tail 分割
    # ============================================================
    print("\n--- head/tail 分割 (Prout Ch.III §4) ---")

    head, tail = subj.get_head_tail_split()
    check("C-D-E-F-G: head=5(Gまで)", len(head) == 5)
    check("C-D-E-F-G: tail=0", len(tail) == 0)

    subj_mid = Subject(
        [Pitch(60), Pitch(67), Pitch(65), Pitch(64), Pitch(62)],
        c_maj, "中間G"
    )
    head_m, tail_m = subj_mid.get_head_tail_split()
    check("C-G-F-E-D: head=2(位置1のGまで)", len(head_m) == 2)
    check("C-G-F-E-D: tail=3", len(tail_m) == 3)

    # ============================================================
    # 主題変形
    # ============================================================
    print("\n--- 主題変形 ---")

    inv = subj.invert()
    check("反転[0]=C4(60)", inv.pitches[0].midi == 60)
    check("反転[1]=58(-2)", inv.pitches[1].midi == 58)
    check("反転[4]=53(-7)", inv.pitches[4].midi == 53)

    retro = subj.retrograde()
    check("逆行[0]=G4(67)", retro.pitches[0].midi == 67)
    check("逆行[4]=C4(60)", retro.pitches[4].midi == 60)

    ri = subj.retrograde_inversion()
    check("反転逆行[0]=53", ri.pitches[0].midi == 53)
    check("反転逆行[4]=60", ri.pitches[4].midi == 60)

    aug = subj.augmentation(2)
    check("拡大名に×2", "×2" in aug.name)
    dim = subj.diminution(2)
    check("縮小名に÷2", "÷2" in dim.name)

    # 空の主題
    empty = Subject([], c_maj, "空")
    check("空の反転も空", empty.invert().get_length() == 0)

    # ============================================================
    # コデッタ — Prout Ch.VI
    # ============================================================
    print("\n--- コデッタ (Prout Ch.VI) ---")

    answer = subj.get_answer("tonal")
    needs = Codetta.needs_codetta(subj, answer)
    # subj末尾=67(G4), answer先頭=67(G4) → 差0 → 不要
    check("C-D-E-F-G → 応答G...: コデッタ不要", not needs,
          f"subj_last={subj.pitches[-1].midi}, ans_first={answer.pitches[0].midi}")

    # 大きな跳躍がある場合
    subj_low = Subject(
        [Pitch(48), Pitch(50), Pitch(52), Pitch(53), Pitch(55)],
        c_maj, "低音主題"
    )
    ans_high = Subject(
        [Pitch(67), Pitch(69), Pitch(71)],
        c_maj.get_dominant_key(), "高音応答"
    )
    check("大跳躍: コデッタ必要",
          Codetta.needs_codetta(subj_low, ans_high))

    # コデッタ生成
    codetta = Codetta.generate_codetta(subj_low, ans_high)
    check("コデッタ生成成功", codetta.get_length() >= 0)

    # 空の場合
    empty_subj = Subject([], c_maj, "空")
    empty_ans = Subject([], c_maj.get_dominant_key(), "空応答")
    check("空のコデッタ不要", not Codetta.needs_codetta(empty_subj, empty_ans))

    # ============================================================
    # エピソード — Prout Ch.VII
    # ============================================================
    print("\n--- エピソード (Prout Ch.VII) ---")

    motif = Episode.extract_motif(subj, 0, 3)
    check("動機抽出: 長さ3", len(motif) == 3)
    check("動機[0]=C4(60)", motif[0].midi == 60)
    check("動機[2]=E4(64)", motif[2].midi == 64)

    ep = Episode(motif, sequence_steps=3, step_interval=-2)
    ep_pitches = ep.generate_pitches()
    check("エピソード長さ=9(3×3)", len(ep_pitches) == 9)
    # 1回目: C-D-E, 2回目: A#-C-D (各-2), 3回目: G#-A#-C (各-4)
    check("エピソード[0]=60(C4)", ep_pitches[0].midi == 60)
    check("エピソード[3]=58(C4-2)", ep_pitches[3].midi == 58)
    check("エピソード[6]=56(C4-4)", ep_pitches[6].midi == 56)

    check("get_total_length=9", ep.get_total_length() == 9)

    # 動機が主題より長い場合
    short_motif = Episode.extract_motif(subj, 0, 10)
    check("動機は主題長で切り詰め", len(short_motif) == 5)

    # ============================================================
    # Countersubject — Prout Ch.V
    # ============================================================
    print("\n--- Countersubject (Prout Ch.V) ---")

    cs = Countersubject(
        [Pitch(64), Pitch(62), Pitch(60), Pitch(62), Pitch(64)],
        "対主題"
    )
    valid, errs = cs.check_invertibility(subj.pitches)
    check("転回可能性テスト実行", True)

    probs = cs.find_fifths_to_avoid(subj.pitches)
    check("5度探索実行", True)

    # 5度を含む対主題
    cs_fifth = Countersubject(
        [Pitch(60), Pitch(62), Pitch(64), Pitch(65), Pitch(60)],
        "5度含"
    )
    subj_fifth = [Pitch(67), Pitch(69), Pitch(71), Pitch(72), Pitch(67)]
    probs2 = cs_fifth.find_fifths_to_avoid(subj_fifth)
    check("5度位置検出", len(probs2) >= 1)

    # ============================================================
    # FugueStructure — 提示部
    # ============================================================
    print("\n--- FugueStructure 提示部 ---")

    # 3声
    fugue3 = FugueStructure(num_voices=3, main_key=c_maj, subject=subj)
    entries3 = fugue3.create_exposition(answer_type="auto")
    check("3声: 登場回数=3", len(entries3) == 3)
    check("3声: 第1=Alto", entries3[0].voice_type == FugueVoiceType.ALTO)
    check("3声: 第2=Soprano", entries3[1].voice_type == FugueVoiceType.SOPRANO)
    check("3声: 第3=Bass", entries3[2].voice_type == FugueVoiceType.BASS)
    check("3声: 第1=主題", not entries3[0].is_answer)
    check("3声: 第2=応答", entries3[1].is_answer)
    check("3声: 第3=主題", not entries3[2].is_answer)

    # 4声
    fugue4 = FugueStructure(num_voices=4, main_key=c_maj, subject=subj)
    entries4 = fugue4.create_exposition()
    check("4声: 登場回数=4", len(entries4) == 4)
    check("4声: 第4=Tenor", entries4[3].voice_type == FugueVoiceType.TENOR)
    check("4声: 偶数位=応答", entries4[1].is_answer and entries4[3].is_answer)

    # 2声
    fugue2 = FugueStructure(num_voices=2, main_key=c_maj, subject=subj)
    entries2 = fugue2.create_exposition()
    check("2声: 登場回数=2", len(entries2) == 2)

    # 応答の調
    check("応答の調=G", entries3[1].key.tonic == 'G')

    # セクション
    check("セクション数>=1", len(fugue3.sections) >= 1)
    sec, s, e = fugue3.sections[0]
    check("第1セクション=EXPOSITION", sec == FugueSection.EXPOSITION)

    # ============================================================
    # エピソード統合
    # ============================================================
    print("\n--- エピソード統合 ---")

    ep_pos = e  # 提示部の終了位置
    episode = fugue3.create_episode(ep_pos, motif_length=3,
                                     sequence_steps=3, step_interval=-2)
    check("エピソード生成", episode.get_total_length() == 9)
    check("セクション数=2", len(fugue3.sections) == 2)
    check("第2セクション=EPISODE", fugue3.sections[1][0] == FugueSection.EPISODE)

    # ============================================================
    # 中間提示 — Prout Ch.IX
    # ============================================================
    print("\n--- 中間提示 (Prout Ch.IX) ---")

    rel_key = c_maj.get_relative_key()
    me = fugue3.add_middle_entry(
        start_position=fugue3.sections[-1][2],
        target_key=rel_key,
    )
    check("中間提示の調=A minor", me.key.tonic == 'A')
    check("セクション数=3", len(fugue3.sections) == 3)
    check("第3セクション=MIDDLE_ENTRY",
          fugue3.sections[2][0] == FugueSection.MIDDLE_ENTRY)

    # ============================================================
    # ストレット — Prout Ch.VIII
    # ============================================================
    print("\n--- ストレット (Prout Ch.VIII) ---")

    feasible2, errs2 = fugue3.check_stretto_feasibility(2)
    check("ストレット距離2: 実行", True)

    feasible_far, _ = fugue3.check_stretto_feasibility(5)
    check("距離>=長さ: 常に可能", feasible_far)

    fugue3.add_stretto(start_position=50, overlap_distance=3)
    check("ストレット追加後エントリ増加", len(fugue3.entries) > 4)

    # ============================================================
    # 調性計画 — Prout Ch.IX
    # ============================================================
    print("\n--- 調性計画 (Prout Ch.IX) ---")

    plan = fugue3.get_modulation_plan()
    check("調性計画: 5段階", len(plan) == 5)
    check("計画[0]: 主調C", plan[0][1].tonic == 'C')
    check("計画[1]: 属調G", plan[1][1].tonic == 'G')
    check("計画[2]: 平行調A", plan[2][1].tonic == 'A')
    check("計画[3]: 下属調F", plan[3][1].tonic == 'F')
    check("計画[4]: 再帰C", plan[4][1].tonic == 'C')

    # ============================================================
    # 構造情報
    # ============================================================
    print("\n--- 構造情報 ---")
    info = fugue3.get_section_info()
    check("フーガ構造分析を含む", "フーガ構造分析" in info)
    check("Prout Ch.IXを含む", "Prout Ch.IX" in info)
    check("コデッタ情報を含む", "コデッタ" in info)
    check("エピソード情報を含む", "エピソード" in info)

    # ============================================================
    # auto answer_type テスト
    # ============================================================
    print("\n--- auto answer_type ---")

    # 属音がない主題 → auto で real answer
    subj_no_dom = Subject(
        [Pitch(60), Pitch(62), Pitch(64)],
        c_maj, "属音なし"
    )
    fugue_nd = FugueStructure(num_voices=3, main_key=c_maj, subject=subj_no_dom)
    entries_nd = fugue_nd.create_exposition(answer_type="auto")
    # 応答は real answer と同じはず
    real_nd = subj_no_dom.get_answer("real")
    if entries_nd[1].subject.pitches:
        check("auto: 属音なし→実音応答",
              entries_nd[1].subject.pitches[0].midi == real_nd.pitches[0].midi)

    # ============================================================
    # エッジケース
    # ============================================================
    print("\n--- エッジケース ---")

    subj1 = Subject([Pitch(60)], c_maj, "1音")
    check("1音主題", subj1.get_length() == 1)
    check("1音の音程列=空", subj1.analyze_intervals() == [])

    subj_c_only = Subject([Pitch(60), Pitch(60), Pitch(60)], c_maj, "C反復")
    tonal_c = subj_c_only.get_answer("tonal")
    real_c = subj_c_only.get_answer("real")
    for i in range(3):
        check(f"C反復{i}: tonal=real",
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
