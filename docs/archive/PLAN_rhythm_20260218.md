# 八分音符・十六分音符の導入設計

## 現状の制約

- Pitch: MIDIピッチのみ（音長情報なし）
- Subject.pitches: List[Pitch]（1要素 = 1拍 = 四分音符）
- ContrapuntalDP: 拍単位の状態空間 (beat, pitch)
- voice_melodies: List[Optional[int]]（拍インデックス = 位置）
- MIDI出力: 全音符が480 ticks固定

## 設計方針: サブビートグリッド + 2層アーキテクチャ

### 時間単位の変更

```
最小単位: サブビート（十六分音符 = 1サブビート）
四分音符 = 4サブビート
八分音符  = 2サブビート
十六分音符 = 1サブビート
1拍 = 480 ticks = 4サブビート → 1サブビート = 120 ticks
```

### 変更1: NoteEvent 導入（harmony_rules_complete.py）

```python
@dataclass
class NoteEvent:
    """音高＋音長"""
    pitch: Pitch
    duration: int  # サブビート単位（4=四分, 2=八分, 1=十六分）
```

Pitch クラスは変更なし。NoteEvent が Pitch を包む。

### 変更2: Subject の拡張（fugue_structure.py）

```python
@dataclass
class Subject:
    notes: List[NoteEvent]       # 旧 pitches: List[Pitch]
    key: Key
    name: str = "主題"

    @property
    def pitches(self) -> List[Pitch]:
        """後方互換: 音高リスト"""
        return [n.pitch for n in self.notes]

    def get_length_beats(self) -> int:
        """拍数（四分音符換算）"""
        return sum(n.duration for n in self.notes) // 4

    def get_length_subbeats(self) -> int:
        """サブビート数"""
        return sum(n.duration for n in self.notes)
```

既存の `get_length()` は `get_length_beats()` に改名。
`pitches` プロパティで後方互換を維持。

### 変更3: 内部表現のサブビート化（fugue_realization.py）

```python
# 旧: melodies[voice] = [Optional[int]] × total_beats
# 新: melodies[voice] = [Optional[int]] × total_subbeats
#     主題の配置時に duration に応じて複数サブビートを同じピッチで埋める
```

主題配置（Phase A）:
```python
for note in entry.subject.notes:
    for sb in range(note.duration):
        melodies[voice][abs_subbeat + sb] = note.pitch.midi
    abs_subbeat += note.duration
```

### 変更4: 2層DP

#### Layer 1: 拍頭の和声骨格（既存DPの拡張）

- 状態空間: (拍インデックス, ピッチ)  ← 変更なし
- 拍頭（サブビート 0, 4, 8, ...）のピッチを決定
- 対位法の硬制約・軟制約はこの層で適用
- 結果: 拍ごとに1つの和声音（骨格音）

#### Layer 2: 拍内のリズム装飾（新規）

拍頭の骨格音が決まった後、各拍の内部をリズムパターンで充填。

```python
class RhythmElaborator:
    """拍内のリズム装飾"""

    # リズムパターン辞書（音価リスト = サブビート配分）
    PATTERNS = {
        'Q':       [4],           # 四分音符 ♩
        'EE':      [2, 2],        # 八分×2 ♪♪
        'SSSS':    [1, 1, 1, 1],  # 十六分×4
        'ES':      [2, 1, 1],     # 八分＋十六分×2
        'SE':      [1, 1, 2],     # 十六分×2＋八分
        'DS':      [3, 1],        # 付点八分＋十六分
    }

    def elaborate(self, skeleton_pitch, next_pitch,
                  chord: ChordLabel, scale, pattern_name) -> List[NoteEvent]:
        """骨格音から拍内を装飾

        規則:
        - 拍頭は骨格音（和声音）
        - 拍内の追加音は経過音・刺繍音・補助音
        - 十六分音符は順次進行のみ
        - 八分音符は3度跳躍まで許容
        """
```

装飾音の種類:
- **経過音 (passing tone)**: 骨格音→次の骨格音を順次進行で接続
- **刺繍音 (neighbor tone)**: 骨格音→上/下隣接音→骨格音に戻る
- **補助音 (auxiliary)**: 和声音間を順次進行で埋める

パターン選択の方針:
- 主題のリズムから対照的なパターンを選ぶ（主題が四分なら対旋律は八分）
- 全声部が同時に細かくなることを避ける（拍点の明確さ維持）
- 3声区間では1声部のみ装飾、2声部は骨格維持を基本とする

### 変更5: 固定声部のサブビート対応

DPの fixed_voices をサブビート解像度に変更:

```python
# 旧: fixed_voices = {"alto": [60, 62, 64, ...]}  (拍単位)
# 新: fixed_voices = {"alto": [60,60,60,60, 62,62,62,62, ...]}  (サブビート単位)
#     八分音符ならサブビート2つが同じ値
```

ただし Layer 1 DP は引き続き拍頭のみを参照:
```python
# Layer 1 は拍頭（sb % 4 == 0）のみ比較
# Layer 2 の装飾音はサブビートレベルで協和性チェック
```

### 変更6: _to_midi_events のサブビート対応

```python
def _to_midi_events(self, melodies, ticks_per_subbeat=120):
    # 連続する同一ピッチをタイ（1つのノートに結合）
    for voice, melody in melodies.items():
        notes = []
        i = 0
        while i < len(melody):
            if melody[i] is not None:
                pitch = melody[i]
                start = i
                while i < len(melody) and melody[i] == pitch:
                    i += 1
                duration = (i - start) * ticks_per_subbeat
                notes.append((start * ticks_per_subbeat, pitch, duration))
            else:
                i += 1
```

### 変更7: Codetta, 応答生成の対応

- Codetta.pitches → Codetta.notes: List[NoteEvent]
- get_answer(): NoteEvent単位で移調（durationは保持）
- create_exposition(): start_position をサブビート単位に変更

## 実装順序

1. NoteEvent 導入 + Subject 拡張（後方互換プロパティ付き）
2. テスト更新（NoteEvent形式のSubject生成）
3. FugueRealizationEngine のサブビートグリッド化（Phase A）
4. _to_midi_events のタイ結合
5. Layer 1 DP は拍頭参照に限定（既存ロジック流用）
6. RhythmElaborator 実装（経過音・刺繍音）
7. Layer 2 → サブビートグリッドへの書き込み
8. 全テスト通過確認 + サンプル生成
