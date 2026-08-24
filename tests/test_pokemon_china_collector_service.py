
from __future__ import annotations

from pathlib import Path

from rareiq.services.pokemon_china_collector_service import (
    PokemonChinaCollectorService,
    _PageParser,
)


def make_service(
    tmp_path: Path,
) -> PokemonChinaCollectorService:
    return PokemonChinaCollectorService(
        project_root=tmp_path,
    )


def test_archive_page_one_url(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert (
        service._archive_url(1)
        == "https://www.pokemon.cn/tcg"
    )


def test_archive_page_later_url(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert (
        service._archive_url(3)
        == "https://www.pokemon.cn/tcg/p/3"
    )


def test_normalize_relative_url(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert (
        service._normalize_url(
            "/tcg/product/123.html",
            "https://www.pokemon.cn/tcg",
        )
        == (
            "https://www.pokemon.cn/"
            "tcg/product/123.html"
        )
    )


def test_normalize_protocol_relative_url(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert (
        service._normalize_url(
            "//image.pokemon.com.cn/card.png",
            "https://www.pokemon.cn/tcg",
        )
        == (
            "https://image.pokemon.com.cn/"
            "card.png"
        )
    )


def test_accepts_product_article_url(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert service._is_article_url(
        "https://www.pokemon.cn/tcg/product/20012.html"
    )


def test_rejects_archive_page_url(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert not service._is_article_url(
        "https://www.pokemon.cn/tcg/p/2"
    )


def test_accepts_official_image_url(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert service._is_image_url(
        (
            "https://image.pokemon.com.cn/"
            "wp-content/uploads/card.webp"
        )
    )


def test_rejects_external_image_url(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert not service._is_image_url(
        "https://example.com/card.webp"
    )


def test_extracts_article_links(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    html = """
    <html>
      <body>
        <a href="/tcg/product/123.html">
          Product Test
        </a>
        <a href="/tcg/p/2">
          Next page
        </a>
      </body>
    </html>
    """

    links = service._extract_article_links(
        html,
        "https://www.pokemon.cn/tcg",
    )

    assert len(links) == 1

    assert (
        links[0]["url"]
        == (
            "https://www.pokemon.cn/"
            "tcg/product/123.html"
        )
    )


def test_extracts_image_sources(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    html = """
    <html>
      <body>
        <img
          src="//image.pokemon.com.cn/card.webp"
          alt="Greninja"
        />
        <img
          src="https://example.com/not-official.webp"
        />
      </body>
    </html>
    """

    images = service._extract_images(
        html,
        "https://www.pokemon.cn/tcg/product/123.html",
    )

    assert len(images) == 1

    assert (
        images[0]["url"]
        == (
            "https://image.pokemon.com.cn/"
            "card.webp"
        )
    )


def test_srcset_uses_largest_width() -> None:
    parser = _PageParser()

    value = (
        "small.webp 320w, "
        "medium.webp 640w, "
        "large.webp 1280w"
    )

    assert (
        parser._best_srcset_url(
            value
        )
        == "large.webp"
    )


def test_safe_filename(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert (
        service._safe_filename(
            "tcg/product:123?"
        )
        == "tcg_product_123"
    )


def test_extracts_chinese_date(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert (
        service._extract_date(
            "发布日期：2026年7月14日"
        )
        == "2026年7月14日"
    )


def test_article_id_from_url(
    tmp_path: Path,
) -> None:
    service = make_service(
        tmp_path
    )

    assert (
        service._article_id(
            "https://www.pokemon.cn/tcg/product/20012.html"
        )
        == "tcg_product_20012.html"
    )
