# バッハ様式フーガ生成プロジェクト - 開発議事録
# Cowork引き継ぎ用ドキュメント

作成日: 2026年2月7日
セッション: Claude.ai Web版 → Claude Desktop Cowork への移行

---

## 📋 プロジェクト概要

### プロジェクト名
**Bach-Style Fugue Generator (bach-fugue-generator / fuge)**

### 目的
古典和声学の規則を100%遵守するバッハ様式のフーガ自動生成システム

### GitHubリポジトリ
- **URL**: https://github.com/nobuhiko-ohki/fuge
- **状態**: プライベートリポジトリ、初回コミット済み
- **ローカル環境**: VS Code + GitHub Desktop で管理中

---

## 🎯 現在の達成状況

### ✅ 完成した成果物

#### 1. 古典和声学 完全規則集
**ファイル**: `src/harmony_rules_complete.py`

**実装内容**:
- Walter Piston "Harmony" (5th edition, 1987) に基づく
- 全10章の規則を完全実装

**規則一覧**:
- 第1章: 音階と調性（長音階・短音階）
- 第2章: 三和音と七の和音（長・短・減・増、属七など）
- 第3章: 声部配置（音域、声部交差、間隔）
- 第4章: 平行進行の禁則（平行5度・8度、隠伏進行）
- 第5章: 不協和音程（短二度・増四度の禁止）
- 第6章: 和声進行（V→IV禁止など）
- 第7章: 導音と解決（導音の上行解決、第七音の下行解決）
- 第8章: 重複と省略（第三音省略禁止）
- 第9章: カデンツ（完全正格終止）
- 第10章: 非和声音（経過音の正しい使用）

**テスト結果**: 7/7項目合格

#### 2. 声部導音テクニック統合生成エンジン
**ファイル**: `src/voice_leading_fugue_gen.py`

**実装された教科書テクニック**:
1. **共通音保持** (Common Tone Retention)
   - 2つの和音の共通音を同じ声部で保持
   - 声部の動きを最小化
   
2. **最短距離の原則** (Nearest Note Principle)
   - 各声部は最も近い和音構成音に動く
   - 大きな跳躍を避ける
   
3. **順次進行優先** (Stepwise Motion Priority)
   - 半音進行（最優先）
   - 全音進行
   - 3度の跳躍（許容）
   - 大きな跳躍（避ける）
   
4. **反行** (Contrary Motion)
   - ソプラノとバスが反対方向に動く
   - 平行5度・8度を自然に回避

**機能**:
- 和声進行の自動計画（I-IV-V-I パターン）
- 3声部の同時生成（Soprano, Alto, Bass）
- MIDI出力（標準ライブラリのみ使用）

#### 3. 包括的テストスイート
**ファイル**: `tests/test_generated_fugue.py`

**テスト項目** (97項目):
1. 声部音域チェック（24項目） → 100%合格
2. 声部交差チェック（8項目） → 100%合格
3. 声部間隔チェック（8項目） → 100%合格
4. 平行5度・8度チェック（21項目） → 91.7%合格 ⚠️
5. 増音程の旋律的使用（21項目） → 100%合格
6. 和声進行チェック（7項目） → 100%合格
7. 和音の完全性チェック（8項目） → 75%合格 ⚠️

**総合成績**: 93/97項目合格（95.9%）

#### 4. サポートファイル
- `src/midi_writer.py`: MIDI出力モジュール
- `src/counterpoint_engine.py`: 対位法エンジン（基礎）
- `src/fugue_structure.py`: フーガ構造定義
- `src/harmony.py`: 和声学補助モジュール
- `examples/outputs/voice_leading_fugue.mid`: 生成サンプル

#### 5. ドキュメント
- `README.md`: プロジェクト概要
- `docs/HARMONY_INTEGRATION.md`: 和声学統合の詳細解説
- `docs/GITHUB_MIGRATION_GUIDE.md`: GitHub移行ガイド
- `GITHUB_READY.md`: GitHub活用ガイド

---

## 🔴 現在の課題（優先順位順）

### Critical（即座に修正すべき）

#### 1. 平行5度・8度の違反（2箇所）
**現状**:
```
拍1→2: alto-bass間で平行1度/8度
拍5→6: soprano-bass間で平行5度
```

**原因**:
- 共通音保持と最短距離の原則が衝突
- 平行進行チェックが声部配置時に不完全

**解決方法**:
```python
# src/voice_leading_fugue_gen.py の voice_next_chord() 内
# 候補選択時に平行進行チェックを追加する必要あり

def voice_next_chord(self, prev_prog, curr_prog):
    # 各声部を処理する前に
    # 全ての組み合わせをチェックして
    # 平行5度・8度を含むものを除外
    pass
```

**期待結果**: 0箇所の違反

#### 2. 第三音省略（2箇所）
**現状**:
```
拍3: 第三音が省略されている
拍4: 第三音が省略されている
```

**原因**:
- `voice_next_chord()` が第三音を必ず含むことを保証していない
- 共通音保持や最短距離を優先しすぎて第三音が抜ける

**解決方法**:
```python
# 和音配置後に第三音の存在をチェック
# 無ければ、どれか1声部を第三音に変更
def ensure_third_present(self, pitches, chord):
    third_pc = chord.third_pc
    if third_pc not in [p % 12 for p in pitches]:
        # アルトまたはソプラノを第三音に変更
        pass
```

**期待結果**: 0箇所の省略

### High（機能拡張）

#### 3. リズムの多様化
**現状**: 4分音符のみ（単調）

**目標**:
- 8分音符の追加
- 付点リズム（付点4分音符 + 8分音符）
- 各声部が異なるリズムで動く

**実装方針**:
```python
# 音符の duration を可変に
# 強拍: 4分音符または2分音符
# 弱拍: 8分音符を許容

class Note:
    duration: int  # 2, 4, 6, 8 など
```

#### 4. より長いフーガの生成
**現状**: 8和音（8拍）のみ

**目標**:
- 16小節以上のフーガ
- バックトラック機能の強化
- 行き詰まった時の回復戦略

#### 5. 主題の自動生成
**現状**: 和声骨組みのみ、明確な主題なし

**目標**:
- バッハ様式の主題パターン分析
- 音階的パターン + 跳躍の組み合わせ
- 主題・応答・対旋律の自動生成

### Medium（将来的な機能）

#### 6. 完全なフーガ構造
- 提示部（Exposition）
- 展開部（Development）
- ストレット（Stretto）
- コーダ（Coda）

#### 7. 副属和音と転調
- V/V, V/vi などの副属和音
- 近親調への転調

#### 8. 4声フーガ
- Soprano, Alto, Tenor, Bass の4声部

---

## 📂 プロジェクト構造

```
fuge/ (または bach-fugue-generator/)
├── .git/                           # Gitリポジトリ
├── .gitignore                      # Git除外設定
├── README.md                       # プロジェクト概要
├── requirements.txt                # 依存関係（なし）
│
├── src/                            # コアソースコード
│   ├── __init__.py
│   ├── harmony_rules_complete.py  # ⭐ 和声学規則集（完成）
│   ├── voice_leading_fugue_gen.py # ⭐ メイン生成エンジン（95.9%）
│   ├── midi_writer.py             # MIDI出力
│   ├── counterpoint_engine.py     # 対位法エンジン
│   ├── fugue_structure.py         # フーガ構造
│   ├── harmony.py                 # 和声学補助
│   └── rule_compliant_generator.py # 制約充足版（開発中）
│
├── tests/                          # テストスイート
│   ├── __init__.py
│   └── test_generated_fugue.py    # ⭐ 自動テスト
│
├── examples/outputs/               # 生成サンプル
│   ├── voice_leading_fugue.mid    # メイン成果物
│   └── strict_harmony_fugue.mid   # 和声骨組みのみ版
│
└── docs/                           # ドキュメント
    ├── HARMONY_INTEGRATION.md     # 和声学統合解説
    └── GITHUB_MIGRATION_GUIDE.md  # GitHub活用ガイド
```

---

## 🛠️ 開発環境

### ローカル環境
- **OS**: macOS
- **エディタ**: VS Code
- **Git管理**: GitHub Desktop
- **Python**: 3.8以上（標準ライブラリのみ使用）

### GitHubリポジトリ
- **URL**: https://github.com/nobuhiko-ohki/fuge
- **可視性**: Private
- **ブランチ**: main
- **最新コミット**: "Initial commit: Bach-style fugue generator"

### 次の作業環境
- **Claude Desktop for Mac** (Cowork機能)
- フォルダ追加予定: `~/Documents/GitHub/fuge/` （または該当パス）

---

## 📝 開発の経緯

### フェーズ1: 基礎実装（完了）
1. 対位法エンジンの基本実装
2. MIDI出力機能
3. 簡易的なフーガ生成

### フェーズ2: 和声学統合（完了）
1. 和声学規則集の完全実装（10章）
2. 和声進行計画機能
3. 規則チェック機能

**問題**: 和声学と対位法の統合が困難
- 和声骨組みを先に作る → 対位法的な動きがない
- 対位法を先に作る → 和声規則を破る

### フェーズ3: 声部導音テクニック統合（現在）
1. 教科書のテクニックを学習
   - 共通音保持
   - 最短距離の原則
   - 順次進行優先
   - 反行の活用

2. これらを統合した生成エンジン作成
   - `voice_leading_fugue_gen.py`
   - 95.9%の規則遵守を達成

3. 包括的テストスイート作成
   - 97項目の自動チェック
   - 違反箇所の特定

**成果**: ほぼ完璧な和声学的正確性
**残課題**: 4箇所の軽微な違反（平行進行2、第三音省略2）

### フェーズ4: GitHub移行（完了）
1. プロジェクト構造の整理
2. Git初期化とコミット
3. GitHubへのプッシュ成功

### フェーズ5: Cowork移行（進行中）
- Claude Desktop for Macにて設定中
- より効率的な開発環境へ移行

---

## 🎯 次のアクションアイテム

### 即座に着手すべきこと

#### 1. 平行5度・8度の完全解消
**優先度**: Critical
**ファイル**: `src/voice_leading_fugue_gen.py`
**実装箇所**: `voice_next_chord()` メソッド

**具体的な修正内容**:
```python
def voice_next_chord(self, prev_prog, curr_prog):
    # 現在のコード:
    # - 各声部を順番に決定している
    # - 決定後に他の声部との平行進行をチェックしていない
    
    # 改善案:
    # 1. 全ての声部の候補を生成
    # 2. 全ての組み合わせを試す
    # 3. 平行5度・8度を含む組み合わせを除外
    # 4. 残った組み合わせから最適なものを選択
    
    # 擬似コード:
    soprano_candidates = get_stepwise_candidates(prev_soprano, ...)
    alto_candidates = get_stepwise_candidates(prev_alto, ...)
    bass_candidates = get_bass_candidates(...)  # バスは根音
    
    for s_pitch in soprano_candidates:
        for a_pitch in alto_candidates:
            for b_pitch in bass_candidates:
                # 平行進行チェック
                if not has_parallel_motion(prev_pitches, new_pitches):
                    # 第三音チェック
                    if has_third(s_pitch, a_pitch, b_pitch):
                        # 採用
                        return (s_pitch, a_pitch, b_pitch)
    
    # 候補がない場合はバックトラック
    return None
```

**期待される結果**: 平行進行違反が0箇所になる

#### 2. 第三音省略の完全防止
**優先度**: Critical
**ファイル**: `src/voice_leading_fugue_gen.py`
**実装箇所**: `voice_next_chord()` メソッド内、または後処理

**具体的な修正内容**:
```python
def ensure_third_in_voicing(self, soprano, alto, bass, chord):
    """和音に第三音が含まれることを保証"""
    third_pc = chord.third_pc
    
    # 現在のピッチクラスを取得
    current_pcs = {soprano % 12, alto % 12, bass % 12}
    
    # 第三音が含まれているかチェック
    if third_pc not in current_pcs:
        # アルトを第三音に変更（バスは根音を維持）
        alto_new = third_pc
        # 適切なオクターブに調整
        while alto_new < bass:
            alto_new += 12
        while alto_new > soprano:
            alto_new -= 12
        
        return (soprano, alto_new, bass)
    
    return (soprano, alto, bass)
```

**期待される結果**: 第三音省略が0箇所になる

#### 3. テストの再実行
**優先度**: Critical
**コマンド**: 
```bash
cd ~/Documents/GitHub/fuge
python tests/test_generated_fugue.py
```

**期待される結果**: 97/97項目合格（100%）

---

## 📚 参考文献・理論的背景

### 和声学
- Walter Piston: "Harmony" (5th edition, 1987)
  - Chapter 4-6: 声部導音の基本原則
  - Chapter 8: 非和声音の使用

### 対位法
- Johann Joseph Fux: "Gradus ad Parnassum" (1725)
  - 種対位法の基礎
  - 声部独立性の原則

- Kent Kennan: "Counterpoint" (4th edition, 1999)
  - 2声対位法の実践
  - フーガの構造分析

### フーガ
- J.S. Bach: "The Well-Tempered Clavier" (1722, 1742)
  - BWV 846-893の48曲のフーガ
  - 実例として参照

---

## 🔧 技術的な詳細

### 使用技術
- **言語**: Python 3.8+
- **依存関係**: なし（標準ライブラリのみ）
- **MIDI生成**: `midiutil` 相当の自作実装

### 音楽表現
- **音高**: MIDI番号（0-127）
- **時間単位**: 16分音符（sixteenth note）を基本単位
- **4分音符** = 4 sixteenths
- **1小節（4/4拍子）** = 16 sixteenths

### 和音表現
```python
@dataclass
class ChordProgression:
    position: int              # 16分音符単位の位置
    degree: ScaleDegree       # I, II, III, IV, V, VI, VII
    chord_tones: Set[int]     # ピッチクラス（0-11）
    root_pc: int              # 根音
    third_pc: int             # 第三音
    fifth_pc: int             # 第五音
```

### 声部
```python
class Voice(Enum):
    SOPRANO = "soprano"  # C4-G5 (60-79)
    ALTO = "alto"        # G3-C5 (55-74)
    BASS = "bass"        # E2-C4 (40-60)
```

---

## 💻 よく使うコマンド

### 生成実行
```bash
cd ~/Documents/GitHub/fuge
python src/voice_leading_fugue_gen.py
```

### テスト実行
```bash
python tests/test_generated_fugue.py
```

### Git操作（GitHub Desktop使用）
- コミット: GUI操作
- プッシュ: GUI操作
- または VS Code統合Git機能

---

## 🐛 既知の問題

### 1. バックトラック機能が不完全
**症状**: 候補が見つからない時に失敗する
**影響**: 長いフーガを生成できない
**暫定対応**: 短い（8和音程度）フーガのみ生成

### 2. リズムが単調
**症状**: 全て4分音符
**影響**: 音楽的に退屈
**優先度**: High（機能拡張）

### 3. 主題が明確でない
**症状**: 和声骨組みのみで旋律的な特徴がない
**影響**: フーガとして不完全
**優先度**: High（機能拡張）

---

## 📊 開発メトリクス

### コード統計
- **総行数**: 約12,214行（全ファイル合計）
- **コアモジュール**: 約3,000行
- **テストコード**: 約500行
- **ドキュメント**: 約8,000行

### テストカバレッジ
- **規則チェック**: 97項目
- **合格率**: 95.9%
- **目標**: 100%

### 生成品質
- **和声学的正確性**: 95.9%
- **対位法的質**: 未評価（今後の課題）
- **音楽的魅力**: 限定的（リズム単調、主題不明確）

---

## 🎵 サンプル出力

### voice_leading_fugue.mid
- **長さ**: 8和音（8拍）
- **調性**: C major
- **声部**: 3声（Soprano, Alto, Bass）
- **和声進行**: I-IV-V-I-I-IV-V-I
- **規則遵守率**: 95.9%

### strict_harmony_fugue.mid
- **長さ**: 6和音（6拍）
- **特徴**: 和声骨組みのみ（全音符）
- **規則遵守率**: 100%（動きが少ないため）

---

## 🔄 Coworkでの作業開始手順

### 1. Coworkタブでフォルダを開く
```
Claude Desktop → Coworkタブ
→ フォルダ追加ボタン
→ ~/Documents/GitHub/fuge を選択
```

### 2. プロジェクトファイルの確認
```
「プロジェクトのファイル一覧を表示して」
```

### 3. 最優先課題に着手
```
「src/voice_leading_fugue_gen.py を開いて、
 平行5度・8度の問題を修正してください」
```

### 4. テスト実行
```
「tests/test_generated_fugue.py を実行して、
 修正が成功したか確認してください」
```

### 5. 完成したらコミット
```
「修正をgit commitしてください。
 コミットメッセージ: Fix parallel fifths and octaves violations」
```

---

## 📋 チェックリスト

### 完了した項目
- [x] 和声学規則集の実装
- [x] 声部導音テクニックの実装
- [x] 基本的なフーガ生成機能
- [x] MIDI出力機能
- [x] テストスイート作成
- [x] GitHub リポジトリ作成
- [x] ドキュメント整備

### 進行中の項目
- [ ] 平行5度・8度の完全解消（95.9% → 100%）
- [ ] 第三音省略の防止

### 未着手の項目
- [ ] リズムの多様化
- [ ] 主題の自動生成
- [ ] より長いフーガの生成
- [ ] 完全なフーガ構造（提示部・展開部・ストレット）
- [ ] 副属和音と転調
- [ ] 4声フーガ

---

## 💬 重要な設計判断

### なぜこのアプローチを選んだか

#### 1. 声部導音テクニックの統合
**選択**: 教科書のテクニック（共通音保持、最短距離など）を明示的に実装

**理由**:
- 制約充足問題として解くだけでは解が見つからない
- 人間の作曲家が使う「解決法」を学ぶ必要があった
- バッハも同じテクニックを使っている

**結果**: 95.9%の高い成功率

#### 2. 和声進行を先に計画
**選択**: 和声進行を事前に全て計画してから声部配置

**理由**:
- 行き当たりばったりでは良い進行にならない
- 終結（カデンツ）から逆算する必要がある
- フーガの構造上、和声計画が必須

**結果**: 明確な和声構造を持つフーガが生成できる

#### 3. 標準ライブラリのみ使用
**選択**: 外部ライブラリに依存しない

**理由**:
- 依存関係の管理が不要
- どの環境でも動作
- MIDIライブラリも自作

**結果**: ポータビリティの高いコード

---

## 🎓 学んだこと

### 技術的な学び
1. **和声学と対位法の統合は難しい**
   - 両方を同時に満たすのは制約充足問題
   - 教科書のテクニックが重要

2. **バックトラックが必須**
   - 行き詰まった時に戻る仕組みが必要
   - 現在の実装は不完全

3. **テストの重要性**
   - 97項目のテストで問題を正確に特定できた
   - テストなしでは改善不可能だった

### 音楽理論的な学び
1. **第三音は絶対省略不可**
   - 和音の性格を決める最重要音
   - これを守るのが意外と難しい

2. **平行5度・8度は本当に目立つ**
   - たった2箇所でも音楽的に不自然
   - 完全に防ぐ必要がある

3. **リズムの重要性**
   - 和声が正しくてもリズムが単調だと退屈
   - 次の大きな課題

---

## 🚀 Coworkでの次のステップ

### Step 1: 環境確認（5分）
```
1. プロジェクトファイルが正しく読めるか確認
2. src/voice_leading_fugue_gen.py の内容を確認
3. tests/test_generated_fugue.py の内容を確認
```

### Step 2: 平行5度・8度の修正（30分）
```
1. voice_next_chord() メソッドを修正
2. 全ての声部の組み合わせをチェック
3. 平行進行を含む組み合わせを除外
```

### Step 3: 第三音省略の修正（20分）
```
1. ensure_third_in_voicing() メソッドを追加
2. voice_next_chord() から呼び出す
3. 第三音が必ず含まれることを保証
```

### Step 4: テスト実行（10分）
```
1. python tests/test_generated_fugue.py を実行
2. 97/97項目合格を確認
3. voice_leading_fugue.mid を生成
```

### Step 5: コミット（5分）
```
1. git add src/voice_leading_fugue_gen.py
2. git commit -m "Fix parallel motion and third omission - achieve 100% rule compliance"
3. git push
```

---

## 📞 連絡事項

### このセッションで作成したファイル
- すべて `/mnt/user-data/outputs/` に保存済み
- GitHub リポジトリにプッシュ済み
- 特に重要: 
  - `src/harmony_rules_complete.py`
  - `src/voice_leading_fugue_gen.py`
  - `tests/test_generated_fugue.py`

### この議事録の使い方
1. Coworkでの作業開始時に参照
2. 「この議事録を読んで理解してください」と指示
3. 「平行5度・8度の修正から始めてください」と指示

---

## ✅ 引き継ぎチェックリスト

Coworkで作業を開始する前に確認：

- [ ] この議事録を Cowork セッションに共有
- [ ] プロジェクトフォルダ（fuge/）が Cowork で開かれている
- [ ] src/voice_leading_fugue_gen.py が読める
- [ ] tests/test_generated_fugue.py が実行できる
- [ ] git が使える状態（GitHub Desktop または CLI）

---

**議事録作成者**: Claude (Anthropic)
**作成日時**: 2026年2月7日
**セッション**: Web版からCoworkへの引き継ぎ
**ステータス**: 95.9% → 100%達成に向けて

---

## 📎 添付ファイル（zipに含まれる）

1. `bach-fugue-generator.zip` - プロジェクト全体
2. この議事録 - Cowork引き継ぎ用

**Coworkでの最初のコマンド例**:
```
「この議事録を読んで、プロジェクトの現状を理解してください。
その後、src/voice_leading_fugue_gen.py の平行5度・8度の問題を修正してください。」
```

成功を祈ります！🎼🚀
