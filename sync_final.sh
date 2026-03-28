#!/bin/bash
# ============================================================
# Prout版ファイル同期スクリプト
#
# Mac側のターミナルで ~/Documents/GitHub/fuge/ にて実行:
#   bash sync_final.sh
#
# デッドロック中のファイルをProut版で置き換え、
# 一時ファイル（_copy.py, _prout.py, _new.py）を整理する。
# ============================================================

set -e
cd "$(dirname "$0")"

echo "=== Prout版ファイル同期 ==="

# 1. デッドロック中のファイルをバックアップしてProut版に置換
echo ""
echo "--- ステップ1: counterpoint_engine.py をProut版に置換 ---"
if [ -f src/counterpoint_engine.py ]; then
    mv src/counterpoint_engine.py src/counterpoint_engine_old.py
    echo "  旧版 → counterpoint_engine_old.py"
fi
cp src/counterpoint_engine_prout.py src/counterpoint_engine.py
echo "  Prout版 → counterpoint_engine.py"

echo ""
echo "--- ステップ2: fugue_structure.py をProut版に置換 ---"
if [ -f src/fugue_structure.py ]; then
    mv src/fugue_structure.py src/fugue_structure_old.py
    echo "  旧版 → fugue_structure_old.py"
fi
cp src/fugue_structure_prout.py src/fugue_structure.py
echo "  Prout版 → fugue_structure.py"

echo ""
echo "--- ステップ3: midi_writer.py を修正版に置換 ---"
if [ -f src/midi_writer_fixed.py ]; then
    mv src/midi_writer.py src/midi_writer_old.py 2>/dev/null || true
    mv src/midi_writer_fixed.py src/midi_writer.py
    echo "  修正版 → midi_writer.py (.midi_number → .midi 修正)"
fi

echo ""
echo "--- ステップ4: テストファイル同期 ---"
if [ -f tests/test_fugue_structure_prout.py ]; then
    mv tests/test_fugue_structure.py tests/test_fugue_structure_old.py 2>/dev/null || true
    cp tests/test_fugue_structure_prout.py tests/test_fugue_structure.py
    echo "  Prout版テスト → test_fugue_structure.py"
fi
if [ -f tests/test_counterpoint_prout.py ]; then
    mv tests/test_counterpoint.py tests/test_counterpoint_old.py 2>/dev/null || true
    cp tests/test_counterpoint_prout.py tests/test_counterpoint.py
    echo "  Prout版テスト → test_counterpoint.py"
fi

echo ""
echo "--- ステップ5: 一時ファイル削除 ---"
rm -f src/_test_write.txt src/_test_overwrite.py
rm -f src/*_copy.py src/*_new.py
rm -f tests/*_new.py
echo "  一時ファイル削除完了"

echo ""
echo "=== 同期完了 ==="
echo ""
echo "残存する _prout.py / _old.py ファイルは参照用に保持しています。"
echo "不要になったら以下で削除:"
echo "  rm src/*_prout.py src/*_old.py tests/*_prout.py tests/*_old.py"
