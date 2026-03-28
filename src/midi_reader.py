"""
MIDI Reader - 標準ライブラリのみを使用したMIDIファイル解析

midi_writer.py と対をなすリーダー。
バッハのフーガMIDIを解析するための基盤。

出力形式:
  MIDIFile → List[MIDITrack]
  MIDITrack → List[NoteOnOff]
  NoteOnOff → (start_tick, end_tick, channel, pitch, velocity)
"""

import struct
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, BinaryIO


@dataclass
class MIDINote:
    """解析済みのMIDIノート"""
    start_tick: int      # 開始時刻（tick）
    end_tick: int        # 終了時刻（tick）
    channel: int         # MIDIチャンネル（0-15）
    pitch: int           # MIDIノート番号（0-127）
    velocity: int        # ベロシティ（0-127）

    @property
    def duration_tick(self) -> int:
        return self.end_tick - self.start_tick

    @property
    def pitch_class(self) -> int:
        return self.pitch % 12

    @property
    def octave(self) -> int:
        return self.pitch // 12 - 1

    def as_tuple(self) -> Tuple[int, int, int]:
        """(start_tick, pitch, duration_tick) — midi_writer互換形式"""
        return (self.start_tick, self.pitch, self.duration_tick)


@dataclass
class MIDITrack:
    """MIDIトラック"""
    notes: List[MIDINote] = field(default_factory=list)
    name: str = ""
    tempo_events: List[Tuple[int, int]] = field(default_factory=list)
    # tempo_events: [(tick, microseconds_per_quarter), ...]

    def get_notes_by_channel(self, channel: int) -> List[MIDINote]:
        return [n for n in self.notes if n.channel == channel]

    @property
    def channels(self) -> set:
        return {n.channel for n in self.notes}

    @property
    def pitch_range(self) -> Tuple[int, int]:
        if not self.notes:
            return (0, 0)
        pitches = [n.pitch for n in self.notes]
        return (min(pitches), max(pitches))


@dataclass
class MIDIFile:
    """解析済みMIDIファイル"""
    format_type: int         # 0, 1, or 2
    ticks_per_beat: int      # 分解能
    tracks: List[MIDITrack] = field(default_factory=list)

    @property
    def all_notes(self) -> List[MIDINote]:
        """全トラック・全チャンネルのノートを時刻順で返す"""
        notes = []
        for track in self.tracks:
            notes.extend(track.notes)
        notes.sort(key=lambda n: (n.start_tick, n.pitch))
        return notes

    def get_voices(self) -> Dict[int, List[MIDINote]]:
        """チャンネル別にノートを分離して返す"""
        voices: Dict[int, List[MIDINote]] = {}
        for note in self.all_notes:
            voices.setdefault(note.channel, []).append(note)
        return voices

    @property
    def duration_ticks(self) -> int:
        """全体の長さ（tick）"""
        if not self.all_notes:
            return 0
        return max(n.end_tick for n in self.all_notes)

    @property
    def duration_beats(self) -> float:
        """全体の長さ（拍数）"""
        return self.duration_ticks / self.ticks_per_beat

    def get_tempo(self) -> int:
        """最初のテンポ値をBPMで返す"""
        for track in self.tracks:
            if track.tempo_events:
                usec = track.tempo_events[0][1]
                return round(60_000_000 / usec)
        return 120  # デフォルト


class MIDIReader:
    """標準ライブラリのみでMIDIファイルを読み込む

    Standard MIDI File (SMF) フォーマット:
    - Format 0: 単一トラック
    - Format 1: 複数トラック、同期（最も一般的）
    - Format 2: 複数トラック、非同期（稀）
    """

    def read(self, filepath: str) -> MIDIFile:
        """MIDIファイルを読み込む"""
        with open(filepath, 'rb') as f:
            return self._parse(f)

    def read_bytes(self, data: bytes) -> MIDIFile:
        """バイト列からMIDIを読み込む"""
        import io
        return self._parse(io.BytesIO(data))

    def _parse(self, f: BinaryIO) -> MIDIFile:
        """MIDIバイナリを解析する"""
        # ヘッダーチャンク
        format_type, num_tracks, ticks_per_beat = self._read_header(f)

        midi_file = MIDIFile(
            format_type=format_type,
            ticks_per_beat=ticks_per_beat,
        )

        # トラックチャンク
        for _ in range(num_tracks):
            track = self._read_track(f)
            midi_file.tracks.append(track)

        return midi_file

    def _read_header(self, f: BinaryIO) -> Tuple[int, int, int]:
        """ヘッダーチャンクを読む"""
        chunk_type = f.read(4)
        if chunk_type != b'MThd':
            raise ValueError(f"Invalid MIDI header: {chunk_type!r}")

        length = struct.unpack('>I', f.read(4))[0]
        if length < 6:
            raise ValueError(f"Header too short: {length}")

        format_type = struct.unpack('>H', f.read(2))[0]
        num_tracks = struct.unpack('>H', f.read(2))[0]
        division = struct.unpack('>H', f.read(2))[0]

        # SMPTE vs ticks-per-beat
        if division & 0x8000:
            raise ValueError("SMPTE time division not supported")

        ticks_per_beat = division

        # 余剰ヘッダーバイトをスキップ
        if length > 6:
            f.read(length - 6)

        return format_type, num_tracks, ticks_per_beat

    def _read_track(self, f: BinaryIO) -> MIDITrack:
        """トラックチャンクを読む"""
        chunk_type = f.read(4)
        if chunk_type != b'MTrk':
            raise ValueError(f"Invalid track header: {chunk_type!r}")

        length = struct.unpack('>I', f.read(4))[0]
        track_data = f.read(length)

        return self._parse_track(track_data)

    def _parse_track(self, data: bytes) -> MIDITrack:
        """トラックデータを解析する"""
        track = MIDITrack()
        pos = 0
        abs_time = 0
        running_status = 0

        # ノートオン追跡: {(channel, pitch): (start_tick, velocity)}
        pending_notes: Dict[Tuple[int, int], Tuple[int, int]] = {}

        while pos < len(data):
            # デルタタイム（可変長）
            delta, bytes_read = self._read_variable_length(data, pos)
            pos += bytes_read
            abs_time += delta

            if pos >= len(data):
                break

            # ステータスバイト
            status = data[pos]

            if status == 0xFF:
                # メタイベント
                pos += 1
                if pos >= len(data):
                    break
                meta_type = data[pos]
                pos += 1
                meta_len, bytes_read = self._read_variable_length(data, pos)
                pos += bytes_read
                meta_data = data[pos:pos + meta_len]
                pos += meta_len

                if meta_type == 0x51 and meta_len == 3:
                    # テンポ
                    usec = (meta_data[0] << 16) | (meta_data[1] << 8) | meta_data[2]
                    track.tempo_events.append((abs_time, usec))
                elif meta_type == 0x03:
                    # トラック名
                    try:
                        track.name = meta_data.decode('utf-8', errors='replace')
                    except Exception:
                        pass
                elif meta_type == 0x2F:
                    # トラック終了
                    break

            elif status == 0xF0 or status == 0xF7:
                # SysEx
                pos += 1
                sysex_len, bytes_read = self._read_variable_length(data, pos)
                pos += bytes_read + sysex_len

            elif status & 0x80:
                # チャンネルメッセージ
                running_status = status
                pos += 1
                msg_type = status & 0xF0
                channel = status & 0x0F

                if msg_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                    # 2データバイト
                    if pos + 1 >= len(data):
                        break
                    data1 = data[pos]
                    data2 = data[pos + 1]
                    pos += 2

                    self._process_note_event(
                        msg_type, channel, data1, data2,
                        abs_time, pending_notes, track)

                elif msg_type in (0xC0, 0xD0):
                    # 1データバイト
                    pos += 1

            else:
                # ランニングステータス
                msg_type = running_status & 0xF0
                channel = running_status & 0x0F

                if msg_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                    if pos + 1 >= len(data):
                        break
                    data1 = data[pos]
                    data2 = data[pos + 1]
                    pos += 2

                    self._process_note_event(
                        msg_type, channel, data1, data2,
                        abs_time, pending_notes, track)

                elif msg_type in (0xC0, 0xD0):
                    pos += 1

        # 未閉じノートを閉じる
        for (ch, pitch), (start, vel) in pending_notes.items():
            track.notes.append(MIDINote(
                start_tick=start, end_tick=abs_time,
                channel=ch, pitch=pitch, velocity=vel))

        # 時刻順にソート
        track.notes.sort(key=lambda n: (n.start_tick, n.pitch))
        return track

    def _process_note_event(
        self, msg_type: int, channel: int,
        data1: int, data2: int, abs_time: int,
        pending: Dict[Tuple[int, int], Tuple[int, int]],
        track: MIDITrack,
    ):
        """ノートオン/オフを処理する"""
        pitch = data1
        velocity = data2
        key = (channel, pitch)

        if msg_type == 0x90 and velocity > 0:
            # ノートオン
            if key in pending:
                # 既にオンのノートを先に閉じる
                start, vel = pending.pop(key)
                track.notes.append(MIDINote(
                    start_tick=start, end_tick=abs_time,
                    channel=channel, pitch=pitch, velocity=vel))
            pending[key] = (abs_time, velocity)

        elif msg_type == 0x80 or (msg_type == 0x90 and velocity == 0):
            # ノートオフ
            if key in pending:
                start, vel = pending.pop(key)
                track.notes.append(MIDINote(
                    start_tick=start, end_tick=abs_time,
                    channel=channel, pitch=pitch, velocity=vel))

    @staticmethod
    def _read_variable_length(data: bytes, pos: int) -> Tuple[int, int]:
        """可変長数値を読む。(値, 読んだバイト数) を返す"""
        value = 0
        bytes_read = 0
        while pos + bytes_read < len(data):
            b = data[pos + bytes_read]
            value = (value << 7) | (b & 0x7F)
            bytes_read += 1
            if not (b & 0x80):
                break
        return value, bytes_read


# ============================================================
# テスト
# ============================================================

if __name__ == "__main__":
    import os
    print("=== MIDI Reader テスト ===\n")

    # midi_writer で生成したファイルを読み返すラウンドトリップテスト
    test_path = os.path.join(os.path.dirname(__file__),
                             "../sample_fugue_v5.mid")
    if os.path.exists(test_path):
        reader = MIDIReader()
        midi = reader.read(test_path)
        print(f"ファイル: {test_path}")
        print(f"フォーマット: {midi.format_type}")
        print(f"トラック数: {len(midi.tracks)}")
        print(f"分解能: {midi.ticks_per_beat} ticks/beat")
        print(f"テンポ: {midi.get_tempo()} BPM")
        print(f"全体長: {midi.duration_beats:.1f}拍")
        print()

        voices = midi.get_voices()
        for ch, notes in sorted(voices.items()):
            pitches = [n.pitch for n in notes]
            lo, hi = min(pitches), max(pitches)
            print(f"  Ch.{ch}: {len(notes)}ノート, "
                  f"音域 {lo}-{hi} (MIDI), "
                  f"長さ {notes[-1].end_tick / midi.ticks_per_beat:.1f}拍")
    else:
        print(f"テストファイルが見つかりません: {test_path}")
        print("先に generate_sample_v5.py を実行してください。")
