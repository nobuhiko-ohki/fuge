"""
声部導音テクニック統合フーガ生成エンジン
Voice Leading Techniques Applied Fugue Generator

Piston "Harmony" のテクニックを実装：
1. 共通音保持
2. 反行
3. 最短距離の原則
4. 和音の展開
5. 順次進行優先
"""

from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum
import random

from harmony_rules_complete import HarmonyRules, Pitch, ScaleDegree
from midi_writer import MIDIWriter


class Voice(Enum):
    """声部"""
    SOPRANO = "soprano"
    ALTO = "alto"
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


class VoiceLeadingGenerator:
    """声部導音テクニックを使用したフーガ生成"""
    
    def __init__(self, tonic_pc: int = 0):
        self.rules = HarmonyRules()
        self.tonic_pc = tonic_pc
        self.scale = self.rules.get_major_scale(tonic_pc)
        
        # 声部の音域
        self.ranges = {
            Voice.SOPRANO: (60, 79),
            Voice.ALTO: (55, 74),
            Voice.BASS: (40, 60)
        }
        
        # 声部の状態
        self.voices: Dict[Voice, List[int]] = {
            Voice.SOPRANO: [],
            Voice.ALTO: [],
            Voice.BASS: []
        }
        
        # 和声進行
        self.progression: List[ChordProgression] = []
    
    # ============================================================
    # テクニック1: 共通音保持
    # ============================================================
    
    def find_common_tones(self, chord1: Set[int], chord2: Set[int]) -> Set[int]:
        """2つの和音の共通音を見つける"""
        return chord1 & chord2
    
    # ============================================================
    # テクニック2: 最短距離の原則
    # ============================================================
    
    def find_nearest_chord_tone(self, current_midi: int, 
                                target_pcs: Set[int],
                                min_midi: int, max_midi: int) -> int:
        """現在の音高から最も近い和音構成音を見つける"""
        candidates = []
        
        for pc in target_pcs:
            # 現在のオクターブ周辺を探索
            current_octave = current_midi // 12
            for oct in range(current_octave - 1, current_octave + 2):
                candidate = pc + oct * 12
                if min_midi <= candidate <= max_midi:
                    distance = abs(candidate - current_midi)
                    candidates.append((candidate, distance))
        
        if not candidates:
            return current_midi
        
        # 最短距離を返す
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]
    
    # ============================================================
    # テクニック3: 順次進行優先
    # ============================================================
    
    def get_stepwise_candidates(self, current_midi: int,
                                target_pcs: Set[int],
                                min_midi: int, max_midi: int) -> List[Tuple[int, int]]:
        """順次進行を優先した候補リスト
        
        Returns:
            [(midi, priority), ...] 優先度が低いほど良い
        """
        candidates = []
        
        for pc in target_pcs:
            current_octave = current_midi // 12
            for oct in range(current_octave - 1, current_octave + 2):
                candidate = pc + oct * 12
                if min_midi <= candidate <= max_midi:
                    interval = abs(candidate - current_midi)
                    
                    # 優先度付け
                    if interval == 0:
                        priority = 0  # 保持（最優先）
                    elif interval == 1:
                        priority = 1  # 半音
                    elif interval == 2:
                        priority = 2  # 全音
                    elif interval <= 4:
                        priority = 3  # 短3度・長3度
                    elif interval <= 7:
                        priority = 5  # 完全4度・5度
                    else:
                        priority = 10  # 大きな跳躍
                    
                    candidates.append((candidate, priority))
        
        candidates.sort(key=lambda x: x[1])
        return candidates
    
    # ============================================================
    # テクニック4: 反行の適用
    # ============================================================
    
    def check_contrary_motion(self, soprano_prev: int, soprano_new: int,
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
    
    def plan_progression(self, num_chords: int = 8):
        """和声進行を計画"""
        print("\n【和声進行計画】")
        
        # 簡単な進行: I-IV-V-I を繰り返し
        pattern = [
            ScaleDegree.I,
            ScaleDegree.IV,
            ScaleDegree.V,
            ScaleDegree.I
        ]
        
        degrees = []
        for i in range(num_chords):
            degrees.append(pattern[i % len(pattern)])
        
        # 最後はV-Iで終わる
        degrees[-2] = ScaleDegree.V
        degrees[-1] = ScaleDegree.I
        
        # ChordProgressionに変換
        for i, degree in enumerate(degrees):
            deg_idx = degree.value - 1
            root_pc = self.scale[deg_idx]
            
            # 和音の種類を決定
            if degree in [ScaleDegree.I, ScaleDegree.IV, ScaleDegree.V]:
                quality = "major"
            else:
                quality = "minor"
            
            triad = self.rules.build_triad(root_pc, quality)
            
            prog = ChordProgression(
                position=i,
                degree=degree,
                chord_tones=set(triad),
                root_pc=triad[0],
                third_pc=triad[1],
                fifth_pc=triad[2]
            )
            
            self.progression.append(prog)
            print(f"  {i}: {degree.name}")
    
    # ============================================================
    # 声部配置の生成
    # ============================================================
    
    def voice_first_chord(self, prog: ChordProgression):
        """最初の和音を配置（密集配置）"""
        # Bass: 根音
        bass_min, bass_max = self.ranges[Voice.BASS]
        bass = prog.root_pc
        while bass < bass_min:
            bass += 12
        while bass > bass_max:
            bass -= 12
        self.voices[Voice.BASS].append(bass)
        
        # Alto: 第三音
        alto_min, alto_max = self.ranges[Voice.ALTO]
        alto = prog.third_pc
        while alto < alto_min:
            alto += 12
        while alto > alto_max:
            alto -= 12
        # Bass より上に
        while alto <= bass:
            alto += 12
        if alto > alto_max:
            alto = prog.fifth_pc
            while alto <= bass:
                alto += 12
        self.voices[Voice.ALTO].append(alto)
        
        # Soprano: 第五音または根音
        soprano_min, soprano_max = self.ranges[Voice.SOPRANO]
        soprano = prog.fifth_pc
        while soprano < soprano_min:
            soprano += 12
        while soprano > soprano_max:
            soprano -= 12
        # Alto より上に
        while soprano <= self.voices[Voice.ALTO][-1]:
            soprano += 12
        if soprano > soprano_max:
            # 根音を試す
            soprano = prog.root_pc
            while soprano <= self.voices[Voice.ALTO][-1]:
                soprano += 12
        
        self.voices[Voice.SOPRANO].append(soprano)
        
        print(f"\n最初の和音配置:")
        print(f"  S: {soprano} ({prog.degree.name})")
        print(f"  A: {alto}")
        print(f"  B: {bass}")
    
    def voice_next_chord(self, prev_prog: ChordProgression, 
                        curr_prog: ChordProgression):
        """次の和音を配置（声部導音テクニックを使用）"""
        
        # 共通音を見つける
        common = self.find_common_tones(prev_prog.chord_tones, curr_prog.chord_tones)
        
        # 各声部を処理
        for voice in [Voice.BASS, Voice.ALTO, Voice.SOPRANO]:
            prev_midi = self.voices[voice][-1]
            prev_pc = prev_midi % 12
            min_midi, max_midi = self.ranges[voice]
            
            # Bass は常に根音
            if voice == Voice.BASS:
                new_midi = curr_prog.root_pc
                while new_midi < min_midi:
                    new_midi += 12
                while new_midi > max_midi:
                    new_midi -= 12
                
                # 最短距離に調整
                if abs(new_midi - 12 - prev_midi) < abs(new_midi - prev_midi):
                    if new_midi - 12 >= min_midi:
                        new_midi -= 12
                elif abs(new_midi + 12 - prev_midi) < abs(new_midi - prev_midi):
                    if new_midi + 12 <= max_midi:
                        new_midi += 12
                
                self.voices[voice].append(new_midi)
            
            else:
                # 共通音があり、現在の音が共通音なら保持
                if common and prev_pc in common:
                    self.voices[voice].append(prev_midi)
                
                else:
                    # 順次進行を優先
                    candidates = self.get_stepwise_candidates(
                        prev_midi, curr_prog.chord_tones, min_midi, max_midi
                    )
                    
                    if candidates:
                        # 上位候補から選択
                        # 他の声部との衝突を避ける
                        for candidate, priority in candidates:
                            # 声部交差チェック
                            valid = True
                            if voice == Voice.ALTO:
                                if candidate >= self.voices[Voice.SOPRANO][-1]:
                                    valid = False
                                if candidate <= self.voices[Voice.BASS][-1]:
                                    valid = False
                            elif voice == Voice.SOPRANO:
                                if candidate <= self.voices[Voice.ALTO][-1]:
                                    valid = False
                            
                            # 間隔チェック（上3声は1オクターブ以内）
                            if voice == Voice.SOPRANO and Voice.ALTO in self.voices:
                                if candidate - self.voices[Voice.ALTO][-1] > 12:
                                    valid = False
                            
                            if valid:
                                self.voices[voice].append(candidate)
                                break
                        else:
                            # 候補がない場合は最短距離
                            nearest = self.find_nearest_chord_tone(
                                prev_midi, curr_prog.chord_tones, min_midi, max_midi
                            )
                            self.voices[voice].append(nearest)
                    else:
                        # fallback
                        self.voices[voice].append(prev_midi)
    
    # ============================================================
    # 生成とMIDI出力
    # ============================================================
    
    def generate(self, num_chords: int = 8):
        """フーガを生成"""
        print("=" * 70)
        print("声部導音テクニック統合フーガ生成")
        print("=" * 70)
        
        self.plan_progression(num_chords)
        
        print("\n【声部配置生成】")
        
        # 最初の和音
        self.voice_first_chord(self.progression[0])
        
        # 残りの和音
        for i in range(1, len(self.progression)):
            self.voice_next_chord(self.progression[i-1], self.progression[i])
            
            if (i + 1) % 2 == 0:
                print(f"  {i+1}個目の和音完了")
        
        print(f"\n✓ 生成完了: {len(self.progression)}個の和音")
    
    def export_midi(self, filename: str, tempo: int = 80):
        """MIDIファイルに出力"""
        print(f"\n【MIDI出力】")
        print(f"  ファイル: {filename}")
        
        midi = MIDIWriter(tempo=tempo, ticks_per_beat=480)
        
        # 4分音符 = 480 ticks
        beat_length = 480
        
        for voice in Voice:
            notes = []
            for i, midi_pitch in enumerate(self.voices[voice]):
                position = i * beat_length
                duration = beat_length
                notes.append((position, midi_pitch, duration))
            
            channel = {"soprano": 0, "alto": 1, "bass": 2}[voice.value]
            midi.add_track_from_notes(notes, channel=channel)
            print(f"  {voice.value}: {len(notes)}音符")
        
        midi.write_file(filename)
        print("✓ 完了")


# ============================================================
# テスト実行
# ============================================================

if __name__ == "__main__":
    generator = VoiceLeadingGenerator(tonic_pc=0)  # C major
    generator.generate(num_chords=8)
    generator.export_midi(
        "/mnt/user-data/outputs/voice_leading_fugue.mid",
        tempo=80
    )
    
    print("\n" + "=" * 70)
    print("✓ 声部導音テクニック適用フーガ生成完了")
    print("=" * 70)
