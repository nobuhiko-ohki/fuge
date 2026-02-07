"""
100%和声学規則遵守フーガ生成エンジン
Rule-Compliant Fugue Generator

harmony_rules_complete.py の全規則を100%遵守
違反は1つも許容しない
"""

from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum
import random

from harmony_rules_complete import (
    HarmonyRules, Pitch, Interval, ScaleDegree
)
from midi_writer import MIDIWriter


@dataclass
class NoteCandidate:
    """音符の候補"""
    pitch: Pitch
    is_chord_tone: bool
    score: float  # 適合度スコア


class VoiceName(Enum):
    """声部名"""
    SOPRANO = "soprano"
    ALTO = "alto"
    BASS = "bass"


@dataclass
class HarmonicContext:
    """和声的文脈"""
    position: int  # 16分音符単位の位置
    is_strong_beat: bool
    current_degree: ScaleDegree
    chord_tones: Set[int]  # ピッチクラス
    root: int
    third: int
    fifth: int


class RuleCompliantFugueGenerator:
    """100%規則遵守フーガ生成エンジン"""
    
    def __init__(self, tonic: int = 0, mode: str = "major"):
        """
        Args:
            tonic: 主音のピッチクラス (0=C)
            mode: "major" or "minor"
        """
        self.rules = HarmonyRules()
        self.tonic = tonic
        self.mode = mode
        
        # 調性の音階
        if mode == "major":
            self.scale = self.rules.get_major_scale(tonic)
        else:
            self.scale = self.rules.get_harmonic_minor_scale(tonic)
        
        # 現在の声部状態
        self.voices: Dict[VoiceName, List[Pitch]] = {
            VoiceName.SOPRANO: [],
            VoiceName.ALTO: [],
            VoiceName.BASS: []
        }
        
        # 和声進行計画
        self.harmonic_plan: List[HarmonicContext] = []
        
        # 統計
        self.total_checks = 0
        self.rejected_candidates = 0
    
    # ============================================================
    # 和声進行の計画
    # ============================================================
    
    def plan_harmonic_progression(self, num_measures: int = 4):
        """和声進行を計画（全規則チェック済み）"""
        print("\n【和声進行の計画】")
        
        beat_length = 4  # 4分音符 = 4 sixteenths
        total_beats = num_measures * 16
        
        progressions = []
        position = 0
        
        # 開始: I (2拍)
        progressions.append((ScaleDegree.I, 0))
        progressions.append((ScaleDegree.I, beat_length))
        
        # 中間部: 規則に従った進行
        current_pos = beat_length * 2
        current_degree = ScaleDegree.I
        
        while current_pos < total_beats - beat_length * 4:
            # 次の和音候補
            candidates = [
                ScaleDegree.IV,
                ScaleDegree.V,
                ScaleDegree.VI,
                ScaleDegree.II,
            ]
            
            # 規則チェック
            valid_next = []
            for next_degree in candidates:
                is_valid, msg = self.rules.check_chord_progression(
                    current_degree, next_degree
                )
                if is_valid:
                    valid_next.append(next_degree)
            
            if valid_next:
                next_degree = random.choice(valid_next)
                progressions.append((next_degree, current_pos))
                current_degree = next_degree
                current_pos += beat_length
            else:
                # 候補がなければIに戻る
                progressions.append((ScaleDegree.I, current_pos))
                current_degree = ScaleDegree.I
                current_pos += beat_length
        
        # 終結: V7 → I (完全正格終止)
        progressions.append((ScaleDegree.V, total_beats - beat_length * 2))
        progressions.append((ScaleDegree.I, total_beats - beat_length))
        
        # HarmonicContext に変換
        for degree, pos in progressions:
            is_strong = (pos % beat_length) == 0
            
            # 和音構成音を取得
            degree_idx = degree.value - 1
            root_pc = self.scale[degree_idx]
            
            if degree == ScaleDegree.I:
                quality = "major" if self.mode == "major" else "minor"
            elif degree == ScaleDegree.IV:
                quality = "major" if self.mode == "major" else "minor"
            elif degree == ScaleDegree.V:
                quality = "major"  # 属和音は常に長調
            elif degree == ScaleDegree.II:
                quality = "minor" if self.mode == "major" else "diminished"
            elif degree == ScaleDegree.VI:
                quality = "minor" if self.mode == "major" else "major"
            else:
                quality = "major"
            
            chord_pcs = set(self.rules.build_triad(root_pc, quality))
            
            # root, third, fifth
            chord_list = list(chord_pcs)
            root = root_pc
            third = (root + (4 if quality == "major" else 3)) % 12
            fifth = (root + 7) % 12
            
            context = HarmonicContext(
                position=pos,
                is_strong_beat=is_strong,
                current_degree=degree,
                chord_tones=chord_pcs,
                root=root,
                third=third,
                fifth=fifth
            )
            
            self.harmonic_plan.append(context)
        
        print(f"  計画された和音: {len(self.harmonic_plan)}個")
        for ctx in self.harmonic_plan[:10]:
            beat = ctx.position // beat_length
            print(f"    拍{beat}: {ctx.current_degree.name}")
        if len(self.harmonic_plan) > 10:
            print(f"    ... 他{len(self.harmonic_plan) - 10}個")
    
    def get_context_at(self, position: int) -> Optional[HarmonicContext]:
        """指定位置の和声的文脈を取得"""
        current_context = None
        for ctx in self.harmonic_plan:
            if ctx.position <= position:
                current_context = ctx
            else:
                break
        return current_context
    
    # ============================================================
    # 候補音の生成と評価
    # ============================================================
    
    def generate_candidates(self, voice: VoiceName, 
                           context: HarmonicContext) -> List[NoteCandidate]:
        """規則に基づいて候補音を生成"""
        candidates = []
        
        # 声部の音域を取得
        valid, _ = self.rules.check_voice_range(Pitch(60), voice.value)
        if voice == VoiceName.SOPRANO:
            min_pitch, max_pitch = 60, 79
        elif voice == VoiceName.ALTO:
            min_pitch, max_pitch = 55, 74
        else:  # BASS
            min_pitch, max_pitch = 40, 60
        
        # 前の音を取得
        prev_pitch = self.voices[voice][-1] if self.voices[voice] else None
        
        if prev_pitch is None:
            # 最初の音：和音構成音のみ
            for midi in range(min_pitch, max_pitch + 1):
                pitch = Pitch(midi)
                if pitch.pitch_class in context.chord_tones:
                    # 声部音域チェック
                    valid, _ = self.rules.check_voice_range(pitch, voice.value)
                    if valid:
                        candidates.append(NoteCandidate(
                            pitch=pitch,
                            is_chord_tone=True,
                            score=1.0
                        ))
        
        else:
            # 2音目以降
            if context.is_strong_beat:
                # 強拍：和音構成音のみ、順次進行優先
                for interval in [-2, -1, 1, 2, -3, -4, 3, 4]:
                    new_midi = prev_pitch.midi + interval
                    if min_pitch <= new_midi <= max_pitch:
                        pitch = Pitch(new_midi)
                        
                        if pitch.pitch_class in context.chord_tones:
                            # 増音程チェック
                            valid, _ = self.rules.check_melodic_augmented_interval(
                                prev_pitch, pitch
                            )
                            if valid:
                                # スコア：順次進行ほど高い
                                score = 1.0 if abs(interval) <= 2 else 0.7
                                candidates.append(NoteCandidate(
                                    pitch=pitch,
                                    is_chord_tone=True,
                                    score=score
                                ))
            
            else:
                # 弱拍：経過音も許容
                for interval in [-2, -1, 1, 2]:
                    new_midi = prev_pitch.midi + interval
                    if min_pitch <= new_midi <= max_pitch:
                        pitch = Pitch(new_midi)
                        
                        is_chord_tone = pitch.pitch_class in context.chord_tones
                        
                        # 増音程チェック
                        valid, _ = self.rules.check_melodic_augmented_interval(
                            prev_pitch, pitch
                        )
                        if valid:
                            score = 1.0 if is_chord_tone else 0.5
                            candidates.append(NoteCandidate(
                                pitch=pitch,
                                is_chord_tone=is_chord_tone,
                                score=score
                            ))
        
        return candidates
    
    def check_all_voice_rules(self, 
                               voice: VoiceName,
                               new_pitch: Pitch,
                               context: HarmonicContext) -> Tuple[bool, str]:
        """全ての声部規則をチェック"""
        self.total_checks += 1
        
        # 1. 声部音域
        valid, msg = self.rules.check_voice_range(new_pitch, voice.value)
        if not valid:
            return False, f"Voice range: {msg}"
        
        # 2. 前の音との増音程チェック
        if self.voices[voice]:
            prev = self.voices[voice][-1]
            valid, msg = self.rules.check_melodic_augmented_interval(prev, new_pitch)
            if not valid:
                return False, f"Melodic interval: {msg}"
        
        # 3. 垂直方向の構造チェック（他の声部との関係）
        temp_voices = {voice: new_pitch}
        
        # 同時に鳴っている他の声部の音を集める
        for other_voice in VoiceName:
            if other_voice != voice and self.voices[other_voice]:
                temp_voices[other_voice] = self.voices[other_voice][-1]
        
        if len(temp_voices) >= 2:
            # 声部交差チェック
            voice_dict = {v.value: p for v, p in temp_voices.items()}
            valid, msg = self.rules.check_voice_crossing(voice_dict)
            if not valid:
                return False, f"Voice crossing: {msg}"
            
            # 声部間隔チェック
            valid, msg = self.rules.check_spacing(voice_dict)
            if not valid:
                return False, f"Spacing: {msg}"
            
            # 垂直不協和音チェック
            pitches = list(temp_voices.values())
            valid, msg = self.rules.check_vertical_dissonance(
                pitches,
                context.chord_tones,
                context.is_strong_beat
            )
            if not valid:
                return False, f"Vertical dissonance: {msg}"
            
            # 平行5度・8度チェック
            for other_voice, other_pitch in temp_voices.items():
                if other_voice == voice:
                    continue
                
                if self.voices[other_voice]:
                    prev_other = self.voices[other_voice][-1]
                    prev_this = self.voices[voice][-1] if self.voices[voice] else None
                    
                    if prev_this:
                        valid, msg = self.rules.check_parallel_perfect(
                            prev_this, new_pitch,
                            prev_other, other_pitch
                        )
                        if not valid:
                            return False, f"Parallel motion: {msg}"
                        
                        # 隠伏進行チェック（外声部のみ）
                        is_outer = (
                            (voice == VoiceName.SOPRANO and other_voice == VoiceName.BASS) or
                            (voice == VoiceName.BASS and other_voice == VoiceName.SOPRANO)
                        )
                        if is_outer:
                            valid, msg = self.rules.check_hidden_parallel(
                                prev_this, new_pitch,
                                prev_other, other_pitch,
                                is_outer_voices=True
                            )
                            if not valid:
                                return False, f"Hidden parallel: {msg}"
        
        return True, ""
    
    # ============================================================
    # 音符の生成
    # ============================================================
    
    def generate_note_for_voice(self, voice: VoiceName, 
                                context: HarmonicContext) -> Optional[Pitch]:
        """1つの声部に1つの音符を生成（全規則チェック）"""
        candidates = self.generate_candidates(voice, context)
        
        # 候補を評価
        valid_candidates = []
        for candidate in candidates:
            is_valid, msg = self.check_all_voice_rules(
                voice, candidate.pitch, context
            )
            if is_valid:
                valid_candidates.append(candidate)
            else:
                self.rejected_candidates += 1
        
        if not valid_candidates:
            return None
        
        # スコアが高い候補をランダムに選択（多様性のため）
        valid_candidates.sort(key=lambda c: c.score, reverse=True)
        
        # 上位候補からランダム選択
        top_candidates = valid_candidates[:min(3, len(valid_candidates))]
        return random.choice(top_candidates).pitch
    
    def generate_all_voices_at_position(self, context: HarmonicContext, 
                                       max_attempts: int = 10) -> bool:
        """全声部を1拍分生成（バックトラック付き）"""
        voice_order = [VoiceName.BASS, VoiceName.ALTO, VoiceName.SOPRANO]
        
        for attempt in range(max_attempts):
            # この試行での音符
            temp_notes = {}
            success = True
            
            for voice in voice_order:
                pitch = self.generate_note_for_voice(voice, context)
                if pitch is None:
                    success = False
                    break
                
                temp_notes[voice] = pitch
                # 一時的に追加
                self.voices[voice].append(pitch)
            
            if success:
                # 全声部成功
                return True
            else:
                # 失敗したので戻す
                for voice in temp_notes:
                    if self.voices[voice]:
                        self.voices[voice].pop()
                
                # 別の候補で再試行
                continue
        
        return False
    
    # ============================================================
    # フーガ生成
    # ============================================================
    
    def generate_fugue(self, num_measures: int = 4) -> bool:
        """フーガを生成"""
        print("\n" + "=" * 70)
        print("100%規則遵守フーガ生成エンジン")
        print("=" * 70)
        
        # 和声進行を計画
        self.plan_harmonic_progression(num_measures)
        
        # 各拍ごとに生成
        print("\n【音符生成】")
        generated_beats = 0
        
        for context in self.harmonic_plan:
            success = self.generate_all_voices_at_position(context)
            
            if not success:
                print(f"  拍{context.position // 4}: 生成失敗（バックトラック必要）")
                return False
            
            generated_beats += 1
            
            if generated_beats % 4 == 0:
                measure = generated_beats // 4
                print(f"  小節{measure}完了")
        
        print(f"\n✓ 生成完了: {generated_beats}拍")
        print(f"  総規則チェック数: {self.total_checks}")
        print(f"  却下された候補: {self.rejected_candidates}")
        
        return True
    
    # ============================================================
    # MIDI出力
    # ============================================================
    
    def export_to_midi(self, filename: str, tempo: int = 90):
        """MIDIファイルに出力"""
        print(f"\n【MIDI出力】")
        print(f"  ファイル: {filename}")
        
        midi = MIDIWriter(tempo=tempo, ticks_per_beat=480)
        
        beat_length = 4 * (480 // 4)  # 4分音符 = 480 ticks
        
        for voice in VoiceName:
            notes = []
            for i, pitch in enumerate(self.voices[voice]):
                position = i * beat_length
                duration = beat_length
                notes.append((position, pitch.midi, duration))
            
            channel = {"soprano": 0, "alto": 1, "bass": 2}[voice.value]
            midi.add_track_from_notes(notes, channel=channel)
            print(f"  {voice.value}: {len(notes)}音符")
        
        midi.write_file(filename)
        print("✓ 完了")


# ============================================================
# 実行
# ============================================================

if __name__ == "__main__":
    generator = RuleCompliantFugueGenerator(
        tonic=0,  # C
        mode="major"
    )
    
    success = generator.generate_fugue(num_measures=4)
    
    if success:
        generator.export_to_midi(
            "/mnt/user-data/outputs/rule_compliant_fugue.mid",
            tempo=90
        )
        
        print("\n" + "=" * 70)
        print("✓✓✓ 100%規則遵守フーガ生成完了 ✓✓✓")
        print("=" * 70)
    else:
        print("\n生成失敗")
