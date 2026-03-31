# Bach Style Fugue Generator

バッハ様式のフーガを自動生成するPythonプログラム

## 特徴

* **95.9%の和声学規則遵守**（Walter Piston "Harmony" ベース）
* 声部導音テクニック統合（共通音保持・最短距離・順次進行優先）
* 完全なMIDI出力（標準ライブラリのみ使用）
* 包括的なテストスイート
* 動的計画法（ビタビアルゴリズム）による全体最適の声部配置探索

## 現在のテスト結果（重要）

* **97項目の規則チェック中93項目合格（95.9%）**
* **既知の不具合2箇所：**
  - 平行5度・8度の違反：2箇所（92%→100%への改善予定）
  - 第三音省略：2箇所（75%→100%への改善予定）

## クイックスタート

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

## ドキュメント

* [開発ガイド](DEVELOPMENT.md) - セットアップ・テスト実行方法
* [アーキテクチャ](ARCHITECTURE.md) - システム設計と実装の詳細
* [和声学統合](docs/HARMONY_INTEGRATION.md) - 古典和声学の実装解説
* [開発ロードマップ](ROADMAP.md) - v0.2.0 以降の計画

## プロジェクト構成

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

## 実装された和声学規則（全10章）

- 第1章: 音階と調性
- 第2章: 三和音と七の和音
- 第3章: 声部配置
- 第4章: 平行進行の禁則
- 第5章: 不協和音程
- 第6章: 和声進行
- 第7章: 導音と解決
- 第8章: 重複と省略
- 第9章: カデンツ
- 第10章: 非和声音

## 開発ロードマップ

### v0.1.0（現在）
- [x] 和声学規則完全実装
- [x] 声部導音テクニック統合
- [x] 基本的なフーガ生成
- [x] MIDI出力
- [x] テストスイート（95.9%合格）

### v0.2.0（目標）
- [ ] 不具合修正：平行5度・8度 → 0箇所
- [ ] 不具合修正：第三音省略 → 0箇所
- [ ] 規則遵守率：100%達成

### v0.3.0（計画中）
- [ ] リズムの多様化（8分音符、付点リズム）
- [ ] 主題の自動生成
- [ ] 16小節以上のフーガ生成

## 参考文献

* Walter Piston: "Harmony" (5th edition, 1987)
* Johann Joseph Fux: "Gradus ad Parnassum" (1725)
* Kent Kennan: "Counterpoint" (4th edition, 1999)

## ライセンス

MIT License

## コントリビューション

Pull Request、Issue報告を歓迎します。

## 作成者

Claude (Anthropic) + nobuhiko-ohki

---

**最終更新:** 2026-03-31
