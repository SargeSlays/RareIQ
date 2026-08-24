
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import httpx


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()

        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []

        self._current_link: dict[str, str] | None = None
        self._current_text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {
            key: value or ""
            for key, value in attrs
        }

        if tag.lower() == "a":
            href = attributes.get("href", "").strip()

            if href:
                self._current_link = {
                    "href": href,
                    "title": attributes.get("title", "").strip(),
                    "class": attributes.get("class", "").strip(),
                }

                self._current_text = []

        if tag.lower() == "img":
            source = (
                attributes.get("src")
                or attributes.get("data-src")
                or attributes.get("data-original")
                or attributes.get("data-lazy-src")
                or ""
            ).strip()

            source_set = (
                attributes.get("srcset")
                or attributes.get("data-srcset")
                or ""
            ).strip()

            if not source and source_set:
                source = self._best_srcset_url(
                    source_set
                )

            if source:
                self.images.append({
                    "src": source,
                    "alt": attributes.get("alt", "").strip(),
                    "title": attributes.get("title", "").strip(),
                    "class": attributes.get("class", "").strip(),
                })

    def handle_data(
        self,
        data: str,
    ) -> None:
        if self._current_link is None:
            return

        value = data.strip()

        if value:
            self._current_text.append(value)

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        if tag.lower() != "a":
            return

        if self._current_link is None:
            return

        item = dict(self._current_link)
        item["text"] = " ".join(
            self._current_text
        ).strip()

        self.links.append(item)

        self._current_link = None
        self._current_text = []

    @staticmethod
    def _best_srcset_url(
        value: str,
    ) -> str:
        candidates: list[tuple[int, str]] = []

        for item in value.split(","):
            part = item.strip()

            if not part:
                continue

            pieces = part.split()

            url = pieces[0]
            width = 0

            if len(pieces) > 1:
                descriptor = pieces[-1]

                match = re.match(
                    r"(\d+)w",
                    descriptor,
                )

                if match:
                    width = int(
                        match.group(1)
                    )

            candidates.append(
                (
                    width,
                    url,
                )
            )

        if not candidates:
            return ""

        candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        return candidates[0][1]


class PokemonChinaCollectorService:
    BASE_URL = "https://www.pokemon.cn"
    ARCHIVE_URL = "https://www.pokemon.cn/tcg"
    ARCHIVE_PAGE_URL = (
        "https://www.pokemon.cn/tcg/p/{page}"
    )

    PRODUCT_PATH_MARKERS = (
        "/tcg/product/",
        "/tcg/news/",
        "/tcg/",
    )

    IMAGE_HOST_MARKERS = (
        "pokemon.com.cn",
        "pokemon.cn",
    )

    IMAGE_EXTENSIONS = (
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
    )

    def __init__(
        self,
        project_root: Path,
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.project_root = Path(
            project_root
        )

        self.emit = emit or (
            lambda payload: None
        )

        self.root = (
            self.project_root
            / "catalog_master"
            / "simplified_chinese"
        )

        self.html_root = (
            self.root
            / "html"
        )

        self.images_root = (
            self.root
            / "images"
            / "official"
        )

        self.archive_path = (
            self.root
            / "official_articles.json"
        )

        self.image_manifest_path = (
            self.root
            / "image_manifest.json"
        )

        self.manifest_path = (
            self.root
            / "manifest.json"
        )

        self.state_path = (
            self.root
            / "collector_state.json"
        )

        for path in (
            self.root,
            self.html_root,
            self.images_root,
        ):
            path.mkdir(
                parents=True,
                exist_ok=True,
            )

        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._cancel = threading.Event()

        self._status: dict[str, Any] = {
            "busy": False,
            "phase": "IDLE",
            "archive_pages_requested": 0,
            "archive_pages_completed": 0,
            "articles_discovered": 0,
            "articles_processed": 0,
            "images_discovered": 0,
            "images_downloaded": 0,
            "images_existing": 0,
            "images_failed": 0,
            "duplicate_images": 0,
            "current_archive_page": None,
            "current_article": None,
            "current_image": None,
            "started_at": None,
            "updated_at": time.time(),
            "error": None,
            "errors": [],
        }

        self._load_existing_manifest()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(
                self._status
            )

    def _set_status(
        self,
        **values: Any,
    ) -> None:
        with self._lock:
            self._status.update(
                values
            )

            self._status[
                "updated_at"
            ] = time.time()

            payload = dict(
                self._status
            )

        self.emit({
            "type": (
                "pokemon_china_collector_status"
            ),
            "payload": payload,
        })

    def _load_existing_manifest(
        self,
    ) -> None:
        if not self.manifest_path.exists():
            return

        try:
            payload = json.loads(
                self.manifest_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return

        with self._lock:
            self._status.update({
                "phase": "READY",
                "archive_pages_completed": int(
                    payload.get(
                        "archive_pages_completed"
                    )
                    or 0
                ),
                "articles_discovered": int(
                    payload.get(
                        "articles_discovered"
                    )
                    or 0
                ),
                "articles_processed": int(
                    payload.get(
                        "articles_processed"
                    )
                    or 0
                ),
                "images_discovered": int(
                    payload.get(
                        "images_discovered"
                    )
                    or 0
                ),
                "images_downloaded": int(
                    payload.get(
                        "images_downloaded"
                    )
                    or 0
                ),
                "images_existing": int(
                    payload.get(
                        "images_existing"
                    )
                    or 0
                ),
                "images_failed": int(
                    payload.get(
                        "images_failed"
                    )
                    or 0
                ),
                "duplicate_images": int(
                    payload.get(
                        "duplicate_images"
                    )
                    or 0
                ),
            })

    @staticmethod
    def _safe_filename(
        value: Any,
    ) -> str:
        cleaned = "".join(
            character
            if character.isalnum()
            or character in "-_."
            else "_"
            for character in str(
                value or ""
            )
        )

        return (
            cleaned.strip("._")
            or "item"
        )

    @staticmethod
    def _sha256_bytes(
        payload: bytes,
    ) -> str:
        return hashlib.sha256(
            payload
        ).hexdigest()

    @staticmethod
    def _sha256_file(
        path: Path,
    ) -> str | None:
        try:
            digest = hashlib.sha256()

            with path.open(
                "rb"
            ) as handle:
                while True:
                    chunk = handle.read(
                        1024 * 1024
                    )

                    if not chunk:
                        break

                    digest.update(
                        chunk
                    )

            return digest.hexdigest()
        except Exception:
            return None

    @staticmethod
    def _read_json(
        path: Path,
        default: Any,
    ) -> Any:
        if not path.exists():
            return default

        try:
            return json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return default

    @staticmethod
    def _write_json(
        path: Path,
        payload: Any,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def _archive_url(
        cls,
        page: int,
    ) -> str:
        if page <= 1:
            return cls.ARCHIVE_URL

        return cls.ARCHIVE_PAGE_URL.format(
            page=page
        )

    @classmethod
    def _normalize_url(
        cls,
        url: str,
        base_url: str,
    ) -> str:
        value = str(
            url or ""
        ).strip()

        if not value:
            return ""

        if value.startswith("//"):
            return f"https:{value}"

        return urljoin(
            base_url,
            value,
        )

    @classmethod
    def _is_article_url(
        cls,
        url: str,
    ) -> bool:
        parsed = urlparse(
            url
        )

        if "pokemon.cn" not in parsed.netloc:
            return False

        path = parsed.path.lower()

        if path.rstrip("/") in (
            "/tcg",
            "/tcg/p",
        ):
            return False

        if "/tcg/p/" in path:
            return False

        return any(
            marker in path
            for marker in cls.PRODUCT_PATH_MARKERS
        )

    @classmethod
    def _is_image_url(
        cls,
        url: str,
    ) -> bool:
        parsed = urlparse(
            url
        )

        host = parsed.netloc.lower()
        path = parsed.path.lower()

        if not any(
            marker in host
            for marker in cls.IMAGE_HOST_MARKERS
        ):
            return False

        return path.endswith(
            cls.IMAGE_EXTENSIONS
        )

    @staticmethod
    def _extract_date(
        text: str,
    ) -> str | None:
        patterns = (
            r"20\d{2}[./\-年]\d{1,2}[./\-月]\d{1,2}日?",
            r"\d{4}-\d{2}-\d{2}",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
            )

            if match:
                return match.group(0)

        return None

    def _parse_page(
        self,
        html: str,
    ) -> _PageParser:
        parser = _PageParser()
        parser.feed(
            html
        )

        return parser

    def _extract_article_links(
        self,
        html: str,
        page_url: str,
    ) -> list[dict[str, Any]]:
        parser = self._parse_page(
            html
        )

        results: list[
            dict[str, Any]
        ] = []

        seen: set[str] = set()

        for item in parser.links:
            url = self._normalize_url(
                item.get(
                    "href",
                    "",
                ),
                page_url,
            )

            if not url:
                continue

            url = url.split(
                "#",
                1,
            )[0]

            if not self._is_article_url(
                url
            ):
                continue

            if url in seen:
                continue

            seen.add(
                url
            )

            combined = " ".join(
                (
                    item.get(
                        "text",
                        "",
                    ),
                    item.get(
                        "title",
                        "",
                    ),
                )
            ).strip()

            results.append({
                "url": url,
                "title": (
                    item.get(
                        "text"
                    )
                    or item.get(
                        "title"
                    )
                    or url
                ),
                "archive_date": (
                    self._extract_date(
                        combined
                    )
                ),
                "archive_page_url": (
                    page_url
                ),
            })

        return results

    def _extract_images(
        self,
        html: str,
        article_url: str,
    ) -> list[dict[str, Any]]:
        parser = self._parse_page(
            html
        )

        results: list[
            dict[str, Any]
        ] = []

        seen: set[str] = set()

        for item in parser.images:
            url = self._normalize_url(
                item.get(
                    "src",
                    "",
                ),
                article_url,
            )

            if not url:
                continue

            if not self._is_image_url(
                url
            ):
                continue

            if url in seen:
                continue

            seen.add(
                url
            )

            results.append({
                "url": url,
                "alt": item.get(
                    "alt",
                    "",
                ),
                "title": item.get(
                    "title",
                    "",
                ),
                "class": item.get(
                    "class",
                    "",
                ),
            })

        return results

    def _article_id(
        self,
        url: str,
    ) -> str:
        parsed = urlparse(
            url
        )

        path = parsed.path.strip(
            "/"
        )

        return self._safe_filename(
            path.replace(
                "/",
                "_",
            )
        )

    def _image_extension(
        self,
        url: str,
        content_type: str,
    ) -> str:
        parsed = urlparse(
            url
        )

        suffix = Path(
            parsed.path
        ).suffix.lower()

        if suffix in self.IMAGE_EXTENSIONS:
            return suffix

        lowered = content_type.lower()

        if "png" in lowered:
            return ".png"

        if "webp" in lowered:
            return ".webp"

        if "gif" in lowered:
            return ".gif"

        return ".jpg"

    def discover_articles(
        self,
        *,
        pages: int,
        client: httpx.Client,
    ) -> list[dict[str, Any]]:
        articles_by_url: dict[
            str,
            dict[str, Any],
        ] = {}

        errors = list(
            self._status.get(
                "errors"
            )
            or []
        )

        for page in range(
            1,
            pages + 1,
        ):
            if self._cancel.is_set():
                break

            archive_url = (
                self._archive_url(
                    page
                )
            )

            self._set_status(
                phase="DISCOVERING",
                current_archive_page=page,
            )

            try:
                response = client.get(
                    archive_url
                )

                response.raise_for_status()

                html = response.text

                archive_html_path = (
                    self.html_root
                    / "archive"
                    / f"page_{page:03d}.html"
                )

                archive_html_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                archive_html_path.write_text(
                    html,
                    encoding="utf-8",
                )

                discovered = (
                    self._extract_article_links(
                        html,
                        archive_url,
                    )
                )

                for article in discovered:
                    articles_by_url[
                        article["url"]
                    ] = article

                self._set_status(
                    archive_pages_completed=page,
                    articles_discovered=len(
                        articles_by_url
                    ),
                )

            except Exception as exc:
                errors.append(
                    (
                        f"archive page {page}: "
                        f"{exc}"
                    )
                )

                self._set_status(
                    errors=errors[-200:],
                )

        articles = sorted(
            articles_by_url.values(),
            key=lambda item: (
                str(
                    item.get(
                        "archive_date"
                    )
                    or ""
                ),
                str(
                    item.get(
                        "url"
                    )
                    or ""
                ),
            ),
            reverse=True,
        )

        self._write_json(
            self.archive_path,
            articles,
        )

        return articles

    def _download_image(
        self,
        *,
        client: httpx.Client,
        article_id: str,
        image_url: str,
        known_hashes: dict[str, str],
    ) -> dict[str, Any]:
        url_hash = hashlib.sha256(
            image_url.encode(
                "utf-8"
            )
        ).hexdigest()[:16]

        article_dir = (
            self.images_root
            / article_id
        )

        article_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        existing_matches = list(
            article_dir.glob(
                f"{url_hash}.*"
            )
        )

        for existing_path in existing_matches:
            checksum = self._sha256_file(
                existing_path
            )

            if checksum:
                return {
                    "ok": True,
                    "state": "existing",
                    "path": str(
                        existing_path
                    ),
                    "checksum": checksum,
                    "content_type": None,
                    "size_bytes": (
                        existing_path.stat().st_size
                    ),
                }

        response = client.get(
            image_url
        )

        response.raise_for_status()

        payload = response.content

        if len(payload) < 256:
            raise RuntimeError(
                "Downloaded image payload "
                "was unexpectedly small."
            )

        content_type = response.headers.get(
            "content-type",
            "",
        )

        extension = (
            self._image_extension(
                image_url,
                content_type,
            )
        )

        checksum = self._sha256_bytes(
            payload
        )

        duplicate_path = known_hashes.get(
            checksum
        )

        if duplicate_path:
            return {
                "ok": True,
                "state": "duplicate",
                "path": duplicate_path,
                "checksum": checksum,
                "content_type": content_type,
                "size_bytes": len(
                    payload
                ),
            }

        image_path = (
            article_dir
            / f"{url_hash}{extension}"
        )

        image_path.write_bytes(
            payload
        )

        known_hashes[
            checksum
        ] = str(
            image_path
        )

        return {
            "ok": True,
            "state": "downloaded",
            "path": str(
                image_path
            ),
            "checksum": checksum,
            "content_type": content_type,
            "size_bytes": len(
                payload
            ),
        }

    def build(
        self,
        *,
        pages: int = 2,
        article_limit: int | None = None,
    ) -> dict[str, Any]:
        self._cancel.clear()

        started_at = time.time()

        self._set_status(
            busy=True,
            phase="STARTING",
            archive_pages_requested=pages,
            archive_pages_completed=0,
            articles_discovered=0,
            articles_processed=0,
            images_discovered=0,
            images_downloaded=0,
            images_existing=0,
            images_failed=0,
            duplicate_images=0,
            current_archive_page=None,
            current_article=None,
            current_image=None,
            started_at=started_at,
            error=None,
            errors=[],
        )

        errors: list[str] = []

        image_manifest = self._read_json(
            self.image_manifest_path,
            [],
        )

        if not isinstance(
            image_manifest,
            list,
        ):
            image_manifest = []

        known_hashes: dict[
            str,
            str,
        ] = {}

        for item in image_manifest:
            checksum = item.get(
                "checksum"
            )

            path = item.get(
                "local_path"
            )

            if checksum and path:
                known_hashes[
                    str(checksum)
                ] = str(path)

        processed_urls = {
            str(
                item.get(
                    "source_url"
                )
            )
            for item in image_manifest
            if item.get(
                "source_url"
            )
        }

        downloaded = 0
        existing = 0
        failed = 0
        duplicates = 0
        images_discovered = 0
        articles_processed = 0

        try:
            with httpx.Client(
                timeout=httpx.Timeout(
                    45.0,
                    connect=12.0,
                ),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "RareIQ/6.4.10.1 "
                        "PokemonChinaCollector"
                    ),
                    "Accept": (
                        "text/html,"
                        "application/xhtml+xml,"
                        "image/avif,"
                        "image/webp,"
                        "image/apng,"
                        "image/*,*/*;q=0.8"
                    ),
                },
            ) as client:
                articles = (
                    self.discover_articles(
                        pages=max(
                            1,
                            int(pages),
                        ),
                        client=client,
                    )
                )

                if article_limit is not None:
                    articles = articles[
                        :max(
                            0,
                            int(article_limit),
                        )
                    ]

                for article in articles:
                    if self._cancel.is_set():
                        break

                    article_url = str(
                        article.get(
                            "url"
                        )
                        or ""
                    )

                    if not article_url:
                        continue

                    article_id = (
                        self._article_id(
                            article_url
                        )
                    )

                    self._set_status(
                        phase="PROCESSING_ARTICLES",
                        current_article=article_url,
                    )

                    try:
                        response = client.get(
                            article_url
                        )

                        response.raise_for_status()

                        html = response.text

                        html_path = (
                            self.html_root
                            / "articles"
                            / f"{article_id}.html"
                        )

                        html_path.parent.mkdir(
                            parents=True,
                            exist_ok=True,
                        )

                        html_path.write_text(
                            html,
                            encoding="utf-8",
                        )

                        images = self._extract_images(
                            html,
                            article_url,
                        )

                        article[
                            "article_id"
                        ] = article_id

                        article[
                            "html_path"
                        ] = str(
                            html_path
                        )

                        article[
                            "images_discovered"
                        ] = len(
                            images
                        )

                        images_discovered += len(
                            images
                        )

                        for image in images:
                            if self._cancel.is_set():
                                break

                            image_url = str(
                                image.get(
                                    "url"
                                )
                                or ""
                            )

                            if not image_url:
                                continue

                            self._set_status(
                                current_image=image_url,
                                images_discovered=(
                                    images_discovered
                                ),
                            )

                            if image_url in processed_urls:
                                existing += 1
                                continue

                            try:
                                result = (
                                    self._download_image(
                                        client=client,
                                        article_id=article_id,
                                        image_url=image_url,
                                        known_hashes=known_hashes,
                                    )
                                )

                                state = result.get(
                                    "state"
                                )

                                if state == "downloaded":
                                    downloaded += 1

                                elif state == "existing":
                                    existing += 1

                                elif state == "duplicate":
                                    duplicates += 1

                                record = {
                                    "source_url": image_url,
                                    "source_article_url": (
                                        article_url
                                    ),
                                    "source_article_title": (
                                        article.get(
                                            "title"
                                        )
                                    ),
                                    "source_archive_date": (
                                        article.get(
                                            "archive_date"
                                        )
                                    ),
                                    "alt": image.get(
                                        "alt"
                                    ),
                                    "title": image.get(
                                        "title"
                                    ),
                                    "local_path": result.get(
                                        "path"
                                    ),
                                    "checksum": result.get(
                                        "checksum"
                                    ),
                                    "content_type": result.get(
                                        "content_type"
                                    ),
                                    "size_bytes": result.get(
                                        "size_bytes"
                                    ),
                                    "state": state,
                                    "downloaded_at": time.time(),
                                }

                                image_manifest.append(
                                    record
                                )

                                processed_urls.add(
                                    image_url
                                )

                            except Exception as exc:
                                failed += 1

                                errors.append(
                                    (
                                        f"{article_url} | "
                                        f"{image_url}: {exc}"
                                    )
                                )

                            self._set_status(
                                images_downloaded=downloaded,
                                images_existing=existing,
                                images_failed=failed,
                                duplicate_images=duplicates,
                                errors=errors[-200:],
                            )

                        articles_processed += 1

                        self._set_status(
                            articles_processed=(
                                articles_processed
                            ),
                        )

                        self._write_json(
                            self.archive_path,
                            articles,
                        )

                        self._write_json(
                            self.image_manifest_path,
                            image_manifest,
                        )

                    except Exception as exc:
                        errors.append(
                            (
                                f"article "
                                f"{article_url}: {exc}"
                            )
                        )

                        self._set_status(
                            errors=errors[-200:],
                        )

            phase = (
                "CANCELED"
                if self._cancel.is_set()
                else "READY"
            )

            manifest = {
                "catalog_format": (
                    "RareIQ Pokemon China "
                    "Official Asset Archive v1"
                ),
                "source": (
                    "https://www.pokemon.cn/tcg"
                ),
                "archive_pages_requested": (
                    pages
                ),
                "archive_pages_completed": (
                    self._status.get(
                        "archive_pages_completed"
                    )
                ),
                "articles_discovered": len(
                    articles
                ),
                "articles_processed": (
                    articles_processed
                ),
                "images_discovered": (
                    images_discovered
                ),
                "images_downloaded": (
                    downloaded
                ),
                "images_existing": (
                    existing
                ),
                "images_failed": failed,
                "duplicate_images": (
                    duplicates
                ),
                "image_manifest_records": len(
                    image_manifest
                ),
                "canceled": (
                    self._cancel.is_set()
                ),
                "built_at": time.time(),
                "duration_seconds": round(
                    time.time()
                    - started_at,
                    2,
                ),
                "errors": errors[-500:],
            }

            self._write_json(
                self.manifest_path,
                manifest,
            )

            self._write_json(
                self.image_manifest_path,
                image_manifest,
            )

            self._set_status(
                busy=False,
                phase=phase,
                articles_discovered=len(
                    articles
                ),
                articles_processed=(
                    articles_processed
                ),
                images_discovered=(
                    images_discovered
                ),
                images_downloaded=(
                    downloaded
                ),
                images_existing=existing,
                images_failed=failed,
                duplicate_images=duplicates,
                current_archive_page=None,
                current_article=None,
                current_image=None,
                errors=errors[-200:],
                error=None,
            )

            return {
                "ok": True,
                "manifest": manifest,
                "root": str(
                    self.root
                ),
                "articles_path": str(
                    self.archive_path
                ),
                "image_manifest_path": str(
                    self.image_manifest_path
                ),
            }

        except Exception as exc:
            self._set_status(
                busy=False,
                phase="FAILED",
                current_archive_page=None,
                current_article=None,
                current_image=None,
                error=str(exc),
                errors=errors[-200:],
            )

            return {
                "ok": False,
                "error": str(
                    exc
                ),
            }

    def start_build(
        self,
        *,
        pages: int = 2,
        article_limit: int | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._status.get(
                "busy"
            ):
                return {
                    "ok": False,
                    "error": (
                        "Pokémon China collector "
                        "is already running."
                    ),
                }

        self._cancel.clear()

        self._worker = threading.Thread(
            target=self.build,
            kwargs={
                "pages": pages,
                "article_limit": article_limit,
            },
            daemon=True,
            name=(
                "RareIQPokemonChinaCollector"
            ),
        )

        self._worker.start()

        return {
            "ok": True,
            "status": self.status(),
        }

    def cancel(
        self,
    ) -> dict[str, Any]:
        self._cancel.set()

        self._set_status(
            phase="CANCELING"
        )

        return {
            "ok": True
        }
