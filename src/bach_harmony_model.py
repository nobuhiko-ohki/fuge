"""
バッハ和声進行モデル — コーパス学習ベースの和声選択

目的:
  ルールベースの _select_for_beat を、コーパスから学習した
  和声進行パターンで置換する。

モデル構成:
  1. ChordProgressionModel: 和音バイグラム/トリグラムの遷移確率
     - 状態: (root_interval_from_key, quality)
     - 条件: 直前の和音 + 現在の旋律音のピッチクラス
  2. CounterpointPatternModel: 対旋律の音程パターン
     - 和音音に対する相対音程の n-gram
     - バッハ的フィグレーション（経過音、刺繍音等）の確率

学習データ:
  - PCP 系列 → 拍単位の和音推定 → 和音バイグラム
  - MIDI 生データ → 声部間音程パターン
"""

import json
import os
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# ============================================================
# 定数
# ============================================================

NOTE_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']

NOTE_TO_PC = {
    'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'Fb': 4, 'E#': 5, 'F': 5, 'F#': 6, 'Gb': 6,
    'G': 7, 'G#': 8, 'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10,
    'B': 11, 'Cb': 11,
}

# 和音テンプレート（ルートからの半音数セット）
CHORD_TEMPLATES = {
    'major':  {0, 4, 7},
    'minor':  {0, 3, 7},
    'dim':    {0, 3, 6},
    'dom7':   {0, 4, 7, 10},
    'min7':   {0, 3, 7, 10},
    'maj7':   {0, 4, 7, 11},
    'dim7':   {0, 3, 6, 9},
    'hdim7':  {0, 3, 6, 10},
}

# 和音の性質ごとの優先度（バッハ的な頻度を反映）
QUALITY_PRIORITY = {
    'major': 0, 'minor': 1, 'dom7': 2, 'dim': 3,
    'min7': 4, 'hdim7': 5, 'dim7': 6, 'maj7': 7, 'aug': 8,
}


# ============================================================
# PCP → 和音推定
# ============================================================

def pcp_to_chord(pcp: List[float], threshold: float = 0.08
                 ) -> Optional[Tuple[int, str]]:
    """PCP ベクトルから最尤和音を推定する。

    Returns:
        (root_pc, quality) or None
    """
    if not pcp or max(pcp) < 0.01:
        return None

    best_score = -1.0
    best_chord = None

    for root in range(12):
        for quality, template in CHORD_TEMPLATES.items():
            # 和音構成音の PCP 値の和
            score = sum(pcp[(root + interval) % 12] for interval in template)
            # 構成音数で正規化（三和音と七和音を公平に比較）
            score /= len(template)
            # 存在しない構成音へのペナルティ
            for interval in template:
                pc = (root + interval) % 12
                if pcp[pc] < threshold:
                    score -= 0.05

            if score > best_score:
                best_score = score
                best_chord = (root, quality)

    return best_chord


# ============================================================
# 声部認識型の和音推定
# ============================================================

# --- Key クラスの軽量インポート ---
# fugue_structure.Key に依存せず、ここで最小限の調情報を構築する
# （循環インポート回避のため）

_MAJOR_INTERVALS = [0, 2, 4, 5, 7, 9, 11]
_HARMONIC_MINOR_INTERVALS = [0, 2, 3, 5, 7, 8, 11]


def _build_scale(tonic_pc: int, mode: str) -> List[int]:
    """調の音階をピッチクラスのリストで返す"""
    intervals = _MAJOR_INTERVALS if mode == 'major' else _HARMONIC_MINOR_INTERVALS
    return [(tonic_pc + i) % 12 for i in intervals]


def _build_all_triads(tonic_pc: int, mode: str) -> List[Tuple[int, int, str, Set[int]]]:
    """調のダイアトニック三和音を返す

    Returns: [(degree, root_pc, quality, tones_set), ...]
    """
    scale = _build_scale(tonic_pc, mode)
    if mode == 'major':
        qualities = ['major', 'minor', 'minor', 'major',
                     'major', 'minor', 'dim']
    else:
        qualities = ['minor', 'dim', 'major', 'minor',
                     'major', 'major', 'dim']

    triads = []
    for degree in range(7):
        root = scale[degree]
        q = qualities[degree]
        intervals = {'major': [0, 4, 7], 'minor': [0, 3, 7],
                     'dim': [0, 3, 6], 'aug': [0, 4, 8]}[q]
        tones = frozenset((root + iv) % 12 for iv in intervals)
        triads.append((degree, root, q, tones))
    return triads


def _build_all_sevenths(tonic_pc: int, mode: str) -> List[Tuple[int, int, str, Set[int]]]:
    """調のダイアトニック七の和音を返す"""
    scale = _build_scale(tonic_pc, mode)
    if mode == 'major':
        qualities = ['maj7', 'min7', 'min7', 'maj7',
                     'dom7', 'min7', 'hdim7']
    else:
        qualities = ['min7', 'hdim7', 'maj7', 'min7',
                     'dom7', 'maj7', 'dim7']

    sevenths = []
    intervals_map = {
        'dom7': [0, 4, 7, 10], 'maj7': [0, 4, 7, 11],
        'min7': [0, 3, 7, 10], 'hdim7': [0, 3, 6, 10],
        'dim7': [0, 3, 6, 9],
    }
    for degree in range(7):
        root = scale[degree]
        q = qualities[degree]
        ivs = intervals_map[q]
        tones = frozenset((root + iv) % 12 for iv in ivs)
        sevenths.append((degree, root, q, tones))
    return sevenths


class VoiceAwareChordEstimator:
    """声部の実音に基づく和音推定

    PCPテンプレートマッチングに代わり、各拍の声部音（拍頭音）を
    直接的に和声音として説明できる和音を選ぶ。

    優先順位:
      1. 拍の全音が構成音に含まれる和音（非和声音ゼロ）
      2. 根音が最低音にある解釈（基本位置）
      3. ダイアトニック三和音 > 七の和音 > 非ダイアトニック
      4. 機能和声的に前後と整合する解釈（逆行回避）
    """

    # ドミナント機能の度数
    DOMINANT_DEGREES = {4, 6}     # V, vii°
    # サブドミナント機能の度数
    SUBDOMINANT_DEGREES = {1, 3}  # ii, IV
    # 逆行禁止パターン: (from_degree, to_degree)
    RETROGRESSION = {(4, 1), (4, 3), (6, 1), (6, 3)}

    def __init__(self):
        self._cache: Dict[Tuple[int, str], List] = {}

    def _get_candidates(self, tonic_pc: int, mode: str):
        """調のダイアトニック三和音＋七の和音の候補リストをキャッシュ付きで返す"""
        cache_key = (tonic_pc, mode)
        if cache_key in self._cache:
            return self._cache[cache_key]

        triads = _build_all_triads(tonic_pc, mode)
        sevenths = _build_all_sevenths(tonic_pc, mode)

        # (degree, root_pc, quality, tones_set, is_seventh, rank)
        # rank: 三和音=0, 七の和音=1  (小さいほど優先)
        candidates = []
        for deg, root, q, tones in triads:
            candidates.append((deg, root, q, tones, False, 0))
        for deg, root, q, tones in sevenths:
            candidates.append((deg, root, q, tones, True, 1))

        self._cache[cache_key] = candidates
        return candidates

    def estimate_chord(
        self,
        beat_pcs: Set[int],      # 拍の全声部のピッチクラス集合
        bass_pc: int,            # 最低音のピッチクラス
        tonic_pc: int,           # 現在の調のトニックPC
        mode: str,               # 'major' or 'minor'
        prev_degree: Optional[int] = None,  # 直前の和音の度数
    ) -> Optional[Tuple[int, int, str, Set[int], float]]:
        """和音を推定する

        Returns:
            (degree, root_pc, quality, tones, score) or None
        """
        if not beat_pcs:
            return None

        candidates = self._get_candidates(tonic_pc, mode)
        scored = []

        for deg, root, quality, tones, is_seventh, rank in candidates:
            tones_set = set(tones)

            # --- 包含スコア: 拍の音がどれだけ和音構成音に含まれるか ---
            covered = len(beat_pcs & tones_set)
            uncovered = len(beat_pcs) - covered
            coverage = covered / len(beat_pcs) if beat_pcs else 0

            # 非和声音が多すぎる候補は除外（半分以上が非和声音）
            if coverage < 0.5:
                continue

            score = coverage * 10.0  # 基本スコア: 0〜10

            # --- 基本位置ボーナス（根音が最低音）---
            if bass_pc == root:
                score += 3.0
            # 第一転回（第3音が最低音）もやや許容
            elif bass_pc in tones_set:
                score += 1.0

            # --- ダイアトニック三和音ボーナス ---
            if not is_seventh:
                score += 2.0  # 三和音 > 七の和音

            # --- 主要三和音ボーナス (I, IV, V) ---
            if deg in (0, 3, 4):
                score += 1.5
            elif deg in (1, 5):
                score += 0.5

            # --- 機能和声整合性: 逆行ペナルティ ---
            if prev_degree is not None:
                if (prev_degree, deg) in self.RETROGRESSION:
                    score -= 5.0  # 強いペナルティ

            # --- 完全包含のボーナス ---
            if uncovered == 0:
                score += 4.0

            scored.append((score, deg, root, quality, tones_set))

        if not scored:
            return None

        scored.sort(key=lambda x: -x[0])
        best_score, best_deg, best_root, best_q, best_tones = scored[0]
        return (best_deg, best_root, best_q, best_tones, best_score)


# ============================================================
# 階層的転調追跡
# ============================================================

class HierarchicalKeyTracker:
    """階層的な調性追跡

    まず現在の調で和音進行を説明できるか試み、
    不自然な進行が検出されたら近親調で再解釈する。

    近親調の試行順序:
      1. 属調 (V)
      2. 平行調 (relative)
      3. 下属調 (IV)
      4. 同主調 (parallel)
    """

    # 逆行パターン（これが出たら転調を疑う）
    RETROGRESSION = {(4, 1), (4, 3), (6, 1), (6, 3)}

    # 自然な進行: D→T は常に自然
    NATURAL_RESOLUTIONS = {(4, 0), (4, 5), (6, 0)}  # V→I, V→vi, vii°→I

    def __init__(self, estimator: Optional[VoiceAwareChordEstimator] = None):
        self.estimator = estimator or VoiceAwareChordEstimator()

    def _get_close_keys(self, tonic_pc: int, mode: str) -> List[Tuple[int, str]]:
        """近親調のリストを (tonic_pc, mode) のタプルで返す"""
        scale = _build_scale(tonic_pc, mode)
        keys = []
        if mode == 'major':
            keys.append((scale[4], 'major'))   # 属調 V
            keys.append((scale[5], 'minor'))   # 平行調 vi
            keys.append((scale[3], 'major'))   # 下属調 IV
            keys.append((tonic_pc, 'minor'))   # 同主調
            keys.append((scale[1], 'minor'))   # ii
        else:
            keys.append((scale[4], 'major'))   # 属調（和声的短音階のV=長調）
            keys.append((scale[2], 'major'))   # 平行調 III
            keys.append((scale[3], 'minor'))   # 下属調 iv
            keys.append((tonic_pc, 'major'))   # 同主調
            keys.append((scale[6], 'major'))   # VII (自然短音階のVII)
        return keys

    def track(
        self,
        beat_data: List[Tuple[Set[int], int]],  # [(beat_pcs, bass_pc), ...]
        initial_tonic_pc: int,
        initial_mode: str,
    ) -> List[Tuple[Tuple[int, str], Tuple[int, int, str]]]:
        """各拍に (調, 和音) のペアを返す

        Args:
            beat_data: 拍ごとの (ピッチクラス集合, バスPC)
            initial_tonic_pc: 曲頭の調のトニックPC
            initial_mode: 'major' or 'minor'

        Returns:
            [((tonic_pc, mode), (degree, root_pc, quality)), ...]
        """
        current_tonic = initial_tonic_pc
        current_mode = initial_mode
        prev_degree: Optional[int] = None
        results = []

        # 前方探索用のウィンドウサイズ
        LOOKAHEAD = 3

        for i, (beat_pcs, bass_pc) in enumerate(beat_data):
            if not beat_pcs:
                # 音がない拍: 前の和音を継続
                if results:
                    results.append(results[-1])
                else:
                    results.append(((current_tonic, current_mode), (0, current_tonic, 'major')))
                continue

            # --- 1. 現在の調で推定 ---
            est = self.estimator.estimate_chord(
                beat_pcs, bass_pc, current_tonic, current_mode, prev_degree)

            # --- 2. 逆行検出 → 転調の試行 ---
            needs_reinterpret = False
            if est is not None:
                deg = est[0]
                if prev_degree is not None and (prev_degree, deg) in self.RETROGRESSION:
                    needs_reinterpret = True
                elif est[4] < 5.0:  # スコアが低い（包含率が低い）
                    needs_reinterpret = True
            else:
                needs_reinterpret = True

            if needs_reinterpret:
                best_key = None
                best_result = est
                best_score = est[4] if est else -999

                for alt_tonic, alt_mode in self._get_close_keys(current_tonic, current_mode):
                    alt_est = self.estimator.estimate_chord(
                        beat_pcs, bass_pc, alt_tonic, alt_mode, None)  # prev_degree=None（新調）

                    if alt_est is None:
                        continue

                    alt_score = alt_est[4]

                    # 転調先での解釈が大幅に改善される場合のみ採用
                    # さらに前方数拍も転調先で自然か確認
                    if alt_score > best_score + 2.0:
                        # 前方確認: 次の2-3拍も新調で良好か
                        forward_ok = True
                        fwd_prev = alt_est[0]
                        for j in range(1, min(LOOKAHEAD + 1, len(beat_data) - i)):
                            fwd_pcs, fwd_bass = beat_data[i + j]
                            if not fwd_pcs:
                                continue
                            fwd_est = self.estimator.estimate_chord(
                                fwd_pcs, fwd_bass, alt_tonic, alt_mode, fwd_prev)
                            if fwd_est is None or fwd_est[4] < 5.0:
                                forward_ok = False
                                break
                            fwd_prev = fwd_est[0]

                        if forward_ok:
                            best_key = (alt_tonic, alt_mode)
                            best_result = alt_est
                            best_score = alt_score

                if best_key is not None:
                    current_tonic, current_mode = best_key
                    est = best_result

            if est is not None:
                deg, root, quality, tones, score = est
                results.append(((current_tonic, current_mode), (deg, root, quality)))
                prev_degree = deg
            else:
                # フォールバック: 現在の調のI度
                results.append(((current_tonic, current_mode), (0, current_tonic, 'major' if current_mode == 'major' else 'minor')))
                prev_degree = 0

        return results


# ============================================================
# 拍ごとの声部音抽出
# ============================================================

def extract_beat_voices(midi_notes: list, ticks_per_beat: int,
                        total_ticks: int) -> List[Tuple[Set[int], int]]:
    """MIDIノートリストから拍ごとの声部音（ピッチクラス集合）と最低音を抽出

    Args:
        midi_notes: MIDINote のリスト（.pitch, .start_tick, .end_tick を持つ）
        ticks_per_beat: 1拍のtick数
        total_ticks: 曲全体のtick数

    Returns:
        [(pcs_set, bass_pc), ...] — 拍数分のリスト
    """
    num_beats = total_ticks // ticks_per_beat + 1
    result = []

    for beat in range(num_beats):
        beat_start = beat * ticks_per_beat
        beat_end = beat_start + ticks_per_beat

        # この拍に発音中のノートを収集
        # 拍頭（beat_start）付近で発音開始、または持続中のノート
        pitches = []
        for n in midi_notes:
            # 拍の前半（拍頭付近）で鳴っている音を優先
            # 拍頭の前後1/4拍以内に開始、または拍を跨いで持続
            onset_window = ticks_per_beat // 4
            if (n.start_tick >= beat_start - onset_window and
                n.start_tick < beat_start + onset_window):
                pitches.append(n.pitch)
            elif n.start_tick < beat_start and n.end_tick > beat_start:
                # 持続音
                pitches.append(n.pitch)

        if not pitches:
            result.append((set(), 0))
            continue

        pcs = set(p % 12 for p in pitches)
        bass_pc = min(pitches) % 12
        result.append((pcs, bass_pc))

    return result


# ============================================================
# 和声進行モデル
# ============================================================

class ChordProgressionModel:
    """和音バイグラム/トリグラムの遷移確率モデル。

    状態空間:
      和音 = (root_interval, quality)
      root_interval: 調のトニックからの半音数 (0-11)
      quality: 'major', 'minor', 'dim', 'dom7' 等

    遷移:
      P(next_chord | prev_chord, melody_pc)
      melody_pc: 現拍の旋律音のピッチクラス（条件付き）

    これにより、旋律音に適合しつつバッハ的な和声語彙を持つ
    進行が生成される。
    """

    def __init__(self, smoothing: float = 0.01):
        self.smoothing = smoothing

        # バイグラム: P(next | prev)
        # key: prev_chord, value: {next_chord: count}
        self.bigram_counts: Dict[Tuple, Dict[Tuple, int]] = defaultdict(
            lambda: defaultdict(int))

        # 旋律条件付き: P(chord | melody_pc)
        # 旋律音を含む和音の分布
        self.melody_chord_counts: Dict[int, Dict[Tuple, int]] = defaultdict(
            lambda: defaultdict(int))

        # 正規化済み確率
        self.bigram_probs: Dict[Tuple, Dict[Tuple, float]] = {}
        self.melody_chord_probs: Dict[int, Dict[Tuple, float]] = {}

        # 全和音セット
        self.chords: Set[Tuple] = set()

        # 統計
        self.num_sequences = 0
        self.num_transitions = 0

    def train_from_features(self, features_path: str):
        """fugue_features.json から学習する。"""
        with open(features_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.train_from_data(data)

    def train_from_data(self, fugue_features: List[Dict]):
        """PCP 系列から和音進行を学習する。"""
        for feat in fugue_features:
            pcp_seq = feat.get('pcp_sequence', [])
            if len(pcp_seq) < 4:
                continue

            global_key = feat.get('global_key', 'C major')
            parts = global_key.split()
            tonic_pc = NOTE_TO_PC.get(parts[0], 0)

            # PCP → 和音系列（トニック相対）
            chord_seq = []
            for pcp in pcp_seq:
                ch = pcp_to_chord(pcp)
                if ch is None:
                    chord_seq.append(None)
                    continue
                root, quality = ch
                rel_root = (root - tonic_pc) % 12
                chord_seq.append((rel_root, quality))

            # None を除外した連続和音ペアで学習
            valid_chords = [(i, c) for i, c in enumerate(chord_seq) if c is not None]

            if len(valid_chords) < 2:
                continue

            self.num_sequences += 1

            for idx in range(len(valid_chords) - 1):
                _, prev = valid_chords[idx]
                _, curr = valid_chords[idx + 1]

                self.bigram_counts[prev][curr] += 1
                self.chords.add(prev)
                self.chords.add(curr)
                self.num_transitions += 1

            # 旋律条件付き: PCP のピーク音と和音の関係
            for _, chord in valid_chords:
                root, quality = chord
                # この和音の構成音を旋律音として記録
                template = CHORD_TEMPLATES.get(quality, {0, 4, 7})
                for interval in template:
                    melody_pc = (root + interval) % 12
                    # トニック相対の旋律音
                    rel_melody = (melody_pc - 0) % 12  # 和音は既にトニック相対
                    self.melody_chord_counts[rel_melody][chord] += 1

        self._normalize()

    def _normalize(self):
        """確率を正規化する。"""
        n_chords = max(len(self.chords), 1)

        # バイグラム
        self.bigram_probs = {}
        for prev in self.bigram_counts:
            total = (sum(self.bigram_counts[prev].values())
                     + self.smoothing * n_chords)
            self.bigram_probs[prev] = {}
            for chord in self.chords:
                count = self.bigram_counts[prev].get(chord, 0)
                self.bigram_probs[prev][chord] = (
                    (count + self.smoothing) / total)

        # 旋律条件付き
        self.melody_chord_probs = {}
        for mel_pc in self.melody_chord_counts:
            total = (sum(self.melody_chord_counts[mel_pc].values())
                     + self.smoothing * n_chords)
            self.melody_chord_probs[mel_pc] = {}
            for chord in self.chords:
                count = self.melody_chord_counts[mel_pc].get(chord, 0)
                self.melody_chord_probs[mel_pc][chord] = (
                    (count + self.smoothing) / total)

    def train_from_midi_voices(self, midi_dir: str, max_files: int = 60):
        """声部認識型の和音推定＋階層的転調追跡でMIDIコーパスを学習する。

        pcp_to_chord() に代わり VoiceAwareChordEstimator を使用し、
        global_key 相対化に代わり HierarchicalKeyTracker のローカルキーを使用。
        """
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from midi_reader import MIDIReader
        from fugue_analyzer import estimate_key, compute_pcp

        reader = MIDIReader()
        estimator = VoiceAwareChordEstimator()
        tracker = HierarchicalKeyTracker(estimator)

        # MIDI ファイルを収集
        midi_files = []
        for dirpath, _, filenames in os.walk(midi_dir):
            for fname in filenames:
                if fname.lower().endswith('.mid'):
                    midi_files.append(os.path.join(dirpath, fname))

        files_processed = 0
        for fpath in midi_files:
            if files_processed >= max_files:
                break
            try:
                midi = reader.read(fpath)
            except Exception:
                continue
            if not midi or not midi.all_notes:
                continue

            tpb = midi.ticks_per_beat or 480

            # 曲全体の調を推定
            global_pcp = [0.0] * 12
            for n in midi.all_notes:
                dur = max(n.end_tick - n.start_tick, 1)
                global_pcp[n.pitch % 12] += dur
            total = sum(global_pcp)
            if total > 0:
                global_pcp = [v / total for v in global_pcp]

            key_info = estimate_key(global_pcp)
            if key_info is None:
                continue
            # KeyEstimate オブジェクト: .tonic (int PC), .mode (str)
            tonic_pc = key_info.tonic
            mode = key_info.mode

            # 拍ごとの声部音を抽出
            beat_data = extract_beat_voices(
                midi.all_notes, tpb, midi.duration_ticks)

            if len(beat_data) < 4:
                continue

            # 階層的転調追跡で (ローカルキー, 和音) を取得
            analyzed = tracker.track(beat_data, tonic_pc, mode)

            # バイグラム学習（ローカルキー相対）
            for i in range(len(analyzed) - 1):
                (key_prev_tonic, key_prev_mode), (deg_p, root_p, q_p) = analyzed[i]
                (key_curr_tonic, key_curr_mode), (deg_c, root_c, q_c) = analyzed[i + 1]

                # ローカルキー相対の和音表現
                rel_root_p = (root_p - key_prev_tonic) % 12
                rel_root_c = (root_c - key_curr_tonic) % 12

                # qualityを簡略化（三和音の quality のまま使用）
                prev_chord = (rel_root_p, q_p)
                curr_chord = (rel_root_c, q_c)

                self.bigram_counts[prev_chord][curr_chord] += 1
                self.chords.add(prev_chord)
                self.chords.add(curr_chord)
                self.num_transitions += 1

            # 旋律条件付き: 各拍のピッチクラスと和音の関係
            for (key_tonic, key_mode), (deg, root, q) in analyzed:
                rel_root = (root - key_tonic) % 12
                chord = (rel_root, q)
                # 構成音を旋律音として記録
                q_intervals = {
                    'major': [0, 4, 7], 'minor': [0, 3, 7],
                    'dim': [0, 3, 6], 'aug': [0, 4, 8],
                    'dom7': [0, 4, 7, 10], 'min7': [0, 3, 7, 10],
                    'maj7': [0, 4, 7, 11], 'hdim7': [0, 3, 6, 10],
                    'dim7': [0, 3, 6, 9],
                }
                for iv in q_intervals.get(q, [0, 4, 7]):
                    melody_pc = (rel_root + iv) % 12
                    self.melody_chord_counts[melody_pc][chord] += 1

            files_processed += 1
            self.num_sequences += 1

        self._normalize()

    def select_chord(self, prev_chord: Optional[Tuple[int, str]],
                     melody_pc: int,
                     key_tonic_pc: int,
                     candidates: List[Tuple[int, str]],
                     rng: random.Random,
                     temperature: float = 1.0,
                     ) -> Tuple[int, str]:
        """学習した確率に基づき次の和音を選択する。

        Args:
            prev_chord: 直前の和音 (rel_root, quality) or None
            melody_pc: 現拍の旋律音ピッチクラス (0-11 絶対)
            key_tonic_pc: 現在の調のトニック PC
            candidates: 選択可能な和音のリスト (rel_root, quality)
            rng: 乱数生成器
            temperature: 1.0=通常, <1.0=決定的, >1.0=探索的

        Returns:
            (rel_root, quality)
        """
        rel_melody = (melody_pc - key_tonic_pc) % 12

        if not candidates:
            # フォールバック: I和音
            return (0, 'major')

        # 各候補のスコアを計算
        scores = {}
        for chord in candidates:
            # バイグラムスコア
            if prev_chord and prev_chord in self.bigram_probs:
                bg_score = self.bigram_probs[prev_chord].get(
                    chord, self.smoothing)
            else:
                bg_score = 1.0 / max(len(self.chords), 1)

            # 旋律適合スコア
            if rel_melody in self.melody_chord_probs:
                mel_score = self.melody_chord_probs[rel_melody].get(
                    chord, self.smoothing)
            else:
                mel_score = 1.0 / max(len(self.chords), 1)

            # 結合スコア（バイグラム 60% + 旋律 40%）
            combined = bg_score * 0.6 + mel_score * 0.4
            scores[chord] = combined

        # temperature 適用
        if temperature != 1.0:
            max_score = max(scores.values())
            if max_score > 0:
                scores = {k: (v / max_score) ** (1.0 / temperature)
                          for k, v in scores.items()}

        # 確率的選択
        total = sum(scores.values())
        if total <= 0:
            return rng.choice(candidates)

        r = rng.random() * total
        cumulative = 0.0
        for chord, score in scores.items():
            cumulative += score
            if cumulative >= r:
                return chord

        return candidates[-1]

    def save(self, path: str):
        """モデルを JSON で保存する。"""
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

        def chord_to_str(c):
            return f"{c[0]}_{c[1]}"

        data = {
            "num_sequences": self.num_sequences,
            "num_transitions": self.num_transitions,
            "smoothing": self.smoothing,
            "chords": sorted([chord_to_str(c) for c in self.chords]),
            "bigram_counts": {
                chord_to_str(prev): {
                    chord_to_str(nxt): cnt
                    for nxt, cnt in nexts.items()
                }
                for prev, nexts in self.bigram_counts.items()
            },
            "melody_chord_counts": {
                str(mel_pc): {
                    chord_to_str(ch): cnt
                    for ch, cnt in chords.items()
                }
                for mel_pc, chords in self.melody_chord_counts.items()
            },
        }

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, path: str):
        """JSON からモデルを復元する。"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        def str_to_chord(s):
            parts = s.split('_', 1)
            return (int(parts[0]), parts[1])

        self.smoothing = data.get("smoothing", 0.01)
        self.num_sequences = data.get("num_sequences", 0)
        self.num_transitions = data.get("num_transitions", 0)
        self.chords = {str_to_chord(s) for s in data.get("chords", [])}

        self.bigram_counts = defaultdict(lambda: defaultdict(int))
        for prev_s, nexts in data.get("bigram_counts", {}).items():
            prev = str_to_chord(prev_s)
            for nxt_s, cnt in nexts.items():
                self.bigram_counts[prev][str_to_chord(nxt_s)] = cnt

        self.melody_chord_counts = defaultdict(lambda: defaultdict(int))
        for mel_s, chords in data.get("melody_chord_counts", {}).items():
            mel_pc = int(mel_s)
            for ch_s, cnt in chords.items():
                self.melody_chord_counts[mel_pc][str_to_chord(ch_s)] = cnt

        self._normalize()

    def summary(self) -> str:
        """モデルの要約を返す。"""
        lines = [
            f"ChordProgressionModel: {self.num_sequences}曲, "
            f"{self.num_transitions}遷移, {len(self.chords)}和音型",
        ]

        # 上位バイグラム
        all_bigrams = []
        for prev, nexts in self.bigram_counts.items():
            for nxt, cnt in nexts.items():
                all_bigrams.append((prev, nxt, cnt))
        all_bigrams.sort(key=lambda x: -x[2])

        lines.append("\n上位バイグラム:")
        for prev, nxt, cnt in all_bigrams[:15]:
            pct = cnt / max(self.num_transitions, 1) * 100
            lines.append(
                f"  {_chord_name(prev):10s} → {_chord_name(nxt):10s}: "
                f"{cnt:4d} ({pct:.1f}%)")

        return "\n".join(lines)


# ============================================================
# 対旋律パターンモデル
# ============================================================

class CounterpointPatternModel:
    """対旋律の音程パターン学習モデル。

    バッハの対位法的な旋律パターンを、和音音に対する
    相対音程の系列として学習する。

    状態:
      (chord_tone_offset, prev_interval) → next_interval
      chord_tone_offset: 現在の音と最近接和音音との半音差 (-6 to +6)
      prev_interval: 直前の旋律音程（半音数, -12 to +12）

    これにより、和音上の位置と直前の動きから次の旋律進行を予測。
    経過音、刺繍音、跳躍後の反行解決などのパターンを捉える。
    """

    def __init__(self, smoothing: float = 0.1):
        self.smoothing = smoothing

        # (chord_offset, prev_interval) → {next_interval: count}
        self.pattern_counts: Dict[Tuple[int, int], Dict[int, int]] = defaultdict(
            lambda: defaultdict(int))

        # 確率
        self.pattern_probs: Dict[Tuple[int, int], Dict[int, float]] = {}

        # 可能な音程の範囲
        self.intervals: Set[int] = set()

        self.num_patterns = 0

    def train_from_midi(self, midi_dir: str, max_files: int = 50):
        """MIDI ファイルから対旋律パターンを学習する。

        voice_by_pitch で声部分離し、主旋律（最高音声部）以外の
        声部から音程パターンを抽出する。
        """
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

        from midi_reader import MIDIReader
        from fugue_analyzer import (
            separate_voices_by_channel, separate_voices_by_pitch,
            compute_pcp,
        )

        reader = MIDIReader()
        files_processed = 0

        # 再帰的に MIDI ファイルを収集
        midi_files = []
        for dirpath, _, filenames in os.walk(midi_dir):
            for fname in filenames:
                if fname.lower().endswith('.mid'):
                    midi_files.append(os.path.join(dirpath, fname))

        for fpath in midi_files:
            if files_processed >= max_files:
                break
            try:
                midi = reader.read(fpath)
            except Exception:
                continue

            if not midi or not midi.all_notes:
                continue

            # 声部分離
            channels = set(n.channel for n in midi.all_notes)
            if len(channels) > 1:
                voices = separate_voices_by_channel(midi)
            else:
                voices = separate_voices_by_pitch(midi.all_notes, num_voices=3)

            if len(voices) < 2:
                continue

            # 各声部から拍単位の音高系列を作成
            tpb = midi.ticks_per_beat or 480
            voice_melodies = {}
            for vs in voices:
                melody = {}
                for n in vs.notes:
                    beat = int(n.start_tick / tpb)
                    if beat not in melody or n.pitch > melody[beat]:
                        melody[beat] = n.pitch
                voice_melodies[vs.voice_id] = melody

            # PCP から和音推定
            beat_chords = {}
            all_notes = midi.all_notes
            max_beat = max(
                (int(n.start_tick / tpb) for n in all_notes), default=0)

            for beat in range(max_beat + 1):
                beat_notes = [
                    n for n in all_notes
                    if int(n.start_tick / tpb) == beat
                ]
                if not beat_notes:
                    continue
                pcp = [0.0] * 12
                for n in beat_notes:
                    dur = max(n.end_tick - n.start_tick, 1)
                    pcp[n.pitch % 12] += dur
                total = sum(pcp)
                if total > 0:
                    pcp = [v / total for v in pcp]
                ch = pcp_to_chord(pcp)
                if ch:
                    beat_chords[beat] = ch

            # 非最高音声部から音程パターンを抽出
            for vid, mel in voice_melodies.items():
                beats = sorted(mel.keys())
                if len(beats) < 3:
                    continue

                for i in range(1, len(beats) - 1):
                    b_prev = beats[i - 1]
                    b_curr = beats[i]
                    b_next = beats[i + 1]

                    # 連続拍でなければスキップ
                    if b_curr - b_prev > 2 or b_next - b_curr > 2:
                        continue

                    p_prev = mel[b_prev]
                    p_curr = mel[b_curr]
                    p_next = mel[b_next]

                    # 和音情報
                    if b_curr not in beat_chords:
                        continue
                    chord_root, chord_qual = beat_chords[b_curr]
                    chord_tones = {
                        (chord_root + iv) % 12
                        for iv in CHORD_TEMPLATES.get(chord_qual, {0, 4, 7})
                    }

                    # 最近接和音音との距離
                    curr_pc = p_curr % 12
                    min_dist = min(
                        min((curr_pc - ct) % 12, (ct - curr_pc) % 12)
                        for ct in chord_tones)
                    # 符号付き: 上に近いか下に近いか
                    chord_offset = min_dist
                    if chord_offset > 6:
                        chord_offset = chord_offset - 12

                    prev_interval = p_curr - p_prev
                    next_interval = p_next - p_curr

                    # 極端な跳躍は除外
                    if abs(prev_interval) > 12 or abs(next_interval) > 12:
                        continue

                    state = (chord_offset, prev_interval)
                    self.pattern_counts[state][next_interval] += 1
                    self.intervals.add(next_interval)
                    self.num_patterns += 1

            files_processed += 1

        self._normalize()

    def _normalize(self):
        """確率を正規化する。"""
        n_intervals = max(len(self.intervals), 1)
        self.pattern_probs = {}
        for state, nexts in self.pattern_counts.items():
            total = sum(nexts.values()) + self.smoothing * n_intervals
            self.pattern_probs[state] = {}
            for interval in self.intervals:
                count = nexts.get(interval, 0)
                self.pattern_probs[state][interval] = (
                    (count + self.smoothing) / total)

    def get_interval_score(self, chord_offset: int,
                           prev_interval: int,
                           next_interval: int) -> float:
        """指定された対旋律進行のスコアを返す。

        高いほどバッハ的。DPのコスト関数に -score として加算する。
        """
        state = (chord_offset, prev_interval)
        if state in self.pattern_probs:
            return self.pattern_probs[state].get(
                next_interval, self.smoothing)

        # 類似状態へのフォールバック
        # chord_offset だけ合致する状態の平均
        fallback = []
        for (co, pi), probs in self.pattern_probs.items():
            if co == chord_offset:
                if next_interval in probs:
                    fallback.append(probs[next_interval])
        if fallback:
            return sum(fallback) / len(fallback)

        return self.smoothing

    def save(self, path: str):
        """JSON で保存する。"""
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        data = {
            "num_patterns": self.num_patterns,
            "smoothing": self.smoothing,
            "intervals": sorted(self.intervals),
            "pattern_counts": {
                f"{s[0]}_{s[1]}": {
                    str(iv): cnt for iv, cnt in nexts.items()
                }
                for s, nexts in self.pattern_counts.items()
            },
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, path: str):
        """JSON から復元する。"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.num_patterns = data.get("num_patterns", 0)
        self.smoothing = data.get("smoothing", 0.1)
        self.intervals = set(data.get("intervals", []))

        self.pattern_counts = defaultdict(lambda: defaultdict(int))
        for state_s, nexts in data.get("pattern_counts", {}).items():
            parts = state_s.split('_')
            state = (int(parts[0]), int(parts[1]))
            for iv_s, cnt in nexts.items():
                self.pattern_counts[state][int(iv_s)] = cnt

        self._normalize()

    def summary(self) -> str:
        """要約を返す。"""
        lines = [
            f"CounterpointPatternModel: {self.num_patterns}パターン, "
            f"{len(self.pattern_counts)}状態, "
            f"{len(self.intervals)}音程種",
        ]

        # 頻出パターン
        all_patterns = []
        for state, nexts in self.pattern_counts.items():
            for iv, cnt in nexts.items():
                all_patterns.append((state, iv, cnt))
        all_patterns.sort(key=lambda x: -x[2])

        lines.append("\n頻出パターン (chord_offset, prev_iv → next_iv):")
        for (co, pi), niv, cnt in all_patterns[:15]:
            pct = cnt / max(self.num_patterns, 1) * 100
            label = _interval_label(co, pi, niv)
            lines.append(f"  {label}: {cnt:4d} ({pct:.1f}%)")

        return "\n".join(lines)


# ============================================================
# ヘルパー
# ============================================================

DEGREE_NAMES = {
    0: 'I', 1: 'bII', 2: 'II', 3: 'bIII', 4: 'III',
    5: 'IV', 6: '#IV', 7: 'V', 8: 'bVI', 9: 'VI',
    10: 'bVII', 11: 'VII',
}


def _chord_name(chord: Tuple[int, str]) -> str:
    """和音を可読形式にする。"""
    root, quality = chord
    degree = DEGREE_NAMES.get(root, str(root))
    suffix = {'major': '', 'minor': 'm', 'dim': 'dim',
              'dom7': '7', 'min7': 'm7', 'maj7': 'M7',
              'dim7': 'o7', 'hdim7': 'ø7'}.get(quality, quality)
    return degree + suffix


def _interval_label(chord_offset, prev_iv, next_iv):
    """パターンの可読形式。"""
    co_name = "CT" if chord_offset == 0 else f"±{chord_offset}"
    return f"[{co_name}, {prev_iv:+d} → {next_iv:+d}]"


# ============================================================
# 学習・テスト CLI
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="バッハ和声進行・対旋律パターンモデルの学習")
    parser.add_argument(
        '--features', '-f',
        default='./corpus/analysis/fugue_features.json',
        help='フーガ特徴量 JSON')
    parser.add_argument(
        '--midi-dir', '-m',
        default='./corpus/bach_midi',
        help='MIDI ファイルディレクトリ')
    parser.add_argument(
        '--output-dir', '-o',
        default='./corpus/models',
        help='モデル出力ディレクトリ')
    parser.add_argument(
        '--test', action='store_true',
        help='テスト選択を実行')
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # --- 和声進行モデル ---
    print("=== 和声進行モデル学習 ===\n")
    chord_model = ChordProgressionModel(smoothing=0.01)
    chord_model.train_from_features(args.features)
    chord_path = os.path.join(args.output_dir, "chord_progression.json")
    chord_model.save(chord_path)
    print(chord_model.summary())
    print(f"\n保存: {chord_path}")

    # --- 対旋律パターンモデル ---
    midi_dir = args.midi_dir
    if os.path.isdir(midi_dir):
        print("\n\n=== 対旋律パターンモデル学習 ===\n")
        cp_model = CounterpointPatternModel(smoothing=0.1)
        cp_model.train_from_midi(midi_dir, max_files=50)
        cp_path = os.path.join(args.output_dir, "counterpoint_patterns.json")
        cp_model.save(cp_path)
        print(cp_model.summary())
        print(f"\n保存: {cp_path}")
    else:
        print(f"\nMIDI ディレクトリが見つかりません: {midi_dir}")

    # --- テスト ---
    if args.test:
        print("\n\n=== テスト選択 ===")
        rng = random.Random(42)
        # I→?→?→?→V→I の6拍進行を生成
        prev = (0, 'major')  # I
        candidates = list(chord_model.chords)
        print(f"\n候補和音数: {len(candidates)}")
        print(f"6拍の和声進行 (C major):")
        progression = [prev]
        for beat in range(5):
            mel_pc = [0, 4, 7, 2, 7, 0][beat]  # C-E-G-D-G-C
            selected = chord_model.select_chord(
                prev, mel_pc, 0, candidates, rng)
            progression.append(selected)
            prev = selected

        for ch in progression:
            print(f"  {_chord_name(ch)}")
