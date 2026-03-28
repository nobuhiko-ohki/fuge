"""
調推移モデル — マルコフ連鎖ベースの KeyPathStrategy

Bach フーガのコーパスから学習した調推移パターンを使って、
嬉遊部・中間部の調性経路を生成する。

モデル:
  1次マルコフ連鎖:
    状態 = トニックからの相対音程（半音数） × 長短
    遷移確率 P(next_state | current_state, position)

  position は曲の位置を3区分:
    "early"  (0-33%)
    "middle" (33-66%)
    "late"   (66-100%)

学習データ:
  fugue_features.json の key_changes 系列

使用方法:
  # 学習
  model = KeyTransitionModel()
  model.train_from_features("corpus/analysis/fugue_features.json")
  model.save("corpus/models/key_transition.json")

  # 生成
  strategy = MarkovKeyPathStrategy(model)
  key_path = strategy.generate(start_key, end_key, num_beats)

  # 既存エンジンへの統合
  engine.realize_episode(..., key_path_strategy=strategy)
"""

import json
import math
import os
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from fugue_structure import Key, KeyPath, KeyPathStrategy

# ============================================================
# 相対調の表現
# ============================================================

# 12半音 × 2モード = 24状態
# 状態名: (interval_from_tonic, mode)
# interval_from_tonic: 0-11（半音）
# mode: "major" or "minor"

# 近親調の名前マッピング（表示用）
RELATIVE_KEY_NAMES = {
    (0, "major"): "I",
    (0, "minor"): "i",
    (2, "major"): "II",
    (2, "minor"): "ii",
    (3, "major"): "bIII",
    (3, "minor"): "iii",
    (4, "major"): "III",
    (4, "minor"): "#iii",
    (5, "major"): "IV",
    (5, "minor"): "iv",
    (7, "major"): "V",
    (7, "minor"): "v",
    (8, "major"): "bVI",
    (8, "minor"): "vi",
    (9, "major"): "VI",
    (9, "minor"): "#vi",
    (10, "major"): "bVII",
    (10, "minor"): "vii",
    (11, "major"): "VII",
    (11, "minor"): "#vii",
}

NOTE_TO_PC = {
    'C': 0, 'C#': 1, 'Db': 1,
    'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'Fb': 4,
    'F': 5, 'F#': 6, 'Gb': 6,
    'G': 7, 'G#': 8, 'Ab': 8,
    'A': 9, 'A#': 10, 'Bb': 10,
    'B': 11, 'Cb': 11,
}


def parse_key_name(key_name: str) -> Tuple[int, str]:
    """'C major' → (0, 'major'), 'F# minor' → (6, 'minor')"""
    parts = key_name.strip().split()
    if len(parts) != 2:
        return (0, "major")
    note = parts[0]
    mode = parts[1].lower()
    pc = NOTE_TO_PC.get(note, 0)
    return (pc, mode)


def relative_state(tonic_pc: int, tonic_mode: str,
                   key_pc: int, key_mode: str) -> Tuple[int, str]:
    """絶対調をトニックからの相対状態に変換する。

    Returns:
        (interval, mode): interval は半音数 (0-11), mode は 'major'/'minor'
    """
    interval = (key_pc - tonic_pc) % 12
    return (interval, key_mode)


def state_name(state: Tuple[int, str]) -> str:
    """相対状態の表示名を返す。"""
    return RELATIVE_KEY_NAMES.get(state, f"({state[0]},{state[1]})")


# ============================================================
# マルコフ連鎖モデル
# ============================================================

class KeyTransitionModel:
    """調推移のマルコフ連鎖モデル。

    状態: (interval_from_tonic, mode) — 24状態
    遷移: P(next | current, position)
    position: "early", "middle", "late"

    全位置を統合した遷移確率も保持する（データ不足時のフォールバック）。
    """

    def __init__(self, smoothing: float = 0.1):
        """
        Args:
            smoothing: ラプラス平滑化パラメータ
        """
        self.smoothing = smoothing

        # 遷移カウント: {position: {state: {next_state: count}}}
        self.counts: Dict[str, Dict[Tuple, Dict[Tuple, int]]] = {
            "early": defaultdict(lambda: defaultdict(int)),
            "middle": defaultdict(lambda: defaultdict(int)),
            "late": defaultdict(lambda: defaultdict(int)),
            "all": defaultdict(lambda: defaultdict(int)),
        }

        # 正規化済み遷移確率
        self.probs: Dict[str, Dict[Tuple, Dict[Tuple, float]]] = {}

        # 初期状態分布
        self.initial_counts: Dict[Tuple, int] = defaultdict(int)
        self.initial_probs: Dict[Tuple, float] = {}

        # 終端状態分布
        self.terminal_counts: Dict[Tuple, int] = defaultdict(int)
        self.terminal_probs: Dict[Tuple, float] = {}

        # 全状態セット
        self.states: set = set()

        # 学習データ統計
        self.num_sequences = 0
        self.num_transitions = 0

        # 転調点間の持続拍数統計
        self.hold_durations: List[float] = []
        self.avg_hold_beats: float = 4.0  # デフォルト最低4拍

    def _position_label(self, beat: float, total_beats: float) -> str:
        """拍位置を3区分に分類する。"""
        if total_beats <= 0:
            return "middle"
        ratio = beat / total_beats
        if ratio < 0.33:
            return "early"
        elif ratio < 0.66:
            return "middle"
        else:
            return "late"

    def train_from_features(self, features_path: str):
        """fugue_features.json から学習する。"""
        with open(features_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.train_from_data(data)

    def train_from_data(self, fugue_features: List[Dict]):
        """特徴量辞書のリストから学習する。"""
        for feat in fugue_features:
            key_changes = feat.get("key_changes", [])
            if len(key_changes) < 2:
                continue

            global_key = feat.get("global_key", "C major")
            total_beats = feat.get("total_beats", 100.0)
            tonic_pc, tonic_mode = parse_key_name(global_key)

            # key_changes を相対状態列に変換
            seq = []
            for kc in key_changes:
                beat = kc["beat"]
                kpc, kmode = parse_key_name(kc["key"])
                state = relative_state(tonic_pc, tonic_mode, kpc, kmode)
                position = self._position_label(beat, total_beats)
                seq.append((beat, state, position))

            if not seq:
                continue

            self.num_sequences += 1

            # 初期状態
            self.initial_counts[seq[0][1]] += 1
            self.states.add(seq[0][1])

            # 終端状態
            self.terminal_counts[seq[-1][1]] += 1

            # 遷移カウント + 持続拍数統計
            for i in range(len(seq) - 1):
                beat_i, curr_state, position = seq[i]
                beat_j, next_state, _ = seq[i + 1]

                self.counts[position][curr_state][next_state] += 1
                self.counts["all"][curr_state][next_state] += 1
                self.states.add(curr_state)
                self.states.add(next_state)
                self.num_transitions += 1

                # 転調点間の持続拍数
                duration = beat_j - beat_i
                if duration > 0:
                    self.hold_durations.append(duration)

        # 持続拍数の中央値を計算（平均だと外れ値に弱い）
        if self.hold_durations:
            sorted_d = sorted(self.hold_durations)
            mid = len(sorted_d) // 2
            self.avg_hold_beats = sorted_d[mid]

        # 確率の正規化
        self._normalize()

    def _normalize(self):
        """カウントを確率に変換する。"""
        self.probs = {}
        n_states = max(len(self.states), 1)

        for position in self.counts:
            self.probs[position] = {}
            for state in self.counts[position]:
                total = (sum(self.counts[position][state].values())
                         + self.smoothing * n_states)
                self.probs[position][state] = {}
                for next_state in self.states:
                    count = self.counts[position][state].get(next_state, 0)
                    self.probs[position][state][next_state] = (
                        (count + self.smoothing) / total)

        # 初期状態確率
        total_init = (sum(self.initial_counts.values())
                      + self.smoothing * n_states)
        self.initial_probs = {
            s: (self.initial_counts.get(s, 0) + self.smoothing) / total_init
            for s in self.states
        }

        # 終端状態確率
        total_term = (sum(self.terminal_counts.values())
                      + self.smoothing * n_states)
        self.terminal_probs = {
            s: (self.terminal_counts.get(s, 0) + self.smoothing) / total_term
            for s in self.states
        }

    def transition_prob(self, current: Tuple[int, str],
                        next_state: Tuple[int, str],
                        position: str = "all") -> float:
        """遷移確率 P(next | current, position) を返す。"""
        if position in self.probs and current in self.probs[position]:
            return self.probs[position][current].get(
                next_state, self.smoothing)
        # フォールバック: 全位置
        if "all" in self.probs and current in self.probs["all"]:
            return self.probs["all"][current].get(
                next_state, self.smoothing)
        # 未知状態: 均等分布
        return 1.0 / max(len(self.states), 1)

    def sample_next(self, current: Tuple[int, str],
                    position: str = "all",
                    rng: Optional[random.Random] = None) -> Tuple[int, str]:
        """現在の状態から次の状態をサンプリングする。"""
        r = rng or random
        probs = {}
        for s in self.states:
            probs[s] = self.transition_prob(current, s, position)

        # 正規化
        total = sum(probs.values())
        if total <= 0:
            return current

        threshold = r.random() * total
        cumulative = 0.0
        for s, p in probs.items():
            cumulative += p
            if cumulative >= threshold:
                return s
        return current

    def most_likely_next(self, current: Tuple[int, str],
                         position: str = "all") -> Tuple[int, str]:
        """最も確率の高い次の状態を返す。"""
        best = current
        best_prob = -1.0
        for s in self.states:
            p = self.transition_prob(current, s, position)
            if p > best_prob:
                best_prob = p
                best = s
        return best

    # ============================================================
    # 保存・読み込み
    # ============================================================

    def save(self, path: str):
        """モデルを JSON として保存する。"""
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

        def state_to_str(s):
            return f"{s[0]}_{s[1]}"

        def str_to_state(s):
            parts = s.split('_', 1)
            return (int(parts[0]), parts[1])

        data = {
            "smoothing": self.smoothing,
            "num_sequences": self.num_sequences,
            "num_transitions": self.num_transitions,
            "avg_hold_beats": self.avg_hold_beats,
            "states": [state_to_str(s) for s in sorted(self.states)],
            "counts": {},
            "initial_counts": {state_to_str(s): c
                               for s, c in self.initial_counts.items()},
            "terminal_counts": {state_to_str(s): c
                                for s, c in self.terminal_counts.items()},
        }

        for position in self.counts:
            data["counts"][position] = {}
            for state in self.counts[position]:
                sk = state_to_str(state)
                data["counts"][position][sk] = {
                    state_to_str(ns): c
                    for ns, c in self.counts[position][state].items()
                }

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, path: str):
        """JSON からモデルを復元する。"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        def str_to_state(s):
            parts = s.split('_', 1)
            return (int(parts[0]), parts[1])

        self.smoothing = data.get("smoothing", 0.1)
        self.num_sequences = data.get("num_sequences", 0)
        self.num_transitions = data.get("num_transitions", 0)
        self.avg_hold_beats = data.get("avg_hold_beats", 4.0)
        self.states = {str_to_state(s) for s in data.get("states", [])}

        self.initial_counts = defaultdict(int)
        for sk, c in data.get("initial_counts", {}).items():
            self.initial_counts[str_to_state(sk)] = c

        self.terminal_counts = defaultdict(int)
        for sk, c in data.get("terminal_counts", {}).items():
            self.terminal_counts[str_to_state(sk)] = c

        self.counts = {}
        for position, states_dict in data.get("counts", {}).items():
            self.counts[position] = defaultdict(lambda: defaultdict(int))
            for sk, nexts in states_dict.items():
                state = str_to_state(sk)
                for nsk, c in nexts.items():
                    self.counts[position][state][str_to_state(nsk)] = c

        self._normalize()

    # ============================================================
    # 診断
    # ============================================================

    def summary(self) -> str:
        """モデルの要約を返す。"""
        lines = [
            f"KeyTransitionModel: {self.num_sequences} 曲, "
            f"{self.num_transitions} 遷移, "
            f"{len(self.states)} 状態",
            f"転調点間の持続拍数（中央値）: {self.avg_hold_beats:.1f}拍",
            "",
        ]

        # 主要遷移（全位置）
        if "all" in self.probs:
            lines.append("主要遷移 (上位):")
            transitions = []
            for state in self.probs["all"]:
                for ns, p in self.probs["all"][state].items():
                    if p > 0.05:  # 5% 以上のみ
                        transitions.append((state, ns, p))
            transitions.sort(key=lambda x: -x[2])
            for s, ns, p in transitions[:20]:
                lines.append(
                    f"  {state_name(s):8s} → {state_name(ns):8s}: "
                    f"{p:.1%}")

        # 初期状態
        lines.append("\n初期状態:")
        for s, p in sorted(self.initial_probs.items(),
                           key=lambda x: -x[1])[:5]:
            lines.append(f"  {state_name(s):8s}: {p:.1%}")

        return "\n".join(lines)


# ============================================================
# MarkovKeyPathStrategy — KeyPathStrategy の学習版実装
# ============================================================

PC_TO_NOTE = {
    0: 'C', 1: 'C#', 2: 'D', 3: 'Eb', 4: 'E', 5: 'F',
    6: 'F#', 7: 'G', 8: 'Ab', 9: 'A', 10: 'Bb', 11: 'B',
}


class MarkovKeyPathStrategy(KeyPathStrategy):
    """マルコフ連鎖モデルに基づく KeyPathStrategy。

    学習した遷移確率でサンプリングしつつ、
    始点調と終点調の制約を満たす経路を生成する。

    近親調制約:
      転調先は主調から見て近親調に限定する。
      長調: I, ii, iii, IV, V, vi, i（同主短調）
      短調: i, III, iv, v, VI, VII, I（同主長調）
      これによりバッハの短いフーガに相応しい自然な調性計画を実現する。

    Args:
        model: 学習済み KeyTransitionModel
        seed: 乱数シード（再現性のため）
        deterministic: True なら最尤遷移を使用
    """

    # 近親調: (トニックからの半音数, モード) のセット
    # 長調の近親調
    CLOSE_KEYS_MAJOR = {
        (0, "major"),   # I  (主調)
        (0, "minor"),   # i  (同主短調)
        (2, "minor"),   # ii
        (4, "minor"),   # iii
        (5, "major"),   # IV
        (5, "minor"),   # iv (借用)
        (7, "major"),   # V
        (7, "minor"),   # v  (借用)
        (9, "minor"),   # vi
        (9, "major"),   # VI (借用)
    }

    # 短調の近親調
    CLOSE_KEYS_MINOR = {
        (0, "minor"),   # i  (主調)
        (0, "major"),   # I  (同主長調)
        (3, "major"),   # III (平行長調)
        (3, "minor"),   # iii
        (5, "minor"),   # iv
        (5, "major"),   # IV (借用)
        (7, "minor"),   # v
        (7, "major"),   # V  (借用: 和声的短音階)
        (8, "major"),   # bVI
        (10, "major"),  # bVII
    }

    def __init__(self, model: KeyTransitionModel,
                 seed: Optional[int] = None,
                 deterministic: bool = False):
        self.model = model
        self.rng = random.Random(seed)
        self.deterministic = deterministic

    def _get_close_keys(self, tonic_mode: str) -> set:
        """主調のモードに応じた近親調セットを返す。"""
        if tonic_mode == "major":
            return self.CLOSE_KEYS_MAJOR
        else:
            return self.CLOSE_KEYS_MINOR

    def _sample_close_key(
        self, current: Tuple[int, str], position: str,
        close_keys: set,
    ) -> Tuple[int, str]:
        """近親調に制限してサンプリングする。

        マルコフモデルの遷移確率を近親調のみでフィルタし、
        確率を再正規化してからサンプリングする。
        """
        probs = {}
        for s in close_keys:
            if s in self.model.states:
                probs[s] = self.model.transition_prob(current, s, position)
            else:
                # モデルに未登録の近親調: 平滑化確率を使用
                probs[s] = self.model.smoothing / max(len(self.model.states), 1)

        total = sum(probs.values())
        if total <= 0:
            return current

        if self.deterministic:
            return max(probs, key=probs.get)

        threshold = self.rng.random() * total
        cumulative = 0.0
        for s, p in probs.items():
            cumulative += p
            if cumulative >= threshold:
                return s
        return current

    def generate(self, start_key: Key, end_key: Key,
                 num_beats: int) -> KeyPath:
        """マルコフモデルで調性経路を生成する。

        転調点単位で経路を生成し、各調をコーパスの中央値持続拍数
        (avg_hold_beats) 前後維持する。

        制約:
          - beat 0 は start_key
          - 最終区間は end_key
          - 途中はモデルからサンプリング
          - 各調は min_hold 拍以上持続
        """
        if num_beats <= 0:
            return KeyPath(start_key, end_key, [])

        if num_beats <= 2 or start_key == end_key:
            if start_key == end_key:
                return KeyPath(start_key, end_key,
                               [start_key] * num_beats)
            pivot = max(1, num_beats - 1)
            return KeyPath(start_key, end_key,
                           [start_key] * pivot
                           + [end_key] * (num_beats - pivot))

        # トニック基準の相対状態に変換
        tonic_pc = start_key.tonic_pc
        tonic_mode = start_key.mode

        start_state = relative_state(
            tonic_pc, tonic_mode,
            start_key.tonic_pc, start_key.mode)
        end_state = relative_state(
            tonic_pc, tonic_mode,
            end_key.tonic_pc, end_key.mode)

        # 転調点単位の経路を生成
        # min_hold: 各調の最低持続拍数（コーパス中央値の75%、最低4拍）
        # 古典和声の転調手順（旧調確立→ピボット→V→I）には最低4拍必要
        min_hold = max(4, int(self.model.avg_hold_beats * 0.75))

        # 終点用に最低 min_hold 拍を確保（十分な調性確立のため）
        end_reserve = max(min_hold, num_beats // 3)
        free_beats = num_beats - end_reserve

        # 近親調フィルタ: 主調からの相対状態で制限
        close_keys = self._get_close_keys(tonic_mode)

        # 転調点リスト: [(state, start_beat), ...]
        key_segments: List[Tuple[Tuple[int, str], int]] = []
        key_segments.append((start_state, 0))

        beat = min_hold  # 最初の調を min_hold 拍は維持
        current = start_state

        while beat < free_beats:
            position = self.model._position_label(beat, num_beats)

            # 近親調のみを候補としてサンプリング
            next_s = self._sample_close_key(
                current, position, close_keys)

            # 同一調が連続した場合はスキップ（持続を延長）
            if next_s == current:
                beat += min_hold
                continue

            key_segments.append((next_s, beat))
            current = next_s
            beat += min_hold

        # 転調回数の上限: エピソード長に対して妥当な回数に制限
        # 12拍で最大2回、6拍で最大1回
        max_mods = max(1, num_beats // 6)
        if len(key_segments) - 1 > max_mods:
            # 後半の転調を切り捨て（開始調を維持しつつ回数を制限）
            key_segments = key_segments[:max_mods + 1]

        # 終点区間を追加（end_state が最後でなければ）
        if key_segments[-1][0] != end_state:
            # 終点着地に十分な拍数を確保
            landing_beat = num_beats - end_reserve
            # 直前の区間と重複しないよう調整
            if key_segments and key_segments[-1][1] >= landing_beat:
                landing_beat = key_segments[-1][1] + min_hold
            if landing_beat < num_beats:
                key_segments.append((end_state, landing_beat))

        # セグメント → 拍単位の配列に展開
        beat_states = [start_state] * num_beats
        for idx, (state, seg_beat) in enumerate(key_segments):
            # 次のセグメントの開始拍まで（最後は末尾まで）
            if idx + 1 < len(key_segments):
                seg_end = key_segments[idx + 1][1]
            else:
                seg_end = num_beats
            for b in range(seg_beat, min(seg_end, num_beats)):
                beat_states[b] = state

        # 相対状態 → 絶対 Key に変換
        beat_keys = []
        for interval, mode in beat_states:
            abs_pc = (tonic_pc + interval) % 12
            note_name = PC_TO_NOTE[abs_pc]
            beat_keys.append(Key(note_name, mode))

        return KeyPath(start_key, end_key, beat_keys)


# ============================================================
# テスト・学習スクリプト
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="調推移モデルの学習と評価")
    parser.add_argument(
        '--features', '-f',
        default='./corpus/analysis/fugue_features.json',
        help='フーガ特徴量 JSON')
    parser.add_argument(
        '--output', '-o',
        default='./corpus/models/key_transition.json',
        help='モデル出力パス')
    parser.add_argument(
        '--test', action='store_true',
        help='テスト生成を実行')
    args = parser.parse_args()

    # 学習
    print("=== 調推移モデル学習 ===\n")
    model = KeyTransitionModel(smoothing=0.1)
    model.train_from_features(args.features)
    print(model.summary())

    # 保存
    model.save(args.output)
    print(f"\nモデル保存: {args.output}")

    # テスト生成
    if args.test:
        print("\n=== テスト生成 ===\n")
        strategy = MarkovKeyPathStrategy(model, seed=42)

        test_cases = [
            (Key('C', 'major'), Key('G', 'major'), 8),
            (Key('C', 'major'), Key('A', 'minor'), 12),
            (Key('G', 'major'), Key('C', 'major'), 6),
            (Key('D', 'minor'), Key('F', 'major'), 10),
        ]

        for start, end, beats in test_cases:
            kp = strategy.generate(start, end, beats)
            path_str = " → ".join(
                f"{k.tonic} {k.mode}"
                for i, k in enumerate(kp.beat_keys)
                if i == 0 or kp.beat_keys[i] != kp.beat_keys[i - 1])
            mods = kp.modulation_points()
            print(f"  {start.tonic} {start.mode} → "
                  f"{end.tonic} {end.mode} ({beats}拍):")
            print(f"    経路: {path_str}")
            print(f"    転調点: {mods}")
            print()
