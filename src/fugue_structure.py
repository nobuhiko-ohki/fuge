"""
フーガ構造モジュール
Fugue Structure Module

フーガに特有の構造要素を定義・管理します。
"""

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum
from counterpoint_engine import Pitch, Voice


class FugueVoiceType(Enum):
    """フーガにおける声部の種類"""
    SOPRANO = "soprano"
    ALTO = "alto"
    TENOR = "tenor"
    BASS = "bass"


class FugueSection(Enum):
    """フーガの構成部分"""
    EXPOSITION = "exposition"  # 提示部
    EPISODE = "episode"  # 間奏部（エピソード）
    MIDDLE_ENTRY = "middle_entry"  # 中間提示
    STRETTO = "stretto"  # ストレット
    CODA = "coda"  # コーダ


@dataclass
class Key:
    """調性を表現するクラス"""
    tonic: str  # 主音（例: "C", "D", "F#"）
    mode: str  # 旋法（"major" or "minor"）
    
    def get_dominant_key(self) -> 'Key':
        """属調を取得"""
        # 簡易実装：5度上の調
        note_map = {
            'C': 'G', 'C#': 'G#', 'D': 'A', 'D#': 'A#', 'E': 'B',
            'F': 'C', 'F#': 'C#', 'G': 'D', 'G#': 'D#', 'A': 'E',
            'A#': 'F', 'B': 'F#'
        }
        dominant_tonic = note_map.get(self.tonic, 'G')
        # 長調の属調は長調、短調の属調も長調が一般的
        return Key(dominant_tonic, "major")
    
    def get_subdominant_key(self) -> 'Key':
        """下属調を取得"""
        # 簡易実装：5度下（4度上）の調
        note_map = {
            'C': 'F', 'C#': 'F#', 'D': 'G', 'D#': 'G#', 'E': 'A',
            'F': 'Bb', 'F#': 'B', 'G': 'C', 'G#': 'C#', 'A': 'D',
            'A#': 'D#', 'B': 'E'
        }
        subdominant_tonic = note_map.get(self.tonic, 'F')
        return Key(subdominant_tonic, self.mode)
    
    def get_relative_key(self) -> 'Key':
        """平行調を取得"""
        # 簡易実装
        if self.mode == "major":
            # 長調の平行短調は短3度下
            note_map = {
                'C': 'A', 'C#': 'A#', 'D': 'B', 'D#': 'C', 'E': 'C#',
                'F': 'D', 'F#': 'D#', 'G': 'E', 'G#': 'F', 'A': 'F#',
                'A#': 'G', 'B': 'G#'
            }
            relative_tonic = note_map.get(self.tonic, 'A')
            return Key(relative_tonic, "minor")
        else:
            # 短調の平行長調は短3度上
            note_map = {
                'C': 'Eb', 'C#': 'E', 'D': 'F', 'D#': 'F#', 'E': 'G',
                'F': 'Ab', 'F#': 'A', 'G': 'Bb', 'G#': 'B', 'A': 'C',
                'A#': 'C#', 'B': 'D'
            }
            relative_tonic = note_map.get(self.tonic, 'C')
            return Key(relative_tonic, "major")


@dataclass
class Subject:
    """フーガの主題"""
    pitches: List[Pitch]
    key: Key
    name: str = "主題"
    
    def get_length(self) -> int:
        """主題の長さ（音符数）"""
        return len(self.pitches)
    
    def transpose(self, semitones: int) -> 'Subject':
        """主題を移調"""
        transposed_pitches = [
            Pitch(p.midi_number + semitones) for p in self.pitches
        ]
        return Subject(transposed_pitches, self.key, f"{self.name}(移調)")
    
    def get_answer(self, answer_type: str = "tonal") -> 'Subject':
        """応答（Answer）を生成
        
        Args:
            answer_type: "tonal"（調的応答）または "real"（実音応答）
        """
        if answer_type == "real":
            # 実音応答：完全5度上に機械的に移調
            return self.transpose(7)
        else:
            # 調的応答：より複雑な変換が必要（簡易実装）
            # 主音→属音、属音→主音などの変換
            transposed = self.transpose(7)
            transposed.name = "応答"
            return transposed
    
    def invert(self) -> 'Subject':
        """主題を反転（上下逆転）"""
        if not self.pitches:
            return Subject([], self.key, f"{self.name}(反転)")
        
        # 最初の音を軸として反転
        axis = self.pitches[0].midi_number
        inverted_pitches = [
            Pitch(axis - (p.midi_number - axis)) for p in self.pitches
        ]
        return Subject(inverted_pitches, self.key, f"{self.name}(反転)")
    
    def retrograde(self) -> 'Subject':
        """主題を逆行"""
        reversed_pitches = list(reversed(self.pitches))
        return Subject(reversed_pitches, self.key, f"{self.name}(逆行)")
    
    def retrograde_inversion(self) -> 'Subject':
        """主題を反転逆行"""
        return self.invert().retrograde()


@dataclass
class Countersubject:
    """対主題（Counter-subject）"""
    pitches: List[Pitch]
    name: str = "対主題"
    
    def __post_init__(self):
        """対主題は主題に対して対位法的に適切でなければならない"""
        pass


@dataclass
class FugueEntry:
    """フーガにおける主題の登場"""
    subject: Subject
    voice_type: FugueVoiceType
    start_position: int  # 開始位置（拍数または小節数）
    key: Key
    is_answer: bool = False  # 応答かどうか


class FugueStructure:
    """フーガ全体の構造を管理"""
    
    def __init__(self, num_voices: int, main_key: Key, subject: Subject):
        """
        Args:
            num_voices: 声部数（通常3-4）
            main_key: 主調
            subject: 主題
        """
        self.num_voices = num_voices
        self.main_key = main_key
        self.subject = subject
        self.entries: List[FugueEntry] = []
        self.sections: List[tuple] = []  # (section_type, start_position, end_position)
    
    def create_exposition(self) -> List[FugueEntry]:
        """提示部を生成
        
        標準的なフーガの提示部では：
        1. 主題が主調で提示される
        2. 応答が属調で提示される（他の声部で）
        3. 主題と応答が交互に現れる
        """
        entries = []
        voice_order = self._get_voice_order()
        
        position = 0
        for i, voice_type in enumerate(voice_order):
            if i % 2 == 0:
                # 主題
                entry = FugueEntry(
                    subject=self.subject,
                    voice_type=voice_type,
                    start_position=position,
                    key=self.main_key,
                    is_answer=False
                )
            else:
                # 応答
                answer = self.subject.get_answer("tonal")
                dominant_key = self.main_key.get_dominant_key()
                entry = FugueEntry(
                    subject=answer,
                    voice_type=voice_type,
                    start_position=position,
                    key=dominant_key,
                    is_answer=True
                )
            
            entries.append(entry)
            position += self.subject.get_length()
        
        self.entries.extend(entries)
        self.sections.append((FugueSection.EXPOSITION, 0, position))
        return entries
    
    def _get_voice_order(self) -> List[FugueVoiceType]:
        """声部の登場順序を決定"""
        if self.num_voices == 3:
            return [FugueVoiceType.ALTO, FugueVoiceType.SOPRANO, FugueVoiceType.BASS]
        elif self.num_voices == 4:
            return [
                FugueVoiceType.ALTO,
                FugueVoiceType.SOPRANO,
                FugueVoiceType.BASS,
                FugueVoiceType.TENOR
            ]
        else:
            # デフォルト
            return [FugueVoiceType.SOPRANO, FugueVoiceType.ALTO]
    
    def add_stretto(self, start_position: int, overlap_distance: int):
        """ストレット（主題の密接模倣）を追加
        
        Args:
            start_position: 開始位置
            overlap_distance: 主題間の重なり距離
        """
        entries = []
        voice_types = self._get_voice_order()
        
        position = start_position
        for voice_type in voice_types:
            entry = FugueEntry(
                subject=self.subject,
                voice_type=voice_type,
                start_position=position,
                key=self.main_key,
                is_answer=False
            )
            entries.append(entry)
            position += overlap_distance  # 主題が完了する前に次の声部が入る
        
        self.entries.extend(entries)
        end_position = position + self.subject.get_length()
        self.sections.append((FugueSection.STRETTO, start_position, end_position))
    
    def get_section_info(self) -> str:
        """構造の概要を文字列で返す"""
        info = f"フーガ構造分析\n"
        info += f"声部数: {self.num_voices}\n"
        info += f"主調: {self.main_key.tonic} {self.main_key.mode}\n"
        info += f"主題の長さ: {self.subject.get_length()}音\n\n"
        
        info += "セクション:\n"
        for section, start, end in self.sections:
            info += f"  {section.value}: 位置 {start}-{end}\n"
        
        info += f"\n主題の登場: {len(self.entries)}回\n"
        for i, entry in enumerate(self.entries):
            entry_type = "応答" if entry.is_answer else "主題"
            info += f"  {i+1}. {entry.voice_type.value} - {entry_type} ({entry.key.tonic}調, 位置{entry.start_position})\n"
        
        return info


# 使用例
if __name__ == "__main__":
    print("=== フーガ構造モジュール ===\n")
    
    # ハ長調の簡単な主題を作成
    c_major = Key("C", "major")
    subject_pitches = [
        Pitch(60),  # C4
        Pitch(62),  # D4
        Pitch(64),  # E4
        Pitch(65),  # F4
        Pitch(67),  # G4
    ]
    subject = Subject(subject_pitches, c_major, "主題")
    
    print(f"主題: {[p.name for p in subject.pitches]}")
    
    # 応答を生成
    answer = subject.get_answer("tonal")
    print(f"応答: {[p.name for p in answer.pitches]}")
    
    # 反転
    inverted = subject.invert()
    print(f"反転: {[p.name for p in inverted.pitches]}")
    
    # 逆行
    retrograde = subject.retrograde()
    print(f"逆行: {[p.name for p in retrograde.pitches]}")
    
    print("\n--- フーガ構造の生成 ---")
    fugue = FugueStructure(num_voices=3, main_key=c_major, subject=subject)
    fugue.create_exposition()
    fugue.add_stretto(start_position=20, overlap_distance=3)
    
    print(fugue.get_section_info())
