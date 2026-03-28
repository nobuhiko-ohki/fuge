#\!/bin/bash
# Prout準拠ファイル同期スクリプト
# マウント復旧後に実行してください
cd /sessions/fervent-vigilant-hypatia/mnt/fuge/src

# バックアップ
for f in fugue_structure.py counterpoint_engine.py harmony_rules_complete.py; do
    if [ -f "$f" ]; then
        cp "$f" "${f}.bak" 2>/dev/null || echo "backup skip: $f"
    fi
done

# Prout版で置換
mv fugue_structure_prout.py fugue_structure.py 2>/dev/null && echo 'Updated: fugue_structure.py'
mv counterpoint_engine_prout.py counterpoint_engine.py 2>/dev/null && echo 'Updated: counterpoint_engine.py'
mv harmony_rules_complete_prout.py harmony_rules_complete.py 2>/dev/null && echo 'Updated: harmony_rules_complete.py'

cd ../tests
mv test_fugue_structure_prout.py test_fugue_structure.py 2>/dev/null && echo 'Updated: test_fugue_structure.py'
mv test_counterpoint_prout.py test_counterpoint.py 2>/dev/null && echo 'Updated: test_counterpoint.py'

# __pycache__ クリア
rm -rf ../src/__pycache__ 2>/dev/null

echo 'Done. Run tests with: cd tests && python3 test_fugue_structure.py && python3 test_counterpoint.py'
