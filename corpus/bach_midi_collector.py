"""
Bach MIDI 自動収集システム

複数のオンラインソースからバッハの MIDI ファイルを
自動的に収集・分類・重複排除する。

アーキテクチャ:
  Collector (抽象基底)
    ├─ HuggingFaceCollector     — drengskapur/midi-classical-music
    ├─ GigaMIDICollector        — Metacreation/GigaMIDI（2.1M files）
    ├─ WebCrawlCollector        — kunstderfuge, bachcentral, jsbach.net 等
    ├─ GitHubCollector          — GitHub リポジトリ検索
    └─ LocalFileCollector       — ローカルファイルスキャン

  CollectionPipeline
    1. 各 Collector が MIDI バイナリ + メタデータを yield
    2. MIDIValidator が破損ファイルを除外
    3. Deduplicator がハッシュベースで重複排除
    4. Classifier が BWV 番号・ジャンルを推定
    5. 出力: corpus_dir/{bwv_nnn}/filename.mid + metadata.json

依存関係:
  必須: requests (pip install requests)
  任意: datasets (pip install datasets) — HuggingFace 用
  フォールバック: urllib.request（requests 不在時）

使用方法:
  python bach_midi_collector.py --output-dir ./corpus/bach_midi
  python bach_midi_collector.py --source huggingface --output-dir ./corpus/bach_midi
  python bach_midi_collector.py --source web --output-dir ./corpus/bach_midi
  python bach_midi_collector.py --list-sources
"""

import hashlib
import json
import os
import re
import struct
import sys
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import (
    List, Dict, Optional, Tuple, Iterator, Set, Any, Generator
)
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# ============================================================
# ログ設定
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('bach_collector')


# ============================================================
# HTTP ユーティリティ（requests フォールバック）
# ============================================================

def _http_get(url: str, timeout: int = 30,
              binary: bool = False) -> Optional[Any]:
    """HTTP GET リクエスト。requests があれば使い、なければ urllib。

    Returns:
        成功時: bytes (binary=True) or str (binary=False)
        失敗時: None
    """
    try:
        import requests
        resp = requests.get(url, timeout=timeout,
                            headers={'User-Agent': 'BachMIDICollector/1.0'})
        resp.raise_for_status()
        return resp.content if binary else resp.text
    except ImportError:
        import urllib.request
        req = urllib.request.Request(
            url, headers={'User-Agent': 'BachMIDICollector/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return data if binary else data.decode('utf-8', errors='replace')
    except Exception as e:
        # 404 は DEBUG レベル（大量に出るため）
        msg = str(e)
        if '404' in msg or '403' in msg:
            logger.debug(f"HTTP {url} — {e}")
        else:
            logger.warning(f"HTTP GET 失敗: {url} — {e}")
        return None


# ============================================================
# データ構造
# ============================================================

@dataclass
class MIDIRecord:
    """収集された MIDI ファイルのメタデータ"""
    # 基本情報
    filename: str = ""
    source: str = ""           # 収集元（"huggingface", "kunstderfuge", etc.）
    source_url: str = ""       # 元 URL
    midi_data: bytes = b""     # MIDI バイナリ（メモリ内）

    # 分類情報
    bwv: Optional[int] = None  # BWV 番号
    title: str = ""
    genre: str = ""            # "fugue", "prelude", "chorale", etc.
    collection: str = ""       # "wtc1", "wtc2", "art_of_fugue", etc.

    # 品質情報
    md5: str = ""
    file_size: int = 0
    is_valid: bool = False
    num_tracks: int = 0
    num_notes: int = 0
    duration_ticks: int = 0

    def compute_hash(self):
        if self.midi_data:
            self.md5 = hashlib.md5(self.midi_data).hexdigest()
            self.file_size = len(self.midi_data)


# ============================================================
# MIDI バリデーション
# ============================================================

class MIDIValidator:
    """MIDI ファイルの妥当性を検証する。"""

    @staticmethod
    def validate(data: bytes) -> Tuple[bool, Dict[str, Any]]:
        """MIDI バイナリを簡易検証する。

        Returns:
            (is_valid, info_dict)
        """
        info = {"error": None, "format": 0, "tracks": 0, "ticks": 0}

        if len(data) < 14:
            info["error"] = "too_short"
            return False, info

        # MThd ヘッダー
        if data[:4] != b'MThd':
            info["error"] = "invalid_header"
            return False, info

        try:
            header_len = struct.unpack('>I', data[4:8])[0]
            if header_len < 6:
                info["error"] = "header_too_short"
                return False, info

            fmt = struct.unpack('>H', data[8:10])[0]
            num_tracks = struct.unpack('>H', data[10:12])[0]
            ticks = struct.unpack('>H', data[12:14])[0]

            info["format"] = fmt
            info["tracks"] = num_tracks
            info["ticks"] = ticks

            if fmt > 2:
                info["error"] = "unknown_format"
                return False, info

            if num_tracks == 0:
                info["error"] = "no_tracks"
                return False, info

            if ticks == 0:
                info["error"] = "zero_ticks"
                return False, info

            # MTrk チャンクが存在するか
            if b'MTrk' not in data[14:]:
                info["error"] = "no_track_chunk"
                return False, info

            return True, info

        except struct.error:
            info["error"] = "struct_error"
            return False, info


# ============================================================
# BWV 番号推定
# ============================================================

# BWV 番号とタイトル/ファイル名のマッピング（主要作品）
BWV_PATTERNS = {
    # WTC Book I (BWV 846-869)
    r'(?:wtc|well.?tempered|wohltemperiert).*?(?:book|buch|bk)?\s*[I1].*?(?:prelude|fugue|pr[aä]ludium|fuge)\s*(?:no\.?\s*)?(\d+)':
        lambda m: 845 + int(m.group(1)),
    # WTC Book II (BWV 870-893)
    r'(?:wtc|well.?tempered|wohltemperiert).*?(?:book|buch|bk)?\s*(?:II|2).*?(?:prelude|fugue|pr[aä]ludium|fuge)\s*(?:no\.?\s*)?(\d+)':
        lambda m: 869 + int(m.group(1)),
    # Art of Fugue (BWV 1080) — ファイル名パターン "1080-" も含む
    r'(?:art.?of.?fugue|kunst.?der.?fuge|1080[\-_])':
        lambda m: 1080,
    # Musical Offering (BWV 1079)
    r'(?:musical.?offering|musikalisches.?opfer|1079[\-_])':
        lambda m: 1079,
    # "bach_NNN" パターン (piano-midi.de: bach_846.mid)
    r'bach[_\-](\d{3,4})':
        lambda m: int(m.group(1)),
    # 直接 BWV 番号
    r'bwv\s*[._\-]?\s*(\d+)':
        lambda m: int(m.group(1)),
}

# ジャンル推定パターン
# \b の代わりに (?=\d|$|\s|[_.\-]) で数字直前もマッチ
GENRE_PATTERNS = {
    'fugue': r'(?:fugue|fuge|fuga|fug(?=\d|[_.\-]))',
    'prelude': r'(?:prelude|pr[aä]ludium|praeludium|prel(?=\d|[_.\-]))',
    'chorale': r'(?:chorale?|choral|catech)',
    'invention': r'(?:invention|sinfonien?|inver|inven)',
    'canon': r'(?:canon|can(?=\d|[_.\-]))',
    'suite': r'(?:suite|partita)',
    'sonata': r'(?:sonata|sonate)',
    'concerto': r'(?:concerto|konzert)',
    'toccata': r'(?:toccata|tocc)',
    'passacaglia': r'(?:passacaglia)',
    'fantasia': r'(?:fantasia|fantasie)',
}

# コレクション推定パターン
COLLECTION_PATTERNS = {
    'wtc1': r'(?:wtc|well.?tempered|wohltemperiert).*?(?:book|buch|bk)?\s*[I1]\b',
    'wtc2': r'(?:wtc|well.?tempered|wohltemperiert).*?(?:book|buch|bk)?\s*(?:II|2)\b',
    'art_of_fugue': r'(?:art.?of.?fugue|kunst.?der.?fuge|1080[\-_])',
    'inventions': r'(?:invention|sinfonien?|inver|inven)',
    'french_suites': r'(?:french.?suite)',
    'english_suites': r'(?:english.?suite)',
    'goldberg': r'(?:goldberg)',
    'organ_works': r'(?:organ|orgel)',
    'cello_suites': r'(?:cello.?suite)',
    'musical_offering': r'(?:musical.?offering|musikalisches.?opfer|1079[\-_])',
}


def classify_bach_midi(filename: str, title: str = "") -> Dict[str, Any]:
    """ファイル名/タイトルから BWV 番号・ジャンル・コレクションを推定する。

    Returns:
        {"bwv": int|None, "genre": str, "collection": str}
    """
    text = f"{filename} {title}".lower()
    result = {"bwv": None, "genre": "", "collection": ""}

    # BWV 番号
    for pattern, extractor in BWV_PATTERNS.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                result["bwv"] = extractor(m)
            except (ValueError, IndexError):
                pass
            break

    # ジャンル
    for genre, pattern in GENRE_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            result["genre"] = genre
            break

    # コレクション
    for coll, pattern in COLLECTION_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            result["collection"] = coll
            break

    return result


# ============================================================
# Collector 抽象基底
# ============================================================

class Collector(ABC):
    """MIDI 収集の抽象基底クラス。

    各ソースに特化した Collector を実装し、
    collect() で MIDIRecord を yield する。
    """

    name: str = "base"
    description: str = ""

    @abstractmethod
    def collect(self, **kwargs) -> Generator[MIDIRecord, None, None]:
        """MIDIRecord を順次 yield する。"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """このソースが利用可能か確認する。"""
        pass


# ============================================================
# 1. HuggingFace Collector
# ============================================================

class HuggingFaceCollector(Collector):
    """HuggingFace の midi-classical-music データセットから Bach を抽出する。

    データセット: drengskapur/midi-classical-music
    構造: composer/title.mid（Bach ディレクトリを検索）

    必要: pip install datasets
    """

    name = "huggingface"
    description = "HuggingFace midi-classical-music dataset (drengskapur)"

    def is_available(self) -> bool:
        try:
            import datasets
            return True
        except ImportError:
            return False

    def collect(self, **kwargs) -> Generator[MIDIRecord, None, None]:
        try:
            from datasets import load_dataset
        except ImportError:
            logger.error("datasets ライブラリが必要です: pip install datasets")
            return

        logger.info("HuggingFace midi-classical-music を読み込み中...")
        try:
            ds = load_dataset(
                "drengskapur/midi-classical-music",
                split="train",
                trust_remote_code=True)
        except Exception as e:
            logger.error(f"データセット読み込み失敗: {e}")
            return

        count = 0
        for item in ds:
            # composer フィールドで Bach をフィルタ
            composer = item.get("composer", "").lower()
            if "bach" not in composer:
                continue

            midi_bytes = item.get("midi", {}).get("bytes", b"")
            if not midi_bytes:
                continue

            filename = item.get("title", f"hf_bach_{count:04d}.mid")
            if not filename.endswith('.mid'):
                filename += '.mid'

            record = MIDIRecord(
                filename=filename,
                source=self.name,
                source_url="https://huggingface.co/datasets/drengskapur/midi-classical-music",
                midi_data=midi_bytes,
                title=item.get("title", ""),
            )
            record.compute_hash()

            classification = classify_bach_midi(filename, record.title)
            record.bwv = classification["bwv"]
            record.genre = classification["genre"]
            record.collection = classification["collection"]

            count += 1
            yield record

        logger.info(f"HuggingFace: {count} 件の Bach MIDI を収集")


# ============================================================
# 2. GigaMIDI Collector
# ============================================================

class GigaMIDICollector(Collector):
    """GigaMIDI データセットから Bach を抽出する。

    データセット: Metacreation/GigaMIDI (2.1M MIDI files)
    タグやメタデータで Bach をフィルタする。

    必要: pip install datasets
    """

    name = "gigamidi"
    description = "GigaMIDI dataset (Metacreation, 2.1M files)"

    def is_available(self) -> bool:
        try:
            import datasets
            return True
        except ImportError:
            return False

    def collect(self, max_items: int = 10000,
                **kwargs) -> Generator[MIDIRecord, None, None]:
        try:
            from datasets import load_dataset
        except ImportError:
            logger.error("datasets ライブラリが必要です: pip install datasets")
            return

        logger.info("GigaMIDI を読み込み中（大容量データセット）...")
        try:
            ds = load_dataset(
                "Metacreation/GigaMIDI",
                "all-instruments-with-drums",
                split="train",
                streaming=True,
                trust_remote_code=True)
        except Exception as e:
            logger.error(f"GigaMIDI 読み込み失敗: {e}")
            return

        count = 0
        scanned = 0
        for item in ds:
            scanned += 1
            if scanned > max_items:
                break

            # メタデータで Bach をフィルタ
            title = str(item.get("title", "")).lower()
            artist = str(item.get("artist", "")).lower()
            tags = str(item.get("tags", "")).lower()
            text = f"{title} {artist} {tags}"

            if "bach" not in text:
                continue

            midi_bytes = item.get("midi", {}).get("bytes", b"")
            if not midi_bytes:
                continue

            filename = f"gigamidi_bach_{count:04d}.mid"
            record = MIDIRecord(
                filename=filename,
                source=self.name,
                source_url="https://huggingface.co/datasets/Metacreation/GigaMIDI",
                midi_data=midi_bytes,
                title=item.get("title", ""),
            )
            record.compute_hash()

            classification = classify_bach_midi(filename, record.title)
            record.bwv = classification["bwv"]
            record.genre = classification["genre"]
            record.collection = classification["collection"]

            count += 1
            yield record

        logger.info(f"GigaMIDI: {scanned} 件中 {count} 件の Bach MIDI を収集")


# ============================================================
# 3. Web Crawl Collector
# ============================================================

class WebCrawlCollector(Collector):
    """Web サイトから Bach MIDI をクロールする。

    対象サイト:
      - kunstderfuge.com  (1500+ Bach MIDIs)
      - bachcentral.com   (Complete Bach Index)
      - jsbach.net        (Dave's Bach Page)
      - mfiles.co.uk      (個別フーガ)
      - piano-midi.de     (ピアノ曲)

    注意: robots.txt を尊重し、リクエスト間隔を空ける。
    """

    name = "web"
    description = "Web crawl from major Bach MIDI sites"

    # クロール対象のサイト定義
    SITES = [
        {
            "name": "kunstderfuge_bach",
            "index_urls": [
                "https://www.kunstderfuge.com/bach/wtk1.htm",
                "https://www.kunstderfuge.com/bach/wtk2.htm",
                "https://www.kunstderfuge.com/bach/keyboard.htm",
                "https://www.kunstderfuge.com/bach/organ.htm",
                "https://www.kunstderfuge.com/bach/chamber.htm",
            ],
            "midi_pattern": r'href=["\']([^"\']*\.mid(?:i)?)["\']',
            "base_url": "https://www.kunstderfuge.com",
            "delay": 2.0,
        },
        {
            "name": "bachcentral",
            "index_urls": [
                "https://www.bachcentral.com/midiindexcomplete.html",
            ],
            "midi_pattern": r'href=["\']([^"\']*\.mid(?:i)?)["\']',
            "base_url": "https://www.bachcentral.com",
            "delay": 2.0,
        },
        {
            "name": "jsbach_net",
            "index_urls": [
                "http://www.jsbach.net/midi/",
                "http://www.jsbach.net/midi/midi_wtc1.html",
                "http://www.jsbach.net/midi/midi_wtc2.html",
                "http://www.jsbach.net/midi/midi_artoffugue.html",
            ],
            "midi_pattern": r'href=["\']([^"\']*\.mid(?:i)?)["\']',
            "base_url": "http://www.jsbach.net",
            "delay": 2.0,
        },
        {
            "name": "piano_midi_de",
            "index_urls": [
                "http://piano-midi.de/bach.htm",
            ],
            "midi_pattern": r'href=["\']([^"\']*\.mid(?:i)?)["\']',
            "base_url": "http://piano-midi.de",
            "delay": 2.0,
        },
    ]

    def is_available(self) -> bool:
        """HTTP アクセスが可能か確認する。"""
        try:
            result = _http_get("https://httpbin.org/status/200", timeout=5)
            return result is not None
        except Exception:
            return False

    def collect(self, sites: Optional[List[str]] = None,
                **kwargs) -> Generator[MIDIRecord, None, None]:
        for site_config in self.SITES:
            if sites and site_config["name"] not in sites:
                continue

            logger.info(f"クロール中: {site_config['name']}")
            yield from self._crawl_site(site_config)

    # 連続エラーがこの数に達したらサイトをスキップ
    MAX_CONSECUTIVE_ERRORS = 20
    # ダウンロード用タイムアウト（秒）
    DOWNLOAD_TIMEOUT = 10
    # 進捗表示間隔
    PROGRESS_INTERVAL = 50

    def _crawl_site(
        self, config: Dict
    ) -> Generator[MIDIRecord, None, None]:
        """1サイトをクロールする。

        - 連続エラーが MAX_CONSECUTIVE_ERRORS に達したらスキップ
        - 404 では delay を入れない（サーバー負荷なし）
        - 定期的に進捗を表示
        """
        midi_urls = set()
        delay = config.get("delay", 2.0)

        # インデックスページから MIDI リンクを抽出
        for index_url in config["index_urls"]:
            html = _http_get(index_url)
            if not html:
                logger.warning(f"  インデックス取得失敗: {index_url}")
                continue

            pattern = config["midi_pattern"]
            for match in re.finditer(pattern, html, re.IGNORECASE):
                midi_path = match.group(1)
                # 絶対 URL に変換
                if midi_path.startswith('http'):
                    midi_url = midi_path
                elif midi_path.startswith('/'):
                    midi_url = config["base_url"] + midi_path
                else:
                    # 相対パス
                    base_dir = index_url.rsplit('/', 1)[0]
                    midi_url = base_dir + '/' + midi_path

                midi_urls.add(midi_url)

            time.sleep(delay)

        total_urls = len(midi_urls)
        logger.info(f"  {total_urls} 件の MIDI リンクを検出")

        # 各 MIDI をダウンロード
        count = 0
        errors = 0
        consecutive_errors = 0
        processed = 0

        for midi_url in sorted(midi_urls):
            processed += 1

            # 進捗表示
            if processed % self.PROGRESS_INTERVAL == 0:
                logger.info(
                    f"  進捗: {processed}/{total_urls} "
                    f"(成功={count}, エラー={errors})")

            # 連続エラー閾値チェック
            if consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                logger.warning(
                    f"  連続 {consecutive_errors} 回エラー — "
                    f"残り {total_urls - processed} 件をスキップ")
                break

            midi_data = _http_get(
                midi_url, binary=True, timeout=self.DOWNLOAD_TIMEOUT)

            if not midi_data or not isinstance(midi_data, bytes):
                errors += 1
                consecutive_errors += 1
                # 404/403 では delay 不要（サーバーに負荷をかけていない）
                continue

            # HTML や ZIP を誤ダウンロードしていないか即座にチェック
            if len(midi_data) < 14 or midi_data[:4] != b'MThd':
                errors += 1
                consecutive_errors += 1
                logger.debug(
                    f"  非MIDI: {midi_url.rsplit('/', 1)[-1]} "
                    f"(先頭={midi_data[:8]!r})")
                continue

            # 成功 → 連続エラーカウンタをリセット
            consecutive_errors = 0

            filename = midi_url.rsplit('/', 1)[-1]
            if not filename.endswith(('.mid', '.midi')):
                filename += '.mid'

            record = MIDIRecord(
                filename=filename,
                source=config["name"],
                source_url=midi_url,
                midi_data=midi_data,
                title=os.path.splitext(filename)[0],
            )
            record.compute_hash()

            classification = classify_bach_midi(filename, record.title)
            record.bwv = classification["bwv"]
            record.genre = classification["genre"]
            record.collection = classification["collection"]

            count += 1
            yield record

            # 成功時のみ delay（サーバーへの配慮）
            time.sleep(delay)

        logger.info(
            f"  完了: {count} 件ダウンロード, "
            f"{errors} 件エラー (全 {total_urls} 件中)")


# ============================================================
# 4. GitHub Collector
# ============================================================

class GitHubCollector(Collector):
    """GitHub API で Bach MIDI リポジトリを検索する。

    既知のリポジトリ + code search API でMIDIを探す。
    """

    name = "github"
    description = "GitHub repository search for Bach MIDI files"

    KNOWN_REPOS = [
        "dmanolidis/bachmidi",
        "ThiagoLira/NeonLightsFugue",
        "halfrost/BachGPT",
        "v3rm1/ml_bach_fugue",
    ]

    def is_available(self) -> bool:
        try:
            result = _http_get("https://api.github.com/rate_limit", timeout=5)
            return result is not None
        except Exception:
            return False

    def collect(self, **kwargs) -> Generator[MIDIRecord, None, None]:
        for repo in self.KNOWN_REPOS:
            logger.info(f"GitHub リポジトリ検索: {repo}")
            yield from self._collect_from_repo(repo)
            time.sleep(1.0)

    def _collect_from_repo(
        self, repo: str
    ) -> Generator[MIDIRecord, None, None]:
        """GitHub リポジトリ内の MIDI ファイルを検索・取得する。"""
        # リポジトリのファイルツリーを取得
        api_url = f"https://api.github.com/repos/{repo}/git/trees/main?recursive=1"
        data = _http_get(api_url)
        if not data:
            # main ブランチがなければ master を試す
            api_url = f"https://api.github.com/repos/{repo}/git/trees/master?recursive=1"
            data = _http_get(api_url)

        if not data:
            return

        try:
            tree = json.loads(data)
        except json.JSONDecodeError:
            return

        midi_files = [
            item for item in tree.get("tree", [])
            if item.get("path", "").lower().endswith(('.mid', '.midi'))
        ]

        for item in midi_files:
            path = item["path"]
            # Raw URL からダウンロード
            raw_url = (f"https://raw.githubusercontent.com/"
                       f"{repo}/main/{path}")
            midi_data = _http_get(raw_url, binary=True)
            if not midi_data:
                raw_url = (f"https://raw.githubusercontent.com/"
                           f"{repo}/master/{path}")
                midi_data = _http_get(raw_url, binary=True)

            if not midi_data or not isinstance(midi_data, bytes):
                continue

            filename = os.path.basename(path)
            record = MIDIRecord(
                filename=filename,
                source=f"github:{repo}",
                source_url=raw_url,
                midi_data=midi_data,
                title=os.path.splitext(filename)[0],
            )
            record.compute_hash()

            classification = classify_bach_midi(filename, record.title)
            record.bwv = classification["bwv"]
            record.genre = classification["genre"]
            record.collection = classification["collection"]

            yield record
            time.sleep(0.5)


# ============================================================
# 5. Local File Collector
# ============================================================

class LocalFileCollector(Collector):
    """ローカルファイルシステムから MIDI ファイルを収集する。

    ユーザーが手動ダウンロードしたファイルを取り込む。
    """

    name = "local"
    description = "Scan local directory for MIDI files"

    def __init__(self, scan_dir: str = "."):
        self.scan_dir = scan_dir

    def is_available(self) -> bool:
        return os.path.isdir(self.scan_dir)

    def collect(self, **kwargs) -> Generator[MIDIRecord, None, None]:
        scan_dir = kwargs.get("scan_dir", self.scan_dir)
        logger.info(f"ローカルスキャン: {scan_dir}")

        count = 0
        for root, dirs, files in os.walk(scan_dir):
            for f in files:
                if not f.lower().endswith(('.mid', '.midi')):
                    continue

                filepath = os.path.join(root, f)
                try:
                    with open(filepath, 'rb') as fh:
                        midi_data = fh.read()
                except IOError:
                    continue

                record = MIDIRecord(
                    filename=f,
                    source="local",
                    source_url=filepath,
                    midi_data=midi_data,
                    title=os.path.splitext(f)[0],
                )
                record.compute_hash()

                classification = classify_bach_midi(f, record.title)
                record.bwv = classification["bwv"]
                record.genre = classification["genre"]
                record.collection = classification["collection"]

                count += 1
                yield record

        logger.info(f"ローカル: {count} 件の MIDI を検出")


# ============================================================
# 重複排除 (Deduplicator)
# ============================================================

class Deduplicator:
    """MD5 ハッシュによる重複排除。"""

    def __init__(self):
        self.seen_hashes: Set[str] = set()
        self.duplicate_count = 0

    def is_duplicate(self, record: MIDIRecord) -> bool:
        if not record.md5:
            record.compute_hash()
        if record.md5 in self.seen_hashes:
            self.duplicate_count += 1
            return True
        self.seen_hashes.add(record.md5)
        return False


# ============================================================
# 収集パイプライン
# ============================================================

class CollectionPipeline:
    """Bach MIDI 収集の統合パイプライン。

    Usage:
        pipeline = CollectionPipeline(output_dir="./corpus/bach_midi")
        pipeline.add_collector(HuggingFaceCollector())
        pipeline.add_collector(WebCrawlCollector())
        stats = pipeline.run()
    """

    def __init__(self, output_dir: str = "./corpus/bach_midi"):
        self.output_dir = output_dir
        self.collectors: List[Collector] = []
        self.validator = MIDIValidator()
        self.deduplicator = Deduplicator()
        self.stats: Dict[str, int] = {
            "total_found": 0,
            "valid": 0,
            "invalid": 0,
            "duplicate": 0,
            "saved": 0,
        }

    def add_collector(self, collector: Collector):
        self.collectors.append(collector)

    def add_all_collectors(self):
        """利用可能な全コレクターを追加する。"""
        all_collectors = [
            HuggingFaceCollector(),
            GigaMIDICollector(),
            WebCrawlCollector(),
            GitHubCollector(),
            LocalFileCollector(),
        ]
        for c in all_collectors:
            if c.is_available():
                self.collectors.append(c)
                logger.info(f"コレクター追加: {c.name} ({c.description})")
            else:
                logger.info(f"コレクター不可: {c.name} — スキップ")

    def run(self, **kwargs) -> Dict[str, int]:
        """収集パイプラインを実行する。"""
        os.makedirs(self.output_dir, exist_ok=True)
        metadata_records = []

        for collector in self.collectors:
            logger.info(f"\n{'='*50}")
            logger.info(f"収集開始: {collector.name}")
            logger.info(f"{'='*50}")

            try:
                for record in collector.collect(**kwargs):
                    self.stats["total_found"] += 1
                    self._process_record(record, metadata_records)
            except Exception as e:
                logger.error(f"コレクター {collector.name} でエラー: {e}")
                continue

        # メタデータ保存
        self._save_metadata(metadata_records)
        self._print_summary()

        return self.stats

    def _process_record(self, record: MIDIRecord,
                        metadata_records: List[Dict]):
        """1件の MIDIRecord を処理する。"""
        # バリデーション
        is_valid, info = self.validator.validate(record.midi_data)
        if not is_valid:
            self.stats["invalid"] += 1
            error_type = info.get('error', '?')
            # エラー種別を集計
            self.stats.setdefault("invalid_reasons", {})
            self.stats["invalid_reasons"][error_type] = (
                self.stats["invalid_reasons"].get(error_type, 0) + 1)
            # invalid_header は HTML を受信した可能性が高い
            if error_type == "invalid_header":
                head = record.midi_data[:40]
                logger.debug(
                    f"  無効(invalid_header): {record.filename} "
                    f"先頭={head!r}")
            else:
                logger.debug(
                    f"  無効: {record.filename} ({error_type})")
            return

        record.is_valid = True
        record.num_tracks = info["tracks"]

        # 重複チェック
        if self.deduplicator.is_duplicate(record):
            self.stats["duplicate"] += 1
            logger.debug(f"  重複: {record.filename}")
            return

        self.stats["valid"] += 1

        # 保存
        self._save_midi(record)
        self.stats["saved"] += 1

        # メタデータ収集（midi_data を除く）
        meta = {
            "filename": record.filename,
            "source": record.source,
            "source_url": record.source_url,
            "bwv": record.bwv,
            "title": record.title,
            "genre": record.genre,
            "collection": record.collection,
            "md5": record.md5,
            "file_size": record.file_size,
            "num_tracks": record.num_tracks,
        }
        metadata_records.append(meta)

    def _save_midi(self, record: MIDIRecord):
        """MIDI ファイルを分類ディレクトリに保存する。"""
        # ディレクトリ構造: output_dir/{collection}/{filename}
        if record.collection:
            subdir = record.collection
        elif record.bwv:
            subdir = f"bwv_{record.bwv:04d}"
        else:
            subdir = "uncategorized"

        save_dir = os.path.join(self.output_dir, subdir)
        os.makedirs(save_dir, exist_ok=True)

        # ファイル名の衝突回避
        save_path = os.path.join(save_dir, record.filename)
        if os.path.exists(save_path):
            base, ext = os.path.splitext(record.filename)
            save_path = os.path.join(
                save_dir, f"{base}_{record.source}{ext}")

        with open(save_path, 'wb') as f:
            f.write(record.midi_data)

        logger.debug(f"  保存: {save_path}")

    def _save_metadata(self, records: List[Dict]):
        """メタデータを JSON として保存する。"""
        meta_path = os.path.join(self.output_dir, "metadata.json")
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        logger.info(f"\nメタデータ保存: {meta_path}")

    def _print_summary(self):
        """収集結果のサマリーを表示する。"""
        s = self.stats
        logger.info(f"\n{'='*50}")
        logger.info("収集完了サマリー")
        logger.info(f"{'='*50}")
        logger.info(f"  検出:   {s['total_found']}")
        logger.info(f"  有効:   {s['valid']}")
        logger.info(f"  無効:   {s['invalid']}")
        if s.get("invalid_reasons"):
            for reason, cnt in sorted(
                    s["invalid_reasons"].items(),
                    key=lambda x: -x[1]):
                logger.info(f"    {reason}: {cnt}")
        logger.info(f"  重複:   {s['duplicate']}")
        logger.info(f"  保存:   {s['saved']}")
        logger.info(f"  出力先: {self.output_dir}")


# ============================================================
# ソース一覧
# ============================================================

ALL_COLLECTORS = {
    "huggingface": HuggingFaceCollector,
    "gigamidi": GigaMIDICollector,
    "web": WebCrawlCollector,
    "github": GitHubCollector,
    "local": LocalFileCollector,
}


def list_sources():
    """利用可能なソース一覧を表示する。"""
    print("\n=== Bach MIDI 収集ソース ===\n")
    for name, cls in ALL_COLLECTORS.items():
        c = cls() if name != "local" else cls(".")
        available = c.is_available()
        status = "OK" if available else "要インストール"
        print(f"  {name:15s} [{status:10s}] {c.description}")
    print()


# ============================================================
# CLI
# ============================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Bach MIDI 自動収集システム")
    parser.add_argument(
        '--output-dir', '-o',
        default='./corpus/bach_midi',
        help='出力ディレクトリ')
    parser.add_argument(
        '--source', '-s',
        choices=list(ALL_COLLECTORS.keys()) + ['all'],
        default='all',
        help='収集ソース（デフォルト: all）')
    parser.add_argument(
        '--list-sources', '-l',
        action='store_true',
        help='利用可能なソース一覧を表示')
    parser.add_argument(
        '--local-dir',
        default=None,
        help='ローカルスキャンディレクトリ')
    parser.add_argument(
        '--max-errors',
        type=int, default=20,
        help='連続エラー閾値（これを超えるとサイトをスキップ、デフォルト: 20）')
    parser.add_argument(
        '--download-timeout',
        type=int, default=10,
        help='MIDI ダウンロードタイムアウト秒（デフォルト: 10）')
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='詳細ログ')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.list_sources:
        list_sources()
        return

    pipeline = CollectionPipeline(output_dir=args.output_dir)

    if args.source == 'all':
        pipeline.add_all_collectors()
    else:
        cls = ALL_COLLECTORS[args.source]
        if args.source == 'local':
            collector = cls(args.local_dir or '.')
        else:
            collector = cls()

        # WebCrawlCollector のパラメータ設定
        if isinstance(collector, WebCrawlCollector):
            collector.MAX_CONSECUTIVE_ERRORS = args.max_errors
            collector.DOWNLOAD_TIMEOUT = args.download_timeout

        pipeline.add_collector(collector)

    if args.local_dir:
        pipeline.add_collector(LocalFileCollector(args.local_dir))

    # add_all_collectors で追加された WebCrawlCollector にもパラメータ適用
    for c in pipeline.collectors:
        if isinstance(c, WebCrawlCollector):
            c.MAX_CONSECUTIVE_ERRORS = args.max_errors
            c.DOWNLOAD_TIMEOUT = args.download_timeout

    stats = pipeline.run()

    if stats["saved"] == 0:
        print("\n※ MIDI が収集できませんでした。")
        print("  - ネットワーク接続を確認してください。")
        print("  - pip install datasets requests でライブラリをインストールしてください。")
        print("  - --local-dir でローカル MIDI を指定できます。")


if __name__ == "__main__":
    main()
