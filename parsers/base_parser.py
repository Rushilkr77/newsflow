from abc import ABC, abstractmethod
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from models.article import RawArticle


class BaseParser(ABC):
    @abstractmethod
    def parse(self, email_body: str, email_metadata: dict) -> list[RawArticle]:
        pass

    def _clean_url(self, url: str) -> str:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        clean_params = {k: v for k, v in params.items() if not k.startswith("utm_")}
        clean_query = urlencode(clean_params, doseq=True)
        return urlunparse(parsed._replace(query=clean_query))
