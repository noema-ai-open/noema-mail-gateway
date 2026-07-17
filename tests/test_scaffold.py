from noema_mail_gateway.domain import DraftReference, DraftStatus


def test_initial_domain_scaffold() -> None:
    draft = DraftReference(
        draft_id="draft-test-001",
        version=1,
        status=DraftStatus.CREATED,
    )

    assert draft.version == 1
    assert draft.status is DraftStatus.CREATED
