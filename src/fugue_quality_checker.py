"""フーガ生成結果の音楽品質検証モジュール

生成されたMIDIデータ（voice→[(tick, midi, duration)]辞書）に対し、
対位法禁則・和声逸脱・声部交差・半音階衝突などを自動検出する。

設計原則:
  - 非和声音であると証明できたもののみ検査から除外する
  - 証明できない音は全て和声音として扱い、並行禁則の対象とする
  - 弱拍の八分音符であっても、和声的配慮がなされるべきである

使用例:
    # 生成器から和声情報つきで検証
    checker = FugueQualityChecker(midi_data, key=Key('C','major'),
                                   beat_chord_tones=chord_tones_map)
    report = checker.run_all()
    report.print_summary()

    # 外部MIDI（和声情報なし）— 全ノートを和声音として厳格に検査
    checker = FugueQualityChecker(midi_data, key=Key('C','major'),
                                   check_voice_range=False,
                                   use_related_keys=True)
"""

from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field
from fugue_structure import Key, FugueVoiceType
from fugue_realization import SUBBEATS_PER_BEAT
from counterpoint_engine import (
    CounterpointProhibitions, DissonanceType, SpeciesCounterpointRules,
)

# --- 定数 ---
TICKS_PER_BEAT = SUBBEATS_PER_BEAT * 120
# サブビート1つ分のtick数
TICKS_PER_SUBBEAT = 120
NOTE_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']


@dataclass
class QualityViolation:
    """検出された違反1件"""
    category: str          # "parallel_fifth", "voice_crossing" 等
    severity: str          # "error" (禁則) / "warning" (推奨違反)
    beat: int
    measure: int
    beat_in_measure: int
    voices: Tuple[str, ...]
    description: str
    midi_values: Tuple[int, ...] = ()

    def __str__(self):
        loc = f"m{self.measure}.{self.beat_in_measure}"
        vs = "+".join(self.voices)
        return f"[{self.severity}] {loc} ({vs}): {self.description}"


@dataclass
class QualityReport:
    """品質検証レポート"""
    violations: List[QualityViolation] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> List[QualityViolation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def warnings(self) -> List[QualityViolation]:
        return [v for v in self.violations if v.severity == "warning"]

    @property
    def infos(self) -> List[QualityViolation]:
        return [v for v in self.violations if v.severity == "info"]

    def count_by_category(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for v in self.violations:
            counts[v.category] = counts.get(v.category, 0) + 1
        return counts

    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"  音楽品質検証レポート")
        print(f"{'='*60}")
        print(f"  総拍数: {self.stats.get('total_beats', '?')}")
        print(f"  総ノート数: {self.stats.get('total_notes', '?')}")
        print(f"  声部数: {self.stats.get('num_voices', '?')}")
        n_err = len(self.errors)
        n_warn = len(self.warnings)
        n_info = len(self.infos)
        print(f"  errors={n_err}, warnings={n_warn}, info={n_info}")

        # error/warning は個別表示
        displayable = [v for v in self.violations if v.severity in ("error", "warning")]
        if displayable:
            for v in displayable:
                print(f"  {v}")

        # info はカテゴリ別集計のみ
        if n_info > 0:
            info_cats: Dict[str, int] = {}
            for v in self.infos:
                info_cats[v.category] = info_cats.get(v.category, 0) + 1
            for cat, cnt in sorted(info_cats.items()):
                print(f"  [INFO] {cat}: {cnt}拍")

        if not self.violations:
            print("  違反なし — すべてのチェックに合格")
        print(f"{'='*60}")

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


def _beat_location(beat: int) -> Tuple[int, int]:
    """beat→(measure_1based, beat_in_measure_1based)"""
    return beat // 4 + 1, beat % 4 + 1


def _note_name(midi: int) -> str:
    """MIDIピッチ→音名"""
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


class FugueQualityChecker:
    """フーガ品質検証器

    並行禁則の判定方針:
      - 各拍で各声部の「和声音」を特定する
      - 非和声音（経過音・刺繍音等）はclassify_nonchord_toneで
        明確に分類できた場合のみ除外する
      - 分類できない音は和声音として扱う（厳格側に倒す）
      - 連続する拍の和声音同士で並行5度・8度を検査する
    """

    def __init__(
        self,
        midi_data: Dict[FugueVoiceType, List[Tuple[int, int, int]]],
        main_key: Key,
        allowed_chromatic_pcs: Optional[Set[int]] = None,
        beat_key_map: Optional[Dict[int, Key]] = None,
        beat_chord_tones: Optional[Dict[int, Set[int]]] = None,
        beat_chord_labels: Optional[Dict[int, 'ChordLabel']] = None,
        check_voice_range: bool = True,
        use_related_keys: bool = False,
    ):
        """
        Args:
            midi_data: voice → [(tick, midi, duration)]
            main_key: 主調
            allowed_chromatic_pcs: 常に許容する追加のピッチクラス
            beat_key_map: beat → Key（転調情報）
            beat_chord_tones: beat → Set[int]（和音構成音のPC集合）
                生成器のchord_planから取得。指定時は非和声音分類に使用。
            check_voice_range: 声域逸脱チェックを行うか
            use_related_keys: 半音衝突チェックで近親調も許容するか
        """
        self.midi_data = midi_data
        self.main_key = main_key
        self.allowed_chromatic_pcs = allowed_chromatic_pcs or set()
        self.beat_key_map = beat_key_map
        self.beat_chord_tones = beat_chord_tones or {}
        self.beat_chord_labels = beat_chord_labels or {}
        self._check_voice_range_flag = check_voice_range
        self._use_related_keys = use_related_keys
        self.proh = CounterpointProhibitions()

        # 総拍数の算出
        max_tick = 0
        total_notes = 0
        for notes in midi_data.values():
            total_notes += len(notes)
            for t, m, d in notes:
                if t + d > max_tick:
                    max_tick = t + d
        self.total_beats = max_tick // TICKS_PER_BEAT
        self.total_notes = total_notes

        # 声部の順序（高→低）
        voice_order = [
            FugueVoiceType.SOPRANO, FugueVoiceType.ALTO,
            FugueVoiceType.TENOR, FugueVoiceType.BASS,
        ]
        self.voices = [v for v in voice_order if v in midi_data]

        # 各声部のノートを時間順にソート
        self._sorted_notes: Dict[FugueVoiceType, List[Tuple[int, int, int]]] = {}
        for vt in self.voices:
            self._sorted_notes[vt] = sorted(midi_data[vt], key=lambda x: x[0])

        # ビートごとのピッチマップを構築
        self.beat_pitches: Dict[int, Dict[FugueVoiceType, Set[int]]] = {}
        # ビートごとの和声音（非和声音を除外した音）
        self.beat_harmonic: Dict[int, Dict[FugueVoiceType, int]] = {}
        # ビートごとの全ピッチ情報
        self.beat_onsets: Dict[int, Dict[FugueVoiceType, int]] = {}
        self._build_beat_maps()

    def _get_notes_at_beat(
        self, vt: FugueVoiceType, beat: int,
    ) -> List[Tuple[int, int, int]]:
        """指定拍に重なるノートを返す"""
        sb_start = beat * TICKS_PER_BEAT
        sb_end = (beat + 1) * TICKS_PER_BEAT
        return [
            (t, m, d) for t, m, d in self._sorted_notes[vt]
            if t < sb_end and t + d > sb_start
        ]

    def _get_note_at_index(
        self, vt: FugueVoiceType, target_midi: int, beat: int,
    ) -> Optional[int]:
        """声部内でtarget_midiの次のノート（beat以降）のインデックスを返す"""
        notes = self._sorted_notes[vt]
        sb_start = beat * TICKS_PER_BEAT
        for i, (t, m, d) in enumerate(notes):
            if t >= sb_start and m == target_midi:
                return i
        return None

    def _classify_note(
        self, vt: FugueVoiceType, note_idx: int, chord_tones: Set[int],
    ) -> Optional[DissonanceType]:
        """ノートを非和声音として分類できるか試みる。

        和音構成音であればNoneを返す。
        非和声音として明確に分類できた場合のみDissonanceTypeを返す。
        分類できない場合もNoneを返す（→和声音として扱う）。
        """
        notes = self._sorted_notes[vt]
        if note_idx < 0 or note_idx >= len(notes):
            return None
        t, m, d = notes[note_idx]
        pc = m % 12

        # 和音構成音ならそもそも非和声音ではない
        if pc in chord_tones:
            return None

        # 前後のノートが必要
        prev_m = notes[note_idx - 1][1] if note_idx > 0 else None
        next_m = notes[note_idx + 1][1] if note_idx < len(notes) - 1 else None

        if prev_m is None or next_m is None:
            return None  # 前後不明→分類不能→和声音扱い

        # classify_nonchord_tone を使用
        result = SpeciesCounterpointRules.classify_nonchord_tone(
            prev_m, m, next_m, chord_tones,
        )
        return result

    def _build_beat_maps(self):
        """各拍の和声音を特定する。

        方針:
          1. 各拍で各声部が鳴らしている全ピッチを収集
          2. beat_chord_tonesが提供されている場合:
             - 各ノートについてclassify_nonchord_toneで分類を試みる
             - 経過音・刺繍音・逸音・先取音として分類されたノートは除外
             - 分類できない非和音構成音も和声音として扱う（厳格側）
          3. beat_chord_tonesがない場合:
             - 拍頭（拍の開始時点）に鳴っている音を和声音とする
          4. 各拍の和声音から1つの代表音を選択（最長音価優先）
        """
        for beat in range(self.total_beats + 1):
            sb_start = beat * TICKS_PER_BEAT
            sb_end = (beat + 1) * TICKS_PER_BEAT
            bp: Dict[FugueVoiceType, Set[int]] = {}
            bh: Dict[FugueVoiceType, int] = {}
            bo: Dict[FugueVoiceType, int] = {}

            chord_tones = self.beat_chord_tones.get(beat, set())

            for vt in self.voices:
                pitches = set()
                onset_count = 0
                # 拍内の全ノートとインデックスを収集
                beat_notes: List[Tuple[int, int, int, int]] = []  # (t, m, d, idx)
                for idx, (t, m, d) in enumerate(self._sorted_notes[vt]):
                    if t < sb_end and t + d > sb_start:
                        pitches.add(m)
                        beat_notes.append((t, m, d, idx))
                        if sb_start <= t < sb_end:
                            onset_count += 1

                if pitches:
                    bp[vt] = pitches

                if not beat_notes:
                    bo[vt] = onset_count
                    continue

                # 和声音の特定
                harmonic_candidates: List[Tuple[int, int]] = []  # (midi, duration)

                if chord_tones:
                    # 和声情報あり: 非和声音の分類を試みる
                    for t, m, d, idx in beat_notes:
                        nct = self._classify_note(vt, idx, chord_tones)
                        if nct is not None:
                            # 明確に非和声音と分類された → 除外
                            continue
                        # 和声音、または分類不能 → 和声音として扱う
                        harmonic_candidates.append((m, d))
                else:
                    # 和声情報なし: 全ノートを和声音として扱う
                    for t, m, d, idx in beat_notes:
                        harmonic_candidates.append((m, d))

                if harmonic_candidates:
                    # 拍頭に発音する和声音を最優先、次に最長音価
                    # beat_notesの(t, m, d, idx)からtick情報を参照
                    onset_mids = {m for t, m, d, idx in beat_notes if t == sb_start}
                    head_candidates = [(m, d) for m, d in harmonic_candidates
                                       if m in onset_mids]
                    if head_candidates:
                        head_candidates.sort(key=lambda x: -x[1])
                        bh[vt] = head_candidates[0][0]
                    else:
                        harmonic_candidates.sort(key=lambda x: -x[1])
                        bh[vt] = harmonic_candidates[0][0]
                elif pitches:
                    # 全て非和声音に分類された場合（稀）→ 最長ノートをフォールバック
                    longest = max(beat_notes, key=lambda x: x[2])
                    bh[vt] = longest[1]

                bo[vt] = onset_count

            self.beat_pitches[beat] = bp
            self.beat_harmonic[beat] = bh
            self.beat_onsets[beat] = bo

    def _get_extended_diatonic(self) -> Set[int]:
        """主調 + 近親調のダイアトニック音を統合"""
        pcs: Set[int] = set(self.main_key.scale)
        if not self._use_related_keys:
            return pcs
        tonic_pc = self.main_key.tonic_pc
        mode = self.main_key.mode
        pc_to_name = {0: 'C', 1: 'C#', 2: 'D', 3: 'Eb', 4: 'E', 5: 'F',
                      6: 'F#', 7: 'G', 8: 'Ab', 9: 'A', 10: 'Bb', 11: 'B'}

        def _make_key(pc: int, m: str) -> Optional[Key]:
            try:
                return Key(pc_to_name[pc % 12], m)
            except Exception:
                return None

        if mode == "major":
            related_specs = [
                ((tonic_pc + 7) % 12, "major"),
                ((tonic_pc + 5) % 12, "major"),
                ((tonic_pc + 9) % 12, "minor"),
                (tonic_pc, "minor"),
            ]
        else:
            related_specs = [
                ((tonic_pc + 7) % 12, "minor"),
                ((tonic_pc + 5) % 12, "minor"),
                ((tonic_pc + 3) % 12, "major"),
                (tonic_pc, "major"),
            ]
        for rpc, rm in related_specs:
            rk = _make_key(rpc, rm)
            if rk is not None:
                pcs.update(rk.scale)
        return pcs

    def run_all(self) -> QualityReport:
        report = QualityReport()
        report.stats = {
            "total_beats": self.total_beats,
            "total_notes": self.total_notes,
            "num_voices": len(self.voices),
        }
        self._check_parallel_perfect(report)
        self._check_voice_crossing(report)
        self._check_chromatic_clash(report)
        self._check_augmented_intervals(report)
        self._check_cross_relation(report)
        if self._check_voice_range_flag:
            self._check_voice_range(report)
        if self.beat_chord_labels:
            self._check_chord_realization(report)
        return report

    def _check_parallel_perfect(self, report: QualityReport):
        """並行5度・並行8度を検出

        各拍の和声音（beat_harmonic）同士で判定する。
        非和声音と分類された音は比較対象から除外済み。

        外部MIDIで声部分離が不正確な場合:
          同一拍に3つ以上のピッチがある声部はスキップ。
        """
        for i in range(len(self.voices)):
            for j in range(i + 1, len(self.voices)):
                v1, v2 = self.voices[i], self.voices[j]
                for beat in range(1, self.total_beats + 1):
                    prev_h = self.beat_harmonic.get(beat - 1, {})
                    curr_h = self.beat_harmonic.get(beat, {})
                    if (v1 not in prev_h or v1 not in curr_h or
                            v2 not in prev_h or v2 not in curr_h):
                        continue
                    # 両声部とも静止（同一音）ならスキップ
                    if (prev_h[v1] == curr_h[v1] and
                            prev_h[v2] == curr_h[v2]):
                        continue
                    # 声部分離品質チェック
                    prev_p_v1 = self.beat_pitches.get(beat - 1, {}).get(v1, set())
                    curr_p_v1 = self.beat_pitches.get(beat, {}).get(v1, set())
                    prev_p_v2 = self.beat_pitches.get(beat - 1, {}).get(v2, set())
                    curr_p_v2 = self.beat_pitches.get(beat, {}).get(v2, set())
                    if (len(prev_p_v1) > 2 or len(curr_p_v1) > 2 or
                            len(prev_p_v2) > 2 or len(curr_p_v2) > 2):
                        continue
                    valid, msg = self.proh.check_parallel_perfect(
                        prev_h[v1], curr_h[v1],
                        prev_h[v2], curr_h[v2])
                    if not valid:
                        m, b = _beat_location(beat)
                        report.violations.append(QualityViolation(
                            category="parallel_perfect",
                            severity="error",
                            beat=beat, measure=m, beat_in_measure=b,
                            voices=(v1.value, v2.value),
                            description=msg,
                            midi_values=(prev_h[v1], curr_h[v1],
                                         prev_h[v2], curr_h[v2]),
                        ))

    def _check_voice_crossing(self, report: QualityReport):
        """声部交差を検出"""
        for i in range(len(self.voices) - 1):
            upper, lower = self.voices[i], self.voices[i + 1]
            for beat in range(self.total_beats + 1):
                h = self.beat_harmonic.get(beat, {})
                if upper not in h or lower not in h:
                    continue
                if h[upper] < h[lower]:
                    m, b = _beat_location(beat)
                    report.violations.append(QualityViolation(
                        category="voice_crossing",
                        severity="warning",
                        beat=beat, measure=m, beat_in_measure=b,
                        voices=(upper.value, lower.value),
                        description=(
                            f"声部交差: {upper.value}={_note_name(h[upper])}"
                            f" < {lower.value}={_note_name(h[lower])}"),
                        midi_values=(h[upper], h[lower]),
                    ))

    @staticmethod
    def _extend_minor_diatonic(key_obj: Key) -> Set[int]:
        """短調のダイアトニック集合を拡張する。

        和声的短音階のスケール(b6, #7)に加え、
        自然短音階の7度(b7)と旋律的短音階の6度(natural 6)も含める。
        E.g. D minor: {D, E, F, G, A, Bb, B, C, C#}
        """
        sc = set(key_obj.scale)
        if key_obj.mode == "minor" and len(key_obj.scale) == 7:
            tonic_pc = key_obj.tonic_pc
            # 自然7度 = tonic - 2半音 (全音下)
            natural_7th = (tonic_pc - 2) % 12
            # 自然6度 = tonic - 4半音 (短3度下) — これは既にb6としてscaleに含まれる
            # 長6度 = tonic - 3半音 — 旋律的短音階上行の6度
            natural_6th = (tonic_pc + 9) % 12  # = tonic - 3
            sc.add(natural_7th)
            sc.add(natural_6th)
        return sc

    def _check_chromatic_clash(self, report: QualityReport):
        """半音衝突を検出

        2つのケースを検出する:
        (A) 非ダイアトニック音を含む半音衝突 — 従来の検出
        (B) 両方ダイアトニックだが、一方が和声音で他方が非和声音、
            かつ実際のMIDI距離が近い場合 — V和音上のF#(和声音)と
            G(非和声音)のように、同一音域で半音がぶつかるケース

        同一声部内の半音進行（装飾音によるC→C#等）は旋律的動きであり
        衝突ではない。異なる声部間で同時に鳴る半音のみを検出する。

        短調では自然7度・旋律的6度もダイアトニックとみなす。
        """
        main_diatonic = self._extend_minor_diatonic(self.main_key)

        for beat in range(self.total_beats + 1):
            if self.beat_key_map and beat in self.beat_key_map:
                diatonic = self._extend_minor_diatonic(self.beat_key_map[beat])
            else:
                diatonic = main_diatonic

            # 当該拍の和声音（chord_tones）
            beat_ct = (self.beat_chord_tones.get(beat, set())
                       if self.beat_chord_tones else set())

            bp = self.beat_pitches.get(beat, {})
            # 声部ごとのPC集合を構築（声部間の比較のため）
            voice_pcs: Dict[FugueVoiceType, Set[int]] = {}
            for vt, pitches in bp.items():
                voice_pcs[vt] = {p % 12 for p in pitches}

            # 異なる声部間で半音衝突をチェック
            vt_list = list(voice_pcs.keys())
            reported: Set[Tuple[int, int]] = set()  # 重複報告防止
            for i in range(len(vt_list)):
                for j in range(i + 1, len(vt_list)):
                    for pc_a in voice_pcs[vt_list[i]]:
                        for pc_b in voice_pcs[vt_list[j]]:
                            diff = (pc_b - pc_a) % 12
                            if diff == 1 or diff == 11:
                                pair = (min(pc_a, pc_b), max(pc_a, pc_b))
                                if pair in reported:
                                    continue

                                both_diatonic = (pc_a in diatonic
                                                 and pc_b in diatonic)

                                if both_diatonic:
                                    # (B) 両方ダイアトニック → 和声音認識で判定
                                    if not beat_ct:
                                        continue  # 和声情報なし → 判定不能、スキップ
                                    a_in_chord = pc_a in beat_ct
                                    b_in_chord = pc_b in beat_ct
                                    if a_in_chord == b_in_chord:
                                        continue  # 両方和声音 or 両方非和声音 → OK
                                    # 片方だけ和声音 → MIDI距離が近いか確認
                                    # （同一音域での衝突のみ問題にする）
                                    midi_a = min(
                                        p for p in bp.get(vt_list[i], [])
                                        if p % 12 == pc_a)
                                    midi_b = min(
                                        p for p in bp.get(vt_list[j], [])
                                        if p % 12 == pc_b)
                                    midi_dist = abs(midi_a - midi_b)
                                    if midi_dist > 2:
                                        continue  # 離れた音域 → 聴感上問題なし

                                    reported.add(pair)
                                    m, b = _beat_location(beat)
                                    nct_note = (NOTE_NAMES[pc_a] if not a_in_chord
                                                else NOTE_NAMES[pc_b])
                                    report.violations.append(QualityViolation(
                                        category="chromatic_clash",
                                        severity="error",
                                        beat=beat, measure=m, beat_in_measure=b,
                                        voices=(vt_list[i].value, vt_list[j].value),
                                        description=(
                                            f"半音衝突: {NOTE_NAMES[pc_a]} vs "
                                            f"{NOTE_NAMES[pc_b]} "
                                            f"(非和声音 {nct_note} が"
                                            f"和声音と半音衝突)"),
                                        midi_values=(midi_a, midi_b),
                                    ))
                                else:
                                    # (A) 非ダイアトニック音を含む → 従来通り
                                    reported.add(pair)
                                    m, b = _beat_location(beat)
                                    non_dia = []
                                    if pc_a not in diatonic:
                                        non_dia.append(NOTE_NAMES[pc_a])
                                    if pc_b not in diatonic:
                                        non_dia.append(NOTE_NAMES[pc_b])
                                    report.violations.append(QualityViolation(
                                        category="chromatic_clash",
                                        severity="error",
                                        beat=beat, measure=m, beat_in_measure=b,
                                        voices=(vt_list[i].value,
                                                vt_list[j].value),
                                        description=(
                                            f"半音衝突: {NOTE_NAMES[pc_a]} vs "
                                            f"{NOTE_NAMES[pc_b]} "
                                            f"(非ダイアトニック: "
                                            f"{','.join(non_dia)})"),
                                        midi_values=(
                                            min(p for p in bp.get(
                                                vt_list[i], [])
                                                if p % 12 == pc_a),
                                            min(p for p in bp.get(
                                                vt_list[j], [])
                                                if p % 12 == pc_b)),
                                    ))

    def _get_aug2_pair(self, beat: int) -> Optional[Set[int]]:
        """指定拍の調における増2度ペア（b6-#7）を返す。

        短調の和声的短音階では第6音(b6)と第7音(#7)が増2度を形成する。
        長調では増2度ペアは存在しない。
        """
        if self.beat_key_map and beat in self.beat_key_map:
            bk = self.beat_key_map[beat]
        else:
            bk = self.main_key
        if bk.mode != "minor":
            return None
        sc = bk.scale
        if len(sc) == 7:
            return {sc[5], sc[6]}  # b6, #7
        return None

    def _check_augmented_intervals(self, report: QualityReport):
        """増音程（旋律的）を検出

        増2度: DP/VNSと同じ方式で、b6-#7ペアの明示的検出のみ。
        「非ダイアトニック → 増音程」の曖昧な判定は行わない。
        短調では自然7度(C natural in D minor)は通常の旋律音であり、
        C→Aは短3度であって増2度ではない。
        """
        for vt in self.voices:
            for beat in range(1, self.total_beats + 1):
                prev_h = self.beat_harmonic.get(beat - 1, {})
                curr_h = self.beat_harmonic.get(beat, {})
                if vt not in prev_h or vt not in curr_h:
                    continue
                interval = abs(curr_h[vt] - prev_h[vt])
                prev_pc = prev_h[vt] % 12
                curr_pc = curr_h[vt] % 12

                if interval == 3:
                    # 増2度: b6-#7ペアとの一致のみ検出
                    aug2 = self._get_aug2_pair(beat)
                    if aug2 is None:
                        continue
                    if {prev_pc, curr_pc} != aug2:
                        continue
                    m, b = _beat_location(beat)
                    report.violations.append(QualityViolation(
                        category="augmented_melodic_interval",
                        severity="warning",
                        beat=beat, measure=m, beat_in_measure=b,
                        voices=(vt.value,),
                        description=(
                            f"増2度: {NOTE_NAMES[prev_pc]}"
                            f"→{NOTE_NAMES[curr_pc]}"),
                        midi_values=(prev_h[vt], curr_h[vt]),
                    ))
                elif interval == 6:
                    m, b = _beat_location(beat)
                    report.violations.append(QualityViolation(
                        category="tritone_melodic_leap",
                        severity="warning",
                        beat=beat, measure=m, beat_in_measure=b,
                        voices=(vt.value,),
                        description=(
                            f"増4度/減5度跳躍: {NOTE_NAMES[prev_pc]}"
                            f"→{NOTE_NAMES[curr_pc]}"),
                        midi_values=(prev_h[vt], curr_h[vt]),
                    ))

    @staticmethod
    def _cross_relation_pairs(key_obj: Key) -> Set[Tuple[int, int]]:
        """指定された調における対斜ペア（同一音名の半音変化ペア）を返す。

        短調では:
          - 自然7度 / 導音 (e.g. C♮/C# in D minor)
          - 自然6度 / 長6度 (e.g. Bb/B♮ in D minor)
        長調では対斜ペアは通常発生しない（借用和音除く）。

        Returns:
            Set of (lower_pc, upper_pc) pairs that constitute cross relations.
        """
        pairs: Set[Tuple[int, int]] = set()
        if key_obj.mode == "minor":
            t = key_obj.tonic_pc
            # 自然7度 vs 導音: (t-2)%12 と (t-1)%12
            nat7 = (t - 2) % 12   # e.g. C=0 for D minor
            lead = (t - 1) % 12   # e.g. C#=1 for D minor
            pairs.add((min(nat7, lead), max(nat7, lead)))
            # 自然6度 vs 長6度: (t-4)%12 と (t-3)%12
            flat6 = (t + 8) % 12  # e.g. Bb=10 for D minor
            nat6 = (t + 9) % 12   # e.g. B=11 for D minor
            pairs.add((min(flat6, nat6), max(flat6, nat6)))
        return pairs

    def _check_cross_relation(self, report: QualityReport):
        """対斜（fausse relation / cross relation）を検出

        定義: 同一音名の半音変化（例: C♮ と C#）が異なる声部間で
        隣接する拍に出現すること。

        E→F や A→Bb のような異なる音名の半音関係は対斜ではない。
        対斜となるのは短調における:
          - 自然7度 vs 導音 (C♮/C# in D minor)
          - 自然6度 vs 長6度 (Bb/B♮ in D minor)

        同一声部内の半音変化は対斜ではなく半音階的進行であり、許容される。
        Gédalge §11.3 に基づく禁止規則。
        """
        # 主調の対斜ペアをキャッシュ
        main_cr_pairs = self._cross_relation_pairs(self.main_key)

        for beat in range(self.total_beats):
            next_beat = beat + 1
            curr_map = self.beat_harmonic.get(beat, {})
            next_map = self.beat_harmonic.get(next_beat, {})
            if not curr_map or not next_map:
                continue

            # 拍ごとの調に基づく対斜ペア
            if self.beat_key_map and next_beat in self.beat_key_map:
                cr_pairs = self._cross_relation_pairs(
                    self.beat_key_map[next_beat])
                # 前拍の調のペアも合わせる
                if beat in self.beat_key_map:
                    cr_pairs = cr_pairs | self._cross_relation_pairs(
                        self.beat_key_map[beat])
            elif self.beat_key_map and beat in self.beat_key_map:
                cr_pairs = self._cross_relation_pairs(
                    self.beat_key_map[beat])
            else:
                cr_pairs = main_cr_pairs

            if not cr_pairs:
                continue  # 長調で対斜ペアなし

            # 各声部の拍頭ピッチクラス
            curr_pcs: Dict[FugueVoiceType, int] = {
                vt: p % 12 for vt, p in curr_map.items()}
            next_pcs: Dict[FugueVoiceType, int] = {
                vt: p % 12 for vt, p in next_map.items()}

            reported: Set[Tuple[int, int]] = set()

            for vt_a, pc_a in curr_pcs.items():
                for vt_b, pc_b in next_pcs.items():
                    if vt_a == vt_b:
                        continue  # 同一声部は対斜ではない
                    diff = (pc_b - pc_a) % 12
                    if diff != 1 and diff != 11:
                        continue  # 半音関係でない

                    pair_key = (min(pc_a, pc_b), max(pc_a, pc_b))
                    if pair_key in reported:
                        continue

                    # この半音ペアが対斜ペアか確認
                    if pair_key not in cr_pairs:
                        continue  # E/F, A/Bb等は対斜ではない

                    # 同一声部が半音変化を引き受けていれば対斜ではない
                    if vt_a in next_pcs and next_pcs[vt_a] == pc_b:
                        continue
                    if vt_b in curr_pcs and curr_pcs[vt_b] == pc_a:
                        continue

                    reported.add(pair_key)
                    m, b = _beat_location(next_beat)
                    report.violations.append(QualityViolation(
                        category="cross_relation",
                        severity="error",
                        beat=next_beat, measure=m, beat_in_measure=b,
                        voices=(vt_a.value, vt_b.value),
                        description=(
                            f"対斜: {NOTE_NAMES[pc_a]}({vt_a.value},"
                            f"beat {beat})"
                            f" → {NOTE_NAMES[pc_b]}({vt_b.value},"
                            f"beat {next_beat})"),
                        midi_values=(curr_map[vt_a], next_map[vt_b]),
                    ))

    def _check_voice_range(self, report: QualityReport):
        """声域逸脱を検出"""
        from fugue_realization import VOICE_RANGES
        for vt in self.voices:
            if vt not in VOICE_RANGES:
                continue
            lo, hi = VOICE_RANGES[vt]
            for beat in range(self.total_beats + 1):
                pitches = self.beat_pitches.get(beat, {}).get(vt, set())
                for p in pitches:
                    if p < lo or p > hi:
                        m, b = _beat_location(beat)
                        report.violations.append(QualityViolation(
                            category="voice_range",
                            severity="error",
                            beat=beat, measure=m, beat_in_measure=b,
                            voices=(vt.value,),
                            description=(
                                f"声域逸脱: {_note_name(p)} "
                                f"(範囲: {_note_name(lo)}"
                                f"-{_note_name(hi)})"),
                            midi_values=(p,),
                        ))


    def _check_chord_realization(self, report: QualityReport):
        """和声実現の検証: 計画された和音が実際に鳴っているか

        バッハの対位法では2声であっても和声の明確性が確保される。
        チェッカーの目的は「全部OK」を出すことではなく、和声として
        聞き取れる要件が満たされているかを厳格に診断すること。

        各拍について以下を検査する:
          (1) 根音欠如 — 根音がどの声部にもない → error
              根音なしでは和音のアイデンティティが成立しない
          (2) 第3音欠如 — 長/短の区別がつかない → warning(2声), error(3声+)
          (3) 計画外の和声音 — 和音構成音に属さない音が和声音として鳴る → error
          (4) 根音が最低音でない — 転回形の検出 → warning

        声部数による扱い:
          1声: 主題の旋律音は所与 → 検査免除
          2声+: 全項目を厳格に検査（バッハは2声でも和声が明確）

        beat_chord_labelsが必要（root_pc, tones, quality）。
        """
        for beat in range(self.total_beats + 1):
            label = self.beat_chord_labels.get(beat)
            if label is None:
                continue

            # この拍で実際に鳴っている全ピッチクラス（和声音として扱われるもの）
            bp = self.beat_pitches.get(beat, {})
            if not bp:
                continue  # 無音拍

            num_voices_here = len(bp)
            # 1声部 = 主題の旋律音は所与であり検査対象外
            if num_voices_here < 2:
                continue

            # 全声部の和声音ピッチクラスを収集
            sounding_pcs: Set[int] = set()
            sounding_midis: List[int] = []
            for vt, pitches in bp.items():
                for p in pitches:
                    sounding_pcs.add(p % 12)
                    sounding_midis.append(p)

            if not sounding_pcs:
                continue

            m, b = _beat_location(beat)
            root_pc = label.root_pc
            chord_tones = label.tones

            # --- 和音構成音の充足度 ---
            # 5度音 = root + 7半音
            fifth_pc = (root_pc + 7) % 12
            if label.quality == "diminished":
                fifth_pc = (root_pc + 6) % 12

            # 第3音の特定
            if label.quality == "major":
                third_pc = (root_pc + 4) % 12
            elif label.quality in ("minor", "diminished"):
                third_pc = (root_pc + 3) % 12
            else:
                third_pc = None

            # (1) 根音欠如 — 2声以上で常にerror
            if root_pc not in sounding_pcs:
                report.violations.append(QualityViolation(
                    category="chord_no_root",
                    severity="error",
                    beat=beat, measure=m, beat_in_measure=b,
                    voices=tuple(vt.value for vt in bp.keys()),
                    description=(
                        f"根音欠如: {NOTE_NAMES[root_pc]} が不在 "
                        f"(計画={NOTE_NAMES[root_pc]}{label.quality}, "
                        f"実音={{{','.join(NOTE_NAMES[p] for p in sorted(sounding_pcs))}}}, "
                        f"{num_voices_here}声)"
                    ),
                ))

            # (2) 第3音欠如 — 2声=warning, 3声+=error
            if third_pc is not None and third_pc not in sounding_pcs:
                sev = "error" if num_voices_here >= 3 else "warning"
                report.violations.append(QualityViolation(
                    category="chord_no_third",
                    severity=sev,
                    beat=beat, measure=m, beat_in_measure=b,
                    voices=tuple(vt.value for vt in bp.keys()),
                    description=(
                        f"第3音欠如: {NOTE_NAMES[third_pc]} が不在 "
                        f"(計画={NOTE_NAMES[root_pc]}{label.quality}, "
                        f"実音={{{','.join(NOTE_NAMES[p] for p in sorted(sounding_pcs))}}}, "
                        f"{num_voices_here}声)"
                    ),
                ))

            # (3) 計画外の和声音 — 2声以上で常にerror
            # beat_harmonic に記録された和声音のPCのみを検査対象にする
            bh = self.beat_harmonic.get(beat, {})
            harmonic_pcs = {bh[vt] % 12 for vt in bh}
            foreign_pcs = harmonic_pcs - chord_tones
            if foreign_pcs:
                report.violations.append(QualityViolation(
                    category="chord_foreign_tone",
                    severity="error",
                    beat=beat, measure=m, beat_in_measure=b,
                    voices=tuple(vt.value for vt in bp.keys()),
                    description=(
                        f"計画外の和声音: "
                        f"{{{','.join(NOTE_NAMES[p] for p in sorted(foreign_pcs))}}} "
                        f"(計画={NOTE_NAMES[root_pc]}{label.quality} "
                        f"{{{','.join(NOTE_NAMES[p] for p in sorted(chord_tones))}}}, "
                        f"{num_voices_here}声)"
                    ),
                ))

            # (4) 根音が最低音でない — 転回形検出 (info: 集計のみ表示)
            if sounding_midis and root_pc in sounding_pcs:
                lowest_midi = min(sounding_midis)
                if lowest_midi % 12 != root_pc:
                    inversion_pc = lowest_midi % 12
                    report.violations.append(QualityViolation(
                        category="chord_inversion",
                        severity="info",
                        beat=beat, measure=m, beat_in_measure=b,
                        voices=tuple(vt.value for vt in bp.keys()),
                        description=(
                            f"転回形: 最低音={NOTE_NAMES[inversion_pc]} "
                            f"(根音={NOTE_NAMES[root_pc]}, "
                            f"{NOTE_NAMES[root_pc]}{label.quality}, "
                            f"{num_voices_here}声)"
                        ),
                    ))


def check_generated_fugue(
    midi_data: Dict[FugueVoiceType, List[Tuple[int, int, int]]],
    main_key: Key,
    beat_chord_tones: Optional[Dict[int, Set[int]]] = None,
    label: str = "",
) -> QualityReport:
    """便利関数: 生成結果を検証してレポートを返す"""
    checker = FugueQualityChecker(
        midi_data, main_key, beat_chord_tones=beat_chord_tones)
    report = checker.run_all()
    if label:
        print(f"\n--- 品質検証: {label} ---")
    report.print_summary()
    return report
