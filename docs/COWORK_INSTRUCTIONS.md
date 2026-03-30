# Cowork ドキュメント整理・更新指示書

## 📋 タスク概要

GitHubへの本格的な移行に向けて、ドキュメント類を**現在のPythonプログラムの実装状態に合わせて**更新・新規作成してください。

現在のプロジェクト：**バッハ様式フーガ自動生成システム**  
リポジトリ：`https://github.com/nobuhiko-ohki/fuge`

---

## 🎯 優先度別タスク

### 【高優先度】必須（これらは絶対実施）

#### **タスク1: README.md の更新**

**現状確認：** `README.md` は存在していますが、内容が現在の実装状態を完全に反映しているか確認し、以下の内容を追加・更新してください。

**更新内容：**

```markdown
# 🎼 Bach Style Fugue Generator

バッハ様式のフーガを自動生成するPythonプログラム

## ✨ 特徴

* **95.9%の和声学規則遵守**（Walter Piston "Harmony" ベース）
* 声部導音テクニック統合（共通音保持・最短距離・順次進行優先）
* 完全なMIDI出力（標準ライブラリのみ使用）
* 包括的なテストスイート
* 動的計画法（ビタビアルゴリズム）による全体最適の声部配置探索

## 📊 現在のテスト結果（重要）

* **97項目の規則チェック中93項目合格（95.9%）**
* **既知の不具合2箇所：**
  - ⚠️ 平行5度・8度の違反：2箇所（92%→100%への改善予定）
  - ⚠️ 第三音省略：2箇所（75%→100%への改善予定）

## 🚀 クイックスタート

### インストール

```bash
git clone https://github.com/nobuhiko-ohki/fuge.git
cd fuge
```

**依存関係なし** - Python 3.8以上のみ必要

### 基本的な使用方法

```python
from src.voice_leading_fugue_gen import VoiceLeadingGenerator

# フーガを生成
generator = VoiceLeadingGenerator(tonic_pc=0)  # C major
generator.generate(num_chords=16)
generator.export_midi("my_fugue.mid", tempo=80)
```

### テスト実行

```bash
# 和声学規則のテスト（全体スイート）
python -m pytest tests/test_generated_fugue.py -v

# 特定のテストのみ実行
python -m pytest tests/test_generated_fugue.py::TestHarmonyRules -v
```

## 📚 ドキュメント

* [開発ガイド](DEVELOPMENT.md) - セットアップ・テスト実行方法
* [アーキテクチャ](ARCHITECTURE.md) - システム設計と実装の詳細
* [和声学統合](docs/HARMONY_INTEGRATION.md) - 古典和声学の実装解説
* [開発ロードマップ](ROADMAP.md) - v0.2.0 以降の計画

## 🏗️ プロジェクト構成

```
fuge/
├── README.md                          # このファイル
├── DEVELOPMENT.md                     # 開発ガイド
├── ARCHITECTURE.md                    # 技術仕様書
├── ROADMAP.md                         # 開発計画
├── requirements.txt                   # 依存関係（なし）
├── setup_github.sh                    # GitHub初期設定スクリプト
│
├── src/                               # ソースコード
│   ├── harmony_rules_complete.py      # 古典和声学規則集（全10章）
│   ├── voice_leading_fugue_gen.py     # メイン生成エンジン（DP法）
│   ├── counterpoint_engine.py         # 対位法エンジン
│   ├── midi_writer.py                 # MIDI出力
│   ├── fugue_structure.py             # フーガ構造
│   └── harmony.py                     # 和声学モジュール
│
├── tests/                             # テストスイート
│   └── test_generated_fugue.py        # 自動テスト（95.9%合格）
│
├── examples/outputs/                  # サンプルMIDI
│   ├── voice_leading_fugue.mid        # 声部導音版
│   └── strict_harmony_fugue.mid       # 厳密和声版
│
└── docs/                              # ドキュメント
    ├── HARMONY_INTEGRATION.md         # 和声学統合の詳細
    └── GITHUB_MIGRATION_GUIDE.md      # GitHub移行ガイド
```

## 🎯 実装された和声学規則（全10章）

✅ 第1章: 音階と調性  
✅ 第2章: 三和音と七の和音  
✅ 第3章: 声部配置  
✅ 第4章: 平行進行の禁則  
✅ 第5章: 不協和音程  
✅ 第6章: 和声進行  
✅ 第7章: 導音と解決  
✅ 第8章: 重複と省略  
✅ 第9章: カデンツ  
✅ 第10章: 非和声音  

## 🔄 開発ロードマップ

### v0.1.0（現在）✅
- [x] 和声学規則完全実装
- [x] 声部導音テクニック統合
- [x] 基本的なフーガ生成
- [x] MIDI出力
- [x] テストスイート（95.9%合格）

### v0.2.0（目標）🎯
- [ ] 不具合修正：平行5度・8度 → 0箇所
- [ ] 不具合修正：第三音省略 → 0箇所
- [ ] 規則遵守率：100%達成

### v0.3.0（計画中）
- [ ] リズムの多様化（8分音符、付点リズム）
- [ ] 主題の自動生成
- [ ] 16小節以上のフーガ生成

## 📖 参考文献

* Walter Piston: "Harmony" (5th edition, 1987)
* Johann Joseph Fux: "Gradus ad Parnassum" (1725)
* Kent Kennan: "Counterpoint" (4th edition, 1999)

## 📄 ライセンス

MIT License

## 🤝 コントリビューション

Pull Request、Issue報告を歓迎します。

## 👤 作成者

Claude (Anthropic) + nobuhiko-ohki

---

**最終更新:** [現在の日付]
```

**実施内容：**
- ✅ 現在の実装状態の正確な記述
- ✅ テスト結果（95.9%）と既知不具合の明記
- ✅ クイックスタートの確認・更新
- ✅ ドキュメントリンクの整備
- ✅ ロードマップの明確化

---

#### **タスク2: DEVELOPMENT.md の新規作成**

**現状確認：** このファイルが存在するかどうか確認してください。存在しなければ新規作成、存在すれば以下の内容が含まれているか確認してください。

**作成内容：**

```markdown
# Development Guide

## 環境セットアップ

### 前提条件
- Python 3.8以上
- macOS / Windows / Linux
- Git

### インストール手順

```bash
# 1. リポジトリのクローン
git clone https://github.com/nobuhiko-ohki/fuge.git
cd fuge

# 2. 仮想環境の作成（推奨）
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# または
venv\Scripts\activate  # Windows

# 3. 依存関係のインストール
# このプロジェクトには外部依存がありません
# （Python標準ライブラリのみを使用）
```

## プロジェクト構成の理解

### ソースコード
| ファイル | 責務 |
|---------|------|
| `src/harmony_rules_complete.py` | 古典和声学規則の実装（全10章） |
| `src/voice_leading_fugue_gen.py` | メイン生成エンジン（DP法） |
| `src/counterpoint_engine.py` | 対位法規則の実装 |
| `src/midi_writer.py` | MIDI形式での出力 |
| `src/fugue_structure.py` | フーガ構造の定義 |
| `src/harmony.py` | 和声学ユーティリティ |

### テスト
| ファイル | 内容 |
|---------|------|
| `tests/test_generated_fugue.py` | 和声学規則のテストスイート（97項目） |

## テスト実行方法

### 全テストスイートを実行

```bash
python -m pytest tests/test_generated_fugue.py -v
```

**期待される結果：**
```
93項目合格 / 97項目
合格率: 95.9%
```

### 特定のテストクラスのみ実行

```bash
# 和声学規則のテスト
python -m pytest tests/test_generated_fugue.py::TestHarmonyRules -v

# 声部配置のテスト
python -m pytest tests/test_generated_fugue.py::TestVoiceConfiguration -v

# カデンツのテスト
python -m pytest tests/test_generated_fugue.py::TestCadences -v
```

### 特定のテスト関数のみ実行

```bash
python -m pytest tests/test_generated_fugue.py::TestHarmonyRules::test_parallel_fifths -v
```

## フーガの生成と出力

### 基本的な生成（16小節）

```bash
cd fuge
python -c "
from src.voice_leading_fugue_gen import VoiceLeadingGenerator

generator = VoiceLeadingGenerator(tonic_pc=0)  # ハ長調
generator.generate(num_chords=16)
generator.export_midi('my_fugue.mid', tempo=80)
"
```

### 異なるテンポで出力

```python
generator.export_midi('my_fugue_slow.mid', tempo=60)    # 遅い
generator.export_midi('my_fugue_fast.mid', tempo=120)   # 速い
```

### 異なる調で生成

```python
# ト長調（G major）
generator_g = VoiceLeadingGenerator(tonic_pc=7)  # Gは ピッチクラス7
generator_g.generate(num_chords=16)
generator_g.export_midi('fugue_g_major.mid', tempo=80)

# ヘ長調（F major）
generator_f = VoiceLeadingGenerator(tonic_pc=5)  # Fは ピッチクラス5
generator_f.generate(num_chords=16)
generator_f.export_midi('fugue_f_major.mid', tempo=80)
```

## ブランチ戦略

このプロジェクトでは以下のブランチ構成を推奨します：

```
main
├── 本番コード（常にリリース可能）
│
develop
├── 開発版
│
feature/*
├── feature/add-rhythm-diversity
├── feature/auto-subject-generation
├── feature/parallel-fifths-fix
└── feature/third-omission-fix

fix/*
├── fix/parallel-fifths-detection
└── fix/third-omission-prevention

docs/*
├── docs/api-reference
└── docs/architecture-diagram
```

### ブランチ作成例

```bash
# 機能追加（リズム多様化）
git checkout -b feature/add-rhythm-diversity

# バグ修正（平行5度の検出漏れ）
git checkout -b fix/parallel-fifths-detection

# ドキュメント更新
git checkout -b docs/update-readme
```

## 不具合修正の手順

### 現在の既知不具合

1. **平行5度・8度の違反（2箇所）**
   - ファイル：`src/voice_leading_fugue_gen.py` の `_check_transition()` メソッド
   - 原因：隠伏5度の判定ロジック
   - 目標：v0.2.0で完全解消

2. **第三音省略（2箇所）**
   - ファイル：`src/voice_leading_fugue_gen.py` の `_enumerate_valid_voicings()` メソッド
   - 原因：第三音の重複チェック
   - 目標：v0.2.0で完全解消

### 修正時のワークフロー

```bash
# 1. 不具合修正用のブランチを作成
git checkout -b fix/parallel-fifths-detection

# 2. テストを失敗させる（TDD）
# test_generated_fugue.py に新しいテストケースを追加

# 3. コードを修正
# src/voice_leading_fugue_gen.py を編集

# 4. テストが通るか確認
python -m pytest tests/test_generated_fugue.py -v

# 5. すべてのテストが通ることを確認
python -m pytest tests/test_generated_fugue.py -v

# 6. コミット
git add src/voice_leading_fugue_gen.py tests/test_generated_fugue.py
git commit -m "Fix: parallel fifths detection in voice leading (issue #X)"

# 7. プッシュして Pull Request を作成
git push origin fix/parallel-fifths-detection
```

## コーディング規約

### スタイルガイド

このプロジェクトでは以下の規約に従ってください：

1. **型ヒント（Type Hints）の使用**
   ```python
   # ✅ Good
   def generate(self, num_chords: int = 16) -> None:
       pass
   
   # ❌ Bad
   def generate(self, num_chords):
       pass
   ```

2. **関数のドキュメント**
   ```python
   def _check_transition(self, prev: Voicing, curr: Voicing) -> bool:
       """遷移制約を満たすか判定
       
       和声学規則（harmony_rules_complete）:
       - 平行5度・8度の禁止
       - 増音程の旋律的使用禁止
       
       Args:
           prev: 前の和音の配置（S, A, T, B）のMIDI値タプル
           curr: 現在の和音の配置
       
       Returns:
           True: 遷移が規則に従っている
           False: 違反している
       """
   ```

3. **変数名の命名**
   ```python
   # ✅ Good
   soprano_pitch = 72
   harmony_rules = HarmonyRules()
   
   # ❌ Bad
   s = 72
   hr = HarmonyRules()
   ```

## トラブルシューティング

### テストが失敗する場合

```bash
# 1. Python バージョン確認
python --version  # 3.8以上必須

# 2. モジュールのインポート確認
python -c "from src.voice_leading_fugue_gen import VoiceLeadingGenerator"

# 3. テストの詳細出力
python -m pytest tests/test_generated_fugue.py -vv

# 4. 特定のテストで止まる場合
python -m pytest tests/test_generated_fugue.py::TestHarmonyRules::test_parallel_fifths -vv
```

### MIDIファイルが出力されない場合

```bash
# 1. examples/outputs ディレクトリの存在確認
ls -la examples/outputs/

# 2. ディレクトリなければ作成
mkdir -p examples/outputs

# 3. 再度出力試行
python -c "
from src.voice_leading_fugue_gen import VoiceLeadingGenerator
generator = VoiceLeadingGenerator(tonic_pc=0)
generator.generate(num_chords=16)
generator.export_midi('examples/outputs/test.mid', tempo=80)
"
```

## リソース

### 内部ドキュメント
- [README.md](README.md) - プロジェクト概要
- [ARCHITECTURE.md](ARCHITECTURE.md) - 技術仕様書
- [ROADMAP.md](ROADMAP.md) - 開発計画
- [docs/HARMONY_INTEGRATION.md](docs/HARMONY_INTEGRATION.md) - 和声学実装の詳細

### 外部リソース
- [Pytest Documentation](https://docs.pytest.org/)
- [Python Type Hints](https://docs.python.org/3/library/typing.html)

## お役立ちコマンド集

```bash
# リポジトリの状態確認
git status
git log --oneline -10

# ブランチの一覧表示
git branch -a

# 変更の詳細確認
git diff

# 最後のコミット内容確認
git show HEAD

# テスト実行（詳細）
python -m pytest tests/ -vv

# テスト実行（カバレッジ計測）
python -m pytest tests/ --cov=src
```

---

**このドキュメントは随時更新されます。**  
最終更新：[現在の日付]
```

**実施内容：**
- ✅ 環境セットアップ手順の詳細化
- ✅ テスト実行方法の具体化
- ✅ ブランチ戦略の明確化
- ✅ 不具合修正ワークフローの提示
- ✅ トラブルシューティングガイド

---

#### **タスク3: ARCHITECTURE.md の新規作成または更新**

**現状確認：** このファイルが存在するかどうか確認してください。存在しなければ新規作成してください。

**作成内容：**

```markdown
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
3. S-A ≤ 12, A-T ≤ 12（声部間隔）
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

**計算量：** O(n × m1 × m2)
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
DP テーブル：O(n × m)
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
最終更新：[現在の日付]
```

**実施内容：**
- ✅ システム全体のアーキテクチャを図解
- ✅ 主要クラスの責務を明確化
- ✅ アルゴリズムを詳細に説明
- ✅ パフォーマンス特性を記載
- ✅ 既知の制限と改善点を明記

---

### 【中優先度】重要だが後回し可

#### **タスク4: ROADMAP.md の新規作成**

**作成内容：**

```markdown
# Development Roadmap

## プロジェクトの進行状況

このドキュメントは、Bach Style Fugue Generator の開発ロードマップを示します。

## v0.1.0（現在の版）✅ 完了

### 実装完了項目

- [x] 古典和声学規則全10章の実装
  - Walter Piston "Harmony" をベース
  - 97項目の規則チェック
  
- [x] 声部導音テクニック統合
  - 共通音保持
  - 反行
  - 最短距離の原則
  - 順次進行優先
  
- [x] 動的計画法（ビタビアルゴリズム）による全体最適探索
  
- [x] MIDI出力（標準ライブラリのみ）

- [x] 包括的なテストスイート（95.9%合格）

- [x] ドキュメント整備

### 成果

- **テスト結果：93/97 項目合格（95.9%）**
- **生成フーガの品質：上々**
- **実行速度：高速（16小節 1-2秒）**

---

## v0.2.0（次期版）🎯 目標：100%規則遵守

### 目標

完全な古典和声学規則の遵守を実現し、テスト合格率を95.9%から100%へ向上。

### 実装予定項目

#### 1. 平行5度・8度の完全解消

**現状：** 2箇所の違反を検出（92%）

**課題：**
- 隠伏5度（外声部）の判定ロジックに漏れ
- テストケース2つが失敗

**実装計画：**
```
Week 1: テストケース分析と原因調査
  ├─ 違反が発生する具体的な和声進行を特定
  ├─ なぜ判定ロジックが漏らすのか分析
  └─ 修正方針を決定

Week 2: 判定ロジックの修正
  ├─ _check_transition() メソッドの改善
  ├─ テストの再実行
  └─ 完全合格を確認

GitHub Issue：#1（優先度高）
対応ブランチ：`fix/parallel-fifths-detection`
```

#### 2. 第三音省略の完全防止

**現状：** 2箇所で第三音が省略（75%）

**課題：**
- 有効配置列挙時の和音構成音チェックが不十分
- 通常は第三音が最上声となるべき場面で省略

**実装計画：**
```
Week 1: 原因分析
  ├─ どの和音進行で省略が発生するか特定
  ├─ _enumerate_valid_voicings() の制約確認
  └─ 修正方針を決定

Week 2: 制約の強化
  ├─ 省略禁止規則を明示的に追加
  ├─ テスト再実行
  └─ 合格を確認

GitHub Issue：#2（優先度高）
対応ブランチ：`fix/third-omission-prevention`
```

### タイムライン

- **Week 1-2（3月末）** ：不具合原因分析
- **Week 3-4（4月中旬）** ：修正実装・テスト
- **Week 5（4月下旬）** ：リリース準備

### テスト

```bash
# 全テストがPASSする状態を目指す
python -m pytest tests/test_generated_fugue.py -v
# Expected: 97/97 ✓ PASS
```

---

## v0.3.0（機能拡張版）💡 計画中

### リズムの多様化

**目標：** 4分音符のみから、8分音符・付点リズムへの対応

**実装内容：**
- 各和音の音価（duration）を可変化
- バッハ様式のリズムパターン学習
- MIDIでの正確な時間制御

**想定コスト：** 中程度（2-3週間）

### 主題の自動生成

**目標：** バッハ様式の主題メロディの自動作成

**実装内容：**
- 主題の特性抽出（区間、モチーフ等）
- 確率的主題生成（Markov連鎖等）
- 対主題・副主題の自動構成

**想定コスト：** 高い（4-6週間）

### より長いフーガ生成

**目標：** 16小節以上、複雑な構造のフーガ

**実装内容：**
- エピソード間のスムーズな遷移
- テーマの再登場タイミング管理
- 32小節以上のフーガ生成

**想定コスト：** 中程度（2-3週間）

### タイムライン

- **5月-6月** ：リズム多様化
- **7月-8月** ：主題自動生成
- **9月** ：統合・テスト

---

## v1.0.0（完全版）🚀 将来計画

### 完全なフーガ構造

提示部 → 展開部 → ストレット → コーダ の実装

### 副属和音と転調

远い調への転調、機能和声の高度な活用

### 複数声部（多声フーガ）

4声以上のフーガ生成

### Web インターフェース

ブラウザで簡単にフーガを生成・試聴・カスタマイズ

### 想定時期

2026年末～2027年

---

## マイルストーン サマリー

| バージョン | 目標期限 | 主要目標 | 状態 |
|-----------|--------|--------|-----|
| v0.1.0 | 2026年3月 | 95.9%の規則遵守 | ✅ 完了 |
| v0.2.0 | 2026年4月末 | 100%の規則遵守 | 🎯 進行中 |
| v0.3.0 | 2026年9月末 | 機能拡張（リズム・主題） | 💡 計画中 |
| v1.0.0 | 2026年末 | 完全版リリース | 🚀 将来 |

---

## フィードバックと改善提案

このロードマップについてのご意見・改善提案は、GitHub Issues でお寄せください。

**Issue テンプレート：**
```
Title: [ROADMAP] ...

Body:
- 改善対象バージョン
- 改善内容
- 理由
```

---

**最終更新：** [現在の日付]
```

**実施内容：**
- ✅ 現在のv0.1.0の完了状況を記載
- ✅ v0.2.0（100%達成）の詳細計画
- ✅ v0.3.0以降のビジョン
- ✅ 具体的なタイムラインの提示

---

#### **タスク5: 古いドキュメントの整理**

**実施内容：**

以下の作業を行ってください：

1. **古いドキュメントを確認**
   - docs/ フォルダ内のすべてのファイルを確認
   - GITHUB_MIGRATION_GUIDE.md などが古くなっていないか確認

2. **古いファイルの処理**
   - 古いファイル（1年以上更新がない等）は、以下いずれかで対応：
     
     **方法A：** archiveフォルダに移動
     ```bash
     mkdir -p docs/archive
     mv docs/old_file.md docs/archive/old_file_[日付].md
     ```
     
     **方法B：** ファイル名に「[DEPRECATED]」とマーク
     ```bash
     mv docs/old_api.md docs/[DEPRECATED]_old_api.md
     ```

3. **ドキュメント一覧を更新**
   - README.md の「ドキュメント」セクションを最新化
   - 新規作成したファイル（DEVELOPMENT.md、ARCHITECTURE.md等）をリンク

---

## 📋 実施チェックリスト

以下の順序で実施してください。各タスク完了後に✅をつけてください。

### 高優先度（必須）

- [ ] **タスク1：README.md を更新**
  - [ ] テスト結果（95.9%）を明記
  - [ ] 既知不具合2箇所を記載
  - [ ] ロードマップリンクを追加
  - [ ] クイックスタートが最新

- [ ] **タスク2：DEVELOPMENT.md を作成**
  - [ ] 環境セットアップ手順
  - [ ] テスト実行方法
  - [ ] ブランチ戦略
  - [ ] 不具合修正ワークフロー
  - [ ] トラブルシューティング

- [ ] **タスク3：ARCHITECTURE.md を作成**
  - [ ] システムアーキテクチャ図
  - [ ] 主要クラスの説明
  - [ ] アルゴリズム詳細
  - [ ] 制御フロー
  - [ ] パフォーマンス特性

### 中優先度（重要）

- [ ] **タスク4：ROADMAP.md を作成**
  - [ ] v0.1.0 の完了状況
  - [ ] v0.2.0 の詳細計画
  - [ ] v0.3.0 以降のビジョン
  - [ ] タイムラインの提示

- [ ] **タスク5：古いドキュメント整理**
  - [ ] 古いファイルを確認
  - [ ] archiveフォルダへ移動 OR [DEPRECATED]マーク
  - [ ] README のリンクを更新

---

## 🎯 最終確認事項

すべてのタスク完了後に、以下を確認してください：

1. **README.md が最新か確認**
   - [ ] プロジェクト概要が正確
   - [ ] テスト結果が正確（95.9%）
   - [ ] ドキュメントリンクが有効

2. **全ドキュメントのリンクが機能しているか確認**
   ```bash
   # README.md の全リンク確認
   - [開発ガイド](DEVELOPMENT.md) → ✓ ファイル存在
   - [アーキテクチャ](ARCHITECTURE.md) → ✓ ファイル存在
   - [ロードマップ](ROADMAP.md) → ✓ ファイル存在
   ```

3. **ドキュメント間の矛盾がないか確認**
   - README と DEVELOPMENT の情報一貫性
   - ROADMAP の実装予定が明確か

4. **ファイル構成を確認**
   ```bash
   fuge/
   ├── README.md ✓
   ├── DEVELOPMENT.md ✓
   ├── ARCHITECTURE.md ✓
   ├── ROADMAP.md ✓
   ├── src/
   ├── tests/
   ├── docs/
   │   ├── HARMONY_INTEGRATION.md
   │   └── archive/ (古いファイル)
   └── examples/
   ```

---

## 📝 報告事項

タスク完了後、このChat内で以下を報告してください：

1. **完了した作業一覧**
   ```markdown
   - [x] README.md 更新完了
   - [x] DEVELOPMENT.md 作成完了
   - [x] ARCHITECTURE.md 作成完了
   - [x] ROADMAP.md 作成完了
   - [x] 古いドキュメント整理完了
   ```

2. **新規作成したドキュメント**
   - ファイル名、行数、主要内容

3. **困った点や質問事項**（あれば）

---

## 💡 ヒント・参考情報

### ドキュメント作成時のコツ

1. **見出しレベルを適切に**
   - `# ` - ファイルタイトル（1つだけ）
   - `## ` - 大セクション
   - `### ` - 中セクション
   - `#### ` - 小セクション

2. **コード例を含める**
   - bash コマンド
   - Python コード
   - ディレクトリ構造

3. **図表を活用**
   ```
   ┌─────────────┐
   │   モジュール A   │
   └─────────────┘
   ```

4. **リンク・参照を活用**
   - 内部リンク：`[DEVELOPMENT.md](DEVELOPMENT.md)`
   - 外部リンク：`[Python Docs](https://docs.python.org)`

### 検証方法

ドキュメント完成後、以下で検証してください：

```bash
# Markdown の構文確認（pandoc インストール必須）
pandoc README.md -t plain > /dev/null && echo "✓ OK"

# リンク確認（zsh 環境）
grep -o '\[.*\](.*\.md)' README.md | while read -r link; do
  file=$(echo $link | sed 's/.*(\(.*\.md\)).*/\1/')
  [ -f "$file" ] && echo "✓ $file" || echo "✗ $file NOT FOUND"
done
```

---

## ✅ 完了時の次のステップ

ドキュメント整理が完了したら、このChat内で以下を実施します：

1. **仕様検討フェーズ**（Chat内）
   - 現在の不具合の詳細分析
   - テスト戦略の共同設計
   - v0.2.0 実装計画の詳細化

2. **Code への移行**
   - ローカルリポジトリで Codeを開く
   - TDD による不具合修正開始

3. **GitHub へのプッシュ**
   - 最新ドキュメント付きでプッシュ
   - 本格的な開発開始

---

**このタスクをCoworkで実行してください。すべて完了したら、このChatで「完了しました」とお知らせください！**

