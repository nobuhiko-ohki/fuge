"""
声部導音テクニック統合フーガ生成エンジン（4声・代理和音対応）
Voice Leading Techniques Applied Fugue Generator

動的計画法（ビタビアルゴリズム）により全体最適の声部配置を探索。

和声学規則（harmony_rules_complete）+ 対位法規則（counterpoint_engine）を統合。

Piston "Harmony" のテクニック:
1. 共通音保持
2. 反行
3. 最短距離の原則
4. 和音の展開
5. 順次進行優先
6. 音域中央への引力
7. 完全正格終止

対位法規則（counterpoint_engine）:
8. 隠伏5度・8度の禁止（外声部）
9. 7度跳躍の禁止
10. 声部超越の禁止
11. 声部独立性のスコアリング
12. 動きの種類（反行優先）のスコアリング
"""

from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum

from harmony_rules_complete import HarmonyRules, Pitch, ScaleDegree
from counterpoint_engine import CounterpointEngine
from midi_writer import MIDIWriter

# 配置: (soprano, alto, tenor, bass) のMIDI値タプル
Voicing = Tuple[int, int, int, int]


class Voice(Enum):
    """声部"""
    SOPRANO = "soprano"
    ALTO = "alto"
    TENOR = "tenor"
    BASS = "bass"


@dataclass
class ChordProgression:
    """和声進行の1ステップ"""
    position: int  # 4分音符単位
    degree: ScaleDegree
    chord_tones: Set[int]  # ピッチクラス
    root_pc: int
    third_pc: int
    fifth_pc: int


# 長調における各度数の和音の種類
MAJOR_SCALE_QUALITIES = {
    ScaleDegree.I: "major",
    ScaleDegree.II: "minor",
    ScaleDegree.III: "minor",
    ScaleDegree.IV: "major",
    ScaleDegree.V: "major",
    ScaleDegree.VI: "minor",
    ScaleDegree.VII: "diminished",
}


class VoiceLeadingGenerator:
    """声部導音テクニックを使用した4声フーガ生成"""

    def __init__(self, tonic_pc: int = 0):
        self.rules = HarmonyRules()
        self.counterpoint = CounterpointEngine(num_voices=4)
        self.tonic_pc = tonic_pc
        self.scale = self.rules.get_major_scale(tonic_pc)

        # 声部の音域 (Piston p.17)
        self.ranges = {
            Voice.SOPRANO: (60, 79),
            Voice.ALTO: (55, 74),
            Voice.TENOR: (48, 67),
            Voice.BASS: (40, 60),
        }

        # 声部の状態
        self.voices: Dict[Voice, List[int]] = {
            Voice.SOPRANO: [],
            Voice.ALTO: [],
            Voice.TENOR: [],
            Voice.BASS: [],
        }

        # 和声進行
        self.progression: List[ChordProgression] = []

    # ============================================================
    # 共通音判定
    # ============================================================

    def find_common_tones(self, chord1: Set[int], chord2: Set[int]) -> Set[int]:
        """2つの和音の共通音を見つける"""
        return chord1 & chord2

    # ============================================================
    # 反行判定
    # ============================================================

    @staticmethod
    def check_contrary_motion(soprano_prev: int, soprano_new: int,
                              bass_prev: int, bass_new: int) -> bool:
        """反行をチェック"""
        s_motion = soprano_new - soprano_prev
        b_motion = bass_new - bass_prev
        if s_motion == 0 or b_motion == 0:
            return True  # 斜行OK
        return (s_motion > 0 and b_motion < 0) or (s_motion < 0 and b_motion > 0)

    # ============================================================
    # 和声進行の計画
    # ============================================================

    def plan_progression(self, num_chords: int = 16):
        """和声進行を計画（代理和音を含む豊かな進行）"""
        print("\n【和声進行計画】")

        if num_chords >= 16:
            # 代理和音を活用した進行
            # I(T) vi(Tp) IV(S) ii(Sp) V(D) vi(偽終止) iii(Dp) vi(Tp)
            # ii(Sp) V(D) I(T) IV(S) vii°(D代理) iii(Dp) V(D) I(T)
            degrees = [
                ScaleDegree.I,     #  1: 主和音 (T)
                ScaleDegree.VI,    #  2: Iの代理 (Tp)
                ScaleDegree.IV,    #  3: 下属和音 (S)
                ScaleDegree.II,    #  4: IVの代理 (Sp)
                ScaleDegree.V,     #  5: 属和音 (D)
                ScaleDegree.VI,    #  6: 偽終止 (Tp)
                ScaleDegree.III,   #  7: Vの代理 (Dp)
                ScaleDegree.VI,    #  8: Iの代理 (Tp)
                ScaleDegree.II,    #  9: IVの代理 (Sp)
                ScaleDegree.V,     # 10: 属和音 (D)
                ScaleDegree.I,     # 11: 主和音 (T)
                ScaleDegree.IV,    # 12: 下属和音 (S)
                ScaleDegree.VII,   # 13: Vの代理・導音和音 (D)
                ScaleDegree.III,   # 14: 中音和音 (Dp)
                ScaleDegree.V,     # 15: 属和音 (D)
                ScaleDegree.I,     # 16: 完全正格終止 (T)
            ]
            # num_chords に合わせて延長（複数パターンをローテーション）
            extensions = [
                [ScaleDegree.IV, ScaleDegree.VII, ScaleDegree.III, ScaleDegree.VI],
                [ScaleDegree.II, ScaleDegree.V, ScaleDegree.VI, ScaleDegree.IV],
                [ScaleDegree.III, ScaleDegree.VI, ScaleDegree.II, ScaleDegree.V],
                [ScaleDegree.VI, ScaleDegree.II, ScaleDegree.V, ScaleDegree.I],
            ]
            ext_idx = 0
            while len(degrees) < num_chords:
                degrees.extend(extensions[ext_idx % len(extensions)])
                ext_idx += 1
            degrees = degrees[:num_chords]
            # 最後はV-Iで終わる
            degrees[-2] = ScaleDegree.V
            degrees[-1] = ScaleDegree.I
        else:
            pattern = [
                ScaleDegree.I, ScaleDegree.IV,
                ScaleDegree.V, ScaleDegree.I,
            ]
            degrees = []
            for i in range(num_chords):
                degrees.append(pattern[i % len(pattern)])
            degrees[-2] = ScaleDegree.V
            degrees[-1] = ScaleDegree.I

        # ChordProgression に変換
        for i, degree in enumerate(degrees):
            deg_idx = degree.value - 1
            root_pc = self.scale[deg_idx]
            quality = MAJOR_SCALE_QUALITIES[degree]

            triad = self.rules.build_triad(root_pc, quality)

            prog = ChordProgression(
                position=i,
                degree=degree,
                chord_tones=set(triad),
                root_pc=triad[0],
                third_pc=triad[1],
                fifth_pc=triad[2],
            )

            self.progression.append(prog)
            print(f"  {i:2d}: {degree.name}")

    # ============================================================
    # ユーティリティ: 特定ピッチクラスの音域内MIDI値を列挙
    # ============================================================

    @staticmethod
    def _midi_values_for_pc(pc: int, min_midi: int, max_midi: int) -> List[int]:
        """指定ピッチクラスの音域内MIDI値をすべて列挙"""
        values = []
        for oct in range(min_midi // 12, max_midi // 12 + 1):
            v = pc + oct * 12
            if min_midi <= v <= max_midi:
                values.append(v)
        return values

    # ============================================================
    # DP基盤: 静的制約による有効配置の列挙
    # ============================================================

    def _enumerate_valid_voicings(self, prog: ChordProgression) -> List[Voicing]:
        """和音の全有効配置を列挙（静的制約のみ）

        静的制約:
        - 各声部が音域内
        - S > A > T > B（声部交差なし）
        - S-A ≤ 12, A-T ≤ 12（間隔制限）
        - 第三音が存在し重複しない
        - 根音が存在する
        """
        chord_pcs = [prog.root_pc, prog.third_pc, prog.fifth_pc]
        s_min, s_max = self.ranges[Voice.SOPRANO]
        a_min, a_max = self.ranges[Voice.ALTO]
        t_min, t_max = self.ranges[Voice.TENOR]
        b_min, b_max = self.ranges[Voice.BASS]

        # 転回形を含む全候補
        bass_vals = []
        for pc in chord_pcs:
            bass_vals.extend(self._midi_values_for_pc(pc, b_min, b_max))
        tenor_vals = sorted(set(
            v for pc in chord_pcs
            for v in self._midi_values_for_pc(pc, t_min, t_max)
        ))
        alto_vals = sorted(set(
            v for pc in chord_pcs
            for v in self._midi_values_for_pc(pc, a_min, a_max)
        ))
        soprano_vals = sorted(set(
            v for pc in chord_pcs
            for v in self._midi_values_for_pc(pc, s_min, s_max)
        ))

        results = []
        for b in bass_vals:
            for t in tenor_vals:
                if t <= b:
                    continue
                for a in alto_vals:
                    if a <= t:
                        continue
                    if a - t > 12:
                        continue
                    for s in soprano_vals:
                        if s <= a:
                            continue
                        if s - a > 12:
                            continue

                        pcs = [s % 12, a % 12, t % 12, b % 12]
                        if prog.third_pc not in pcs:
                            continue
                        if pcs.count(prog.third_pc) > 1:
                            continue
                        if prog.root_pc not in pcs:
                            continue

                        results.append((s, a, t, b))
        return results

    # ============================================================
    # DP基盤: 遷移制約の判定
    # ============================================================

    def _check_transition(self, prev: Voicing, curr: Voicing) -> bool:
        """遷移制約を満たすか判定

        和声学規則（harmony_rules_complete）:
        - 平行5度・8度の禁止（全6声部ペア）
        - 増音程の旋律的使用禁止（全4声部）

        対位法規則（counterpoint_engine）:
        - 隠伏5度・8度の禁止（外声部: S-B）
        - 7度跳躍の禁止（全4声部）
        - 声部超越の禁止（隣接声部ペア）
        """
        # 対位法エンジンの統合ハード制約
        valid, _ = self.counterpoint.check_transition_hard(prev, curr)
        return valid

    # ============================================================
    # DP基盤: スコアリング（遷移コスト）
    # ============================================================

    def _score_initial(self, v: Voicing, prog: ChordProgression) -> float:
        """初期配置のスコア（低いほど良い）

        音域中央に近い密集配置を優先。
        """
        s, a, t, b = v
        score = 0.0

        # 音域中央への引力（各声部）
        for midi_val, voice in zip(v, [Voice.SOPRANO, Voice.ALTO,
                                        Voice.TENOR, Voice.BASS]):
            lo, hi = self.ranges[voice]
            mid = (lo + hi) / 2
            score += abs(midi_val - mid) * 0.3

        # 密集配置の優先
        score += (s - b) * 0.1

        return score

    def _score_transition(self, prev: Voicing, curr: Voicing,
                          prev_prog: ChordProgression,
                          curr_prog: ChordProgression,
                          is_final: bool = False) -> float:
        """遷移のスコアリング（低いほど良い）

        和声学テクニック:
        - 各声部の移動量（順次進行を優先）
        - 共通音保持のボーナス
        - 上声部の跳躍ペナルティ
        - 反行ボーナス
        - 音域中央への引力
        - 転回形のペナルティ
        - 完全正格終止のボーナス

        対位法テクニック:
        - 声部独立性（全声部同方向を回避）
        - 動きの種類（反行・斜行を優先）
        """
        score = 0.0

        # --- 各声部の移動コスト ---
        for k in range(4):
            interval = abs(curr[k] - prev[k])
            if interval == 0:
                score += 0       # 保持
            elif interval <= 2:
                score += 1       # 順次進行
            elif interval <= 4:
                score += 3       # 3度
            elif interval <= 7:
                score += 6       # 4度・5度
            else:
                score += 12      # 大跳躍

        # --- 上声部の跳躍ペナルティ (S, A, T のみ) ---
        for k in range(3):
            leap = abs(curr[k] - prev[k])
            if leap > 4:
                score += leap * 1.5

        # --- 共通音保持ボーナス ---
        common_pcs = prev_prog.chord_tones & curr_prog.chord_tones
        for k in range(3):  # 上声部のみ
            if prev[k] % 12 in common_pcs and curr[k] == prev[k]:
                score -= 3

        # --- 反行ボーナス（ソプラノ・バス） ---
        if self.check_contrary_motion(prev[0], curr[0], prev[3], curr[3]):
            score -= 2

        # --- 音域中央への引力 ---
        for midi_val, voice in zip(curr, [Voice.SOPRANO, Voice.ALTO,
                                           Voice.TENOR, Voice.BASS]):
            lo, hi = self.ranges[voice]
            mid = (lo + hi) / 2
            score += abs(midi_val - mid) * 0.3

        # --- 転回形のペナルティ ---
        bass_pc = curr[3] % 12
        if bass_pc == curr_prog.root_pc:
            pass  # 基本形: ペナルティなし
        elif bass_pc == curr_prog.third_pc:
            score += 3   # 第1転回形
        elif bass_pc == curr_prog.fifth_pc:
            score += 5   # 第2転回形

        # --- 完全正格終止のボーナス ---
        if is_final and curr_prog.degree == ScaleDegree.I:
            tonic_pc = self.scale[0]
            if curr[0] % 12 == tonic_pc:      # ソプラノ=主音
                score -= 20
            if curr[3] % 12 == tonic_pc:      # バス=根音
                score -= 10

        # --- 対位法: 声部独立性 ---
        score += self.counterpoint.scoring.score_voice_independence(
            list(prev), list(curr)
        ) * 0.5

        # --- 対位法: 動きの種類（全声部ペア） ---
        for i in range(4):
            for j in range(i + 1, 4):
                score += self.counterpoint.scoring.score_motion_type(
                    prev[i], curr[i], prev[j], curr[j]
                ) * 0.15

        return score

    # ============================================================
    # 生成: 動的計画法（ビタビアルゴリズム）
    # ============================================================

    def generate(self, num_chords: int = 16):
        """動的計画法で全体最適の声部配置を探索"""
        print("=" * 70)
        print("声部導音テクニック統合フーガ生成（4声・DP探索）")
        print("=" * 70)

        self.plan_progression(num_chords)
        n = len(self.progression)

        print("\n【DP探索】")

        # Step 1: 各和音の有効配置を列挙
        all_voicings: List[List[Voicing]] = []
        for i, prog in enumerate(self.progression):
            vv = self._enumerate_valid_voicings(prog)
            all_voicings.append(vv)

        print(f"  有効配置数: {[len(v) for v in all_voicings]}")

        # Step 2: DP テーブル
        #   dp_cost[i][j] = 和音0からiまでの最小累積コスト（和音iで配置jを選択）
        #   dp_prev[i][j] = 和音iで配置jを選択した時の、和音i-1での最良配置インデックス

        INF = float('inf')

        # 初期和音のスコア
        dp_cost_prev = []
        for j, v in enumerate(all_voicings[0]):
            dp_cost_prev.append(self._score_initial(v, self.progression[0]))

        dp_prev_table: List[List[int]] = [[] for _ in range(n)]

        # Step 3: 前進パス
        transitions_evaluated = 0
        for i in range(1, n):
            curr_voicings = all_voicings[i]
            prev_voicings = all_voicings[i - 1]
            is_final = (i == n - 1)

            dp_cost_curr = [INF] * len(curr_voicings)
            dp_prev_curr = [-1] * len(curr_voicings)

            for cj, cv in enumerate(curr_voicings):
                best_cost = INF
                best_prev = -1

                for pj, pv in enumerate(prev_voicings):
                    if dp_cost_prev[pj] == INF:
                        continue

                    # 遷移制約チェック
                    if not self._check_transition(pv, cv):
                        continue

                    transitions_evaluated += 1

                    # 遷移コスト
                    t_cost = self._score_transition(
                        pv, cv,
                        self.progression[i - 1],
                        self.progression[i],
                        is_final=is_final,
                    )
                    total = dp_cost_prev[pj] + t_cost

                    if total < best_cost:
                        best_cost = total
                        best_prev = pj

                dp_cost_curr[cj] = best_cost
                dp_prev_curr[cj] = best_prev

            dp_cost_prev = dp_cost_curr
            dp_prev_table[i] = dp_prev_curr

            if (i + 1) % 4 == 0:
                reachable = sum(1 for c in dp_cost_curr if c < INF)
                print(f"  和音{i+1:2d}: 到達可能{reachable}/{len(curr_voicings)}")

        print(f"  遷移評価数: {transitions_evaluated}")

        # Step 4: 逆追跡（バックトラック）
        # 最終和音で最小コストの配置を選択
        best_final_idx = -1
        best_final_cost = INF
        for j, cost in enumerate(dp_cost_prev):
            if cost < best_final_cost:
                best_final_cost = cost
                best_final_idx = j

        if best_final_idx < 0:
            raise ValueError("有効な声部配置経路が見つかりませんでした")

        # 逆追跡で最適経路を復元
        path_indices = [0] * n
        path_indices[n - 1] = best_final_idx
        for i in range(n - 2, -1, -1):
            path_indices[i] = dp_prev_table[i + 1][path_indices[i + 1]]

        # Step 5: 声部に書き込み
        for i in range(n):
            v = all_voicings[i][path_indices[i]]
            self.voices[Voice.SOPRANO].append(v[0])
            self.voices[Voice.ALTO].append(v[1])
            self.voices[Voice.TENOR].append(v[2])
            self.voices[Voice.BASS].append(v[3])

        print(f"\n  最終コスト: {best_final_cost:.1f}")
        print(f"  初期配置: S:{self.voices[Voice.SOPRANO][0]} "
              f"A:{self.voices[Voice.ALTO][0]} "
              f"T:{self.voices[Voice.TENOR][0]} "
              f"B:{self.voices[Voice.BASS][0]}")
        print(f"  終端配置: S:{self.voices[Voice.SOPRANO][-1]} "
              f"A:{self.voices[Voice.ALTO][-1]} "
              f"T:{self.voices[Voice.TENOR][-1]} "
              f"B:{self.voices[Voice.BASS][-1]}")
        print(f"\n✓ 生成完了: {n}個の和音")

    def export_midi(self, filename: str, tempo: int = 80):
        """MIDIファイルに出力"""
        print(f"\n【MIDI出力】")
        print(f"  ファイル: {filename}")

        midi = MIDIWriter(tempo=tempo, ticks_per_beat=480)

        # 4分音符 = 480 ticks
        beat_length = 480

        channel_map = {"soprano": 0, "alto": 1, "tenor": 2, "bass": 3}

        for voice in Voice:
            notes = []
            for i, midi_pitch in enumerate(self.voices[voice]):
                position = i * beat_length
                duration = beat_length
                notes.append((position, midi_pitch, duration))

            midi.add_track_from_notes(notes, channel=channel_map[voice.value])
            print(f"  {voice.value}: {len(notes)}音符")

        midi.write_file(filename)
        print("✓ 完了")


# ============================================================
# テスト実行
# ============================================================

if __name__ == "__main__":
    generator = VoiceLeadingGenerator(tonic_pc=0)  # C major
    generator.generate(num_chords=16)
    generator.export_midi(
        "examples/outputs/voice_leading_fugue.mid",
        tempo=80,
    )

    print("\n" + "=" * 70)
    print("✓ 声部導音テクニック適用フーガ生成完了")
    print("=" * 70)
