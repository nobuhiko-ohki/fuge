#!/bin/bash
# GitHub移行セットアップスクリプト
# Bach Fugue Generator Project

set -e

echo "======================================================================"
echo "Bach Fugue Generator - GitHub移行セットアップ"
echo "======================================================================"

# 作業ディレクトリ
WORK_DIR="/mnt/user-data/outputs"
cd "$WORK_DIR"

echo ""
echo "【1. ディレクトリ構造の作成】"
mkdir -p src tests examples/outputs docs
echo "✓ ディレクトリ作成完了"

echo ""
echo "【2. ファイルの整理】"

# コアファイル
cp harmony_rules_complete.py src/ 2>/dev/null && echo "  ✓ harmony_rules_complete.py → src/"
cp voice_leading_fugue_gen.py src/ 2>/dev/null && echo "  ✓ voice_leading_fugue_gen.py → src/"
cp midi_writer.py src/ 2>/dev/null && echo "  ✓ midi_writer.py → src/"
cp counterpoint_engine.py src/ 2>/dev/null || echo "  - counterpoint_engine.py (オプション)"
cp fugue_structure.py src/ 2>/dev/null || echo "  - fugue_structure.py (オプション)"
cp harmony.py src/ 2>/dev/null || echo "  - harmony.py (オプション)"
cp rule_compliant_generator.py src/ 2>/dev/null || echo "  - rule_compliant_generator.py (オプション)"

# テストファイル
cp test_generated_fugue.py tests/ 2>/dev/null && echo "  ✓ test_generated_fugue.py → tests/"

# ドキュメント
cp HARMONY_INTEGRATION.md docs/ 2>/dev/null && echo "  ✓ HARMONY_INTEGRATION.md → docs/"
cp GITHUB_MIGRATION_GUIDE.md docs/ 2>/dev/null && echo "  ✓ GITHUB_MIGRATION_GUIDE.md → docs/"

# サンプルMIDI
cp voice_leading_fugue.mid examples/outputs/ 2>/dev/null && echo "  ✓ voice_leading_fugue.mid → examples/outputs/"
cp strict_harmony_fugue.mid examples/outputs/ 2>/dev/null || echo "  - strict_harmony_fugue.mid (オプション)"

echo "✓ ファイル整理完了"

echo ""
echo "【3. __init__.py の作成】"
touch src/__init__.py
touch tests/__init__.py
echo "✓ __init__.py 作成完了"

echo ""
echo "【4. .gitignore の作成】"
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/
build/
dist/
*.egg-info/
.pytest_cache/

# IDE
.vscode/
.idea/
*.swp
*.swo
*.sublime-*

# OS
.DS_Store
Thumbs.db
.directory

# Project specific
temp/
*.log

# Keep example outputs
!examples/outputs/*.mid
EOF
echo "✓ .gitignore 作成完了"

echo ""
echo "【5. requirements.txt の作成】"
cat > requirements.txt << 'EOF'
# Bach Fugue Generator
# No external dependencies - uses Python standard library only

# For development/testing:
# pytest>=7.0.0  # Optional: for advanced testing
# black>=22.0.0  # Optional: for code formatting
# mypy>=0.950    # Optional: for type checking
EOF
echo "✓ requirements.txt 作成完了"

echo ""
echo "【6. README.md の作成】"
cat > README.md << 'EOF'
# 🎼 Bach Style Fugue Generator

バッハ様式のフーガを自動生成するPythonプログラム

## ✨ 特徴

- **95.9%の和声学規則遵守**（Walter Piston "Harmony" ベース）
- 声部導音テクニック統合（共通音保持・最短距離・順次進行優先）
- 完全なMIDI出力（標準ライブラリのみ使用）
- 包括的なテストスイート

## 📊 テスト結果

- **97項目の規則チェック中93項目合格**
- 全10章の古典和声学規則を実装

### 検証済みの規則

✅ 声部音域（100%）  
✅ 声部交差（100%）  
✅ 声部間隔（100%）  
✅ 増音程の旋律的使用（100%）  
✅ 和声進行（100%）  
⚠️ 平行5度・8度（91.7%） - 2箇所の違反  
⚠️ 和音の完全性（75%） - 第三音省略2箇所  

## 🚀 クイックスタート

```python
from src.voice_leading_fugue_gen import VoiceLeadingGenerator

# フーガを生成
generator = VoiceLeadingGenerator(tonic_pc=0)  # C major
generator.generate(num_chords=8)
generator.export_midi("my_fugue.mid", tempo=80)
```

## 📦 インストール

```bash
git clone https://github.com/YOUR_USERNAME/bach-fugue-generator.git
cd bach-fugue-generator
```

依存関係なし - Python 3.8以上のみ必要

## 🧪 テスト実行

```bash
# 和声学規則のテスト
python -m tests.test_harmony_rules

# 生成フーガのテスト
python -m tests.test_generated_fugue
```

## 📚 ドキュメント

- [和声学統合の解説](docs/HARMONY_INTEGRATION.md)
- [GitHub移行ガイド](docs/GITHUB_MIGRATION_GUIDE.md)

## 🏗️ プロジェクト構成

```
bach-fugue-generator/
├── src/
│   ├── harmony_rules_complete.py      # 古典和声学規則集
│   ├── voice_leading_fugue_gen.py     # メイン生成エンジン
│   └── midi_writer.py                  # MIDI出力
├── tests/
│   └── test_generated_fugue.py         # テストスイート
├── examples/
│   └── outputs/                        # 生成MIDIサンプル
└── docs/                               # ドキュメント
```

## 🎯 実装された和声学規則

### 第1章: 音階と調性
長音階・自然短音階・和声的短音階

### 第2章: 三和音と七の和音
長・短・減・増三和音、属七・長七・短七・半減七・減七

### 第3章: 声部配置
声部音域、声部交差の禁止、声部間隔の制限

### 第4章: 平行進行の禁則
平行5度・8度の禁止、隠伏5度・8度のチェック

### 第5章: 不協和音程
短二度・増四度の禁止、強拍での制約

### 第6章: 和声進行
V→IV、V→ii、vii°→IV の禁止

### 第7章: 導音と解決
導音の主音への上行解決、第七音の下行解決

### 第8章: 重複と省略
第三音の省略禁止、重複規則

### 第9章: カデンツ
完全正格終止（V7→I）

### 第10章: 非和声音
経過音・刺繍音の正しい使い方

## 🔄 開発ロードマップ

### 短期（完成度100%へ）
- [ ] 平行進行違反の完全解消
- [ ] 第三音省略の完全防止

### 中期（機能拡張）
- [ ] リズムの多様化（8分音符、付点リズム）
- [ ] 主題の自動生成
- [ ] より長いフーガ（16小節以上）

### 長期（完全なシステム）
- [ ] 完全なフーガ構造（提示部・展開部・ストレット・コーダ）
- [ ] 副属和音と転調
- [ ] 複数声部（4声フーガ）
- [ ] Webインターフェース

## 📖 参考文献

- Walter Piston: "Harmony" (5th edition, 1987)
- Johann Joseph Fux: "Gradus ad Parnassum" (1725)
- Kent Kennan: "Counterpoint"

## 📄 ライセンス

MIT License

## 🤝 コントリビューション

Pull Requestを歓迎します！

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 👤 Author

Created with Claude (Anthropic)

## 🌟 謝辞

このプロジェクトは古典和声学の巨匠たちの知恵に基づいています。
EOF
echo "✓ README.md 作成完了"

echo ""
echo "======================================================================"
echo "✓ セットアップ完了！"
echo "======================================================================"
echo ""
echo "次のステップ:"
echo ""
echo "1. Gitリポジトリを初期化:"
echo "   cd $WORK_DIR"
echo "   git init"
echo "   git branch -M main"
echo ""
echo "2. 初回コミット:"
echo "   git add ."
echo "   git commit -m \"Initial commit: Bach-style fugue generator\""
echo ""
echo "3. GitHubリモートを追加（YOUR_USERNAME と REPO_NAME を置き換え）:"
echo "   git remote add origin https://github.com/YOUR_USERNAME/REPO_NAME.git"
echo ""
echo "4. プッシュ:"
echo "   git push -u origin main"
echo ""
echo "======================================================================"
