"""
MIDI Writer - 標準ライブラリのみを使用したMIDIファイル生成

外部ライブラリなしでMIDIファイルを生成します。
"""

import struct
from typing import List, Tuple
from harmony_rules_complete import Pitch

from dataclasses import dataclass

@dataclass
class Voice:
    """Voice data structure"""
    pitches: List
    name: str = ""


class MIDIWriter:
    """MIDIファイルを生成するクラス"""
    
    def __init__(self, tempo: int = 120, ticks_per_beat: int = 480):
        """
        Args:
            tempo: テンポ（BPM）
            ticks_per_beat: 1拍あたりのティック数
        """
        self.tempo = tempo
        self.ticks_per_beat = ticks_per_beat
        self.tracks = []
    
    def _write_variable_length(self, value: int) -> bytes:
        """可変長数値をMIDIフォーマットで書き込む"""
        result = bytearray()
        result.append(value & 0x7F)
        value >>= 7
        while value > 0:
            result.insert(0, (value & 0x7F) | 0x80)
            value >>= 7
        return bytes(result)
    
    def _write_header(self, num_tracks: int) -> bytes:
        """MIDIヘッダーチャンクを生成"""
        header = b'MThd'  # チャンクタイプ
        length = struct.pack('>I', 6)  # ヘッダー長
        format_type = struct.pack('>H', 1)  # フォーマット1（複数トラック）
        num_tracks_bytes = struct.pack('>H', num_tracks)
        division = struct.pack('>H', self.ticks_per_beat)
        return header + length + format_type + num_tracks_bytes + division
    
    def _create_tempo_event(self) -> bytes:
        """テンポ設定イベントを生成"""
        microseconds_per_quarter = int(60000000 / self.tempo)
        tempo_bytes = struct.pack('>I', microseconds_per_quarter)[1:]  # 24ビット
        return b'\x00\xFF\x51\x03' + tempo_bytes
    
    def _create_note_events(self, pitch: int, duration_ticks: int, 
                           velocity: int = 64) -> List[Tuple[int, bytes]]:
        """ノートオン/オフイベントを生成
        
        Returns:
            [(delta_time, event_bytes), ...]のリスト
        """
        # ノートオン
        note_on = bytes([0x90, pitch, velocity])
        # ノートオフ
        note_off = bytes([0x80, pitch, 0])
        
        return [
            (0, note_on),
            (duration_ticks, note_off)
        ]
    
    def add_track_from_voice(self, voice: Voice, note_duration_ticks: int = 480,
                            channel: int = 0, velocity: int = 64):
        """声部からMIDIトラックを生成
        
        Args:
            voice: 声部データ
            note_duration_ticks: 各音符の長さ（ティック数）
            channel: MIDIチャンネル（0-15）
            velocity: ベロシティ（音の強さ、0-127）
        """
        events = []
        current_time = 0
        
        for pitch in voice.pitches:
            note_events = self._create_note_events(
                pitch.midi,
                note_duration_ticks, 
                velocity
            )
            
            for delta, event in note_events:
                events.append((current_time + delta, event))
                current_time += delta
        
        self.tracks.append(events)
    
    def add_track_from_notes(self, notes: List[Tuple[int, int, int]], 
                            channel: int = 0):
        """音符リストからMIDIトラックを生成
        
        Args:
            notes: [(start_ticks, pitch, duration_ticks), ...]
            channel: MIDIチャンネル
        """
        events = []
        
        for start_time, pitch, duration in notes:
            # ノートオン
            events.append((start_time, bytes([0x90 | channel, pitch, 64])))
            # ノートオフ
            events.append((start_time + duration, bytes([0x80 | channel, pitch, 0])))
        
        # 時間順にソート
        events.sort(key=lambda x: x[0])
        
        self.tracks.append(events)
    
    def _write_track(self, events: List[Tuple[int, bytes]], 
                    is_first_track: bool = False) -> bytes:
        """トラックチャンクを生成"""
        track_data = bytearray()
        
        # 最初のトラックにはテンポ情報を追加
        if is_first_track:
            track_data.extend(self._create_tempo_event())
        
        # イベントをデルタタイム付きで書き込む
        last_time = 0
        for abs_time, event in events:
            delta = abs_time - last_time
            track_data.extend(self._write_variable_length(delta))
            track_data.extend(event)
            last_time = abs_time
        
        # トラック終了
        track_data.extend(b'\x00\xFF\x2F\x00')
        
        # トラックチャンクヘッダー
        header = b'MTrk'
        length = struct.pack('>I', len(track_data))
        
        return header + length + track_data
    
    def write_file(self, filename: str):
        """MIDIファイルに書き出す"""
        with open(filename, 'wb') as f:
            # ヘッダー
            f.write(self._write_header(len(self.tracks)))
            
            # 各トラック
            for i, track in enumerate(self.tracks):
                f.write(self._write_track(track, is_first_track=(i == 0)))
    
    def clear_tracks(self):
        """すべてのトラックをクリア"""
        self.tracks = []


# 使用例とテスト
if __name__ == "__main__":
    print("=== MIDI Writer テスト ===\n")
    
    # テスト用の簡単なメロディ
    from harmony_rules_complete import Pitch
    
    # ド・レ・ミ・ファ・ソのメロディ
    test_voice = Voice([
        Pitch(60, "C4"),
        Pitch(62, "D4"),
        Pitch(64, "E4"),
        Pitch(65, "F4"),
        Pitch(67, "G4"),
    ], name="テストメロディ")
    
    # MIDIファイル作成
    midi = MIDIWriter(tempo=120, ticks_per_beat=480)
    midi.add_track_from_voice(test_voice, note_duration_ticks=480)
    midi.write_file("/home/claude/test_melody.mid")
    
    print("✓ テストMIDIファイルを生成: test_melody.mid")
    print(f"  メロディ: {' - '.join([p.name for p in test_voice.pitches])}")
    
    # 複数トラックのテスト
    soprano = Voice([Pitch(67), Pitch(69), Pitch(71)], name="ソプラノ")
    alto = Voice([Pitch(64), Pitch(65), Pitch(67)], name="アルト")
    
    midi2 = MIDIWriter(tempo=100)
    midi2.add_track_from_voice(soprano, note_duration_ticks=480, channel=0)
    midi2.add_track_from_voice(alto, note_duration_ticks=480, channel=1)
    midi2.write_file("/home/claude/test_harmony.mid")
    
    print("✓ 和声テストMIDIファイルを生成: test_harmony.mid")
    print("  2つの声部を含む")
