from bs4 import BeautifulSoup


def soup(html: str) -> BeautifulSoup:
    """Parse `html` with the html.parser backend — shared by every ingestion
    test module that builds/inspects a BeautifulSoup tree."""
    return BeautifulSoup(html, "html.parser")
