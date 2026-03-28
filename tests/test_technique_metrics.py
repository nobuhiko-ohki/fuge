"""
模範的和声連結技法の適用率測定
Exemplary Voice Leading Technique Application Metrics

禁則（してはならないこと）の遵守率とは別に、
教科書が推奨する積極的技法（すべきこと）の適用率を定量的に測定する。

基準: Walter Piston "Harmony" (5th ed., 1987)
"""

from voice_leading_fugue_gen import VoiceLeadingGenerator, Voice, ChordProgression
from harmony_rules_complete import HarmonyRules, Pitch, ScaleDegree


class TechniqueMetrics:
    """推奨技法の適用率を測定"""

    def __init__(self, generator: VoiceLeadingGenerator):
        self.gen = generator
        self.rules = HarmonyRules()
        self.num_positions = len(generator.voices[Voice.SOPRANO])
        self.num_transitions = self.num_positions - 1

    # ================================================================
    # 技法1: 共通音保持 (Piston Ch.4-5)
    # ================================================================
    # 隣接する2和音が共通のピッチクラスを持つ場合、
    # それを同一声部に保持するのが原則。
    # 測定: 保持可能だった共通音のうち、実際に保持された割合。

    def measure_common_tone_retention(self) -> dict:
        """共通音保持率を測定"""
        available = 0  # 共通音が存在した機会の総数
        retained = 0   # 実際に同一声部に保持された数
        detail = []

        upper_voices = [Voice.SOPRANO, Voice.ALTO, Voice.TENOR]

        for i in range(self.num_transitions):
            prev_prog = self.gen.progression[i]
            curr_prog = self.gen.progression[i + 1]
            common_pcs = prev_prog.chord_tones & curr_prog.chord_tones

            if not common_pcs:
                continue

            # 各上声部について、前の音が共通音であれば保持機会
            for voice in upper_voices:
                prev_midi = self.gen.voices[voice][i]
                prev_pc = prev_midi % 12
                curr_midi = self.gen.voices[voice][i + 1]

                if prev_pc in common_pcs:
                    available += 1
                    if curr_midi == prev_midi:
                        retained += 1
                        detail.append((i, voice.value, "保持"))
                    else:
                        detail.append((i, voice.value, "非保持"))

        rate = retained / available * 100 if available > 0 else 0
        return {
            "name": "共通音保持",
            "piston_ref": "Ch.4-5",
            "available": available,
            "applied": retained,
            "rate": rate,
            "detail": detail,
        }

    # ================================================================
    # 技法2: 順次進行 (Piston p.18-19)
    # ================================================================
    # 上声部は順次進行（半音または全音=1～2半音）が理想。
    # 保持（0半音）も良好。3度（3-4半音）は許容。
    # 5半音以上は跳躍で非推奨。
    # 測定: 上声部の動きのうち、順次進行（1-2半音）の割合。

    def measure_stepwise_motion(self) -> dict:
        """順次進行率を測定（上声部）"""
        upper_voices = [Voice.SOPRANO, Voice.ALTO, Voice.TENOR]

        total_movements = 0    # 保持を除く動きの総数
        stepwise_count = 0     # 順次進行の数（1-2半音）
        third_count = 0        # 3度進行の数（3-4半音）
        leap_count = 0         # 跳躍の数（5半音以上）
        hold_count = 0         # 保持の数（0半音）

        per_voice = {}
        for voice in upper_voices:
            v_total = 0
            v_step = 0
            v_third = 0
            v_leap = 0
            v_hold = 0

            for i in range(self.num_transitions):
                prev = self.gen.voices[voice][i]
                curr = self.gen.voices[voice][i + 1]
                interval = abs(curr - prev)

                if interval == 0:
                    hold_count += 1
                    v_hold += 1
                elif interval <= 2:
                    stepwise_count += 1
                    total_movements += 1
                    v_step += 1
                    v_total += 1
                elif interval <= 4:
                    third_count += 1
                    total_movements += 1
                    v_third += 1
                    v_total += 1
                else:
                    leap_count += 1
                    total_movements += 1
                    v_leap += 1
                    v_total += 1

            v_rate = v_step / v_total * 100 if v_total > 0 else 0
            per_voice[voice.value] = {
                "stepwise": v_step, "third": v_third,
                "leap": v_leap, "hold": v_hold,
                "rate": v_rate,
            }

        rate = stepwise_count / total_movements * 100 if total_movements > 0 else 0
        return {
            "name": "順次進行（上声部）",
            "piston_ref": "p.18-19",
            "total_movements": total_movements,
            "stepwise": stepwise_count,
            "third": third_count,
            "leap": leap_count,
            "hold": hold_count,
            "rate": rate,
            "per_voice": per_voice,
        }

    # ================================================================
    # 技法3: 外声反行 (Piston p.22)
    # ================================================================
    # ソプラノとバスは反行（逆方向の動き）が理想。
    # 斜行（一方が保持）も良好。
    # 並行（同方向）は避けるべき。
    # 測定: 両声部が動いた場合のうち、反行の割合。

    def measure_contrary_motion(self) -> dict:
        """外声反行率を測定"""
        both_moved = 0      # 両外声が動いた回数
        contrary = 0        # 反行
        similar = 0         # 並行（同方向）
        oblique = 0         # 斜行（片方が保持）

        for i in range(self.num_transitions):
            s_prev = self.gen.voices[Voice.SOPRANO][i]
            s_curr = self.gen.voices[Voice.SOPRANO][i + 1]
            b_prev = self.gen.voices[Voice.BASS][i]
            b_curr = self.gen.voices[Voice.BASS][i + 1]

            s_motion = s_curr - s_prev
            b_motion = b_curr - b_prev

            if s_motion == 0 or b_motion == 0:
                oblique += 1
            elif (s_motion > 0 and b_motion < 0) or (s_motion < 0 and b_motion > 0):
                contrary += 1
                both_moved += 1
            else:
                similar += 1
                both_moved += 1

        rate = contrary / both_moved * 100 if both_moved > 0 else 0
        return {
            "name": "外声反行",
            "piston_ref": "p.22",
            "both_moved": both_moved,
            "contrary": contrary,
            "similar": similar,
            "oblique": oblique,
            "rate": rate,
        }

    # ================================================================
    # 技法4: 導音解決 (Piston Ch.7, p.32)
    # ================================================================
    # V→IまたはV→viの連結で、導音（第7音階音）が声部に
    # 出現している場合、主音へ半音上行解決すべき。
    # 測定: 導音の出現機会のうち、正しく解決された割合。

    def measure_leading_tone_resolution(self) -> dict:
        """導音解決率を測定"""
        scale = self.gen.scale
        leading_tone_pc = scale[6]  # 第7音（導音）
        tonic_pc = scale[0]

        opportunities = 0
        resolved = 0
        detail = []

        for i in range(self.num_transitions):
            prev_deg = self.gen.progression[i].degree
            curr_deg = self.gen.progression[i + 1].degree

            # V→I または vii°→I の連結
            if prev_deg not in (ScaleDegree.V, ScaleDegree.VII):
                continue
            if curr_deg != ScaleDegree.I:
                continue

            # 各声部で導音を持つものを探す
            for voice in Voice:
                prev_midi = self.gen.voices[voice][i]
                prev_pc = prev_midi % 12
                curr_midi = self.gen.voices[voice][i + 1]
                curr_pc = curr_midi % 12

                if prev_pc == leading_tone_pc:
                    opportunities += 1
                    # 主音へ上行解決したか
                    if curr_pc == tonic_pc and curr_midi > prev_midi:
                        resolved += 1
                        detail.append((i, voice.value, "解決"))
                    elif curr_pc == tonic_pc and curr_midi <= prev_midi:
                        detail.append((i, voice.value, "下行解決（非推奨）"))
                    else:
                        detail.append((i, voice.value,
                                       f"未解決→pc{curr_pc}"))

        rate = resolved / opportunities * 100 if opportunities > 0 else 0
        return {
            "name": "導音解決",
            "piston_ref": "Ch.7 p.32",
            "opportunities": opportunities,
            "resolved": resolved,
            "rate": rate,
            "detail": detail,
        }

    # ================================================================
    # 技法5: 根音配置 (Piston p.19)
    # ================================================================
    # 三和音は基本形（根音がバス）が最も安定。
    # 転回形は声部導音の滑らかさのため許容されるが、
    # 根音配置が基本。
    # 測定: バスが根音である和音の割合。

    def measure_root_position(self) -> dict:
        """根音配置率を測定"""
        root_position = 0
        first_inversion = 0
        second_inversion = 0

        for i in range(self.num_positions):
            bass_pc = self.gen.voices[Voice.BASS][i] % 12
            prog = self.gen.progression[i]

            if bass_pc == prog.root_pc:
                root_position += 1
            elif bass_pc == prog.third_pc:
                first_inversion += 1
            elif bass_pc == prog.fifth_pc:
                second_inversion += 1

        rate = root_position / self.num_positions * 100
        return {
            "name": "根音配置",
            "piston_ref": "p.19",
            "total": self.num_positions,
            "root_position": root_position,
            "first_inversion": first_inversion,
            "second_inversion": second_inversion,
            "rate": rate,
        }

    # ================================================================
    # 技法6: バス強進行 (Piston p.29-31)
    # ================================================================
    # バスの4度・5度進行は「強進行」と呼ばれ、和声的に最も安定。
    # 2度進行は「弱進行」、3度は「中程度」。
    # 測定: バスの動きのうち、4度・5度進行の割合。

    def measure_bass_strong_motion(self) -> dict:
        """バス強進行率を測定"""
        total = 0
        strong = 0      # 4度・5度（5半音 or 7半音）
        moderate = 0    # 3度（3-4半音）
        weak = 0        # 2度（1-2半音）
        hold = 0        # 保持
        other = 0       # その他

        for i in range(self.num_transitions):
            prev = self.gen.voices[Voice.BASS][i]
            curr = self.gen.voices[Voice.BASS][i + 1]
            interval = abs(curr - prev)
            ic = interval % 12  # 音程クラス（オクターブ換算）

            if interval == 0:
                hold += 1
                continue

            total += 1

            if ic in (5, 7):  # 完全4度=5半音, 完全5度=7半音
                strong += 1
            elif ic in (3, 4, 8, 9):  # 短3度, 長3度, 短6度, 長6度
                moderate += 1
            elif ic in (1, 2, 10, 11):  # 短2度, 長2度, 短7度, 長7度
                weak += 1
            else:
                other += 1

        rate = strong / total * 100 if total > 0 else 0
        return {
            "name": "バス強進行（4度・5度）",
            "piston_ref": "p.29-31",
            "total_movements": total,
            "strong_4th_5th": strong,
            "moderate_3rd": moderate,
            "weak_2nd": weak,
            "hold": hold,
            "rate": rate,
        }

    # ================================================================
    # 技法7: 密集配置 (Piston p.18)
    # ================================================================
    # 上3声（S, A, T）の全体がオクターブ以内に収まるのが密集配置。
    # 密集配置は声部の一体感が高く、教科書では初学者に推奨される。
    # 開離配置（S-Tが1オクターブ超）は表現の幅を広げるが、
    # 声部の分離が生じやすい。
    # 測定: S-T間がオクターブ以内の和音の割合。

    def measure_close_position(self) -> dict:
        """密集配置率を測定"""
        close = 0

        for i in range(self.num_positions):
            s = self.gen.voices[Voice.SOPRANO][i]
            t = self.gen.voices[Voice.TENOR][i]

            if s - t <= 12:
                close += 1

        rate = close / self.num_positions * 100
        return {
            "name": "密集配置",
            "piston_ref": "p.18",
            "total": self.num_positions,
            "close_position": close,
            "open_position": self.num_positions - close,
            "rate": rate,
        }

    # ================================================================
    # 技法8: 完全正格終止 (Piston p.88-89)
    # ================================================================
    # 楽曲末尾のV→Iで:
    #   - バスが根音（基本形）
    #   - ソプラノが主音
    # これを満たすのが「完全正格終止」（最も決定力のある終止）。
    # 測定: 最終V→Iがこれを満たすか（真偽値）。

    def measure_perfect_authentic_cadence(self) -> dict:
        """完全正格終止の判定"""
        n = self.num_positions
        if n < 2:
            return {
                "name": "完全正格終止",
                "piston_ref": "p.88-89",
                "achieved": False,
                "detail": "和音数不足",
            }

        penult_deg = self.gen.progression[n - 2].degree
        final_deg = self.gen.progression[n - 1].degree

        if penult_deg != ScaleDegree.V or final_deg != ScaleDegree.I:
            return {
                "name": "完全正格終止",
                "piston_ref": "p.88-89",
                "achieved": False,
                "detail": f"最終進行が{penult_deg.name}→{final_deg.name}（V→Iではない）",
            }

        tonic_pc = self.gen.scale[0]
        final_bass_pc = self.gen.voices[Voice.BASS][n - 1] % 12
        final_soprano_pc = self.gen.voices[Voice.SOPRANO][n - 1] % 12

        bass_is_root = final_bass_pc == tonic_pc
        soprano_is_tonic = final_soprano_pc == tonic_pc

        achieved = bass_is_root and soprano_is_tonic
        detail_parts = []
        if bass_is_root:
            detail_parts.append("バス=根音✓")
        else:
            detail_parts.append(f"バス=pc{final_bass_pc}（根音pc{tonic_pc}ではない）")
        if soprano_is_tonic:
            detail_parts.append("ソプラノ=主音✓")
        else:
            detail_parts.append(f"ソプラノ=pc{final_soprano_pc}（主音ではない）")

        return {
            "name": "完全正格終止",
            "piston_ref": "p.88-89",
            "achieved": achieved,
            "detail": "、".join(detail_parts),
        }

    # ================================================================
    # 全測定の実行
    # ================================================================

    def run_all(self) -> list:
        """全推奨技法の測定を実行"""
        return [
            self.measure_common_tone_retention(),
            self.measure_stepwise_motion(),
            self.measure_contrary_motion(),
            self.measure_leading_tone_resolution(),
            self.measure_root_position(),
            self.measure_bass_strong_motion(),
            self.measure_close_position(),
            self.measure_perfect_authentic_cadence(),
        ]


# ================================================================
# レポート出力
# ================================================================

def print_report(results: list):
    """測定結果をレポート出力"""
    print("\n" + "=" * 70)
    print("模範的和声連結技法 適用率レポート")
    print("Based on Walter Piston \"Harmony\" (5th ed., 1987)")
    print("=" * 70)

    total_rate_sum = 0
    rate_count = 0

    for r in results:
        print(f"\n{'─' * 60}")
        print(f"【{r['name']}】 (Piston {r['piston_ref']})")
        print(f"{'─' * 60}")

        if r["name"] == "完全正格終止":
            status = "達成" if r["achieved"] else "未達成"
            print(f"  結果: {status}")
            print(f"  詳細: {r['detail']}")
            if r["achieved"]:
                total_rate_sum += 100
                rate_count += 1
            else:
                total_rate_sum += 0
                rate_count += 1
            continue

        if "rate" in r:
            print(f"  適用率: {r['rate']:.1f}%")
            total_rate_sum += r["rate"]
            rate_count += 1

        # 技法別の詳細表示
        if r["name"] == "共通音保持":
            print(f"  機会: {r['available']}回  保持: {r['applied']}回")

        elif r["name"] == "順次進行（上声部）":
            print(f"  動き{r['total_movements']}回中: "
                  f"順次{r['stepwise']}  3度{r['third']}  "
                  f"跳躍{r['leap']}  (保持{r['hold']})")
            for v, info in r["per_voice"].items():
                print(f"    {v:8s}: 順次{info['stepwise']:2d} "
                      f"3度{info['third']:2d} "
                      f"跳躍{info['leap']:2d} "
                      f"保持{info['hold']:2d} "
                      f"→ {info['rate']:.0f}%")

        elif r["name"] == "外声反行":
            print(f"  両声部が動いた{r['both_moved']}回中: "
                  f"反行{r['contrary']}  並行{r['similar']}  "
                  f"(斜行{r['oblique']})")

        elif r["name"] == "導音解決":
            print(f"  機会: {r['opportunities']}回  解決: {r['resolved']}回")
            for beat, voice, status in r.get("detail", []):
                print(f"    拍{beat}→{beat+1} {voice}: {status}")

        elif r["name"] == "根音配置":
            print(f"  {r['total']}和音中: "
                  f"基本形{r['root_position']}  "
                  f"第1転回{r['first_inversion']}  "
                  f"第2転回{r['second_inversion']}")

        elif r["name"] == "バス強進行（4度・5度）":
            print(f"  動き{r['total_movements']}回中: "
                  f"強(4度5度){r['strong_4th_5th']}  "
                  f"中(3度){r['moderate_3rd']}  "
                  f"弱(2度){r['weak_2nd']}  "
                  f"(保持{r['hold']})")

        elif r["name"] == "密集配置":
            print(f"  {r['total']}和音中: "
                  f"密集{r['close_position']}  "
                  f"開離{r['open_position']}")

    # 総合スコア
    overall = total_rate_sum / rate_count if rate_count > 0 else 0
    print(f"\n{'=' * 70}")
    print(f"総合適用率: {overall:.1f}% （{rate_count}技法の平均）")
    print(f"{'=' * 70}")

    return overall


# ================================================================
# メイン
# ================================================================

def test_technique_metrics(num_chords: int = 32):
    """指定和音数で生成し、推奨技法の適用率を測定"""
    generator = VoiceLeadingGenerator(tonic_pc=0)
    generator.generate(num_chords=num_chords)

    metrics = TechniqueMetrics(generator)
    results = metrics.run_all()
    overall = print_report(results)

    return overall, results


if __name__ == "__main__":
    overall, results = test_technique_metrics(num_chords=32)
