# 古典和声学の統合 - 技術解説

## 🎼 追加された和声学機能

### 1. 和音システム（Chord）

バッハ様式で使用される主要な和音を実装：

**三和音：**
- 長三和音（Major）: C-E-G（ド・ミ・ソ）
- 短三和音（Minor）: C-Eb-G（ド・ミ♭・ソ）
- 減三和音（Diminished）: C-Eb-Gb（ド・ミ♭・ソ♭）
- 増三和音（Augmented）: C-E-G#（ド・ミ・ソ♯）

**七の和音：**
- 属七の和音（V7）: G-B-D-F（最重要！）
- 短七の和音（m7）
- 長七の和音（M7）
- 減七の和音（dim7）
- 半減七の和音（m7♭5）

### 2. 機能和声（Function Harmony）

バッハの和声は機能和声理論に基づいています：

```
主和音（Tonic, T）      : I, vi     - 安定
下属和音（Subdominant, S）: IV, ii    - 準備
属和音（Dominant, D）    : V, vii°   - 緊張
```

**重要な和声進行：**
```
T → S → D → T  （最強の進行）

具体例（ハ長調）：
I → IV → V7 → I
C → F → G7 → C
```

**禁則進行：**
```
D → S  （属和音から下属和音への進行は避ける）
V → IV （×）
```

### 3. カデンツ（Cadence）- 終止形

フーガの区切りや終結部で使用される重要な要素：

**完全正格終止（Perfect Authentic Cadence）：**
```
V7 → I （両方とも基本形、ソプラノは主音で終わる）
バッハのフーガで最も頻繁に使用される終止
```

**不完全正格終止（Imperfect Authentic Cadence）：**
```
V7 → I （転回形を含む、またはソプラノが主音以外で終わる）
```

**変格終止（Plagal Cadence）：**
```
IV → I （「アーメン終止」）
```

**半終止（Half Cadence）：**
```
I → V （属和音で終わり、継続感を与える）
エピソードの終わりなどで使用
```

**偽終止（Deceptive Cadence）：**
```
V → vi （期待を裏切って短調の平行調へ）
意外性を生む
```

### 4. 和声分析（Harmonic Analysis）

垂直方向（同時に鳴っている音）の分析：

```python
# 例：C-E-G が同時に鳴っている
pitches = [60, 64, 67]  # C4, E4, G4
analyzer = HarmonicAnalyzer(key)
chord = analyzer.analyze_vertical_sonority(pitches)
# → ハ長調のI和音（主和音）と識別
```

**非和声音（Non-Harmonic Tones）の処理：**
- 経過音（Passing Tone）
- 刺繍音（Neighbor Tone）
- 掛留音（Suspension）
- 倚音（Appoggiatura）
- 先取音（Anticipation）

### 5. 和声的対主題の生成

従来の対位法的対主題に加えて、和声構造を考慮：

```python
def generate_harmonic_countersubject():
    # 1. 現在の拍の和音を取得
    chord = get_chord_at_beat(current_beat)
    
    # 2. 和音構成音を優先
    if pitch_class in chord_tones:
        score += 10  # 高スコア
    
    # 3. 対位法規則も考慮
    - 主題が跳躍 → 対主題は順次進行
    - 主題が順次 → 対主題は反行
    
    # 4. 最適な音を選択
```

## 📊 実装の違い

### 従来版（対位法のみ）
```
主題：C-D-E-F-G
対主題：G-F-E-D-C （単純な反行）

問題点：
✗ 和声的な響きが考慮されていない
✗ 不協和音が偶然発生する可能性
✗ バッハらしい和声進行がない
```

### 和声統合版
```
和声計画：I → IV → V7 → I

主題：C-D-E-F-G（I和音上）
対主題：E-F-G-A-G（和音構成音を優先）

改善点：
✓ 和声進行が計画的
✓ 協和音が保証される
✓ バッハらしい機能和声
```

## 🎵 バッハ様式の和声的特徴

### 1. 属七の和音（V7）の重要性

バッハのフーガで最も重要な和音：

```
ハ長調の例：
V7 = G-B-D-F

機能：
- 強い緊張感を生む
- 主和音（I）への解決を要求
- 完全正格終止で必須
```

### 2. 和声リズム（Harmonic Rhythm）

和音の変わる速さ：

```
バッハの典型的なパターン：
- 提示部：ゆっくり（2-4拍ごと）
- エピソード：速く（1拍ごと、または拍の中間でも変化）
- ストレット：中程度
- 終結：遅く（最後のV-Iは長め）
```

### 3. 転調（Modulation）

フーガでは以下の調への転調が一般的：

```
主調がC majorの場合：
- 属調（G major）：提示部の応答で使用
- 下属調（F major）：中間部で使用
- 平行短調（A minor）：対比のため
```

### 4. 声部導音（Voice Leading）

和声進行における各声部の動き：

```
良い声部導音の原則：
✓ 共通音は保持する
✓ 他の音は最短距離で動く
✓ 導音（B in C major）は上行して主音へ

例：C major → G major
C (do) → B (ti)  ← 半音進行
E (mi) → D (re)  ← 全音下降
G (sol) → G (sol) ← 共通音保持
```

## 🔬 和声分析の例

### バッハ「平均律第1巻 フーガ第1番」（ハ長調）

```
小節1-2（提示部）：
拍1-2: I和音（C-E-G）- 主題開始
拍3-4: V和音（G-B-D）- 経過
拍5-6: I和音（C-E-G）- 主題終了

小節3-4（応答）：
拍1-2: V和音（G-B-D）- 応答開始（属調）
拍3-4: I和音（C-E-G）- 主調に戻る準備
```

### 終結部の典型的な和声進行

```
V7 → I の完全正格終止：

声部配置の例（4声）：
ソプラノ：F → E （導音が主音へ解決）
アルト：  D → C （不協和音が協和音へ）
テノール：B → C （同上）
バス：   G → C （根音の進行）

全体として：
G7 (G-B-D-F) → C (C-E-G-C)
```

## 💡 実装上の工夫

### 1. 和声計画の事前生成

```python
def plan_harmonic_structure(num_beats):
    # フーガ全体の和声進行を事前に設計
    # これにより、対位法の中でも和声的整合性を保つ
    
    harmonic_plan = [
        (0, I),    # 開始
        (4, IV),   # 下属和音
        (8, V7),   # 属七
        (12, I),   # 主和音
        ...
    ]
```

### 2. 和声と対位法の統合

```python
# 対位法的に良い動き + 和声的に適切な音 = 最適な対旋律

score = counterpoint_score + harmony_score

if in_chord_tones:
    harmony_score += 10
if good_voice_leading:
    counterpoint_score += 5
```

### 3. 適応的な和音選択

```python
# エピソードでは和声進行を加速
# ストレットでは和声を安定化
# 終結では典型的なカデンツを使用
```

## 📚 参考文献と理論的背景

### 古典和声学の基本文献
1. **Jean-Philippe Rameau: "Traité de l'harmonie"** (1722)
   - 機能和声理論の創始者
   
2. **Heinrich Schenker: "Harmony"** (1906)
   - シェンカー分析の基礎
   
3. **Walter Piston: "Harmony"** (1941)
   - 現代の和声学教科書の標準

### バッハの和声実践
- 平均律クラヴィーア曲集での和声進行の分析
- フーガにおける和声リズムの研究
- バロック時代の機能和声の発展

## 🎹 使用方法

### 和声統合版フーガの生成

```python
from harmonic_fugue_generator import HarmonicFugueGenerator
from harmony import Key
from counterpoint_engine import Pitch
from fugue_structure import Subject

# 主題を作成
subject_pitches = [
    Pitch(60), Pitch(62), Pitch(64), Pitch(65), Pitch(67)
]

# 調性を設定
key = Key.from_name("C", "major")

# 古いKeyオブジェクトも必要（互換性のため）
from fugue_structure import Key as OldKey
old_key = OldKey("C", "major")
subject = Subject(subject_pitches, old_key, "主題")

# 和声統合フーガ生成
generator = HarmonicFugueGenerator(
    num_voices=3,
    main_key=key,
    subject=subject
)

# 生成
generator.generate_complete_fugue()

# MIDI出力
generator.export_to_midi("my_harmonic_fugue.mid", tempo=90)
```

## 🔍 生成されたフーガの確認ポイント

MIDIファイルを再生する際、以下を確認してください：

1. **和声進行の滑らかさ**
   - I → IV → V → I の流れが聞こえるか
   
2. **終止の明確さ**
   - V7 → I で終わっているか
   - 終結感があるか
   
3. **対位法と和声の調和**
   - 各声部が独立して動いているか（対位法）
   - 全体として和声的にまとまっているか（和声学）

## 🚀 今後の改善点

### 実装予定の高度な機能

1. **転調の自動化**
   - エピソードでの自然な転調
   - 遠隔調への移行
   
2. **より複雑な和声進行**
   - 副属和音（Secondary Dominants）
   - ナポリの六の和音
   - 増六の和音
   
3. **和声リズムの精緻化**
   - セクションごとの適応的な変化
   - 緊張と弛緩のバランス

4. **非和声音の体系的扱い**
   - 経過音・刺繍音の意図的な配置
   - 掛留音による表現力の向上

---

**これで、バッハ様式のフーガ生成システムは、対位法と和声学の両方を統合した、より完全なシステムになりました！** 🎵
