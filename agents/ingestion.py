"""
Agent 1: Ingestion
Fetches newsletters from Gmail, detects variants, routes to parsers, returns RawArticles.

Sender configuration is driven by config/senders.yaml (enabled: true/false).
Additional custom senders can be added via NEWSLETTER_SENDERS env var
(comma-separated email addresses) — these are routed to the generic parser.
"""
import base64
import email
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog
import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from models.article import RawArticle
from parsers.et_ai_parser import ETAIParser
from parsers.ettech_parser import ETtechParser
from parsers.generic_parser import GenericParser
from parsers.harper_carroll_parser import HarperCarrollParser
from parsers.techcrunch_parser import TechCrunchParser
from parsers.tldr_parser import TLDRParser

log = structlog.get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.modify",
]

NEWSFLOW_LABEL = "NewsFlow/Processed"

_SENDERS_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "senders.yaml")

# Parser instances by parser name (from senders.yaml `parser:` field)
_PARSER_INSTANCES = {
    "tldr": TLDRParser(),
    "techcrunch": TechCrunchParser(),
    "harper_carroll": HarperCarrollParser(),
    "ettech": ETtechParser(),
    "et_ai": ETAIParser(),
    "generic": GenericParser(),
}

_GENERIC_PARSER = GenericParser()


def _load_senders_config() -> dict:
    with open(_SENDERS_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def _build_gmail_query(senders_config: dict) -> str:
    """
    Build Gmail query from enabled senders in config + NEWSLETTER_SENDERS env var.
    Only includes unique email addresses (multiple sources can share an address, e.g. TLDR variants).
    """
    emails: set[str] = set()

    for sender in senders_config.get("senders", []):
        if sender.get("enabled", False):
            emails.add(sender["sender_email"].lower())

    extra = os.getenv("NEWSLETTER_SENDERS", "")
    for addr in extra.split(","):
        addr = addr.strip().lower()
        if addr and "@" in addr:
            emails.add(addr)

    if not emails:
        log.warning("no_senders_configured", hint="Set enabled: true in senders.yaml or NEWSLETTER_SENDERS in .env")
        return "newer_than:1d label:inbox"

    email_list = " OR ".join(sorted(emails))
    return f"from:({email_list}) newer_than:1d"


def _build_source_routing(senders_config: dict) -> dict:
    """
    Build routing table: sender_email → list of sender config entries.
    Multiple entries can share the same email (e.g. TLDR variants).
    Only includes enabled entries.
    """
    routing: dict[str, list[dict]] = {}
    for sender in senders_config.get("senders", []):
        if not sender.get("enabled", False):
            continue
        addr = sender["sender_email"].lower()
        routing.setdefault(addr, []).append(sender)
    return routing


class IngestionAgent:
    def __init__(self):
        self._service = None
        self._senders_config = _load_senders_config()
        self._gmail_query = _build_gmail_query(self._senders_config)
        self._source_routing = _build_source_routing(self._senders_config)
        self._excluded_variants = self._senders_config.get("excluded_variants", [])

        # Custom senders from env that are NOT in the YAML config → generic parser
        yaml_emails = {s["sender_email"].lower() for s in self._senders_config.get("senders", [])}
        extra = os.getenv("NEWSLETTER_SENDERS", "")
        self._custom_senders: set[str] = set()
        for addr in extra.split(","):
            addr = addr.strip().lower()
            if addr and "@" in addr and addr not in yaml_emails:
                self._custom_senders.add(addr)

        log.info(
            "ingestion_configured",
            gmail_query=self._gmail_query,
            custom_senders=sorted(self._custom_senders),
        )

    def run(self) -> list[RawArticle]:
        self._service = self._get_gmail_service()
        messages = self._fetch_messages()
        log.info("gmail_fetch_complete", message_count=len(messages))

        all_articles: list[RawArticle] = []
        processed_ids: list[str] = []

        for msg_id in messages:
            try:
                articles, email_id = self._process_message(msg_id)
                all_articles.extend(articles)
                if email_id:
                    processed_ids.append(email_id)
            except Exception as e:
                log.error("message_processing_failed", msg_id=msg_id, error=str(e))

        # Deduplicate by exact URL
        seen_urls: set[str] = set()
        deduped: list[RawArticle] = []
        for article in all_articles:
            url_str = str(article.url)
            if url_str not in seen_urls:
                seen_urls.add(url_str)
                deduped.append(article)

        log.info(
            "ingestion_complete",
            raw_count=len(all_articles),
            deduped_count=len(deduped),
        )

        if processed_ids:
            self._label_messages(processed_ids)

        return deduped

    def _get_gmail_service(self):
        creds_path = os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")
        token_path = os.environ.get("GMAIL_TOKEN_PATH", "token.json")

        creds = None
        if Path(token_path).exists():
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            Path(token_path).write_text(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    def _fetch_messages(self) -> list[str]:
        """Fetch message IDs matching the Gmail query with exponential backoff."""
        messages = []
        page_token = None
        retries = 0

        while True:
            try:
                kwargs = {"userId": "me", "q": self._gmail_query, "maxResults": 50}
                if page_token:
                    kwargs["pageToken"] = page_token

                result = self._service.users().messages().list(**kwargs).execute()
                messages.extend([m["id"] for m in result.get("messages", [])])

                page_token = result.get("nextPageToken")
                if not page_token:
                    break
                retries = 0

            except HttpError as e:
                if e.resp.status == 429 and retries < 3:
                    wait = 2 ** retries
                    log.warning("gmail_rate_limited", retry_in_sec=wait)
                    time.sleep(wait)
                    retries += 1
                else:
                    raise

        return messages

    def _process_message(self, msg_id: str) -> tuple[list[RawArticle], str | None]:
        """Fetch a single message, detect source, parse into RawArticles."""
        msg = self._service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        from_raw = headers.get("From", "")
        subject = headers.get("Subject", "")
        date_str = headers.get("Date", "")

        sender_email, from_display_name = self._parse_from_header(from_raw)
        timestamp = self._parse_date(date_str)
        newsletter_date = timestamp.strftime("%Y-%m-%d")

        source_id, parser = self._detect_source_and_parser(
            sender_email, from_display_name, subject
        )

        if source_id is None or parser is None:
            log.debug("email_skipped", from_raw=from_raw, subject=subject)
            return [], None

        body = self._extract_body(msg["payload"], source_id)
        if not body:
            log.warning("empty_body", msg_id=msg_id, source_id=source_id)
            return [], None

        email_metadata = {
            "source_id": source_id,
            "sender_email": sender_email,
            "timestamp": timestamp,
            "newsletter_date": newsletter_date,
        }

        articles = parser.parse(body, email_metadata)
        log.info(
            "email_parsed",
            source_id=source_id,
            subject=subject,
            article_count=len(articles),
        )
        return articles, msg_id

    def _detect_source_and_parser(
        self, sender_email: str, from_display_name: str, subject: str
    ) -> tuple[str | None, object | None]:
        """
        Route email to (source_id, parser) using config-driven routing table.
        Returns (None, None) to skip the email.
        """
        # Custom senders (from NEWSLETTER_SENDERS env, not in YAML config)
        if sender_email in self._custom_senders:
            log.debug("custom_sender_routed", sender=sender_email)
            return "custom", _GENERIC_PARSER

        # Check excluded variant patterns before any routing
        if self._is_excluded_variant(sender_email, from_display_name):
            return None, None

        sender_entries = self._source_routing.get(sender_email, [])
        if not sender_entries:
            return None, None

        for entry in sender_entries:
            detection = entry.get("variant_detection", "none")

            if detection == "none":
                parser = _PARSER_INSTANCES.get(entry.get("parser", "generic"), _GENERIC_PARSER)
                return entry["id"], parser

            elif detection == "from_display_name":
                match_str = entry.get("display_name_match", "")
                subject_prefix = entry.get("subject_prefix", "")
                if match_str.upper() in from_display_name.upper():
                    parser = _PARSER_INSTANCES.get(entry.get("parser", "generic"), _GENERIC_PARSER)
                    return entry["id"], parser
                if subject_prefix and subject.startswith(subject_prefix):
                    parser = _PARSER_INSTANCES.get(entry.get("parser", "generic"), _GENERIC_PARSER)
                    return entry["id"], parser

            elif detection == "subject_filter":
                keywords = [kw.lower() for kw in entry.get("subject_keywords", [])]
                if any(kw in subject.lower() for kw in keywords):
                    parser = _PARSER_INSTANCES.get(entry.get("parser", "generic"), _GENERIC_PARSER)
                    return entry["id"], parser

        return None, None

    def _is_excluded_variant(self, sender_email: str, from_display_name: str) -> bool:
        """Check if this email matches a known excluded variant."""
        for rule in self._excluded_variants:
            if rule.get("sender", "").lower() != sender_email:
                continue
            for pattern in rule.get("patterns", []):
                if pattern.upper() in from_display_name.upper():
                    return True
            for excl in rule.get("exclude_display_names", []):
                if excl.lower() in from_display_name.lower():
                    return True
        return False

    def _extract_body(self, payload: dict, source_id: str) -> str | None:
        """
        Extract the correct body part:
        - TLDR: text/plain (well-structured plain text)
        - All others: text/html
        """
        want_plain = source_id.startswith("tldr_")
        mime_pref = "text/plain" if want_plain else "text/html"
        fallback_mime = "text/html" if want_plain else "text/plain"

        parts = self._collect_parts(payload)

        for mime, data in parts:
            if mime == mime_pref:
                return self._decode_part(data)

        for mime, data in parts:
            if mime == fallback_mime:
                return self._decode_part(data)

        return None

    def _collect_parts(self, payload: dict) -> list[tuple[str, str]]:
        """Recursively collect (mimeType, body_data) pairs from message payload."""
        results = []
        mime = payload.get("mimeType", "")

        if mime in ("text/plain", "text/html"):
            body_data = payload.get("body", {}).get("data", "")
            if body_data:
                results.append((mime, body_data))

        for part in payload.get("parts", []):
            results.extend(self._collect_parts(part))

        return results

    def _decode_part(self, data: str) -> str:
        """Decode base64url-encoded email body."""
        try:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _parse_from_header(self, from_raw: str) -> tuple[str, str]:
        """Parse 'Display Name <email@example.com>' into (email, display_name)."""
        if "<" in from_raw and ">" in from_raw:
            display_name = from_raw.split("<")[0].strip().strip('"')
            sender_email = from_raw.split("<")[1].split(">")[0].strip().lower()
        else:
            sender_email = from_raw.strip().lower()
            display_name = sender_email
        return sender_email, display_name

    def _parse_date(self, date_str: str) -> datetime:
        """Parse email Date header into UTC datetime."""
        try:
            parsed = email.utils.parsedate_to_datetime(date_str)
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            return datetime.utcnow()

    def _label_messages(self, msg_ids: list[str]) -> None:
        """Apply 'NewsFlow/Processed' label to processed emails."""
        try:
            label_id = self._get_or_create_label(NEWSFLOW_LABEL)
            for msg_id in msg_ids:
                self._service.users().messages().modify(
                    userId="me",
                    id=msg_id,
                    body={"addLabelIds": [label_id]},
                ).execute()
        except Exception as e:
            log.warning("label_apply_failed", error=str(e))

    def _get_or_create_label(self, label_name: str) -> str:
        """Get label ID, creating it if it doesn't exist."""
        result = self._service.users().labels().list(userId="me").execute()
        for label in result.get("labels", []):
            if label["name"] == label_name:
                return label["id"]

        new_label = (
            self._service.users()
            .labels()
            .create(userId="me", body={"name": label_name})
            .execute()
        )
        return new_label["id"]
