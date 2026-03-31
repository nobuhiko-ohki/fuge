# Architecture Guide

## システム概要

バッハ様式フーガ自動生成システムは、**古典和声学規則**と**対位法規則**を統合し、
**動的計画法（ビタビアルゴリズム）**により全体最適の声部配置を探索するシステムです。

```
┌─────────────────────────────────────────────────────┐
│  VoiceLeadingGenerator（メイン生成エンジン）         │
│  ├─ 和声進行計画（和音系列の決定）                  │
│  ├─ DP探索（全体最適な声部配置）                    │
│  └─ MIDI出力（標準ライブラリ）                      │
└─────────────────────────────────────────────────────┘
        ↑                       ↑
        │                       │
  HarmonyRules            CounterpointEngine
  (和声学規則)             (対位法規則)
  ├─ 音階・調性            ├─ 隠伏5度・8度禁止
  ├─ 和音体系              ├─ 7度跳躍禁止
  ├─ 和声進行              ├─ 声部交差禁止
  └─ カデンツ              └─ 声部独立性スコア
```

## 主要クラスと責務

### VoiceLeadingGenerator（声部導音テクニック統合フーガ生成）

**ファイル：** `src/voice_leading_fugue_gen.py`

**責務：**
1. 和声進行の計画（I-IV-V-I等の和音系列決定）
2. 各和音の全有効配置を列挙（静的制約）
3. DP（動的計画法）による全体最適探索
4. 声部に結果を書き込み
5. MIDI形式で出力

**主要メソッド：**

| メソッド | 説明 |
|---------|------|
| `__init__(tonic_pc)` | 初期化（調の設定） |
| `plan_progression(num_chords)` | 和声進行を計画 |
| `_enumerate_valid_voicings(prog)` | 有効配置を列挙 |
| `_check_transition(prev, curr)` | 遷移制約をチェック |
| `_score_initial(v, prog)` | 初期配置のスコア計算 |
| `_score_transition(prev, curr, ...)` | 遷移コストの計算 |
| `generate(num_chords)` | DP法で生成 |
| `export_midi(filename, tempo)` | MIDI出力 |

### HarmonyRules（古典和声学規則集）

**ファイル：** `src/harmony_rules_complete.py`

**責務：**
1. 音階の生成
2. 和音の構築（三和音、七の和音）
3. 和声進行の妥当性判定
4. カデンツの判定

**実装済み規則：** 全10章（Walter Piston "Harmony"）

### CounterpointEngine（対位法エンジン）

**ファイル：** `src/counterpoint_engine.py`

**責務：**
1. 隠伏5度・8度の判定
2. 7度跳躍の禁止判定
3. 声部超越の判定
4. 声部独立性のスコアリング
5. 動きの種類（反行・斜行・平行）のスコアリング

### MIDIWriter（MIDI出力）

**ファイル：** `src/midi_writer.py`

**責務：**
1. MIDI トラックの構築
2. ノートイベントの生成
3. MIDIファイルの書き込み

**使用モジュール：** Python標準ライブラリ `midiutil` (内部実装)

## アルゴリズム詳細

### 1. 和声進行計画（Harmonic Planning）

```python
# 例：16小節のフーガ
Plan = [I, VI, IV, II, V, VI, III, VI, II, V, I, IV, VII, III, V, I]

これは以下の機能和声に対応：
[T, Tp, S, Sp, D, Tp, Dp, Tp, Sp, D, T, S, D代理, Dp, D, T]
```

**関数：** `plan_progression(num_chords)`

### 2. 有効配置の列挙（Enumeration of Valid Voicings）

各和音に対して、静的制約を満たす全配置を列挙：

**制約：**
1. 各声部が音域内
2. S > A > T > B（声部交差なし）
3. S-A <= 12, A-T <= 12（声部間隔）
4. 第三音が存在し、重複しない
5. 根音が存在する

**関数：** `_enumerate_valid_voicings(prog)`

**計算量：** O(配置数) = 通常数十〜数百個

### 3. DP探索（Viterbi Algorithm）

```
前進パス（Forward Pass）：
─────────────────────────────────────────
時刻 i=0        i=1             i=n-1
   配置v00    配置v10,...    配置vn0,...
   配置v01    配置v11,...    配置vn1,...
   ...        配置v1m,...    配置vnm,...
   配置v0k    ...

DP[i][j] = 和音0からiまでの最小累積コスト（和音i で配置j を選択）

逆追跡（Backtracking）：
最終和音で最小コストの配置を選択し、逆方向にたどる
→ 最適経路を復元
```

**関数：** `generate(num_chords)`

**計算量：** O(n * m1 * m2)
- n: 和音数
- m1, m2: 各時刻の配置数

### 4. スコアリング（Scoring）

#### 初期配置スコア

```python
score = 0
# 音域中央への引力
for midi_val, voice in zip(v, voices):
    mid = (range_min + range_max) / 2
    score += abs(midi_val - mid) * 0.3

# 密集配置の優先
score += (soprano - bass) * 0.1
```

#### 遷移スコア（コスト）

```python
score = 0

# 1. 各声部の移動コスト（低いほど良い）
if interval == 0:      score += 0    # 保持
elif interval <= 2:    score += 1    # 順次進行
elif interval <= 4:    score += 3    # 3度
elif interval <= 7:    score += 6    # 4-5度
else:                  score += 12   # 大跳躍

# 2. 上声部跳躍ペナルティ
if leap > 4:
    score += leap * 1.5

# 3. 共通音保持ボーナス
if common_tone_held:
    score -= 3

# 4. 反行ボーナス
if soprano_bass_contrary:
    score -= 2

# 5-7. その他の加算...
```

**関数：** `_score_transition(prev, curr, prev_prog, curr_prog)`

## 制御フロー

```
main()
│
├─ VoiceLeadingGenerator.__init__(tonic_pc=0)
│  ├─ HarmonyRules() を初期化
│  ├─ CounterpointEngine() を初期化
│  └─ 声部音域を設定
│
├─ generator.generate(num_chords=16)
│  │
│  ├─ plan_progression(16)
│  │  ├─ I-VI-IV-II-V-... の和音系列を決定
│  │  └─ ChordProgression オブジェクト16個を生成
│  │
│  ├─ _enumerate_valid_voicings() for each chord
│  │  ├─ 各ピッチクラスの音域内MIDI値を列挙
│  │  ├─ S > A > T > B の制約をチェック
│  │  ├─ 声部間隔を確認
│  │  └─ 和音構成音の要件を満たすか確認
│  │
│  ├─ DP前進パス
│  │  ├─ i=0: 初期和音のスコア計算
│  │  ├─ i=1..15: 遷移制約・コスト計算で最小経路を追跡
│  │  └─ dp_cost[], dp_prev[] に結果を格納
│  │
│  ├─ 逆追跡（バックトラック）
│  │  └─ 最適経路を復元
│  │
│  └─ 声部データに書き込み
│
└─ generator.export_midi("out.mid", tempo=80)
   ├─ MIDIWriter を初期化
   ├─ 各声部のノートを登録
   └─ MIDIファイルを書き込み
```

## パフォーマンス特性

### 実行時間の目安

| num_chords | 有効配置数/時刻 | 遷移評価数 | 実行時間 |
|-----------|-----------------|----------|--------|
| 8 | 50-100 | 5,000-10,000 | < 1秒 |
| 16 | 50-100 | 10,000-20,000 | 1-2秒 |
| 32 | 50-100 | 20,000-40,000 | 2-4秒 |

### メモリ使用量

```
DP テーブル：O(n * m)
- n=16 時刻
- m≈100 配置/時刻
→ ≈1,600 エントリ
→ ≈数MB
```

## 既知の制限と改善点

### 現在の制限

1. **平行5度・8度の検出が不完全**
   - 隠伏5度の判定ロジックに2箇所の漏れ
   - v0.2.0で修正予定

2. **第三音省略の禁止が不完全**
   - 2箇所で第三音が省略されている
   - v0.2.0で修正予定

3. **リズムが4分音符のみ**
   - 8分音符、付点リズム未対応
   - v0.3.0で実装予定

### 今後の改善

1. **転調対応**
   - 現在：同一調のみ
   - 改善：V 調への転調、平行短調への転調

2. **主題自動生成**
   - 現在：和音系列のみ生成
   - 改善：バッハ様式の主題メロディを自動作成

3. **完全フーガ構造**
   - 現在：基本的な連続進行
   - 改善：提示部→展開部→ストレット→コーダ

## テスト構成

### test_generated_fugue.py

```python
TestHarmonyRules          # 和声学規則テスト
├─ test_parallel_fifths   # 平行5度
├─ test_parallel_octaves  # 平行8度
├─ test_voice_ranges      # 声部音域
└─ ...                     # 他34項目

TestVoiceConfiguration    # 声部配置テスト
├─ test_no_crossing       # 声部交差なし
├─ test_spacing           # 声部間隔
└─ ...

TestCadences              # カデンツテスト
├─ test_authentic_cadence
└─ ...

総計：97項目
合格：93項目（95.9%）
失敗：4項目（4.1%）- 既知の不具合
```

## 参考文献

- **Walter Piston: "Harmony"** (5th ed., 1987)
  - 実装の理論的基礎

- **Johann Joseph Fux: "Gradus ad Parnassum"** (1725)
  - 対位法の古典

- **Kent Kennan: "Counterpoint"** (4th ed., 1999)
  - 近代的な対位法理論

---

**このドキュメントは随時更新されます。**
最終更新：2026-03-31
