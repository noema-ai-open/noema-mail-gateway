from email.message import EmailMessage

from noema_mail_gateway.mailparse import MAX_BODY_SIZE, parse_message


def test_multipart_parser_retains_bounded_bodies_and_attachment_metadata() -> None:
    attachment = b"binary attachment"
    raw = EmailMessage()
    raw["From"] = "Sender <sender@example.test>"
    raw["Message-ID"] = "<multipart@example.test>"
    raw["Subject"] = "Multipart"
    raw.set_content("plain body")
    raw.add_alternative("<p>&#0; remains encoded</p>", subtype="html")
    raw.add_attachment(
        attachment,
        maintype="application",
        subtype="octet-stream",
        filename="../../evidence.bin",
    )

    parsed = parse_message("42", raw.as_bytes())

    assert parsed.body_text == "plain body\n"
    assert parsed.body_html == "<p>&#0; remains encoded</p>\n"
    assert parsed.attachment_meta[0].filename == "evidence.bin"
    assert parsed.attachment_meta[0].mime_type == "application/octet-stream"
    assert parsed.attachment_meta[0].size == len(attachment)
    assert not hasattr(parsed.attachment_meta[0], "content")


def test_body_limit_is_applied_separately_to_plain_and_html() -> None:
    raw = EmailMessage()
    raw["Message-ID"] = "<large@example.test>"
    raw["Subject"] = "Large"
    raw.set_content("x" * (MAX_BODY_SIZE + 100))
    raw.add_alternative("y" * (MAX_BODY_SIZE + 100), subtype="html")

    parsed = parse_message("1", raw.as_bytes())

    assert len(parsed.body_text.encode()) == MAX_BODY_SIZE
    assert parsed.body_html is not None
    assert len(parsed.body_html.encode()) == MAX_BODY_SIZE
    assert parsed.truncated is True


def test_untrusted_headers_are_decoded_cleaned_and_capped() -> None:
    raw = (
        b"From: =?utf-8?q?M=C3=BCller?= <sender@example.test>\r\n"
        b"Message-ID: <header@example.test>\r\n"
        + b"Subject: safe\x00"
        + b"z" * 1100
        + b"\r\n\r\nbody"
    )

    parsed = parse_message("7", raw)

    assert parsed.summary.from_addr == "Müller <sender@example.test>"
    assert "\x00" not in parsed.summary.subject
    assert len(parsed.summary.subject) == 1024
