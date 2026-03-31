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
   # Good
   def generate(self, num_chords: int = 16) -> None:
       pass

   # Bad
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
   # Good
   soprano_pitch = 72
   harmony_rules = HarmonyRules()

   # Bad
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
最終更新：2026-03-31
